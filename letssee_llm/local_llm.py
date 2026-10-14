"""A directly accessible Hugging Face model, independent of ROS 2."""

import torch
from transformers import (
    AutoModelForCausalLM, AutoTokenizer, PreTrainedModel, PreTrainedTokenizerBase,
)

from .structured import generation_options, logits_processor


class LocalLLM:
    """Load once and generate text locally with greedy decoding."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen3-0.6B",
        device: str = "cpu",
        max_new_tokens: int = 128,
        *,
        local_files_only: bool = False,
        dtype: str | None = None,
    ) -> None:
        if max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be positive")
        self.max_new_tokens = max_new_tokens
        options = {"local_files_only": True} if local_files_only else {}
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, **options)
        if dtype is not None:
            options["dtype"] = dtype
        # Eager attention keeps attention patterns accessible for later research.
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name, attn_implementation="eager", **options
        ).to(device)
        self.model.eval()

    def generate(
        self, prompt: str, *, system_prompt: str = "", schema: dict | None = None,
        max_tokens: int | None = None, temperature: float = 0.0,
    ) -> str:
        """Return only the newly generated tokens, without the input prompt."""
        has_chat_template = bool(self.tokenizer.chat_template)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        if has_chat_template:
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        elif system_prompt:
            prompt = f"{system_prompt}\n\n{prompt}"
        inputs = self.tokenizer(
            prompt, return_tensors="pt", add_special_tokens=not has_chat_template
        ).to(self.model.device)
        options = generation_options(
            self.max_new_tokens if max_tokens is None else max_tokens, temperature
        )
        options["pad_token_id"] = self.tokenizer.eos_token_id
        if schema is not None:
            # This masks invalid next tokens; the prompt is not the constraint.
            options["logits_processor"] = [
                logits_processor(self.model, self.tokenizer, schema)
            ]
        # Disable gradients only during generation; direct model calls stay unrestricted.
        with torch.no_grad():
            output = self.model.generate(
                **inputs,
                **options,
            )
        new_tokens = output[0][inputs["input_ids"].shape[-1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True)

    def get_model(self) -> PreTrainedModel:
        """Return the original PyTorch model for inspection and hooks."""
        return self.model

    def get_tokenizer(self) -> PreTrainedTokenizerBase:
        """Return the original tokenizer."""
        return self.tokenizer
