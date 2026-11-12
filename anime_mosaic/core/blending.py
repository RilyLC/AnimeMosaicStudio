"""Mask compositing strategies.

Each strategy takes RGB arrays of the same size and a float mask in ``[0, 1]``
and returns the composited RGB image.  ``seamless`` may decline (returning
``None``) when the mask touches the crop border, in which case the hard
fallback is used — exactly like the original implementation.
"""

from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

Blender = Callable[[np.ndarray, np.ndarray, np.ndarray], np.ndarray | None]


def hard_blend(base: np.ndarray, generated: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Paste generated pixels wherever the (binary) mask is set."""
    comp = np.where(mask[..., None] > 0, generated, base)
    return comp.astype(np.uint8)


SEAMLESS_CLONE_MODES = {
    "normal": cv2.NORMAL_CLONE,
    "mixed": cv2.MIXED_CLONE,
    "monochrome": cv2.MONOCHROME_TRANSFER,
}


def seamless_blend(
    base: np.ndarray,
    generated: np.ndarray,
    mask: np.ndarray,
    mode: str = "normal",
    strength: float = 1.0,
    feather: int = 0,
) -> np.ndarray | None:
    """Poisson seamless clone; returns ``None`` when the mask touches a border.

    ``strength`` (0–1) slides the clone result back towards a plain paste: 1.0
    keeps the full Poisson solve, lower values keep more of the generated
    pixels (sharper, but the original colour cast can survive).  ``feather``
    (px) softens how the blend resolves just inside the mask edge; 0 hands the
    whole masked area to the Poisson solver.
    """
    height, width = base.shape[:2]
    mask_u8 = (mask > 0).astype(np.uint8) * 255
    ys, xs = np.nonzero(mask_u8)
    if not len(xs):
        return None
    if xs.min() <= 2 or ys.min() <= 2 or xs.max() >= width - 3 or ys.max() >= height - 3:
        return None
    try:
        src_bgr = cv2.cvtColor(generated, cv2.COLOR_RGB2BGR)
        dst_bgr = cv2.cvtColor(np.ascontiguousarray(base), cv2.COLOR_RGB2BGR)
        center = (int(xs.mean()), int(ys.mean()))
        clone_mode = SEAMLESS_CLONE_MODES.get(mode, cv2.NORMAL_CLONE)
        blended = cv2.seamlessClone(src_bgr, dst_bgr, mask_u8, center, clone_mode)
        blended_rgb = cv2.cvtColor(blended, cv2.COLOR_BGR2RGB).astype(np.float32)
        if strength >= 0.999 and feather <= 0:
            return np.rint(np.clip(blended_rgb, 0, 255)).astype(np.uint8)
        hard = np.where(mask_u8[..., None] > 0, generated, base).astype(np.float32)
        ratio = float(np.clip(strength, 0.0, 1.0))
        composed = blended_rgb * ratio + hard * (1.0 - ratio)
        if feather > 0:
            sigma = max(0.1, float(feather) / 2.0)
            alpha = cv2.GaussianBlur(mask_u8.astype(np.float32) / 255.0, (0, 0), sigma)
            alpha = np.clip(alpha, 0.0, 1.0)[..., None]
            composed = composed * alpha + hard * (1.0 - alpha)
        return np.rint(np.clip(composed, 0, 255)).astype(np.uint8)
    except Exception:
        return None


def laplacian_blend(
    base: np.ndarray,
    generated: np.ndarray,
    mask: np.ndarray,
    levels: int = 6,
    feather: int = 0,
    detail: float = 1.0,
    gamma: float = 1.0,
    lowfreq: float = 1.0,
) -> np.ndarray:
    """Multi-band (Laplacian pyramid) blend with a wide-to-narrow transition.

    ``detail`` scales the finest generated band (sharper above 1.0), ``gamma``
    reshapes the per-band mask weight (>1 = crisper transition, <1 = softer),
    and ``lowfreq`` decides how much of the generated image's coarse colour and
    lighting survives (1.0 = all of it, 0.0 = keep the original's).
    """
    base_f = base.astype(np.float32)
    gen_f = generated.astype(np.float32)
    mask_f = mask.astype(np.float32)
    if mask_f.ndim == 3:
        mask_f = mask_f[..., 0]
    if feather > 0:
        mask_f = cv2.GaussianBlur(mask_f, (0, 0), float(max(0.1, feather)) / 2.0)
        mask_f = np.clip(mask_f, 0.0, 1.0)

    gp_base = [base_f]
    gp_gen = [gen_f]
    gp_mask = [mask_f]
    for _ in range(max(1, min(8, int(levels)))):
        if min(gp_base[-1].shape[:2]) < 8:
            break
        gp_base.append(cv2.pyrDown(gp_base[-1]))
        gp_gen.append(cv2.pyrDown(gp_gen[-1]))
        gp_mask.append(cv2.pyrDown(gp_mask[-1]))

    lp_base: list[np.ndarray] = []
    lp_gen: list[np.ndarray] = []
    for index in range(len(gp_base) - 1):
        size = (gp_base[index].shape[1], gp_base[index].shape[0])
        lp_base.append(gp_base[index] - cv2.pyrUp(gp_base[index + 1], dstsize=size))
        lp_gen.append(gp_gen[index] - cv2.pyrUp(gp_gen[index + 1], dstsize=size))
    lp_base.append(gp_base[-1])
    lp_gen.append(gp_gen[-1])

    detail_f = float(np.clip(detail, 0.0, 2.0))
    gamma_f = float(np.clip(gamma, 0.2, 3.0))
    lowfreq_f = float(np.clip(lowfreq, 0.0, 1.0))
    if detail_f != 1.0:
        lp_gen[0] = lp_gen[0] * detail_f
    if lowfreq_f != 1.0:
        # The coarsest "band" is the remaining image, so mixing it towards the
        # base keeps the original colour and lighting while generation still
        # contributes all of the detail bands.
        lp_gen[-1] = lp_base[-1] * (1.0 - lowfreq_f) + lp_gen[-1] * lowfreq_f

    blended: list[np.ndarray] = []
    for index in range(len(lp_base)):
        weight = gp_mask[min(index, len(gp_mask) - 1)]
        if gamma_f != 1.0:
            weight = np.clip(weight, 0.0, 1.0) ** gamma_f
        if weight.ndim == 2:
            weight = weight[..., None]
        blended.append(lp_base[index] * (1.0 - weight) + lp_gen[index] * weight)

    out = blended[-1]
    for index in range(len(blended) - 2, -1, -1):
        size = (blended[index].shape[1], blended[index].shape[0])
        out = cv2.pyrUp(out, dstsize=size) + blended[index]
    return np.clip(out, 0, 255).astype(np.uint8)


BLENDERS: dict[str, Blender] = {
    "seamless": seamless_blend,
    "laplacian": laplacian_blend,
}


def blend(
    method: str,
    base: np.ndarray,
    generated: np.ndarray,
    mask: np.ndarray,
    *,
    seamless_mode: str = "normal",
    seamless_strength: int = 100,
    seamless_feather: int = 0,
    laplacian_levels: int = 6,
    laplacian_feather: int = 0,
    laplacian_detail: float = 1.0,
    laplacian_gamma: float = 1.0,
    laplacian_lowfreq: float = 1.0,
) -> np.ndarray:
    """Apply ``method`` with the same defensive fallbacks as the legacy app."""
    binary = (mask > 127).astype(np.float32)
    if method == "laplacian":
        try:
            return laplacian_blend(
                base,
                generated,
                binary,
                levels=laplacian_levels,
                feather=laplacian_feather,
                detail=laplacian_detail,
                gamma=laplacian_gamma,
                lowfreq=laplacian_lowfreq,
            )
        except Exception:
            return hard_blend(base, generated, binary)
    if method == "seamless":
        try:
            result = seamless_blend(
                base,
                generated,
                binary,
                mode=seamless_mode,
                strength=float(seamless_strength) / 100.0,
                feather=seamless_feather,
            )
        except Exception:
            result = None
        if result is not None:
            return result
        return hard_blend(base, generated, binary)
    return hard_blend(base, generated, binary)


def available_methods() -> tuple[str, ...]:
    return tuple(BLENDERS)
