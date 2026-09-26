"""Local rendering of therapist-approved tutorial media; never calls a cloud service."""

import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from app import db
from app.config import DATA_DIR, TUTORIAL_MEDIA_DIR
from app.video import FFMPEG, VideoError


def _tts_command() -> str | None:
    configured = os.getenv("RM_TTS_BIN")
    if configured and shutil.which(configured):
        return configured
    for candidate in ("espeak-ng", "espeak"):
        if shutil.which(candidate):
            return candidate
    return None


def _piper_command() -> str | None:
    configured = os.getenv("RM_PIPER_BIN")
    candidates = [configured] if configured else []
    candidates.extend((str(Path(sys.executable).with_name("piper")), shutil.which("piper")))
    return next((candidate for candidate in candidates if candidate and shutil.which(candidate)), None)


def _piper_model() -> Path | None:
    configured = os.getenv("RM_PIPER_MODEL")
    model = Path(configured) if configured else DATA_DIR / "tts" / "piper" / "en_US-lessac-medium.onnx"
    return model if model.is_file() else None


def _video_dimensions(path: str) -> tuple[int, int]:
    result = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True)
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr)
    return (int(match.group(1)), int(match.group(2))) if match else (1280, 720)



def _short_lines(value: str, max_lines: int = 2, width: int = 56) -> list[str]:
    """Keep burned-in guidance readable without turning it into a text panel."""
    text = " ".join(str(value or "").split())
    if not text:
        return []
    lines = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= max_lines:
        return lines
    remainder = " ".join(lines[max_lines - 1:])
    if len(remainder) > width:
        remainder = remainder[: max(1, width - 1)].rstrip() + "…"
    return [*lines[: max_lines - 1], remainder]


def _ass_text(lines: list[str]) -> str:
    return r"\N".join(line.replace("\\", "\\\\").replace("{", "(").replace("}", ")") for line in lines)


def _write_overlay(tutorial: dict, path: Path, video_width: int = 1280, video_height: int = 720) -> None:
    portrait = video_height > video_width
    wrap_width = 40 if portrait else 58
    caption_margin = round(video_height * (0.126 if portrait else 0.19))
    coaching_margin = round(video_height * (0.076 if portrait else 0.11))
    warning_margin = round(video_height * (0.033 if portrait else 0.04))
    captions = _short_lines(" ".join(tutorial.get("captions") or []) or tutorial.get("script"), width=wrap_width)
    coaching = _short_lines("Coaching: " + " ".join(tutorial.get("coaching_cues") or []), width=wrap_width)
    warnings = _short_lines("Warning: " + " ".join(tutorial.get("warnings") or []), width=wrap_width)
    events = []
    # Keep each message in its own compact lower-third band so the person and pose
    # landmarks remain visible. Larger MarginV values move the band farther up.
    for lines, margin in ((captions, caption_margin), (coaching, coaching_margin), (warnings, warning_margin)):
        if lines:
            events.append(f"Dialogue: 0,0:00:00.00,1:00:00.00,Default,,0,0,{margin},,{_ass_text(lines)}")
    event_text = "\n".join(events)
    path.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "WrapStyle: 2\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,DejaVu Sans,22,&H00F8FBFF,&H00F8FBFF,&H88152B43,&H78152B43,0,0,0,0,100,100,0,0,1,2,0,2,{round(video_width * 0.06)},{round(video_width * 0.06)},28,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"{event_text}\n",
        encoding="utf-8",
    )


def _voice(text: str, output: Path) -> str:
    piper = _piper_command()
    model = _piper_model()
    if piper and model:
        try:
            result = subprocess.run(
                [piper, "--model", str(model), "--output_file", str(output)],
                input=text + "\n", capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and output.is_file():
                return "generated"
        except (OSError, subprocess.SubprocessError):
            pass
    command = _tts_command()
    if not command:
        return "unavailable"
    try:
        result = subprocess.run([command, "-w", str(output), text], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "failed"
    if result.returncode or not output.is_file():
        return "failed"
    return "generated"


def render_tutorial_media(tutorial_id: str, voice_enabled: bool = False) -> tuple[Path, str]:
    tutorial = db.one("SELECT * FROM tutorials WHERE id=?", tutorial_id)
    if not tutorial:
        raise VideoError("No such tutorial")
    reference = db.one("SELECT * FROM reference_videos WHERE id=? AND approval_status='approved'", tutorial["reference_video_id"])
    if not reference or not Path(reference["path"]).is_file():
        raise VideoError("Approved reference video is not available")
    TUTORIAL_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    target_dir = TUTORIAL_MEDIA_DIR / tutorial_id
    target_dir.mkdir(parents=True, exist_ok=True)
    overlay = target_dir / "captions.ass"
    video_width, video_height = _video_dimensions(reference["path"])
    _write_overlay({**tutorial, **{
        "coaching_cues": db.loads(tutorial["coaching_cues_json"]),
        "warnings": db.loads(tutorial["warnings_json"]),
        "captions": db.loads(tutorial["captions_json"]),
    }}, overlay, video_width, video_height)
    output = target_dir / "tutorial.mp4"
    temporary = target_dir / "tutorial.tmp.mp4"
    voice_status = "not_requested"
    voice_file = target_dir / "voice.wav"
    if voice_enabled:
        voice_status = _voice(tutorial["script"], voice_file)
    draw = f"subtitles='{overlay}'"
    command = [FFMPEG, "-y", "-loglevel", "error", "-i", reference["path"]]
    if voice_status == "generated":
        command += ["-i", str(voice_file)]
    command += ["-vf", draw, "-map", "0:v:0"]
    if voice_status == "generated":
        command += ["-map", "1:a:0", "-shortest", "-c:a", "aac", "-b:a", "96k"]
    else:
        command += ["-an"]
    command += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(temporary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode or not temporary.is_file():
        raise VideoError(f"Could not render tutorial media: {result.stderr.strip()[:300]}")
    temporary.replace(output)
    return output, voice_status
