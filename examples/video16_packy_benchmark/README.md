# Video16 Packy ATR Benchmark

This directory records `video16` Packy ATR benchmark outputs from the remote
`RTX 5090` instance.

Input:

- Source SRT: `output/video16.srt` on the remote run directory
- Provider: `packy`
- Model: `gpt-5.4-mini`
- Test date: `2026-04-23`

## Recommended Result

- Best current practical profile: `--chunk_size 10 --concurrency 8`
- Runtime: `28.357s`
- Chunks: `14`
- Output subtitle: `video16.c8k10.atr.srt`
- Output transcript: `video16.c8k10.atr.txt`
- Last subtitle range: `01:20:17,300 --> 01:20:21,580`

## Benchmarks

| Profile | Chunk Size | Concurrency | Chunks | Result | Runtime |
| --- | ---: | ---: | ---: | --- | ---: |
| `c4` | `20` | `4` | `7` | success | `52.101s` |
| `c8` | `20` | `8` | `7` | success in one run, failed in a repeat run due to malformed JSON | `25.169s` success run; `32.309s` failed run |
| `c8k10` | `10` | `8` | `14` | success | `28.357s` |

## Logs

- `atr-video16-c8.log`: successful `chunk_size=20, concurrency=8` run log
- `c4.log`: successful `chunk_size=20, concurrency=4` run log
- `c8.log`: repeated `chunk_size=20, concurrency=8` run that failed with a JSON parse error
- `c8k10.log`: successful `chunk_size=10, concurrency=8` run log

## Notes

- `chunk_size=20, concurrency=8` can be the fastest when Packy returns clean JSON, but it showed instability during repeat testing.
- `chunk_size=10, concurrency=8` produced more chunks and finished reliably in this run, so it is the current default ATR profile.
- The raw logs do not include API keys.
