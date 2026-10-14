"""ROS service setup; inference remains in the ROS-independent model layer."""

from pathlib import Path

import rclpy
from rclpy.executors import ExternalShutdownException
from rcl_interfaces.msg import ParameterDescriptor

from ..inference import LocalModels


def configure_models(node) -> LocalModels:
    """Read startup-only asset paths and inference device."""
    source = Path(__file__).resolve().parents[2]
    if (source / "models/model_library.yaml").is_file():
        default_data = str(source)
        default_models = str(source / "models")
    else:
        from ament_index_python.packages import get_package_share_directory

        default_data = get_package_share_directory("letssee")
        default_models = str(Path.home() / ".cache/letssee/models")
    descriptor = ParameterDescriptor(read_only=True)
    data_dir = node.declare_parameter("data_dir", default_data, descriptor).value
    model_root = node.declare_parameter("model_root", default_models, descriptor).value
    device = node.declare_parameter("device", "cpu", descriptor).value
    return LocalModels(data_dir, model_root, device)


def run(node_class, args: list[str] | None = None) -> None:
    """Spin one synchronous service and clean up on shutdown."""
    rclpy.init(args=args)
    node = None
    try:
        node = node_class()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
