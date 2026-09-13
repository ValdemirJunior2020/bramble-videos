from __future__ import annotations

import json
import re

import httpx

from .assets import load_assets, recognized_names
from .config import settings
from .models import ProjectCreate, Scene

MASTER_NEGATIVE = (
    "ugly, deformed, mutated, extra limbs, missing limbs, floating limbs, disconnected body, disconnected torso, "
    "severed body, body cut in half, split body, duplicated torso, duplicated head, two heads, extra head, "
    "multiple bodies for same character, malformed body, bad anatomy, duplicate character, wrong character, "
    "wrong clothing, swapped clothing, mixed clothing, fused character, merged character, face blend, face swap, "
    "hybrid creature, mixed species, human-animal hybrid, animal ears on human, animal tail on human, animal fur on human, "
    "rabbit ears on girl, squirrel ears on girl, owl features on girl, bear features on girl, turtle features on girl, "
    "human nose on animal, human skin on animal, wrong outfit, wrong colors, text, watermark, signature, scary, aggressive, "
    "hyper-saturated, neon colors, glowing eyes, blurry, low quality, low resolution, jpeg artifacts, flat lighting, "
    "random unrelated person, wrong environment, old church art, statue, icon, manuscript, character sheet, turnaround sheet, "
    "model sheet, reference sheet, contact sheet, collage, split screen, multiple views, white studio background"
)

PRONOUN_PATTERN = re.compile(r"\b(he|she|they|him|her|them|his|hers|their|ele|ela|eles|elas|dele|dela|deles|delas)\b", re.I)
OBJECT_FOCUS_PATTERN = re.compile(
    r"^(it was|it looked|there was|there were|ahead stood|before them stood|in front of them stood|"
    r"towering above|nearby stood|the gate|the tree|the path|the stream|the meadow|the cave)",
    re.I,
)
OBJECT_KEYWORDS = {
    "gate", "garden gate", "vine", "vines", "tree", "stream", "path", "meadow", "meadowood",
    "forest", "flowers", "door", "cave", "hill", "sunlight", "sky", "clouds", "grass", "rock",
    "stone", "river", "water", "bush", "arch", "branches", "leaves", "moss",
}
EMOTIONS = [
    "sad", "afraid", "scared", "happy", "grateful", "curious", "worried", "peaceful",
    "excited", "surprised", "gentle", "calm", "awe", "frustrated",
]

SECTION_HEADINGS: dict[str, tuple[str, str]] = {
    "heart lesson": ("heart_lesson", "Heart Lesson"),
    "licao para o coracao": ("heart_lesson", "Lição para o Coração"),
    "for parents: why this story matters": ("parents", "For Parents: Why This Story Matters"),
    "for parents why this story matters": ("parents", "For Parents: Why This Story Matters"),
    "para os pais: por que esta historia e importante": ("parents", "Para os Pais: Por Que Esta História é Importante"),
    "para os pais por que esta historia e importante": ("parents", "Para os Pais: Por Que Esta História é Importante"),
    "a note to parents": ("parents", "A Note to Parents"),
    "uma mensagem aos pais": ("parents", "Uma Mensagem aos Pais"),
    "for parents / para os pais": ("parents", "For Parents / Para os Pais"),
}

CANONICAL_LOCKS = {
    "Grace": (
        "Grace is a human little girl only. She has curly auburn-red hair styled in two low buns, warm light skin, large brown eyes, and freckles. "
        "Her locked default outfit is blue denim overalls over a light blue short-sleeve shirt. She must never have animal ears, tail, whiskers, muzzle, fur, beak, shell, or any non-human features."
    ),
    "Pip": (
        "Pip is a small orange-red squirrel only. He has squirrel ears, squirrel muzzle, whiskers, orange fur, and one fluffy squirrel tail. "
        "His locked default outfit is a muted green aviator hat and muted green outfit. He must never become a human child and must never borrow Grace's face, hair, or clothing."
    ),
    "Bramble": (
        "Bramble is a turtle only. He has a green turtle body and a flower-painted shell with a red bow tie. "
        "He must never become human, squirrel, owl, or bear. Preserve turtle species anatomy and his exact shell style."
    ),
    "Oliver": (
        "Oliver is an owl only. He has a barn-owl style face, feathers, glasses, and a brown vest. "
        "He must never become human or mammal-like. Preserve owl beak, feathers, glasses, and vest."
    ),
    "Barnaby": (
        "Barnaby is a brown bear only. He has bear ears, bear muzzle, brown fur, and a thick yellow scarf. "
        "He must never become human or another animal species. Preserve his scarf and bear anatomy."
    ),
}


def _heading_key(value: str) -> str:
    value = re.sub(r"[*_#]+", "", value).strip().lower()
    value = value.replace("ç", "c").replace("ã", "a").replace("á", "a").replace("â", "a")
    value = value.replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o").replace("ô", "o").replace("ú", "u")
    return re.sub(r"\s+", " ", value).strip()


def _segment_plain(text: str, target_words: int = 24, max_words: int = 34) -> list[str]:
    text = re.sub(r"\s+", " ", text.strip())
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


def segment_script(script: str, target_words: int = 24, max_words: int = 34) -> list[str]:
    """Backward-compatible plain segmentation used by tests and callers."""
    return _segment_plain(script, target_words=target_words, max_words=max_words)


def segment_script_with_sections(script: str) -> list[dict[str, str]]:
    """Preserve the story structure and remove section headings from spoken narration.

    Recognizes the bilingual headings used in the Bramble & Grace story collection.
    Headings themselves are metadata; only the text beneath them is narrated.
    """
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()
    # Help pasted text where a Markdown heading may touch the previous paragraph.
    heading_phrases = [
        "Heart Lesson", "Lição para o Coração", "Licao para o Coracao",
        "For Parents: Why This Story Matters", "Para os Pais: Por Que Esta História é Importante",
        "Para os Pais: Por Que Esta Historia e Importante", "A Note to Parents", "Uma Mensagem aos Pais",
        "For Parents / Para os Pais",
    ]
    for phrase in heading_phrases:
        normalized = re.sub(rf"(?<!^)\s*(\*\*\s*)?({re.escape(phrase)})(\s*\*\*)?", r"\n\2\n", normalized, flags=re.I)

    blocks: list[tuple[str, str, str]] = []
    current_type = "story"
    current_label = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        text = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        if text:
            blocks.append((current_type, current_label, text))
        current_lines = []

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key = _heading_key(line)
        heading = SECTION_HEADINGS.get(key)
        if heading:
            flush()
            current_type, current_label = heading
            continue
        current_lines.append(line)
    flush()

    results: list[dict[str, str]] = []
    for section_type, label, text in blocks:
        if section_type == "heart_lesson":
            pieces = _segment_plain(text, target_words=30, max_words=42)
        elif section_type == "parents":
            pieces = _segment_plain(text, target_words=30, max_words=42)
        else:
            pieces = _segment_plain(text, target_words=24, max_words=34)
        for piece in pieces:
            results.append({"text": piece, "section_type": section_type, "section_label": label})
    return results


def _catalog() -> list[dict]:
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


def _fallback(narration: str) -> dict:
    chars = recognized_names(narration, "character")
    locs = recognized_names(narration, "location")
    lower = narration.lower()
    emotion = next((word for word in EMOTIONS if word in lower), "gentle")
    return {"characters": chars, "location": locs[0] if locs else "", "emotion": emotion, "action": narration[:320]}


def _is_object_or_environment_focus(narration: str) -> bool:
    explicit_chars = recognized_names(narration, "character")
    if explicit_chars:
        return False
    lower = narration.lower().strip()
    if OBJECT_FOCUS_PATTERN.search(lower):
        return True
    object_hits = sum(1 for word in OBJECT_KEYWORDS if word in lower)
    pronoun_hits = 1 if PRONOUN_PATTERN.search(lower) else 0
    speech_hits = sum(1 for word in ["said", "asked", "replied", "shouted", "whispered"] if word in lower)
    action_hits = sum(1 for word in ["walked", "ran", "jumped", "pulled", "grabbed", "looked", "smiled", "sat"] if word in lower)
    return object_hits >= 2 and speech_hits == 0 and action_hits <= 1 and pronoun_hits <= 1


async def _annotate(items: list[dict[str, str]], language: str):
    body = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are the cinematic scene director for Bramble & Grace, a calm low-stimulation premium 3D animated children's series. "
                    "Analyze every narration segment literally and visually. Never rewrite, translate, shorten, expand, or reorder narration. "
                    "Return JSON only with key scenes. For each scene return scene_number, characters using only names from the asset catalog, "
                    "location, emotion, action, and visual_description. The image MUST depict what the narration is saying at that exact moment. "
                    "GRAMMAR IS CRITICAL: bind every adjective and size word to the noun it actually modifies. If narration says 'a tall gate', the GATE is tall, never the character. "
                    "If narration says a small flower, huge tree, rusty gate, long path, dark cave, or wide stream, those properties belong only to that object or location. "
                    "Never transfer an object's height, size, color, age, texture, shape, or condition onto a character. "
                    "For heart_lesson and parents sections, do not literalize abstract teaching language. Use peaceful reflective visuals from the established story world instead. "
                    "Do not insert extra characters into object-focused or environment-focused narration. Only keep characters that are actively visible or necessary. "
                    "Preserve character identity, species, clothing, colors, normal proportions, and continuity. Every character has one intact coherent body. "
                    "Avoid more than two active characters unless clearly required by the narration."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "language": language,
                        "assets": _catalog(),
                        "segments": [
                            {
                                "scene_number": i + 1,
                                "narration": item["text"],
                                "section_type": item["section_type"],
                            }
                            for i, item in enumerate(items)
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "options": {"temperature": 0.05},
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{settings.ollama_url.rstrip('/')}/api/chat", json=body)
        response.raise_for_status()
        data = json.loads(response.json()["message"]["content"])
    return data.get("scenes", [])


def _asset_map() -> dict[str, object]:
    return {a.name.lower(): a for a in load_assets()}


def _traits(names: list[str]) -> str:
    by_name = _asset_map()
    parts: list[str] = []
    for name in names:
        asset = by_name.get(name.lower())
        if not asset:
            continue
        detail = asset.traits or asset.description or "approved uploaded design"
        parts.append(
            f"{asset.name}: keep exact approved face, body type or species, hairstyle or fur, outfit, clothing colors, and proportions from the primary uploaded reference; {detail}"
        )
    return "; ".join(parts)


def _canonical_rules(names: list[str]) -> str:
    rules = [CANONICAL_LOCKS[name] for name in names if name in CANONICAL_LOCKS]
    return " ".join(rules)


def build_prompt(scene: Scene) -> str:
    primary_action = scene.action or scene.narration
    if scene.section_type == "parents":
        parts = [
            "PARENT MESSAGE REFLECTION MODE — create a quiet, reassuring closing visual from the established episode world",
            f"Visual direction: {primary_action}",
            "Do NOT literally illustrate abstract parenting statements, developmental concepts, fear, mistakes, routines, or generic children",
            "Do NOT introduce random parents or children. Prefer the established location after the story, gentle light, stillness, and emotional closure",
        ]
    elif scene.section_type == "heart_lesson":
        parts = [
            "HEART LESSON REFLECTION MODE — this is a calm emotional takeaway, not a new action scene",
            f"Visual direction: {primary_action}",
            "Use familiar characters only if already present in the story and show them peaceful, safe, settled, and reflective",
            "Do NOT literalize abstract moral words. Show the emotional result of the lesson with a simple calm composition",
        ]
    else:
        parts = [
            f"PRIMARY REQUIRED SHOT — depict this exact visible moment and make it the dominant composition: {primary_action}",
            f"Scene narration to match literally: {scene.narration}",
            (
                "STRICT ATTRIBUTE BINDING: adjectives and size words belong only to the noun they describe. "
                "A tall gate means the gate is tall; a large tree means the tree is large; a tiny flower means the flower is tiny. "
                "Never make a character taller, shorter, wider, older, rusted, overgrown, colored, or reshaped because an object or location has that description."
            ),
        ]
    if scene.characters:
        parts.append(f"Only these characters may appear prominently: {', '.join(scene.characters)}")
        parts.append(_traits(scene.characters))
        rules = _canonical_rules(scene.characters)
        if rules:
            parts.append(rules)
        parts.append(
            "ANATOMY LOCK: render exactly one intact coherent body for each named character, with one head attached to one torso and all limbs naturally connected. "
            "Never split a character into upper/lower pieces, never duplicate a torso or head, and never show floating or disconnected body parts."
        )
        parts.append(
            "Never merge characters. Never swap clothing. Never give one character another character's face, hair, fur, body, species traits, or outfit. "
            "Each named character must stay visually separate, recognizable, and in their correct approved clothing."
        )
    else:
        parts.append("Environment or object focused shot. No new characters in frame unless explicitly required by the established story moment.")
    if scene.location:
        location_traits = _traits([scene.location])
        if location_traits:
            parts.append(location_traits)
        parts.append(f"Location: {scene.location}")
    if scene.emotion:
        parts.append(f"Visible emotion and mood: {scene.emotion}")
    parts.extend(
        [
            settings.default_style,
            "Bramble & Grace premium cinematic 3D animated film frame",
            "high resolution, ultra detailed, polished feature-film quality",
            "physically believable soft lighting, global illumination, cinematic depth of field, natural lens perspective, detailed textures",
            "low-stimulation children's scene, soft natural color palette",
            "no written words, logos, captions or watermarks in image",
        ]
    )
    return ", ".join(x for x in parts if x)


async def plan_scenes(request: ProjectCreate) -> list[Scene]:
    items = segment_script_with_sections(request.script)
    if not items:
        return []
    try:
        annotations = await _annotate(items, request.language)
        by_num = {int(x.get("scene_number", 0)): x for x in annotations if isinstance(x, dict)}
    except Exception:
        by_num = {}
    assets = load_assets()
    allowed_chars = {a.name for a in assets if a.type == "character"}
    allowed_locations = {a.name for a in assets if a.type == "location"}
    scenes: list[Scene] = []
    previous_chars: list[str] = []
    previous_location = "Meadowood"

    for i, item in enumerate(items, 1):
        narration = item["text"]
        section_type = item["section_type"]
        section_label = item["section_label"]
        fallback = _fallback(narration)
        meta = by_num.get(i, {})

        if section_type == "parents":
            chars: list[str] = []
            location = previous_location
            emotion = "calm, reassuring, reflective"
            action = (
                f"A peaceful wide closing view of {location} after the story events, warm soft light, gentle stillness, "
                "subtle signs of the completed story moment, no new action, no random people, reassuring emotional closure"
            )
        elif section_type == "heart_lesson":
            chars = previous_chars[:2]
            location = previous_location
            emotion = "warm, peaceful, reflective"
            names = ", ".join(chars) if chars else "the familiar story world"
            action = (
                f"A quiet reflective closing moment with {names} in {location}, calm body language, soft expressions, "
                "gentle warm light, no new conflict, visually expressing safety, connection, and the lesson settling in"
            )
        else:
            explicit_chars = [name for name in recognized_names(narration, "character") if name in allowed_chars]
            meta_chars = [x for x in meta.get("characters", []) if x in allowed_chars]
            object_focus = _is_object_or_environment_focus(narration)
            if explicit_chars:
                chars = explicit_chars.copy()
                for name in meta_chars:
                    if name not in chars:
                        chars.append(name)
            elif object_focus:
                chars = []
            elif meta_chars:
                chars = meta_chars.copy()
            elif previous_chars and PRONOUN_PATTERN.search(narration):
                chars = previous_chars.copy()
            else:
                chars = [x for x in fallback["characters"] if x in allowed_chars]
            chars = chars[:2]
            explicit_locations = recognized_names(narration, "location")
            location = meta.get("location") or (explicit_locations[0] if explicit_locations else fallback["location"])
            if location not in allowed_locations:
                location = explicit_locations[0] if explicit_locations else previous_location
            if not explicit_locations and not meta.get("location"):
                location = previous_location
            action_source = meta.get("visual_description") or meta.get("action") or fallback["action"] or narration
            action = str(action_source)[:700]
            emotion = str(meta.get("emotion") or fallback["emotion"] or "gentle")[:80]

        scene = Scene(
            scene_number=i,
            narration=narration,
            section_type=section_type,
            section_label=section_label,
            characters=chars,
            location=location,
            emotion=emotion,
            action=action,
            negative_prompt=MASTER_NEGATIVE,
        )
        scene.image_prompt = build_prompt(scene)
        scenes.append(scene)
        if section_type == "story" and chars:
            previous_chars = chars.copy()
        if location:
            previous_location = location
    return scenes
