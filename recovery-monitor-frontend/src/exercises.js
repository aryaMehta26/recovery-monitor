// Display names for the six exercises the models support (plus the original prototype's leg extension).
export const EXERCISES = {
  squat: { name: 'Squats', one: 'squat', area: 'Lower body' },
  leg_lunge: { name: 'Lunges', one: 'lunge', area: 'Lower body' },
  leg_abduction: { name: 'Leg raises to the side', one: 'leg raise', area: 'Lower body' },
  arm_abduction: { name: 'Arm raises to the side', one: 'arm raise', area: 'Upper body' },
  arm_vw: { name: 'Arm V-W', one: 'arm V-W', area: 'Upper body' },
  push_ups: { name: 'Push-ups (hands on table)', one: 'push-up', area: 'Upper body' },
  seated_leg_extension: { name: 'Seated leg extension', one: 'leg extension', area: 'Lower body' },
};
export const exerciseName = (key) => EXERCISES[key]?.name ?? key ?? '—';

// How to film each exercise (matches the analysis: which camera angle measures it reliably).
export const FILMING = {
  squat: 'Stand side-on to the camera with your whole body in frame. Knee angles are measured accurately from the side (about ±5°).',
  leg_lunge: 'Stand side-on to the camera with your whole body in frame.',
  leg_abduction: 'Face the camera so the sideways leg raise is visible, whole body in frame.',
  arm_abduction: 'Face the camera so the sideways arm raise is visible, from your head to your hips.',
  arm_vw: 'Face the camera with both arms fully in frame.',
  push_ups: 'Place the camera to your side so your arms and body line are visible for the whole movement.',
};
export const filmingTip = (exercise) => FILMING[exercise] ?? FILMING.squat;

const AREA_WORDS = { knee: 'Knee', hip: 'Hip', back_core: 'Back', ankle_foot: 'Ankle / foot', shoulder_arm: 'Shoulder / arm',
  elbow_forearm: 'Elbow', wrist_hand: 'Wrist / hand', general_mobility: 'General mobility' };
// Onboarding stores body areas as keys ("shoulder_arm, knee"); show them as words.
export const prettyCondition = (text) => (text ? text.replace(/\b[a-z]+_[a-z_]+\b|\bknee\b|\bhip\b/g, (k) => AREA_WORDS[k] ?? k) : text);
