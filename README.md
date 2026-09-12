# Bramble Videos

A separate local-first AI production studio for **Bramble & Grace**. It does not modify `MoneyPrinterJunior` or `MoneyPrint-Junior-Audio-to-image`; those working repos stay untouched.

## What this project does

- Scene-by-scene planning from your exact script. The planner analyzes the script but does not rewrite it.
- Automatic recognition of Bramble, Grace, Pip, Oliver and Barnaby when their names appear.
- Character Library with multiple approved reference images per character, location, prop or group.
- **Bramble Consistency Lock** prevents a render when a named character is missing an approved reference.
- Uses multiple face/front/back/expression reference images together when building a character reference sheet.
- Cinematic, script-matched, high-resolution ComfyUI generation: 1920x1080 for 16:9, 1080x1920 for 9:16, 1536x1536 for 1:1, 1440x1800 for 4:5, plus custom dimensions.
- New poses and expressions are created from the narration while approved character references preserve identity.
- Phrase-based subtitles and narration are generated from the **same audio chunks**, so subtitle timing and image timing share one timeline.
- English or Portuguese-Brazilian project selection.
- Local Windows voice selection plus expressive Chatterbox narration.
- Narration styles: Calm, Documentary, Warm, Inspirational, Emotional, Dramatic and Sermon.
- Optional uploaded voice-reference audio for Chatterbox voice/style matching.
- Subtitle controls for font, size, top/middle/bottom position, text color, outline color and outline width.
- Watermark image upload with position, opacity and size controls.
- Background music upload with volume control.
- 16:9, 9:16, 1:1 and 4:5 outputs plus custom width/height.
- Local Ollama scene analysis, local ComfyUI image generation, local Chatterbox, and AMD AMF video encoding when available.

## Conflict-free local ports

- Bramble frontend: `http://127.0.0.1:5174`
- Bramble backend/API: `http://127.0.0.1:8010`
- Chatterbox: `http://127.0.0.1:8001`
- Shared Ollama: `http://127.0.0.1:11434`
- Shared ComfyUI: `http://127.0.0.1:8188`

`START.bat` reuses Ollama, ComfyUI, or Chatterbox if they are already running. It does not replace or change the working services from your other projects. `STOP.bat` only stops Bramble ports `5174` and `8010`.

## Install and run

After pulling a new version, run `INSTALL.bat` once. The installer creates/verifies the backend environment, the local Chatterbox environment, frontend packages, storage folders, and tests. The first Chatterbox install can take several minutes because its local TTS dependencies are larger.

After installation, double-click `START.bat`. Open `http://127.0.0.1:5174` if the browser does not open automatically.

## Studio controls

The **Studio** page contains the language selector, local/expressive voice selector, narration style, uploaded voice reference, video format, transition, subtitle settings, background music, watermark controls, Character Reference quick upload, Consistency Lock and the episode planner.

The **Character Library** tab is for saving multiple approved reference images for Bramble, Grace, Pip, Oliver, Barnaby, locations, props and groups.

The **System** tab shows ComfyUI, Ollama, Chatterbox and FFmpeg encoder status.

## Exact sync design

The tool does **not** guess subtitle timing from word count. Each scene narration is split into readable phrases. Each phrase is synthesized as its own audio file, its real duration is measured with FFprobe, and its subtitle uses that same measured start/end time. Scene image duration is calculated from the exact sum of its phrase audio. Narration, phrase subtitles and scene changes therefore come from the same timeline.

## Character consistency

If ComfyUI has IP-Adapter nodes installed, Bramble Videos detects them and uses the approved character reference sheet through IP-Adapter first. If those nodes are not installed, it falls back to a vanilla ComfyUI image-to-image reference workflow, then to text-to-image only if required. Your existing ComfyUI installation is left untouched.

## GPU behavior

ComfyUI stays pointed at your existing working local installation. FFmpeg automatically uses `h264_amf` when the installed FFmpeg build exposes AMD AMF; otherwise it falls back to `libx264`. Ollama remains shared on port `11434`.

## Safety for your existing projects

The original two working repositories are not modified by Bramble Videos. Bramble has separate frontend/backend ports and reuses already-running shared AI services instead of replacing them.
