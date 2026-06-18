# Philosophy

**deep** was built around a few ideas that shaped every decision in the codebase.

---

## You talk, the agent works

Programming is communication. You know *what* you want — the hard part is translating that
intent into working code across a dozen files. `deep` is an agent: you describe the task in
plain language and it operates on your project with tools — reading, searching, writing,
running, verifying — and iterates until it's done. Not a one-shot generator: a loop that
observes its own results and keeps going.

---

## The strong model writes the code

The quality of generated code is capped by whichever model actually writes the bytes. So the
model that reasons about the task is the same one that writes every line that matters — we
don't hand the writing to a cheaper, weaker model to save tokens. DeepSeek is already cheap;
trading quality for a few tokens is a bad deal. The fast model earns its place doing low-risk,
high-volume work: reading and summarizing code, compacting context, mechanical boilerplate.

---

## Verify, don't assume

Code that "looks done" isn't done. After touching code, `deep` runs the project's tests, reads
the failures, and fixes them — iterating until green. The agent is pushed to verify its own
work, and the harness runs the tests automatically as a safety net so nothing closes red.

---

## Be surgical

Edits change only the lines that need to change. `deep` never rewrites a whole file for a
small change, never reformats unrelated code, and shows you the real diff of everything it
touches. It reads a file before editing it, so it doesn't invent content.

---

## Local first, no lock-in

Your code lives on your machine. Your API key stays on your machine. `deep` is a CLI tool, not
a cloud service — no account, no telemetry, no subscription. The only external dependency is
the DeepSeek API (or any compatible model you configure). You own the output.

---

## Permissions you control

The agent asks before it writes to disk or runs a command. Modes (`ask` / `auto` / `plan` /
`yolo`) let you decide how much rope it gets — from read-only planning to fully autonomous.

---

## Open source because it should be

Tools that help people build software belong to everyone. `deep` is MIT licensed. Fork it,
modify it, make it yours.

---

Built by [Cynchro Labs](https://www.cynchrolabs.com.ar)
