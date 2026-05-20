# Philosophy

**deep** was built around a few ideas that shaped every decision in the codebase.

---

## You describe, the machine builds

Programming is communication. Most of the time you know *what* you want to build — the hard part is translating that intent into working code across a dozen files. `deep` shortens that gap: describe what you need in plain language and get a functional project back, ready to run.

---

## Local first, no lock-in

Your code lives on your machine. Your API key stays on your machine. `deep` is a CLI tool, not a cloud service — there's no account, no telemetry, no subscription. You own the output.

The only external dependency is the DeepSeek API (or any compatible model you configure). If you want to run everything locally with a local LLM, that's a valid path too.

---

## The system should learn

A single build is useful. A system that gets better with each build is powerful.

`deep` stores structured experiences from every run — what worked, what failed, why. It uses that memory to inform the planning phase of future builds. The more you use it, the more context it has about what approaches work for your kind of tasks.

---

## Honest evaluation

Generated code isn't always good. `deep` evaluates its own output after every build using a second model pass, reports issues explicitly, and offers to fix them. We'd rather show you a 6/10 with a list of real problems than pretend everything is fine.

---

## Simple tools, composable

`build`, `ask`, `fix`, `update`, `show` — each command does one thing well. They compose: `build` a project, `ask` questions about it, `update` it incrementally, `fix` what broke. No magic, no hidden state (other than what's explicitly stored in `.deep/`).

---

## Open source because it should be

Tools that help people build software belong to everyone. `deep` is MIT licensed. Fork it, modify it, make it yours.

---

Built by [Cynchro Labs](https://www.cynchrolabs.com.ar)
