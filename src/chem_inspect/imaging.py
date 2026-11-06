"""图像预处理与证据裁剪。

三件事必须做对（都来自探针实测）：
1. **EXIF 方向纠正**：手机/相机竖拍图不纠正，模型看到的是躺倒的人。
2. **长边压缩**：控制 token；但 HZ-01（小目标）需要相对高的分辨率，默认 1280。
3. **bbox 换算**：模型给的是 0~1000 相对坐标，必须换算成像素并裁剪。
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps

DEFAULT_LONG_SIDE = 1280
JPEG_QUALITY = 88


def load_image(data: bytes) -> Image.Image:
    img = Image.open(BytesIO(data))
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


def resize_long_side(img: Image.Image, long_side: int = DEFAULT_LONG_SIDE) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest <= long_side:
        return img
    scale = long_side / longest
    return img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def to_jpeg(img: Image.Image, quality: int = JPEG_QUALITY) -> bytes:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def make_thumb(img: Image.Image, size: int = 320) -> bytes:
    thumb = img.copy()
    thumb.thumbnail((size, size), Image.LANCZOS)
    return to_jpeg(thumb, quality=80)


def crop_evidence(
    img: Image.Image, box_px: list[float] | None, padding: float = 0.12
) -> Image.Image | None:
    """按像素框裁剪证据图；带外扩，避免把关键物体裁掉一半。"""
    if not box_px:
        return None
    w, h = img.size
    x1, y1, x2, y2 = box_px
    if x2 <= x1 or y2 <= y1:
        return None
    pad_x = (x2 - x1) * padding
    pad_y = (y2 - y1) * padding
    left = max(0, int(x1 - pad_x))
    top = max(0, int(y1 - pad_y))
    right = min(w, int(x2 + pad_x))
    bottom = min(h, int(y2 + pad_y))
    if right - left < 8 or bottom - top < 8:
        return None
    return img.crop((left, top, right, bottom))
