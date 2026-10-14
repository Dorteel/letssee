"""Image analysis using the same local registry and structured decoding."""

from rclpy.node import Node
from letssee.srv import AnalyzeImage

from ..images import to_pil
from . import configure_models, run


class MinimalService(Node):
    """Serve local VLMs using sensor_msgs/Image requests."""

    def __init__(self) -> None:
        super().__init__("vlm_service")
        try:
            self.models = configure_models(self)
            self.srv = self.create_service(
                AnalyzeImage, "/vlm/analyze_image", self.analyze_callback
            )
        except Exception:
            self.destroy_node()
            raise

    def analyze_callback(
        self, request: AnalyzeImage.Request, response: AnalyzeImage.Response,
    ) -> AnalyzeImage.Response:
        """Convert the image, delegate inference, and return explicit errors."""
        response.success, response.response, response.error_message = False, "", ""
        try:
            response.response = self.models.generate(
                request.prompt, image=to_pil(request.image), model_id=request.model_id,
                prompt_template=request.prompt_template, schema_id=request.schema_id,
            )
            response.success = True
        except Exception as error:
            response.error_message = str(error)
            self.get_logger().error(response.error_message)
        return response


def main(args: list[str] | None = None) -> None:
    """Start the image analysis service."""
    run(MinimalService, args)
