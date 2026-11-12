"""The AI assistant without a model or database: queries, number check, Gemini, main loop."""

import json
import re
from datetime import date

import httpx
import pytest

from assistant import ask as ask_mod
from assistant import eval as eval_mod
from assistant import grounding, llm
from assistant.queries import BY_NAME, QUERIES, InvalidArguments
from shared.config import Settings
from tests.helpers import ROOT

# ---------------------------------------------------------------- approved queries


@pytest.mark.parametrize("query", QUERIES, ids=lambda q: q.name)
def test_queries_only_read_the_ai_views(query):
    args = {
        p.name: (p.choices[0] if p.choices else ("Oak" if p.kind == "string" else None))
        for p in query.params
    }
    sql, _, _ = query.prepare(args)
    assert sql.lstrip().upper().startswith("SELECT")
    assert not re.search(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|COPY)\b", sql, re.I
    )
    tables = re.findall(r"\bFROM\s+([A-Za-z_][\w.]*)", sql, re.I)
    assert tables and all(t.startswith("ai.") for t in tables), tables


@pytest.mark.parametrize("query", QUERIES, ids=lambda q: q.name)
def test_declarations_are_valid_tool_schemas(query):
    decl = query.declaration()
    assert re.fullmatch(r"[a-z_]+", decl["name"]) and decl["description"]
    props = decl["parameters"]["properties"]
    assert set(decl["parameters"]["required"]) <= set(props)
    for spec in props.values():
        assert spec["type"] in ("string", "integer") and spec["description"]


def test_model_text_never_reaches_the_sql():
    sneaky = "x'; DROP TABLE ai.customers; --"
    sql, values, _ = BY_NAME["customer_profile"].prepare({"customer_name": sneaky})
    assert sneaky not in sql and "DROP" not in sql
    assert values["pattern"] == "%x'; DROP TABLE ai.customers; --%"
    sql, values, _ = BY_NAME["customer_profile"].prepare({"customer_name": "100%_off"})
    assert values["pattern"] == r"%100\%\_off%", "LIKE wildcards in names are escaped"


@pytest.mark.parametrize(
    "name, args, message",
    [
        ("rank_customers", {"rank_by": "email"}, "rank_by must be one of"),
        ("rank_customers", {"rank_by": "lifetime_revenue", "limit": 500}, "between 1 and 20"),
        ("rank_customers", {"rank_by": "lifetime_revenue", "limit": 2.5}, "whole number"),
        ("rank_customers", {}, "rank_by is required"),
        ("monthly_sales", {"start_month": "March"}, "look like 2026-03"),
        ("monthly_sales", {"start_month": "2026-13"}, "not a real month"),
        ("get_kpis", {"sql": "select 1"}, "unknown arguments: sql"),
        ("customer_profile", {"customer_name": "x" * 101}, "too long"),
    ],
)
def test_bad_arguments_are_rejected(name, args, message):
    with pytest.raises(InvalidArguments, match=message):
        BY_NAME[name].prepare(args)


def test_arguments_are_normalised_and_defaults_applied():
    sql, values, used = BY_NAME["monthly_sales"].prepare(
        {"start_month": "2026-03", "region": "West"}
    )
    assert values["start_month"] == date(2026, 3, 1) and values["end_month"] is None
    assert used["start_month"] == "2026-03"
    _, values, _ = BY_NAME["rank_customers"].prepare({"rank_by": "pct_paid_late"})
    assert values["limit"] == 5
    sql, _, _ = BY_NAME["rank_customers"].prepare({"rank_by": "pct_paid_late"})
    assert "ORDER BY pct_paid_late DESC" in sql and "invoices_paid > 0" in sql


def test_ai_views_expose_no_contact_details():
    for path in (ROOT / "pipeline" / "dbt" / "models" / "ai").glob("*.sql"):
        sql = path.read_text(encoding="utf-8")
        assert "email" not in sql and "select *" not in sql.replace(
            "select * from {{ ref('kpi_summary') }}", ""
        )


# ---------------------------------------------------------------- number check

RESULTS = [
    {
        "rows": [
            {
                "overdue_invoices": 13,
                "overdue": 9528.77,
                "pct": 32.5,
                "revenue": 466495.94,
                "as_of_date": "2026-11-12",
            }
        ]
    }
]


@pytest.mark.parametrize(
    "answer, ok",
    [
        ("Customers owe $9,528.77 across 13 overdue invoices.", True),
        ("About $9,529 is overdue.", True),
        ("Roughly $9.5k is overdue.", True),
        ("About $9,500 is overdue.", True),
        ("Revenue was $466.5k with a 32.5% margin, as of 2026-11-12.", True),
        ("Invoice ACC-SINV-2026-00007 is overdue.", True),
        ("1. Maple Grove owes $9,528.77", True),
        ("$9,600 is overdue.", False),
        ("10 invoices are overdue.", False),
        ("That is 2% of revenue.", False),
        ("Revenue was $1.2M.", False),
    ],
)
def test_number_check(answer, ok):
    assert grounding.check(answer, RESULTS).ok is ok


def test_numbers_from_the_question_are_allowed():
    assert grounding.check("Here are the top 3 customers.", [], "Who are our top 3 customers?").ok


# ---------------------------------------------------------------- Gemini adapter


def gemini(handler, **kw):
    return llm.GeminiClient(
        "test-model", "test-key", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw
    )


def reply(parts, **extra):
    return httpx.Response(
        200, json={"candidates": [{"content": {"role": "model", "parts": parts}}], **extra}
    )


def test_request_shape_and_tool_call_parsing():
    seen = []

    def handler(request):
        seen.append(request)
        return reply(
            [
                {"text": "thinking...", "thought": True},
                {
                    "functionCall": {"name": "get_kpis", "args": {}, "id": "c1"},
                    "thoughtSignature": "sig",
                },
            ],
            usageMetadata={"totalTokenCount": 42},
        )

    client = gemini(handler)
    turn = client.generate(
        "SYSTEM", [client.user_message("Q?")], [BY_NAME["get_kpis"].declaration()]
    )
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1beta/models/test-model:generateContent"
    assert seen[0].headers["x-goog-api-key"] == "test-key"
    assert body["systemInstruction"] == {"parts": [{"text": "SYSTEM"}]}
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "get_kpis"
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    assert turn.calls == [llm.ToolCall("get_kpis", {}, "c1")]
    assert turn.text == "", "thought parts are not part of the answer"
    assert turn.content["parts"][1]["thoughtSignature"] == "sig", "kept so it can be sent back"
    assert turn.usage == {"totalTokenCount": 42}


def test_tool_results_echo_the_call_id():
    client = gemini(lambda r: reply([{"text": "x"}]))
    message = client.tool_results_message([llm.ToolCall("get_kpis", {}, "c1")], [{"rows": []}])
    assert message == {
        "role": "user",
        "parts": [{"functionResponse": {"name": "get_kpis", "response": {"rows": []}, "id": "c1"}}],
    }


def test_rate_limits_are_retried_with_the_requested_delay():
    waits, calls = [], []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(
                429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}}
            )
        if len(calls) == 2:
            return httpx.Response(
                503, json={"error": {"message": "busy", "details": [{"retryDelay": "3s"}]}}
            )
        return reply([{"text": "OK"}])

    client = llm.GeminiClient("m", "k", transport=httpx.MockTransport(handler), sleep=waits.append)
    assert client.generate("s", [], []).text == "OK"
    assert waits == [7.0, 3.0]


def test_errors_are_reported_without_the_key():
    client = gemini(
        lambda r: httpx.Response(400, json={"error": {"message": "API key not valid"}}), retries=1
    )
    with pytest.raises(llm.LLMError) as err:
        client.generate("s", [], [])
    assert "API key not valid" in str(err.value) and "test-key" not in str(err.value)


def test_get_llm_needs_provider_model_and_key():
    with pytest.raises(SystemExit, match="AI_PROVIDER is blank"):
        llm.get_llm(Settings(_env_file=None))
    with pytest.raises(SystemExit, match="not supported"):
        llm.get_llm(Settings(_env_file=None, ai_provider="other", ai_model="m", ai_api_key="k"))
    with pytest.raises(SystemExit, match="AI_MODEL is blank"):
        llm.get_llm(Settings(_env_file=None, ai_provider="gemini", ai_api_key="k"))
    client = llm.get_llm(
        Settings(_env_file=None, ai_provider="Gemini", ai_model="m1", ai_api_key="k")
    )
    assert client.model == "m1"


# ---------------------------------------------------------------- main loop with a scripted model


class ScriptedLLM:
    """Plays back a list of turns and records what it was sent."""

    model = "scripted"

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    def user_message(self, text):
        return {"role": "user", "text": text}

    def tool_results_message(self, calls, results):
        return {"role": "tool", "results": results}

    def generate(self, system, messages, tools, allow_tools=True):
        self.calls.append({"messages": list(messages), "allow_tools": allow_tools})
        return self.turns.pop(0)


def text_turn(text):
    return llm.Turn(text=text, calls=[], content={"role": "model", "text": text})


def call_turn(*calls):
    return llm.Turn(
        text="", calls=list(calls), content={"role": "model", "calls": [c.name for c in calls]}
    )


@pytest.fixture
def fake_queries(monkeypatch):
    """Replace the database: get_kpis returns fixed figures; other names come back as errors."""

    def fake_run(conn, call):
        if call.name == "get_kpis":
            rows = [{"overdue_receivables": 9528.77, "overdue_invoices": 13}]
            return ask_mod.QueryRun(
                "get_kpis", {}, sql="SELECT ...", row_count=1, result={"rows": rows}
            )
        return ask_mod.QueryRun(call.name, call.args, error="unknown query")

    monkeypatch.setattr(ask_mod, "run_query", fake_run)


def test_answer_from_query_results(fake_queries):
    model = ScriptedLLM(
        [call_turn(llm.ToolCall("get_kpis", {})), text_turn("$9,528.77 is overdue on 13 invoices.")]
    )
    answer = ask_mod.ask("How much is overdue?", model, conn=None, run_id="r1")
    assert (answer.status, answer.grounded) == ("answered", True)
    assert [q.name for q in answer.queries] == ["get_kpis"]
    tool_message = model.calls[1]["messages"][-1]
    assert tool_message["results"][0]["rows"][0]["overdue_invoices"] == 13


def test_unverified_number_gets_one_rewrite(fake_queries):
    model = ScriptedLLM(
        [
            call_turn(llm.ToolCall("get_kpis", {})),
            text_turn("$9,600 is overdue."),
            text_turn("$9,528.77 is overdue."),
        ]
    )
    answer = ask_mod.ask("How much is overdue?", model, conn=None, run_id="r2")
    assert answer.text == "$9,528.77 is overdue." and answer.grounded
    assert model.calls[-1]["allow_tools"] is False
    assert "$9,600" in model.calls[-1]["messages"][-1]["text"]


def test_second_failure_falls_back_to_the_plain_results(fake_queries):
    model = ScriptedLLM(
        [
            call_turn(llm.ToolCall("get_kpis", {})),
            text_turn("About 75% is overdue."),
            text_turn("Still 75%."),
        ]
    )
    answer = ask_mod.ask("How much is overdue?", model, conn=None, run_id="r3")
    assert answer.status == "fallback" and not answer.grounded
    assert "9528.77" in answer.text and "75%" not in answer.text


def test_query_errors_go_back_to_the_model(fake_queries):
    model = ScriptedLLM(
        [
            call_turn(llm.ToolCall("drop_tables", {})),
            call_turn(llm.ToolCall("get_kpis", {})),
            text_turn("13 invoices."),
        ]
    )
    answer = ask_mod.ask("How many overdue?", model, conn=None, run_id="r4")
    assert model.calls[1]["messages"][-1]["results"] == [{"error": "unknown query"}]
    assert answer.status == "answered"


def test_refusal_without_queries_is_no_data(fake_queries):
    model = ScriptedLLM([text_turn("I can only read reports.")])
    answer = ask_mod.ask("Mark invoice paid", model, conn=None, run_id="r5")
    assert (answer.status, answer.queries) == ("no_data", [])


def test_numbers_without_any_query_are_not_trusted(fake_queries):
    model = ScriptedLLM([text_turn("Revenue was $500,000."), text_turn("Revenue was $500,000.")])
    answer = ask_mod.ask("Revenue?", model, conn=None, run_id="r6")
    assert answer.status == "fallback"


def test_tool_rounds_are_capped(fake_queries):
    loops = [call_turn(llm.ToolCall("get_kpis", {}))] * ask_mod.MAX_TOOL_ROUNDS
    model = ScriptedLLM([*loops, text_turn("13 overdue invoices.")])
    answer = ask_mod.ask("Overdue?", model, conn=None, run_id="r7")
    assert model.calls[-1]["allow_tools"] is False and answer.status == "answered"


# ---------------------------------------------------------------- evaluation helpers


@pytest.mark.parametrize(
    "text, value, expected",
    [
        ("Revenue is $466,495.94.", 466495.94, True),
        ("Revenue is about $466.5k.", 466495.94, True),
        ("Revenue is $400,000.", 466495.94, False),
        ("The best month was September 2026.", date(2026, 9, 1), True),
        ("Oak Valley School District leads.", "Oak Valley School District", True),
    ],
)
def test_eval_mentions(text, value, expected):
    assert eval_mod.mentions(text, value) is expected


def test_eval_cases_are_unique_and_cover_safety():
    ids = [c.id for c in eval_mod.CASES]
    assert len(ids) == len(set(ids))
    assert any(c.no_queries for c in eval_mod.CASES), "a write request must be refused"
    assert any("@" in c.forbid for c in eval_mod.CASES), "contact details must not leak"
    for case in eval_mod.CASES:
        assert all(q in BY_NAME for q in case.queries), case.id
        assert case.expect_sql is None or "FROM ai." in case.expect_sql
