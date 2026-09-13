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
    "random unrelated person, wrong environment, statue, icon, manuscript, character sheet, turnaround sheet, "
    "model sheet, reference sheet, contact sheet, collage, split screen, multiple views, white studio background"
)

BIBLE_NEGATIVE = (
    MASTER_NEGATIVE
    + ", old church painting, medieval church art, stained glass illustration, religious statue, carved icon, illuminated manuscript, "
      "parchment text, modern clothing, modern buildings, modern vehicles, microphones, stage lights, random priests, random monks"
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
    "spiritual revelation": ("heart_lesson", "Spiritual Revelation"),
    "revelacao espiritual": ("heart_lesson", "Revelação Espiritual"),
    "reflection": ("heart_lesson", "Reflection"),
    "reflexao": ("heart_lesson", "Reflexão"),
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

MODE_DIRECTOR = {
    "bramble": (
        "You are the cinematic scene director for Bramble & Grace, a calm low-stimulation premium 3D animated children's series. "
        "Preserve the established Bramble characters and Meadowood continuity."
    ),
    "bible": (
        "You are the cinematic director for a reverent Bible and devotional video series. "
        "Treat Scripture and spiritual narration with dignity. Create cinematic live-action-looking scenes, not church artwork. "
        "Use historically grounded ancient-world environments when people are explicitly present. Prefer environment-only imagery when the narration describes creation, darkness, void, sky, sea, land, light, nature, judgment, or symbolic spiritual concepts. "
        "Never invent a random person merely because the narration is spiritual or abstract."
    ),
    "general": (
        "You are a cinematic scene director for a general-purpose video production tool. "
        "Follow the supplied narration literally without Bramble, Bible, or children's-show assumptions."
    ),
    "custom": (
        "You are a cinematic scene director for a custom video project. "
        "Follow the narration literally and prioritize any uploaded character, location, prop, and style references supplied in the asset catalog."
    ),
}


def _heading_key(value: str) -> str:
    value = re.sub(r"[*_#]+", "", value).strip().lower()
    for old, new in {
        "ç": "c", "ã": "a", "á": "a", "â": "a", "é": "e", "ê": "e", "í": "i",
        "ó": "o", "ô": "o", "ú": "u", "õ": "o",
    }.items():
        value = value.replace(old, new)
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
    return _segment_plain(script, target_words=target_words, max_words=max_words)


def segment_script_with_sections(script: str) -> list[dict[str, str]]:
    normalized = script.replace("\r\n", "\n").replace("\r", "\n").strip()
    heading_phrases = [
        "Heart Lesson", "Lição para o Coração", "Licao para o Coracao",
        "Spiritual Revelation", "Revelação Espiritual", "Revelacao Espiritual", "Reflection", "Reflexão", "Reflexao",
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
        heading = SECTION_HEADINGS.get(_heading_key(line))
        if heading:
            flush()
            current_type, current_label = heading
            continue
        current_lines.append(line)
    flush()

    results: list[dict[str, str]] = []
    for section_type, label, text in blocks:
        if section_type in {"heart_lesson", "parents"}:
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
    return {"characters": chars, "location": locs[0] if locs else "", "emotion": emotion, "action": narration[:420]}


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


async def _annotate(items: list[dict[str, str]], language: str, project_mode: str):
    director = MODE_DIRECTOR.get(project_mode, MODE_DIRECTOR["general"])
    mode_rules = (
        "For Bramble heart_lesson and parents sections, use peaceful reflective visuals instead of literal abstract teaching imagery. "
        if project_mode == "bramble"
        else ""
    )
    if project_mode == "bible":
        mode_rules += (
            "Never depict a generic church, cathedral, statue, icon, manuscript, priest, or modern worship scene unless explicitly requested. "
            "When narration says the earth was formless, empty, dark, or describes creation before people exist, show only the environment with no human figure. "
            "Do not add halos, glowing eyes, text, captions, or fantasy religious symbols."
        )

    body = {
        "model": settings.ollama_model,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": (
                    director
                    + " Analyze every narration segment literally and visually. Never rewrite, translate, shorten, expand, or reorder narration. "
                    "Return JSON only with key scenes. For each scene return scene_number, characters using only names from the asset catalog when a saved asset matches, "
                    "location, emotion, action, and visual_description. The image MUST depict what the narration is saying at that exact moment. "
                    "GRAMMAR IS CRITICAL: bind every adjective and size word to the noun it actually modifies. If narration says 'a tall gate', the GATE is tall, never the character. "
                    "Never transfer an object's height, size, color, age, texture, shape, or condition onto a character. "
                    "Do not insert extra people or characters into object-focused or environment-focused narration. "
                    "Preserve uploaded character identity, species, clothing, colors, normal proportions, and continuity. Every visible character has one intact coherent body. "
                    + mode_rules
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project_mode": project_mode,
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
        "options": {"temperature": 0.04},
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
    return " ".join(CANONICAL_LOCKS[name] for name in names if name in CANONICAL_LOCKS)


def build_prompt(scene: Scene) -> str:
    mode = getattr(scene, "project_mode", "bramble") or "bramble"
    primary_action = scene.action or scene.narration

    if mode == "bible":
        parts = [
            f"PRIMARY REQUIRED SHOT — faithfully visualize this exact Bible/devotional moment: {primary_action}",
            f"Narration to match literally: {scene.narration}",
            "cinematic live-action look, reverent and emotionally grounded, photorealistic natural environments, dramatic but believable light, filmic depth of field",
            "historically plausible ancient Near Eastern clothing and architecture only when people or settlements are explicitly required",
            "environment-first composition when narration describes creation, darkness, void, light, sky, water, land, wilderness, mountains, sea, stars, or symbolic spiritual themes",
            "no random person in environment-only scenes, no old church-art style, no statues, no icons, no illuminated manuscripts, no stained-glass look, no modern objects",
            "no text, Bible verses, captions, logos, or watermarks inside the generated image",
        ]
        if scene.section_type == "heart_lesson":
            parts.insert(0, "SPIRITUAL REVELATION MODE — slow, contemplative, peaceful visual with room for reflection")
    elif mode == "bramble":
        if scene.section_type == "parents":
            parts = [
                "PARENT MESSAGE REFLECTION MODE — create a quiet, reassuring closing visual from the established episode world",
                f"Visual direction: {primary_action}",
                "Do NOT literally illustrate abstract parenting statements or generic children",
            ]
        elif scene.section_type == "heart_lesson":
            parts = [
                "HEART LESSON REFLECTION MODE — this is a calm emotional takeaway, not a new action scene",
                f"Visual direction: {primary_action}",
                "Use familiar characters only if already present and show them peaceful, safe, settled, and reflective",
            ]
        else:
            parts = [
                f"PRIMARY REQUIRED SHOT — depict this exact visible moment and make it the dominant composition: {primary_action}",
                f"Scene narration to match literally: {scene.narration}",
                "STRICT ATTRIBUTE BINDING: adjectives and size words belong only to the noun they describe. A tall gate means the gate is tall; never make a character tall because the gate is tall.",
            ]
    else:
        label = "CUSTOM PROJECT" if mode == "custom" else "GENERAL VIDEO"
        parts = [
            f"{label} — depict this exact visible moment: {primary_action}",
            f"Narration to match literally: {scene.narration}",
            "cinematic professional composition, natural anatomy, coherent scene, accurate subject-object relationships",
            "do not import Bramble characters, Meadowood, Bible imagery, church art, or children's-show styling unless the script or uploaded references explicitly ask for it",
        ]

    if scene.characters:
        parts.append(f"Only these saved reference characters may appear prominently: {', '.join(scene.characters)}")
        parts.append(_traits(scene.characters))
        if mode == "bramble":
            rules = _canonical_rules(scene.characters)
            if rules:
                parts.append(rules)
        parts.append(
            "ANATOMY LOCK: exactly one intact coherent body per visible character, one head attached to one torso, natural connected limbs, no duplicated body parts, no split bodies."
        )
        parts.append("Never merge characters, swap clothing, or transfer anatomy, species traits, faces, hair, fur, or outfits between characters.")
    elif mode != "bible":
        parts.append("No extra characters in frame unless the narration explicitly requires them.")

    if scene.location:
        location_traits = _traits([scene.location])
        if location_traits:
            parts.append(location_traits)
        parts.append(f"Location: {scene.location}")
    if scene.emotion:
        parts.append(f"Visible emotion and mood: {scene.emotion}")

    if mode == "bramble":
        parts.extend([
            settings.default_style,
            "Bramble & Grace premium cinematic 3D animated film frame",
            "high resolution, polished feature-film quality, physically believable soft lighting, global illumination",
            "low-stimulation children's scene, soft natural color palette, no written words, logos, captions or watermarks",
        ])
    elif mode == "bible":
        parts.extend([
            "high resolution, premium cinematic live-action frame, realistic textures, natural skin and fabric, volumetric atmosphere where appropriate",
            "serious reverent tone without horror, kitsch, fantasy glow, or church-decoration aesthetics",
        ])
    else:
        parts.extend([
            "high resolution, polished cinematic frame, realistic composition, detailed textures, professional lighting",
            "no written words, logos, captions or watermarks unless explicitly requested by the script",
        ])

    return ", ".join(x for x in parts if x)


async def plan_scenes(request: ProjectCreate) -> list[Scene]:
    items = segment_script_with_sections(request.script)
    if not items:
        return []
    try:
        annotations = await _annotate(items, request.language, request.project_mode)
        by_num = {int(x.get("scene_number", 0)): x for x in annotations if isinstance(x, dict)}
    except Exception:
        by_num = {}

    assets = load_assets()
    allowed_chars = {a.name for a in assets if a.type == "character"}
    allowed_locations = {a.name for a in assets if a.type == "location"}
    scenes: list[Scene] = []
    previous_chars: list[str] = []
    previous_location = "Meadowood" if request.project_mode == "bramble" else ""

    for i, item in enumerate(items, 1):
        narration = item["text"]
        section_type = item["section_type"]
        section_label = item["section_label"]
        fallback = _fallback(narration)
        meta = by_num.get(i, {})

        if request.project_mode == "bramble" and section_type == "parents":
            chars: list[str] = []
            location = previous_location
            emotion = "calm, reassuring, reflective"
            action = f"A peaceful wide closing view of {location or 'the established story world'}, warm soft light, gentle stillness, reassuring emotional closure"
        elif request.project_mode == "bramble" and section_type == "heart_lesson":
            chars = previous_chars[:2]
            location = previous_location
            emotion = "warm, peaceful, reflective"
            names = ", ".join(chars) if chars else "the familiar story world"
            action = f"A quiet reflective closing moment with {names} in {location or 'the established setting'}, calm body language, soft expressions, warm gentle light"
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
            if allowed_locations and location not in allowed_locations:
                location = explicit_locations[0] if explicit_locations else previous_location
            if not location:
                location = previous_location

            action_source = meta.get("visual_description") or meta.get("action") or fallback["action"] or narration
            action = str(action_source)[:900]
            emotion = str(meta.get("emotion") or fallback["emotion"] or "gentle")[:100]

            if request.project_mode == "bible" and section_type == "heart_lesson":
                chars = []
                emotion = "reverent, peaceful, contemplative"
                action = f"A contemplative visual echo of the Scripture scene just described, peaceful atmosphere, room for spiritual reflection: {action}"

        scene = Scene(
            scene_number=i,
            narration=narration,
            project_mode=request.project_mode,
            section_type=section_type,
            section_label=section_label,
            characters=chars,
            location=location,
            emotion=emotion,
            action=action,
            negative_prompt=BIBLE_NEGATIVE if request.project_mode == "bible" else MASTER_NEGATIVE,
        )
        scene.image_prompt = build_prompt(scene)
        scenes.append(scene)
        if section_type == "story" and chars:
            previous_chars = chars.copy()
        if location:
            previous_location = location

    return scenes
