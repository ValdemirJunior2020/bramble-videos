from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from fastapi import UploadFile

from .config import settings
from .models import Asset

DEFAULT_ASSETS: list[Asset] = [
    Asset(id="char-bramble", name="Bramble", type="character", aliases=["bramble the bear"], description="Gentle caregiver and father figure; a large grizzly bear.", traits="large pear-shaped soft brown grizzly bear, chunky knitted mustard-yellow scarf, gentle smiling eyes, warm protective expression"),
    Asset(id="char-grace", name="Grace", type="character", aliases=["grace girl"], description="Compassionate six-year-old girl and heart of the group.", traits="6-year-old girl, curly auburn hair in two low buns, large brown eyes, blue denim overall dress, light blue shirt, green rain boots, kind expressive face"),
    Asset(id="char-pip", name="Pip", type="character", aliases=["pip squirrel"], description="Tiny curious red squirrel full of joyful energy.", traits="tiny copper-red squirrel, round springy silhouette, huge bushy tail, green aviator cap, wide excited eyes"),
    Asset(id="char-oliver", name="Oliver", type="character", aliases=["oliver owl"], description="Precise thoughtful barn owl who values wisdom and honesty.", traits="wise beige-and-white barn owl, tall oval silhouette, oversized round reading glasses, brown buttoned vest, thoughtful amber eyes"),
    Asset(id="char-barnaby", name="Barnaby", type="character", aliases=["barnaby turtle"], description="Shy box turtle who models forgiveness and peace.", traits="small box turtle, green-brown domed shell with painted flower details, tiny red bow tie, shy sweet eyes"),
    Asset(id="loc-meadowood", name="Meadowood", type="location", aliases=["forest", "meadow"], traits="peaceful Meadowood forest, soft wildflowers, rolling green hills, warm natural sunlight, safe low-stimulation environment"),
    Asset(id="loc-garden-gate", name="Garden Gate", type="location", aliases=["gate", "overgrown gate"], traits="old woven wooden garden gate between mossy stone walls, gentle vines, warm meadow beyond"),
    Asset(id="loc-great-oak", name="Great Oak", type="location", aliases=["oak", "oak tree"], traits="enormous ancient oak tree with mossy roots and a tiny round wooden library door at its base"),
    Asset(id="loc-stream", name="The Stream", type="location", aliases=["stream", "creek"], traits="shallow clear stream over smooth pebbles, grassy banks, calm meadow light"),
    Asset(id="loc-bramble-cave", name="Bramble's Cave", type="location", aliases=["Bramble’s Cave", "cave", "Bramble cave"], traits="cozy safe woodland cave home with warm amber light, rounded stone walls, simple wooden furniture, mustard textiles and a calm welcoming feeling"),
]

def _db_path() -> Path:
    return settings.assets_path / "assets.json"

def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or uuid4().hex[:10]

def save_assets(items: Iterable[Asset]) -> None:
    _db_path().write_text(json.dumps([x.model_dump() for x in items], indent=2, ensure_ascii=False), encoding="utf-8")

def load_assets() -> list[Asset]:
    path = _db_path()
    if not path.exists():
        save_assets(DEFAULT_ASSETS)
        return [a.model_copy(deep=True) for a in DEFAULT_ASSETS]
    try:
        items = [Asset.model_validate(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    except Exception:
        items = []
    existing = {a.name.lower() for a in items}
    changed = False
    for asset in DEFAULT_ASSETS:
        if asset.name.lower() not in existing:
            items.append(asset.model_copy(deep=True))
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
        existing.aliases = sorted(set([*existing.aliases, *parsed]))
        existing.description = description.strip() or existing.description
        existing.traits = traits.strip() or existing.traits
        asset = existing
    else:
        asset = Asset(id=asset_id, name=name.strip(), type=asset_type, aliases=parsed, description=description.strip(), traits=traits.strip(), image_paths=[str(target)])
        items.append(asset)
    save_assets(items)
    return asset

def delete_asset(asset_id: str) -> bool:
    items = load_assets()
    target = next((a for a in items if a.id == asset_id), None)
    if not target:
        return False
    if any(d.id == target.id for d in DEFAULT_ASSETS):
        target.image_paths = []
        save_assets(items)
    else:
        items = [a for a in items if a.id != asset_id]
        save_assets(items)
    folder = settings.assets_path / asset_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    return True
