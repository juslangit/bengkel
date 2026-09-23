#!/usr/bin/env bash
#
# Install a local 3D generator on the Windows PC, inside WSL.
#
# This is the open-weight equivalent of Meshy: Tencent's Hunyuan3D-2. It turns
# an image into a textured mesh, runs entirely on the machine, costs nothing
# per model and needs no account.
#
#   bash install.sh            shape generation only  (~5 GB VRAM, no compiler)
#   bash install.sh --texture  shape and texture      (~12 GB VRAM, builds CUDA)
#
# Why it is staged that way: shape generation is pure PyTorch and either works
# or fails on the first run. Texture generation needs two custom C++/CUDA
# extensions compiled against your exact CUDA version, which is where this kind
# of install usually dies. Get the first half working and proven before going
# near the second.
#
# The card is an RTX 3060 with 12 GB. Shape at ~5 GB is comfortable; shape plus
# texture at ~12 GB is right at the edge, so expect to generate at a lower
# resolution or to run the two stages one after the other rather than together.

set -euo pipefail

ROOT="${HOME}/hunyuan3d"
REPO="https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git"
WITH_TEXTURE=0
[ "${1:-}" = "--texture" ] && WITH_TEXTURE=1

say() { printf '\n\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mstopped:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- the card
say "Checking the GPU"
command -v nvidia-smi >/dev/null 2>&1 || die \
  "nvidia-smi is not on the PATH inside WSL. Install the NVIDIA driver on
   Windows (not inside WSL) and make sure WSL2 is the backend, then reopen
   this shell."
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
[ "$VRAM" -ge 5500 ] || die "only ${VRAM} MB of VRAM; shape generation needs about 5 GB"
if [ "$WITH_TEXTURE" = 1 ] && [ "$VRAM" -lt 11000 ]; then
  die "texture generation wants about 12 GB and this card reports ${VRAM} MB"
fi

# ---------------------------------------------------------------- python
say "Setting up Python"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed in WSL"
python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' \
  || die "Python 3.10 or newer is needed; this is $(python3 -V)"

mkdir -p "$ROOT"
cd "$ROOT"
if [ ! -d venv ]; then
  python3 -m venv venv || die "could not make a virtualenv (apt install python3-venv)"
fi
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --quiet --upgrade pip wheel

say "Installing PyTorch with CUDA (this is the big one, several GB)"
python -c "import torch" 2>/dev/null || \
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
python - <<'PY'
import torch
print("  torch", torch.__version__, "| cuda available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("torch cannot see the GPU - the CUDA wheel or the driver is wrong")
print("  device:", torch.cuda.get_device_name(0))
PY

# ---------------------------------------------------------------- the model
say "Fetching Hunyuan3D-2"
[ -d Hunyuan3D-2 ] || git clone --depth 1 "$REPO"
cd Hunyuan3D-2
pip install --quiet -r requirements.txt
pip install --quiet -e .

say "Downloading the mini-turbo weights (0.6B shape model, about 2 GB)"
pip install --quiet "huggingface_hub[cli]"
python - <<'PY'
from huggingface_hub import snapshot_download
# the small, fast shape model: 0.6B against the standard 1.1B, and the one
# that actually fits a 12 GB card alongside everything else
snapshot_download("tencent/Hunyuan3D-2mini",
                  allow_patterns=["hunyuan3d-dit-v2-mini-turbo/*", "*.json", "*.md"])
print("  weights in place")
PY

# ---------------------------------------------------------------- texture
if [ "$WITH_TEXTURE" = 1 ]; then
  say "Building the texture extensions (custom rasteriser and renderer)"
  command -v nvcc >/dev/null 2>&1 || die \
    "nvcc is not on the PATH. The CUDA toolkit is needed to compile these -
     apt install nvidia-cuda-toolkit, or skip texture and run shape only."
  ( cd hy3dgen/texgen/custom_rasterizer && pip install --quiet -e . ) \
    || die "the custom rasteriser would not build - run shape-only for now"
  ( cd hy3dgen/texgen/differentiable_renderer && pip install --quiet -e . ) \
    || die "the differentiable renderer would not build - run shape-only for now"
  python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("tencent/Hunyuan3D-2",
                  allow_patterns=["hunyuan3d-paint-v2-0-turbo/*", "*.json"])
print("  paint weights in place")
PY
fi

# ---------------------------------------------------------------- proof
say "Smoke test: one small mesh from the demo image"
cd "$ROOT/Hunyuan3D-2"
python - <<'PY'
import glob, time
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
from PIL import Image

image = sorted(glob.glob("assets/example_images/*.png"))[0]
pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    "tencent/Hunyuan3D-2mini", subfolder="hunyuan3d-dit-v2-mini-turbo")
started = time.time()
mesh = pipe(image=Image.open(image).convert("RGB"),
            num_inference_steps=20, octree_resolution=256)[0]
mesh.export("/tmp/hunyuan-smoke.glb")
print("  made /tmp/hunyuan-smoke.glb in %.0f seconds" % (time.time() - started))
PY

say "Done. Start the service with:"
echo "    cd $ROOT/Hunyuan3D-2 && source ../venv/bin/activate && \\"
echo "    python $(cd "$(dirname "$0")" && pwd)/serve.py"
