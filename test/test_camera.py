"""Capture one camera frame and ask the existing VLM several questions about it."""

import math
import sys
import time

PROMPTS = [
    "Describe what you see in this image.",
    "List the objects visible in the image.",
    "What is the most prominent object?",
]


def main(args: list[str] | None = None) -> int:
    """Use one subscription and sequential async requests, then release ROS resources."""
    import rclpy
    from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    from letssee.srv import AnalyzeImage
    from letssee_llm.images import to_pil

    node = executor = subscription = None
    frame = None
    try:
        rclpy.init(args=args)
        node = rclpy.create_node("one_frame_camera_test")
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        topic = node.declare_parameter("camera_topic", "/camera/image_raw").value
        service = node.declare_parameter("service_name", "/vlm/analyze_image").value
        model = node.declare_parameter("model_id", "").value
        timeouts = {}
        for name, default in [("camera_timeout", 30.0), ("service_timeout", 30.0), ("response_timeout", 180.0)]:
            value = node.declare_parameter(name, default).value
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
            timeouts[name] = value

        def capture(message: Image) -> None:
            nonlocal frame, subscription
            if frame is not None:
                return  # Ignore any callback already queued before unsubscribe.
            try:
                to_pil(message)  # Validate using the same supported layouts as the VLM.
            except ValueError as error:
                node.get_logger().warning(f"Ignoring invalid camera frame: {error}")
                return
            frame = message
            node.destroy_subscription(subscription)
            subscription = None
            print(f"Captured one image: {frame.width}x{frame.height}", flush=True)
            print("Camera subscription stopped.", flush=True)

        # Sensor-data QoS accepts typical best-effort camera publishers.
        subscription = node.create_subscription(Image, topic, capture, qos_profile_sensor_data)
        print(f"Waiting for camera frame on {topic}...", flush=True)
        deadline = time.monotonic() + timeouts["camera_timeout"]
        while frame is None:
            remaining = deadline - time.monotonic()
            if not rclpy.ok() or remaining <= 0:
                raise TimeoutError(f"No valid camera image on {topic} within {timeouts['camera_timeout']} seconds")
            executor.spin_once(timeout_sec=min(0.1, remaining))

        client = node.create_client(AnalyzeImage, service)
        print(f"Waiting for VLM service {service}...", flush=True)
        if not client.wait_for_service(timeout_sec=timeouts["service_timeout"]):
            raise TimeoutError(f"VLM service {service} unavailable after {timeouts['service_timeout']} seconds")

        for prompt in PROMPTS:
            request = AnalyzeImage.Request()
            request.image = frame  # Reuse this exact message, including its original header.
            request.prompt = prompt
            request.model_id = model
            request.schema_id = ""  # These exploratory questions need unrestricted text.
            print(f"\nPrompt: {prompt}", flush=True)
            future = client.call_async(request)
            # Keep spinning so the executor can deliver the asynchronous service response.
            executor.spin_until_future_complete(future, timeout_sec=timeouts["response_timeout"])
            if not future.done():
                client.remove_pending_request(future)
                future.cancel()
                raise TimeoutError(f"VLM response timed out after {timeouts['response_timeout']} seconds")
            response = future.result()
            if response is None or not response.success:
                error = response.error_message if response is not None else "No response received"
                raise RuntimeError(f"VLM service failed: {error}")
            print(f"Response: {response.response}", flush=True)
        print("\nCamera test completed.", flush=True)
        return 0
    except (KeyboardInterrupt, ExternalShutdownException):
        print("Camera test interrupted.", file=sys.stderr, flush=True)
        return 130
    except Exception as error:
        print(f"Camera test failed: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        if subscription is not None and node is not None:
            node.destroy_subscription(subscription)
        if executor is not None:
            executor.shutdown()
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
