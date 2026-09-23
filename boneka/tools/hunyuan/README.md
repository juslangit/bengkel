# A local 3D generator, on the Windows PC

The open-weight equivalent of Meshy: **Tencent's Hunyuan3D-2**, running on the
RTX 3060 at the academy. An image goes in, a mesh comes out, it costs nothing
per model, needs no account, and works offline once installed.

It exists because a hand-written recipe can build a body to measured
proportions but cannot build a face — that needs a model that has seen a
million of them. See `06-decisions.md`, D-024, in the knowledge base.

## Why the PC and not the Mac

| | |
|---|---|
| MacBook Air, M2 | **8 GB unified memory**, shared with everything else. Not enough, and these are CUDA-first |
| Todak PC, RTX 3060 | **12 GB VRAM**. Shape generation wants ~5 GB, shape + texture ~12 GB |

So shape generation is comfortable and texture is right at the edge, which is
why the install is staged.

## Setting it up, once

On the PC, in WSL:

```bash
bash install.sh              # shape only — ~5 GB VRAM, nothing to compile
bash install.sh --texture    # adds texture — ~12 GB, builds two CUDA extensions
```

Start with the first. Shape generation is pure PyTorch and either works on the
first run or fails loudly. Texture needs two custom C++/CUDA extensions built
against your exact CUDA version, which is where installs like this usually
die — get the first half proven before going near it.

Then start the service:

```bash
cd ~/hunyuan3d/Hunyuan3D-2 && source ../venv/bin/activate
python /path/to/boneka/tools/hunyuan/serve.py           # add --texture if built
```

It prints a token. Put both lines in `~/.claude/.env` **on the Mac**:

```
HUNYUAN_URL=http://100.104.28.73:4488
HUNYUAN_TOKEN=<the token it printed>
```

That address is the PC's Tailscale address. boneka picks it up on the next
start and the panel says the PC is awake.

## Using it

In boneka, open **"Generate from a photo, on the PC"**, choose an image, press
the button. A minute or two later the mesh arrives and lands in the session.

Then press **Auto-Rig**. It will use the *fitted* route, not the exact one —
what comes back is one lump with no named parts, so there is nothing to read
and a standard skeleton is measured against its proportions instead. That path
has been there since the Meshy button and is what this reuses.

## What this is not

- **Not as good as Meshy on texture.** Meshy's remesh, UV unwrap and 8K
  multi-view texturing are tuned as one commercial product. Expect a good
  shape and a more variable texture.
- **Not always available.** The PC is at the academy and is often off. Every
  call from the Mac is written to fail quickly and say so.
- **Not parametric.** Unlike a recipe, you cannot ask for the same thing 20%
  taller and get the same thing.

## Untested

**None of this has been run.** It was written while the PC was reachable on
the tailnet but with nothing listening on it — no claude-chat, no SSH — so
there was no way to get a shell. The install script checks its ground as it
goes and stops with a plain reason rather than half-finishing, but it has not
been proven, and the first run should be watched.
