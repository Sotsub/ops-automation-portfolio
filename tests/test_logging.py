import json
import logging

from shared.logging import JsonFormatter, get_logger, new_run_id


def test_new_run_id_is_unique():
    assert new_run_id() != new_run_id()


def test_log_line_is_json_with_run_id(capsys):
    run_id = new_run_id()
    log = get_logger("tests.json_logging", run_id)
    log.info("extract finished", extra={"rows": 42})

    line = capsys.readouterr().err.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["run_id"] == run_id
    assert payload["message"] == "extract finished"
    assert payload["level"] == "INFO"
    assert payload["rows"] == 42


def test_logger_does_not_add_duplicate_handlers():
    get_logger("tests.no_dupes", "a")
    get_logger("tests.no_dupes", "b")
    handlers = logging.getLogger("tests.no_dupes").handlers
    assert sum(isinstance(h.formatter, JsonFormatter) for h in handlers) == 1


def test_exception_is_included():
    formatter = JsonFormatter()
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, "", 0, "failed", None, sys.exc_info())
    payload = json.loads(formatter.format(record))
    assert "RuntimeError: boom" in payload["exception"]
    assert payload["run_id"] is None
