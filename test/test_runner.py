"""Verify the CLI response checker rejects failures and invalid structured output."""

import importlib.util
from pathlib import Path

from jsonschema import ValidationError
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("response_checker", ROOT / "test/check_service_response.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def response(**fields):
    arguments = ", ".join(f"{key}={value!r}" for key, value in fields.items())
    return f"requester: making request\nresponse:\nexample.srv.Response({arguments})\n"


def test_cli_response_and_schema_checks():
    output = response(success=True, response='{"response":"hello"}', error_message="")
    checker.check(output, "structured_response", ROOT / "schemas")
    checker.check(response(response="hello"), "legacy", ROOT / "schemas")
    checker.check(response(success=False, response="", error_message="missing schema"), "error", ROOT / "schemas")
    with pytest.raises(ValidationError):
        checker.check(response(success=True, response='{"wrong":true}', error_message=""),
                      "structured_response", ROOT / "schemas")
    with pytest.raises(ValueError, match="Service failed"):
        checker.check(response(success=False, response="", error_message="failed"), "text", ROOT / "schemas")
    with pytest.raises(ValueError, match="no response"):
        checker.check("waiting for service...", "text", ROOT / "schemas")


def test_response_checker_never_executes_code():
    with pytest.raises(ValueError):
        checker.check("response:\nResponse(response=__import__('os').getcwd())", "text", ROOT / "schemas")
