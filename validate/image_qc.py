from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImageCheck:
    issues: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    size_bytes: int = 0


@dataclass
class ImageDiff:
    issues: list[str] = field(default_factory=list)
    rms: float | None = None
    changed_pixel_ratio: float | None = None


def inspect_image(path: Path) -> ImageCheck:
    if not path.exists():
        return ImageCheck(["image_file_missing"])
    size = path.stat().st_size
    if size == 0:
        return ImageCheck(["image_file_empty"], size_bytes=0)
    issues: list[str] = []
    if size < 2048:
        issues.append("image_file_very_small_lt_2kb")
    try:
        from PIL import Image, ImageStat
    except Exception:
        return ImageCheck(issues, size_bytes=size)
    try:
        with Image.open(path) as image:
            width, height = image.size
            if width < 200 or height < 150:
                issues.append("image_dimensions_too_small")
            sample = image.convert("L").resize((64, 64))
            stat = ImageStat.Stat(sample)
            mean = stat.mean[0]
            stddev = stat.stddev[0]
            if stddev < 3:
                issues.append("image_nearly_solid_color")
            if mean > 248:
                issues.append("image_nearly_all_white")
            if mean < 7:
                issues.append("image_nearly_all_black")
            return ImageCheck(issues, width=width, height=height, size_bytes=size)
    except Exception:
        issues.append("image_decode_failed")
        return ImageCheck(issues, size_bytes=size)


def compare_images(src: Path, dst: Path, *, size: tuple[int, int] = (256, 256), low_rms: float = 0.005) -> ImageDiff:
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:
        return ImageDiff(["image_diff_pillow_unavailable"])
    try:
        with Image.open(src) as a_raw, Image.open(dst) as b_raw:
            a = a_raw.convert("RGB").resize(size)
            b = b_raw.convert("RGB").resize(size)
            diff = ImageChops.difference(a, b)
            stat = ImageStat.Stat(diff)
            rms = sum(v * v for v in stat.rms) ** 0.5 / (255 * (len(stat.rms) ** 0.5))
            gray = diff.convert("L")
            changed = sum(1 for px in gray.getdata() if px > 3)
            ratio = changed / (size[0] * size[1])
            issues = []
            if rms < low_rms:
                issues.append("image_repair_near_identical_lt_0_005")
            return ImageDiff(issues, rms=round(rms, 6), changed_pixel_ratio=round(ratio, 6))
    except Exception as exc:  # noqa: BLE001
        return ImageDiff([f"image_diff_failed:{type(exc).__name__}"])
