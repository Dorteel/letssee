"""Launch production ROS callbacks with lightweight inference fixtures only."""

import argparse
import json
import sys
from types import SimpleNamespace


class FixtureModel:
    """Deterministic test responses; never load weights or download files."""

    def __init__(self, *args, **kwargs):
        pass

    def generate(self, prompt: str, *, schema=None, **kwargs) -> str:
        if schema is None:
            return f"fixture: {prompt}"
        if "objects" in schema.get("properties", {}):
            return json.dumps({"objects": [{"label": "red square", "confidence": 0.8}]})
        return json.dumps({"response": "fixture response"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=["text", "vision", "legacy"], required=True)
    options, ros_args = parser.parse_known_args()
    import rclpy
    from rclpy.executors import ExternalShutdownException

    if options.service == "legacy":
        sys.modules["letssee_llm.local_llm"] = SimpleNamespace(LocalLLM=FixtureModel)
        from letssee_llm.service import MinimalService
    elif options.service == "text":
        from letssee_llm.services.llm_service import MinimalService
    else:
        from letssee_llm.services.vlm_service import MinimalService

    rclpy.init(args=ros_args)
    node = None
    try:
        node = MinimalService()
        if options.service != "legacy":
            node.models.loaded.update({key: FixtureModel() for key in node.models.library.models})
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
