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
        # gfx1200 / 16 GB safe native AI sizes. Bramble upscales/crops during
        # final FFmpeg finishing, so these do not change the requested output size.
        "16:9": (512, 288),
        "9:16": (288, 512),
        "1:1": (384, 384),
        "4:5": (384, 480),
    }.get(aspect, (min(custom_width or 512, 512), min(custom_height or 288, 512)))


def split_duration(seconds: float, max_shot_seconds: float = 2.5) -> list[float]:
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
