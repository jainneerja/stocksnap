#!/usr/bin/env bash
# Render every dress photo in dresses/ onto the idol photo.
#   bash run_all.sh                 (idol photo: idol_bare.jpg)
#   BLENDER="/c/path/to/blender.exe" bash run_all.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IDOL="${IDOL:-idol_bare.jpg}"
if [ -z "${BLENDER:-}" ]; then
  BLENDER=$(ls -d "/c/Program Files/Blender Foundation"/Blender*/blender.exe 2>/dev/null | sort -V | tail -1 || true)
  [ -n "$BLENDER" ] || BLENDER=$(command -v blender || true)
fi
[ -n "$BLENDER" ] || { echo "Blender not found. Install it from blender.org or set BLENDER=/path/to/blender.exe"; exit 1; }
mkdir -p "$HERE/out"
shopt -s nullglob
files=("$HERE"/dresses/*.jpg "$HERE"/dresses/*.jpeg "$HERE"/dresses/*.png)
[ ${#files[@]} -gt 0 ] || { echo "Put dress photos in the dresses/ folder first"; exit 1; }
n=0
for f in "${files[@]}"; do
  n=$((n + 1)); name=$(basename "${f%.*}")
  echo "[$n/${#files[@]}] $name"
  "$BLENDER" -b --factory-startup -P "$HERE/dress3d.py" -- "$f" "$HERE/$IDOL" "$HERE/out/$name.png" 2>&1 \
    | grep -E "dress photo|saved|Error|Traceback" || true
done
echo "Done: $HERE/out"
