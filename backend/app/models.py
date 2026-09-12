from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator

AssetType = Literal["character", "location", "prop", "group"]
Language = Literal["en", "pt-BR"]
Aspect = Literal["16:9", "9:16", "1:1", "4:5", "custom"]

class Asset(BaseModel):
    id: str
    name: str
    type: AssetType
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    traits: str = ""
    image_paths: list[str] = Field(default_factory=list)
    approved: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Scene(BaseModel):
    scene_number: int = Field(ge=1)
    narration: str = Field(min_length=1)
    characters: list[str] = Field(default_factory=list)
    location: str = ""
    emotion: str = "gentle"
    action: str = ""
    image_prompt: str = ""
    negative_prompt: str = ""
    start_seconds: float = 0.0
    end_seconds: float = 0.0
    duration_seconds: float = 0.0
    image_path: str | None = None

class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    script: str = Field(min_length=1)
    language: Language = "en"
    aspect: Aspect = "16:9"
    custom_width: int | None = Field(default=None, ge=256, le=4096)
    custom_height: int | None = Field(default=None, ge=256, le=4096)
    voice: str = ""
    narration_style: str = "Warm"
    consistency_lock: bool = True
    generate_images: bool = True
    reference_denoise: float | None = Field(default=None, ge=0.15, le=0.95)
    transition: Literal["Gentle Fade", "Cut", "Subtle Zoom"] = "Gentle Fade"
    background_music_path: str | None = None
    music_volume: float = Field(default=0.08, ge=0.0, le=0.5)

    @field_validator("script")
    @classmethod
    def normalize_script(cls, value: str) -> str:
        return value.replace("\r\n", "\n").strip()

class Project(BaseModel):
    id: str
    title: str
    script: str
    language: Language
    aspect: Aspect
    custom_width: int | None = None
    custom_height: int | None = None
    voice: str = ""
    narration_style: str = "Warm"
    consistency_lock: bool = True
    generate_images: bool = True
    reference_denoise: float | None = None
    transition: str = "Gentle Fade"
    background_music_path: str | None = None
    music_volume: float = 0.08
    scenes: list[Scene] = Field(default_factory=list)
    state: Literal["planned", "rendering", "complete", "failed"] = "planned"
    progress: int = 0
    stage: str = "Planned"
    error: str | None = None
    output_path: str | None = None
    subtitle_path: str | None = None
    narration_path: str | None = None
    video_encoder: str | None = None

class SceneUpdate(BaseModel):
    narration: str | None = None
    characters: list[str] | None = None
    location: str | None = None
    emotion: str | None = None
    action: str | None = None
    image_prompt: str | None = None

class RenderRequest(BaseModel):
    regenerate_all_images: bool = False

class VoiceInfo(BaseModel):
    name: str
    culture: str = ""
    gender: str = ""
