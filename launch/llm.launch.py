"""Launch exactly one local service, restricted to one registered model."""

from pathlib import Path
import xml.etree.ElementTree as ET

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

from letssee_llm.library import ModelLibrary


def selected_service(context):
    """Validate metadata before starting a node; never load weights in launch."""
    share = Path(__file__).resolve().parents[1]
    package = ET.parse(share / "package.xml").getroot().findtext("name")
    service = LaunchConfiguration("service").perform(context)
    model = LaunchConfiguration("model").perform(context)
    library = ModelLibrary(share / "models/model_library.yaml")
    capability = "vision" if service == "vlm" else "text"
    if capability not in library.entry(model)["capabilities"]:
        raise ValueError(f"Model {model!r} does not support {capability} for service {service!r}")
    executable = "vlm_service" if service == "vlm" else "generate_text_service"
    return [Node(
        package=package, executable=executable, output="screen",
        # Use the active Python environment rather than the installed script's shebang.
        prefix=["python3"], parameters=[{"model_id": ParameterValue(model, value_type=str)}],
    )]


def generate_launch_description() -> LaunchDescription:
    """Expose only service and model selection; model_root remains a node setting."""
    return LaunchDescription([
        DeclareLaunchArgument("service", default_value="llm", choices=["llm", "vlm"]),
        DeclareLaunchArgument("model", default_value="general"),
        OpaqueFunction(function=selected_service),
    ])
