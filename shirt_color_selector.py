"""Upper-shirt colour heuristic and constrained Chinese intent, not identity AI.

Image input must be CLEAN BGR pixels in the same coordinates as detections.
No ROS, model downloads, OpenCV or motor commands are required by this module.
"""
import math
import re
import numpy as np

COLORS = ("red", "orange", "yellow", "green", "blue", "purple", "black", "white", "gray")
ALIASES = {
    "red": ("紅", "红"), "orange": ("橘", "橙"), "yellow": ("黃", "黄"),
    "green": ("綠", "绿"), "blue": ("藍", "蓝"), "purple": ("紫",),
    "black": ("黑",), "white": ("白",), "gray": ("灰",),
}


def appearance_intent(text):
    """Return a bounded observation request; never a shell command or motion.

    Intentionally rejects compound descriptions, questions and multi-colour
    requests rather than turning them into ordinary FOLLOW.
    """
    compact = re.sub(r"[\s，。！？,.!?]", "", text).lower()
    if any(word in compact for word in ("不要", "別", "别", "停止", "停下", "不用", "不跟")):
        return {"action": "UNKNOWN", "reason": "negative/stop request; no new appearance target"}
    if not re.search(r"跟|追蹤|追踪", compact):
        return {"action": "UNKNOWN", "reason": "no explicit follow request"}
    if any(word in compact for word in ("嗎", "吗", "能否", "可不可以", "是不是", "如果", "或", "不是")):
        return {"action": "UNKNOWN", "reason": "question, condition or alternative is not a target request"}
    found = [color for color, aliases in ALIASES.items() if any(alias in compact for alias in aliases)]
    if len(found) != 1 or not re.search(r"上衣|衣服|[衣衫]|t恤", compact):
        return {"action": "UNKNOWN", "reason": "say one supported colour and shirt/clothes"}
    if any(word in compact for word in ("帽", "褲", "裤", "背包", "裙", "條紋", "条纹", "花", "眼鏡", "眼镜", "頭髮", "头发", "外套", "粉", "棕", "褐", "咖啡", "金", "銀", "银", "青")):
        return {"action": "UNKNOWN", "reason": "compound/unsupported appearance; first version is plain upper-shirt colour only"}
    return {"action": "FOLLOW", "shirt_color": found[0], "mode": "OBSERVATION_ONLY"}


def torso_roi(box, shape):
    """Central upper torso; exclude head, trouser area, box border and labels."""
    if not box.valid():
        return None
    height, width = shape[:2]
    left = math.floor(box.x - 0.30 * box.w)
    right = math.ceil(box.x + 0.30 * box.w)
    top = math.floor(box.y - 0.30 * box.h)
    bottom = math.ceil(box.y + 0.05 * box.h)
    if right - left < 16 or bottom - top < 16:
        return None
    if left < 0 or top < 0 or right > width or bottom > height:
        return None
    return left, top, right, bottom


def colour_ratios(bgr):
    """Vectorized HSV calculation, with conservative non-overlapping ranges."""
    rgb = bgr[..., ::-1].astype(np.float32) / 255.0
    maximum, minimum = rgb.max(axis=-1), rgb.min(axis=-1)
    delta = maximum - minimum
    denominator = np.where(delta > 0, delta, 1.0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    hue = np.zeros_like(maximum)
    red = (maximum == r) & (delta > 0)
    green = (maximum == g) & (delta > 0) & ~red
    blue = (maximum == b) & (delta > 0) & ~red & ~green
    hue[red] = ((g - b) / denominator)[red] % 6
    hue[green] = ((b - r) / denominator + 2)[green]
    hue[blue] = ((r - g) / denominator + 4)[blue]
    hue *= 60
    saturation = delta / np.where(maximum > 0, maximum, 1.0)
    chromatic = (saturation >= 0.35) & (maximum >= 0.25)
    masks = {
        "red": chromatic & ((hue < 15) | (hue >= 345)),
        "orange": chromatic & (hue >= 15) & (hue < 45),
        "yellow": chromatic & (hue >= 45) & (hue < 70),
        "green": chromatic & (hue >= 70) & (hue < 170),
        "blue": chromatic & (hue >= 190) & (hue < 260),
        "purple": chromatic & (hue >= 260) & (hue < 345),
        "black": maximum <= 0.20,
        "white": (saturation <= 0.18) & (maximum >= 0.78),
        "gray": (saturation <= 0.18) & (maximum >= 0.30) & (maximum <= 0.70),
    }
    return {color: float(mask.mean()) for color, mask in masks.items()}


def analyse_shirt(image, box, wanted):
    if wanted not in COLORS:
        raise ValueError("unsupported shirt colour")
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("image must be uint8 BGR")
    roi = torso_roi(box, image.shape)
    if roi is None:
        return {"match": False, "label": "unknown", "ratio": 0.0, "roi": None}
    left, top, right, bottom = roi
    ratios = colour_ratios(image[top:bottom, left:right])
    best = max(ratios, key=ratios.get)
    runner_up = max(value for color, value in ratios.items() if color != best)
    confident = ratios[best] >= 0.45 and ratios[best] - runner_up >= 0.12
    return {"match": confident and best == wanted,
            "label": best if confident else "unknown",
            "ratio": ratios[wanted], "roi": roi}
