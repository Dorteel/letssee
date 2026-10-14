"""Validate launch selection without ROS processes or loading model weights."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("service,model,executable", [
    ("llm", "coding", "generate_text_service"), ("vlm", "vision", "vlm_service"),
])
def test_launch_starts_only_selected_node(service, model, executable):
    launch_node = MagicMock()
    configuration = lambda key: SimpleNamespace(perform=lambda context: context[key])
    dependencies = {
        "launch": MagicMock(), "launch.actions": MagicMock(),
        "launch.substitutions": SimpleNamespace(LaunchConfiguration=configuration),
        "launch_ros": MagicMock(), "launch_ros.actions": SimpleNamespace(Node=launch_node),
        "launch_ros.parameter_descriptions": SimpleNamespace(ParameterValue=lambda value, **kw: value),
    }
    with patch.dict("sys.modules", dependencies):
        spec = importlib.util.spec_from_file_location("local_launch", ROOT / "launch/llm.launch.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        nodes = module.selected_service({"service": service, "model": model})
        assert len(nodes) == 1
        launch_node.assert_called_once()
        assert launch_node.call_args.kwargs["executable"] == executable
        assert launch_node.call_args.kwargs["parameters"] == [{"model_id": model}]
        with pytest.raises(ValueError, match="Unknown model"):
            module.selected_service({"service": service, "model": "missing"})
        with pytest.raises(ValueError, match="does not support vision"):
            module.selected_service({"service": "vlm", "model": "coding"})
