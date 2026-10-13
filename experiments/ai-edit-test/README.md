# Experiment: full AI "dress on idol" on a laptop CPU

**Question:** can a free, local, open-source image-editing model take a seller's flat photo of a
Laddu Gopal dress and produce a marketplace photo of an idol wearing *that exact dress*,
on a normal laptop with no NVIDIA graphics card?

## Setup

| | |
|---|---|
| Model | **Qwen-Image-Edit-2511** (Apache-2.0), `Q3_K_M` quantization (~9.5 GB) |
| Vision/text encoder | Qwen2.5-VL-7B-Instruct `Q4_K_M` + `mmproj` (reads the photo and the prompt) |
| Speed-up | Qwen-Image-Edit-2511-Lightning 4-step LoRA |
| Runtime | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) Windows CPU build |
| Machine | Windows laptop, CPU only (no NVIDIA card), 768×768 output, seed 42 |
| Prompt | [`prompt.txt`](prompt.txt) - "dress the idol in the exact outfit, change nothing" |

```bash
QUANT=Q3_K_M bash run.sh dress.jpg     # downloads ~17 GB of models on first run
```

## Results

| Stage | Time |
|---|---|
| Encode the reference photo (VAE) | 229 s |
| Read prompt + photo (Qwen2.5-VL) | 272 s |
| Drawing, per step | ~2,780 s (46 min) |
| **Total for one image** | **~3 hours** |

**Quality:** the model kept the dress's *colours and motifs* (red base, pink flowers, green
leaves, gold border) but **redesigned the product**: added sleeves and a hood, turned the
flat round dress into a pleated gown with a plain skirt, and invented a different figure
instead of the idol. For a marketplace listing that is a different product from the one
the buyer receives.

## Conclusion

Full generative editing is (a) far too slow on a seller's laptop and (b) not faithful
enough to the real product, even with a strict prompt. That led to StockSnap's
**scene templates** (`backend/app/services/scenes.py`): the real product photo is
reshaped into a ready-made scene with plain image processing - about **0.5 s per image**,
free, offline, and every detail of the product is exactly as photographed.

Models, binaries and photos are not committed (see `.gitignore`).

## Test 2: dress a photo of the idol without clothes (recommended)

Instead of letting the AI invent the idol, give it a real photo of the idol with no
dress. The AI then only has to add the dress: the idol, jewellery, pose and
background stay from your photo.

1. Put two photos in `C:\Projects\ai-edit-test`:
   - the dress (flat photo, the whole dress visible), e.g. `dress.jpg`
   - the idol without clothes, front view, plain background, e.g. `idol_bare.jpg`
2. In Git Bash:
   ```bash
   cd /c/Projects/ai-edit-test
   bash run.sh dress.jpg idol_bare.jpg
   ```
3. Leave the PC on (plugged in, sleep off). Expect a few hours on a CPU - two input
   photos take longer than one. The result lands in `out/idol-HHMMSS.png`.
4. Not right? Try another seed (`SEED=7 bash run.sh dress.jpg idol_bare.jpg`) or edit
   `prompt_idol.txt`. Faster, lower-quality test run: `SIZE=512 bash run.sh ...`

The prompt (`prompt_idol.txt`) calls the idol photo "image 1" and the dress "image 2",
and spells out how a worn dress sits: top over chest and shoulders, necklaces and hands
in front of it, skirt from the waist over the legs and spread on the floor.

Always compare the result with the real dress before listing it: the AI redraws the
dress, so small details (motif count, sequin pattern) can change.
