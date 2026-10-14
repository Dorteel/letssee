"""Text generation using independently reusable models, prompts, and schemas."""

from rclpy.node import Node
from letssee.srv import GenerateText

from . import configure_models, run


class MinimalService(Node):
    """Serve registered local language models, loading each at most once."""

    def __init__(self) -> None:
        super().__init__("generate_text_service")
        try:
            self.models = configure_models(self)
            self.srv = self.create_service(
                GenerateText, "/llm/generate_text", self.generate_callback
            )
        except Exception:
            self.destroy_node()
            raise

    def generate_callback(
        self, request: GenerateText.Request, response: GenerateText.Response,
    ) -> GenerateText.Response:
        """Delegate inference and report explicit failures."""
        response.success, response.response, response.error_message = False, "", ""
        try:
            response.response = self.models.generate(
                request.prompt, model_id=request.model_id,
                prompt_template=request.prompt_template, schema_id=request.schema_id,
            )
            response.success = True
        except Exception as error:
            response.error_message = str(error)
            self.get_logger().error(response.error_message)
        return response


def main(args: list[str] | None = None) -> None:
    """Start the text service."""
    run(MinimalService, args)
