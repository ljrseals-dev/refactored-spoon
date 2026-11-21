#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="offline-doc-mcp-v0.1.0.zip"
rm -f "$OUT"
zip -r "$OUT" . \
  -x "data/*" \
  -x "**/.git/*" \
  -x "**/__pycache__/*" \
  -x "**/*.pyc" \
  -x ".venv/*" \
  -x "*.egg-info/*"
echo "Created $OUT"
ls -lh "$OUT"
