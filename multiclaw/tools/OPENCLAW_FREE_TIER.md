# OpenClaw free tier — limiting overtokening

When using this repo with **OpenClaw** on the **free tier**, keep usage within limits to avoid overtokening (excessive token consumption or rate limits).

## Practices

1. **Batch work** — Use one session for a coherent set of edits (e.g. one feature or one doc) instead of many tiny back-and-forths.
2. **Summarize in-repo** — Ask the agent to write a short reasoning trace or summary into a file (e.g. `openclaw01/session-*.md`) so you can resume later without re-explaining.
3. **Smaller context** — Open only the files or folders relevant to the task; avoid loading the whole workspace when not needed.
4. **Clear prompts** — One clear request per turn reduces follow-up rounds and token use.
5. **Offload to CI** — Use GitHub Actions (e.g. in terraform01, snorkel01, LangChain01) for validate/test so OpenClaw is not used for every run.

## Token awareness

- Free tiers usually cap daily or monthly tokens or requests.
- If you hit limits, pause and continue next day or switch to local tools (Neovim, CLI) for edits and use OpenClaw for planning or summaries only.

## Repo layout

This repo (openclaw01) holds **agentic research docs** (PDF-ready). Use OpenClaw here for refining the framework doc or generating session traces; keep heavy code work in the repo that owns the code (e.g. terraform01, LangChain01) so context stays small.
