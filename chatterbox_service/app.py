from __future__ import annotations

import asyncio
import io
import os
import re
import tempfile
import threading
import wave
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from chatterbox.tts import ChatterboxTTS
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

app = FastAPI(title="Bramble Chatterbox Service", version="1.1.0")
_english_model: ChatterboxTTS | None = None
_multilingual_model: ChatterboxMultilingualTTS | None = None
_model_lock = threading.Lock()

@dataclass(frozen=True)
class EmotionProfile:
    exaggeration: float
    cfg_weight: float
    temperature: float
    pause_scale: float
    intensity_variation: float

EMOTION_PROFILES: dict[str, EmotionProfile] = {
    "calm": EmotionProfile(0.34, 0.62, 0.68, 1.18, 0.04),
    "documentary": EmotionProfile(0.46, 0.52, 0.72, 1.00, 0.06),
    "warm": EmotionProfile(0.56, 0.48, 0.75, 1.08, 0.08),
    "inspirational": EmotionProfile(0.68, 0.40, 0.82, 1.12, 0.14),
    "emotional": EmotionProfile(0.82, 0.34, 0.86, 1.18, 0.18),
    "dramatic": EmotionProfile(1.05, 0.28, 0.92, 1.32, 0.26),
    "sermon": EmotionProfile(0.88, 0.32, 0.80, 1.42, 0.20),
}

class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1)
    style: str = "Warm"
    language: str = "en"
    exaggeration: float | None = None
    cfg_weight: float | None = None
    temperature: float | None = None

def _device() -> str:
    requested = os.getenv("TTS_DEVICE", "cpu").strip().lower()
    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("TTS_DEVICE=cuda requested but PyTorch cannot see CUDA")
    return requested

def _language_id(language: str) -> str:
    value = (language or "en").strip().lower()
    if value in {"pt-br", "pt_br", "pt"}:
        return "pt"
    return "en"

def _get_model(language: str):
    global _english_model, _multilingual_model
    lang = _language_id(language)
    with _model_lock:
        if lang == "en":
            if _english_model is None:
                _english_model = ChatterboxTTS.from_pretrained(device=_device())
            return _english_model, "en"
        if _multilingual_model is None:
            _multilingual_model = ChatterboxMultilingualTTS.from_pretrained(device=_device(), t3_model="v3")
        return _multilingual_model, lang

def _segments(text: str, max_words: int = 34) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.strip())
    sentences = [s.strip() for s in re.split(r"(?<=[.!?;:])\s+", normalized) if s.strip()]
    out: list[str] = []
    for sentence in sentences or [normalized]:
        words = sentence.split()
        if len(words) <= max_words:
            out.append(sentence)
        else:
            out.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
    return out

def _profile(style: str) -> tuple[str, EmotionProfile]:
    key = style.strip().lower()
    if key not in EMOTION_PROFILES:
        key = "warm"
    return key, EMOTION_PROFILES[key]

def _intensity(profile: EmotionProfile, style: str, index: int, total: int, segment: str) -> float:
    factor = 1.0 if total <= 1 else 1.0 + (index / max(1, total - 1) - 0.35) * profile.intensity_variation
    if style == "dramatic": factor += 0.10 if segment.rstrip().endswith("!") else (0.06 if index == total - 1 else 0.0)
    if style == "sermon": factor += 0.08 if index == total - 1 else 0.0
    return max(0.25, min(1.6, profile.exaggeration * factor))

def _pause_seconds(style: str, segment: str, scale: float) -> float:
    base = 0.30 if segment.rstrip().endswith("!") else (0.26 if segment.rstrip().endswith((".", "?")) else 0.18)
    if style == "sermon": base += 0.08
    elif style == "dramatic": base += 0.05
    return base * scale

def _tensor_to_mono_numpy(wav: torch.Tensor) -> np.ndarray:
    data = wav.detach().cpu().float().numpy()
    if data.ndim == 2: data = data.mean(axis=0)
    return np.clip(data, -1.0, 1.0)

def _wav_bytes(data: np.ndarray, sample_rate: int) -> bytes:
    pcm = (data * 32767.0).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sample_rate); wf.writeframes(pcm.tobytes())
    return buffer.getvalue()

def _synthesize_sync(text: str, style: str, language: str = "en", reference_path: str | None = None, overrides: dict | None = None) -> tuple[bytes, str]:
    key, profile = _profile(style)
    model, language_id = _get_model(language)
    segments = _segments(text)
    audio_parts: list[np.ndarray] = []
    for i, segment in enumerate(segments):
        kwargs = {
            "exaggeration": float((overrides or {}).get("exaggeration") or _intensity(profile, key, i, len(segments), segment)),
            "cfg_weight": float((overrides or {}).get("cfg_weight") or profile.cfg_weight),
            "temperature": float((overrides or {}).get("temperature") or profile.temperature),
        }
        if reference_path:
            kwargs["audio_prompt_path"] = reference_path
        if language_id != "en":
            kwargs["language_id"] = language_id
        wav = model.generate(segment, **kwargs)
        audio_parts.append(_tensor_to_mono_numpy(wav))
        if i < len(segments) - 1:
            audio_parts.append(np.zeros(max(1, round(model.sr * _pause_seconds(key, segment, profile.pause_scale))), dtype=np.float32))
    merged = np.concatenate(audio_parts) if audio_parts else np.zeros(1, dtype=np.float32)
    return _wav_bytes(merged, model.sr), key

@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "device": _device(),
        "english_model_loaded": _english_model is not None,
        "multilingual_model_loaded": _multilingual_model is not None,
        "languages": ["en", "pt-BR"],
    }

@app.get("/profiles")
def profiles() -> dict:
    return {key: asdict(value) for key, value in EMOTION_PROFILES.items()}

@app.post("/synthesize")
async def synthesize(request: SynthesizeRequest):
    try:
        audio, key = await asyncio.to_thread(
            _synthesize_sync,
            request.text,
            request.style,
            request.language,
            None,
            request.model_dump(exclude_none=True),
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return Response(content=audio, media_type="audio/wav", headers={"x-tts-engine":"chatterbox","x-tts-profile":key})

@app.post("/synthesize-upload")
async def synthesize_upload(
    text: str = Form(...),
    style: str = Form("Warm"),
    language: str = Form("en"),
    reference: UploadFile = File(...),
    exaggeration: float | None = Form(None),
    cfg_weight: float | None = Form(None),
    temperature: float | None = Form(None),
):
    suffix = Path(reference.filename or "reference.wav").suffix.lower()
    if suffix not in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
        raise HTTPException(400, "Unsupported reference audio type")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(await reference.read()); temp_path = tmp.name
        audio, key = await asyncio.to_thread(
            _synthesize_sync,
            text,
            style,
            language,
            temp_path,
            {"exaggeration":exaggeration,"cfg_weight":cfg_weight,"temperature":temperature},
        )
    except Exception as exc:
        raise HTTPException(500, str(exc))
    finally:
        if temp_path: Path(temp_path).unlink(missing_ok=True)
    return Response(content=audio, media_type="audio/wav", headers={"x-tts-engine":"chatterbox","x-tts-profile":key})
