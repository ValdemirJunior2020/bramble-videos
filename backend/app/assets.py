from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from fastapi import UploadFile

from .config import settings
from .models import Asset, AssetVoiceUpdate

DEFAULT_ASSETS: list[Asset] = [
    Asset(
        id="char-bramble", name="Bramble", type="character", aliases=["bramble turtle"],
        description="Gentle turtle with a flower-painted shell and red bow tie.",
        traits="stylized olive-green turtle, large warm brown eyes, rounded gentle face, flower-painted shell, red bow tie, premium children's 3D character design",
        species="turtle", canonical_outfit="red bow tie; flower-painted shell",
        forbidden_traits=["fur", "bear ears", "squirrel tail", "owl feathers", "human skin", "extra shell", "duplicate head", "split body"],
        voice_style="Warm", voice_speed=0.92,
    ),
    Asset(
        id="char-grace", name="Grace", type="character", aliases=["grace girl"],
        description="Compassionate human girl and heart of the group.",
        traits="young human girl, curly auburn-red hair, large warm brown eyes, light freckles, light blue short-sleeve shirt, blue denim overalls, soft stylized children's 3D face",
        species="human", canonical_outfit="light blue short-sleeve shirt; blue denim overalls",
        forbidden_traits=["animal ears", "tail", "fur", "muzzle", "whiskers", "beak", "feathers", "shell", "paws", "hybrid animal features"],
        voice_style="Emotional", voice_speed=1.02,
    ),
    Asset(
        id="char-pip", name="Pip", type="character", aliases=["pip squirrel"],
        description="Curious stylized orange-red squirrel with a locked green aviator outfit.",
        traits="stylized orange-red squirrel, huge round dark eyes, cream muzzle and belly, one fluffy squirrel tail, muted green aviator cap with ear flaps, muted green outfit, cute rounded children's 3D proportions",
        species="squirrel", canonical_outfit="muted green aviator cap with ear flaps; muted green outfit",
        forbidden_traits=["human skin", "human hair", "human child body", "missing hat", "missing green outfit", "extra tail", "detached tail", "floating tail", "duplicate body", "split body"],
        voice_style="Inspirational", voice_speed=1.08,
    ),
    Asset(
        id="char-oliver", name="Oliver", type="character", aliases=["oliver owl"],
        description="Thoughtful barn owl with round glasses and a brown vest.",
        traits="stylized cream-and-golden barn owl, heart-shaped owl face, amber eyes, oversized round glasses, brown buttoned vest, soft premium children's 3D design",
        species="barn owl", canonical_outfit="oversized round glasses; brown buttoned vest",
        forbidden_traits=["human face", "human skin", "squirrel tail", "bear muzzle", "turtle shell", "missing glasses", "missing vest", "extra wings", "split body"],
        voice_style="Documentary", voice_speed=0.96,
    ),
    Asset(
        id="char-barnaby", name="Barnaby", type="character", aliases=["barnaby bear"],
        description="Gentle brown bear with a thick mustard-yellow knitted scarf.",
        traits="stylized soft brown bear, rounded bear ears, warm brown eyes, broad gentle muzzle, thick mustard-yellow knitted scarf, premium children's 3D proportions",
        species="brown bear", canonical_outfit="thick mustard-yellow knitted scarf",
        forbidden_traits=["turtle shell", "red bow tie", "squirrel tail", "owl feathers", "human skin", "missing scarf", "extra head", "split body"],
        voice_style="Calm", voice_speed=0.90,
    ),
    Asset(id="loc-meadowood", name="Meadowood", type="location", aliases=["forest", "meadow"], traits="peaceful Meadowood forest, soft wildflowers, rolling green hills, warm natural sunlight, safe low-stimulation environment", identity_lock=False),
    Asset(id="loc-garden-gate", name="Garden Gate", type="location", aliases=["gate", "overgrown gate"], traits="rustic woven wooden garden gate between mossy stone walls, climbing vines, warm meadow beyond", identity_lock=False),
    Asset(id="loc-great-oak", name="Great Oak", type="location", aliases=["oak", "oak tree"], traits="enormous ancient mossy oak tree with a tiny round wooden door at its base", identity_lock=False),
    Asset(id="loc-stream", name="The Stream", type="location", aliases=["stream", "creek"], traits="shallow clear stream over smooth pebbles, grassy banks, warm calm meadow light", identity_lock=False),
    Asset(id="loc-bramble-cave", name="Bramble's Cave", type="location", aliases=["Bramble’s Cave", "cave", "Bramble cave"], traits="cozy safe woodland cave home with warm amber light, rounded stone walls, simple wooden furniture and a calm welcoming feeling", identity_lock=False),
]

BUILTIN_IDS = {a.id for a in DEFAULT_ASSETS}


def _db_path() -> Path:
    return settings.assets_path / "assets.json"


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or uuid4().hex[:10]


def save_assets(items: Iterable[Asset]) -> None:
    _db_path().write_text(json.dumps([x.model_dump() for x in items], indent=2, ensure_ascii=False), encoding="utf-8")


def _migrate_builtin(current: Asset, default: Asset) -> bool:
    changed = False
    # Canon is authoritative for built-in Bramble assets; user media/voice settings are preserved.
    for field in ("name", "type", "aliases", "description", "traits", "species", "canonical_outfit", "forbidden_traits", "identity_lock"):
        value = getattr(default, field)
        if getattr(current, field) != value:
            setattr(current, field, value)
            changed = True
    if current.type == "character" and current.voice_style == "Warm" and default.voice_style != "Warm" and not current.voice_reference_path and not current.voice:
        current.voice_style = default.voice_style
        current.voice_speed = default.voice_speed
        changed = True
    valid_images = [p for p in current.image_paths if Path(p).exists()]
    if current.image_paths != valid_images:
        current.image_paths = valid_images
        changed = True
    if current.primary_image_path and current.primary_image_path not in current.image_paths:
        current.primary_image_path = None
        changed = True
    if current.type == "character" and not current.primary_image_path and current.image_paths:
        current.primary_image_path = current.image_paths[0]
        changed = True
    return changed


def load_assets() -> list[Asset]:
    path = _db_path()
    if not path.exists():
        save_assets(DEFAULT_ASSETS)
        return [a.model_copy(deep=True) for a in DEFAULT_ASSETS]
    try:
        items = [Asset.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    except Exception:
        items = []
    by_id = {a.id: a for a in items}
    changed = False
    for default in DEFAULT_ASSETS:
        current = by_id.get(default.id)
        if not current:
            items.append(default.model_copy(deep=True))
            changed = True
        elif _migrate_builtin(current, default):
            changed = True
    # Backward compatibility for custom assets created before primary-image support.
    for asset in items:
        if asset.type == "character" and not asset.primary_image_path and asset.image_paths:
            first = next((p for p in asset.image_paths if Path(p).exists()), None)
            if first:
                asset.primary_image_path = first
                changed = True
    if changed:
        save_assets(items)
    return items


def find_asset(name: str) -> Asset | None:
    key = name.strip().lower()
    return next((a for a in load_assets() if a.name.lower() == key or key in {x.lower() for x in a.aliases}), None)


def recognized_names(text: str, asset_type: str | None = None) -> list[str]:
    lowered = text.lower()
    out: list[str] = []
    for asset in load_assets():
        if asset_type and asset.type != asset_type:
            continue
        if any(re.search(rf"\b{re.escape(x.lower())}\b", lowered) for x in [asset.name, *asset.aliases] if x.strip()):
            out.append(asset.name)
    return out


async def add_reference(name: str, asset_type: str, file: UploadFile, aliases: str = "", description: str = "", traits: str = "") -> Asset:
    items = load_assets()
    existing = next((a for a in items if a.name.lower() == name.strip().lower()), None)
    suffix = Path(file.filename or "reference.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise ValueError("Reference images must be PNG, JPG, JPEG or WEBP")
    asset_id = existing.id if existing else f"{asset_type[:4]}-{_slug(name)}"
    folder = settings.assets_path / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{uuid4().hex[:10]}{suffix}"
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    parsed = [x.strip() for x in aliases.split(",") if x.strip()]
    if existing:
        existing.image_paths.append(str(target))
        if existing.type == "character" and not existing.primary_image_path:
            existing.primary_image_path = str(target)
        existing.aliases = sorted(set([*existing.aliases, *parsed]))
        existing.description = description.strip() or existing.description
        existing.traits = traits.strip() or existing.traits
        asset = existing
    else:
        asset = Asset(
            id=asset_id, name=name.strip(), type=asset_type, aliases=parsed,
            description=description.strip(), traits=traits.strip(), image_paths=[str(target)],
            primary_image_path=str(target) if asset_type == "character" else None,
            identity_lock=asset_type == "character",
        )
        items.append(asset)
    save_assets(items)
    return asset


def set_primary_reference(asset_id: str, index: int) -> Asset | None:
    items = load_assets()
    asset = next((a for a in items if a.id == asset_id), None)
    if not asset:
        return None
    if index < 0 or index >= len(asset.image_paths):
        raise ValueError("Reference index is out of range")
    path = asset.image_paths[index]
    if not Path(path).exists():
        raise ValueError("Reference image no longer exists")
    asset.primary_image_path = path
    asset.identity_lock = True
    save_assets(items)
    return asset


def update_voice_profile(asset_id: str, update: AssetVoiceUpdate) -> Asset | None:
    items = load_assets()
    asset = next((a for a in items if a.id == asset_id), None)
    if not asset or asset.type != "character":
        return None
    data = update.model_dump()
    reference = data.get("voice_reference_path")
    if reference and not Path(reference).exists():
        raise ValueError("Voice reference file no longer exists")
    asset.voice = data["voice"]
    asset.voice_style = data["voice_style"]
    asset.voice_reference_path = reference
    asset.voice_speed = data["voice_speed"]
    asset.voice_volume = data["voice_volume"]
    save_assets(items)
    return asset


def delete_asset(asset_id: str) -> bool:
    items = load_assets()
    target = next((a for a in items if a.id == asset_id), None)
    if not target:
        return False
    if asset_id in BUILTIN_IDS:
        target.image_paths = []
        target.primary_image_path = None
        save_assets(items)
    else:
        items = [a for a in items if a.id != asset_id]
        save_assets(items)
    folder = settings.assets_path / asset_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return True
