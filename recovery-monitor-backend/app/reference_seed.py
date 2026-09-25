"""Reference ("how it should look") clips for all six exercises, cut from REHAB24-6 reps that the dataset's
physiotherapists labelled correct. Safe to run again: exercises that already have a clip are skipped.

    cd recovery-monitor-backend && RM_APP_DATA=... ~/rm-venv/bin/python -m app.reference_seed
"""

import csv
from collections import defaultdict

from app import db
from app.config import REFERENCE_DIR
from app.video import clip

SOURCE = "Public sample data: REHAB24-6 (CC BY-NC 4.0, Černek et al., SISAP 2024)"
EXERCISES = {1: "arm_abduction", 2: "arm_vw", 3: "push_ups", 4: "leg_abduction", 5: "leg_lunge", 6: "squat"}
TITLES = {"arm_abduction": "Arm raise to the side", "arm_vw": "Arm V-W", "push_ups": "Push-ups, hands on a table",
          "leg_abduction": "Leg raise to the side", "leg_lunge": "Lunge", "squat": "Bodyweight squat"}
SIDE_ON = {"squat", "leg_lunge"}  # filmed side-on; the rest face the camera (matches the app's filming advice)
FPS, REPS = 30, 3


def pick(rows: list[dict], exercise: str) -> tuple[str, int, int, str] | None:
    """First video with REPS consecutive correct reps, lights on, nobody else in the chosen camera."""
    by_video = defaultdict(list)
    for r in rows:
        by_video[r["video_id"]].append(r)
    for vid in sorted(by_video):
        reps = sorted(by_video[vid], key=lambda r: int(r["repetition_number"]))
        orient17 = reps[0]["cam17_orientation"]
        # Camera 17's angle is labelled (front / half-profile / profile). When it faces the person, camera 18
        # films them from the side, which is what squats and lunges need.
        if exercise in SIDE_ON:
            if orient17 != "front":
                continue
            cam = 18
        elif exercise == "push_ups":
            cam = 17
        else:
            if orient17 != "front":
                continue
            cam = 17
        for i in range(len(reps) - REPS + 1):
            run = reps[i:i + REPS]
            if all(r["correctness"] == "1" and r["lights_on"] == "1" and r[f"extra_person_in_cam{cam}"] == "0"
                   and r["mocap_erroneous"] == "0" for r in run):
                view = "side" if exercise in SIDE_ON or exercise == "push_ups" else "front"
                return vid, int(run[0]["first_frame"]), int(run[-1]["last_frame"]), f"{cam}:{view}"
    return None


def main():
    from model.config import SEGMENTATION, VIDEOS

    rows = list(csv.DictReader(open(SEGMENTATION), delimiter=";"))
    have = {r["exercise"] for r in db.all_("SELECT exercise FROM reference_videos")}
    for ex_id, exercise in EXERCISES.items():
        if exercise in have:
            print(f"{exercise}: already has a reference clip")
            continue
        found = pick([r for r in rows if r["exercise_id"] == str(ex_id)], exercise)
        if not found:
            print(f"{exercise}: no clean run of {REPS} correct reps found")
            continue
        vid, first, last, cam_view = found
        cam, view = cam_view.split(":")
        src = VIDEOS / f"Ex{ex_id}" / (f"{vid}-Camera17-30fps.mp4" if cam == "17" else f"{vid}-Camera18-30fps-transposed.mp4")
        folder = REFERENCE_DIR / f"demo-{exercise}"
        folder.mkdir(parents=True, exist_ok=True)
        clip(src, folder / "video.mp4", max(0, first / FPS - 0.4), last / FPS + 0.4)
        title = f"{TITLES[exercise]}, {'side' if view == 'side' else 'front'} view: {REPS} correct reps"
        with db.tx() as c:
            c.execute("INSERT INTO reference_videos (exercise, title, path, source, created_at) VALUES (?,?,?,?,?)",
                      (exercise, title, str(folder / "video.mp4"), SOURCE, db.now()))
        print(f"{exercise}: {title} ({vid}, camera {cam}, frames {first}-{last})")


if __name__ == "__main__":
    main()
