"""The batch de-mosaic pipeline.

Orchestration only: detection, cropping, ComfyUI round-trip, blending and
saving are delegated to small single-purpose modules.  The processing order and
every tunable threshold match the original AutoMosaicStudio implementation.
"""

from __future__ import annotations

import os
import random
import shutil
import time
import traceback
import uuid
from collections import OrderedDict
from typing import Callable, Sequence

import numpy as np

from .blending import blend
from .comfy import ComfyClient
from .detector import Detector, MosaicDetector
from .discovery import discover_images, find_ultralytics_model
from .errors import Cancelled, ComfyError, PipelineError
from .crop_groups import group_crops
from .events import ProcessRecord, Reporter, RunSummary
from .geometry import CropPlan, model_size
from .imaging import (
    crop_arrays,
    fit_result,
    is_animated,
    mask_to_rgb_image,
    model_inputs,
    open_image,
    save_like,
)
from .manifest import ManifestWriter
from .manual_mask import ManualMaskStore
from .maskplan import build_manual_plan, build_mask_plan
from .settings import Settings
from .util import human_time
from .workflow import build_workflow
from .prompting import append_nsfw_prompts

WORKFLOW_TIMEOUT = 900
MAX_CONSECUTIVE_CONNECTION_ERRORS = 5


class Pipeline:
    """Run one batch.  Dependencies are injectable for tests and other front ends."""

    def __init__(
        self,
        settings: Settings,
        reporter: Reporter,
        stop_event=None,
        *,
        client_factory: Callable[[str], ComfyClient] | None = None,
        detector_factory: Callable[..., Detector] = MosaicDetector,
        detector_provider: Callable[[Settings], tuple[Detector, Detector | None, str]]
        | None = None,
        manifest_factory: Callable[[str], ManifestWriter] = ManifestWriter,
        discovery: Callable[[str, str, bool], list[str]] = discover_images,
        mask_store_factory: Callable[[str], ManualMaskStore] = ManualMaskStore,
        reuse_disabled: set[str] | None = None,
    ):
        self.settings = settings
        self.reporter = reporter
        self.stop_event = stop_event
        self.client = (client_factory or (lambda url: ComfyClient(url)))(settings.comfy_url)
        self._detector_factory = detector_factory
        self._detector_provider = detector_provider
        self._manifest_factory = manifest_factory
        self._discovery = discovery
        self._mask_store_factory = mask_store_factory

        self.run_id = "%08x" % random.getrandbits(32)
        self.work_sub = f"ams_work/{self.run_id}"
        self.out_sub = f"ams_tmp/{self.run_id}"
        self.comfy_dir = settings.comfy_dir
        self.mosaic_model = settings.mosaic_model or find_ultralytics_model(
            self.comfy_dir, "mosaic"
        )
        self.nsfw_model = settings.nsfw_model or find_ultralytics_model(self.comfy_dir, "nsfw")
        self.detector: Detector | None = None
        self.nsfw_detector: Detector | None = None
        self.manifest_path = os.path.join(settings.output_dir, "_AnimeMosaicStudio_manifest.csv")
        self.manifest = manifest_factory(settings.output_dir)
        self.manual_masks = mask_store_factory(settings.output_dir)
        self.counts = {"processed": 0, "copied": 0, "skipped": 0, "errors": 0, "regions": 0}
        self._reuse_cache: "OrderedDict[tuple, dict]" = OrderedDict()
        self._reuse_cache_limit = 8
        self._reuse_disabled = {
            self._rel_key(rel) for rel in (reuse_disabled or ()) if str(rel).strip()
        }

    @staticmethod
    def _rel_key(rel: str) -> str:
        return os.path.normpath(rel).replace("\\", "/")

    # --------------------------------------------------------------- reuse
    def _reuse_key(self, plan: CropPlan, positive: str | None) -> tuple:
        s = self.settings
        return (
            plan.width,
            plan.height,
            s.size,
            s.steps,
            s.cfg,
            s.denoise,
            s.mosaic_model,
            s.positive,
            positive or "",
        )

    def _find_reuse(
        self,
        key: tuple,
        crop_rgb: np.ndarray,
        crop_mask: np.ndarray,
        rel: str = "",
    ) -> tuple[np.ndarray, float, int] | None:
        if not self.settings.reuse_enabled or self._rel_key(rel) in self._reuse_disabled:
            return None
        for cached_key, cached in reversed(self._reuse_cache.items()):
            if cached_key != key:
                continue
            old_mask = cached["mask"]
            union = np.logical_or(crop_mask > 0, old_mask > 0).sum()
            if union == 0:
                continue
            inter = np.logical_and(crop_mask > 0, old_mask > 0).sum()
            if inter / float(union) < self.settings.reuse_min_mask_iou:
                continue
            ys, xs = np.where(crop_mask > 0)
            if len(ys) == 0:
                continue
            pad = max(0, int(self.settings.reuse_context_px))
            top = max(0, int(ys.min()) - pad)
            left = max(0, int(xs.min()) - pad)
            bottom = min(crop_rgb.shape[0], int(ys.max()) + 1 + pad)
            right = min(crop_rgb.shape[1], int(xs.max()) + 1 + pad)
            diff = np.abs(
                crop_rgb[top:bottom, left:right].astype(np.int16)
                - cached["crop"][top:bottom, left:right].astype(np.int16)
            )
            mean = float(diff.mean())
            p99 = float(np.percentile(diff, 99))
            if (
                mean <= self.settings.reuse_max_diff
                and p99 <= self.settings.reuse_max_diff * self.settings.reuse_p99_factor
            ):
                return cached["generated"], mean, int(cached["seed"])
        return None

    def _remember_reuse(
        self,
        key: tuple,
        crop_rgb: np.ndarray,
        crop_mask: np.ndarray,
        generated: np.ndarray,
        seed: int,
    ) -> None:
        if not self.settings.reuse_enabled:
            return
        self._reuse_cache[key] = {
            "crop": crop_rgb.copy(),
            "mask": crop_mask.copy(),
            "generated": generated.copy(),
            "seed": int(seed),
        }
        while len(self._reuse_cache) > self._reuse_cache_limit:
            self._reuse_cache.popitem(last=False)

    # ------------------------------------------------------------------ setup
    def check(self) -> None:
        """Validate directories, ComfyUI and models before touching any image."""
        settings = self.settings
        if not settings.input_dir or not os.path.isdir(settings.input_dir):
            raise PipelineError("输入目录不存在")
        if not settings.output_dir:
            raise PipelineError("请设置输出目录")
        if settings.output_conflicts:
            raise PipelineError("输出目录不能与输入目录相同")
        os.makedirs(settings.output_dir, exist_ok=True)
        if not self.mosaic_model or not os.path.isfile(self.mosaic_model):
            raise PipelineError("找不到马赛克检测模型（.pt），请在“设置 → 检测模型”中指定")

        self.reporter.log("info", f"连接 ComfyUI：{settings.comfy_url}")
        stats = self.client.ping()
        version = (stats.get("system") or {}).get("comfyui_version", "")
        self.reporter.log("info", f"ComfyUI 已连接{f'（版本 {version}）' if version else ''}")

        names = {
            key: getattr(settings, key)
            for key in ("unet_name", "clip_name", "vae_name", "lora_name")
        }
        problems = self.client.check_environment(names)
        if problems:
            raise PipelineError("ComfyUI 环境不完整：" + "；".join(problems))

        self.reporter.log("info", f"马赛克检测模型：{os.path.basename(self.mosaic_model)}")
        if not self.comfy_dir:
            self.reporter.log(
                "warn",
                "未配置 ComfyUI 目录：本次不会自动清理 ComfyUI 里的临时图片，且无法校验模型文件路径",
            )
        if self._detector_provider is not None:
            self.reporter.log("info", "使用已加载的检测模型")
            try:
                self.detector, self.nsfw_detector, _name = self._detector_provider(
                    settings
                )
            except Exception as exc:  # noqa: BLE001 - normalize model errors
                raise PipelineError(f"检测模型加载失败：{exc}") from exc
        else:
            self.detector = self._detector_factory(
                self.mosaic_model,
                device=settings.device,
                imgsz=settings.imgsz,
                conf=settings.conf,
                iou=0.5,
            )
            self.detector.load()

        active = getattr(self.detector, "active_device", "cpu")
        self.reporter.log("info", f"检测设备：{'GPU' if active != 'cpu' else 'CPU'}")

        if self._detector_provider is None and settings.nsfw_mode != "off":
            if not self.nsfw_model or not os.path.isfile(self.nsfw_model):
                raise PipelineError("找不到 NSFW 检测模型（.pt），请在设置中指定或关闭 NSFW 选项")
            self.nsfw_detector = self._detector_factory(
                self.nsfw_model,
                device=settings.device,
                imgsz=settings.imgsz,
                conf=0.25,
                iou=0.5,
            )
            self.nsfw_detector.load()

    def _cleanup(self, keep: bool = False) -> None:
        if keep or not self.comfy_dir:
            return
        paths = [
            os.path.join(self.comfy_dir, "input", *self.work_sub.split("/")),
            os.path.join(self.comfy_dir, "output", *self.out_sub.split("/")),
        ]
        for path in paths:
            shutil.rmtree(path, ignore_errors=True)

    # ------------------------------------------------------------------- batch
    def run(self) -> RunSummary:
        self.check()
        settings = self.settings
        files = self._discovery(
            settings.input_dir, settings.output_dir, settings.include_subdirs
        )
        total = len(files)
        self.reporter.log("info", f"发现 {total} 张图片，输出目录：{settings.output_dir}")
        if total == 0:
            summary = RunSummary(total=0)
            self.reporter.done(summary)
            return summary

        started = time.time()
        consecutive_errors = 0
        processed_any = 0
        stopped = False

        try:
            for index, path in enumerate(files, 1):
                if self.stop_event is not None and self.stop_event.is_set():
                    stopped = True
                    self.reporter.log("warn", "已停止（未处理的图片保留原样，下次运行可继续）")
                    break

                rel = os.path.relpath(path, settings.input_dir)
                dst = os.path.join(settings.output_dir, rel)
                abort_after_record = False
                if settings.skip_existing and os.path.isfile(dst) and os.path.getsize(dst) > 0:
                    self.counts["skipped"] += 1
                    self.reporter.log("info", f"跳过已存在：{rel}")
                    record = ProcessRecord(file=rel, status="skipped", message="输出已存在")
                else:
                    started_image = time.time()
                    try:
                        record = self._process_one(path, rel, dst)
                        consecutive_errors = 0
                        processed_any += 1
                    except Cancelled:
                        stopped = True
                        self.reporter.log("warn", "已停止（当前图片未保存）")
                        break
                    except ComfyError as exc:
                        consecutive_errors += 1
                        self.counts["errors"] += 1
                        self.reporter.log("error", f"{rel}：{exc}")
                        record = ProcessRecord(
                            file=rel,
                            status="error",
                            seconds=round(time.time() - started_image, 1),
                            message=str(exc)[:500],
                        )
                        if consecutive_errors >= MAX_CONSECUTIVE_CONNECTION_ERRORS:
                            self.reporter.log("error", "连续 5 次与 ComfyUI 通信失败，已中止批次")
                            abort_after_record = True
                    except Exception as exc:
                        self.counts["errors"] += 1
                        self.reporter.log("error", f"{rel}：{type(exc).__name__}: {exc}")
                        self.reporter.log("debug", traceback.format_exc(limit=3))
                        record = ProcessRecord(
                            file=rel,
                            status="error",
                            seconds=round(time.time() - started_image, 1),
                            message=f"{type(exc).__name__}: {exc}"[:500],
                        )

                record.file = rel
                self.manifest.append(record)
                done = index
                elapsed = time.time() - started
                speed = elapsed / done if done else 0.0
                eta = speed * (total - done)
                self.reporter.progress(done, total, rel, speed, eta)
                if record.status in ("processed", "copied", "error"):
                    self.reporter.result(record, dst)
                if abort_after_record:
                    stopped = True
                    break
        finally:
            if self.stop_event is not None and self.stop_event.is_set():
                try:
                    self.client.interrupt()
                except Exception:
                    pass
            self._cleanup(keep=bool(settings.keep_temp))

        elapsed = time.time() - started
        summary = RunSummary(
            total=total,
            processed=self.counts["processed"],
            copied=self.counts["copied"],
            skipped=self.counts["skipped"],
            errors=self.counts["errors"],
            regions=self.counts["regions"],
            elapsed=elapsed,
            stopped=stopped,
        )
        if processed_any == 0 and total > 0 and self.counts["errors"] == 0 and not stopped:
            self.reporter.log("info", "本批次没有需要新处理的图片（均已存在或无需处理）")
        self.reporter.log(
            "info",
            f"完成：处理 {summary.processed}，复制 {summary.copied}，"
            f"跳过 {summary.skipped}，失败 {summary.errors}，"
            f"重绘区域 {summary.regions}，用时 {human_time(elapsed)}",
        )
        self.reporter.done(summary)
        return summary

    # ------------------------------------------------------------------- single
    def run_single(self, rel: str) -> tuple[ProcessRecord, str]:
        """Re-process one image, overwriting its output (used by result compare)."""
        return self.run_group([rel])[0]

    def run_group(self, rels: Sequence[str]) -> list[tuple[ProcessRecord, str]]:
        """Re-process images in one session so reuse can share a generation.

        The first image generates; later ones whose crop and mask match reuse it
        after the same exact pixel check as a batch run.  Regenerating a reuse
        group this way keeps every member visually consistent.  Each output is
        overwritten in order.
        """
        settings = self.settings
        rels = [str(rel) for rel in rels]
        if not rels:
            return []
        self.check()
        started = time.time()
        total = len(rels)
        results: list[tuple[ProcessRecord, str]] = []
        try:
            for index, rel in enumerate(rels):
                if self.stop_event is not None and self.stop_event.is_set():
                    raise Cancelled("用户停止")
                path = os.path.join(settings.input_dir, rel)
                dst = os.path.join(settings.output_dir, rel)
                try:
                    if not os.path.isfile(path):
                        raise PipelineError(f"输入图片不存在：{rel}")
                    self.reporter.log("info", f"重新生成（{index + 1}/{total}）：{rel}")
                    record = self._process_one(path, rel, dst)
                except Cancelled:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad member must not stop the group
                    self.reporter.log("error", f"{rel}：{type(exc).__name__}: {exc}")
                    self.reporter.log("debug", traceback.format_exc(limit=3))
                    record = ProcessRecord(
                        file=rel,
                        status="error",
                        seconds=0.0,
                        message=f"{type(exc).__name__}: {exc}"[:500],
                    )
                record.file = rel
                self.manifest.append(record)
                results.append((record, dst))
                elapsed = time.time() - started
                self.reporter.progress(
                    index + 1, total, rel, elapsed / (index + 1), 0.0
                )
                self.reporter.result(record, dst)
            summary = RunSummary(
                total=total,
                processed=sum(
                    1 for record, _ in results if record.status == "processed"
                ),
                copied=sum(1 for record, _ in results if record.status == "copied"),
                skipped=sum(1 for record, _ in results if record.status == "skipped"),
                errors=sum(1 for record, _ in results if record.status == "error"),
                regions=sum(int(record.regions or 0) for record, _ in results),
                elapsed=time.time() - started,
                stopped=False,
            )
            self.reporter.done(summary)
            return results
        except Cancelled as exc:
            # Hand the already written images back so the dialog can refresh
            # them even though the group did not finish.
            exc.results = results  # type: ignore[attr-defined]
            raise
        finally:
            if self.stop_event is not None and self.stop_event.is_set():
                try:
                    self.client.interrupt()
                except Exception:
                    pass
            self._cleanup(keep=bool(settings.keep_temp))

    def _process_one(self, path: str, rel: str, dst: str) -> ProcessRecord:
        settings = self.settings
        started = time.time()
        original = open_image(path)
        if is_animated(original):
            return self._copy_original(path, dst, rel, started, "动图暂不支持，已复制原图")

        base = original.convert("RGB")
        width, height = base.size
        rgb = np.array(base)

        self.reporter.stage(rel, "detect")
        manual_mask = self.manual_masks.load(rel)
        if manual_mask is not None and manual_mask.shape != rgb.shape[:2]:
            self.reporter.log("warn", f"{rel}：手动遮罩尺寸与图片不符，本次改用自动检测")
            manual_mask = None

        if manual_mask is not None:
            plan = build_manual_plan(manual_mask)
            detection_text = "manual"
            nsfw_names = "手动遮罩"
            self.reporter.log("info", f"[{rel}] 使用手动遮罩：{len(plan.regions)} 处")
            if plan.empty:
                return self._copy_original(path, dst, rel, started, "手动遮罩为空，未处理")
            if not plan.regions:
                return self._copy_original(path, dst, rel, started, "手动遮罩中没有可处理区域")
        else:
            plan = build_mask_plan(rgb, self.detector, self.nsfw_detector, settings)
            detection_text = plan.detection_text()
            nsfw_names = plan.nsfw_text
            if plan.empty:
                return self._copy_original(path, dst, rel, started, "未检测到马赛克")
            self.reporter.log("info", f"[{rel}] 马赛克 {len(plan.regions)} 处：{detection_text}")

        mask = plan.mask
        regions = plan.regions
        positive = append_nsfw_prompts(settings.positive, plan.nsfw_text, settings)

        groups = group_crops(
            [region.box for region in regions],
            width,
            height,
            settings.crop_min_pct,
            background_ratio=settings.crop_background_ratio,
        )

        out = rgb.copy()
        seeds: list[int] = []
        reused_any = False
        for index, group in enumerate(groups):
            if self.stop_event is not None and self.stop_event.is_set():
                raise Cancelled("用户停止")
            base_seed = int(settings.seed)
            seed = (
                (base_seed + index) % (2**63)
                if base_seed >= 0
                else random.randint(0, 2**32 - 1)
            )
            self.reporter.stage(rel, "generate", f"{index + 1}/{len(groups)}")
            info = self._inpaint_region(out, mask, group.plan, seed, rel, positive)
            reused_any = reused_any or bool(info.get("reused"))
            seeds.append(int(info.get("seed", seed)))
            first = regions[group.indexes[0]]
            extent = f"{group.plan.width}x{group.plan.height}"
            if len(group.indexes) == 1:
                self.reporter.log(
                    "info",
                    f"    区域 {index + 1}/{len(groups)} {first.w}x{first.h} "
                    f"@({first.x},{first.y}) · 裁切 {extent} · "
                    f"{info['model_w']}x{info['model_h']} · {info['seconds']:.1f}s",
                )
            else:
                self.reporter.log(
                    "info",
                    f"    区域组 {index + 1}/{len(groups)}（{len(group.indexes)} 处）"
                    f" · 裁切 {extent} · {info['model_w']}x{info['model_h']} · "
                    f"{info['seconds']:.1f}s",
                )

        self.counts["regions"] += len(regions)
        self.reporter.stage(rel, "save")
        save_like(out, original, dst)
        elapsed = time.time() - started
        self.counts["processed"] += 1
        self.reporter.log("success", f"完成：{rel}（{elapsed:.1f}s）")
        return ProcessRecord(
            file=rel,
            status="processed",
            regions=len(regions),
            seconds=round(elapsed, 1),
            seed=",".join(str(seed) for seed in seeds),
            detections=detection_text,
            message=nsfw_names,
            reused=reused_any,
        )

    def _copy_original(
        self, path: str, dst: str, rel: str, started: float, message: str
    ) -> ProcessRecord:
        if self.settings.copy_if_no_mosaic:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            self.reporter.stage(rel, "copy")
            shutil.copy2(path, dst)
            self.counts["copied"] += 1
            self.reporter.log("info", f"{message}，复制原图：{rel}")
            return ProcessRecord(
                file=rel,
                status="copied",
                seconds=round(time.time() - started, 1),
                message=message,
            )
        self.reporter.log("info", f"{message}，跳过：{rel}")
        self.counts["skipped"] += 1
        return ProcessRecord(
            file=rel,
            status="skipped",
            seconds=round(time.time() - started, 1),
            message=message,
        )

    # ------------------------------------------------------------------ region
    def _inpaint_region(
        self,
        out: np.ndarray,
        mask: np.ndarray,
        plan: CropPlan,
        seed: int,
        rel: str = "",
        positive: str | None = None,
    ) -> dict:
        settings = self.settings
        crop_rgb, crop_mask = crop_arrays(out, mask, plan)

        size = int(settings.size)
        result = None
        model_w = model_h = 0
        cache_key = self._reuse_key(plan, positive)
        cached = self._find_reuse(cache_key, crop_rgb, crop_mask, rel)
        reused = cached is not None
        reuse_diff = cached[1] if cached else 0.0
        used_seed = cached[2] if cached else seed
        if cached is not None:
            generated = cached[0].copy()
            self.reporter.log(
                "info",
                f"    复用上一张生成结果（差分 {reuse_diff:.2f}），跳过 ComfyUI",
            )
        else:
            for attempt in range(2):
                # Group crops are always square, so the model gets its standard
                # square input without stretching the art.
                model_w, model_h = model_size(plan, size, settings.min_side)
                crop_model, mask_model = model_inputs(crop_rgb, crop_mask, model_w, model_h)

                image_name = self.client.upload_png(
                    crop_model, self.work_sub, f"{self.run_id}_{uuid.uuid4().hex[:8]}_i.png"
                )
                mask_name = self.client.upload_png(
                    mask_to_rgb_image(mask_model),
                    self.work_sub,
                    f"{self.run_id}_{uuid.uuid4().hex[:8]}_m.png",
                )

                prompt = build_workflow(
                    settings,
                    image_name,
                    mask_name,
                    seed,
                    f"{self.out_sub}/ams",
                    positive=positive,
                )
                started = time.time()
                try:
                    info = self.client.run_prompt(prompt, timeout=WORKFLOW_TIMEOUT, stop_event=self.stop_event)
                    result = self.client.download(info).convert("RGB")
                    break
                except ComfyError as exc:
                    text = str(exc).lower()
                    out_of_memory = any(
                        key in text for key in ("out of memory", "allocation", "显存", "内存", "cuda error")
                    )
                    if attempt == 0 and out_of_memory and size > 640:
                        size = int(size * 0.75) // 32 * 32
                        self.reporter.log("warn", f"显存不足，降低重绘尺寸到 {size} 后重试")
                        continue
                    raise

            if result is None:
                raise PipelineError("重绘失败：没有返回图片")
            result = fit_result(result, model_w, model_h, plan)
            generated = np.array(result)
            self._remember_reuse(cache_key, crop_rgb, crop_mask, generated, seed)

        self.reporter.stage(rel, "blend")
        composited = blend(
            settings.blend,
            crop_rgb,
            generated,
            crop_mask,
            seamless_mode=settings.seamless_mode,
            seamless_strength=settings.seamless_strength,
            seamless_feather=settings.seamless_feather,
            laplacian_levels=settings.laplacian_levels,
            laplacian_feather=settings.laplacian_feather,
            laplacian_detail=settings.laplacian_detail,
            laplacian_gamma=settings.laplacian_gamma,
            laplacian_lowfreq=settings.laplacian_lowfreq,
        )
        out[plan.top : plan.bottom, plan.left : plan.right] = composited
        return {
            "model_w": model_w,
            "model_h": model_h,
            "seconds": 0.0 if reused else time.time() - started,
            "reused": reused,
            "reuse_diff": reuse_diff,
            "seed": used_seed,
        }


def run_batch(
    settings: Settings, reporter: Reporter, stop_event=None, **dependencies
) -> RunSummary:
    """Convenience entry point used by the CLI and the desktop UI."""
    return Pipeline(settings, reporter, stop_event, **dependencies).run()
