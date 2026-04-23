#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from autosubtitle.refine_subtitles import (  # noqa: E402
    dedupe_strings,
    merge_replacement_hints,
    normalize_term,
    should_learn_pair,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean noisy learned ATR term memory.")
    parser.add_argument(
        "--memory_file",
        default=str(PROJECT_ROOT / "config" / "course_terms.memory.json"),
        help="Path to the local learned memory file",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Show what would be kept without writing changes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    memory_path = Path(args.memory_file).expanduser().resolve()
    if not memory_path.is_file():
        print(f"⚠️  memory file not found: {memory_path}")
        return 0

    data = json.loads(memory_path.read_text(encoding="utf-8"))
    kept_pairs = []
    removed_pairs = []

    for item in data.get("learned_pairs", []):
        before = normalize_term(str(item.get("from", "")))
        after = normalize_term(str(item.get("to", "")))
        if should_learn_pair(before, after):
            kept_pairs.append(item)
        else:
            removed_pairs.append(item)

    hints = {}
    for item in kept_pairs:
        canonical = normalize_term(str(item.get("to", "")))
        variant = normalize_term(str(item.get("from", "")))
        if not canonical or not variant:
            continue
        entry = hints.setdefault(canonical.casefold(), {"canonical": canonical, "variants": []})
        variants = {value.casefold() for value in entry["variants"]}
        if variant.casefold() != canonical.casefold() and variant.casefold() not in variants:
            entry["variants"].append(variant)

    cleaned = {
        **data,
        "protected_terms": dedupe_strings([str(item.get("to", "")) for item in kept_pairs]),
        "replacement_hints": merge_replacement_hints(list(hints.values())),
        "learned_pairs": kept_pairs,
    }

    print(f"memory_file={memory_path}")
    print(f"kept={len(kept_pairs)}")
    print(f"removed={len(removed_pairs)}")
    if removed_pairs:
        print("removed_pairs:")
        for item in removed_pairs:
            print(f"- {item.get('from')} -> {item.get('to')}")

    if not args.dry_run:
        memory_path.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
