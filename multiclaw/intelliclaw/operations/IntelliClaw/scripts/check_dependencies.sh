#!/usr/bin/env bash
echo "=== IntelliClaw Dependency Check ==="
for cmd in node npm jq psql agent-browser; do
  command -v "$cmd" &>/dev/null && echo "  ✓ $cmd" || echo "  ✗ $cmd: NOT FOUND"
done
