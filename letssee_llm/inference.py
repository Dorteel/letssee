"""Small, ROS-independent bridge between assets and local model backends."""

import json
from pathlib import Path

from .library import ModelLibrary, load_template
from .structured import decoding_schema, generation_options, load_schema, validate_response


class GGUFModel:
    """Use llama.cpp's native JSON grammar; GGUF does not expose PyTorch weights."""

    def __init__(self, path: str, options: dict) -> None:
        from llama_cpp import Llama

        if set(options) - {"n_ctx", "n_gpu_layers", "n_threads", "seed"}:
            raise ValueError("Unsupported llama.cpp model options")
        self.model = Llama(model_path=path, **options)

    def generate(
        self, prompt: str, *, system_prompt: str = "", schema: dict | None = None,
        max_tokens: int = 128, temperature: float = 0.0,
    ) -> str:
        """Generate a chat response, optionally constrained by a compiled grammar."""
        from llama_cpp import LlamaGrammar

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        options = {}
        if schema is not None:
            options["grammar"] = LlamaGrammar.from_json_schema(
                json.dumps(decoding_schema(schema)), verbose=False
            )
        result = self.model.create_chat_completion(
            messages=messages, max_tokens=max_tokens, temperature=temperature, **options
        )
        return result["choices"][0]["message"]["content"]


class LocalModels:
    """Resolve task defaults and cache each model on its first request."""

    def __init__(
        self, data_dir: str | Path, model_root: str | Path | None = None,
        device: str = "cpu",
        selected_model: str = "",
    ) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.library = ModelLibrary(self.data_dir / "models/model_library.yaml", model_root)
        self.device = device
        self.loaded = {}
        self.selected_model = selected_model
        if selected_model:
            self.library.entry(selected_model)

    def get(self, model_id: str):
        """Return the cached wrapper, loading only verified local files."""
        if self.selected_model and model_id != self.selected_model:
            raise ValueError(f"Service is restricted to model {self.selected_model!r}; requested {model_id!r}")
        if model_id not in self.loaded:
            entry = self.library.entry(model_id)
            path = str(self.library.verify(model_id))
            if entry["backend"] == "llama_cpp":
                model = GGUFModel(path, entry.get("options", {}))
            elif "vision" in entry["capabilities"]:
                from .local_vlm import LocalVLM

                model = LocalVLM(path, self.device)
            else:
                from .local_llm import LocalLLM

                model = LocalLLM(path, self.device, local_files_only=True, dtype="auto")
            self.loaded[model_id] = model
        return self.loaded[model_id]

    def generate(
        self, prompt: str, *, model_id: str = "", prompt_template: str = "",
        schema_id: str | None = None, image=None,
    ) -> str:
        """Resolve assets, enforce constraints, and validate structured responses.

        None uses a template's schema default; an empty string explicitly disables it.
        ROS requests always pass their schema_id, so an empty request stays unrestricted.
        """
        template = load_template(self.data_dir / "prompts", prompt_template)
        if self.selected_model:
            if model_id and model_id != self.selected_model:
                raise ValueError(f"Service is restricted to model {self.selected_model!r}; requested {model_id!r}")
            model_id = self.selected_model
        else:
            model_id = model_id or template.get("model", "vision" if image is not None else "general")
        schema_id = template.get("schema", "") if schema_id is None else schema_id
        schema = load_schema(self.data_dir / "schemas", schema_id)
        entry = self.library.entry(model_id)
        capability = "vision" if image is not None else "text"
        if capability not in entry["capabilities"]:
            raise ValueError(f"Model {model_id} does not support {capability}")
        if schema is not None and "structured" not in entry["capabilities"]:
            raise ValueError(f"Model {model_id} does not support constrained decoding")
        generation = {"max_tokens": 128, "temperature": 0.0, **template.get("generation", {})}
        # Validate parameters even for llama.cpp, before loading a potentially large model.
        generation_options(generation["max_tokens"], generation["temperature"])
        options = {"system_prompt": template.get("system_prompt", ""), "schema": schema, **generation}
        if image is not None:
            options["image"] = image
        text = self.get(model_id).generate(prompt, **options)
        return validate_response(text, schema) if schema is not None else text
