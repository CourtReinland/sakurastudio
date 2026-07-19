"""Harvest animation frames from video (ffmpeg) and select a looping window."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageStat


def _mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    d = ImageChops.difference(a, b)
    st = ImageStat.Stat(d)
    return sum(st.mean) / max(1, len(st.mean))


def harvest_frames(
    video_path: Path,
    out_dir: Path,
    *,
    fps: float = 12.0,
) -> list[Path]:
    """Extract dense PNG frames with ffmpeg. Returns sorted frame paths."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found on PATH")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("f*.png"):
        p.unlink()
    pattern = str(out_dir / "f%03d.png")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        pattern,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(out_dir.glob("f*.png"))


def select_cycle_window(
    frames: list[Path],
    *,
    n: int = 8,
    thumb: tuple[int, int] = (120, 160),
) -> tuple[int, list[Path], dict[str, Any]]:
    """
    Pick n consecutive frames with high motion and best loop closure.
    Returns (start_index, selected_paths, metrics).
    """
    if len(frames) < n + 1:
        return 0, frames[:n], {"note": "short clip, took all"}

    thumbs = [Image.open(p).convert("RGBA").resize(thumb) for p in frames]
    diffs = [_mean_abs_diff(thumbs[i], thumbs[i - 1]) for i in range(1, len(thumbs))]

    best: tuple[float, int, float, float] | None = None
    for start in range(0, len(thumbs) - n):
        local = diffs[start : start + n - 1]
        motion = sum(local) / len(local)
        loop = _mean_abs_diff(thumbs[start], thumbs[start + n - 1])
        score = motion - 0.35 * loop
        if best is None or score > best[0]:
            best = (score, start, motion, loop)
    assert best is not None
    start = best[1]
    selected = frames[start : start + n]
    return start, selected, {
        "score": best[0],
        "motion": best[2],
        "loop_distance": best[3],
        "start": start,
        "n": n,
    }


def normalize_frame_canvas(
    src: Path,
    dest: Path,
    *,
    size: tuple[int, int] = (864, 1152),
    bg: tuple[int, int, int, int] = (0, 0, 0, 0),
    feet_bottom: bool = True,
) -> Path:
    """Resize/pad frame onto fixed canvas (transparent by default)."""
    im = Image.open(src).convert("RGBA")
    tw, th = size
    # if has alpha content, crop tight first
    bb = im.split()[-1].getbbox()
    if bb:
        im = im.crop(bb)
    scale = min(tw / im.width, th / im.height) * 0.95
    nw = max(1, int(im.width * scale))
    nh = max(1, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (tw, th), bg)
    x = (tw - nw) // 2
    y = (th - nh) if feet_bottom else (th - nh) // 2
    canvas.paste(im, (x, y), im)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return dest


def make_contact_sheet(frames: list[Path], dest: Path, cell: tuple[int, int] = (108, 144)) -> Path:
    n = len(frames)
    cw, ch = cell
    sheet = Image.new("RGBA", (n * cw, ch), (0, 0, 0, 255))
    for i, p in enumerate(frames):
        im = Image.open(p).convert("RGBA").resize(cell)
        sheet.paste(im, (i * cw, 0), im)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)
    return dest


def video_to_cycle_frames(
    video_bytes: bytes,
    *,
    n_frames: int = 8,
    fps: float = 12.0,
    canvas: tuple[int, int] = (864, 1152),
    work_dir: Path | None = None,
) -> tuple[list[bytes], dict[str, Any]]:
    """
    Full harvest: write video → extract → select window → normalize.
    Returns (list of PNG bytes, metrics).
    """
    tmp_root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="sakura_anim_"))
    tmp_root.mkdir(parents=True, exist_ok=True)
    vid = tmp_root / "clip.mp4"
    vid.write_bytes(video_bytes)
    raw_dir = tmp_root / "raw"
    frames = harvest_frames(vid, raw_dir, fps=fps)
    start, selected, metrics = select_cycle_window(frames, n=n_frames)
    metrics["total_harvested"] = len(frames)
    out_bytes: list[bytes] = []
    sel_dir = tmp_root / "sel"
    sel_dir.mkdir(exist_ok=True)
    paths: list[Path] = []
    for i, p in enumerate(selected):
        dest = sel_dir / f"frame_{i + 1:02d}.png"
        # keep video pixels with transparent-friendly pad; rembg can run outside
        normalize_frame_canvas(p, dest, size=canvas, bg=(18, 12, 36, 255))
        paths.append(dest)
        out_bytes.append(dest.read_bytes())
    contact = tmp_root / "contact.png"
    make_contact_sheet(paths, contact)
    metrics["contact_sheet"] = str(contact)
    metrics["work_dir"] = str(tmp_root)
    return out_bytes, metrics
