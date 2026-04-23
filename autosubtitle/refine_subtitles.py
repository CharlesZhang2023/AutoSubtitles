#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import json
import os
import re
import shlex
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOSSARY_FILE = PROJECT_ROOT / "config" / "course_terms.json"
DEFAULT_ENV_FILE = PROJECT_ROOT / "config" / "packy.env"

SYSTEM_PROMPT = """你是一位专业的学术助教，擅长将口语化的课堂转录稿转化为精准、易读的课程字幕。

你必须遵守以下规则：
1. 所有课程代码统一为 COMP1023 或 COMP2211，保持全大写且无空格。
2. 句首大写；专有名词必须规范，如 Python、VS Code、NumPy、Pandas、Matplotlib、Zoom、Desmond Tsoi、HKUST。
3. 删除语气词与无意义重复，如 uh、um、ah、hey、okay、right、you know、sort of、sorry sorry、no no no。
4. 纠正常见术语识别错误，如 Soon/Sun -> Zoom，Lumpie/Numpi -> NumPy，Math plot lab/Math for lip -> Matplotlib，Polandrum -> Palindrome，Pseudo cold -> Pseudocode，Bite -> Byte（仅在存储单位语境）。
5. 将口语碎句整理成更自然的书面句子，但不要改变原意。
6. 不要改动条目顺序，不要合并或拆分条目。
7. 仅返回 JSON，不能返回 Markdown。
"""


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        try:
            value = shlex.split(raw_value, comments=False, posix=True)[0]
        except IndexError:
            value = ""

        os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refine generated SRT subtitles with an OpenAI model."
    )
    parser.add_argument("input_srt", help="Input SRT file")
    parser.add_argument(
        "--output_srt",
        default=None,
        help="Path for refined SRT output, defaults to <stem>.atr.srt",
    )
    parser.add_argument(
        "--output_txt",
        default=None,
        help="Path for refined plain text output, defaults to <stem>.atr.txt",
    )
    parser.add_argument(
        "--report_file",
        default=None,
        help="Path for glossary report, defaults to <stem>.atr_report.md",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AUTO_SUBTITLE_ATR_MODEL", "gpt-5.4-mini"),
        help="OpenAI model for subtitle refinement",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "packy"],
        default=os.environ.get("AUTO_SUBTITLE_ATR_PROVIDER", "openai"),
        help="LLM provider for ATR refinement",
    )
    parser.add_argument(
        "--packy_base_url",
        default=os.environ.get("PACKY_API_BASE", "https://www.packyapi.com/v1"),
        help="PackyAPI OpenAI-compatible base URL",
    )
    parser.add_argument(
        "--max_tokens",
        type=int,
        default=int(os.environ.get("AUTO_SUBTITLE_ATR_MAX_TOKENS", "8192")),
        help="Maximum visible output tokens for chat-completion providers",
    )
    parser.add_argument(
        "--chunk_size",
        type=int,
        default=int(os.environ.get("AUTO_SUBTITLE_ATR_CHUNK_SIZE", "120")),
        help="Subtitle entries sent per request",
    )
    parser.add_argument(
        "--glossary_file",
        default=os.environ.get("AUTO_SUBTITLE_GLOSSARY_FILE", str(DEFAULT_GLOSSARY_FILE)),
        help="JSON glossary config for protected terms and replacement hints",
    )
    parser.add_argument(
        "--memory_file",
        default=os.environ.get("AUTO_SUBTITLE_MEMORY_FILE"),
        help="JSON file for auto-learned term memory, defaults beside glossary file",
    )
    return parser.parse_args()


def parse_srt(path: Path) -> list[dict[str, object]]:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return []

    blocks = []
    for raw_block in content.split("\n\n"):
        lines = [line.rstrip() for line in raw_block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue

        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        blocks.append(
            {
                "index": index,
                "timestamp": lines[1].strip(),
                "text": " ".join(line.strip() for line in lines[2:]).strip(),
            }
        )
    return blocks


def chunk_entries(entries: list[dict[str, object]], chunk_size: int) -> list[list[dict[str, object]]]:
    return [entries[index : index + chunk_size] for index in range(0, len(entries), chunk_size)]


def build_schema(expected_count: int) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entries": {
                "type": "array",
                "minItems": expected_count,
                "maxItems": expected_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                    "required": ["index", "text"],
                },
            },
            "glossary": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "from": {"type": "string"},
                        "to": {"type": "string"},
                    },
                    "required": ["from", "to"],
                },
            },
        },
        "required": ["entries", "glossary"],
    }


def resolve_json_path(path_value: str | None, fallback_name: str | None = None) -> Path:
    if path_value:
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()

    if fallback_name is None:
        raise ValueError("A path or fallback_name is required.")

    return (Path.cwd() / fallback_name).resolve()


def dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_term(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def merge_replacement_hints(*hint_groups: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}

    for hints in hint_groups:
        for item in hints:
            canonical = normalize_term(str(item.get("canonical", "")))
            if not canonical:
                continue

            key = canonical.casefold()
            entry = merged.setdefault(key, {"canonical": canonical, "variants": []})
            variants = entry["variants"]

            for raw_variant in item.get("variants", []):
                variant = normalize_term(str(raw_variant))
                if not variant:
                    continue
                if variant.casefold() == canonical.casefold():
                    continue
                if variant.casefold() in {value.casefold() for value in variants}:
                    continue
                variants.append(variant)

    return list(merged.values())


def load_json_dict(path: Path, default: dict[str, object]) -> dict[str, object]:
    if not path.is_file():
        return json.loads(json.dumps(default))
    return json.loads(path.read_text(encoding="utf-8"))


def default_memory_path(glossary_path: Path) -> Path:
    if glossary_path.suffix:
        return glossary_path.with_name(f"{glossary_path.stem}.memory.json")
    return glossary_path.with_name(f"{glossary_path.name}.memory.json")


def load_glossary(glossary_path_value: str, memory_path_value: str | None) -> dict[str, object]:
    glossary_path = resolve_json_path(glossary_path_value, str(DEFAULT_GLOSSARY_FILE))
    memory_path = resolve_json_path(memory_path_value, None) if memory_path_value else default_memory_path(glossary_path)

    base_default = {
        "protected_terms": [],
        "replacement_hints": [],
        "hard_replacements": [],
    }
    memory_default = {
        "protected_terms": [],
        "replacement_hints": [],
        "hard_replacements": [],
        "learned_pairs": [],
        "metadata": {"updated_at": None},
    }

    base_data = load_json_dict(glossary_path, base_default)
    memory_data = load_json_dict(memory_path, memory_default)

    protected_terms = dedupe_strings(
        list(base_data.get("protected_terms", []))
        + list(memory_data.get("protected_terms", []))
    )
    replacement_hints = merge_replacement_hints(
        list(base_data.get("replacement_hints", [])),
        list(memory_data.get("replacement_hints", [])),
    )
    hard_replacements = list(base_data.get("hard_replacements", [])) + list(
        memory_data.get("hard_replacements", [])
    )

    return {
        "path": str(glossary_path),
        "memory_path": str(memory_path),
        "protected_terms": protected_terms,
        "replacement_hints": replacement_hints,
        "hard_replacements": hard_replacements,
        "base_data": base_data,
        "memory_data": memory_data,
    }


def glossary_prompt(glossary: dict[str, object]) -> str:
    protected_terms = glossary["protected_terms"]
    replacement_hints = glossary["replacement_hints"]

    if not protected_terms and not replacement_hints:
        return "当前没有额外术语词典。请仅按系统规则校对。"

    payload = {
        "protected_terms": protected_terms,
        "replacement_hints": replacement_hints,
    }
    return (
        "请严格参考以下课程术语词典。"
        "优先使用 protected_terms 中的标准写法；"
        "若识别结果与 replacement_hints 中的 variants 接近，请优先纠正为 canonical。\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def build_user_prompt(entries: list[dict[str, object]], glossary: dict[str, object]) -> str:
    input_payload = json.dumps(entries, ensure_ascii=False)
    expected_count = len(entries)
    return (
        "请校对以下 SRT 文本条目。"
        "不要修改 index，不要返回 timestamp。"
        f"必须返回恰好 {expected_count} 个 entries，顺序必须和输入一致。"
        "请为每个条目返回 refined text，并在 glossary 中列出关键术语修正。"
        "输出必须是严格 JSON，不能包含 Markdown、代码块或解释文字。"
        "JSON 格式必须是："
        "{\"entries\":[{\"index\":1,\"text\":\"...\"}],\"glossary\":[{\"from\":\"...\",\"to\":\"...\"}]}。\n"
        f"{glossary_prompt(glossary)}\n"
        f"{input_payload}"
    )


def parse_json_response(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def call_openai(
    model: str, entries: list[dict[str, object]], glossary: dict[str, object]
) -> dict[str, object]:
    try:
        from openai import OpenAI
    except ImportError:
        print(
            "❌ 缺少依赖 openai。请先运行: python3 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("❌ 缺少环境变量 OPENAI_API_KEY，无法执行 ATR 校对。", file=sys.stderr)
        raise SystemExit(1)

    client = OpenAI()

    response = client.responses.create(
        model=model,
        reasoning={"effort": "low"},
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM_PROMPT}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_user_prompt(entries, glossary),
                    }
                ],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "subtitle_refinement",
                "schema": build_schema(len(entries)),
                "strict": True,
            }
        },
    )
    return json.loads(response.output_text)


def packy_ssl_context() -> ssl.SSLContext:
    verify = os.environ.get("PACKY_API_SSL_VERIFY", "1").lower()
    if verify in {"0", "false", "no", "off"}:
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def call_packy(
    model: str,
    entries: list[dict[str, object]],
    glossary: dict[str, object],
    base_url: str,
    max_tokens: int,
) -> dict[str, object]:
    api_key = os.environ.get("PACKY_API_KEY")
    if not api_key:
        print("❌ 缺少环境变量 PACKY_API_KEY，无法执行 PackyAPI ATR 校对。", file=sys.stderr)
        raise SystemExit(1)

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(entries, glossary)},
        ],
        "stream": True,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "curl/8.0.1",
        },
    )

    output_parts: list[str] = []
    try:
        with urllib.request.urlopen(
            request, context=packy_ssl_context(), timeout=180
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue

                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break

                chunk = json.loads(data)
                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    output_parts.append(content)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"❌ PackyAPI HTTP {exc.code}: {body[:1000]}", file=sys.stderr)
        raise SystemExit(1)
    except ssl.SSLError as exc:
        print(
            "❌ PackyAPI TLS 证书校验失败。若确认该网关可信，可临时设置 PACKY_API_SSL_VERIFY=0。",
            file=sys.stderr,
        )
        print(f"   {exc}", file=sys.stderr)
        raise SystemExit(1)

    output_text = "".join(output_parts).strip()
    if not output_text:
        print("❌ PackyAPI stream 未返回可见文本。", file=sys.stderr)
        raise SystemExit(1)

    return parse_json_response(output_text)


def call_refiner(
    provider: str,
    model: str,
    entries: list[dict[str, object]],
    glossary: dict[str, object],
    packy_base_url: str,
    max_tokens: int,
) -> dict[str, object]:
    if provider == "packy":
        return call_packy(model, entries, glossary, packy_base_url, max_tokens)
    return call_openai(model, entries, glossary)


def apply_hard_replacements(text: str, glossary: dict[str, object]) -> str:
    normalized = text
    for item in glossary["hard_replacements"]:
        pattern = item.get("pattern")
        replacement = item.get("replacement")
        if not pattern or replacement is None:
            continue
        normalized = re.sub(pattern, str(replacement), normalized, flags=re.IGNORECASE)
    return normalized


def should_learn_pair(before: str, after: str) -> bool:
    before = normalize_term(before)
    after = normalize_term(after)
    if not before or not after:
        return False
    if before.casefold() == after.casefold():
        return False
    if len(before) > 80 or len(after) > 80:
        return False
    if len(before.split()) > 5 or len(after.split()) > 5:
        return False
    if "\n" in before or "\n" in after:
        return False

    safe_pattern = r"^[A-Za-z0-9][A-Za-z0-9 .#+:/&'_-]*$"
    return bool(re.match(safe_pattern, before)) and bool(re.match(safe_pattern, after))


def known_variants(glossary: dict[str, object], canonical: str) -> set[str]:
    variants = {canonical.casefold()}
    for item in glossary["replacement_hints"]:
        item_canonical = normalize_term(str(item.get("canonical", "")))
        if item_canonical.casefold() != canonical.casefold():
            continue
        for raw_variant in item.get("variants", []):
            variant = normalize_term(str(raw_variant))
            if variant:
                variants.add(variant.casefold())
    return variants


def update_memory(
    glossary: dict[str, object], learned_pairs: list[dict[str, str]]
) -> dict[str, object]:
    memory_path = Path(str(glossary["memory_path"]))
    memory_data = json.loads(json.dumps(glossary["memory_data"]))
    existing_pairs: dict[tuple[str, str], dict[str, object]] = {}

    for item in memory_data.get("learned_pairs", []):
        before = normalize_term(str(item.get("from", "")))
        after = normalize_term(str(item.get("to", "")))
        if before and after:
            existing_pairs[(before.casefold(), after.casefold())] = item

    existing_hints = merge_replacement_hints(list(memory_data.get("replacement_hints", [])))
    hint_map = {
        normalize_term(str(item["canonical"])).casefold(): {
            "canonical": item["canonical"],
            "variants": list(item["variants"]),
        }
        for item in existing_hints
    }
    known_canonicals = {value.casefold() for value in memory_data.get("protected_terms", [])}

    learned_count = 0
    skipped_count = 0

    for item in learned_pairs:
        before = normalize_term(item["from"])
        after = normalize_term(item["to"])

        if not should_learn_pair(before, after):
            skipped_count += 1
            continue

        known = known_variants(glossary, after)
        if before.casefold() in known:
            continue

        canonical_key = after.casefold()
        hint_entry = hint_map.setdefault(
            canonical_key, {"canonical": after, "variants": []}
        )
        existing_variants = {value.casefold() for value in hint_entry["variants"]}
        if before.casefold() not in existing_variants:
            hint_entry["variants"].append(before)
            learned_count += 1

        if canonical_key not in known_canonicals:
            memory_data.setdefault("protected_terms", []).append(after)
            known_canonicals.add(canonical_key)

        pair_key = (before.casefold(), after.casefold())
        if pair_key in existing_pairs:
            pair_entry = existing_pairs[pair_key]
            pair_entry["count"] = int(pair_entry.get("count", 0)) + 1
            pair_entry["last_seen"] = datetime.now(timezone.utc).isoformat()
        else:
            pair_entry = {
                "from": before,
                "to": after,
                "count": 1,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
            memory_data.setdefault("learned_pairs", []).append(pair_entry)
            existing_pairs[pair_key] = pair_entry

    memory_data["protected_terms"] = dedupe_strings(
        list(memory_data.get("protected_terms", []))
    )
    memory_data["replacement_hints"] = list(hint_map.values())
    memory_data["metadata"] = {
        **dict(memory_data.get("metadata", {})),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        json.dumps(memory_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "path": str(memory_path),
        "learned_count": learned_count,
        "skipped_count": skipped_count,
        "pair_count": len(memory_data.get("learned_pairs", [])),
    }


def validate_chunk(
    original_entries: list[dict[str, object]],
    refined_payload: dict[str, object],
    glossary: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    refined_entries = refined_payload.get("entries", [])
    if len(refined_entries) != len(original_entries):
        raise ValueError("Refined entry count does not match original entry count.")

    merged_entries: list[dict[str, object]] = []
    for original, refined in zip(original_entries, refined_entries):
        if int(refined["index"]) != int(original["index"]):
            raise ValueError("Refined entry indices do not align with original SRT.")

        merged_entries.append(
            {
                "index": original["index"],
                "timestamp": original["timestamp"],
                "text": apply_hard_replacements(str(refined["text"]).strip(), glossary),
            }
        )

    glossary: list[dict[str, str]] = []
    for item in refined_payload.get("glossary", []):
        before = str(item["from"]).strip()
        after = str(item["to"]).strip()
        if before and after:
            glossary.append({"from": before, "to": after})

    return merged_entries, glossary


def write_srt(entries: list[dict[str, object]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(f"{entry['index']}\n")
            handle.write(f"{entry['timestamp']}\n")
            handle.write(f"{entry['text']}\n\n")


def write_txt(entries: list[dict[str, object]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            text = str(entry["text"]).strip()
            if text:
                handle.write(text)
                handle.write("\n")


def write_report(
    glossary: list[dict[str, str]], memory_update: dict[str, object], path: Path
) -> None:
    seen: set[tuple[str, str]] = set()
    unique_items = []
    for item in glossary:
        pair = (item["from"], item["to"])
        if pair not in seen:
            seen.add(pair)
            unique_items.append(item)

    with path.open("w", encoding="utf-8") as handle:
        handle.write("# ATR Glossary Report\n\n")
        if not unique_items:
            handle.write("- No notable glossary corrections recorded.\n")
        else:
            for item in unique_items:
                handle.write(f"- `{item['from']}` → `{item['to']}`\n")

        handle.write("\n## Memory Writeback\n\n")
        handle.write(f"- Memory file: `{memory_update['path']}`\n")
        handle.write(f"- New learned variants: `{memory_update['learned_count']}`\n")
        handle.write(f"- Skipped noisy pairs: `{memory_update['skipped_count']}`\n")
        handle.write(f"- Total learned pairs stored: `{memory_update['pair_count']}`\n")


def main() -> int:
    load_env_file(DEFAULT_ENV_FILE)
    args = parse_args()

    input_path = Path(args.input_srt).expanduser().resolve()
    if not input_path.is_file():
        print(f"❌ 找不到输入字幕文件: {input_path}", file=sys.stderr)
        return 1

    output_srt = (
        Path(args.output_srt).expanduser().resolve()
        if args.output_srt
        else input_path.with_name(f"{input_path.stem}.atr.srt")
    )
    output_txt = (
        Path(args.output_txt).expanduser().resolve()
        if args.output_txt
        else input_path.with_name(f"{input_path.stem}.atr.txt")
    )
    report_file = (
        Path(args.report_file).expanduser().resolve()
        if args.report_file
        else input_path.with_name(f"{input_path.stem}.atr_report.md")
    )

    entries = parse_srt(input_path)
    if not entries:
        print("❌ 输入 SRT 为空或无法解析。", file=sys.stderr)
        return 1

    glossary = load_glossary(args.glossary_file, args.memory_file)

    all_refined_entries: list[dict[str, object]] = []
    all_glossary: list[dict[str, str]] = []
    chunks = chunk_entries(entries, args.chunk_size)

    print("======================================")
    print(f"🔌 ATR provider: {args.provider}")
    print(f"📝 ATR model: {args.model}")
    print(f"📦 chunks: {len(chunks)} chunk_size={args.chunk_size}")
    print(f"📚 glossary_file={glossary['path'] or 'none'}")
    print(f"🧠 memory_file={glossary['memory_path']}")
    print("======================================")

    for index, chunk in enumerate(chunks, start=1):
        print(f"🔄 refining chunk {index}/{len(chunks)}")
        refined_payload = call_refiner(
            args.provider,
            args.model,
            chunk,
            glossary,
            args.packy_base_url,
            args.max_tokens,
        )
        refined_entries, chunk_glossary = validate_chunk(chunk, refined_payload, glossary)
        all_refined_entries.extend(refined_entries)
        all_glossary.extend(chunk_glossary)

    memory_update = update_memory(glossary, all_glossary)
    write_srt(all_refined_entries, output_srt)
    write_txt(all_refined_entries, output_txt)
    write_report(all_glossary, memory_update, report_file)

    print(f"✅ wrote_refined_srt={output_srt}")
    print(f"✅ wrote_refined_txt={output_txt}")
    print(f"✅ wrote_report={report_file}")
    print(f"✅ wrote_memory={memory_update['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
