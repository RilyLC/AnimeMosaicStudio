"""Minimal ComfyUI HTTP API client.

Everything network-related lives here so the pipeline can be tested with a fake
client that implements the same small surface.
"""

from __future__ import annotations

import io
import json
import time
import uuid
from typing import Any

import requests

from .errors import Cancelled, ComfyError
from .workflow import NODE_CLASSES


class ComfyClient:
    def __init__(self, url: str, connect_timeout: float = 5, read_timeout: float = 60):
        self.url = (url or "http://127.0.0.1:8188").rstrip("/")
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.session = requests.Session()
        self._object_info: dict[str, Any] | None = None
        self.client_id = uuid.uuid4().hex

    # ------------------------------------------------------------------ basics
    def _get(self, path: str, **kwargs):
        try:
            response = self.session.get(
                self.url + path,
                timeout=(self.connect_timeout, self.read_timeout),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ComfyError(f"无法连接 ComfyUI（{self.url}）：{exc}") from exc
        if response.status_code != 200:
            raise ComfyError(f"ComfyUI 返回 HTTP {response.status_code}：{response.text[:300]}")
        return response

    def _post(self, path: str, **kwargs):
        try:
            return self.session.post(
                self.url + path,
                timeout=(self.connect_timeout, self.read_timeout),
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ComfyError(f"无法连接 ComfyUI（{self.url}）：{exc}") from exc

    def ping(self) -> dict:
        return self._get("/system_stats").json()

    def comfy_version(self) -> str:
        try:
            stats = self.ping()
            return (stats.get("system") or {}).get("comfyui_version", "")
        except Exception:
            return ""

    def object_info(self, force: bool = False) -> dict:
        if self._object_info is None or force:
            self._object_info = self._get("/object_info").json()
        return self._object_info

    # --------------------------------------------------------------- model check
    def check_environment(self, names: dict[str, str]) -> list[str]:
        """Validate the nodes and model files the workflow needs."""
        info = self.object_info(force=True)
        problems: list[str] = []

        for node in NODE_CLASSES:
            if node not in info:
                problems.append(f"缺少节点：{node}")

        checks = (
            ("UNETLoader", "unet_name", names.get("unet_name"), "UNet 模型"),
            ("CLIPLoader", "clip_name", names.get("clip_name"), "文本编码器"),
            ("VAELoader", "vae_name", names.get("vae_name"), "VAE"),
            ("LoraLoaderModelOnly", "lora_name", names.get("lora_name"), "LoRA"),
        )
        for node, field, value, label in checks:
            if not value:
                continue
            options = self.model_options(node, field, info=info)
            if value not in options:
                problems.append(f"找不到{label}“{value}”（当前 ComfyUI 中不存在）")
        return problems

    def model_options(self, node: str, field: str, info: dict | None = None) -> list[str]:
        """Read the list of available model files for a loader node."""
        info = info or self.object_info()
        required = ((info.get(node) or {}).get("input") or {}).get("required") or {}
        spec = required.get(field)
        if spec and isinstance(spec[0], list):
            return [str(value) for value in spec[0]]
        return []

    # -------------------------------------------------------------------- upload
    def upload_png(self, image, subfolder: str, filename: str) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        response = self._post(
            "/upload/image",
            files={"image": (filename, buffer, "image/png")},
            data={"overwrite": "true", "subfolder": subfolder, "type": "input"},
        )
        if response.status_code != 200:
            raise ComfyError(f"上传图片失败：HTTP {response.status_code} {response.text[:300]}")
        data = response.json()
        name = data.get("name") or filename
        sub = data.get("subfolder") or ""
        return f"{sub}/{name}" if sub else name

    # ------------------------------------------------------------------- prompt
    def queue_prompt(self, prompt: dict) -> str:
        response = self._post("/prompt", json={"prompt": prompt, "client_id": self.client_id})
        if response.status_code != 200:
            detail = response.text
            try:
                data = response.json()
                if "error" in data:
                    detail = json.dumps(data["error"], ensure_ascii=False)
                node_errors = data.get("node_errors")
                if node_errors:
                    detail += " " + json.dumps(node_errors, ensure_ascii=False)[:1500]
            except Exception:
                pass
            raise ComfyError(f"工作流提交失败：HTTP {response.status_code} {detail[:2000]}")
        return response.json()["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 900, stop_event=None, poll: float = 0.35) -> dict:
        start = time.time()
        while True:
            if stop_event is not None and stop_event.is_set():
                raise Cancelled("用户停止")
            if time.time() - start > timeout:
                raise ComfyError(f"等待 ComfyUI 生成超时（{timeout}s）")
            try:
                history = self.session.get(
                    f"{self.url}/history/{prompt_id}",
                    timeout=(self.connect_timeout, 30),
                ).json()
            except requests.RequestException as exc:
                raise ComfyError(f"读取 ComfyUI 状态失败：{exc}") from exc
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    messages = []
                    for item in status.get("messages", []):
                        if isinstance(item, list) and item and item[0] == "execution_error":
                            data = item[1] or {}
                            messages.append(
                                data.get("exception_message") or data.get("exception_type") or ""
                            )
                    detail = "；".join(messages) if messages else json.dumps(status, ensure_ascii=False)[:1200]
                    raise ComfyError("ComfyUI 执行出错：" + detail)
                outputs = entry.get("outputs") or {}
                for node_output in outputs.values():
                    for image in node_output.get("images", []):
                        if image.get("type") in (None, "output", "temp"):
                            return image
                raise ComfyError("工作流没有输出图片：" + json.dumps(entry, ensure_ascii=False)[:800])
            time.sleep(poll)

    def run_prompt(self, prompt: dict, timeout: float = 900, stop_event=None) -> dict:
        prompt_id = self.queue_prompt(prompt)
        return self.wait(prompt_id, timeout=timeout, stop_event=stop_event)

    def interrupt(self) -> None:
        try:
            self._post("/interrupt")
        except Exception:
            pass

    # ----------------------------------------------------------------- download
    def download(self, info: dict):
        from PIL import Image

        params = {
            "filename": info.get("filename", ""),
            "subfolder": info.get("subfolder", ""),
            "type": info.get("type", "output"),
        }
        response = self._get("/view", params=params)
        return Image.open(io.BytesIO(response.content))
