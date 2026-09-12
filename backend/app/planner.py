from __future__ import annotations

import json
import re
import httpx
from .assets import load_assets, recognized_names
from .config import settings
from .models import ProjectCreate, Scene

MASTER_NEGATIVE = "ugly, deformed, mutated, extra limbs, bad anatomy, duplicate character, wrong character, wrong clothing, text, watermark, signature, scary, aggressive, hyper-saturated, neon colors, glowing eyes, blurry, low quality, low resolution, jpeg artifacts, flat lighting, random unrelated person, wrong environment, old church art, statue, icon, manuscript"
PRONOUN_PATTERN = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|ele|ela|eles|elas|dele|dela|deles|delas)\b", re.I)

def segment_script(script: str, target_words: int = 28, max_words: int = 40) -> list[str]:
    text = re.sub(r"\s+", " ", script.strip())
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()] or ([text] if text else [])
    out: list[str] = []
    current: list[str] = []
    count = 0
    for sentence in sentences:
        words = sentence.split()
        if current and (count + len(words) > max_words or count >= target_words):
            out.append(" ".join(current))
            current = []
            count = 0
        if len(words) > max_words:
            if current:
                out.append(" ".join(current))
                current = []
                count = 0
            out.extend(" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words))
            continue
        current.append(sentence)
        count += len(words)
    if current:
        out.append(" ".join(current))
    return out

def _catalog():
    return [{"name": a.name, "type": a.type, "aliases": a.aliases, "description": a.description, "traits": a.traits, "has_reference": bool(a.image_paths)} for a in load_assets()]

def _fallback(narration: str):
    chars = recognized_names(narration, "character")
    locs = recognized_names(narration, "location")
    lower = narration.lower()
    emotion = next((word for word in ["sad", "afraid", "scared", "happy", "grateful", "curious", "worried", "peaceful", "excited", "surprised"] if word in lower), "gentle")
    return {"characters": chars, "location": locs[0] if locs else "", "emotion": emotion, "action": narration[:220]}

async def _annotate(segments: list[str], language: str):
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": "You are the cinematic scene director for Bramble & Grace, a calm low-stimulation premium 3D animated children's series. Analyze every narration segment literally and visually. Never rewrite, translate, shorten, expand, or reorder narration. Return JSON only with key scenes. For each scene return scene_number, characters using only names from the asset catalog, location, emotion, action, and visual_description. The image MUST depict what the narration is saying at that exact moment. Do not insert a random character into environment-only narration. Preserve character identity, clothing, colors and continuity. Use child-safe cinematic lighting, depth of field, expressive but gentle facial emotion, high-detail environments, natural composition, and no more than three active characters unless required."},
            {"role": "user", "content": json.dumps({"language": language, "assets": _catalog(), "segments": [{"scene_number": i + 1, "narration": s} for i, s in enumerate(segments)]}, ensure_ascii=False)}
        ],
        "options": {"temperature": 0.12}
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json=body)
        response.raise_for_status()
        data = json.loads(response.json()["message"]["content"])
    return data.get("scenes", [])

def _traits(names: list[str]) -> str:
    by_name = {a.name.lower(): a for a in load_assets()}
    return "; ".join(f"{by_name[n.lower()].name}: {by_name[n.lower()].traits or by_name[n.lower()].description}" for n in names if n.lower() in by_name)

def build_prompt(scene: Scene) -> str:
    parts = [
        settings.default_style,
        "Bramble & Grace premium cinematic 3D animated film frame",
        "high resolution, ultra detailed, polished feature-film quality",
        "physically believable soft lighting, global illumination, volumetric sunlight when appropriate",
        "cinematic depth of field, natural lens perspective, detailed textures",
        "consistent approved character designs and exact facial identity from references",
        "low-stimulation children's scene, soft natural color palette",
        "composition and environment must match the narration literally",
        "subtle facial expression matching the narration",
    ]
    if scene.characters:
        parts.append(_traits(scene.characters))
    else:
        parts.append("environment-focused composition, no people or characters unless the narration clearly requires them")
    if scene.location:
        parts.append(_traits([scene.location]))
        parts.append(f"Location: {scene.location}")
    if scene.action:
        parts.append(f"Exact visual action from narration: {scene.action}")
    if scene.emotion:
        parts.append(f"Emotion and mood: {scene.emotion}")
    parts.append("no written words, logos, captions or watermarks in image")
    return ", ".join(x for x in parts if x)

async def plan_scenes(request: ProjectCreate) -> list[Scene]:
    segments = segment_script(request.script)
    try:
        annotations = await _annotate(segments, request.language)
        by_num = {int(x.get("scene_number", 0)): x for x in annotations if isinstance(x, dict)}
    except Exception:
        by_num = {}
    allowed_chars = {a.name for a in load_assets() if a.type == "character"}
    allowed_locations = {a.name for a in load_assets() if a.type == "location"}
    scenes: list[Scene] = []
    previous_chars: list[str] = []
    previous_location = "Meadowood"
    for i, narration in enumerate(segments, 1):
        fallback = _fallback(narration)
        meta = by_num.get(i, {})
        chars = [x for x in meta.get("characters", fallback["characters"]) if x in allowed_chars]
        explicit_chars = recognized_names(narration, "character")
        for name in explicit_chars:
            if name not in chars:
                chars.append(name)
        if not explicit_chars and not chars and previous_chars and PRONOUN_PATTERN.search(narration):
            chars = previous_chars.copy()
        chars = chars[:3]
        explicit_locations = recognized_names(narration, "location")
        location = meta.get("location") or (explicit_locations[0] if explicit_locations else fallback["location"])
        if location not in allowed_locations:
            location = explicit_locations[0] if explicit_locations else previous_location
        if not explicit_locations and not meta.get("location"):
            location = previous_location
        action = str(meta.get("visual_description") or meta.get("action") or fallback["action"])[:700]
        scene = Scene(scene_number=i, narration=narration, characters=chars, location=location, emotion=str(meta.get("emotion") or fallback["emotion"])[:80], action=action, negative_prompt=MASTER_NEGATIVE)
        scene.image_prompt = build_prompt(scene)
        scenes.append(scene)
        if chars:
            previous_chars = chars.copy()
        if location:
            previous_location = location
    return scenes
