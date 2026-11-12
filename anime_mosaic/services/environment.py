"""ComfyUI environment inspection used by the settings page and the CLI."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..core.comfy import ComfyClient
from ..core.discovery import find_ultralytics_model
from ..core.settings import Settings

MODEL_FIELDS = (
    ("UNETLoader", "unet_name", "unet_name"),
    ("CLIPLoader", "clip_name", "clip_name"),
    ("VAELoader", "vae_name", "vae_name"),
    ("LoraLoaderModelOnly", "lora_name", "lora_name"),
)


@dataclass
class ConnectionReport:
    connected: bool = False
    version: str = ""
    error: str = ""
    elapsed: float = 0.0


@dataclass
class EnvironmentReport(ConnectionReport):
    problems: list[str] = field(default_factory=list)
    models: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.connected and not self.problems


def probe_connection(url: str, timeout: float = 4.0) -> ConnectionReport:
    """Lightweight connectivity check (``/system_stats`` only)."""
    started = time.time()
    try:
        client = ComfyClient(url, connect_timeout=min(4.0, timeout), read_timeout=timeout)
        stats = client.ping()
        version = (stats.get("system") or {}).get("comfyui_version", "")
        return ConnectionReport(True, version, "", time.time() - started)
    except Exception as exc:
        return ConnectionReport(False, "", str(exc), time.time() - started)


def inspect_environment(settings: Settings, timeout: float = 25.0) -> EnvironmentReport:
    """Full check: nodes, model files and available model lists."""
    started = time.time()
    try:
        client = ComfyClient(
            settings.comfy_url,
            connect_timeout=min(5.0, timeout),
            read_timeout=timeout,
        )
        stats = client.ping()
        version = (stats.get("system") or {}).get("comfyui_version", "")
        names = {key: getattr(settings, key) for _, _, key in MODEL_FIELDS}
        problems = client.check_environment(names)
        info = client.object_info()
        models: dict[str, list[str]] = {}
        for node, field_name, setting_key in MODEL_FIELDS:
            models[setting_key] = client.model_options(node, field_name, info=info)
        return EnvironmentReport(
            connected=True,
            version=version,
            problems=problems,
            models=models,
            elapsed=time.time() - started,
        )
    except Exception as exc:
        return EnvironmentReport(
            connected=False, error=str(exc), elapsed=time.time() - started
        )


def autodetect_paths(settings: Settings) -> dict:
    """Scan the configured ComfyUI folder for detector weights.

    Only a folder the user already filled in is inspected; no path is guessed.
    """
    comfy_dir = settings.comfy_dir
    changes: dict[str, str] = {}
    if comfy_dir:
        if not settings.mosaic_model:
            changes["mosaic_model"] = find_ultralytics_model(comfy_dir, "mosaic")
        if not settings.nsfw_model:
            changes["nsfw_model"] = find_ultralytics_model(comfy_dir, "nsfw")
    return {key: value for key, value in changes.items() if value}


def readiness_problems(settings: Settings) -> list[str]:
    """Cheap local checks (no network) used before starting a batch."""
    problems: list[str] = []
    if not settings.mosaic_model:
        problems.append("尚未指定马赛克检测模型")
    return problems
