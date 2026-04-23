#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    cat <<EOF
💡 用法:
  $0 <视频文件路径> [speed|balanced|throughput] [--atr] [--no-burn] [--keep-wav]

说明:
  - speed: 最低延迟，适合快速出字幕草稿
  - balanced: 默认档，适合 5090 正式跑课件字幕
  - throughput: 极限吞吐，优先吃满 5090 显存
  - --atr: 启用 ATR 学术校对
  - --no-burn: 不压制硬字幕，只产出字幕文件
  - --keep-wav: 保留中间生成的 16kHz WAV
EOF
}

if [ -z "${1:-}" ]; then
    usage
    exit 1
fi

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

INPUT_FILE="$1"
MODE="${AUTO_SUBTITLE_5090_MODE:-balanced}"
ENABLE_ATR="${AUTO_SUBTITLE_ENABLE_ATR:-0}"
BURN_SUBS=1
KEEP_WAV=0

for arg in "${@:2}"; do
    case "$arg" in
        speed|balanced|throughput)
            MODE="$arg"
            ;;
        --atr)
            ENABLE_ATR=1
            ;;
        --no-burn)
            BURN_SUBS=0
            ;;
        --keep-wav)
            KEEP_WAV=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "❌ 不支持的参数: $arg"
            usage
            exit 1
            ;;
    esac
done

if [ ! -f "$INPUT_FILE" ]; then
    echo "❌ 错误: 找不到文件 '$INPUT_FILE'"
    exit 1
fi

case "$MODE" in
    speed)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-48}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-1}"
        ;;
    balanced)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-64}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-3}"
        ;;
    throughput)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-96}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-1}"
        ;;
    *)
        echo "❌ 不支持的模式: $MODE"
        usage
        exit 1
        ;;
esac

MODEL="${AUTO_SUBTITLE_MODEL:-turbo}"
LANGUAGE="${AUTO_SUBTITLE_LANGUAGE:-en}"
DEVICE="${AUTO_SUBTITLE_DEVICE:-cuda}"
COMPUTE_TYPE="${AUTO_SUBTITLE_COMPUTE_TYPE:-float16}"
GLOSSARY_FILE="${AUTO_SUBTITLE_GLOSSARY_FILE:-$PROJECT_ROOT/config/course_terms.json}"
MEMORY_FILE="${AUTO_SUBTITLE_MEMORY_FILE:-$PROJECT_ROOT/config/course_terms.memory.json}"

DIRNAME=$(dirname "$INPUT_FILE")
BASENAME=$(basename "$INPUT_FILE")
FILENAME="${BASENAME%.*}"
AUDIO_FILE="${DIRNAME}/${FILENAME}.16k.wav"
SRT_FILE="${DIRNAME}/${FILENAME}.srt"
TXT_FILE="${DIRNAME}/${FILENAME}.txt"
REFINED_SRT_FILE="${DIRNAME}/${FILENAME}.atr.srt"
REFINED_TXT_FILE="${DIRNAME}/${FILENAME}.atr.txt"
ATR_REPORT_FILE="${DIRNAME}/${FILENAME}.atr_report.md"
OUTPUT_FILE="${DIRNAME}/${FILENAME}_with_subs.mp4"
ACTIVE_SRT_FILE="$SRT_FILE"

echo "======================================"
echo "🚀 RTX 5090 faster-whisper 自动处理"
echo "📂 输入文件: $INPUT_FILE"
echo "⚙️  模式: $MODE"
echo "🧠 model=$MODEL device=$DEVICE compute_type=$COMPUTE_TYPE"
echo "📦 batch_size=$BATCH_SIZE beam_size=$BEAM_SIZE"
echo "📝 ATR 校对: $ENABLE_ATR"
echo "🎞️  烧录字幕: $BURN_SUBS"
echo "======================================"

echo "🎯 步骤 1: 提取 16kHz 单声道 WAV..."
ffmpeg -y -i "$INPUT_FILE" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$AUDIO_FILE"

echo "🎯 步骤 2: 使用 faster-whisper Turbo 转写..."
python3 "$PROJECT_ROOT/autosubtitle/transcribe_faster.py" \
    "$AUDIO_FILE" \
    --output_dir "$DIRNAME" \
    --basename "$FILENAME" \
    --language "$LANGUAGE" \
    --device "$DEVICE" \
    --model "$MODEL" \
    --compute_type "$COMPUTE_TYPE" \
    --batch_size "$BATCH_SIZE" \
    --beam_size "$BEAM_SIZE"

if [ ! -f "$SRT_FILE" ]; then
    echo "❌ 错误: 字幕文件未生成。"
    exit 1
fi

echo "✅ 字幕生成成功: $SRT_FILE"
if [ -f "$TXT_FILE" ]; then
    echo "✅ 检索文本生成成功: $TXT_FILE"
fi

if [ "$ENABLE_ATR" = "1" ]; then
    echo "🎯 步骤 3: ATR 学术校对..."
    python3 "$PROJECT_ROOT/autosubtitle/refine_subtitles.py" \
        "$SRT_FILE" \
        --output_srt "$REFINED_SRT_FILE" \
        --output_txt "$REFINED_TXT_FILE" \
        --report_file "$ATR_REPORT_FILE" \
        --glossary_file "$GLOSSARY_FILE" \
        --memory_file "$MEMORY_FILE"
    ACTIVE_SRT_FILE="$REFINED_SRT_FILE"
    echo "✅ ATR 校对完成: $REFINED_SRT_FILE"
fi

if [ "$BURN_SUBS" = "1" ]; then
    echo "🎯 步骤 4: 压制硬字幕..."
    ffmpeg -y -i "$INPUT_FILE" -vf "subtitles=\"${ACTIVE_SRT_FILE}\"" -c:a copy "$OUTPUT_FILE"
    echo "✅ 输出视频: $OUTPUT_FILE"
else
    echo "⏭️  跳过硬字幕压制。"
fi

if [ "$KEEP_WAV" != "1" ]; then
    rm -f "$AUDIO_FILE"
fi

echo "======================================"
echo "🎉 处理完成"
echo "📦 原始字幕: $SRT_FILE"
if [ "$ENABLE_ATR" = "1" ]; then
    echo "📦 校对字幕: $REFINED_SRT_FILE"
    echo "📦 术语报告: $ATR_REPORT_FILE"
fi
if [ "$BURN_SUBS" = "1" ]; then
    echo "📦 输出视频: $OUTPUT_FILE"
fi
echo "======================================"
