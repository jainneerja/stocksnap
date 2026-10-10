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
