"""Answer a business question from the approved reporting views (`make ask Q="..."`).

Flow for one question:
1. The model sees the question and the list of approved queries (assistant/queries.py).
2. Each query it asks for is checked and run as ai_reader (read-only, ai views only, 5 s limit).
   Bad arguments go back to the model as an error it can correct.
3. The model writes a short answer from the results.
4. Every number in the answer must match a result (assistant/grounding.py). If one doesn't, the
   model gets one chance to rewrite without it; after that the plain results are shown instead.
5. The question, queries, answer and check result are written to ops.assistant_log.

Demo data only. The assistant has no tool that changes data.
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from assistant import grounding
from assistant.llm import LLM, LLMError, ToolCall, get_llm
from assistant.queries import BY_NAME, MAX_ROWS, QUERIES, InvalidArguments
from shared.config import Settings
from shared.logging import get_logger, new_run_id

MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = """\
You are the reporting assistant for Bluefield Supply Co., a fictional US distributor of cleaning,
paper, packaging and safety supplies. All of its data is demo data.

Answer questions about its sales, customers, receivables, suppliers and stock using ONLY the
results of the tools you are given.

Rules:
- Always call a tool to get figures. Never answer from memory or guess.
- Only state numbers that appear in the tool results. Do not calculate new numbers: no sums,
  differences, averages, percentages or shares that a tool did not return. If a figure isn't
  available, say so and say what you can answer instead.
- Amounts are US dollars. When you mention overdue amounts or stock levels, say the as_of_date.
- You cannot create, change, send or delete anything. If asked to, say you can only read reports.
- You have no customer contact details.
- Keep answers short: one to four sentences, or a short list.
"""

RETRY_PROMPT = (
    "Your answer contains numbers that are not in the tool results: {numbers}. Rewrite the answer "
    "using only numbers that appear in the results, exactly or rounded. "
    "Do not calculate new numbers."
)


@dataclass
class QueryRun:
    name: str
    args: dict[str, Any]
    sql: str | None = None
    row_count: int = 0
    truncated: bool = False
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class Answer:
    question: str
    text: str
    status: str  # answered | no_data | fallback | error
    grounded: bool
    unsupported: list[str]
    queries: list[QueryRun]
    model: str
    run_id: str
    duration_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)


def plain(value: Any) -> Any:
    """JSON-friendly values for the model and the log."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def run_query(conn: psycopg.Connection, call: ToolCall) -> QueryRun:
    query = BY_NAME.get(call.name)
    if query is None:
        return QueryRun(call.name, call.args, error=f"unknown query {call.name}")
    try:
        sql, values, used = query.prepare(call.args)
    except InvalidArguments as exc:
        return QueryRun(call.name, call.args, error=str(exc))
    run = QueryRun(call.name, used, sql=sql)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, values)
            columns = [c.name for c in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as exc:
        run.error = f"query failed: {type(exc).__name__}"
        return run
    run.truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    run.row_count = len(rows)
    run.result = {
        "rows": [{c: plain(v) for c, v in zip(columns, row, strict=True)} for row in rows],
        "row_count": len(rows),
        "truncated": run.truncated,
    }
    return run


def render_results(queries: list[QueryRun]) -> str:
    """Plain-text tables of the query results (used when the AI's wording fails the check)."""
    blocks = []
    for q in queries:
        if q.error or not q.result.get("rows"):
            continue
        rows = q.result["rows"][:20]
        cols = list(rows[0])
        widths = [max(len(c), *(len(str(r[c])) for r in rows)) for c in cols]
        lines = [
            f"{q.name} ({q.row_count} rows):",
            "  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)),
        ]
        lines += [
            "  ".join(str(r[c]).ljust(w) for c, w in zip(cols, widths, strict=True)) for r in rows
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "No results."


def _add_usage(total: dict[str, int], usage: dict[str, Any]) -> None:
    for key in (
        "promptTokenCount",
        "candidatesTokenCount",
        "thoughtsTokenCount",
        "totalTokenCount",
    ):
        if isinstance(usage.get(key), int):
            total[key] = total.get(key, 0) + usage[key]


def ask(question: str, llm: LLM, conn: psycopg.Connection, run_id: str, log=None) -> Answer:
    started = time.monotonic()
    tools = [q.declaration() for q in QUERIES]
    messages = [llm.user_message(question)]
    queries: list[QueryRun] = []
    usage: dict[str, int] = {}

    def finish(text, status, check):
        return Answer(
            question=question,
            text=text,
            status=status,
            grounded=check.ok,
            unsupported=check.unsupported,
            queries=queries,
            model=llm.model,
            run_id=run_id,
            duration_ms=int((time.monotonic() - started) * 1000),
            usage=usage,
        )

    turn = None
    for _ in range(MAX_TOOL_ROUNDS):
        turn = llm.generate(SYSTEM_PROMPT, messages, tools)
        _add_usage(usage, turn.usage)
        if not turn.calls:
            break
        runs = [run_query(conn, call) for call in turn.calls]
        queries.extend(runs)
        if log:
            for r in runs:
                log.info(
                    "Query run",
                    extra={
                        "query": r.name,
                        "query_args": r.args,
                        "rows": r.row_count,
                        "error": r.error,
                    },
                )
        messages.append(turn.content)
        results = [r.result if not r.error else {"error": r.error} for r in runs]
        messages.append(llm.tool_results_message(turn.calls, results))
    else:
        # Still asking for queries after the last round: make it answer with what it has.
        turn = llm.generate(SYSTEM_PROMPT, messages, tools, allow_tools=False)
        _add_usage(usage, turn.usage)

    results = [q.result for q in queries if q.result]
    check = grounding.check(turn.text, results, question)
    if not check.ok:
        messages.append(turn.content)
        messages.append(llm.user_message(RETRY_PROMPT.format(numbers=", ".join(check.unsupported))))
        turn = llm.generate(SYSTEM_PROMPT, messages, tools, allow_tools=False)
        _add_usage(usage, turn.usage)
        check = grounding.check(turn.text, results, question)
    if not check.ok:
        text = (
            "I couldn't word an answer using only verified figures, so here are the query results "
            "instead.\n\n" + render_results(queries)
        )
        return finish(text, "fallback", check)
    return finish(turn.text, "answered" if results else "no_data", check)


# ---------------------------------------------------------------- audit log

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS ops.assistant_log (
    run_id text PRIMARY KEY,
    asked_at timestamptz NOT NULL DEFAULT now(),
    question text NOT NULL,
    status text NOT NULL,
    grounded boolean NOT NULL,
    unsupported jsonb NOT NULL,
    answer text NOT NULL,
    queries jsonb NOT NULL,
    model text NOT NULL,
    duration_ms integer NOT NULL,
    usage jsonb NOT NULL
);
COMMENT ON TABLE ops.assistant_log IS
    'Every question put to the AI reporting assistant, the approved queries it ran, its answer, '
    'and whether every number in the answer matched the query results. Demo data only.';
"""


def write_audit(admin: psycopg.Connection, answer: Answer) -> None:
    queries = [{k: v for k, v in asdict(q).items() if k != "result"} for q in answer.queries]
    with admin.transaction():
        admin.execute(AUDIT_DDL)
        admin.execute(
            """INSERT INTO ops.assistant_log
               (run_id, question, status, grounded, unsupported, answer, queries, model,
                duration_ms, usage)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                answer.run_id,
                answer.question,
                answer.status,
                answer.grounded,
                json.dumps(answer.unsupported),
                answer.text,
                json.dumps(queries),
                answer.model,
                answer.duration_ms,
                json.dumps(answer.usage),
            ),
        )


# ---------------------------------------------------------------- command line


def connect_ai_reader(settings: Settings) -> psycopg.Connection:
    if settings.ai_reader_password is None:
        raise SystemExit(
            "AI_READER_PASSWORD is blank in .env. "
            "Run `make env-secrets`, `make up`, `make db-init`."
        )
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user="ai_reader",
        password=settings.ai_reader_password.get_secret_value(),
        application_name="bluefield-assistant",
        autocommit=True,
    )


def format_answer(answer: Answer, show_sql: bool = False) -> str:
    lines = [answer.text, "", "Sources (demo data, read-only views):"]
    for q in answer.queries:
        args = ", ".join(f"{k}={v}" for k, v in q.args.items() if v is not None)
        outcome = f"error: {q.error}" if q.error else f"{q.row_count} rows"
        lines.append(f"  - {q.name}({args}) -> {outcome}")
        if show_sql and q.sql:
            lines += ["      " + line for line in q.sql.splitlines()]
    if not answer.queries:
        lines.append("  - none (no query was needed or allowed)")
    check = "passed" if answer.grounded else f"FAILED ({', '.join(answer.unsupported)})"
    lines.append(
        f"Number check: {check} | status: {answer.status} | model: {answer.model} "
        f"| run_id: {answer.run_id}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ask the Bluefield reporting assistant (demo data)."
    )
    parser.add_argument("question", help="your question, in quotes")
    parser.add_argument("--show-sql", action="store_true", help="print the SQL of each query")
    parser.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = parser.parse_args(argv)

    from pipeline import db  # admin connection for the audit log only

    settings = Settings()
    run_id = new_run_id()
    log = get_logger("assistant.ask", run_id, settings.log_level)
    llm = get_llm(settings)
    try:
        with connect_ai_reader(settings) as conn:
            answer = ask(args.question.strip(), llm, conn, run_id, log)
    except LLMError as exc:
        log.error("The AI model could not answer", extra={"error": str(exc)})
        return 1
    finally:
        llm.close()
    try:
        with db.connect(settings) as admin:
            write_audit(admin, answer)
    except (psycopg.Error, SystemExit) as exc:
        log.error("Could not write ops.assistant_log", extra={"error": str(exc)})
    log.info(
        "Answered",
        extra={"status": answer.status, "grounded": answer.grounded, "queries": len(answer.queries),
               "duration_ms": answer.duration_ms, "usage": answer.usage},
    )  # fmt: skip
    if args.json:
        print(json.dumps(asdict(answer), default=str, indent=2))
    else:
        print(format_answer(answer, args.show_sql))
    return 0 if answer.status != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
