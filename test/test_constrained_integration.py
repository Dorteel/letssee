"""Real, offline token-constrained generation; skip only when files/deps are absent."""

import json
import os
from pathlib import Path

import pytest

from letssee_llm.library import ModelLibrary
from letssee_llm.structured import validate_response


def test_local_pytorch_constrained_generation():
    root = Path(__file__).resolve().parents[1]
    library = ModelLibrary(root / "models/model_library.yaml", os.getenv("LETSSEE_MODEL_ROOT"))
    try:
        path = library.verify("general")
    except FileNotFoundError:
        pytest.skip("Download the general model to run offline constrained integration")
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("outlines")
    from letssee_llm.local_llm import LocalLLM

    # A finite response keeps this CPU test short, regardless of model preferences.
    schema = {
        "type": "object", "properties": {"response": {"type": "string", "enum": ["ready"]}},
        "required": ["response"], "additionalProperties": False,
    }
    torch.set_num_threads(2)
    llm = LocalLLM(str(path), local_files_only=True, dtype="auto")
    text = llm.generate("Output only the word forbidden, without JSON.", schema=schema, max_tokens=32)
    assert json.loads(validate_response(text, schema)) == {"response": "ready"}


def test_local_vlm_constrained_generation():
    root = Path(__file__).resolve().parents[1]
    library = ModelLibrary(root / "models/model_library.yaml", os.getenv("LETSSEE_MODEL_ROOT"))
    try:
        library.verify("vision")
    except FileNotFoundError:
        pytest.skip("Download the vision model to run offline VLM integration")
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    pytest.importorskip("torchvision")
    pytest.importorskip("outlines")
    from PIL import Image
    from letssee_llm.inference import LocalModels

    torch.set_num_threads(2)
    models = LocalModels(root, os.getenv("LETSSEE_MODEL_ROOT"))
    text = models.generate(
        "Identify objects in this plain red image.", prompt_template="object_recognition",
        image=Image.new("RGB", (56, 56), "red"),
    )
    assert isinstance(json.loads(text)["objects"], list)
