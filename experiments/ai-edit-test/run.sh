#!/usr/bin/env bash
# One-image test: put a Laddu Gopal dress on an idol with a local AI image-editing model.
# Runs on CPU (no NVIDIA card). Needs about 20 GB of free disk and ideally 24 GB+ RAM.
#
#   cd /c/Projects/ai-edit-test
#   bash run.sh dress.jpg            # your dress photo
#
# Options (put before "bash"):
#   QUANT=Q3_K_M   smaller/faster model if your PC has 16 GB RAM (default Q4_K_M)
#   BACKEND=vulkan try the Intel/AMD graphics chip instead of the CPU
#   SIZE=512       smaller output, much faster (default 768)
set -euo pipefail
PHOTO="${1:?Usage: bash run.sh <dress-photo.jpg>}"
[ -f "$PHOTO" ] || { echo "Can't find '$PHOTO'. Photos here: $(ls *.jp*g *.png 2>/dev/null | tr '\n' ' ')"; exit 1; }
QUANT="${QUANT:-Q4_K_M}"; BACKEND="${BACKEND:-cpu}"; SIZE="${SIZE:-768}"
HERE="$(cd "$(dirname "$0")" && pwd)"; M="$HERE/models"; mkdir -p "$M" "$HERE/bin" "$HERE/out"
PY="$(command -v python || command -v python3)"

hf_pick() {  # repo, regex -> first matching file name in a Hugging Face repo
  curl -fsSL "https://huggingface.co/api/models/$1" | "$PY" -c "import sys,json,re; fs=[s['rfilename'] for s in json.load(sys.stdin)['siblings'] if re.search(r'''$2''', s['rfilename'])]; print(sorted(fs, key=len)[0] if fs else '')"
}
get() {  # repo, file, dest
  [ -s "$3" ] && { echo "  have $(basename "$3")"; return; }
  echo "  downloading $(basename "$3") ..."; curl -fL --retry 3 -C - -o "$3.part" "https://huggingface.co/$1/resolve/main/$2" && mv "$3.part" "$3"
}

echo "1/3  stable-diffusion.cpp ($BACKEND)"
if [ ! -f "$HERE/bin/sd-cli.exe" ] && [ ! -f "$HERE/bin/sd.exe" ]; then
  URL=$(curl -fsSL https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest | "$PY" -c "import sys,json; a=[x['browser_download_url'] for x in json.load(sys.stdin)['assets'] if 'win' in x['name'] and '$BACKEND' in x['name'] and x['name'].endswith('.zip')]; print(a[0] if a else '')")
  [ -n "$URL" ] || { echo "No Windows $BACKEND build found in the latest release"; exit 1; }
  curl -fL -o "$HERE/bin/sd.zip" "$URL"
  (cd "$HERE/bin" && (unzip -oq sd.zip || powershell -NoProfile -Command "Expand-Archive -Force sd.zip ."))
fi
SD="$HERE/bin/sd-cli.exe"; [ -f "$SD" ] || SD="$HERE/bin/sd.exe"
[ -f "$SD" ] || { echo "stable-diffusion.cpp didn't unpack - paste this to Claude"; exit 1; }
echo "  ready: $(basename "$SD")"

echo "2/3  models (first time only, ~20 GB)"
EDIT=$(hf_pick unsloth/Qwen-Image-Edit-2511-GGUF "$QUANT\\.gguf$")
LLM=$(hf_pick mradermacher/Qwen2.5-VL-7B-Instruct-GGUF "Q4_K_M\\.gguf$")
PROJ=$(hf_pick mradermacher/Qwen2.5-VL-7B-Instruct-GGUF "mmproj.*(Q8_0|f16)\\.gguf$")
LORA=$(hf_pick lightx2v/Qwen-Image-Edit-2511-Lightning "4step.*\\.safetensors$" || true)
for v in EDIT LLM PROJ; do [ -n "${!v}" ] || { echo "Couldn't find the $v model file on Hugging Face - paste this message to Claude"; exit 1; }; done
echo "  using $EDIT, $LLM, $PROJ${LORA:+, $LORA}"
get unsloth/Qwen-Image-Edit-2511-GGUF "$EDIT" "$M/edit.gguf"
get mradermacher/Qwen2.5-VL-7B-Instruct-GGUF "$LLM" "$M/llm.gguf"
get mradermacher/Qwen2.5-VL-7B-Instruct-GGUF "$PROJ" "$M/mmproj.gguf"
get Comfy-Org/Qwen-Image_ComfyUI split_files/vae/qwen_image_vae.safetensors "$M/vae.safetensors"
PROMPT="$(cat "$HERE/prompt.txt")"; STEPS=20; CFG=2.5; EXTRA=()
if [ -n "$LORA" ]; then   # 4-step "Lightning" add-on: ~5x faster
  mkdir -p "$M/lora"; get lightx2v/Qwen-Image-Edit-2511-Lightning "$LORA" "$M/lora/lightning.safetensors"
  PROMPT="$PROMPT <lora:lightning:1>"; STEPS=4; CFG=1; EXTRA=(--lora-model-dir "$M/lora")
fi

OUT="$HERE/out/idol-$(date +%H%M%S).png"
echo "3/3  generating ${SIZE}px, $STEPS steps on $BACKEND - this can take 10-60 minutes on a CPU"
START=$(date +%s)
"$SD" --diffusion-model "$M/edit.gguf" --vae "$M/vae.safetensors" --llm "$M/llm.gguf" --llm_vision "$M/mmproj.gguf" \
  -r "$PHOTO" -p "$PROMPT" --cfg-scale $CFG --steps $STEPS --sampling-method euler --flow-shift 3 \
  --model-args qwen_image_zero_cond_t=true -W $SIZE -H $SIZE --seed 42 --offload-to-cpu "${EXTRA[@]}" -o "$OUT"
echo "Done in $(( ($(date +%s)-START)/60 )) min -> $OUT"
