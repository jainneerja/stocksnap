#!/usr/bin/env bash
# Put every dress photo in dresses/ onto the AI picture, then add the necklace.
#   bash run_all.sh                      (uses ai_red.png + swap_ai_d2.json)
#   REF=ai_red.png SETUP=swap_ai_d2.json bash run_all.sh
set -euo pipefail
cd "$(dirname "$0")"
REF="${REF:-ai_red.png}"; SETUP="${SETUP:-swap_ai_d2.json}"; NECK="${NECK:-necklace_ai.json}"
PY="${PY:-../../backend/.venv/Scripts/python.exe}"; [ -x "$PY" ] || PY=python
mkdir -p out
shopt -s nullglob
files=(dresses/*.jpg dresses/*.jpeg dresses/*.png)
[ ${#files[@]} -gt 0 ] || { echo "Put dress photos in the dresses/ folder first"; exit 1; }
for f in "${files[@]}"; do
  n=$(basename "${f%.*}")
  "$PY" swap.py "$REF" "$f" "out/$n.tmp.png" "$SETUP"
  "$PY" add_necklace.py "out/$n.tmp.png" "$REF" "out/$n.png" "$NECK"
  rm -f "out/$n.tmp.png" "out/$n.tmp_mask.png" "out/${n}_mask.png"
  echo "done: out/$n.png"
done
