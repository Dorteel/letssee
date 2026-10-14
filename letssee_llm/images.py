"""Convert supported sensor_msgs/Image layouts without importing ROS."""

from PIL import Image


def to_pil(message) -> Image.Image:
    """Convert 8-bit RGB/BGR/RGBA/BGRA/mono images, respecting row padding."""
    formats = {
        "rgb8": ("RGB", "RGB", 3), "bgr8": ("RGB", "BGR", 3),
        "rgba8": ("RGBA", "RGBA", 4), "bgra8": ("RGBA", "BGRA", 4),
        "mono8": ("L", "L", 1),
    }
    if message.encoding not in formats:
        raise ValueError(f"Unsupported image encoding: {message.encoding}")
    mode, raw_mode, channels = formats[message.encoding]
    if message.width <= 0 or message.height <= 0:
        raise ValueError("Image dimensions must be positive")
    if message.step < message.width * channels:
        raise ValueError("Image step is smaller than a pixel row")
    data = bytes(message.data)
    if len(data) != message.step * message.height:
        raise ValueError("Image data length does not match step * height")
    return Image.frombytes(
        mode, (message.width, message.height), data, "raw", raw_mode, message.step, 1
    ).convert("RGB")
