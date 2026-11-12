"""Unit tests for how the live stack checks treat optional Compose profiles. No Docker needed.

`make check-stack` must skip Metabase or n8n only when the service was never started
(connection refused), and must still fail when a started service is unhealthy.
"""

import urllib.error

import pytest

from tests.integration import test_stack


def test_check_skips_when_service_is_not_running(monkeypatch):
    def refused(url):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    monkeypatch.setattr(test_stack, "http_get", refused)
    with pytest.raises(pytest.skip.Exception, match="make up-reporting"):
        test_stack.http_get_profiled("http://127.0.0.1:1/", "Metabase", "make up-reporting")


def test_check_fails_when_service_is_unhealthy(monkeypatch):
    def server_error(url):
        raise urllib.error.HTTPError(url, 503, "Service Unavailable", {}, None)

    monkeypatch.setattr(test_stack, "http_get", server_error)
    with pytest.raises(urllib.error.HTTPError):
        test_stack.http_get_profiled("http://127.0.0.1:1/", "Metabase", "make up-reporting")


def test_check_fails_on_other_network_errors(monkeypatch):
    def timed_out(url):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(test_stack, "http_get", timed_out)
    with pytest.raises(urllib.error.URLError):
        test_stack.http_get_profiled("http://127.0.0.1:1/", "n8n", "make up-automation")
