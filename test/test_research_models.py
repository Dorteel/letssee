"""Focused tests of reusable assets, backend dispatch, and schema guarantees."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jsonschema import SchemaError, ValidationError
import pytest
import yaml

from letssee_llm.inference import GGUFModel, LocalModels
from letssee_llm.library import ModelLibrary, load_template
from letssee_llm.structured import decoding_schema, generation_options, load_schema, validate_response

ROOT = Path(__file__).resolve().parents[1]


def write_model(path, model_type="qwen3"):
    path.mkdir(parents=True, exist_ok=True)
    for name, content in {
        "config.json": json.dumps({"model_type": model_type}),
        "tokenizer_config.json": "{}", "tokenizer.json": "{}",
        "model.safetensors": "mock weights",
    }.items():
        (path / name).write_text(content)


def test_registry_paths_and_metadata(tmp_path):
    library = ModelLibrary(ROOT / "models/model_library.yaml", tmp_path)
    assert set(library.models) == {"general", "coding", "vision"}
    assert library.path("coding") == tmp_path / "coding/qwen2.5-coder-1.5b-instruct"
    assert "vision" in library.entry("vision")["capabilities"]
    with pytest.raises(ValueError, match="Unknown model"):
        library.entry("missing")
    with pytest.raises(FileNotFoundError):
        library.verify("general")
    write_model(library.path("general"))
    assert library.verify("general") == tmp_path / "general/qwen3-0.6b"
    (library.path("general") / "config.json").write_text('{"model_type":"wrong"}')
    with pytest.raises(ValueError, match="architecture"):
        library.verify("general")


def test_absolute_paths_and_invalid_registry(tmp_path):
    registry = tmp_path / "registry.yaml"
    entry = {"backend": "transformers", "path": str(tmp_path / "weights"), "capabilities": ["text"]}
    registry.write_text(yaml.safe_dump({"models": {"custom": entry}}))
    assert ModelLibrary(registry).path("custom") == tmp_path / "weights"
    registry.write_text(yaml.safe_dump({"models": {"a": entry, "b": entry}}))
    with pytest.raises(ValueError, match="own path"):
        ModelLibrary(registry)
    entry["backend"] = "api"
    registry.write_text(yaml.safe_dump({"models": {"custom": entry}}))
    with pytest.raises(ValueError, match="backend"):
        ModelLibrary(registry)


def test_models_coexist_in_category_and_resolve_without_cwd(tmp_path, monkeypatch):
    root = tmp_path / "models"
    root.mkdir()
    registry = root / "model_library.yaml"
    entries = {
        model_id: {
            "category": "general", "format": "safetensors", "backend": "transformers",
            "path": f"general/{directory}", "capabilities": ["text"],
        }
        for model_id, directory in [("first-id", "qwen3-0.6b-v1"), ("second-id", "qwen3-0.6b-v2")]
    }
    registry.write_text(yaml.safe_dump({"models": entries}))
    monkeypatch.chdir(tmp_path)
    library = ModelLibrary(registry)
    for model_id in entries:
        directory = root / entries[model_id]["path"]
        write_model(directory)
        assert library.path(model_id) == directory
        assert library.verify(model_id) == directory
    assert library.path("first-id") != library.path("second-id")


@pytest.mark.parametrize("path,category", [
    ("general", "general"), ("general/../model", "general"),
    ("coding/model", "general"), ("general/model with spaces", "general"),
    ("general/model", "unknown"),
])
def test_invalid_category_directories(tmp_path, path, category):
    registry = tmp_path / "registry.yaml"
    registry.write_text(yaml.safe_dump({"models": {"id": {
        "backend": "transformers", "format": "safetensors", "category": category,
        "path": path, "capabilities": ["text"],
    }}}))
    with pytest.raises(ValueError):
        ModelLibrary(registry)


def test_gguf_directory_download_and_auxiliary_cache(tmp_path):
    registry = tmp_path / "model_library.yaml"
    registry.write_text(yaml.safe_dump({"models": {"quantized-id": {
        "category": "general", "format": "gguf", "backend": "llama_cpp",
        "path": "general/model-q4-k-m", "filename": "weights.gguf",
        "repo_id": "account/model", "revision": "pinned-commit", "quantization": "Q4_K_M",
        "auxiliary_files": ["projector.gguf"], "capabilities": ["text", "structured"],
    }}}))
    library = ModelLibrary(registry)
    folder = tmp_path / "general/model-q4-k-m"
    assert library.path("quantized-id") == folder
    hub = MagicMock()

    def download(repo_id, filename, **kwargs):
        target = Path(kwargs["local_dir"]) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"GGUFtest fixture")
        return str(target)

    hub.hf_hub_download.side_effect = download
    with patch.dict("sys.modules", {"huggingface_hub": hub}):
        assert library.download("quantized-id") == folder / "weights.gguf"
        assert library.download("quantized-id") == folder / "weights.gguf"
    assert hub.hf_hub_download.call_count == 2
    assert all(call.kwargs["local_dir"] == folder for call in hub.hf_hub_download.call_args_list)
    assert all(call.kwargs["revision"] == "pinned-commit" for call in hub.hf_hub_download.call_args_list)
    assert library.entry("quantized-id")["quantization"] == "Q4_K_M"
    (folder / "projector.gguf").unlink()
    with pytest.raises(FileNotFoundError, match="auxiliary"):
        library.verify("quantized-id")
    # Loader receives the selected GGUF file, while registration selects a directory.
    (folder / "projector.gguf").write_bytes(b"GGUFprojector")
    models = LocalModels(ROOT)
    models.library = library
    with patch("letssee_llm.inference.GGUFModel") as wrapper:
        models.get("quantized-id")
    wrapper.assert_called_once_with(str(folder / "weights.gguf"), {})


def test_legacy_gguf_file_entry_still_resolves(tmp_path):
    weight = tmp_path / "legacy/model.gguf"
    weight.parent.mkdir()
    weight.write_bytes(b"GGUFfixture")
    registry = tmp_path / "model_library.yaml"
    registry.write_text(yaml.safe_dump({"models": {"old-id": {
        "backend": "llama_cpp", "path": "legacy/model.gguf", "capabilities": ["text"],
    }}}))
    assert ModelLibrary(registry).verify("old-id") == weight


def test_download_cache_and_incomplete_resume(tmp_path):
    library = ModelLibrary(ROOT / "models/model_library.yaml", tmp_path)
    hub = MagicMock()
    hub.snapshot_download.side_effect = lambda *a, **kw: write_model(Path(kw["local_dir"]))
    with patch.dict("sys.modules", {"huggingface_hub": hub}):
        path = library.download("general")
        assert library.download("general") == path
        assert hub.snapshot_download.call_count == 1
        # Missing auxiliary files must trigger a resume, not a false cache hit.
        (path / "tokenizer_config.json").unlink()
        library.download("general")
        assert hub.snapshot_download.call_count == 2
        assert hub.snapshot_download.call_args.kwargs["local_dir"] == path


def test_shards_and_vlm_auxiliary_files(tmp_path):
    library = ModelLibrary(ROOT / "models/model_library.yaml", tmp_path)
    path = library.path("vision")
    write_model(path, "qwen3_vl")
    with pytest.raises(FileNotFoundError, match="chat template"):
        library.verify("vision")
    (path / "chat_template.jinja").write_text("template")
    with pytest.raises(FileNotFoundError, match="preprocessor"):
        library.verify("vision")
    (path / "preprocessor_config.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="video_preprocessor"):
        library.verify("vision")
    (path / "video_preprocessor_config.json").write_text("{}")
    (path / "model.safetensors.index.json").write_text(json.dumps({"weight_map": {"weight": "shard.safetensors"}}))
    with pytest.raises(FileNotFoundError, match="shard"):
        library.verify("vision")
    (path / "shard.safetensors").write_text("weights")
    assert library.verify("vision") == path


def test_templates_and_schema_loading():
    template = load_template(ROOT / "prompts", "object_recognition")
    assert template["model"] == "vision"
    assert template["generation"]["temperature"] == 0
    assert load_template(ROOT / "prompts", "") == {}
    schema = load_schema(ROOT / "schemas", "object_recognition")
    assert schema["properties"]["objects"]["items"]["properties"]["confidence"]["maximum"] == 1
    assert load_schema(ROOT / "schemas", "") is None
    with pytest.raises(FileNotFoundError):
        load_schema(ROOT / "schemas", "missing")
    with pytest.raises(ValueError, match="identifier"):
        load_schema(ROOT / "schemas", "../object_recognition")


def test_schema_definition_and_unsupported_features(tmp_path):
    (tmp_path / "invalid.schema.json").write_text('{"type":"imaginary"}')
    with pytest.raises(SchemaError):
        load_schema(tmp_path, "invalid")
    for schema in [
        {"type": "string", "pattern": "abc"},
        {"type": "object", "$ref": "https://example.com/schema"},
        {"type": "object", "additionalProperties": True},
        {"type": "number", "minimum": 0, "maximum": 1},
        {"type": "array"},
    ]:
        with pytest.raises(ValueError):
            decoding_schema(schema)
    assert decoding_schema({"type": "number", "enum": [0.0, 1.0], "minimum": 0, "maximum": 1}) == {
        "type": "number", "enum": [0.0, 1.0]
    }
    with pytest.raises(ValueError, match="Enum values"):
        decoding_schema({"type": "number", "enum": [2], "maximum": 1})


def test_valid_and_invalid_structured_responses():
    schema = load_schema(ROOT / "schemas", "object_recognition")
    text = '{"objects":[{"label":"robot","confidence":0.8}]}'
    assert json.loads(validate_response(text, schema))["objects"][0]["label"] == "robot"
    for text in ['{"objects":[{"label":"robot","confidence":1.2}]}', '{"extra":true}', '{"objects":[{}]}']:
        with pytest.raises(ValidationError):
            validate_response(text, schema)
    for text in ["not JSON", '```json\n{"objects":[]}\n```', '{"objects":[{"label":"x","confidence":NaN}]}']:
        with pytest.raises(ValueError):
            validate_response(text, schema)


def test_model_dispatch_templates_and_schema_validation(tmp_path):
    models = LocalModels(ROOT, tmp_path)
    backend = MagicMock()
    models.loaded["general"] = backend
    backend.generate.return_value = '{"response":"hello"}'
    result = models.generate("Hi", prompt_template="general", schema_id="structured_response")
    assert json.loads(result) == {"response": "hello"}
    assert backend.generate.call_args.kwargs["schema"]["type"] == "object"
    assert backend.generate.call_args.kwargs["max_tokens"] == 128
    backend.generate.return_value = "unrestricted"
    assert models.generate("Hi", schema_id="") == "unrestricted"
    assert backend.generate.call_args.kwargs["schema"] is None
    with pytest.raises(ValueError, match="vision"):
        models.generate("Image", model_id="general", image=object())
    backend.generate.return_value = '{"wrong":true}'
    with pytest.raises(ValidationError):
        models.generate("Hi", schema_id="structured_response")
    before = backend.generate.call_count
    with pytest.raises(FileNotFoundError):
        models.generate("Hi", schema_id="missing")
    assert backend.generate.call_count == before


def test_gguf_grammar_is_passed_to_backend(tmp_path):
    llama = MagicMock()
    llama.Llama.return_value.create_chat_completion.return_value = {
        "choices": [{"message": {"content": '{"response":"ok"}'}}]
    }
    with patch.dict("sys.modules", {"llama_cpp": llama}):
        wrapper = GGUFModel(str(tmp_path / "model.gguf"), {"n_ctx": 1024})
        schema = load_schema(ROOT / "schemas", "structured_response")
        assert wrapper.generate("Hi", schema=schema) == '{"response":"ok"}'
        llama.LlamaGrammar.from_json_schema.assert_called_once()
        assert wrapper.model.create_chat_completion.call_args.kwargs["grammar"] is llama.LlamaGrammar.from_json_schema.return_value
        with pytest.raises(ValueError, match="Unsupported schema"):
            wrapper.generate("Hi", schema={"type": "string", "pattern": "abc"})


def test_native_wrappers_are_loaded_once(tmp_path):
    models = LocalModels(ROOT, tmp_path)
    llm, vlm = MagicMock(), MagicMock()
    with patch.dict("sys.modules", {
        "letssee_llm.local_llm": SimpleNamespace(LocalLLM=llm),
        "letssee_llm.local_vlm": SimpleNamespace(LocalVLM=vlm),
    }), patch.object(models.library, "verify", return_value=tmp_path):
        assert models.get("general") is models.get("general")
        assert models.get("vision") is models.get("vision")
    llm.assert_called_once_with(str(tmp_path), "cpu", local_files_only=True, dtype="auto")
    vlm.assert_called_once_with(str(tmp_path), "cpu")


@pytest.mark.parametrize("tokens,temperature", [(0, 0), (-1, 0), (1.5, 0), (10, -1), (10, float("nan"))])
def test_invalid_generation_parameters(tokens, temperature):
    with pytest.raises(ValueError):
        generation_options(tokens, temperature)
