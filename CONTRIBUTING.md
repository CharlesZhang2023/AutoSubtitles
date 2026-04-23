# Contributing

Thanks for helping improve AutoSubtitle.

## Development Setup

```bash
python3 -m pip install -r requirements.txt
```

For GPU transcription, make sure your NVIDIA driver, CUDA runtime, cuDNN, and `ctranslate2` versions are compatible. See `README.md` for CUDA notes.

## Local Checks

```bash
python3 -m py_compile autosubtitle/transcribe_faster.py autosubtitle/refine_subtitles.py
bash -n scripts/workflow.sh
bash -n scripts/workflow_fastwhisper_5090.sh
bash -n scripts/process_input_output.sh
```

## Project Conventions

- Keep generated media files out of git.
- Put reusable Python entrypoints under `autosubtitle/`.
- Put shell automation under `scripts/`.
- Put course-specific terminology under `config/`.
- Put reference prompts and workflow notes under `docs/`.
- Use `scripts/clean_term_memory.py` to clean noisy local ATR memory before promoting terms.
