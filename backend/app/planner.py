from __future__ import annotations

import json
import re

import httpx

from .assets import load_assets, recognized_names
from .config import settings
from .models import ProjectCreate, Scene

MASTER_NEGATIVE = (
    "ugly, deformed, mutated, extra limbs, bad anatomy, duplicate character, "
    "wrong character, wrong clothing, text, watermark, signature, scary, aggressive, "
    "hyper-saturated, neon colors, glowing eyes, blurry, low quality, low resolution, "
    "jpeg artifacts, flat lighting, random unrelated person, wrong environment, old church art, "
    "statue, icon, manuscript, character sheet, turnaround sheet, model sheet, reference sheet, "
    "contact sheet, collage, split screen, multiple views of the same character, front view and back view together, "
    "plain white studio background, isolated reference pose"
)

PRONOUN_PATTERN = re.compile(
    r"\b(he|she|they|him|her|them|his|hers|their|ele|ela|eles|elas|dele|dela|deles|delas)\b",
    re.I,
)


def _chunk_words(text: str, max_words: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _split_sentence(sentence: str, max_words: int = 26) -> list[str]:
    """Split long narration into visual beats instead of 15-20 second mega-scenes."""
    sentence = sentence.strip()
    if len(sentence.split()) <= max_words:
        return [sentence]

    # Prefer natural visual/action boundaries before falling back to word chunks.
    parts = [
        p.strip(" ,;—-")
        for p in re.split(
            r"(?<=[,;:])\s+|\s+[—–-]\s+|\s+(?=(?:but|while|when|then|as|and then)\b)",
            sentence,
            flags=re.I,
        )
        if p.strip(" ,;—-")
    ]

    if len(parts) <= 1:
        return _chunk_words(sentence, max_words)

    out: list[str] = []
    current: list[str] = []
    count = 0
    for part in parts:
        words = len(part.split())
        if current and count + words > max_words:
            out.append(" ".join(current).strip())
            current = []
            count = 0
        if words > max_words:
            if current:
                out.append(" ".join(current).strip())
                current = []
                count = 0
            out.extend(_chunk_words(part, max_words))
        else:
            current.append(part)
            count += words
    if current:
        out.append(" ".join(current).strip())
    return [x for x in out if x]


def segment_script(script: str, max_words: int = 26) -> list[str]:
    """Create short, imageable narration beats so each generated frame matches what is being spoken."""
    text = re.sub(r"\s+", " ", script.strip())
    if not text:
        return []
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    if not sentences:
        sentences = [text]

    out: list[str] = []
    for sentence in sentences:
        out.extend(_split_sentence(sentence, max_words=max_words))
    return out


def _catalog():
    return [
        {
            "name": a.name,
            "type": a.type,
            "aliases": a.aliases,
            "description": a.description,
            "traits": a.traits,
            "has_reference": bool(a.image_paths),
        }
        for a in load_assets()
    ]


def _clean_value(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, list):
        return ", ".join(str(x).strip() for x in value if str(x).strip())
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    return str(value).strip() or default


def _fallback(narration: str):
    chars = recognized_names(narration, "character")
    locs = recognized_names(narration, "location")
    lower = narration.lower()
    emotion = next(
        (
            word
            for word in [
                "sad",
                "afraid",
                "scared",
                "happy",
                "grateful",
                "curious",
                "worried",
                "peaceful",
                "excited",
                "surprised",
                "frustrated",
                "confused",
                "relieved",
            ]
            if word in lower
        ),
        "gentle",
    )
    return {
        "characters": chars,
        "location": locs[0] if locs else "",
        "emotion": emotion,
        "action": narration[:500],
    }


async def _annotate(segments: list[str], language: str):
    system_prompt = """
You are the shot director for Bramble & Grace, a premium calm 3D animated children's film.
Your ONLY job is to turn each supplied narration segment into one literal, visible movie frame.
Never rewrite, translate, shorten, expand, or reorder the narration.
Return JSON only with key \"scenes\".

For every scene return:
- scene_number
- characters: only character names present IN THE FRAME, using only names from the asset catalog
- location: one catalog location when possible
- emotion: short visible emotion
- action: concrete visible physical action happening in this exact spoken beat
- visual_description: one direct camera-ready snapshot of exactly what the viewer should see

STRICT VISUAL GROUNDING RULES:
1. The image must show the main thing being spoken at that exact moment.
2. Put the spoken action/object/environment first. Do not return generic poses.
3. If narration says a vine wraps around Pip, the frame must visibly show vines wrapped around Pip.
4. If narration says Grace watches Pip, show Grace watching Pip, not a portrait of Grace.
5. If narration is environment-only, characters must be [] unless a character is truly visible in the narration.
6. Never describe a character sheet, turnaround sheet, reference board, collage, front/back views, or white studio reference image.
7. Character reference images are identity guidance only. The final scene is a completely new cinematic composition.
8. Keep continuity from previous scenes when pronouns refer to the same character or location.
9. Use no more than three active characters unless the narration clearly requires more.
10. Prefer a single decisive visual moment over trying to show several moments at once.
""".strip()

    body = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "language": language,
                        "assets": _catalog(),
                        "segments": [
                            {"scene_number": i + 1, "narration": s}
                            for i, s in enumerate(segments)
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "options": {"temperature": 0.05},
    }

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json=body,
        )
        response.raise_for_status()
        data = json.loads(response.json()["message"]["content"])
    return data.get("scenes", [])


def _traits(names: list[str]) -> str:
    by_name = {a.name.lower(): a for a in load_assets()}
    return "; ".join(
        f"{by_name[n.lower()].name}: {by_name[n.lower()].traits or by_name[n.lower()].description}"
        for n in names
        if n.lower() in by_name
    )


def build_prompt(scene: Scene) -> str:
    """Put the literal shot before style/identity so SD/ComfyUI prioritizes the story beat."""
    parts: list[str] = []

    if scene.action:
        parts.append(
            "PRIMARY REQUIRED SHOT — depict this exact visible moment and make it the dominant composition: "
            + scene.action
        )
    else:
        parts.append("PRIMARY REQUIRED SHOT — depict the narration literally: " + scene.narration)

    if scene.characters:
        parts.append("Characters physically visible in frame: " + ", ".join(scene.characters))
        traits = _traits(scene.characters)
        if traits:
            parts.append("Character identity only — preserve these traits while creating a NEW pose and NEW full scene: " + traits)
        parts.append(
            "uploaded references are identity guidance only; recreate full bodies, pose, expression and camera angle needed by the story"
        )
    else:
        parts.append(
            "environment-only shot; no people, no animals, no characters, no silhouettes unless the narration explicitly requires them"
        )

    if scene.location:
        loc_traits = _traits([scene.location])
        parts.append(f"Location: {scene.location}")
        if loc_traits:
            parts.append("Location continuity: " + loc_traits)

    if scene.emotion:
        parts.append("Visible emotion/mood: " + scene.emotion)

    parts.extend(
        [
            settings.default_style,
            "Bramble & Grace premium cinematic 3D animated film frame",
            "single coherent story frame, not a character presentation board",
            "high resolution, ultra detailed, polished feature-film quality",
            "natural cinematic composition with clear subject/action readability",
            "physically believable soft lighting, global illumination, volumetric sunlight when appropriate",
            "cinematic depth of field, natural lens perspective, detailed environment textures",
            "soft natural color palette, child-safe, low-stimulation visual design",
            "no written words, logos, captions or watermarks in image",
        ]
    )
    return ", ".join(x for x in parts if x)


async def plan_scenes(request: ProjectCreate) -> list[Scene]:
    segments = segment_script(request.script)
    try:
        annotations = await _annotate(segments, request.language)
        by_num = {
            int(x.get("scene_number", 0)): x
            for x in annotations
            if isinstance(x, dict)
        }
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

        raw_chars = meta.get("characters", fallback["characters"])
        if not isinstance(raw_chars, list):
            raw_chars = [raw_chars] if raw_chars else []
        chars = [x for x in raw_chars if x in allowed_chars]

        explicit_chars = recognized_names(narration, "character")
        for name in explicit_chars:
            if name not in chars:
                chars.append(name)

        # Pronoun continuity only when the model did not identify anyone in this beat.
        if not explicit_chars and not chars and previous_chars and PRONOUN_PATTERN.search(narration):
            chars = previous_chars.copy()
        chars = chars[:3]

        explicit_locations = recognized_names(narration, "location")
        location = _clean_value(meta.get("location")) or (
            explicit_locations[0] if explicit_locations else fallback["location"]
        )
        if location not in allowed_locations:
            location = explicit_locations[0] if explicit_locations else previous_location
        if not explicit_locations and not _clean_value(meta.get("location")):
            location = previous_location

        visual = _clean_value(meta.get("visual_description"))
        action = _clean_value(meta.get("action"))
        exact_action = visual or action or fallback["action"]

        scene = Scene(
            scene_number=i,
            narration=narration,
            characters=chars,
            location=location,
            emotion=_clean_value(meta.get("emotion"), fallback["emotion"])[:120],
            action=exact_action[:900],
            negative_prompt=MASTER_NEGATIVE,
        )
        scene.image_prompt = build_prompt(scene)
        scenes.append(scene)

        if chars:
            previous_chars = chars.copy()
        if location:
            previous_location = location

    return scenes
