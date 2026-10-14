"""Test-process-only initialization tracing and optional weight-free backends."""

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

if os.getenv("LETSSEE_LOAD_TRACE"):
    from letssee_llm.inference import LocalModels
    from letssee_llm.library import ModelLibrary

    original_get = LocalModels.get

    def traced_get(self, model_id):
        already_loaded = model_id in self.loaded
        result = original_get(self, model_id)
        if not already_loaded:
            with open(os.environ["LETSSEE_LOAD_TRACE"], "a") as stream:
                stream.write(json.dumps(model_id) + "\n")
        return result

    LocalModels.get = traced_get
    if os.getenv("LETSSEE_TEST_MOCK") == "1":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from service_fixture import FixtureModel

        ModelLibrary.verify = lambda self, model_id: self.path(model_id)
        sys.modules["letssee_llm.local_llm"] = SimpleNamespace(LocalLLM=FixtureModel)
        sys.modules["letssee_llm.local_vlm"] = SimpleNamespace(LocalVLM=FixtureModel)
