# Differences from the previous version

> *Versión en español: [diferencias.md](diferencias.md).*

> A summary of what changed between the old version (a **single-shot** generator)
> and the current one (an **agent** with tools). For per-release detail see
> [CHANGELOG.md](CHANGELOG.md).

## In one sentence

**Before:** you typed a command (`build`/`fix`/`update`) and a model generated
everything in a single pass. **Now:** you talk to it in natural language and an
**agent** solves the task by operating on the project with tools —it reads,
searches, writes, runs and verifies— iterating until done, just like Claude Code.

## What changed

| Topic | Before (single-shot) | Now (agent) |
|------|---------------------|----------------|
| **Usage mode** | Fixed commands that generate files in one go | Conversational natural-language REPL + `deep agent` |
| **Who writes the code** | A generic model, in one pass | The strong model (PRO) writes directly; FLASH only reads/summarizes and handles cheap bulk work |
| **Editing** | Regenerated whole files | **Surgical** editing (changes only what's needed) with visible diffs |
| **Verification** | A single evaluation at the end | Runs tests/lint and **iterates until everything is green** (auto-verify) |
| **Models** | A single one (`deepseek-chat`) | PRO/FLASH split (`deepseek-v4`), with per-model cost |
| **Permissions** | None | `ask` / `auto` / `plan` / `yolo` modes before touching disk or shell |
| **Project context** | — | `DEEP.md` (CLAUDE.md-style) + `.deeprules`, with `/init` |

## New capabilities

- **Code search (`search_code`)** by relevance (local index), much better than
  grep for getting oriented in large projects. Optional: **semantic** search with embeddings.
- **Parallel sub-agents**: delegates independent parts and builds them at the same time.
- **Persistent task list** + **auto-resume**: a large build survives interruptions,
  restarts and the step limit (it keeps going on its own).
- **Faithful context compaction**: long sessions without losing paths, decisions or results.
- **Language control**: you describe in any language and the **code comes out in English**
  by default (`DEEP_CODE_LANG`), with comments in another language if you want (`DEEP_COMMENT_LANG`).
  The console interface itself switches between Spanish and English via `config set-lang`.
- **Agentic skills**, **PWA with a live agent** (streaming) and token/cost telemetry.

## Compatibility

The old commands (`build`, `update`, `fix`, `claudejob`, `serve`) **still work**
for scripting and the PWA; they were not removed. The agent replaces them for daily use.

## Upgrade

```bash
pip install --upgrade deepseek-builder   # PyPI
# or
deep upgrade                              # from GitHub
```
