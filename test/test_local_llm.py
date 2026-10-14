"""Exercise the wrapper without installing ML libraries or downloading weights."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def wrapper():
    torch = MagicMock()
    transformers = MagicMock()
    # Keep dependency mocks scoped so other tests can import the real libraries.
    with patch.dict(sys.modules, {"torch": torch, "transformers": transformers}):
        sys.modules.pop("letssee_llm.local_llm", None)
        module = importlib.import_module("letssee_llm.local_llm")
        yield module.LocalLLM, torch, transformers
        sys.modules.pop("letssee_llm.local_llm", None)


def test_load_once_and_expose_original_objects(wrapper):
    LocalLLM, _, transformers = wrapper
    llm = LocalLLM("local/model", "cuda", 12)
    transformers.AutoTokenizer.from_pretrained.assert_called_once_with("local/model")
    transformers.AutoModelForCausalLM.from_pretrained.assert_called_once_with(
        "local/model", attn_implementation="eager"
    )
    transformers.AutoModelForCausalLM.from_pretrained.return_value.to.assert_called_once_with("cuda")
    assert llm.get_model() is llm.model
    assert llm.get_tokenizer() is llm.tokenizer
    llm.model.eval.assert_called_once()
    llm.generate("one")
    llm.generate("two")
    assert transformers.AutoModelForCausalLM.from_pretrained.call_count == 1


def test_generation_formats_chat_and_removes_input_tokens(wrapper):
    LocalLLM, torch, _ = wrapper
    llm = LocalLLM(max_new_tokens=7)
    inputs = MagicMock()
    inputs.keys.return_value = ["input_ids", "attention_mask"]
    inputs.__getitem__.side_effect = {
        "input_ids": MagicMock(shape=(1, 3)), "attention_mask": MagicMock()
    }.__getitem__
    llm.tokenizer.return_value.to.return_value = inputs
    llm.model.generate.return_value = [[1, 2, 3, 4, 5]]
    llm.tokenizer.decode.return_value = "hello"
    assert llm.generate("question") == "hello"
    llm.tokenizer.apply_chat_template.assert_called_once_with(
        [{"role": "user", "content": "question"}],
        tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
    llm.tokenizer.decode.assert_called_once_with([4, 5], skip_special_tokens=True)
    kwargs = llm.model.generate.call_args.kwargs
    assert kwargs["max_new_tokens"] == 7
    assert kwargs["do_sample"] is False
    assert kwargs["num_beams"] == 1
    torch.no_grad.assert_called_once()


def test_plain_tokenizer_and_invalid_length(wrapper):
    LocalLLM, _, transformers = wrapper
    with pytest.raises(ValueError, match="positive"):
        LocalLLM(max_new_tokens=0)
    transformers.AutoModelForCausalLM.from_pretrained.assert_not_called()
    llm = LocalLLM()
    llm.tokenizer.chat_template = None
    llm.generate("plain prompt")
    llm.tokenizer.apply_chat_template.assert_not_called()
    llm.tokenizer.assert_called_once_with(
        "plain prompt", return_tensors="pt", add_special_tokens=True
    )


def test_constraints_are_passed_and_never_silently_disabled(wrapper):
    LocalLLM, _, _ = wrapper
    llm = LocalLLM()
    module = sys.modules[LocalLLM.__module__]
    marker = object()
    schema = {"type": "string", "enum": ["ready"]}
    with patch.object(module, "logits_processor", return_value=marker) as constraints:
        llm.generate("Hi", schema=schema)
        constraints.assert_called_once_with(llm.model, llm.tokenizer, schema)
        assert llm.model.generate.call_args.kwargs["logits_processor"] == [marker]
    llm.model.generate.reset_mock()
    with patch.object(module, "logits_processor", side_effect=ImportError("Install Outlines")):
        with pytest.raises(ImportError, match="Outlines"):
            llm.generate("Hi", schema=schema)
    llm.model.generate.assert_not_called()
