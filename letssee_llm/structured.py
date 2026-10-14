"""Explicit decoding support checks and final JSON Schema validation."""

import json
from pathlib import Path

from jsonschema import validators

from .library import asset_path


def generation_options(max_tokens: int, temperature: float) -> dict:
    """Use greedy decoding at zero temperature, sampling only when requested."""
    import math

    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
        raise ValueError("max_tokens must be a positive integer")
    if not isinstance(temperature, (int, float)) or not math.isfinite(temperature) or temperature < 0:
        raise ValueError("temperature must be finite and nonnegative")
    options = {"max_new_tokens": max_tokens, "do_sample": temperature > 0, "num_beams": 1}
    if temperature > 0:
        options["temperature"] = temperature
    else:
        # Clear model-specific sampling defaults when requesting greedy decoding.
        options.update(temperature=None, top_p=None, top_k=None)
    return options


def load_schema(directory: Path, schema_id: str) -> dict | None:
    """Load and validate a schema definition; an empty ID disables constraints."""
    if not schema_id:
        return None
    schema = json.loads(asset_path(directory, schema_id, ".schema.json").read_text())
    validators.validator_for(schema).check_schema(schema)
    decoding_schema(schema)
    return schema


def decoding_schema(schema: dict) -> dict:
    """Limit decoding to a deliberately small shared backend schema subset.

    Unknown assertions are rejected, because some grammar converters ignore them.
    Numeric bounds are supported only with a finite enum that enforces the bounds.
    """
    validators.validator_for(schema).check_schema(schema)
    if not isinstance(schema, dict):
        raise ValueError("Boolean schemas are unsupported for constrained decoding")
    annotations = {"$schema", "title", "description"}
    common = {"type", "enum", *annotations}
    kind = schema.get("type")
    allowed = {
        "object": common | {"properties", "required", "additionalProperties"},
        "array": common | {"items", "minItems", "maxItems"},
        "string": common,
        "integer": common | {"minimum", "maximum"},
        "number": common | {"minimum", "maximum"},
        "boolean": common,
        "null": common,
    }
    if not isinstance(kind, str) or kind not in allowed:
        raise ValueError("Constrained schemas require one explicit primitive type per node")
    unsupported = set(schema) - allowed[kind]
    if unsupported:
        raise ValueError(f"Unsupported schema features: {', '.join(sorted(unsupported))}")
    result = {key: value for key, value in schema.items() if key not in annotations}
    if "enum" in schema:
        if kind in {"object", "array"}:
            raise ValueError("Only primitive enums are supported")
        validator = validators.validator_for(schema)({k: v for k, v in schema.items() if k != "enum"})
        if not all(validator.is_valid(value) for value in schema["enum"]):
            raise ValueError("Enum values must satisfy the schema's type and bounds")
    if "minimum" in schema or "maximum" in schema:
        if "enum" not in schema:
            raise ValueError("Numeric bounds require a finite enum for constrained decoding")
        result.pop("minimum", None)
        result.pop("maximum", None)
    if kind == "object":
        if schema.get("additionalProperties") is not False:
            raise ValueError("Constrained objects require additionalProperties: false")
        result["properties"] = {
            key: decoding_schema(value) for key, value in schema.get("properties", {}).items()
        }
    if kind == "array":
        if not isinstance(schema.get("items"), dict):
            raise ValueError("Constrained arrays require a single items schema")
        result["items"] = decoding_schema(schema["items"])
    return result


def validate_response(text: str, schema: dict) -> str:
    """Parse complete JSON and validate against the original, unreduced schema."""
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-JSON numeric constant: {value}")

    value = json.loads(text, parse_constant=reject_constant)
    validators.validator_for(schema)(schema).validate(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def logits_processor(model, tokenizer, schema: dict):
    """Build an Outlines token mask for native model.generate(), including VLMs."""
    import outlines
    from outlines.backends import get_json_schema_logits_processor

    adapter = outlines.from_transformers(model, tokenizer)
    return get_json_schema_logits_processor(
        "outlines_core", adapter, json.dumps(decoding_schema(schema)), whitespace_pattern=r" ?"
    )
