"""Small client for the Frappe/ERPNext REST API.

Endpoints follow the Frappe REST docs (https://docs.frappe.io/framework/user/en/api/rest):
- documents: /api/resource/<doctype>[/<name>]
- whitelisted methods: /api/method/<dotted.path>
- token auth header: "Authorization: token <api_key>:<api_secret>"

Only GET requests are retried. A create is never retried, because a timed-out POST may still have
been saved. Callers make creates safe to rerun by looking records up by a key first.
"""

import json
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import httpx

PAGE_SIZE = (
    500  # The list API treats a page size of 0 as "use the default (20)", so page explicitly.
)


class ErpError(Exception):
    """ERPNext rejected a request. The message is ERPNext's own text, not request data."""

    def __init__(self, status: int, message: str, exc_type: str | None = None):
        super().__init__(f"HTTP {status}: {exc_type + ': ' if exc_type else ''}{message}")
        self.status = status
        self.exc_type = exc_type
        self.message = message


def _error_from(response: httpx.Response) -> ErpError:
    """Pull a readable message out of a Frappe error response."""
    try:
        body = response.json()
    except ValueError:
        return ErpError(response.status_code, response.text[:300] or response.reason_phrase)
    messages = []
    for raw in json.loads(body.get("_server_messages") or "[]"):
        try:
            messages.append(json.loads(raw).get("message", raw))
        except (ValueError, AttributeError):
            messages.append(str(raw))
    message = "; ".join(messages) or body.get("message") or body.get("exception") or response.text
    return ErpError(response.status_code, str(message)[:500], body.get("exc_type"))


class ErpClient:
    """Thin wrapper over the REST API. Pass `transport` in tests to avoid the network."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        *,
        timeout: float = 120.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ):
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"token {api_key}:{api_secret}",
                "Accept": "application/json",
            },
            timeout=timeout,
            transport=transport,
        )
        self._retries = retries

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ErpClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(1, self._retries + 1):
            try:
                response = self._http.get(path, params=params)
            except httpx.TransportError:
                if attempt == self._retries:
                    raise
                time.sleep(2**attempt)
                continue
            if response.status_code >= 500 and attempt < self._retries:
                time.sleep(2**attempt)
                continue
            if response.is_error:
                raise _error_from(response)
            return response.json()
        raise AssertionError("unreachable")

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        response = self._http.post(path, json=payload)
        if response.is_error:
            raise _error_from(response)
        return response.json()

    def logged_user(self) -> str:
        """Return the user the API key belongs to (cheap way to check the key works)."""
        return self._get("/api/method/frappe.auth.get_logged_user")["message"]

    def get_list(
        self,
        doctype: str,
        fields: Iterable[str] = ("name",),
        filters: list[list[Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return every matching record, fetching PAGE_SIZE at a time."""
        rows: list[dict[str, Any]] = []
        while True:
            params = {
                "fields": json.dumps(list(fields)),
                "limit_start": len(rows),
                "limit_page_length": PAGE_SIZE,
                "order_by": "creation asc",
            }
            if filters:
                params["filters"] = json.dumps(filters)
            page = self._get(f"/api/resource/{quote(doctype)}", params)["data"]
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        return self._get(f"/api/resource/{quote(doctype)}/{quote(name, safe='')}")["data"]

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Create a document (as a draft, for submittable doctypes)."""
        return self._post(f"/api/resource/{quote(doc['doctype'])}", doc)["data"]

    def submit(self, doctype: str, name: str) -> dict[str, Any]:
        """Submit a saved draft. Saving docstatus 0 -> 1 runs ERPNext's normal submit, which also
        sets the document's status (inserting with docstatus 1 directly leaves status "Draft")."""
        response = self._http.put(
            f"/api/resource/{quote(doctype)}/{quote(name, safe='')}", json={"docstatus": 1}
        )
        if response.is_error:
            raise _error_from(response)
        return response.json()["data"]
