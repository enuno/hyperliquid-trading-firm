#!/usr/bin/env bash
# Build dense technical PDF with small margins and page numbers.
# Requires: pandoc, pdflatex (or lualatex/xelatex)
set -e
cd "$(dirname "$0")"

INPUT="${1:-agentic-reasoning-framework.md}"
OUTPUT="${2:-${INPUT%.md}.pdf}"

if ! command -v pandoc &>/dev/null; then
  echo "Error: pandoc not found. Install pandoc to build PDFs."
  exit 1
fi

echo "Building: $INPUT -> $OUTPUT"
pandoc "$INPUT" -o "$OUTPUT" \
  --pdf-engine=pdflatex \
  --include-in-header=pdf-header.tex \
  -V documentclass=article \
  -V papersize=letter \
  -V fontsize=10pt \
  -V numbersections=true \
  --number-sections \
  -V colorlinks=true

echo "Done: $OUTPUT"
