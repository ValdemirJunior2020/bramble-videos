# Bramble Videos

A separate local-first AI production studio for **Bramble & Grace**. It does not modify `MoneyPrinterJunior` or `MoneyPrint-Junior-Audio-to-image`; those working repos stay untouched.

## What this project does

- Scene-by-scene planning from your exact script. The planner analyzes the script but does not rewrite it.
- Automatic recognition of Bramble, Grace, Pip, Oliver and Barnaby when their names appear.
- Character Library with multiple approved reference images per character, location, prop or group.
- **Bramble Consistency Lock** prevents a render when a named character is missing an approved reference.
- New poses and expressions are created from the narration while the approved reference sheet is used as the visual starting point.
- Phrase-based subtitles and narration are generated from the **same audio chunks**, so subtitle timing and image timing share one exact timeline.
- English or Portuguese-Brazilian project selection.
- 16:9, 9:16, 1:1 and 4:5 outputs. Backend also supports custom width/height.
- Local Ollama scene analysis, local ComfyUI image generation, local Windows voices, optional local Chatterbox if it is already running.
- AMD Radeon acceleration where it is useful: ComfyUI performs image generation on the GPU, Ollama can use Radeon VRAM when available, and FFmpeg uses `h264_amf` automatically when your FFmpeg build exposes it. CPU encoding is only a fallback.

## Conflict-free local ports

Bramble Videos uses its own app ports so it can run beside your other working video tools:

- Bramble frontend: `http://127.0.0.1:5174`
- Bramble backend/API: `http://127.0.0.1:8010`
- Shared Ollama: `http://127.0.0.1:11434`
- Shared ComfyUI: `http://127.0.0.1:8188`
- Optional shared Chatterbox: `http://127.0.0.1:8001`

`START.bat` reuses Ollama and ComfyUI if they are already running. `STOP.bat` only stops ports `5174` and `8010`, so it does not stop services used by your other projects.

## Character style built in

The repo includes the Bramble & Grace character descriptions from the project strategy as metadata. Upload your approved character sheets in **Character Library**. You can add several references to the same character: face, front, back, full body, expression sheets, and so on.

If ComfyUI has IP-Adapter nodes installed, Bramble Videos detects them and uses the approved reference sheet through IP-Adapter first. If those nodes are not installed, it automatically falls back to a vanilla ComfyUI image-to-image reference workflow, and then to text-to-image only if needed. Your current working ComfyUI setup is not changed.

## Install and run

First time only:

1. Clone or download this repository.
2. Double-click `INSTALL.bat`.
3. Wait for `INSTALL COMPLETE`.

Every time after that:

1. Double-click `START.bat`.
2. The launcher starts/reuses Ollama and ComfyUI, starts the Bramble backend on port `8010`, starts the Bramble frontend on port `5174`, and opens the browser.
3. If the browser does not open automatically, open `http://127.0.0.1:5174`.

To stop Bramble only, double-click `STOP.bat`.

To verify the code after an update, double-click `TEST.bat`.

The installer never overwrites an existing `.env`.

## Existing local services

Default local integrations:

- Ollama: `127.0.0.1:11434`, model `qwen3:8b`
- ComfyUI: `127.0.0.1:8188`
- Default ComfyUI folder: `C:\Users\nobody\Documents\comfy\ComfyUI`
- Optional Chatterbox service: `127.0.0.1:8001`

Change these in the new repo's `.env` only if needed.

## Exact sync design

The tool does **not** guess subtitle timing from word count. Each scene narration is split into readable phrases. Each phrase is synthesized as its own audio file, its real duration is measured with FFprobe, and its subtitle uses that same measured start/end time. Scene image duration is then calculated from the exact sum of its phrase audio. That keeps narration, subtitles and image changes on the same timeline.

## GPU behavior

Open the **System** tab. `h264_amf` means final H.264 encoding can use AMD AMF. Ollama VRAM shows whether the loaded Ollama model is occupying GPU memory. ComfyUI remains pointed at your already-working local installation, so image generation continues to use the GPU configuration that already works on your PC.

## English and Portuguese

English can use your already-running local Chatterbox service when available, with Windows local speech as fallback. Portuguese-Brazilian uses an installed Windows `pt-BR` voice. The Studio voice list shows only voices that match the selected language.

## Safety for your existing projects

`STOP.bat` stops only the Bramble frontend/backend. It intentionally leaves Ollama and ComfyUI running so it will not shut down services used by your other working tools.
