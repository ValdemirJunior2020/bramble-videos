from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    comfyui_url: str = "http://127.0.0.1:8188"
    comfyui_path: str = r"C:\Users\nobody\Documents\comfy\ComfyUI"
    comfyui_checkpoint: str = ""
    chatterbox_url: str = "http://127.0.0.1:8001"
    storage_root: str = "storage"
    narration_speed: float = 0.90
    default_style: str = "warm 3D claymation, soft natural colors, cinematic children's animation, gentle lighting"
    reference_denoise: float = 0.48
    ffmpeg_encoder: str = "auto"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def storage_path(self) -> Path:
        p = Path(self.storage_root); p.mkdir(parents=True, exist_ok=True); return p
    @property
    def assets_path(self) -> Path:
        p = self.storage_path / "assets"; p.mkdir(parents=True, exist_ok=True); return p
    @property
    def projects_path(self) -> Path:
        p = self.storage_path / "projects"; p.mkdir(parents=True, exist_ok=True); return p
    @property
    def uploads_path(self) -> Path:
        p = self.storage_path / "uploads"; p.mkdir(parents=True, exist_ok=True); return p

settings = Settings()
