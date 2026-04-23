# Transcript Refiner & Subtitle Generator

本项目旨在为课程提供一套高效、精准的自动化字幕生成与学术校对方案。通过集成 **Whisper Turbo** 与 **faster-whisper / CTranslate2** 高吞吐推理链路，再结合 **OpenAI LLM** 学术语义校正技术，该工具能够将原始课堂录音转化为高质字幕与检索索引。

输入：课程视频

交付物：.srt字幕 与 .txt检索索引

## 🌟 核心功能 (Core Features)

- **高性能转录**: 采用 **Whisper Turbo (large-v3-turbo)** 与 **faster-whisper**，针对英文讲课环境优化，实现远超实时速度的文本提取。
- **5090 优化档位**: 内置 `fast`、`balanced`、`max` 三个 profile，支持利用高显存 GPU 提高 batch 吞吐。
- **ATR 自动校对**: 可选接入 OpenAI 模型进行学术语义校对，针对 **COMP2211** 等课程特性自动修正以下内容：
  - **术语纠错**: 修正口音引起的识别偏差，如 *NumPy*, *Matplotlib*, *Pandas*, *Palindrome*, *Pseudocode* 等。
  - **去噪处理**: 智能剔除口语语气词（uh, um, right）及无意义的重复，提升阅读体验。
  - **格式统一**: 强制课程代码为 **COMP1023** 规范格式，并确保句首字母大写与专有名词拼写正确。
- **一键式流水线**: 集成 Bash 脚本，实现从“原始视频输入”到“提取音频 -> 生成字幕 -> LLM 校对 -> 硬字幕压制”的全自动化流程。

## 🏗️ 技术架构 (Technical Pipeline)

1. **Preprocessing**: 利用 **FFmpeg** 提取 16kHz 单声道 WAV，以减少解码开销并匹配 Whisper 输入标准。
2. **Transcription**: 使用 **faster-whisper** 的 batched pipeline 在 GPU 上运行 Whisper Turbo，并输出标准 `.srt` 与 `.txt` 文件。
3. **Refinement**: 通过预设的 **Academic Transcript Refiner** 指令集，调用 OpenAI Responses API 对字幕进行二次语义对齐，并输出 `.atr.srt`、`.atr.txt` 和术语报告。
4. **Integration**: 使用 FFmpeg `subtitles` 滤镜将校对后的字幕硬编码至视频中，确保移动端学习的兼容性。

## 🚀 快速开始 (Quick Start)

先安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

如需使用 ATR 校对，请设置 OpenAI API Key：

```bash
export OPENAI_API_KEY="your_api_key"
```

在终端中运行以下指令即可处理指定的课程视频：

```bash
chmod +x workflow.sh
./workflow.sh <path_to_lecture_video.mp4> balanced
```

如需直接使用 `RTX 5090` 优化版 `faster-whisper` 自动脚本：

```bash
chmod +x workflow_fastwhisper_5090.sh
./workflow_fastwhisper_5090.sh <path_to_lecture_video.mp4> balanced
```

可选 profile：

- `fast`: 更低 beam，优先速度
- `balanced`: 默认档，适合课程字幕正式产出
- `max`: 更大 batch，适合高显存 GPU 压榨吞吐

如需启用 ATR：

```bash
./workflow.sh <path_to_lecture_video.mp4> balanced --atr
```

`workflow_fastwhisper_5090.sh` 也支持：

```bash
./workflow_fastwhisper_5090.sh <path_to_lecture_video.mp4> throughput --atr
```

也可以单独调用转写入口：

```bash
python3 transcribe_faster.py input.wav --output_dir . --profile max --language en
```

也可以单独调用 ATR 校对：

```bash
python3 refine_subtitles.py lecture.srt
```

如需指定自定义术语词典：

```bash
AUTO_SUBTITLE_GLOSSARY_FILE=./course_terms.json ./workflow.sh lecture.mp4 balanced --atr
```

如需指定术语记忆文件：

```bash
AUTO_SUBTITLE_MEMORY_FILE=./course_terms.memory.json ./workflow.sh lecture.mp4 balanced --atr
```

## ⚙️ RTX 5090 调优建议

- 首选 `balanced`，确认稳定后改用 `max`
- 默认使用 `cuda + float16 + vad_filter`
- 长 lecture 先抽音频再转写，避免边解码边推理拖慢 GPU
- 批量处理多节课时，优先排队给单个高吞吐 GPU worker，而不是多进程抢同一张卡

## 🧩 CUDA 注意事项

- `faster-whisper` 底层依赖 `CTranslate2`，当前 GPU 路线优先面向 `CUDA 12 + cuBLAS 12 + cuDNN 9`
- 如果 `RTX 5090` 上跑不起来，最常见原因不是脚本本身，而是 `CUDA / cuDNN / ctranslate2` 版本不匹配
- 当前项目默认配置面向 `device=cuda` 和 `compute_type=float16`，适合高显存 NVIDIA GPU
- `faster-whisper` 自带 `PyAV` 音频解码能力，但本项目仍使用 `ffmpeg` 预抽 `16kHz mono WAV`，这样更稳，也更利于吞吐调优

**推荐环境**

- NVIDIA Driver：使用与你本机 `CUDA 12` 运行时兼容的较新驱动
- CUDA Runtime：优先 `CUDA 12`
- cuDNN：优先 `cuDNN 9`
- Python：建议 `3.10+`

**常见兼容性问题**

- 如果你是 `CUDA 11 + cuDNN 8` 老环境，最新 `ctranslate2` 往往不能直接工作
- 如果你是 `CUDA 12 + cuDNN 8`，也可能出现版本不兼容
- 这两类情况通常需要固定 `ctranslate2` 到兼容版本，而不是只重装 `faster-whisper`

**排错建议**

- 先确认 `nvidia-smi` 能正常识别 `RTX 5090`
- 再确认 Python 环境里安装的是 `faster-whisper`，而不是误装成仅 CPU 可跑的残缺环境
- 如果报缺少 `cublas`、`cudnn`、`libcudnn`、`cublas64` 之类错误，优先检查 CUDA 库路径和版本匹配
- 如果模型能加载但速度很慢，通常说明没有真正走到 GPU，可先检查日志里的 `device=cuda`
- 如果 `throughput` 档不稳定，可先把 `AUTO_SUBTITLE_5090_BATCH_SIZE` 从 `96` 降到 `64` 或 `48`

**版本回退思路**

- `CUDA 11 + cuDNN 8`：通常需要回退到 `ctranslate2==3.24.0`
- `CUDA 12 + cuDNN 8`：通常需要回退到 `ctranslate2==4.4.0`
- 如果你已经是 `CUDA 12 + cuDNN 9`，优先保持较新的 `ctranslate2 / faster-whisper`

**检查命令**

```bash
nvidia-smi
python3 -c "import faster_whisper; print('faster-whisper ok')"
python3 -c "import ctranslate2; print(ctranslate2.__version__)"
```

## 🚀 5090 专用脚本

- 专用脚本为 `workflow_fastwhisper_5090.sh:1`
- `speed` 使用 `batch_size=48, beam_size=1`，适合快速草稿
- `balanced` 使用 `batch_size=64, beam_size=3`，适合正式字幕
- `throughput` 使用 `batch_size=96, beam_size=1`，优先榨干 `RTX 5090`
- 可通过 `AUTO_SUBTITLE_5090_BATCH_SIZE`、`AUTO_SUBTITLE_5090_BEAM_SIZE` 覆盖默认值
- 可通过 `--no-burn` 仅输出字幕，通过 `--keep-wav` 保留中间音频

## 🧠 ATR 调优建议

- 默认模型为 `gpt-5.4-mini`，可通过 `AUTO_SUBTITLE_ATR_MODEL` 覆盖
- 默认每次发送 `120` 条字幕，可通过 `AUTO_SUBTITLE_ATR_CHUNK_SIZE` 调整
- 默认读取 `course_terms.json`，可通过 `AUTO_SUBTITLE_GLOSSARY_FILE` 或 `--glossary_file` 指向自定义词典
- 默认自动回写 `course_terms.memory.json`，可通过 `AUTO_SUBTITLE_MEMORY_FILE` 或 `--memory_file` 改位置
- 输出文件包括 `.atr.srt`、`.atr.txt` 与 `.atr_report.md`
- 硬字幕压制时，若启用 ATR，会优先使用 `.atr.srt`

## 📚 课程术语词典

- 默认词典文件为 `course_terms.json:1`
- 自动积累词典为 `course_terms.memory.json:1`
- `protected_terms` 用于告诉 ATR 哪些写法必须优先保留
- `replacement_hints` 用于告诉 ATR 哪些常见误识别应该纠正成标准术语
- `hard_replacements` 用于做本地确定性规范化，适合课程代码、固定品牌名等低歧义项
- `learned_pairs` 会记录 ATR 实际纠正过的 `from → to`、次数和时间，作为长期记忆来源
- 建议把稳定规则手工整理到 `course_terms.json:1`，把自动学习结果留在 `course_terms.memory.json:1`

## 📅 未来展望 (Future Work)

作为 COMP2211+ 项目的一部分，该工具未来将支持：

- **知识点自动索引**: 基于字幕内容自动提取 Lecture 的关键知识点时间轴。
- **多语言翻译**: 为非母语同学提供更精准的术语对照翻译。
- **课程术语词典长期记忆**

------

**Developed by:** Jiahao (Charles) Zhang

**Supervised by:** Prof. Desmond Tsoi

**Course:** COMP2211, HKUST
