from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

import httpx

from .assets import find_asset
from .config import settings
from .models import VoiceInfo

EMOTION_PROFILES: dict[str, dict[str, float]] = {
    "calm": {"exaggeration": 0.45, "cfg_weight": 0.35, "temperature": 0.70},
    "documentary": {"exaggeration": 0.55, "cfg_weight": 0.35, "temperature": 0.72},
    "warm": {"exaggeration": 0.65, "cfg_weight": 0.32, "temperature": 0.76},
    "inspirational": {"exaggeration": 0.78, "cfg_weight": 0.30, "temperature": 0.82},
    "emotional": {"exaggeration": 0.90, "cfg_weight": 0.28, "temperature": 0.86},
    "dramatic": {"exaggeration": 1.00, "cfg_weight": 0.25, "temperature": 0.90},
    "sermon": {"exaggeration": 0.88, "cfg_weight": 0.25, "temperature": 0.82},
}

STYLE_RATE = {
    "calm": -2,
    "documentary": -1,
    "warm": -1,
    "inspirational": 0,
    "emotional": -1,
    "dramatic": 0,
    "sermon": -2,
}
PIPER_STYLE_SPEED = {
    "calm": 0.93,
    "documentary": 0.97,
    "warm": 0.96,
    "inspirational": 1.00,
    "emotional": 0.94,
    "dramatic": 0.91,
    "sermon": 0.90,
}
SPEECH_VERBS = "said|asked|replied|answered|whispered|shouted|cried|called|squeaked|murmured|laughed|exclaimed|yelled|spoke"
QUOTE_PATTERN = re.compile(r'[“\"]([^”\"]+)[”\"]')


def _ps_escape(value: str) -> str:
    return value.replace("'", "''")


async def _run(cmd: list[str]) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(err.decode(errors="ignore")[-3000:])
    return out.decode(errors="ignore"), err.decode(errors="ignore")


async def list_sapi_voices() -> list[VoiceInfo]:
    script = "Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.GetInstalledVoices() | ForEach-Object { $i=$_.VoiceInfo; Write-Output ($i.Name+'|'+$i.Culture.Name+'|'+$i.Gender) }"
    try:
        out, _ = await _run(["powershell", "-NoProfile", "-Command", script])
    except Exception:
        return []
    voices: list[VoiceInfo] = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if parts and parts[0]:
            voices.append(VoiceInfo(name=parts[0], culture=parts[1] if len(parts) > 1 else "", gender=parts[2] if len(parts) > 2 else ""))
    return voices


def split_phrases(text: str, max_words: int = 9) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = [x.strip() for x in re.split(r"(?<=[,;:.!?])\s+", text) if x.strip()]
    out: list[str] = []
    for part in parts or [text]:
        words = part.split()
        if len(words) <= max_words:
            out.append(part)
        else:
            out.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
    return out


def _speaker_from_context(prefix: str, suffix: str, scene_characters: list[str]) -> str:
    candidates = [name for name in scene_characters if name]
    for name in candidates:
        escaped = re.escape(name)
        if re.search(rf"\b{escaped}\b\s+(?:{SPEECH_VERBS})\b", suffix, re.I):
            return name
        if re.search(rf"\b{escaped}\b\s+(?:{SPEECH_VERBS})\b", prefix[-140:], re.I):
            return name
        if re.search(rf"(?:{SPEECH_VERBS})\s+\b{escaped}\b", suffix, re.I):
            return name
    nearest = ""
    nearest_pos = -1
    low = prefix.lower()
    for name in candidates:
        pos = low.rfind(name.lower())
        if pos > nearest_pos:
            nearest = name
            nearest_pos = pos
    if nearest:
        return nearest
    if len(candidates) == 1:
        return candidates[0]
    return "Narrator"


def split_voice_chunks(text: str, scene_characters: list[str]) -> list[tuple[str, str]]:
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    names = [name for name in scene_characters if name]
    if names:
        name_alt = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True))
        explicit = re.compile(rf"\b({name_alt})\s*:\s*", re.I)
        matches = list(explicit.finditer(normalized))
        if matches:
            chunks: list[tuple[str, str]] = []
            if matches[0].start() > 0:
                lead = normalized[:matches[0].start()].strip()
                if lead:
                    chunks.append(("Narrator", lead))
            for i, match in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(normalized)
                body = normalized[match.end():end].strip()
                canonical = next((n for n in names if n.lower() == match.group(1).lower()), match.group(1))
                if body:
                    chunks.append((canonical, body))
            return chunks

    chunks: list[tuple[str, str]] = []
    cursor = 0
    for match in QUOTE_PATTERN.finditer(normalized):
        before = normalized[cursor:match.start()].strip()
        if before:
            chunks.append(("Narrator", before))
        prefix = normalized[:match.start()]
        suffix = normalized[match.end():match.end() + 120]
        speaker = _speaker_from_context(prefix, suffix, names)
        dialogue = match.group(1).strip()
        if dialogue:
            chunks.append((speaker, dialogue))
        cursor = match.end()
    tail = normalized[cursor:].strip()
    if tail:
        chunks.append(("Narrator", tail))
    return chunks or [("Narrator", normalized)]


async def _chatterbox_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.chatterbox_url.rstrip('/')}/health")
            return response.status_code == 200
    except Exception:
        return False


async def _sapi(text: str, language: str, voice: str, style: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    target = _ps_escape(str(output.resolve()))
    txt = _ps_escape(text)
    requested = _ps_escape(voice if voice not in {"__chatterbox__", "__piper_ptbr__"} else "")
    culture = "pt-BR" if language == "pt-BR" else "en-US"
    rate = STYLE_RATE.get((style or "warm").strip().lower(), -1)
    script = f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $voices=$s.GetInstalledVoices() | ForEach-Object {{$_.VoiceInfo}}; $v=$null; if ('{requested}' -ne '') {{$v=$voices | Where-Object {{$_.Name -eq '{requested}'}} | Select-Object -First 1}}; if ($null -eq $v) {{$v=$voices | Where-Object {{$_.Culture.Name -eq '{culture}'}} | Select-Object -First 1}}; if ($null -eq $v) {{ throw 'No installed Windows voice matches {culture}.' }}; $s.SelectVoice($v.Name); $s.Rate={rate}; $s.SetOutputToWaveFile('{target}'); $s.Speak('{txt}'); $s.Dispose()"
    await _run(["powershell", "-NoProfile", "-Command", script])


def _piper_executable() -> str:
    found = shutil.which("piper")
    if found:
        return found
    scripts = Path(sys.executable).resolve().parent
    for name in ("piper.exe", "piper"):
        candidate = scripts / name
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Brazilian Portuguese voice engine is missing. Run INSTALL.bat again to install Piper TTS.")


async def _piper_ptbr(text: str, style: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    voice_dir = settings.storage_path / "voices" / "piper"
    voice_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        _piper_executable(),
        "--model", "pt_BR-faber-medium",
        "--data-dir", str(voice_dir),
        "--download-dir", str(voice_dir),
        "--output_file", str(output),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(text.encode("utf-8"))
    if proc.returncode != 0:
        raise RuntimeError((err or out).decode(errors="ignore")[-3000:])
    if not output.exists():
        raise RuntimeError("Piper Brazilian Portuguese voice did not create audio")


async def _chatterbox(text: str, language: str, style: str, output: Path, reference_voice: Path | None = None) -> None:
    profile = EMOTION_PROFILES.get((style or "warm").strip().lower(), EMOTION_PROFILES["warm"])
    base = settings.chatterbox_url.rstrip("/")
    async with httpx.AsyncClient(timeout=None) as client:
        if reference_voice and reference_voice.exists():
            with reference_voice.open("rb") as handle:
                response = await client.post(
                    f"{base}/synthesize-upload",
                    data={
                        "text": text,
                        "language": language,
                        "style": style,
                        "exaggeration": str(profile["exaggeration"]),
                        "cfg_weight": str(0.0 if language == "pt-BR" else profile["cfg_weight"]),
                        "temperature": str(profile["temperature"]),
                    },
                    files={"reference": (reference_voice.name, handle, "audio/wav")},
                )
        else:
            response = await client.post(
                f"{base}/synthesize",
                json={
                    "text": text,
                    "language": language,
                    "style": style,
                    "exaggeration": profile["exaggeration"],
                    "cfg_weight": profile["cfg_weight"],
                    "temperature": profile["temperature"],
                },
            )
        response.raise_for_status()
        output.write_bytes(response.content)


async def normalize_wav(source: Path, target: Path, speed: float = 1.0, volume: float = 1.0) -> None:
    filters: list[str] = []
    chain: list[str] = []
    speed = max(0.5, min(2.0, speed))
    volume = max(0.1, min(3.0, volume))
    if abs(speed - 1.0) > 0.001:
        chain.append(f"atempo={speed:.4f}")
    if abs(volume - 1.0) > 0.001:
        chain.append(f"volume={volume:.3f}")
    if chain:
        filters = ["-filter:a", ",".join(chain)]
    await _run(["ffmpeg", "-y", "-i", str(source), *filters, "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(target)])


async def synthesize_phrase(
    text: str,
    language: str,
    voice: str,
    style: str,
    output: Path,
    reference_voice_path: str | None = None,
    speed: float = 1.0,
    volume: float = 1.0,
) -> None:
    raw = output.with_name(output.stem + "-raw.wav")
    reference = Path(reference_voice_path) if reference_voice_path else None
    chatterbox_available = await _chatterbox_available()

    if language == "pt-BR":
        if reference and reference.exists() and chatterbox_available:
            await _chatterbox(text, language, style, raw, reference)
        elif voice and voice not in {"__chatterbox__", "__piper_ptbr__"}:
            try:
                await _sapi(text, language, voice, style, raw)
            except Exception:
                await _piper_ptbr(text, style, raw)
        else:
            await _piper_ptbr(text, style, raw)
        piper_speed = PIPER_STYLE_SPEED.get((style or "warm").strip().lower(), 0.96)
        await normalize_wav(raw, output, settings.narration_speed * speed * piper_speed, volume)
        raw.unlink(missing_ok=True)
        return

    use_chatterbox = voice == "__chatterbox__" or bool(reference) or not voice
    if use_chatterbox and chatterbox_available:
        await _chatterbox(text, language, style, raw, reference)
    elif voice and voice != "__chatterbox__":
        try:
            await _sapi(text, language, voice, style, raw)
        except Exception:
            if chatterbox_available:
                await _chatterbox(text, language, style, raw, reference)
            else:
                raise
    elif chatterbox_available:
        await _chatterbox(text, language, style, raw, reference)
    else:
        await _sapi(text, language, voice, style, raw)
    await normalize_wav(raw, output, settings.narration_speed * speed, volume)
    raw.unlink(missing_ok=True)


async def duration(path: Path) -> float:
    out, _ = await _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ])
    return float(out.strip())


async def make_silence(path: Path, seconds: float = 0.12) -> None:
    await _run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
        "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(path),
    ])


def _srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{milli:03}"


def _voice_for_speaker(
    speaker: str,
    default_voice: str,
    default_style: str,
    default_reference: str | None,
) -> tuple[str, str, str | None, float, float]:
    if not speaker or speaker == "Narrator":
        return default_voice, default_style, default_reference, 1.0, 1.0
    asset = find_asset(speaker)
    if not asset or asset.type != "character":
        return default_voice, default_style, default_reference, 1.0, 1.0
    voice = asset.voice or ""
    style = asset.voice_style or default_style
    reference = asset.voice_reference_path or None
    return voice, style, reference, asset.voice_speed, asset.voice_volume


async def build_narration_and_subtitles(
    scenes,
    language: str,
    voice: str,
    style: str,
    workdir: Path,
    reference_voice_path: str | None = None,
):
    audio_dir = workdir / "audio_parts"
    audio_dir.mkdir(parents=True, exist_ok=True)
    silence = audio_dir / "silence.wav"
    await make_silence(silence)
    concat_entries: list[Path] = []
    subtitle_entries: list[dict] = []
    cursor = 0.0
    index = 0

    for scene in scenes:
        scene_start = cursor
        voice_chunks = split_voice_chunks(scene.narration, scene.characters)
        for speaker, chunk in voice_chunks:
            selected_voice, selected_style, selected_reference, selected_speed, selected_volume = _voice_for_speaker(
                speaker, voice, style, reference_voice_path
            )
            for phrase in split_phrases(chunk):
                index += 1
                part = audio_dir / f"phrase-{index:04d}.wav"
                await synthesize_phrase(
                    phrase,
                    language,
                    selected_voice,
                    selected_style,
                    part,
                    selected_reference,
                    selected_speed,
                    selected_volume,
                )
                seconds = await duration(part)
                subtitle_entries.append({
                    "index": index,
                    "scene_number": scene.scene_number,
                    "speaker": speaker,
                    "text": phrase,
                    "start": cursor,
                    "end": cursor + seconds,
                })
                concat_entries.append(part)
                cursor += seconds
                concat_entries.append(silence)
                cursor += 0.12
        scene.start_seconds = scene_start
        scene.end_seconds = cursor
        scene.duration_seconds = max(0.1, cursor - scene_start)

    concat_file = audio_dir / "concat.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in concat_entries),
        encoding="utf-8",
    )
    narration = workdir / "narration.wav"
    await _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:a", "pcm_s16le", str(narration),
    ])
    srt = workdir / "subtitles.srt"
    srt.write_text(
        "\n".join(
            f"{x['index']}\n{_srt_time(x['start'])} --> {_srt_time(x['end'])}\n{x['text']}\n"
            for x in subtitle_entries
        ),
        encoding="utf-8",
    )
    (workdir / "subtitle-timing.json").write_text(
        json.dumps(subtitle_entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return narration, srt, subtitle_entries
