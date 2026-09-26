# Recovery Monitor: Presentation and Demo Guide

## One-sentence description

Recovery Monitor is a privacy-first rehabilitation assistant that runs movement analysis, voice notes, local AI summaries, and therapist-reviewed exercise tutorials on an HP ZGX Nano instead of sending patient data to the cloud.

## The problem

Patients often exercise between physiotherapy visits without reliable feedback. Therapists need more than a raw video: they need movement measurements, patient-reported symptoms, and a safe way to review and personalize guidance.

## The solution

1. A patient records an exercise video and optionally describes how it felt by text or voice.
2. The Nano analyzes pose, repetitions, depth/range of motion, form, quality, and possible flags locally.
3. The therapist reviews the evidence and patient check-in.
4. A local AI assistant creates a tutorial draft from verified measurements and patient comments.
5. The therapist edits, requests changes, or approves the tutorial.
6. The system renders an optional captioned tutorial video using the approved reference video.
7. Optional local voice guidance reads the approved instruction script.
8. The patient receives only therapist-approved tutorial content.

## Why edge AI matters

- Patient videos and health comments stay on the HP ZGX Nano.
- The workflow continues to work without cloud AI access.
- Video analysis, speech recognition, local LLM drafting, and tutorial rendering happen on-device.
- The therapist remains the decision-maker; AI produces evidence and drafts, not autonomous treatment decisions.
- The device can provide feedback close to where the patient records the exercise.

## What is completed

### Product workflow

- Patient and therapist sign-in flows.
- Patient onboarding and issue intake.
- Therapist specialization and patient-care assignment workflow.
- Therapist patient-request acceptance or decline.
- Patient dashboard with assigned therapist visibility.
- Therapist review queue with urgent and movement filters.
- Session review with video, pose overlay, measurements, repetition cards, pain, stiffness, comments, and voice transcript.
- Therapist approval and request-changes workflow.
- Exercise plans and approved reference videos.
- Patient session recording/upload and check-in.
- Logout and profile controls.

### On-device AI and movement analysis

- MediaPipe pose tracking.
- Exercise-specific movement analysis for six exercises:
  - squat;
  - lunge;
  - leg raise to the side;
  - arm raise to the side;
  - arm V-W;
  - push-ups using a table or elevated surface.
- Repetition counting and movement measurements.
- XGBoost form classification models.
- Local vision model for exercise/view/form second opinion.
- Local Whisper speech-to-text for voice notes.
- Local LLM draft reports using verified movement facts and patient comments.
- Local safety flags for pain, red-flag terms, poor quality, incorrect exercise, and insufficient repetitions.

### AI exercise tutorial

- Tutorial drafts are created only from reviewed sessions.
- Strict tutorial structure includes:
  - exercise;
  - repetitions and target depth;
  - verified movement findings;
  - personalized coaching cues;
  - warnings;
  - captions;
  - instruction script;
  - approved reference video;
  - source session;
  - draft/approved/request-changes status.
- Deterministic fallback when the local LLM is unavailable or returns invalid JSON.
- Therapist object-level authorization is enforced.
- Only approved reference videos can be attached.
- Draft tutorials are hidden from patients.
- Patients can access only approved tutorials.
- Request-changes notes are saved and returned.

### Tutorial media

- Reuses the approved reference video; it does not synthesize a fake person.
- Burns captions, coaching cues, and warnings into a new MP4 with FFmpeg/libass.
- Captions use compact lower-third styling with portrait-video support.
- Optional local Piper voice guidance is embedded as audio.
- espeak/espeak-ng is used as a local fallback when Piper is unavailable.
- Media status is visible as queued, processing, ready, or failed.
- Therapists can generate, preview, download, and approve tutorial media.
- Patients receive the generated MP4 only after tutorial approval.

## Recommended presentation structure

### Slide 1 — Title

**Recovery Monitor**

Subtitle: **Private, on-device rehabilitation evidence between visits**

Show the product logo and an image of the patient or therapist dashboard.

### Slide 2 — The gap in rehabilitation

Use three short points:

- Patients practice without immediate supervision.
- Therapists see limited evidence between appointments.
- Sending health video to the cloud creates privacy and connectivity concerns.

### Slide 3 — Our workflow

Show this flow:

```text
Patient video + check-in
          ↓
Nano-local movement and voice analysis
          ↓
Evidence and AI draft
          ↓
Therapist review and approval
          ↓
Personalized tutorial for the patient
```

### Slide 4 — Why the HP ZGX Nano

Explain that the Nano runs pose tracking, form models, vision analysis, Whisper, local LLM drafting, and FFmpeg tutorial rendering locally.

Key message: **The Nano is not just hosting the website; it is the private AI runtime.**

### Slide 5 — What the patient sees

Show:

- assigned therapist;
- exercise plan;
- reference video;
- record session control;
- movement results;
- pain and voice check-in;
- approved tutorial.

### Slide 6 — What the therapist sees

Show:

- review queue;
- urgent flags;
- pose overlay and measurement graph;
- patient comments/transcript;
- approve/request-changes actions;
- tutorial draft editor.

### Slide 7 — AI tutorial safety model

Use these points:

- AI uses verified analysis facts and patient comments.
- AI cannot invent measurements or diagnoses.
- A therapist reviews and approves the content.
- Drafts remain invisible to patients.
- Reference videos must be approved.

### Slide 8 — Tutorial media

Show a before/after comparison:

- approved reference video;
- rendered MP4 with compact captions;
- coaching cue and warning;
- optional local voice guidance.

State clearly: **This is a personalized instructional layer over an approved exercise video, not synthetic video generation.**

### Slide 9 — Impact and differentiation

- More useful evidence between appointments.
- Personalized guidance without exposing videos to cloud services.
- Therapist remains in control.
- Works on-device and can continue with limited connectivity.

### Slide 10 — Next steps

- Improve tutorial voice naturalness and timing.
- Add richer exercise-aware caption timing.
- Expand therapist review analytics.
- Validate with more real-world recordings and clinical feedback.
- Evaluate additional Nano-appropriate local models.

## Recommended demo video: 2–3 minutes

### Preparation

- Use the integrated branch URL: `http://127.0.0.1:5181`.
- Forward port `5181` through VS Code if connecting over SSH.
- Use a clean browser window and hide unrelated tabs.
- Sign in before recording so there is no typing delay.
- Use a patient/session that already has an analyzed video and an approved reference video.
- Keep the Nano status card visible at least once.

Demo account password: `recovery-demo`.

Therapist account: `therapist.demo@example.com`.

Patient accounts: `jordan@demo.local`, `sam@demo.local`, or `test@demo.local`.

### Suggested recording sequence

#### 0:00–0:15 — Set the context

Say:

> Recovery Monitor helps patients practice between visits while keeping video, voice, and AI processing on the HP ZGX Nano.

Show the privacy badge and Nano model card.

#### 0:15–0:40 — Patient evidence

Show the patient dashboard and a completed session. Point out:

- repetitions;
- measured depth or range;
- pose overlay;
- patient pain score;
- optional voice note.

Say:

> The system turns a short movement recording and patient check-in into structured evidence for the therapist.

#### 0:40–1:10 — Therapist review

Switch to the therapist account. Open a flagged session. Show:

- the movement video;
- measurement graph;
- rep-level review;
- pain/transcript information;
- approved reference-video selector.

Say:

> The AI highlights what needs attention, but the therapist makes the final decision.

#### 1:10–1:45 — Generate the tutorial

Approve the session, then open **AI exercise tutorial**.

1. Click **Generate tutorial draft**.
2. Show the verified findings, coaching cues, warnings, captions, and script.
3. Keep **Add local voice guidance** enabled.
4. Click **Generate tutorial video**.
5. Show the status moving from queued/processing to ready.
6. Play the rendered preview.

Say:

> The tutorial reuses an approved reference video, adds patient-specific coaching and warnings, and can read the guidance using a local voice engine.

#### 1:45–2:10 — Therapist approval and patient delivery

1. Click **Approve tutorial**.
2. Sign out.
3. Sign in as the patient.
4. Open **Your exercise tutorials**.
5. Play the approved tutorial video.

Say:

> The patient sees the media only after therapist approval. Draft content is never exposed to the patient.

#### 2:10–2:25 — Closing message

Say:

> Recovery Monitor combines movement evidence, local AI, and human clinical review into a private workflow that works between visits.

## Recording tips

- Record at 1080p if possible, but keep the video under three minutes.
- Use browser zoom around 90% so the important panel fits on screen.
- Move the mouse slowly and pause briefly after each important action.
- Capture the Nano status card, not just the browser page.
- Avoid showing passwords, terminal secrets, tokens, or unrelated patient data.
- Do not claim that the system diagnoses patients or replaces therapists.
- Do not claim that a synthetic exercise video is generated; the current system reuses an approved reference video.
- If the tutorial takes time to render, record the queued state and then cut to the ready preview.

## Backup demo if live generation is slow

Prepare one approved tutorial before recording. During the demo:

1. Open the therapist review page.
2. Show the reviewed evidence.
3. Open the existing tutorial draft.
4. Show the generated MP4 and voice option.
5. Approve it.
6. Open the patient view and play the approved media.

This keeps the story complete while avoiding a long silent processing segment.

## Honest limitations to mention if asked

- The generated media currently uses the approved reference video rather than synthesizing a new human demonstration.
- Local voice quality depends on the installed offline TTS engine.
- The therapist must review and approve AI-generated tutorial content.
- Model accuracy still needs broader real-world validation.
- The application is a rehabilitation evidence and guidance tool, not a diagnosis or emergency-care system.

## Current branch and commits

- Branch: `feat/arya-ai-tutorial-voice`
- Worktree: `/home/hp21/rm-arya-ai`
- Remote branch: `https://github.com/aryaMehta26/recovery-monitor/tree/feat/arya-ai-tutorial-voice`
- AI tutorial backend: `8b983de`
- Tutorial review UI: `19c1bc3`
- Local media rendering: `9828db2`
- Caption/audio and integrated UI fixes: `bacf8f3`, `1cad83f`
