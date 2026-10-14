"""Native PyTorch vision-language inference with accessible model internals."""

import torch
from PIL import Image
from transformers import (
    AutoModelForImageTextToText, AutoProcessor, PreTrainedModel, PreTrainedTokenizerBase,
)

from .structured import generation_options, logits_processor


class LocalVLM:
    """Load a local VLM and its image processor once."""

    def __init__(self, model_path: str, device: str = "cpu") -> None:
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path, local_files_only=True, dtype="auto", attn_implementation="eager"
        ).to(device)
        self.model.eval()

    def generate(
        self, prompt: str, *, image: Image.Image | None = None, system_prompt: str = "",
        schema: dict | None = None, max_tokens: int = 512, temperature: float = 0.0,
    ) -> str:
        """Process a PIL image and mask output tokens when a schema is provided."""
        content = [{"type": "text", "text": prompt}]
        if image is not None:
            content.insert(0, {"type": "image", "image": image})
        messages = []
        if system_prompt:
            messages.append({
                "role": "system", "content": [{"type": "text", "text": system_prompt}]
            })
        messages.append({"role": "user", "content": content})
        inputs = self.processor.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True,
            return_dict=True, return_tensors="pt",
        ).to(self.model.device)
        options = generation_options(max_tokens, temperature)
        if schema is not None:
            options["logits_processor"] = [
                logits_processor(self.model, self.get_tokenizer(), schema)
            ]
        with torch.no_grad():
            output = self.model.generate(**inputs, **options)
        return self.processor.decode(
            output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True
        )

    def get_model(self) -> PreTrainedModel:
        """Return the original PyTorch VLM, including its vision encoder."""
        return self.model

    def get_tokenizer(self) -> PreTrainedTokenizerBase:
        """Return the VLM's text tokenizer."""
        return self.processor.tokenizer
