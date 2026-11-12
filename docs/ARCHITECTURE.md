# 架构说明

面向二次开发与代码审阅。用户文档见 [README](../README.md)。

---

## 1. 设计目标

- **区域级重绘**：只把遮挡区域裁出来交给 ComfyUI，整图不变。
- **可中断、可续跑**：每张图落一条清单记录，重启后跳过已完成项。
- **界面不阻塞**：所有耗时操作在 `TaskRunner` 的工作线程里跑，主线程只碰 Qt。
- **可测试**：网络、检测器、清单写入、目录扫描都能从构造参数替换。
- **单一配置来源**：`Settings` 冻结 dataclass + `SettingsStore`，界面只读写这一份。

---

## 2. 分层与依赖方向

```
┌─────────────── ui/ ───────────────┐
│ main_window, pages/, widgets/,    │
│ setup_dialog, theme, state, tasks │
└───────────────┬───────────────────┘
                │ 只往下
┌───────────────▼───── services/ ───┐
│ environment, preflight, presets,  │
│ reuse_groups, detector_cache      │
└───────────────┬───────────────────┘
                │
┌───────────────▼─────── core/ ─────┐
│ settings, discovery, pipeline,    │
│ workflow, detector, geometry,     │
│ blending, masking, manifest …     │
└───────────────────────────────────┘

cli.py ─────────────► core/
```

规则（由 `tests/test_architecture.py` 强制）：

- `core/` 与 `services/` **不得** `import PySide6` / `PyQt*` / `tkinter`。
- `core/` 不导入 `services/` 或 `ui/`。
- 只有 `ui/app.py` 创建 `QApplication`。

---

## 3. 核心模块

| 模块 | 职责 |
| --- | --- |
| `core/settings.py` | `Settings` 冻结 dataclass、`FIELD_SPECS`、校验、`config.json` 读写 |
| `core/discovery.py` | `discover_images()`、`find_ultralytics_model()`、`looks_like_comfy()` |
| `core/pipeline.py` | 批处理主循环、单图"检测→裁切→重绘→贴回" |
| `core/comfy.py` | ComfyUI HTTP 客户端：上传、排队、轮询、下载 |
| `core/detector.py` | Ultralytics YOLO 分割封装（torch / ultralytics 惰性导入） |
| `core/workflow.py` | 组工作流图（固定节点 ID 1–14） |
| `core/geometry.py` | 裁切框、面积规则、坐标换算 |
| `core/crop_groups.py` | 相邻检测框聚组 |
| `core/masking.py` / `core/maskplan.py` | 遮罩生成与外扩 |
| `core/manual_mask.py` | 手动遮罩编解码 |
| `core/blending.py` | 泊松 / 多频段 / 硬贴回 |
| `core/imaging.py` | 读写、缩放、色彩转换 |
| `core/manifest.py` | 清单 CSV（原子追加） |
| `services/environment.py` | 连接探测、节点/模型校验、在已填目录内自动找权重 |
| `services/preflight.py` | 预处理：检测结果缓存、遮罩落盘、断点判断 |
| `services/reuse_groups.py` | 差分分组与复用判定 |
| `ui/state.py` | `SettingsStore`：唯一可变状态 + 600ms 防抖落盘 |
| `ui/setup_dialog.py` | 首次使用向导（Python → ComfyUI → 模型） |

---

## 4. 单张图的数据流

```
输入图 ─► discover_images（扫描）
        ─► MosaicDetector.detect（区域列表）
        ─► crop_groups（聚组）
        ─► geometry（裁切 + 外扩 + 缩放）
        ─► ComfyClient.upload_png / run_prompt / download
        ─► blending（贴回原图）
        ─► imaging.save + manifest.append
```

`Pipeline` 负责编排；每一步都是纯函数或可注入对象，因此单测不需要 ComfyUI。

### 预处理（preflight）

「预处理」先把检测结果算完并缓存到 `_AnimeMosaicStudio_preflight/index.json`，同时把遮罩写到 `_AnimeMosaicStudio_masks/`。开始处理时直接读缓存，避免重复检测；参数变化后缓存会被标记为过期。

### 差分复用

`services/reuse_groups.py` 把"裁切窗口 + 生成参数 + 模型 + 有效提示词（不含 seed）"相同的图片分到一组，用像素差异决定是否能直接复用上一张的结果。组信息存在 `_AnimeMosaicStudio_reuse_groups.json`，可在界面里查看与禁用。

### 检测模型缓存

`services/detector_cache.py` 按 `(mosaic_model, nsfw_model, device, imgsz)` 缓存已加载的 YOLO 实例，预处理与正式处理共用，避免重复加载权重。

### 连接状态

`MainWindow` 每 8 秒静默 ping 一次 `/system_stats`，用 `_probe_busy` 防重入；地址变更后 700ms 防抖再探测。状态或版本变化才写日志。

---

## 5. 设置：唯一数据源

```
config.json ──load_settings──► Settings（frozen）──► SettingsStore
                                                     │ set()/update()
                                                     ▼
                                     600ms 防抖 save_settings（tmp + os.replace）
```

- `Settings` 是冻结 dataclass，字段元信息在 `FIELD_SPECS`（标签、分组、类型、范围、帮助文本），界面据此自动生成控件。
- `SettingsStore` 是唯一可变状态；`set/update/replace` 置脏并排一次保存，`save_now()` 立即落盘。
- `config.json` 与程序同目录（`core/settings.py` 的 `CONFIG_PATH`），**不入库**。
- 加载时**不做任何探测与填充**：`load_settings()` 只读文件、修路径（外部对话框的编码问题）、合并默认值。
- 首次使用由两步兜底：
  1. `launcher.py` 按 `config.json` → `AMS_PYTHON` → PATH 上的 `python.exe` → `py` 启动器的顺序找解释器，**每个候选都先试运行**（Store 占位符会因此被跳过）；全都不行时才弹系统文件选择框，并把选择写回 `config.json`；
  2. 界面首次启动（配置里没有 ComfyUI 目录）打开 `ui/setup_dialog.py` 三步向导。
- `config.json.example` 是给没有向导的命令行用户的空白模板：键集合必须与 `DEFAULTS` 一致（`tests/test_settings.py` 会校验），路径字段全部为空串。
- 读取用 `utf-8-sig`：用户用记事本手改配置时带入的 BOM 不会让整个文件被当成损坏。
- 写入失败（只读目录、权限）被静默忽略，界面仍可用，只是不持久化。

---

## 6. 可注入依赖

```python
Pipeline(
    settings,
    reporter,
    stop_event=None,
    client_factory=ComfyClient,
    detector_factory=MosaicDetector,
    detector_provider=None,
    manifest_factory=ManifestWriter,
    discovery=discover_images,
    mask_store_factory=ManualMaskStore,
)
```

- `client_factory(settings)` → 后端客户端，需实现 `upload_png / run_prompt / download / ping / check_environment`。
- `detector_factory(path, device, imgsz)` → 需实现 `load()` 与 `detect(rgb)`。
- `detector_provider()` → 复用已加载的检测器（`DetectorCache`）。
- `manifest_factory(path)` → 清单写入器。

测试里全部替换为内存实现，所以 `tests/` 不需要网络和 GPU。

---

## 7. 线程模型

```
主线程（Qt）                      工作线程（TaskRunner）
├─ 界面事件、绘制                  ├─ pipeline.run()
├─ SettingsStore                  ├─ ComfyClient（HTTP 轮询）
├─ 8s 连接探测                    ├─ 检测器加载 / 推理
└─ 收到信号刷新界面 ◄── Signal ───┘ 每 0.35s 检查 stop_event
```

- 停止：`stop_event.set()`，工作线程在检查点退出；`shutdown` 最多等 2.5s。
- 界面更新只通过 Qt 信号回到主线程。
- 预处理有独立的进度与取消路径，和正式处理互不阻塞。

---

## 8. UI 结构

```
MainWindow
├─ Sidebar                     六页导航
├─ Header                      标题 / 主题切换 / 连接状态
├─ QStackedWidget
│  ├─ WorkspacePage            输入输出、预处理入口、结果列表、相册
│  ├─ TuningPage               预设 + 全部参数
│  ├─ PromptsPage              正向 / 反向 / NSFW 部位词
│  ├─ SettingsPage             Python、连接、模型、检测器、输出行为、维护
│  ├─ LogsPage                 日志筛选、搜索、复制
│  └─ AboutPage                简介、流程、许可
├─ ActionBar                   预设选择、预处理、开始/停止
└─ ToastManager                轻提示

对话框：SetupDialog（首次向导）、PreflightDialog（预处理 + 手动遮罩）、
        ReuseGroupsDialog（差分管理）、ResultCompareDialog（对比）、
        PostProcessDialog（后处理，占位）
```

主题由 `ui/theme.py` 的 QSS 模板 + `Palette` 生成，切换时不重启；

---

## 9. 错误处理

| 异常 | 来源 | 处理 |
| --- | --- | --- |
| `PipelineError` | 单图处理失败 | 记入清单 `status=error`，继续下一张 |
| `ComfyError` | 通信/工作流失败 | 单图失败；连续 5 次通信失败则中止整批 |
| `DetectorError` | 模型加载/推理失败 | 中止当前阶段并提示 |
| `Cancelled` | 用户停止 | 正常收尾，清单保持可续跑 |
| `ModuleNotFoundError` | 缺依赖 | `.pyw` 弹窗给出 `pip install -r requirements.txt` |

日志：`logging_setup.py` 写 `AnimeMosaicStudio.log`，2 MB × 2 滚动。

---

## 10. 测试策略

| 文件 | 覆盖 |
| --- | --- |
| `test_settings.py` | 默认值、校验、序列化、预设 |
| `test_core_units.py` | 几何、裁切分组、遮罩、融合、工作流图 |
| `test_pipeline.py` | 完整流程（假客户端/假检测器）、清单、续跑、融合一致性 |
| `test_preflight.py` / `test_preflight_cache.py` | 预处理缓存与失效 |
| `test_reuse_groups.py` | 差分分组与复用判定 |
| `test_detector_cache.py` | 检测器缓存键 |
| `test_output_index.py` / `test_output_state.py` | 输出索引与状态 |
| `test_launcher.py` | 解释器解析、`config.json` 写入、依赖探测 |
| `test_ui.py` | 无头 UI 冒烟（`QT_QPA_PLATFORM=offscreen`） |
| `test_architecture.py` | 分层约束 |

运行：

```bat
python -m unittest discover -s tests -t .
```

---

## 11. 扩展指南

**新增融合方式**：在 `core/blending.py` 加实现并注册到 `BLEND_METHODS`，`Settings.blend` 的 choices 自动带上，参数页无需改动。

**新增预设**：在 `services/presets.py` 的 `PRESETS` 里加一个 `Preset`，值为 `Settings` 字段覆盖；界面与 CLI 自动出现。

**新增设置项**：在 `core/settings.py` 的 `Settings` 加字段 + `FIELD_SPECS` 加一条（分组决定它出现在哪一页）。`from_mapping/merged/validate` 无需手改。

**新增页面**：加 `ui/pages/xxx.py`，在 `main_window.py` 的 `PAGE_META` 与 `_build()` 里注册。

**新增检测器**：实现 `load()` / `detect(rgb) -> list[Box]`，通过 `detector_factory` 注入，无需改 `Pipeline`。

---

## 12. 已知边界

- 工作流节点 ID 固定为 `"1"`–`"14"`，并依赖 `ApplyCosmosReferenceLatent`；换工作流要改 `core/workflow.py`。
- 界面文案只有中文，没有 i18n 层。
- 后处理（对比视图里的锐化/降噪）是占位实现。
- 启动器是 Windows 专用（`ctypes` 文件对话框、`DETACHED_PROCESS`）。
- 差分复用最多缓存 8 组，超出按最近使用淘汰。


## 13. 项目结构

```
AnimeMosaicStudio/
├─ AnimeMosaicStudioLauncher.exe   启动器
├─ AnimeMosaicStudio.pyw           界面入口
├─ launcher.py                     启动器源码
├─ build_launcher.bat              用 PyInstaller 重建启动器
├─ install dependencies.bat        安装 requirements.txt
├─ Start AnimeMosaicStudio.bat     启动界面
├─ cli run.bat                     命令行入口
├─ requirements.txt
├─ config.json                     本地配置
├─ config.json.example             配置模板
├─ anime_mosaic/
│  ├─ core/       settings, discovery, pipeline, workflow, detector, geometry, blending …
│  ├─ services/   environment, preflight, presets, reuse_groups, autodetect …
│  └─ ui/         app, main_window, setup_dialog, pages/, widgets/, theme
├─ tests/         单元/集成测试
├─ docs/          ARCHITECTURE.md
└─ tools/
```

依赖方向：`ui → services → core`，`cli → core`。`core` 与 `services` 不导入 Qt。
