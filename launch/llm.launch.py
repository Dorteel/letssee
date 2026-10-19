"""Launch exactly one local service, restricted to one registered model."""

from pathlib import Path
import math
import os
import xml.etree.ElementTree as ET

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
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
    """Select one model, optionally asking several questions about one camera frame."""
    return LaunchDescription([
        DeclareLaunchArgument("service", default_value="llm", choices=["llm", "vlm"]),
        DeclareLaunchArgument("model", default_value="general"),
        DeclareLaunchArgument("test_camera", default_value="false", choices=["true", "false"]),
        DeclareLaunchArgument("camera_topic", default_value="/camera/image_raw"),
        DeclareLaunchArgument("camera_timeout", default_value="30.0"),
        DeclareLaunchArgument("service_timeout", default_value="30.0"),
        DeclareLaunchArgument("response_timeout", default_value="180.0"),
        DeclareLaunchArgument("camera_test_script", default_value="",
                              description="Optional absolute path to source test/test_camera.py"),
        OpaqueFunction(function=launch_with_camera_test),
    ])


def launch_with_camera_test(context):
    """Run the source-only camera experiment without changing package installation."""
    enabled = LaunchConfiguration("test_camera").perform(context) == "true"
    if enabled and LaunchConfiguration("service").perform(context) != "vlm":
        raise ValueError("test_camera:=true requires service:=vlm; text services cannot analyze images")
    actions = selected_service(context)
    if not enabled:
        return actions

    share = Path(__file__).resolve().parents[1]
    override = LaunchConfiguration("camera_test_script").perform(context)
    candidates = [Path(override).expanduser()] if override else [share / "test/test_camera.py"]
    if not override:
        model_root = os.getenv("LETSSEE_MODEL_ROOT")
        if model_root:
            candidates.append(Path(model_root).expanduser().resolve().parent / "test/test_camera.py")
        package = ET.parse(share / "package.xml").getroot().findtext("name")
        for ancestor in share.parents:
            source = ancestor / "src"
            if source.is_dir():
                for manifest in source.rglob("package.xml"):
                    if ET.parse(manifest).getroot().findtext("name") == package:
                        candidates.append(manifest.parent / "test/test_camera.py")
                break
    script = next((path.resolve() for path in candidates if path.is_file()), None)
    if script is None:
        raise ValueError("Camera test is source-only: keep the checkout available or pass "
                         "camera_test_script:=/absolute/path/test/test_camera.py")
    command = ["python3", str(script), "--ros-args"]
    for name in ("camera_topic", "camera_timeout", "service_timeout", "response_timeout"):
        value = LaunchConfiguration(name).perform(context)
        if name.endswith("_timeout"):
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        command.extend(["-p", f"{name}:={value}"])
    command.extend(["-p", f"model_id:={LaunchConfiguration('model').perform(context)}"])
    actions.append(ExecuteProcess(cmd=command, output="screen"))
    return actions
