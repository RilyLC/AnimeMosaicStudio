"""Command line interface, useful for batch automation and smoke tests."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .core.discovery import discover_images
from .core.events import Reporter, RunSummary
from .core.pipeline import run_batch
from .core.settings import (
    BLEND_METHODS,
    DEVICES,
    NSFW_MODES,
    SEAMLESS_MODES,
    load_settings,
    save_settings,
)
from .core.util import human_time
from .logging_setup import setup_logging
from .services.environment import inspect_environment
from .services.presets import preset_by_id


class ConsoleReporter(Reporter):
    def log(self, level, message):
        print(f"[{level}] {message}", flush=True)

    def stage(self, rel_path, stage, detail=""):
        if stage in ("detect", "save", "copy"):
            print(f"    · {rel_path} → {stage}", flush=True)

    def progress(self, done, total, rel_path, speed, eta):
        print(
            f"({done}/{total}) {rel_path}  {speed:.1f}s/张  剩余约 {human_time(eta)}",
            flush=True,
        )

    def done(self, summary: RunSummary):
        print("=" * 64)
        print(
            f"处理 {summary.processed} · 复制 {summary.copied} · 跳过 {summary.skipped} · "
            f"失败 {summary.errors} · 区域 {summary.regions}"
        )
        print(f"总用时 {human_time(summary.elapsed)}" + ("（已停止）" if summary.stopped else ""))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anime-mosaic",
        description="AnimeMosaicStudio — 批量检测马赛克并用 ComfyUI 重绘",
    )
    parser.add_argument("--version", action="version", version=f"AnimeMosaicStudio {__version__}")
    parser.add_argument("--input", "-i", help="输入目录")
    parser.add_argument("--output", "-o", help="输出目录")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 张（测试用）")
    parser.add_argument("--preset", choices=["fast", "balanced", "quality"], help="参数预设")
    parser.add_argument("--conf", type=float, help="马赛克检测置信度")
    parser.add_argument("--size", type=int, help="重绘边长（正方形裁切缩放到的边长）")
    parser.add_argument("--crop-min-pct", type=int, dest="crop_min_pct",
                        help="裁切窗口至少占整张图的百分比（5–100）")
    parser.add_argument("--crop-background", type=float, dest="crop_background_ratio",
                        help="背景面积相对马赛克的倍数（0–4）")
    parser.add_argument("--steps", type=int, help="采样步数")
    parser.add_argument("--cfg", type=float, help="CFG")
    parser.add_argument("--denoise", type=float, help="降噪强度 0.2–1.0（越低越接近原图）")
    parser.add_argument("--seed", type=int, help="固定种子（-1 随机）")
    parser.add_argument("--grow", type=int, help="掩码外扩像素")
    parser.add_argument("--nsfw", choices=list(NSFW_MODES), help="NSFW 检测模式")
    parser.add_argument("--device", choices=list(DEVICES), help="检测设备")
    parser.add_argument("--blend", choices=list(BLEND_METHODS), help="贴回原图的融合方式")
    parser.add_argument("--seamless-mode", choices=list(SEAMLESS_MODES),
                        help="无缝融合克隆模式")
    parser.add_argument("--laplacian-levels", type=int, help="多频段融合层数 1–8")
    parser.add_argument("--laplacian-feather", type=int, help="多频段遮罩羽化 0–64px")
    parser.add_argument("--seamless-strength", type=int, help="泊松融合强度 0–100（%）")
    parser.add_argument("--seamless-feather", type=int, help="泊松边缘过渡 0–32px")
    parser.add_argument("--laplacian-detail", type=float, help="多频段细节增益 0.0–2.0")
    parser.add_argument("--laplacian-gamma", type=float, help="多频段过渡曲线 0.2–3.0")
    parser.add_argument("--laplacian-lowfreq", type=float, help="多频段低频保护 0.0–1.0")
    parser.add_argument("--no-subdirs", action="store_true", help="只处理输入目录第一层，不含子目录")
    parser.add_argument("--check", action="store_true", help="只检查 ComfyUI 环境后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging(console=True)
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    if not settings.comfy_dir or not settings.mosaic_model:
        print(
            "[hint] 还没有配置 ComfyUI 目录或检测模型：把 config.json.example 复制为 config.json 并填写，"
            "或先运行一次界面的首次设置向导。",
            file=sys.stderr,
        )
    if args.preset:
        preset = preset_by_id(args.preset)
        if preset:
            settings = preset.apply(settings)
    if args.input:
        settings = settings.merged(input_dir=os.path.abspath(args.input))
    if args.output:
        settings = settings.merged(output_dir=os.path.abspath(args.output))
    if not settings.output_dir and settings.input_dir:
        settings = settings.merged(output_dir=settings.default_output)

    for key in (
        "conf",
        "size",
        "crop_min_pct",
        "crop_background_ratio",
        "steps",
        "seed",
        "grow",
        "device",
        "cfg",
        "denoise",
        "seamless_mode",
        "seamless_strength",
        "seamless_feather",
        "laplacian_levels",
        "laplacian_feather",
        "laplacian_detail",
        "laplacian_gamma",
        "laplacian_lowfreq",
    ):
        value = getattr(args, key)
        if value is not None:
            settings = settings.merged(**{key: value})
    if args.nsfw:
        settings = settings.merged(nsfw_mode=args.nsfw)
    if args.blend:
        settings = settings.merged(blend=args.blend)
    if args.no_subdirs:
        settings = settings.merged(include_subdirs=False)

    if not settings.input_dir or not os.path.isdir(settings.input_dir):
        parser.error("请用 --input 指定存在的输入目录")

    problems = settings.validate()
    if problems:
        for problem in problems:
            print(f"[error] {problem.message}", file=sys.stderr)
        return 2

    if args.check:
        report = inspect_environment(settings)
        if not report.connected:
            print(f"[error] ComfyUI 连接失败：{report.error}")
            return 1
        print(f"ComfyUI {report.version or ''} 已连接")
        if report.problems:
            for problem in report.problems:
                print(f"[warn] {problem}")
            return 1
        print("环境检查通过")
        return 0

    save_settings(settings)
    discovery = discover_images
    if args.limit:
        discovery = lambda input_dir, output_dir, include_subdirs=True: discover_images(
            input_dir, output_dir, include_subdirs
        )[: args.limit]

    try:
        summary = run_batch(settings, ConsoleReporter(), discovery=discovery)
    except KeyboardInterrupt:
        print("已中断", flush=True)
        return 130
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 1 if summary.errors else 0


if __name__ == "__main__":
    sys.exit(main())
