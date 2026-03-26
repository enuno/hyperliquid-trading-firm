# Agentic Thought Process: Research Documentation

**Purpose:** Research on the process itself—how an agentic AI (within Cursor’s framework) reasons, plans, and acts. Suitable for print/PDF.

**Version:** 1.0  
**Date:** 2025-02-05

---

## 1. Framework context

- **Environment:** Cursor IDE with an agent-style assistant (“Auto”, agent router).
- **Capabilities:** The agent can use tools (codebase search, file read/write, terminal, browser, MCP, etc.), plan multi-step work, and iterate from results.
- **Visibility:** User sees messages and tool calls; internal reasoning (e.g. `<think>` blocks) is not shown in the UI unless the agent writes it out.

This document describes that thought process from the agent’s perspective so it can be studied and printed.

---

## 2. High-level thought process

### 2.1 Parse and ground the request

1. **Intent:** What is the user asking for (deliverable, explanation, fix, exploration)?
2. **Constraints:** Explicit (e.g. “no new dependencies”) and implicit (workspace layout, existing patterns).
3. **Output form:** Code, docs, commands, a mix?

### 2.2 Plan (implicit or explicit)

- **Decomposition:** Break the request into steps (e.g. “find X → change Y → run Z”).
- **Dependencies:** Order steps so each has what it needs (e.g. read before edit).
- **Tools:** Which tools are needed (search, read, edit, run, MCP)?
- **Parallelism:** Which steps can be done in one “batch” of tool calls (e.g. multiple reads) vs must be sequential.

### 2.3 Act and observe

- **Tool use:** Execute one or more tools with concrete arguments.
- **Interpret results:** Success/failure, content of files, command output, search hits.
- **Update plan:** Continue, backtrack, or branch (e.g. if a file is missing, create it; if a command fails, fix and retry).

### 2.4 Iterate until done

- **Completion:** All sub-goals addressed and user request satisfied.
- **Quality:** Lint/run checks if relevant; fix issues found.
- **Response:** Summarize what was done and any caveats or next steps.

---

## 3. Decision points (what the agent “thinks” about)

| Decision | Options considered | Typical choice |
|----------|--------------------|----------------|
| **Search vs read** | Semantic search (by meaning) vs grep (exact text) vs direct read | Search when exploring; grep when symbol known; read when path known. |
| **Edit vs new file** | Change existing vs create new | Prefer edit when file exists and change is local; new file when adding a module/doc. |
| **Batch tool calls** | One call at a time vs several in parallel | Parallel when calls are independent (e.g. reading 3 files). |
| **Scope of change** | Minimal fix vs refactor | Minimal unless user asks for refactor or the fix clearly requires it. |
| **Explain vs do** | Describe plan first vs do then summarize | Do first for small tasks; short plan then do for larger ones. |
| **Retry vs report** | Retry with different params vs tell user and stop | Retry once or twice (e.g. path/typo); then report and suggest. |

---

## 4. Information flow (within the framework)

```
User message
    → System prompt + rules + skills (if any)
    → Agent interprets request
    → Optional: todo list (for multi-step)
    → Tool calls (parallel where possible)
    → Tool results
    → Agent updates state and plan
    → More tool calls or final reply
    → User sees: tool calls + final reply (reasoning often hidden)
```

**For research:** The “reasoning” is in the internal state between user message and tool calls/reply. Capturing it requires either (a) the agent explicitly writing a “reasoning trace” into a file or message, or (b) using a session template (see below) filled after the fact or by the agent when asked.

---

## 5. How to capture thought process for print/PDF

### Option A: Ask the agent at end of session

After a task, you can say:

- “Summarize the thought process you used: what you decided first, what you searched/read, what you changed and why, and what you’d do next.”
- “Write a short reasoning trace for this session into `openclaw01/session-YYYY-MM-DD-HHMM.md`.”

Then combine that with this document for a full “process + instance” report.

### Option B: Use the session template

Use the file `session-reasoning-template.md` (in this folder). For each session:

1. Copy the template.
2. Fill “User request” and “Date”.
3. Either (i) ask the agent to fill “Agent reasoning trace” and “Tool sequence”, or (ii) fill them yourself from the chat and tool history.
4. Export to PDF (see “Generating PDFs” below).

### Option C: Cursor rules for automatic trace

You can add a rule (e.g. in `.cursor/rules` or a project rule) so that for “research” sessions the agent is instructed to append a short reasoning trace to a designated file or to the end of its reply. The create-rule skill can help draft that rule.

---

## 6. Generating PDFs

- **From Cursor/VS Code:** Open the `.md` file → Print (e.g. Ctrl+P / Cmd+P) → “Save as PDF” or “Microsoft Print to PDF”.
- **From command line (Pandoc):**  
  `pandoc AGENTIC-THOUGHT-PROCESS.md -o AGENTIC-THOUGHT-PROCESS.pdf`
- **From browser:** Use a Markdown-to-HTML viewer, then Print → Save as PDF.

---

## 7. Limitations (for accurate research)

- Internal reasoning is not automatically logged; only what the agent outputs or what you record is available.
- Tool results are truncated in long outputs; the agent sees more than might be visible in the chat.
- “Thought process” here is a reconstruction and description of the intended design, not a literal dump of internal state.

---

*Document generated for research on agentic process within the Cursor agent framework. To extend or correct, edit this file or add a session-specific trace using the session template.*
