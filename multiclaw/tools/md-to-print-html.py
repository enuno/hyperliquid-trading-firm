#!/usr/bin/env python3
"""
Generate a single HTML file from the agentic-reasoning-framework.md for
printing to PDF: small margins, dense text, page numbers via @page.
Usage: python3 md-to-print-html.py [input.md] [output.html]
Opens in browser: no. User opens output.html then File → Print → Save as PDF.
"""
import re
import sys
from pathlib import Path

INPUT = Path(__file__).parent / "agentic-reasoning-framework.md"
OUTPUT = Path(__file__).parent / "agentic-reasoning-framework.html"
CSS = Path(__file__).parent / "print.css"


def strip_yaml_frontmatter(text: str) -> str:
    if not text.strip().startswith("---"):
        return text
    rest = text.split("---", 2)
    if len(rest) < 3:
        return text
    return rest[2].lstrip("\n")


def md_to_html(md: str) -> str:
    """Minimal markdown to HTML (no external deps). Handles headers, lists, code, tables, bold/italic."""
    md = strip_yaml_frontmatter(md)
    lines = md.split("\n")
    out = []
    in_block = None
    block_buf = []
    in_table = False
    table_rows = []
    i = 0

    def flush_block():
        nonlocal block_buf, in_block
        if not block_buf:
            return
        if in_block == "pre":
            out.append("<pre><code>" + _escape("".join(block_buf)) + "</code></pre>")
        block_buf = []
        in_block = None

    def _escape(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def inline(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
        s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
        return s

    while i < len(lines):
        line = lines[i]
        raw = line

        if line.strip().startswith("```"):
            flush_block()
            if in_block == "pre":
                in_block = None
            else:
                in_block = "pre"
                block_buf = []
            i += 1
            continue

        if in_block == "pre":
            block_buf.append(line + "\n")
            i += 1
            continue

        # Table
        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            row = [c.strip() for c in line.split("|")[1:-1]]
            table_rows.append(row)
            i += 1
            continue
        else:
            if in_table and table_rows:
                out.append("<table>")
                sep = 1 if len(table_rows) > 1 and all(
                    re.match(r"^:?-+:?$", c.strip()) for c in table_rows[1]
                ) else 0
                for r_idx, row in enumerate(table_rows):
                    if sep and r_idx == 1:
                        continue
                    tag = "th" if r_idx == 0 else "td"
                    out.append("<tr>" + "".join(f"<{tag}>{inline(_escape(c))}</{tag}>" for c in row) + "</tr>")
                out.append("</table>")
                table_rows = []
            in_table = False

        # Headers
        if line.startswith("# "):
            flush_block()
            out.append("<h1>" + inline(_escape(line[2:].strip())) + "</h1>")
            i += 1
            continue
        if line.startswith("## "):
            flush_block()
            out.append("<h2>" + inline(_escape(line[3:].strip())) + "</h2>")
            i += 1
            continue
        if line.startswith("### "):
            flush_block()
            out.append("<h3>" + inline(_escape(line[4:].strip())) + "</h3>")
            i += 1
            continue
        if line.startswith("#### "):
            flush_block()
            out.append("<h4>" + inline(_escape(line[5:].strip())) + "</h4>")
            i += 1
            continue

        # LaTeX newpage -> page break div
        if line.strip() == "\\newpage":
            flush_block()
            out.append('<div class="page-break"></div>')
            i += 1
            continue

        # Horizontal rule
        if line.strip() in ("---", "***", "___"):
            flush_block()
            out.append("<hr/>")
            i += 1
            continue

        # Unordered list
        if line.strip().startswith("- ") or line.strip().startswith("* "):
            flush_block()
            out.append("<ul>")
            while i < len(lines) and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                out.append("<li>" + inline(_escape(lines[i].strip()[2:])) + "</li>")
                i += 1
            out.append("</ul>")
            continue

        # Ordered list (simple)
        if re.match(r"^\d+\.\s", line):
            flush_block()
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                out.append("<li>" + inline(_escape(re.sub(r"^\d+\.\s", "", lines[i]))) + "</li>")
                i += 1
            out.append("</ol>")
            continue

        # Paragraph
        if line.strip():
            flush_block()
            out.append("<p>" + inline(_escape(line.strip())) + "</p>")
        else:
            flush_block()
            out.append("<p></p>")

        i += 1

    flush_block()
    if table_rows:
        out.append("<table>")
        sep = 1 if len(table_rows) > 1 and all(
            re.match(r"^:?-+:?$", c.strip()) for c in table_rows[1]
        ) else 0
        for r_idx, row in enumerate(table_rows):
            if sep and r_idx == 1:
                continue
            tag = "th" if r_idx == 0 else "td"
            out.append("<tr>" + "".join(f"<{tag}>{inline(_escape(c))}</{tag}>" for c in row) + "</tr>")
        out.append("</table>")

    return "\n".join(out)


def main():
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else INPUT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT
    css_path = CSS
    md = input_path.read_text(encoding="utf-8")
    html_body = md_to_html(md)
    css_content = css_path.read_text(encoding="utf-8") if css_path.exists() else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Agentic Reasoning Framework — Research</title>
<style>
{css_content}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path}. Open in browser, then File → Print → Save as PDF.")


if __name__ == "__main__":
    main()
