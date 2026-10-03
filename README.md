# Bramble Videos

Bramble Videos is a **local cinematic AI production studio**. The React interface, FastAPI project system, Character Library, exact script handling, narration, exact phrase subtitle timing, music, watermark, and FFmpeg finishing remain Bramble-owned workflows. **Video generation is powered by WanGP** through its official Python API.

## Core engines

- **WanGP** — cinematic image/video generation through the official `shared.api` Python integration.
- **Ollama** — script and scene intelligence only.
- **Chatterbox / Windows / Piper voices** — narration.
- **FFmpeg** — final edit, subtitles, music, watermark, scaling/cropping, and AMD AMF encoding when available.
- **ComfyUI** — retained only as an optional compatibility fallback while the migration settles.

Bramble does not automate WanGP's browser or scrape Gradio. A local WanGP bridge owns one persistent `WanGPSession` so a large model is not reinitialized for every scene.

## Target AMD machine

Primary validated configuration target:

- AMD Radeon RX 9060 XT 16 GB
- RDNA 4 / `gfx1200`
- Windows 11
- 32 GB system RAM
- Python 3.12 for the WanGP environment
- RX 9060 XT compatibility stack: PyTorch `2.12.0+rocm7.14.0` with WanGP pinned to the validated RDNA4 revision
- WanGP memory profile 4
- SDPA attention by default

ROCm-enabled PyTorch still exposes the AMD device through the `torch.cuda` namespace. That does not mean CUDA packages are installed.

## Architecture

```text
Bramble React UI
        |
Bramble FastAPI backend
        |
scene planner + Character Library + Consistency Lock
        |
local Bramble WanGP bridge (127.0.0.1:8020)
        |
persistent WanGP shared.api session
        |
AMD RX 9060 XT / gfx1200
        |
real generated MP4 scene clips
        |
FFmpeg + narration + exact subtitles + music + watermark
        |
final MP4
```

WanGP stays in `runtime/WanGP` by default and is ignored by Git. You can set `WANGP_ROOT` to another directory, such as `C:\AI\WanGP`. Model files and checkpoints are never committed to this repository.

## Install

1. Install Git, Node.js, FFmpeg/FFprobe, Python for Bramble, and **Python 3.12** for WanGP.
2. Double-click `INSTALL.bat`.
3. The installer:
   - detects the AMD GPU and reports RX 9060 XT as `gfx1200`;
   - clones the official WanGP repository if it is missing;
   - creates an isolated `wan2gp-env`;
   - calls WanGP's current official automatic installer, which detects the AMD target and installs the recommended ROCm/TheRock stack;
   - installs WanGP and the small local bridge dependencies;
   - verifies `shared.api` imports and `torch.cuda.is_available()`;
   - preserves the independent Bramble and Chatterbox environments;
   - installs frontend dependencies;
   - verifies FFmpeg/AMF and runs code tests.

The first WanGP model download can be large. Bramble lists the models WanGP reports and uses their availability/capability metadata rather than pretending every model is installed.

## Start / stop

Double-click `START.bat`.

It reuses compatible already-running services and starts:

- Bramble frontend — `127.0.0.1:5174`
- Bramble FastAPI — `127.0.0.1:8010`
- Bramble WanGP bridge — `127.0.0.1:8020`
- Chatterbox — `127.0.0.1:8001` when needed
- Ollama — `127.0.0.1:11434` when installed

The standard workflow does **not** open the WanGP Gradio UI.

`STOP.bat` stops only PID-tracked services that this Bramble launch started. Pre-existing/shared services are left untouched, and Ollama is never killed by Bramble.

All services bind to localhost by default.

## Cinematic generation

Normal projects use **WanGP** as the default generator. The UI provides:

- dynamic local model discovery;
- Fast Preview, Balanced Cinematic, High Quality, and Maximum Local Quality presets;
- real moving scene clips instead of slideshow-style still-image zooms;
- character reference conditioning when the selected model exposes a compatible reference role;
- sequential one-heavy-job-at-a-time generation for 16 GB VRAM safety;
- long-scene splitting into continuity sub-shots;
- progress phase and percentage from WanGP events;
- image or MP4 generation preview when WanGP emits one;
- real cancellation through `SessionJob.cancel()`;
- saved seeds;
- regenerate with the same seed or a new seed;
- completed-scene reuse so a stopped project does not intentionally regenerate successful clips.

For a narration scene longer than the practical shot window, Bramble generates multiple short shots and joins them while preserving scene identity/continuity instructions.

## Character consistency

The Character Library remains first-class. Bramble, Grace, Pip, Oliver, Barnaby, and custom saved characters can hold multiple approved references.

When Consistency Lock is on, a named scene character without a valid approved reference blocks generation rather than silently substituting a random character.

Bramble passes approved references using the strongest generic media role declared by the selected WanGP model. Unsupported reference modes return an actionable error.

## Exact script, narration, and subtitles

The planner may split and visually analyze the script, but the narration text is not rewritten merely to make the visual prompt better.

Subtitle timing is still based on measured audio duration, not estimated word count. Narration phrases and subtitle timing share the same FFprobe-measured timeline.

Existing English / Portuguese-Brazilian selection, narration styles, Windows voices, Chatterbox, uploaded voice references, background music, watermark controls, and aspect-ratio output remain available.

## Outputs and resume

Project state remains under `storage/projects/<project-id>/`. WanGP scene clips are organized under:

```text
storage/projects/<project-id>/
  project.json
  narration/
  scenes/
    scene-001/
      prompt-01.json
      settings-01.json
      clip.mp4
    scene-002/
      prompt-01.json
      settings-01.json
      clip.mp4
  final/
    <project-id>-final.mp4
```

`project.json` persists scene state, progress, seed, selected model/preset, clip paths, and final output state.

## System health

The System page calls `GET /api/system/health` and reports:

- WanGP installed / ready
- detected GPU
- `gfx1200` on RX 9060 XT
- VRAM
- PyTorch version
- ROCm/HIP version
- GPU acceleration
- WanGP commit
- Ollama
- Chatterbox
- FFmpeg
- AMD AMF / `h264_amf`

Run `GPU_CHECK.bat` for a terminal-level diagnostic.

## Hardware smoke test

After at least one compatible WanGP video model is installed, run:

```bat
TEST_WANGP.bat
```

It uses the official `shared.api` session to generate a short real video with conservative settings:

> A cinematic sunrise over a peaceful meadow, slow camera push forward.

The test passes only when WanGP returns a real MP4 on disk.

## Tests

Normal code validation:

```bat
TEST.bat
```

CI compiles the Bramble backend plus WanGP bridge/smoke scripts, runs the Python tests, and builds the React frontend. Hardware generation is intentionally a local smoke test because GitHub-hosted CI does not provide the target RX 9060 XT.

## Troubleshooting

**WanGP bridge offline** — verify `WANGP_ROOT` in `.env`, run `GPU_CHECK.bat`, then restart `START.bat`.

**ROCm PyTorch cannot see the GPU** — `GPU_CHECK.bat` must report `torch.cuda.is_available() = True` and an AMD Radeon device. Do not install CUDA as a workaround.

**Selected model is missing** — install/download that model through the supported WanGP model mechanism, or select another available model in Bramble.

**Out of VRAM** — use Balanced or Fast Preview, keep profile 4/SDPA, and avoid simultaneous GPU-heavy Ollama workloads while a WanGP scene is rendering.

**AMD AMF unavailable** — Bramble falls back to `libx264`; generation itself can still work.

## WanGP attribution and license

**Video generation powered by WanGP**, a DeepBeepMeep production.

Bramble clones WanGP as an independently updateable local runtime rather than copying its source into this repository. WanGP currently uses the **WanGP Community License 2.0** and its third-party models/components retain their own licenses. Upstream notices must remain intact. Review the current WanGP license before redistributing Bramble together with WanGP or using the integration as part of a paid/hosted product.

Bramble records the installed WanGP Git commit in system health for debugging and reproducibility. It does not automatically replace a working WanGP checkout with an untested upstream update.
