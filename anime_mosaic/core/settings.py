"""Application settings: the single source of truth for every tunable value.

The :class:`Settings` dataclass defines defaults and types.  :data:`FIELD_SPECS`
adds presentation metadata (label, range, help text) that the desktop UI and the
CLI both reuse, so a new option only has to be described once.

Nothing in this module imports Qt or any heavyweight dependency.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields, replace
from typing import Any, Iterable, Mapping

APP_NAME = "AnimeMosaicStudio"
APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "AnimeMosaicStudio.log")

DEFAULT_POSITIVE = (
    "remove bar censor and mosaic censoring. nsfw, uncensored, pussy, anus, "
    "detailed anatomy, best quality"
)
DEFAULT_NEGATIVE = (
    "censored, bar censor, mosaic censoring, low quality, worst quality, blurry, watermark"
)

DEVICES = ("gpu", "cpu")
NSFW_MODES = ("off", "record", "augment")
BLEND_METHODS = ("seamless", "laplacian")
SEAMLESS_MODES = ("normal", "mixed", "monochrome")
NSFW_PROMPT_CLASSES = ("pussy", "anus", "penis", "testicles")
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".tif", ".tiff"}
PATH_KEYS = (
    "input_dir",
    "output_dir",
    "comfy_dir",
    "python_exe",
    "mosaic_model",
    "nsfw_model",
)


def repair_path(path: str) -> str:
    """Recover paths that were UTF-8 bytes decoded as GBK by an external dialog.

    This is a no-op for normal paths; it only rewrites a non-existent path when
    the repaired candidate exists (or its parent directory does).
    """
    if not path or os.path.exists(path):
        return path
    for encoding in ("gbk", "cp936"):
        try:
            candidate = path.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if candidate == path:
            continue
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(candidate)
        if parent and os.path.isdir(parent):
            return candidate
    return path


@dataclass(frozen=True)
class Settings:
    """Every processing option, with defaults identical to the legacy app."""

    # ComfyUI connection
    comfy_url: str = "http://127.0.0.1:8188"
    comfy_dir: str = ""
    # Interpreter used by the standalone launcher.  Empty means "not chosen
    # yet": the launcher asks the user to pick one instead of guessing.
    python_exe: str = ""
    # Model file names as known by ComfyUI
    unet_name: str = "anima-turbo-v1.1.safetensors"
    clip_name: str = "qwen_3_06b_base.safetensors"
    vae_name: str = "qwen_image_vae.safetensors"
    lora_name: str = "uncensored_lora_v6-000034.safetensors"
    lora_strength: float = 0.33
    sampler: str = "er_sde"
    scheduler: str = "simple"
    # Detector
    mosaic_model: str = ""
    nsfw_model: str = ""
    device: str = "gpu"
    imgsz: int = 1280
    conf: float = 0.25
    nsfw_mode: str = "off"
    # Folders and file policy
    input_dir: str = ""
    output_dir: str = ""
    include_subdirs: bool = True
    skip_existing: bool = True
    copy_if_no_mosaic: bool = True
    keep_temp: bool = False
    # Inpainting
    crop_min_pct: int = 25
    crop_background_ratio: float = 2.0
    size: int = 1024
    min_side: int = 128
    grow: int = 8
    blend: str = "seamless"
    seamless_mode: str = "normal"
    seamless_strength: int = 100
    seamless_feather: int = 0
    laplacian_levels: int = 6
    laplacian_feather: int = 0
    laplacian_detail: float = 1.0
    laplacian_gamma: float = 1.0
    laplacian_lowfreq: float = 1.0
    steps: int = 25
    cfg: float = 3.0
    denoise: float = 1.0
    seed: int = -1
    preset: str = "balanced"
    # Per-preset overrides for PRESET_VALUE_KEYS, e.g. {"fast": {"steps": 20}}.
    preset_values: dict[str, dict[str, Any]] = field(default_factory=dict)
    positive: str = DEFAULT_POSITIVE
    negative: str = DEFAULT_NEGATIVE
    # Optional NSFW prompt injection.  The detector exposes these four classes.
    nsfw_prompt_enabled: bool = False
    nsfw_prompt_pussy: str = "pussy"
    nsfw_prompt_anus: str = "anus"
    nsfw_prompt_penis: str = "penis"
    nsfw_prompt_testicles: str = "testicles"
    # Advanced differential reuse (opt-in, conservative).
    reuse_enabled: bool = False
    reuse_max_diff: float = 2.0
    reuse_context_px: int = 8
    reuse_min_group_iou: float = 0.85
    reuse_min_mask_iou: float = 0.985
    reuse_p99_factor: float = 3.0
    show_nsfw_marks: bool = False
    show_grow_band: bool = True

    # ------------------------------------------------------------------ mapping
    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Settings":
        """Build settings from a JSON-like mapping, ignoring unknown keys."""
        if not isinstance(data, Mapping):
            return cls()
        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in data:
                continue
            value = _coerce(data[field.name], getattr(cls(), field.name))
            if field.name == "preset_values":
                value = _clean_preset_values(value)
            if field.name in PATH_KEYS:
                value = repair_path(value)
            values[field.name] = value
        return cls(**values)

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)

    def merged(self, **changes: Any) -> "Settings":
        """Return a copy with validated type coercion applied."""
        clean = {}
        for key, value in changes.items():
            if key not in self.to_mapping():
                raise KeyError(f"未知设置项：{key}")
            value = _coerce(value, getattr(self, key))
            if key == "preset_values":
                value = _clean_preset_values(value)
            if key in PATH_KEYS:
                value = repair_path(value)
            clean[key] = value
        return replace(self, **clean)

    # ------------------------------------------------------------------ derived
    @property
    def has_input(self) -> bool:
        return bool(self.input_dir and os.path.isdir(self.input_dir))

    @property
    def has_output(self) -> bool:
        return bool(self.output_dir)

    @property
    def output_conflicts(self) -> bool:
        if not self.input_dir or not self.output_dir:
            return False
        return os.path.normcase(os.path.abspath(self.input_dir)) == os.path.normcase(
            os.path.abspath(self.output_dir)
        )

    @property
    def default_output(self) -> str:
        return default_output_dir(self.input_dir)

    # --------------------------------------------------------------- validation
    def validate(self) -> list["Problem"]:
        """Cross-field validation shared by the UI and the CLI."""
        problems: list[Problem] = []

        if not self.input_dir:
            problems.append(Problem("input_dir", "请选择输入目录"))
        elif not os.path.isdir(self.input_dir):
            problems.append(Problem("input_dir", "输入目录不存在"))
        if not self.output_dir:
            problems.append(Problem("output_dir", "请选择输出目录"))
        elif self.output_conflicts:
            problems.append(Problem("output_dir", "输出目录不能与输入目录相同"))
        if not self.comfy_url.strip():
            problems.append(Problem("comfy_url", "请填写 ComfyUI 地址"))
        if not _is_http_url(self.comfy_url):
            problems.append(Problem("comfy_url", "ComfyUI 地址需以 http:// 或 https:// 开头"))
        if not (0.0 <= self.conf <= 1.0):
            problems.append(Problem("conf", "检测置信度需在 0 到 1 之间"))
        if self.grow < 0:
            problems.append(Problem("grow", "掩码外扩不能为负数"))
        if not (5 <= self.crop_min_pct <= 100):
            problems.append(Problem("crop_min_pct", "最小裁切占比需在 5% 到 100% 之间"))
        if not (0.0 <= self.crop_background_ratio <= 4.0):
            problems.append(Problem("crop_background_ratio", "背景倍数需在 0 到 4 之间"))
        if self.size < 64:
            problems.append(Problem("size", "重绘边长需不小于 64"))
        if self.steps < 1:
            problems.append(Problem("steps", "采样步数需至少为 1"))
        if self.cfg < 0:
            problems.append(Problem("cfg", "CFG 不能为负数"))
        if not (0.2 <= self.denoise <= 1.0):
            problems.append(Problem("denoise", "降噪强度需在 0.2 到 1.0 之间"))
        if self.preset not in ("fast", "balanced", "quality", "custom"):
            problems.append(Problem("preset", "预设类型无效"))
        if self.device not in DEVICES:
            problems.append(Problem("device", "检测设备只能是 gpu 或 cpu"))
        if self.nsfw_mode not in NSFW_MODES:
            problems.append(Problem("nsfw_mode", "NSFW 辅助模式无效"))
        if self.blend not in BLEND_METHODS:
            problems.append(Problem("blend", "融合方式无效"))
        if self.seamless_mode not in SEAMLESS_MODES:
            problems.append(Problem("seamless_mode", "无缝克隆模式无效"))
        if not (1 <= self.laplacian_levels <= 8):
            problems.append(Problem("laplacian_levels", "多频段层数需在 1 到 8 之间"))
        if not (0 <= self.laplacian_feather <= 64):
            problems.append(Problem("laplacian_feather", "遮罩羽化需在 0 到 64 之间"))
        if not (0 <= self.seamless_strength <= 100):
            problems.append(Problem("seamless_strength", "融合强度需在 0% 到 100% 之间"))
        if not (0 <= self.seamless_feather <= 32):
            problems.append(Problem("seamless_feather", "边缘过渡需在 0 到 32 像素之间"))
        if not (0.0 <= self.laplacian_detail <= 2.0):
            problems.append(Problem("laplacian_detail", "细节增益需在 0.0 到 2.0 之间"))
        if not (0.2 <= self.laplacian_gamma <= 3.0):
            problems.append(Problem("laplacian_gamma", "过渡曲线需在 0.2 到 3.0 之间"))
        if not (0.0 <= self.laplacian_lowfreq <= 1.0):
            problems.append(Problem("laplacian_lowfreq", "低频保护需在 0.0 到 1.0 之间"))
        if not self.positive.strip():
            problems.append(Problem("positive", "正向提示词不能为空"))
        if not (0.0 <= self.reuse_max_diff <= 100.0):
            problems.append(Problem("reuse_max_diff", "差分阈值需在 0 到 100 之间"))
        if not (0 <= self.reuse_context_px <= 256):
            problems.append(Problem("reuse_context_px", "差分上下文需在 0 到 256 像素之间"))
        if not (0.5 <= self.reuse_min_group_iou <= 1.0):
            problems.append(Problem("reuse_min_group_iou", "分组 IoU 需在 0.5 到 1.0 之间"))
        if not (0.9 <= self.reuse_min_mask_iou <= 1.0):
            problems.append(Problem("reuse_min_mask_iou", "复用 IoU 需在 0.9 到 1.0 之间"))
        if not (1.0 <= self.reuse_p99_factor <= 10.0):
            problems.append(Problem("reuse_p99_factor", "99 分位倍数需在 1 到 10 之间"))
        return problems


@dataclass(frozen=True)
class Problem:
    field: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.message


# ---------------------------------------------------------------------- fields
@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    help: str = ""


@dataclass(frozen=True)
class FieldSpec:
    """UI/CLI metadata for one setting.  Key must exist on :class:`Settings`."""

    key: str
    label: str
    group: str
    kind: str = "text"  # int | float | bool | text | choice | url | path
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0
    decimals: int = 0
    suffix: str = ""
    choices: tuple[Choice, ...] = ()
    advanced: bool = False
    slider: bool = True


GROUP_SAMPLING = "sampling"
GROUP_DETECTION = "detection"
GROUP_CROP = "crop"
GROUP_BLEND = "blend"
GROUP_BLEND_SEAMLESS = "blend_seamless"
GROUP_BLEND_LAPLACIAN = "blend_laplacian"
GROUP_CONNECTION = "connection"
GROUP_RUNTIME = "runtime"
GROUP_MODELS = "models"
GROUP_FILES = "files"
GROUP_ADVANCED = "advanced"
GROUP_REUSE = "reuse"

GROUP_LABELS = {
    GROUP_SAMPLING: "采样",
    GROUP_DETECTION: "检测",
    GROUP_CROP: "裁切",
    GROUP_BLEND: "融合",
    GROUP_BLEND_SEAMLESS: "无缝融合高级设置",
    GROUP_BLEND_LAPLACIAN: "多频段融合高级设置",
    GROUP_CONNECTION: "ComfyUI 连接",
    GROUP_RUNTIME: "运行环境",
    GROUP_MODELS: "模型文件",
    GROUP_FILES: "输出行为",
    GROUP_ADVANCED: "高级",
    GROUP_REUSE: "差分复用",
}

FIELD_SPECS: tuple[FieldSpec, ...] = (
    # ------------------------------------------------------------- sampling
    FieldSpec(
        "size", "重绘边长", GROUP_SAMPLING, "int",
        help="正方形裁切缩放到该边长后送给模型（按 64 对齐）。越大细节越多，也越慢、越吃显存。",
        minimum=256, maximum=2048, step=64, suffix="px",
    ),
    FieldSpec(
        "steps", "采样步数", GROUP_SAMPLING, "int",
        help="步数越高细节越多、越慢。Turbo 模型 12–25 步通常足够。",
        minimum=1, maximum=60, step=1, suffix="步",
    ),
    FieldSpec(
        "cfg", "CFG 引导", GROUP_SAMPLING, "float",
        help="分类器自由引导强度。Turbo 模型建议 2.0–3.5。",
        minimum=0.0, maximum=15.0, step=0.1, decimals=1,
    ),
    FieldSpec(
        "denoise", "降噪强度", GROUP_SAMPLING, "float",
        help=(
            "K 采样器的 denoise：越低越接近原图，越高越彻底重绘。"
        ),
        minimum=0.2, maximum=1.0, step=0.05, decimals=2,
    ),
    FieldSpec(
        "seed", "随机种子", GROUP_SAMPLING, "int",
        help="-1 表示每张随机；固定值可复现同一结果。",
        minimum=-1, maximum=2**31 - 1, step=1, slider=False,
    ),
    # ------------------------------------------------------------ detection
    FieldSpec(
        "conf", "检测置信度", GROUP_DETECTION, "float",
        help="越低越容易检出，但误检更多。漏检时先试 0.15–0.20。",
        minimum=0.01, maximum=0.99, step=0.01, decimals=2,
    ),
    FieldSpec(
        "grow", "掩码外扩", GROUP_DETECTION, "int",
        help="把检测到的区域向外扩张，确保盖住马赛克边缘。",
        minimum=0, maximum=64, step=1, suffix="px",
    ),
    FieldSpec(
        "device", "检测设备", GROUP_DETECTION, "choice",
        help="显存紧张时改用 CPU：更慢，但不占显存。",
        choices=(Choice("gpu", "GPU（推荐）"), Choice("cpu", "CPU")),
    ),
    FieldSpec(
        "nsfw_mode", "NSFW 辅助", GROUP_DETECTION, "choice",
        help="record 只记录识别结果；augment 会把 NSFW 区域并入掩码。",
        choices=(
            Choice("off", "关闭", "只用马赛克检测模型"),
            Choice("record", "仅记录", "记录 NSFW 识别结果，不改变掩码"),
            Choice("augment", "并入掩码", "把 NSFW 生殖器区域也交给模型重绘"),
        ),
    ),
    # ---------------------------------------------------------------- blend
    FieldSpec(
        "blend", "融合方式", GROUP_BLEND, "choice",
        choices=(
            Choice("seamless", "无缝（Poisson）", "边界颜色过渡自然，速度较快"),
            Choice("laplacian", "多频段（Laplacian）", "低频宽过渡、高频窄过渡，细节更好"),
        ),
    ),
    FieldSpec(
        "seamless_mode", "克隆模式", GROUP_BLEND_SEAMLESS, "choice",
        help="标准模式保留目标图的颜色与光照；纹理混合保留更多源图纹理；单色迁移只迁移亮度。",
        choices=(
            Choice("normal", "标准", "颜色与光照最稳，默认"),
            Choice("mixed", "纹理混合", "保留更多生成图的纹理"),
            Choice("monochrome", "单色迁移", "只迁移亮度，保留原图色彩"),
        ),
    ),
    FieldSpec(
        "laplacian_levels", "金字塔层数", GROUP_BLEND_LAPLACIAN, "int",
        help="多频段融合的下采样次数；越多过渡越宽，也越慢。",
        minimum=1, maximum=8, step=1,
    ),
    FieldSpec(
        "laplacian_feather", "遮罩羽化", GROUP_BLEND_LAPLACIAN, "int",
        help="融合前柔化遮罩边缘，避免硬边；0 表示不羽化。",
        minimum=0, maximum=64, step=2, suffix="px",
    ),
    FieldSpec(
        "seamless_strength", "融合强度", GROUP_BLEND_SEAMLESS, "int",
        help=(
            "泊松结果与直接粘贴的混合比例：100 表示整片交给泊松缝合（边界最自然），"
            "越低越保留生成图原色（更锐利，但原图的色偏可能残留）。"
        ),
        minimum=0, maximum=100, step=5, suffix="%",
    ),
    FieldSpec(
        "seamless_feather", "边缘过渡", GROUP_BLEND_SEAMLESS, "int",
        help=(
            "遮罩内侧的过渡宽度：0 表示整片交给泊松；数值越大，靠近遮罩边缘越贴近"
            "生成图（边缘更锐利，但可能出现轻微色差）。"
        ),
        minimum=0, maximum=32, step=2, suffix="px",
    ),
    FieldSpec(
        "laplacian_detail", "细节增益", GROUP_BLEND_LAPLACIAN, "float",
        help="放大或衰减生成图的最高频细节：1.00 保持原样，越大越锐，越小越柔。",
        minimum=0.0, maximum=2.0, step=0.05, decimals=2,
    ),
    FieldSpec(
        "laplacian_gamma", "过渡曲线", GROUP_BLEND_LAPLACIAN, "float",
        help=(
            "每个频段遮罩权重的指数：1.0 为线性，越大过渡越陡（边缘更清晰），"
            "越小过渡越宽（接缝更柔和）。"
        ),
        minimum=0.2, maximum=3.0, step=0.1, decimals=1,
    ),
    FieldSpec(
        "laplacian_lowfreq", "低频保护", GROUP_BLEND_LAPLACIAN, "float",
        help=(
            "生成图低频（整体色调与光照）的占比：1.00 完全采用生成图，越低越保留原图"
            "色调，只用生成图补细节与纹理。"
        ),
        minimum=0.0, maximum=1.0, step=0.05, decimals=2,
    ),
    FieldSpec(
        "crop_min_pct", "最小裁切占比", GROUP_CROP, "int",
        help=(
            "裁切窗口至少占整张图的这个面积比例，保证小马赛克也有足够背景。"
            "1080p 下 25% 约为 720×720；正方形最大只能到画面短边（1080p 为 1080），"
            "比例再大也以短边为准。"
        ),
        minimum=5, maximum=100, step=1, suffix="%",
    ),
    FieldSpec(
        "crop_background_ratio", "背景倍数", GROUP_CROP, "float",
        help=(
            "裁切窗口面积至少是马赛克面积的 1+该倍数：0 表示刚好盖住，"
            "1 表示背景与马赛克等面积，2 表示背景是马赛克的两倍。"
        ),
        minimum=0.0, maximum=4.0, step=0.1, decimals=1, suffix="×",
    ),
    # ----------------------------------------------------------- connection
    FieldSpec("comfy_url", "ComfyUI 地址", GROUP_CONNECTION, "url",
             help="ComfyUI 的 HTTP 地址，默认 http://127.0.0.1:8188。"),
    FieldSpec("comfy_dir", "ComfyUI 目录", GROUP_CONNECTION, "path",
             help="用于在该目录的 models/ultralytics 下查找检测模型，并在结束后清理临时图片。"),
    # -------------------------------------------------------------- runtime
    FieldSpec(
        "python_exe", "Python 解释器", GROUP_RUNTIME, "path",
        help=(
            "修改后需要重启。"
        ),
    ),
    # ---------------------------------------------------------------- files
    FieldSpec("skip_existing", "跳过已存在", GROUP_FILES, "bool",
             help="输出目录已有同名文件时跳过，支持断点续跑。"),
    FieldSpec("copy_if_no_mosaic", "无马赛克时复制", GROUP_FILES, "bool",
             help="没有检测到马赛克的图片直接复制到输出目录。"),
    FieldSpec("keep_temp", "保留临时文件", GROUP_FILES, "bool",
             help="保留上传到 ComfyUI 的裁切图，便于排查问题。"),
    # --------------------------------------------------------------- reuse
    FieldSpec(
        "reuse_enabled", "差分复用", GROUP_REUSE, "bool",
        help="开启后，遮罩相同且马赛克周边差异很小的差分图会复用代表图的生成结果，跳过重复重绘。",
        advanced=True,
    ),
    FieldSpec(
        "reuse_max_diff", "差分阈值", GROUP_REUSE, "float",
        help="遮罩周边平均像素差超过该百分比就不复用，宁可重绘。",
        minimum=0.0, maximum=100.0, step=0.1, decimals=1, suffix="%", advanced=True,
    ),
    FieldSpec(
        "reuse_context_px", "差分上下文", GROUP_REUSE, "int",
        help="比较遮罩外多少像素的周边，提前发现背景变化。",
        minimum=0, maximum=256, step=2, suffix="px", advanced=True,
    ),
    FieldSpec(
        "reuse_min_group_iou", "分组最小 IoU", GROUP_REUSE, "float",
        help="预处理阶段两张图的遮罩重合度达到该值才归入同一差分候选组。",
        minimum=0.5, maximum=1.0, step=0.005, decimals=3, advanced=True,
    ),
    FieldSpec(
        "reuse_min_mask_iou", "复用最小 IoU", GROUP_REUSE, "float",
        help="真正复用前，当前裁切遮罩与缓存遮罩的重合度必须达到该值。",
        minimum=0.9, maximum=1.0, step=0.001, decimals=3, advanced=True,
    ),
    FieldSpec(
        "reuse_p99_factor", "99 分位倍数", GROUP_REUSE, "float",
        help="像素差 99 分位允许为平均差阈值的多少倍，防止局部突变被平均掉。",
        minimum=1.0, maximum=10.0, step=0.1, decimals=1, advanced=True,
    ),
    # ------------------------------------------------------------- advanced
    FieldSpec("imgsz", "检测输入尺寸", GROUP_ADVANCED, "int",
             help="YOLO 推理时的输入边长，越大越准也越慢。",
             minimum=320, maximum=2048, step=32, suffix="px", advanced=True),
    FieldSpec("lora_strength", "LoRA 强度", GROUP_ADVANCED, "float",
             help="去码 LoRA 的作用强度。",
             minimum=0.0, maximum=2.0, step=0.05, decimals=2, advanced=True),
)

# Every parameter shown on the tuning page belongs to a preset: switching
# presets restores the whole page (detection, crop, sampling, blend), and edits
# made while a preset is active are stored as overrides in
# ``Settings.preset_values`` instead of switching to the custom preset.
PRESET_GROUPS: tuple[str, ...] = (
    GROUP_DETECTION,
    GROUP_CROP,
    GROUP_SAMPLING,
    GROUP_BLEND,
    GROUP_BLEND_SEAMLESS,
    GROUP_BLEND_LAPLACIAN,
)
PRESET_VALUE_KEYS: tuple[str, ...] = tuple(
    spec.key for spec in FIELD_SPECS if spec.group in PRESET_GROUPS
)


def spec_for(key: str) -> FieldSpec:
    for spec in FIELD_SPECS:
        if spec.key == key:
            return spec
    raise KeyError(key)


def specs_in_group(group: str) -> list[FieldSpec]:
    return [s for s in FIELD_SPECS if s.group == group]


def format_value(spec: FieldSpec | None, value: Any) -> str:
    if isinstance(value, bool):
        return "开" if value else "关"
    if spec is not None and spec.kind == "float":
        return f"{float(value):.{spec.decimals}f}{spec.suffix}"
    if spec is not None and spec.kind == "int":
        return f"{int(value)}{spec.suffix}"
    if spec is not None and spec.kind == "choice":
        for choice in spec.choices:
            if choice.value == value:
                return choice.label
    return str(value)


# ------------------------------------------------------------------- defaults
DEFAULTS = Settings().to_mapping()


def default_output_dir(input_dir: str) -> str:
    if not input_dir:
        return ""
    return os.path.normpath(input_dir) + "_uncensored"


# ------------------------------------------------------------------- loading
def load_settings(path: str = CONFIG_PATH) -> Settings:
    """Load settings from ``path``; a missing file simply yields the defaults."""
    data = _read_json(path)
    settings = Settings.from_mapping(data)
    return _normalize_loaded(settings, path)


def save_settings(settings: Settings, path: str = CONFIG_PATH) -> None:
    """Atomically persist settings.  Never raises for the caller's comfort."""
    tmp = path + ".tmp"
    try:
        data = settings.to_mapping()
        for key in PATH_KEYS:
            data[key] = repair_path(data[key])
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def reset_settings() -> Settings:
    return Settings()


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        # utf-8-sig tolerates the BOM that Windows editors add when the user
        # hand-edits config.json (Notepad "UTF-8" writes one).
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _normalize_loaded(settings: Settings, path: str) -> Settings:
    """Repair paths that went through a non-UTF-8 file dialog.

    Nothing is detected or filled in here: ComfyUI and Python locations are
    configured by the user, never guessed.
    """
    changes: dict[str, Any] = {}
    for key in PATH_KEYS:
        value = getattr(settings, key)
        fixed = repair_path(value)
        if fixed != value:
            changes[key] = fixed

    if changes:
        settings = settings.merged(**changes)
        save_settings(settings, path)
    return settings


def _clean_preset_values(value: Any) -> dict[str, dict[str, Any]]:
    """Keep only known preset ids and preset-owned keys with coerced values."""
    if not isinstance(value, Mapping):
        return {}
    defaults = Settings()
    clean: dict[str, dict[str, Any]] = {}
    for preset_id, overrides in value.items():
        if not isinstance(preset_id, str) or not isinstance(overrides, Mapping):
            continue
        entry: dict[str, Any] = {}
        for key in PRESET_VALUE_KEYS:
            if key in overrides:
                entry[key] = _coerce(overrides[key], getattr(defaults, key))
        if entry:
            clean[preset_id] = entry
    return clean


def _coerce(value: Any, fallback: Any) -> Any:
    """Coerce JSON/UI strings to the declared field type, falling back safely."""
    try:
        if isinstance(fallback, bool):
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on", "是", "开")
            return bool(value)
        if isinstance(fallback, int):
            return int(float(value))
        if isinstance(fallback, float):
            return float(value)
        if isinstance(fallback, str):
            return str(value)
    except (TypeError, ValueError):
        return fallback
    return value


def _is_http_url(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def iter_settings(settings: Settings) -> Iterable[tuple[str, Any]]:
    return ((key, getattr(settings, key)) for key in DEFAULTS)
