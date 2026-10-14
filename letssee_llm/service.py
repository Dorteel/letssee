"""Minimal synchronous ROS 2 service for local text generation."""

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rcl_interfaces.msg import ParameterDescriptor

from letssee.srv import Generate
from letssee_llm.local_llm import LocalLLM


class MinimalService(Node):
    """Serve one prompt at a time using a model loaded at startup."""

    def __init__(self) -> None:
        super().__init__("llm_service")
        try:
            # Startup-only parameters reflect the single model instance.
            descriptor = ParameterDescriptor(read_only=True)
            model_name = self.declare_parameter(
                "model_name", "Qwen/Qwen3-0.6B", descriptor
            ).value
            device = self.declare_parameter("device", "cpu", descriptor).value
            max_new_tokens = self.declare_parameter(
                "max_new_tokens", 128, descriptor
            ).value
            self.llm = LocalLLM(model_name, device, max_new_tokens)
            self.srv = self.create_service(Generate, "/llm/generate", self.generate_callback)
            self.get_logger().info("Ready on /llm/generate")
        except Exception:
            self.destroy_node()
            raise

    def generate_callback(
        self, request: Generate.Request, response: Generate.Response
    ) -> Generate.Response:
        """Fill the response using local inference."""
        try:
            response.response = self.llm.generate(request.prompt)
        except Exception as error:
            self.get_logger().error(f"Generation failed: {error}")
            # The minimal interface has no error field; leave the response empty.
            response.response = ""
        return response


def main(args: list[str] | None = None) -> None:
    """Initialize ROS, spin the service, and release resources on shutdown."""
    rclpy.init(args=args)
    node = None
    try:
        node = MinimalService()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
