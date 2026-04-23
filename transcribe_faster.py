#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path


PROFILES = {
    "fast": {
        "batch_size": 48,
        "beam_size": 1,
        "compute_type": "float16",
        "vad_filter": True,
        "word_timestamps": False,
        "condition_on_previous_text": False,
    },
    "balanced": {
        "batch_size": 32,
        "beam_size": 3,
        "compute_type": "float16",
        "vad_filter": True,
        "word_timestamps": False,
        "condition_on_previous_text": False,
    },
    "max": {
        "batch_size": 64,
        "beam_size": 1,
        "compute_type": "float16",
        "vad_filter": True,
        "word_timestamps": False,
        "condition_on_previous_text": False,
    },
}


def format_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000.0)
    hours = milliseconds // 3_600_000
    milliseconds -= hours * 3_600_000
    minutes = milliseconds // 60_000
    milliseconds -= minutes * 60_000
    secs = milliseconds // 1000
    milliseconds -= secs * 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def write_srt(segments, srt_path: Path) -> None:
    with srt_path.open("w", encoding="utf-8") as handle:
        for index, segment in enumerate(segments, start=1):
            handle.write(f"{index}\n")
            handle.write(
                f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n"
            )
            handle.write(f"{segment.text.strip()}\n\n")


def write_txt(segments, txt_path: Path) -> None:
    with txt_path.open("w", encoding="utf-8") as handle:
        for segment in segments:
            text = segment.text.strip()
            if text:
                handle.write(text)
                handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="High-throughput Whisper Turbo transcription for long lectures."
    )
    parser.add_argument("input_file", help="Input audio or video file")
    parser.add_argument(
        "--output_dir",
        default=".",
        help="Directory for generated transcript files",
    )
    parser.add_argument(
        "--basename",
        default=None,
        help="Base filename for output files, defaults to input stem",
    )
    parser.add_argument(
        "--model",
        default="turbo",
        help="Whisper model name, defaults to turbo",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Language code passed to Whisper, defaults to en",
    )
    parser.add_argument(
        "--device",
        default="cuda",
        help="Inference device, defaults to cuda",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="balanced",
        help="Tuning profile for throughput vs decoding quality",
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        default=None,
        help="Override profile batch size",
    )
    parser.add_argument(
        "--beam_size",
        type=int,
        default=None,
        help="Override profile beam size",
    )
    parser.add_argument(
        "--compute_type",
        default=None,
        help="Override profile compute type",
    )
    parser.add_argument(
        "--word_timestamps",
        action="store_true",
        help="Enable word-level timestamps",
    )
    parser.add_argument(
        "--no_vad",
        action="store_true",
        help="Disable voice activity detection",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
    except ImportError:
        print(
            "❌ 缺少依赖 faster-whisper。请先运行: python3 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    preset = PROFILES[args.profile].copy()

    batch_size = args.batch_size or preset["batch_size"]
    beam_size = args.beam_size or preset["beam_size"]
    compute_type = args.compute_type or preset["compute_type"]
    vad_filter = False if args.no_vad else preset["vad_filter"]
    word_timestamps = args.word_timestamps or preset["word_timestamps"]
    condition_on_previous_text = preset["condition_on_previous_text"]

    input_path = Path(args.input_file).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    basename = args.basename or input_path.stem
    srt_path = output_dir / f"{basename}.srt"
    txt_path = output_dir / f"{basename}.txt"

    print("======================================")
    print(f"🚀 faster-whisper profile: {args.profile}")
    print(f"🧠 model={args.model} device={args.device} compute_type={compute_type}")
    print(f"📦 batch_size={batch_size} beam_size={beam_size} vad_filter={vad_filter}")
    print("======================================")

    model = WhisperModel(args.model, device=args.device, compute_type=compute_type)
    pipeline = BatchedInferencePipeline(model=model)
    segments, info = pipeline.transcribe(
        str(input_path),
        batch_size=batch_size,
        beam_size=beam_size,
        language=args.language,
        vad_filter=vad_filter,
        word_timestamps=word_timestamps,
        condition_on_previous_text=condition_on_previous_text,
    )

    segment_list = list(segments)
    write_srt(segment_list, srt_path)
    write_txt(segment_list, txt_path)

    print(f"✅ detected_language={info.language} probability={info.language_probability:.4f}")
    print(f"✅ wrote_srt={srt_path}")
    print(f"✅ wrote_txt={txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
