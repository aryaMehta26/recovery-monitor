import { ArrowLeft, Mic, Save, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import TrendChart from '../components/TrendChart.jsx';
import { ErrorNote, FlagBadge, Note, Panel } from '../components/ui.jsx';
import { EXERCISES, prettyCondition } from '../exercises.js';
import { fmtDateTime, go, num, useLoad } from '../hooks.js';

export default function PhysioPatient({ patientId }) {
  const patient = useLoad(() => api.patient(patientId), [patientId]);
  const history = useLoad(() => api.patientSessions(patientId), [patientId]);
  const refs = useLoad(() => api.referenceVideos(), []);
  const intakes = useLoad(() => api.therapistIntakes().catch(() => []), [patientId]);
  const intake = intakes.data?.find((i) => i.patient_user_id === patientId);
  const protocol = patient.data?.protocol;

  return (
    <div className="page">
      <button className="text-button back" onClick={() => go('/physio')}><ArrowLeft size={14} /> Review queue</button>
      <header className="page-heading">
        <div>
          <span className="eyebrow">Patient</span>
          <h1>{patient.data?.name}</h1>
          <p className="page-subtitle">{prettyCondition(patient.data?.condition)}</p>
        </div>
      </header>
      <ErrorNote error={patient.error} />
      {intake && <IntakeNote intake={intake} />}

      <Panel className="plan-wide" title="Exercise plan" subtitle={protocol ? `Version ${protocol.version} · ${fmtDateTime(protocol.created_at)}` : 'No plan yet: choose an exercise and send it to the patient'}>
        <ProtocolEditor patientId={patientId} protocol={protocol} refs={refs.data} onSaved={patient.reload} suggested={intake?.ai?.suggested_exercise} areas={intake?.affected_areas} />
      </Panel>

      <div className="grid-2">
        <Panel title="Sessions" subtitle={history.data?.length ? `${history.data.length} recorded` : undefined}>
          {history.data?.length ? (
            <table className="table">
              <thead><tr><th>Date</th><th>Reps</th><th>Flagged</th><th>Pain</th><th>Status</th><th>Decision</th></tr></thead>
              <tbody>
                {history.data.slice().reverse().map((s) => (
                  <tr key={s.id} onClick={() => go(`/physio/session/${s.id}`)}>
                    <td>{fmtDateTime(s.created_at)}</td>
                    <td>{num(s.repetitions)}</td>
                    <td>{s.repetitions != null ? s.repetitions - (s.correct_repetitions ?? 0) : '—'}</td>
                    <td>{s.pain_score ?? '—'}</td>
                    <td><FlagBadge flag={s.flag} /></td>
                    <td>{s.review ? s.review.decision.replace('_', ' ') : 'pending'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="muted small">No sessions yet. They appear here once the patient records their first one.</p>}
        </Panel>
        <Panel title="Recovery trend">
          <TrendChart sessions={history.data} targetDepth={protocol?.target_depth_deg} />
        </Panel>
      </div>
    </div>
  );
}

// Exercises that make sense to start from, per body area (mirrors the intake assistant's rules).
const FITS = { knee: ['squat', 'leg_lunge'], hip: ['leg_abduction', 'squat', 'leg_lunge'], ankle_foot: ['leg_lunge', 'squat'],
  back_core: ['squat', 'leg_abduction'], shoulder_arm: ['arm_abduction', 'arm_vw'], elbow_forearm: ['push_ups', 'arm_vw'],
  wrist_hand: ['push_ups'] };
const PLAN_EXERCISES = ['squat', 'leg_lunge', 'leg_abduction', 'arm_abduction', 'arm_vw', 'push_ups'];

function ProtocolEditor({ patientId, protocol, refs, onSaved, suggested, areas = [] }) {
  const blank = { exercise: suggested || 'squat', target_reps: 10, target_depth_deg: 100, pain_threshold: 5, tempo: '', notes: '', reference_video_id: null };
  const [form, setForm] = useState(blank);
  const [state, setState] = useState({ saving: false, error: null, saved: false });
  const refFor = (ex) => refs?.find((v) => v.exercise === ex)?.id ?? null;
  useEffect(() => {
    if (protocol) setForm({ ...blank, ...protocol });
    else setForm((f) => ({ ...f, exercise: suggested || f.exercise, reference_video_id: refFor(suggested || f.exercise) }));
  }, [protocol?.id, suggested, refs?.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep exactly what the therapist types (an emptied box stays empty); numbers are parsed on save.
  const set = (k) => (e) => { const v = e.target.value; setForm((f) => ({ ...f, [k]: v })); };
  const choose = (ex) => setForm((f) => ({ ...f, exercise: ex, reference_video_id: refFor(ex) }));
  const recommended = new Set(areas.flatMap((a) => FITS[a] ?? []));
  const ordered = [...PLAN_EXERCISES].sort((x, y) => (y === suggested) - (x === suggested) || recommended.has(y) - recommended.has(x));
  const exRefs = refs?.filter((v) => v.exercise === form.exercise) ?? [];
  const ref = refs?.find((v) => v.id === Number(form.reference_video_id));

  const int = (v, lo, hi) => { const n = Number(v); return v !== '' && Number.isInteger(n) && n >= lo && n <= hi ? n : null; };

  async function save() {
    const reps = int(form.target_reps, 1, 100);
    const pain = int(form.pain_threshold, 0, 10);
    const depth = form.exercise === 'squat' ? int(form.target_depth_deg, 30, 175) : int(form.target_depth_deg, 30, 175) ?? 100;
    const bad = reps == null ? 'Repetitions must be a whole number from 1 to 100.'
      : pain == null ? 'Pain alert must be a whole number from 0 to 10.'
        : depth == null ? 'Target depth must be between 30° and 175°.' : null;
    if (bad) { setState({ saving: false, error: new Error(bad), saved: false }); return; }
    setState({ saving: true, error: null, saved: false });
    try {
      await api.setProtocol(patientId, {
        exercise: form.exercise, target_reps: reps, target_depth_deg: depth,
        pain_threshold: pain, tempo: form.tempo || null, notes: form.notes || null,
        reference_video_id: form.reference_video_id ? Number(form.reference_video_id) : null,
      });
      setState({ saving: false, error: null, saved: true });
      onSaved();
    } catch (error) {
      setState({ saving: false, error, saved: false });
    }
  }

  return (
    <div className="form plan-editor">
      <span className="field-label">Exercise</span>
      <div className="ex-grid" role="radiogroup" aria-label="Exercise">
        {ordered.map((k) => (
          <button key={k} type="button" role="radio" aria-checked={form.exercise === k} className={`ex-tile ${form.exercise === k ? 'on' : ''}`} onClick={() => choose(k)}>
            <strong>{EXERCISES[k].name}</strong>
            <small>{EXERCISES[k].area}</small>
            {k === suggested ? <span className="ex-tag ai">AI suggests</span> : recommended.has(k) ? <span className="ex-tag">Recommended</span> : null}
          </button>
        ))}
      </div>
      <div className="form-row">
        <label className="field"><span>Repetitions</span><input type="number" min="1" max="100" value={form.target_reps} onChange={set('target_reps')} /></label>
        {form.exercise === 'squat' && (
          <label className="field"><span>Target depth (knee °)</span><input type="number" min="30" max="175" value={form.target_depth_deg ?? 100} onChange={set('target_depth_deg')} /></label>
        )}
        <label className="field"><span>Pain alert at (0–10)</span><input type="number" min="0" max="10" value={form.pain_threshold} onChange={set('pain_threshold')} /></label>
      </div>
      <label className="field"><span>Tempo</span><input value={form.tempo ?? ''} onChange={set('tempo')} placeholder="Slow and controlled, 2 s down, 2 s up" /></label>
      <label className="field"><span>Instructions for the patient</span><textarea rows={3} value={form.notes ?? ''} onChange={set('notes')}
        placeholder="e.g. Keep your knee behind your toes. Stop if the pain goes above 5." /></label>
      <label className="field">
        <span>Reference video (correct form)</span>
        <select value={form.reference_video_id ?? ''} onChange={set('reference_video_id')}>
          <option value="">None</option>
          {exRefs.map((v) => <option key={v.id} value={v.id}>{v.title}</option>)}
        </select>
      </label>
      {ref && <video className="ref-preview" src={ref.url} controls muted playsInline preload="metadata" />}
      {form.exercise === 'squat' && <Note>Smaller knee angle = deeper squat.</Note>}
      <button className="primary-button" onClick={save} disabled={state.saving}><Save size={14} /> {state.saving ? 'Saving…' : protocol ? 'Save new plan version' : 'Send plan to patient'}</button>
      {state.saved && <Note tone="ok">Sent: {form.target_reps} × {EXERCISES[form.exercise]?.name.toLowerCase()}, pain alert at {form.pain_threshold}/10. The patient sees it, with your instructions and the video, on their Today page.</Note>}
      <ErrorNote error={state.error} />
    </div>
  );
}

const DURATION = { less_than_two_weeks: 'under 2 weeks', two_to_six_weeks: '2–6 weeks', one_to_three_months: '1–3 months',
  more_than_three_months: 'over 3 months', unknown: 'duration not given' };
const MOOD = { calm: 'Calm', hopeful: 'Hopeful', worried: 'Worried', frustrated: 'Frustrated', in_pain: 'In pain' };
const TREND = { improving: 'getting better', unchanged: 'about the same', getting_worse: 'getting worse', unknown: 'trend not given' };

// What the patient told the intake assistant, so the plan starts from their own words.
function IntakeNote({ intake }) {
  const ai = intake.ai;
  return (
    <Panel className="intake-note" title={<><span className="ai-mark"><Sparkles size={14} /></span> What the patient told us</>}
      subtitle={`Care request · ${fmtDateTime(intake.created_at)}${ai?.model ? ` · summarised by ${ai.model} on this device` : ''}`}>
      <div className="intake-note-grid">
        <div>
          {ai?.summary_for_therapist && <p className="report-headline">{ai.summary_for_therapist}</p>}
          {intake.voice_transcript && <blockquote><Mic size={13} /> “{intake.voice_transcript}”</blockquote>}
          {!ai && intake.notes && <p>{intake.notes}</p>}
        </div>
        <div className="intake-facts">
          <div><span>Pain</span><strong>{intake.pain_score}/10</strong></div>
          <div><span>How long</span><strong>{DURATION[intake.duration] ?? intake.duration}</strong></div>
          <div><span>Lately</span><strong>{TREND[intake.trend] ?? intake.trend}</strong></div>
          {ai?.mood && <div><span>Mood</span><strong>{MOOD[ai.mood] ?? ai.mood}</strong></div>}
          {ai?.suggested_exercise && <div><span>AI suggests</span><strong>{EXERCISES[ai.suggested_exercise]?.name ?? ai.suggested_exercise}</strong></div>}
        </div>
      </div>
      {ai?.red_flags?.length > 0 && <Note tone="error"><strong>Red flags (fixed rules):</strong> {ai.red_flags.join(' · ')}</Note>}
      {ai?.follow_up_questions?.length > 0 && (
        <div className="report"><section><h4>Questions to ask</h4><ul>{ai.follow_up_questions.map((q) => <li key={q}>{q}</li>)}</ul></section></div>
      )}
    </Panel>
  );
}
