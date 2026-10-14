"""Validate ros2 service call's Python response representation without eval()."""

import argparse
import ast
from pathlib import Path

from letssee_llm.structured import load_schema, validate_response


def check(output: str, expectation: str, schema_dir: Path) -> None:
    """Check transport output, success/error fields, and original JSON Schemas."""
    marker = "response:\n"
    if marker not in output:
        raise ValueError("ros2 service call produced no response")
    expression = ast.parse(output.rsplit(marker, 1)[1].strip(), mode="eval").body
    if not isinstance(expression, ast.Call) or expression.args:
        raise ValueError("Unexpected ROS response representation")
    fields = {item.arg: ast.literal_eval(item.value) for item in expression.keywords}
    if expectation == "error":
        if fields.get("success") is not False or not fields.get("error_message"):
            raise ValueError(f"Expected an explicit service failure: {fields}")
        if fields.get("response") != "":
            raise ValueError("Failed service returned a nonempty response")
        return
    if expectation != "legacy":
        if fields.get("success") is not True or fields.get("error_message") != "":
            raise ValueError(f"Service failed: {fields}")
    text = fields.get("response")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expected a nonempty generated response")
    if expectation in {"structured_response", "object_recognition"}:
        validate_response(text, load_schema(schema_dir, expectation))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("expectation", choices=["text", "legacy", "error", "structured_response", "object_recognition"])
    parser.add_argument("schema_dir", type=Path)
    args = parser.parse_args()
    check(args.output.read_text(), args.expectation, args.schema_dir)


if __name__ == "__main__":
    main()
