"""Check that every number in an AI answer came from the query results (or the question).

This is how "AI explains results but never invents them" is enforced. The answer may round a
figure or write it as $9.5k or 32.5%, but the value must match something the SQL returned. A
figure the model worked out itself (a new total, a difference, a share) fails the check, even if
the arithmetic is right: calculations belong in SQL, where they are tested.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

# $1,234.56 | 1234 | 32.5% | 9.5k | $1.2M | -42 | (but not part of an id like ACC-SINV-2026-00007)
NUMBER = re.compile(
    r"(?<![\w.-])(?P<sign>-)?\$?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<suffix>\s?(?:k|K|M|million|thousand)\b)?(?P<pct>%)?(?![\w-])"
)
LIST_MARKER = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
DATE_LIKE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6}


@dataclass(frozen=True)
class Grounding:
    ok: bool
    numbers: list[str]  # every figure found in the answer
    unsupported: list[str]  # figures that match nothing in the results


def _values(obj: Any, out: set[float]) -> None:
    """Collect every number in the results, including the parts of dates (2026, 11, 12)."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float, Decimal)):
        out.add(float(obj))
    elif isinstance(obj, (date, datetime)):
        _values(obj.isoformat(), out)
    elif isinstance(obj, str):
        for match in re.finditer(r"\d+(?:\.\d+)?", obj):
            out.add(float(match[0]))
    elif isinstance(obj, dict):
        for value in obj.values():
            _values(value, out)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _values(value, out)


def tolerance(written: str, scale: float = 1.0) -> float:
    """Half a unit of the last digit written: 9,528.77 -> 0.005, 9,529 -> 0.5, 9.5k -> 50.

    Round thousands such as "about 9,500" get half a unit of the last non-zero digit (50), but
    only from 1,000 up, so "10 invoices" can't pass for 13.
    """
    digits = written.replace(",", "").lstrip("-")
    if "." in digits:
        return 0.5 * scale * 10 ** -len(digits.split(".")[1])
    unit = 1.0
    if scale == 1.0 and float(digits) >= 1000:
        unit = 10.0 ** (len(digits) - len(digits.rstrip("0")))
    return 0.5 * scale * unit


def _matches(value: float, tol: float, known: set[float]) -> bool:
    return any(abs(k - value) <= tol + 1e-9 for k in known)


def check(answer: str, results: list[Any], question: str = "") -> Grounding:
    known: set[float] = set()
    _values(results, known)
    _values(question, known)
    text = LIST_MARKER.sub(" ", answer)
    text = DATE_LIKE.sub(lambda m: m[0].replace("-", " "), text)  # 2026-11-12 -> "2026 11 12"
    numbers, unsupported = [], []
    for match in NUMBER.finditer(text):
        scale = SCALE.get((match["suffix"] or "").strip(), 1.0)
        value = float(match["num"].replace(",", "")) * scale * (-1 if match["sign"] else 1)
        numbers.append(match[0].strip())
        if not _matches(value, tolerance(match["num"], scale), known):
            unsupported.append(match[0].strip())
    return Grounding(ok=not unsupported, numbers=numbers, unsupported=unsupported)
