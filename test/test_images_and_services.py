"""Image layouts, VLM preprocessing, and short ROS callbacks with mocked models."""

import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from letssee_llm.images import to_pil


def image(encoding="rgb8", data=bytes([255, 0, 0]), step=3):
    return SimpleNamespace(width=1, height=1, encoding=encoding, data=data, step=step)


@pytest.mark.parametrize("encoding,data,step", [
    ("rgb8", bytes([255, 0, 0, 99]), 4),
    ("bgr8", bytes([0, 0, 255]), 3),
    ("rgba8", bytes([255, 0, 0, 255]), 4),
    ("bgra8", bytes([0, 0, 255, 255]), 4),
])
def test_color_channels_and_padding(encoding, data, step):
    assert to_pil(image(encoding, data, step)).getpixel((0, 0)) == (255, 0, 0)


def test_mono_and_invalid_images():
    assert to_pil(image("mono8", b"\x80", 1)).getpixel((0, 0)) == (128, 128, 128)
    for message in [image("16UC1"), image(step=2), image(data=b""), image()]:
        if message.encoding == "rgb8" and message.step == 3 and message.data:
            message.width = 0
        with pytest.raises(ValueError):
            to_pil(message)


def test_padding_between_rows():
    message = image(data=bytes([255, 0, 0, 99, 0, 255, 0, 99]), step=4)
    message.height = 2
    result = to_pil(message)
    assert result.getpixel((0, 0)) == (255, 0, 0)
    assert result.getpixel((0, 1)) == (0, 255, 0)


def test_vlm_processor_and_output_slicing():
    transformers, torch = MagicMock(), MagicMock()
    with patch.dict(sys.modules, {"transformers": transformers, "torch": torch}):
        sys.modules.pop("letssee_llm.local_vlm", None)
        module = importlib.import_module("letssee_llm.local_vlm")
        try:
            wrapper = module.LocalVLM("local/vision", "cpu")
            inputs = MagicMock()
            inputs.keys.return_value = ["input_ids"]
            inputs.__getitem__.return_value = SimpleNamespace(shape=(1, 2))
            wrapper.processor.apply_chat_template.return_value.to.return_value = inputs
            wrapper.model.generate.return_value = [[1, 2, 3]]
            wrapper.processor.decode.return_value = "robot"
            pil = to_pil(image())
            assert wrapper.generate("Identify", image=pil) == "robot"
            messages = wrapper.processor.apply_chat_template.call_args.args[0]
            assert messages[0]["content"][0]["image"] is pil
            wrapper.processor.decode.assert_called_once_with([3], skip_special_tokens=True)
            assert wrapper.get_model() is wrapper.model
            assert wrapper.get_tokenizer() is wrapper.processor.tokenizer
            marker = object()
            with patch.object(module, "logits_processor", return_value=marker):
                wrapper.generate(
                    "Identify", image=pil, system_prompt="Observe carefully",
                    schema={"type": "string"},
                )
            assert wrapper.model.generate.call_args.kwargs["logits_processor"] == [marker]
            messages = wrapper.processor.apply_chat_template.call_args.args[0]
            assert messages[0] == {
                "role": "system", "content": [{"type": "text", "text": "Observe carefully"}]
            }
        finally:
            sys.modules.pop("letssee_llm.local_vlm", None)


@pytest.mark.parametrize("module_name,callback,with_image", [
    ("llm_service", "generate_callback", False),
    ("vlm_service", "analyze_callback", True),
])
def test_mocked_ros_requests(module_name, callback, with_image):
    # Mock ROS imports so these callback tests run before building the interfaces.
    dependencies = {
        "rclpy": MagicMock(), "rclpy.node": SimpleNamespace(Node=object),
        "rclpy.executors": MagicMock(), "rcl_interfaces": MagicMock(),
        "rcl_interfaces.msg": MagicMock(), "letssee": MagicMock(), "letssee.srv": MagicMock(),
    }
    name = f"letssee_llm.services.{module_name}"
    with patch.dict(sys.modules, dependencies):
        sys.modules.pop("letssee_llm.services", None)
        sys.modules.pop(name, None)
        module = importlib.import_module(name)
        try:
            node = SimpleNamespace(models=MagicMock(), get_logger=MagicMock())
            node.models.generate.return_value = '{"response":"ok"}'
            request = SimpleNamespace(prompt="Hi", model_id="general", prompt_template="general", schema_id="structured_response")
            if with_image:
                request.image = image()
                request.model_id = "vision"
            response = SimpleNamespace()
            result = getattr(module.MinimalService, callback)(node, request, response)
            assert result is response and result.success
            assert result.error_message == ""
            assert node.models.generate.call_args.kwargs["schema_id"] == "structured_response"
            if with_image:
                assert node.models.generate.call_args.kwargs["image"].mode == "RGB"
            node.models.generate.side_effect = ValueError("Unsupported schema feature")
            result = getattr(module.MinimalService, callback)(node, request, response)
            assert not result.success and result.response == ""
            assert "Unsupported schema" in result.error_message
        finally:
            sys.modules.pop(name, None)
            sys.modules.pop("letssee_llm.services", None)
