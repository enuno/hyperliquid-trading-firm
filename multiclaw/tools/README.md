# Agentic Thought Process — Research

This folder holds material for **research on the agentic process**: how the Cursor agent reasons, plans, and uses tools. The main deliverable is a **dense, technical document** (textbook/arxiv style) suitable for multi-page PDFs with **small margins** and **page numbers**.

## Contents

| File | Purpose |
|------|--------|
| **agentic-reasoning-framework.md** | **Primary source:** Long-form technical document (abstract, 10 sections, appendices). Dense prose, small margins, numbered sections. Use this to generate PDFs. |
| **agentic-reasoning-framework.html** | Print-ready HTML generated from the .md (run `python3 md-to-print-html.py` to regenerate). Open in browser → Print → Save as PDF. |
| **AGENTIC-THOUGHT-PROCESS.md** | Shorter summary; framework, decision points, capture methods. |
| **session-reasoning-template.md** | Template to fill per session (user request, reasoning trace, tool sequence, outcome). |
| **print.css** | CSS for dense layout (small margins, serif, tight line-height). Inlined when generating HTML. |
| **pdf-header.tex** | LaTeX header for Pandoc: geometry (0.6in margins), pagestyle, spacing. |
| **build-pdf.sh** | Builds PDF via Pandoc + pdflatex (small margins, page numbers). |
| **md-to-print-html.py** | Converts the .md to a single HTML file with embedded print CSS (no Pandoc/LaTeX required). |
| **README.md** | This file. |

## Getting a PDF: dense layout, small margins, page numbers

### Option A — Pandoc + LaTeX (best quality, page numbers automatic)

Requires `pandoc` and a LaTeX install (e.g. `texlive`).

```bash
cd /home/dennis/projects/openclaw01
./build-pdf.sh
```

Output: `agentic-reasoning-framework.pdf` with ~0.6in margins and footer page numbers.

### Option B — HTML + browser print (no Pandoc/LaTeX)

1. Generate HTML (if you changed the .md):
   ```bash
   python3 md-to-print-html.py
   ```
2. Open `agentic-reasoning-framework.html` in a browser.
3. File → Print (or Ctrl+P).
4. Set **Margins** to “Minimum” or “None” for more text per page.
5. Enable **Headers and footers** (or “Background graphics”) so the browser adds **page numbers**.
6. Save as PDF.

### Option C — Print from IDE

Open `agentic-reasoning-framework.md` in Cursor/VS Code and use Print (Ctrl+P / Cmd+P) → Save as PDF. Margins and page numbers depend on the editor’s print styling; for consistent dense layout use Option A or B.

## Document style

- **Format:** Dense technical textbook / arxiv / O’Reilly–HashiCorp style.
- **Layout:** More words per page; small margins (0.5–0.6 in); page numbers (Pandoc footer or browser print).
- **Structure:** Abstract, numbered sections 1–10, references, appendices (decision heuristics, session trace template).

## Capturing the thought process from “inside” the framework

The agent does not automatically expose internal reasoning. To get printouts of the thought process:

1. **After a session:** Ask the agent to “summarize your thought process and key decisions for this task” or to “write a short reasoning trace to `openclaw01/session-YYYY-MM-DD.md`.”
2. **Use the template:** Copy `session-reasoning-template.md`, fill it (or have the agent fill the reasoning/tool parts), then print or export to PDF.
3. **Combine:** Print/PDF the main doc + one or more session traces for a full “process + instance” research pack.

See **Section 9** in `agentic-reasoning-framework.md` for capture methods and PDF generation details.

## OpenClaw free tier

When using OpenClaw (free tier) with this repo, see **OPENCLAW_FREE_TIER.md** for guidance on limiting overtokening and staying within token/rate limits.
