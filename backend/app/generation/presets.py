from __future__ import annotations

PRESETS = {
    "fast": {"label": "Fast Preview", "step_scale": 0.65},
    "balanced": {"label": "Balanced Cinematic", "step_scale": 1.0},
    "high": {"label": "High Quality", "step_scale": 1.25},
    "max": {"label": "Maximum Local Quality", "step_scale": 1.45},
}


def apply_preset(defaults: dict, preset: str) -> dict:
    values = dict(defaults or {})
    config = PRESETS.get(preset, PRESETS["balanced"])
    steps = int(values.get("num_inference_steps") or 0)
    if steps > 0:
        values["num_inference_steps"] = max(4, min(steps + 12, round(steps * config["step_scale"])))
    values["override_profile"] = 4
    values["override_attention"] = "sdpa"
    return values


def target_resolution(aspect: str, custom_width: int | None = None, custom_height: int | None = None) -> tuple[int, int]:
    # Conservative native generation sizes for a 16 GB RDNA4 card. Final output is
    # still resized/cropped by Bramble's FFmpeg finishing pipeline.
    return {
        "16:9": (832, 480),
        "9:16": (480, 832),
        "1:1": (640, 640),
        "4:5": (576, 720),
    }.get(aspect, (min(custom_width or 832, 960), min(custom_height or 480, 960)))


def split_duration(seconds: float, max_shot_seconds: float = 6.0) -> list[float]:
    seconds = max(1.0, float(seconds or 1.0))
    if seconds <= max_shot_seconds:
        return [seconds]
    chunks: list[float] = []
    remaining = seconds
    while remaining > max_shot_seconds:
        chunks.append(max_shot_seconds)
        remaining -= max_shot_seconds
    if remaining >= 1.0:
        chunks.append(remaining)
    elif chunks:
        chunks[-1] += remaining
    return chunks
