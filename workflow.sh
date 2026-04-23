#!/bin/bash

set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "❌ 使用错误！"
    echo "💡 用法: $0 <视频文件路径> [fast|balanced|max] [--atr]"
    exit 1
fi

INPUT_FILE="$1"
PROFILE="${AUTO_SUBTITLE_PROFILE:-balanced}"
ENABLE_ATR="${AUTO_SUBTITLE_ENABLE_ATR:-0}"

for arg in "${@:2}"; do
    case "$arg" in
        fast|balanced|max)
            PROFILE="$arg"
            ;;
        --atr)
            ENABLE_ATR=1
            ;;
        *)
            echo "❌ 不支持的参数: $arg"
            echo "💡 可选 profile: fast, balanced, max"
            echo "💡 可选附加参数: --atr"
            exit 1
            ;;
    esac
done

if [ ! -f "$INPUT_FILE" ]; then
    echo "❌ 错误: 找不到文件 '$INPUT_FILE'"
    exit 1
fi

case "$PROFILE" in
    fast|balanced|max) ;;
    *)
        echo "❌ 不支持的 profile: $PROFILE"
        echo "💡 可选值: fast, balanced, max"
        exit 1
        ;;
esac

DIRNAME=$(dirname "$INPUT_FILE")
BASENAME=$(basename "$INPUT_FILE")
FILENAME="${BASENAME%.*}"
AUDIO_FILE="${DIRNAME}/${FILENAME}.wav"
SRT_FILE="${DIRNAME}/${FILENAME}.srt"
TXT_FILE="${DIRNAME}/${FILENAME}.txt"
REFINED_SRT_FILE="${DIRNAME}/${FILENAME}.atr.srt"
REFINED_TXT_FILE="${DIRNAME}/${FILENAME}.atr.txt"
ATR_REPORT_FILE="${DIRNAME}/${FILENAME}.atr_report.md"
GLOSSARY_FILE="${AUTO_SUBTITLE_GLOSSARY_FILE:-$(dirname "$0")/course_terms.json}"
MEMORY_FILE="${AUTO_SUBTITLE_MEMORY_FILE:-$(dirname "$0")/course_terms.memory.json}"
OUTPUT_FILE="${DIRNAME}/${FILENAME}_with_subs.mp4"
ACTIVE_SRT_FILE="$SRT_FILE"

echo "======================================"
echo "🚀 开始处理: $BASENAME"
echo "📂 所在目录: $DIRNAME"
echo "⚙️  转写模式: $PROFILE"
echo "📝 ATR 校对: $ENABLE_ATR"
echo "📚 术语词典: $GLOSSARY_FILE"
echo "🧠 术语记忆: $MEMORY_FILE"
echo "======================================"

echo "🎯 步骤 1: 提取 16kHz 单声道音频..."
ffmpeg -y -i "$INPUT_FILE" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$AUDIO_FILE"

echo "🎯 步骤 2: 使用 faster-whisper Turbo 生成字幕..."
python3 "$(dirname "$0")/transcribe_faster.py" \
    "$AUDIO_FILE" \
    --output_dir "$DIRNAME" \
    --basename "$FILENAME" \
    --language en \
    --profile "$PROFILE"

if [ ! -f "$SRT_FILE" ]; then
    echo "❌ 错误: 字幕文件未生成。"
    exit 1
fi

echo "✅ 字幕生成成功: $SRT_FILE"
if [ -f "$TXT_FILE" ]; then
    echo "✅ 检索文本生成成功: $TXT_FILE"
fi

if [ "$ENABLE_ATR" = "1" ]; then
    echo "🎯 步骤 3: 使用 OpenAI ATR 校对字幕..."
    python3 "$(dirname "$0")/refine_subtitles.py" \
        "$SRT_FILE" \
        --output_srt "$REFINED_SRT_FILE" \
        --output_txt "$REFINED_TXT_FILE" \
        --report_file "$ATR_REPORT_FILE" \
        --glossary_file "$GLOSSARY_FILE" \
        --memory_file "$MEMORY_FILE"
    ACTIVE_SRT_FILE="$REFINED_SRT_FILE"
    echo "✅ ATR 校对完成: $REFINED_SRT_FILE"
    echo "✅ ATR 术语报告: $ATR_REPORT_FILE"
    echo "✅ ATR 术语记忆: $MEMORY_FILE"
else
    echo "📝 提示: 如需 ATR 校对，可追加参数 --atr，或设置 AUTO_SUBTITLE_ENABLE_ATR=1。"
fi

echo "🎯 步骤 4: 正在将字幕压制进视频..."
ffmpeg -y -i "$INPUT_FILE" -vf "subtitles=\"${ACTIVE_SRT_FILE}\"" -c:a copy "$OUTPUT_FILE"

echo "======================================"
echo "🎉 处理完成！"
echo "📦 原始字幕: $SRT_FILE"
if [ "$ENABLE_ATR" = "1" ]; then
    echo "📦 校对字幕: $REFINED_SRT_FILE"
fi
echo "📦 输出视频: $OUTPUT_FILE"
echo "======================================"
