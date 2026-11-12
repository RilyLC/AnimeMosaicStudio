# AnimeMosaicStudio

用 ComfyUI 做**区域级**去马赛克：只把被遮挡的那一小块裁出来重绘，再贴回原图。整张图其他地方都保持原样。

支持批处理、断点续跑、手动遮罩编辑、差分复用、结果对比，全部集成在一个桌面界面里。

![License](https://img.shields.io/badge/license-MIT-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4)

本项目的运行依赖以下模型：
| 用途 | 文件名 | 官方下载 |
| --- | --- | --- |
| 重绘主模型 (UNet) | anima-turbo-v1.1.safetensors | https://civitai.com/models/2458426 |
| 去码 LoRA | uncensored_lora_v6-000034.safetensors | https://civitai.red/models/2893720/uncensored-edit-anima-lora |
| 马赛克检测 | mosaic_detection_seg_L.pt | https://civitai.red/models/1308310/mosaic-detectionall-in-one |
| NSFW 部位检测 | ntd11_anime_nsfw_segm_v5-variant1.pt | https://civitai.red/models/1313556/anime-nsfw-detection-adetailer-all-in-one |

感谢以上模型作者及开源社区的贡献

> **免责声明**：使用本项目即表示你已确认：所有输入素材的版权与使用权限由你本人负责，生成结果仅供合法用途，开发者不对任何版权纠纷或使用后果承担责任。


---

## 目录

- [工作原理](#工作原理)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始](#快速开始)
- [输出结构](#输出结构)
- [常见问题](#常见问题)
- [许可](#许可)

---



## 工作原理

1. **检测**：YOLO 分割模型找出马赛克（可选 NSFW 部位）区域。
2. **裁切**：每个区域按面积规则裁成正方形，四周留出上下文，再缩放到 `size`。
3. **重绘**：把裁切图与掩码交给 ComfyUI，只对掩码区域采样。
4. **贴回**：用泊松融合或多频段融合贴回原图，边缘不留接缝。

同一张图内相邻的检测框会先聚成一组，避免同一块被反复重绘。

---

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows 10 / 11（64 位） |
| Python | 3.10 及以上 |
| ComfyUI | 0.3 及以上，`--listen 127.0.0.1 --port 8188` |
| 依赖 | 见 `requirements.txt`；含 torch、ultralytics、PySide6 |


---

## 安装

1. 下载源代码。
2. 双击 `Start AnimeMosaicStudio.bat`,或使用`build_launcher.bat`构建exe。
3. 第一次启动如果没有配置过 Python解释器，会弹出提示,解释器需要安装好项目所需依赖环境
4. 建议手动安装CUDA版torch,以获得更快的检测速度
5. ComfyUI需要能加载自定义节点工作流，参考工作流见根目录的workflow.json
---

## 快速开始

1. 启动 ComfyUI和本项目
2. 在工作台选择输入目录；输出目录会默认填成「输入目录名 + `_uncensored`」。
3. 点「预处理」：程序检测区域、生成遮罩，可以在预览里手动补/删。
4. 预处理完成后点「开始处理」。
5. 完成后在工作台看结果：可单张重生成、进对比视图或相册。

---

## 输出结构

```
<输出目录>/
├─ <相对路径>.<ext>                       处理后的图片（未检测到马赛克时为复制）
├─ _AnimeMosaicStudio_manifest.csv        清单：file,status,regions,seconds,seed,detections,message,time
├─ _AnimeMosaicStudio_masks/<相对路径>.mask.png   手动/预处理遮罩
├─ _AnimeMosaicStudio_preflight/index.json       预处理缓存
└─ _AnimeMosaicStudio_reuse_groups.json          差分分组
```

清单里的 `status` 取值：`processed` / `copied` / `skipped` / `error`。


---


## 常见问题

**启动器说找不到 Python**
启动器会依次尝试：`config.json` 的 `python_exe` → 环境变量 `AMS_PYTHON` → PATH 上的 `python.exe` → `py` 启动器登记的 Python。它会先运行每个候选确认可用，所以 Microsoft Store 的 `python.exe` 占位符会被跳过。都不行时才弹文件选择框；想重新弹，就把 `python_exe` 清空。

**提示缺少依赖**
确保config.json提供的Python解释器安装好了依赖,手动运行 `"<python>" -m pip install -r requirements.txt`。

**连不上 ComfyUI**
确认 ComfyUI 已启动、地址与「设置 → ComfyUI 连接」一致；点「测试连接」看具体报错。


**想让 torch 用 CUDA**
先按 https://pytorch.org 的说明装好对应 CUDA 版本的 torch。

**马赛克检测速度非常慢**
确保安装了CUDA版torch并使用GPU进行检测,如果配置较低可以考虑将马赛克检测模型从L模型换到S模型
---

