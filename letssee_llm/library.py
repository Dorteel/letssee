"""Local model registry, reusable templates, and resumable downloads."""

import argparse
import json
import os
from pathlib import Path
import re

import yaml


def load_yaml(path: Path) -> dict:
    """Read a YAML mapping without executing YAML constructors."""
    value = yaml.safe_load(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def asset_path(directory: Path, name: str, suffix: str) -> Path:
    """Resolve an asset identifier without allowing arbitrary file access."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError(f"Invalid asset identifier: {name!r}")
    path = (directory / f"{name}{suffix}").resolve()
    if path.parent != directory.resolve():
        raise ValueError("Asset path escapes its directory")
    return path


def load_template(directory: Path, name: str) -> dict:
    """Load a task template; an empty name selects no defaults."""
    if not name:
        return {}
    template = load_yaml(asset_path(directory, name, ".yaml"))
    generation = template.get("generation", {})
    if not isinstance(generation, dict) or set(generation) - {"temperature", "max_tokens"}:
        raise ValueError("Template generation supports temperature and max_tokens only")
    return template


class ModelLibrary:
    """Resolve registered models and check that their local files are complete."""

    def __init__(self, registry: str | Path, model_root: str | Path | None = None) -> None:
        self.registry = Path(registry).expanduser().resolve()
        self.root = Path(model_root).expanduser().resolve() if model_root else self.registry.parent
        self.models = load_yaml(self.registry).get("models")
        if not isinstance(self.models, dict) or not self.models:
            raise ValueError("Registry must contain a nonempty models mapping")
        paths = set()
        for model_id in self.models:
            entry = self.entry(model_id)
            path = self.path(model_id)
            legacy_gguf = entry["backend"] == "llama_cpp" and "category" not in entry and path.suffix.lower() == ".gguf"
            folder = path.parent if legacy_gguf else path
            if folder in paths:
                raise ValueError("Each registered model must have its own path")
            paths.add(folder)
            if not isinstance(entry.get("capabilities"), list):
                raise ValueError(f"Missing capability list for {model_id}")
            if entry["backend"] == "llama_cpp" and "vision" in entry["capabilities"]:
                raise ValueError("GGUF vision requires a model-specific projector; use transformers")

    def entry(self, model_id: str) -> dict:
        """Return metadata, rejecting unknown IDs and backends."""
        if model_id not in self.models:
            raise ValueError(f"Unknown model: {model_id!r}")
        entry = self.models[model_id]
        if not isinstance(entry, dict) or entry.get("backend") not in {"transformers", "llama_cpp"}:
            raise ValueError(f"Unsupported backend for {model_id}")
        if not isinstance(entry.get("path"), str) or not entry["path"]:
            raise ValueError(f"Missing model path for {model_id}")
        auxiliary = entry.get("auxiliary_files", [])
        if not isinstance(auxiliary, list) or any(
            not isinstance(name, str) or Path(name).name != name or name in {".", ".."}
            for name in auxiliary
        ):
            raise ValueError("Auxiliary filenames must be plain filenames")
        expected_format = "gguf" if entry["backend"] == "llama_cpp" else "safetensors"
        if entry.get("format", expected_format) != expected_format:
            raise ValueError(f"Model format does not match backend for {model_id}")
        if "category" in entry:
            category = entry["category"]
            parts = Path(entry["path"]).parts
            if category not in {"general", "coding", "vision"}:
                raise ValueError(f"Unsupported model category: {category}")
            if len(parts) != 2 or parts[0] != category or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", parts[1]):
                raise ValueError("Categorized model paths must be category/filesystem-safe-model-name")
            if parts[1] in {".", ".."}:
                raise ValueError("Invalid model directory name")
        return entry

    def path(self, model_id: str) -> Path:
        """Resolve relative paths against model_root, and expand absolute paths."""
        path = Path(os.path.expandvars(self.entry(model_id)["path"])).expanduser()
        return (path if path.is_absolute() else self.root / path).resolve()

    def gguf_path(self, model_id: str) -> Path:
        """Resolve a GGUF filename within its model directory; retain legacy file paths."""
        path = self.path(model_id)
        entry = self.entry(model_id)
        if "category" not in entry and path.suffix.lower() == ".gguf":
            return path
        filename = entry.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.lower().endswith(".gguf"):
            raise ValueError("GGUF directory entries require a plain .gguf filename")
        file = (path / filename).resolve()
        if file.parent != path:
            raise ValueError("GGUF filename escapes its model directory")
        return file

    def verify(self, model_id: str) -> Path:
        """Check architecture, tokenizer/processor files, and every weight shard."""
        entry = self.entry(model_id)
        path = self.path(model_id)
        if entry["backend"] == "llama_cpp":
            path = self.gguf_path(model_id)
            if not path.is_file() or path.suffix.lower() != ".gguf":
                raise FileNotFoundError(f"Missing GGUF file: {path}")
            with path.open("rb") as stream:
                if stream.read(4) != b"GGUF":
                    raise ValueError(f"Invalid GGUF header: {path}")
            for name in entry.get("auxiliary_files", []):
                file = path.parent / name
                if not file.is_file() or file.stat().st_size == 0:
                    raise FileNotFoundError(f"Missing or empty auxiliary file: {file}")
            return path
        config = json.loads((path / "config.json").read_text())
        if entry.get("model_type") and config.get("model_type") != entry["model_type"]:
            raise ValueError(f"Unexpected model architecture in {path}")
        required = [path / "tokenizer_config.json"]
        if not any((path / name).is_file() for name in ("tokenizer.json", "tokenizer.model", "vocab.json")):
            raise FileNotFoundError(f"Missing tokenizer vocabulary in {path}")
        if (path / "vocab.json").is_file() and not (path / "tokenizer.json").is_file():
            required.append(path / "merges.txt")
        if "vision" in entry["capabilities"]:
            required.append(path / "preprocessor_config.json")
            if entry.get("model_type") == "qwen3_vl":
                # Its AutoProcessor also initializes a video processor for image-only use.
                required.append(path / "video_preprocessor_config.json")
            if not any((path / name).is_file() for name in ("chat_template.json", "chat_template.jinja")):
                tokenizer_config = json.loads((path / "tokenizer_config.json").read_text())
                if not tokenizer_config.get("chat_template"):
                    raise FileNotFoundError(f"Missing VLM chat template in {path}")
        index = path / "model.safetensors.index.json"
        if index.is_file():
            shards = set(json.loads(index.read_text())["weight_map"].values())
            if not shards:
                raise ValueError("Empty weight index")
            for shard in shards:
                target = (path / shard).resolve()
                if target.parent != path:
                    raise ValueError("Weight shard escapes model directory")
                required.append(target)
        else:
            required.append(path / "model.safetensors")
        for file in required:
            if not file.is_file() or file.stat().st_size == 0:
                raise FileNotFoundError(f"Missing or empty model file: {file}")
        return path

    def download(self, model_id: str) -> Path:
        """Reuse complete files, or let Hugging Face resume an incomplete download."""
        try:
            return self.verify(model_id)
        except FileNotFoundError:
            pass
        from huggingface_hub import hf_hub_download, snapshot_download

        entry = self.entry(model_id)
        path = self.path(model_id)
        if not entry.get("repo_id"):
            raise ValueError(f"No download source for {model_id}; populate {path} manually")
        revision = entry.get("revision", "main")
        if entry["backend"] == "llama_cpp":
            filename = entry.get("filename")
            file = self.gguf_path(model_id)
            if not filename or Path(filename).name != file.name:
                raise ValueError("GGUF filename must match the registered path's basename")
            hf_hub_download(entry["repo_id"], filename, revision=revision, local_dir=file.parent)
            for auxiliary in entry.get("auxiliary_files", []):
                hf_hub_download(entry["repo_id"], auxiliary, revision=revision, local_dir=file.parent)
        else:
            snapshot_download(
                entry["repo_id"], revision=revision, local_dir=path,
                allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja"],
                max_workers=2,
            )
        return self.verify(model_id)


def main() -> None:
    """Attempt each selected download, reporting failures without hiding them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("model_ids", nargs="*")
    args = parser.parse_args()
    library = ModelLibrary(args.registry, args.model_root)
    failed = False
    for model_id in args.model_ids or library.models:
        try:
            print(f"{model_id}: {library.download(model_id)}", flush=True)
        except Exception as error:
            print(f"{model_id}: download failed: {error}", flush=True)
            failed = True
    raise SystemExit(1 if failed else 0)
