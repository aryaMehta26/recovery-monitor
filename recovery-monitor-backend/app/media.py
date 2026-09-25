"""Local rendering of therapist-approved tutorial media; never calls a cloud service."""

import os
import shutil
import subprocess
from pathlib import Path

from app import db
from app.config import TUTORIAL_MEDIA_DIR
from app.video import FFMPEG, VideoError


def _tts_command() -> str | None:
    configured = os.getenv("RM_TTS_BIN")
    if configured and shutil.which(configured):
        return configured
    for candidate in ("espeak-ng", "espeak"):
        if shutil.which(candidate):
            return candidate
    return None



def _write_overlay(tutorial: dict, path: Path) -> None:
    coaching = tutorial.get("coaching_cues") or []
    warnings = tutorial.get("warnings") or []
    captions = tutorial.get("captions") or []
    lines = [
        "Recovery Monitor",
        *captions,
        "Guidance: " + tutorial["script"],
        "Coaching: " + " ".join(coaching) if coaching else "",
        "Warnings: " + " ".join(warnings) if warnings else "",
    ]
    text = r"\N".join(line.replace("{", "(").replace("}", ")") for line in lines if line)
    path.write_text(
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1280\n"
        "PlayResY: 720\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,DejaVu Sans,28,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,0,0,0,0,100,100,0,0,1,2,0,2,36,36,28,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,1:00:00.00,Default,,0,0,0,,{text}\n",
        encoding="utf-8",
    )


def _voice(text: str, output: Path) -> str:
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
    _write_overlay({**tutorial, **{
        "coaching_cues": db.loads(tutorial["coaching_cues_json"]),
        "warnings": db.loads(tutorial["warnings_json"]),
        "captions": db.loads(tutorial["captions_json"]),
    }}, overlay)
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
