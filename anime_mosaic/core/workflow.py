"""The ComfyUI ``autoMosaic`` workflow graph builder.

Kept deliberately declarative: the graph is data, not control flow, so adding a
node or swapping a loader is a one-line change.
"""

from __future__ import annotations

from .settings import Settings

NODE_CLASSES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "LoraLoaderModelOnly",
    "LoadImage",
    "LoadImageMask",
    "VAEEncode",
    "ApplyCosmosReferenceLatent",
    "CLIPTextEncode",
    "SetLatentNoiseMask",
    "KSampler",
    "VAEDecode",
    "SaveImage",
)


def build_workflow(
    settings: Settings,
    image_name: str,
    mask_name: str,
    seed: int,
    prefix: str,
    *,
    positive: str | None = None,
) -> dict:
    """Build the exact API-format graph used by the original application.

    ``positive`` allows the pipeline to append per-part NSFW prompts without
    mutating the frozen settings object.
    """
    positive_text = settings.positive if positive is None else positive
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": settings.unet_name, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": settings.clip_name,
                "type": "stable_diffusion",
                "device": "default",
            },
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": settings.vae_name}},
        "4": {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": ["1", 0],
                "lora_name": settings.lora_name,
                "strength_model": float(settings.lora_strength),
            },
        },
        "5": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
        "7": {
            "class_type": "ApplyCosmosReferenceLatent",
            "inputs": {"model": ["4", 0], "ref_latents.ref_latent_1": ["6", 0]},
        },
        "8": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_text, "clip": ["2", 0]},
        },
        "9": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": settings.negative, "clip": ["2", 0]},
        },
        "10": {"class_type": "LoadImageMask", "inputs": {"image": mask_name, "channel": "red"}},
        "11": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["6", 0], "mask": ["10", 0]}},
        "12": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["7", 0],
                "positive": ["8", 0],
                "negative": ["9", 0],
                "latent_image": ["11", 0],
                "seed": int(seed),
                "steps": int(settings.steps),
                "cfg": float(settings.cfg),
                "sampler_name": settings.sampler,
                "scheduler": settings.scheduler,
                "denoise": float(settings.denoise),
            },
        },
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["3", 0]}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["13", 0], "filename_prefix": prefix}},
    }
