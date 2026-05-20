# Contributing

Thanks for your interest in contributing to **deep**. Here's everything you need to know.

---

## Getting started

```bash
git clone https://github.com/cynchro/deepseekCLI.git
cd deepseekCLI
pip install -e ".[https]"
export DEEPSEEK_API_KEY=your_key_here
python deep.py doctor   # verify everything works
```

---

## What we're looking for

- **Bug fixes** — if you found it and can reproduce it, a PR is welcome
- **Model compatibility** — fixes or improvements for other DeepSeek models or compatible APIs
- **Platform support** — Windows, macOS, Linux edge cases
- **New skills** — add useful skill files to `examples/skills/`
- **Documentation** — clearer explanations, better examples

For larger features, open an issue first so we can discuss the approach before you invest time writing code.

---

## Code style

- Python 3.9+ compatible
- No external dependencies beyond what's in `requirements.txt` and `pyproject.toml` — keep the install footprint small
- The core pipeline (`core/`) should stay decoupled from the CLI layer (`cli/`) — don't import from `cli/` inside `core/`
- No comments that describe *what* the code does — only comment *why* when it's non-obvious
- Keep functions small and focused

---

## Testing a change

There are no automated tests yet (contributions welcome). To validate manually:

```bash
# Basic flow
python deep.py doctor
python deep.py build "hello world in Python"

# With reasoner model
python deep.py build "REST API in FastAPI" --model deepseek-reasoner --debug

# Debug log should show clean JSON parse in PHASE_4
grep '\[EVAL\]' debug.log
```

If you're changing the pipeline, run a few builds with `--debug` and check:
- `HEURISTIC: structural_ok=True` (or expected False with issues)
- `EVAL: evaluation_parsed` (no `json_parse_failed`)
- Files on disk match what `PHASE_3` logged

---

## Submitting a PR

1. Fork the repo and create a branch from `main`
2. Make your changes with a clear commit message
3. Open a PR describing: what changed, why, and how you tested it
4. Keep PRs focused — one thing per PR

---

## What we won't merge

- Breaking changes to the CLI interface without discussion
- Dependencies that require C compilation on install (keep it `pip install`-able on a clean system)
- Features that phone home or collect usage data
- Code that touches `.deep/` directories in user projects without explicit user intent

---

## Questions?

Open an issue or reach out directly: **alexissaucedo@gmail.com**
