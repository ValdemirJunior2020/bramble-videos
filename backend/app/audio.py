from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from .config import settings
from .models import VoiceInfo


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

async def _chatterbox_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.chatterbox_url.rstrip('/')}/health")
            return response.status_code == 200
    except Exception:
        return False

async def _sapi(text: str, language: str, voice: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    target = _ps_escape(str(output.resolve()))
    txt = _ps_escape(text)
    requested = _ps_escape(voice)
    culture = "pt-BR" if language == "pt-BR" else "en-US"
    script = f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $voices=$s.GetInstalledVoices() | ForEach-Object {{$_.VoiceInfo}}; $v=$null; if ('{requested}' -ne '') {{$v=$voices | Where-Object {{$_.Name -eq '{requested}'}} | Select-Object -First 1}}; if ($null -eq $v) {{$v=$voices | Where-Object {{$_.Culture.Name -eq '{culture}'}} | Select-Object -First 1}}; if ($null -eq $v) {{ throw 'No installed Windows voice matches {culture}. Choose or install a local voice for this language.' }}; $s.SelectVoice($v.Name); $s.Rate=-1; $s.SetOutputToWaveFile('{target}'); $s.Speak('{txt}'); $s.Dispose()"
    await _run(["powershell", "-NoProfile", "-Command", script])

async def _chatterbox(text: str, style: str, output: Path) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(f"{settings.chatterbox_url.rstrip('/')}/synthesize", json={"text": text, "style": style})
        response.raise_for_status()
        output.write_bytes(response.content)

async def normalize_wav(source: Path, target: Path, speed: float = 1.0) -> None:
    filters: list[str] = []
    if abs(speed - 1.0) > 0.001:
        filters = ["-filter:a", f"atempo={speed:.4f}"]
    await _run(["ffmpeg", "-y", "-i", str(source), *filters, "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(target)])

async def synthesize_phrase(text: str, language: str, voice: str, style: str, output: Path) -> None:
    raw = output.with_name(output.stem + "-raw.wav")
    if language == "en" and await _chatterbox_available():
        await _chatterbox(text, style, raw)
    else:
        await _sapi(text, language, voice, raw)
    await normalize_wav(raw, output, settings.narration_speed)
    raw.unlink(missing_ok=True)

async def duration(path: Path) -> float:
    out, _ = await _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(out.strip())

async def make_silence(path: Path, seconds: float = 0.12) -> None:
    await _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", f"{seconds:.3f}", "-c:a", "pcm_s16le", str(path)])

def _srt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{milli:03}"

async def build_narration_and_subtitles(scenes, language: str, voice: str, style: str, workdir: Path):
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
        for phrase in split_phrases(scene.narration):
            index += 1
            part = audio_dir / f"phrase-{index:04d}.wav"
            await synthesize_phrase(phrase, language, voice, style, part)
            seconds = await duration(part)
            subtitle_entries.append({"index": index, "scene_number": scene.scene_number, "text": phrase, "start": cursor, "end": cursor + seconds})
            concat_entries.append(part)
            cursor += seconds
            concat_entries.append(silence)
            cursor += 0.12
        scene.start_seconds = scene_start
        scene.end_seconds = cursor
        scene.duration_seconds = max(0.1, cursor - scene_start)
    concat_file = audio_dir / "concat.txt"
    concat_file.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in concat_entries), encoding="utf-8")
    narration = workdir / "narration.wav"
    await _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c:a", "pcm_s16le", str(narration)])
    srt = workdir / "subtitles.srt"
    srt.write_text("\n".join(f"{x['index']}\n{_srt_time(x['start'])} --> {_srt_time(x['end'])}\n{x['text']}\n" for x in subtitle_entries), encoding="utf-8")
    (workdir / "subtitle-timing.json").write_text(json.dumps(subtitle_entries, indent=2, ensure_ascii=False), encoding="utf-8")
    return narration, srt, subtitle_entries
