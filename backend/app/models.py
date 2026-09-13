from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator

AssetType = Literal["character", "location", "prop", "group"]
Language = Literal["en", "pt-BR"]
Aspect = Literal["16:9", "9:16", "1:1", "4:5", "custom"]
NarrationStyle = Literal["Calm", "Documentary", "Warm", "Inspirational", "Emotional", "Dramatic", "Sermon"]
SubtitlePosition = Literal["top", "middle", "bottom"]
WatermarkPosition = Literal["top-left", "top-right", "bottom-left", "bottom-right"]
SceneSection = Literal["story", "heart_lesson", "parents"]

class Asset(BaseModel):
    id: str
    name: str
    type: AssetType
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    traits: str = ""
    image_paths: list[str] = Field(default_factory=list)
    approved: bool = True
    voice: str = ""
    voice_style: NarrationStyle = "Warm"
    voice_reference_path: str | None = None
    voice_speed: float = Field(default=1.0, ge=0.70, le=1.30)
    voice_volume: float = Field(default=1.0, ge=0.20, le=2.00)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class AssetVoiceUpdate(BaseModel):
    voice: str = ""
    voice_style: NarrationStyle = "Warm"
    voice_reference_path: str | None = None
    voice_speed: float = Field(default=1.0, ge=0.70, le=1.30)
    voice_volume: float = Field(default=1.0, ge=0.20, le=2.00)

class Scene(BaseModel):
    scene_number: int = Field(ge=1)
    narration: str = Field(min_length=1)
    section_type: SceneSection = "story"
    section_label: str = ""
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
    narration_style: NarrationStyle = "Warm"
    reference_voice_path: str | None = None
    consistency_lock: bool = True
    generate_images: bool = True
    reference_denoise: float | None = Field(default=None, ge=0.15, le=0.95)
    transition: Literal["Gentle Fade", "Cut", "Subtle Zoom"] = "Gentle Fade"
    background_music_path: str | None = None
    music_volume: float = Field(default=0.08, ge=0.0, le=0.5)
    subtitles_enabled: bool = True
    subtitle_font: str = "Arial"
    subtitle_size: int = Field(default=22, ge=8, le=96)
    subtitle_position: SubtitlePosition = "bottom"
    subtitle_color: str = "#FFFFFF"
    subtitle_stroke_color: str = "#000000"
    subtitle_stroke_width: int = Field(default=3, ge=0, le=10)
    watermark_path: str | None = None
    watermark_position: WatermarkPosition = "bottom-right"
    watermark_opacity: float = Field(default=0.75, ge=0.05, le=1.0)
    watermark_width_percent: int = Field(default=14, ge=4, le=40)

    @field_validator("script")
    @classmethod
    def normalize_script(cls, value: str) -> str:
        return value.replace("\r\n", "\n").strip()

    @field_validator("subtitle_color", "subtitle_stroke_color")
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 7 or not value.startswith("#"):
            raise ValueError("Colors must use #RRGGBB")
        int(value[1:], 16)
        return value

class Project(BaseModel):
    id: str
    title: str
    script: str
    language: Language
    aspect: Aspect
    custom_width: int | None = None
    custom_height: int | None = None
    voice: str = ""
    narration_style: NarrationStyle = "Warm"
    reference_voice_path: str | None = None
    consistency_lock: bool = True
    generate_images: bool = True
    reference_denoise: float | None = None
    transition: str = "Gentle Fade"
    background_music_path: str | None = None
    music_volume: float = 0.08
    subtitles_enabled: bool = True
    subtitle_font: str = "Arial"
    subtitle_size: int = 22
    subtitle_position: SubtitlePosition = "bottom"
    subtitle_color: str = "#FFFFFF"
    subtitle_stroke_color: str = "#000000"
    subtitle_stroke_width: int = 3
    watermark_path: str | None = None
    watermark_position: WatermarkPosition = "bottom-right"
    watermark_opacity: float = 0.75
    watermark_width_percent: int = 14
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
