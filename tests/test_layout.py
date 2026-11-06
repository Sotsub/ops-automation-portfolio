import importlib

import pytest

PACKAGES = ["erp", "pipeline", "assistant", "sync", "reports", "eval", "agent", "shared"]


@pytest.mark.parametrize("name", PACKAGES)
def test_project_package_imports(name):
    module = importlib.import_module(name)
    assert module.__doc__
