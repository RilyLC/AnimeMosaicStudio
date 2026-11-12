"""Image I/O: open, crop, resize and save with the original metadata."""

from __future__ import annotations

import os

import cv2
import numpy as np
from PIL import Image

from .geometry import CropPlan


def open_image(path: str) -> Image.Image:
    """Open and fully decode an image (keeps ``info`` for metadata)."""
    image = Image.open(path)
    image.load()
    return image


def is_animated(image: Image.Image) -> bool:
    return getattr(image, "n_frames", 1) > 1


def to_rgb_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))


def crop_arrays(
    rgb: np.ndarray, mask: np.ndarray, plan: CropPlan
) -> tuple[np.ndarray, np.ndarray]:
    """Contiguous RGB and mask crops for the planned window."""
    rgb_crop = np.ascontiguousarray(rgb[plan.top : plan.bottom, plan.left : plan.right])
    mask_crop = np.ascontiguousarray(mask[plan.top : plan.bottom, plan.left : plan.right])
    return rgb_crop, mask_crop


def model_inputs(
    rgb_crop: np.ndarray, mask_crop: np.ndarray, width: int, height: int
) -> tuple[Image.Image, np.ndarray]:
    """RGB crop and binary mask resampled to the model's input size."""
    rgb_image = Image.fromarray(rgb_crop).resize((width, height), Image.Resampling.LANCZOS)
    mask_image = cv2.resize(mask_crop, (width, height), interpolation=cv2.INTER_NEAREST)
    return rgb_image, mask_image


def fit_result(result: Image.Image, model_w: int, model_h: int, plan: CropPlan) -> Image.Image:
    """Resize a generated image back to the crop's original pixel size."""
    if result.size != (model_w, model_h):
        result = result.resize((model_w, model_h), Image.Resampling.LANCZOS)
    return result.resize((plan.out_w, plan.out_h), Image.Resampling.LANCZOS)


def save_like(rgb: np.ndarray, original: Image.Image, dst_path: str) -> None:
    """Save processed RGB pixels using the original format and metadata."""
    ext = os.path.splitext(dst_path)[1].lower()
    if original.mode in ("RGBA", "LA") or (original.mode == "P" and "transparency" in original.info):
        rgba = original.convert("RGBA")
        image = Image.fromarray(rgb).convert("RGBA")
        image.putalpha(rgba.getchannel("A"))
    elif original.mode == "L":
        image = Image.fromarray(rgb).convert("L")
    else:
        image = Image.fromarray(rgb)

    kwargs: dict[str, object] = {}
    info = original.info or {}
    if info.get("icc_profile"):
        kwargs["icc_profile"] = info["icc_profile"]
    if ext in (".jpg", ".jpeg", ".jfif"):
        kwargs.update(quality=95, subsampling=0)
        if info.get("exif"):
            kwargs["exif"] = info["exif"]
    elif ext == ".png":
        kwargs["compress_level"] = 6
    elif ext == ".webp":
        kwargs.update(quality=95, method=4)
        if info.get("exif"):
            kwargs["exif"] = info["exif"]

    os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    try:
        image.save(dst_path, **kwargs)
    except Exception:
        # Some formats reject metadata; retry with only quality/compression.
        image.save(dst_path, **{k: v for k, v in kwargs.items() if k in ("quality", "compress_level")})


def mask_to_rgb_image(mask: np.ndarray) -> Image.Image:
    """ComfyUI's LoadImageMask expects a 3-channel image; keep the red channel."""
    return Image.fromarray(mask).convert("RGB")


def read_scaled_preview(path: str, max_w: int, max_h: int) -> Image.Image | None:
    """Load a downscaled copy for UI previews without decoding full 4K bitmaps."""
    try:
        image = Image.open(path)
        image.thumbnail((max_w, max_h))
        return image.convert("RGB")
    except Exception:
        return None
