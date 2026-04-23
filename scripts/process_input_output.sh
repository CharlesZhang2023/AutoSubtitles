#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${AUTO_SUBTITLE_ENV_FILE:-$PROJECT_ROOT/config/packy.env}"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

INPUT_DIR="${AUTO_SUBTITLE_INPUT_DIR:-$PROJECT_ROOT/input}"
OUTPUT_DIR="${AUTO_SUBTITLE_OUTPUT_DIR:-$PROJECT_ROOT/output}"
MODE="${AUTO_SUBTITLE_5090_MODE:-balanced}"
ENABLE_ATR="${AUTO_SUBTITLE_ENABLE_ATR:-0}"
KEEP_WAV=0

usage() {
    cat <<EOF
💡 用法:
  $0 [speed|balanced|throughput] [--atr] [--keep-wav]

说明:
  - 默认从 $INPUT_DIR 读取视频
  - 默认把 .srt / .txt 写到 $OUTPUT_DIR
  - speed: 更快出结果
  - balanced: 默认档，适合 5090 日常跑批
  - throughput: 更高 batch，优先吃满 5090
  - --atr: 额外生成 ATR 校对结果
  - --keep-wav: 保留中间 16kHz WAV
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    usage
    exit 0
fi

for arg in "$@"; do
    case "$arg" in
        speed|balanced|throughput)
            MODE="$arg"
            ;;
        --atr)
            ENABLE_ATR=1
            ;;
        --keep-wav)
            KEEP_WAV=1
            ;;
        *)
            echo "❌ 不支持的参数: $arg"
            usage
            exit 1
            ;;
    esac
done

case "$MODE" in
    speed)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-48}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-1}"
        TRANSCRIBE_PROFILE="fast"
        ;;
    balanced)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-64}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-3}"
        TRANSCRIBE_PROFILE="balanced"
        ;;
    throughput)
        BATCH_SIZE="${AUTO_SUBTITLE_5090_BATCH_SIZE:-96}"
        BEAM_SIZE="${AUTO_SUBTITLE_5090_BEAM_SIZE:-1}"
        TRANSCRIBE_PROFILE="max"
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
export HF_ENDPOINT="${AUTO_SUBTITLE_HF_ENDPOINT:-${HF_ENDPOINT:-https://hf-mirror.com}}"
GLOSSARY_FILE="${AUTO_SUBTITLE_GLOSSARY_FILE:-$PROJECT_ROOT/config/course_terms.json}"
MEMORY_FILE="${AUTO_SUBTITLE_MEMORY_FILE:-$PROJECT_ROOT/config/course_terms.memory.json}"

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR"

shopt -s nullglob
video_files=(
    "$INPUT_DIR"/*.mp4
    "$INPUT_DIR"/*.mkv
    "$INPUT_DIR"/*.mov
    "$INPUT_DIR"/*.avi
    "$INPUT_DIR"/*.m4v
    "$INPUT_DIR"/*.webm
)
shopt -u nullglob

if [ "${#video_files[@]}" -eq 0 ]; then
    echo "⚠️  $INPUT_DIR 里没有找到可处理的视频文件。"
    echo "💡 支持的格式: mp4, mkv, mov, avi, m4v, webm"
    exit 0
fi

echo "======================================"
echo "🚀 AutoSubtitle input/output 批处理"
echo "📥 input:  $INPUT_DIR"
echo "📤 output: $OUTPUT_DIR"
echo "⚙️  mode:  $MODE"
echo "🌐 HF_ENDPOINT=$HF_ENDPOINT"
echo "📦 batch_size=$BATCH_SIZE beam_size=$BEAM_SIZE"
echo "📝 ATR:   $ENABLE_ATR"
echo "======================================"

for input_file in "${video_files[@]}"; do
    basename="$(basename "$input_file")"
    filename="${basename%.*}"
    audio_file="$OUTPUT_DIR/${filename}.16k.wav"
    srt_file="$OUTPUT_DIR/${filename}.srt"
    txt_file="$OUTPUT_DIR/${filename}.txt"
    refined_srt_file="$OUTPUT_DIR/${filename}.atr.srt"
    refined_txt_file="$OUTPUT_DIR/${filename}.atr.txt"
    atr_report_file="$OUTPUT_DIR/${filename}.atr_report.md"

    echo
    echo "--------------------------------------"
    echo "🎬 正在处理: $basename"
    echo "--------------------------------------"

    ffmpeg -y -i "$input_file" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$audio_file"

    python3 "$PROJECT_ROOT/autosubtitle/transcribe_faster.py" \
        "$audio_file" \
        --output_dir "$OUTPUT_DIR" \
        --basename "$filename" \
        --language "$LANGUAGE" \
        --device "$DEVICE" \
        --model "$MODEL" \
        --profile "$TRANSCRIBE_PROFILE" \
        --compute_type "$COMPUTE_TYPE" \
        --batch_size "$BATCH_SIZE" \
        --beam_size "$BEAM_SIZE"

    if [ ! -f "$srt_file" ] || [ ! -f "$txt_file" ]; then
        echo "❌ 处理失败: $basename 未生成完整的字幕结果"
        exit 1
    fi

    echo "✅ 输出字幕: $srt_file"
    echo "✅ 输出文本: $txt_file"

    if [ "$ENABLE_ATR" = "1" ]; then
        python3 "$PROJECT_ROOT/autosubtitle/refine_subtitles.py" \
            "$srt_file" \
            --output_srt "$refined_srt_file" \
            --output_txt "$refined_txt_file" \
            --report_file "$atr_report_file" \
            --glossary_file "$GLOSSARY_FILE" \
            --memory_file "$MEMORY_FILE"

        echo "✅ ATR 字幕: $refined_srt_file"
        echo "✅ ATR 文本: $refined_txt_file"
    fi

    if [ "$KEEP_WAV" != "1" ]; then
        rm -f "$audio_file"
    fi
done

echo
echo "======================================"
echo "🎉 批处理完成"
echo "📥 输入目录: $INPUT_DIR"
echo "📤 输出目录: $OUTPUT_DIR"
echo "======================================"
