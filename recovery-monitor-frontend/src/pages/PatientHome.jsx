import { Activity, ArrowRight, CalendarCheck, Check, CheckCircle2, MessageSquareText, Mic, PlayCircle, ShieldCheck, Sparkles, Trash2, UserRoundPlus } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api.js';
import SessionPlayer from '../components/SessionPlayer.jsx';
import TrendChart from '../components/TrendChart.jsx';
import UploadPanel from '../components/UploadPanel.jsx';
import VoiceRecorder from '../components/VoiceRecorder.jsx';
import { exerciseName, prettyCondition } from '../exercises.js';
import { Disclaimer, ErrorNote, Note, Panel, Stat } from '../components/ui.jsx';
import { fmtDate, fmtDateTime, go, num, useLoad } from '../hooks.js';

export default function PatientHome({ patientId, view = 'today' }) {
  const patient = useLoad(() => api.patient(patientId), [patientId]);
  const history = useLoad(() => api.patientSessions(patientId), [patientId]);
  const latestId = history.data?.length ? history.data[history.data.length - 1].id : null;
  const latest = useLoad(() => (latestId ? api.session(latestId) : Promise.resolve(null)), [latestId]);
  const refs = useLoad(() => api.referenceVideos(), []);
  const careTeam = useLoad(() => api.patientCareTeam(), []);
  const intakes = useLoad(() => api.patientIntakes(), []);

  const protocol = patient.data?.protocol;
  const approvedIntake = intakes.data?.find((intake) => intake.status === 'approved' && intake.plan);
  const pendingIntake = intakes.data?.some((intake) => ['pending', 'assigned', 'under_review'].includes(intake.status));
  const openIntake = intakes.data?.[0];
  const carePlan = protocol ?? approvedIntake?.plan;
  const refVideo = refs.data?.find((r) => r.id === (latest.data?.review?.reference_video_id ?? carePlan?.reference_video_id));
  const refresh = () => {
    history.reload();
    latest.reload();
  };
  const completedSessions = history.data?.filter((s) => s.stage === 'done').length ?? 0;
  const needsReview = latest.data?.flag?.flagged && !latest.data?.review;
  const status = latest.data?.stage && latest.data.stage !== 'done'
    ? 'Analysis in progress'
    : latest.data?.review
      ? 'Reviewed by your physiotherapist'
      : needsReview
        ? 'Ready for therapist review'
        : completedSessions
          ? 'Ready for today’s movement'
          : 'Your first session starts here';

  return (
    <div className="page patient-dashboard">
      <header className="page-heading patient-heading">
        <div>
          <span className="eyebrow">{{ today: 'Today', progress: 'My progress', care: 'My care team' }[view]}</span>
          <h1>{view === 'today' ? `Hi ${patient.data?.name?.split(' ')[0] ?? ''}` : view === 'progress' ? 'Your progress' : 'Your care team'}</h1>
          <p className="page-subtitle">{prettyCondition(patient.data?.condition)}</p>
        </div>
        <div className={`patient-status ${needsReview ? 'review' : ''}`}><span /> {status}</div>
      </header>
      <ErrorNote error={patient.error || history.error || intakes.error} />
      {view === 'care' && <CareTeam careTeam={careTeam.data} intakes={intakes.data} hasPlan={Boolean(carePlan)} />}

      {view === 'progress' && (
        <>
          <Panel title="Your progress" subtitle="From your analysed sessions">
            <TrendChart sessions={history.data} targetDepth={carePlan?.target_depth_deg} />
          </Panel>
          <Panel title="All sessions" subtitle={`${completedSessions} analysed`}>
            <SessionHistory sessions={history.data} />
          </Panel>
        </>
      )}

      {view === 'today' && !carePlan && (
        <div className="next-card">
          <span className="ai-avatar"><Sparkles size={18} /></span>
          <div>
            <strong>{openIntake ? (openIntake.assigned_therapist_id ? `${careTeam.data?.therapist?.name || 'Your physiotherapist'} is preparing your plan` : 'Your request is waiting for a physiotherapist') : 'Tell us what’s going on'}</strong>
            <p>{openIntake ? 'Your exercises will appear here as soon as your plan is ready.' : 'Describe your problem to our assistant in your own words. It prepares a request for a physiotherapist who covers that area.'}</p>
          </div>
          <button className="primary-button" onClick={() => go(openIntake ? `/patient/${patientId}/care` : '/patient/intake')}>
            {openIntake ? 'See my request' : 'Ask the AI assistant'} <ArrowRight size={15} />
          </button>
        </div>
      )}

      {view === 'today' && (<>
      <section className="patient-overview" aria-label="Your recovery overview">
        <div className="overview-card overview-next">
          <div className="overview-icon"><Activity size={17} /></div>
          <span className="overview-label">Next step</span>
          <strong>{carePlan ? `${carePlan.target_reps} × ${exerciseName(carePlan.exercise).toLowerCase()}` : 'Set your plan'}</strong>
          <p>{carePlan ? (carePlan.exercise === 'squat' ? `Aim for ${carePlan.target_depth_deg ?? 'your'}° depth, then tell your physiotherapist how it felt.` : 'Move slowly and with control, then tell your physiotherapist how it felt.') : 'Your physiotherapist will add an exercise plan here.'}</p>
          {carePlan && <button type="button" className="overview-link" onClick={() => document.getElementById('record-session')?.scrollIntoView({ behavior: 'smooth' })}>Record a session <ArrowRight size={14} /></button>}
        </div>
        <div className="overview-card">
          <div className="overview-icon calm"><CheckCircle2 size={17} /></div>
          <span className="overview-label">Sessions completed</span>
          <strong>{completedSessions}</strong>
          <p>{completedSessions ? 'Your movement history is building over time.' : 'Your analysed sessions will appear here.'}</p>
        </div>
        <div className="overview-card">
          <div className="overview-icon quiet"><ShieldCheck size={17} /></div>
          <span className="overview-label">Care connection</span>
          <strong>{latest.data?.review ? 'Feedback received' : 'Therapist-guided'}</strong>
          <p>Measurements stay on this device and your check-ins go to your care team.</p>
        </div>
      </section>

      <section className="patient-workflow" aria-label="Your session workflow">
        <div className="workflow-heading"><span className="eyebrow">Your workflow</span><span className="muted small">One step at a time</span></div>
        <div className="workflow-steps">
          <div className="workflow-step current"><span className="workflow-number">1</span><div><strong>Follow your plan</strong><small>{carePlan ? `${carePlan.target_reps} × ${exerciseName(carePlan.exercise).toLowerCase()} assigned today` : 'Wait for your plan'}</small></div></div>
          <ArrowRight className="workflow-arrow" size={16} />
          <div className="workflow-step"><span className="workflow-number">2</span><div><strong>Record movement</strong><small>Use your camera or upload a video</small></div></div>
          <ArrowRight className="workflow-arrow" size={16} />
          <div className="workflow-step"><span className="workflow-number">3</span><div><strong>Check in</strong><small>Tell your physiotherapist how it felt</small></div></div>
        </div>
      </section>

      <div className="grid-2" id="record-session">
        <Panel title="Today's exercise" subtitle={carePlan ? `Plan version ${carePlan.version ?? 1}, set ${fmtDate(carePlan.created_at)} by your physiotherapist` : ''}>
          {carePlan ? (
            <>
              <div className="stats-row">
                <Stat label="Exercise" value={exerciseName(carePlan.exercise)} />
                <Stat label="Repetitions" value={carePlan.target_reps} />
                {carePlan.exercise === 'squat' && carePlan.target_depth_deg && (
                  <Stat label="Target depth" value={`${carePlan.target_depth_deg}°`} sub="knee angle at the bottom" />
                )}
              </div>
              {carePlan.tempo && <p className="plan-line"><CalendarCheck size={14} /> {carePlan.tempo}</p>}
              {carePlan.notes && (
                <div className="physio-note">
                  <span className="mini-label"><MessageSquareText size={13} /> From {careTeam.data?.therapist?.name || carePlan.approved_by || 'your physiotherapist'}</span>
                  <p>{carePlan.notes}</p>
                </div>
              )}
              {refVideo && (
                <div className="reference">
                  <span className="mini-label"><PlayCircle size={13} /> How it should look: {refVideo.title}</span>
                  <video src={refVideo.url} controls playsInline preload="metadata" />
                </div>
              )}
            </>
          ) : (
            <Note>{approvedIntake ? 'Your approved plan is ready below.' : 'Your physiotherapist has not set a plan yet.'}</Note>
          )}
        </Panel>

        <Panel title="Record today's session" subtitle="Your video is analysed on this device only">
          <UploadPanel patientId={patientId} onDone={refresh} exercise={carePlan?.exercise} />
        </Panel>
      </div>

      {latest.data && <LatestSession session={latest.data} patientId={patientId} refVideo={refVideo} onSaved={refresh} />}
      </>)}
      <Disclaimer />
    </div>
  );
}

function LatestSession({ session, patientId, refVideo, onSaved }) {
  const r = session.result;
  const review = session.review;
  const target = r?.protocol?.target_reps ?? session.protocol?.target_reps;
  const flagged = r?.reps?.filter((x) => !x.predicted_correct).length ?? 0;

  if (session.stage !== 'done') {
    return (
      <Panel title={`Session from ${fmtDateTime(session.created_at)}`} action={<DeleteSessionAction sessionId={session.id} onDeleted={onSaved} />}>
        {session.stage === 'failed' ? <Note tone="error">{session.error}</Note> : <Note>Still being analysed…</Note>}
      </Panel>
    );
  }

  return (
    <Panel title={`Your last session · ${fmtDateTime(session.created_at)}`}
      subtitle={review ? 'Reviewed by your physiotherapist' : flagged ? 'Sent to your physiotherapist for review' : 'Analysed on this device'}
      action={<DeleteSessionAction sessionId={session.id} onDeleted={onSaved} />}>
      {r.status === 'rejected_quality' && (
        <Note tone="warn">
          <strong>We couldn't measure this video reliably.</strong>
          <ul>{r.quality.instructions.map((m) => <li key={m}>{m}</li>)}</ul>
        </Note>
      )}
      {r.status !== 'rejected_quality' && (
        <>
          <div className="stats-row">
            <Stat label="Reps done" value={`${r.repetitions}${target ? ` / ${target}` : ''}`} />
            {r.exercise === 'squat' ? (
              <>
                <Stat label="Reached target depth" value={`${r.metrics?.reps_reaching_target ?? 0} of ${r.repetitions}`} />
                <Stat label="Deepest squat" value={num(r.metrics?.min_knee_angle_deg, 0, '°')} />
              </>
            ) : (
              <Stat label={r.measure_label ?? 'Movement'} value={num(r.metrics?.peak_deg, 0, '°')} sub="best rep" />
            )}
            <Stat label="For your physio to check" value={flagged} tone={flagged ? 'amber' : 'green'}
              sub={flagged ? 'reps looked different from your approved form' : 'nothing flagged'} />
          </div>
          {r.vlm?.mismatch && (
            <Note tone="warn">This looks like <strong>{exerciseName(r.vlm.detected_exercise).toLowerCase()}</strong>, but
              your plan is <strong>{exerciseName(r.vlm.planned_exercise).toLowerCase()}</strong>. Your physiotherapist will check.</Note>
          )}
          {r.quality?.instructions?.length > 0 && <Note tone="warn">{r.quality.instructions.join(' ')}</Note>}
        </>
      )}

      {review && (
        <div className={`feedback ${review.decision}`}>
          <strong>{review.decision === 'approve' ? 'Your physiotherapist approved this session' : 'Your physiotherapist asked for changes'}</strong>
          {review.notes && <p>“{review.notes}”</p>}
          {session.report?.patient_message && <p>{session.report.patient_message}</p>}
          <small>{fmtDateTime(review.created_at)}</small>
        </div>
      )}

      <div className={refVideo && review ? 'side-by-side' : ''}>
        <div>
          {refVideo && review && <span className="mini-label">You</span>}
          <SessionPlayer session={session} />
        </div>
        {refVideo && review && (
          <div>
            <span className="mini-label">How it should look</span>
            <div className="video-frame"><video src={refVideo.url} controls playsInline preload="metadata" /></div>
          </div>
        )}
      </div>

      {!session.check_in ? <CheckIn patientId={patientId} sessionId={session.id} onSaved={onSaved} /> : (
        <p className="muted small">You reported pain {session.check_in.pain_score}/10 for this session.</p>
      )}
    </Panel>
  );
}

function DeleteSessionAction({ sessionId, onDeleted }) {
  const [state, setState] = useState({ deleting: false, error: null });

  async function remove() {
    if (!window.confirm('Delete this video and its analysis? This cannot be undone.')) return;
    setState({ deleting: true, error: null });
    try {
      await api.deleteSession(sessionId);
      onDeleted?.();
    } catch (error) {
      setState({ deleting: false, error });
    }
  }

  return (
    <div className="session-delete-action">
      <button type="button" className="text-button danger-text" onClick={remove} disabled={state.deleting}>
        <Trash2 size={14} /> {state.deleting ? 'Deleting…' : 'Delete video'}
      </button>
      {state.error && <ErrorNote error={state.error} />}
    </div>
  );
}

function CheckIn({ patientId, sessionId, onSaved }) {
  const [pain, setPain] = useState(null);
  const [stiff, setStiff] = useState(false);
  const [comment, setComment] = useState('');
  const [transcript, setTranscript] = useState('');
  const [state, setState] = useState({ saving: false, error: null });

  async function save() {
    setState({ saving: true, error: null });
    try {
      await api.checkIn(patientId, sessionId, { pain_score: pain, stiffness: stiff, comment, transcript: transcript || null });
      onSaved();
    } catch (error) {
      setState({ saving: false, error });
    }
  }

  return (
    <div className="checkin">
      <h3>How did it feel?</h3>
      <div className="pain-scale" role="radiogroup" aria-label="Pain from 0 to 10">
        {Array.from({ length: 11 }, (_, i) => (
          <button key={i} className={pain === i ? 'selected' : ''} onClick={() => setPain(i)} aria-pressed={pain === i}>{i}</button>
        ))}
      </div>
      <div className="pain-labels"><span>No pain</span><span>Worst pain</span></div>
      <label className="check"><input type="checkbox" checked={stiff} onChange={(e) => setStiff(e.target.checked)} /> It felt stiff</label>
      <VoiceRecorder patientId={patientId} sessionId={sessionId} onTranscript={setTranscript} />
      {transcript && (
        <label className="field">
          <span>What we heard (edit if anything is wrong)</span>
          <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)} rows={3} />
        </label>
      )}
      <textarea placeholder="Or type anything your physiotherapist should know (optional)" value={comment}
        onChange={(e) => setComment(e.target.value)} rows={2} />
      <button className="primary-button" disabled={pain === null || state.saving} onClick={save}>
        {state.saving ? 'Saving…' : 'Send to my physiotherapist'}
      </button>
      <ErrorNote error={state.error} />
    </div>
  );
}

const AREA_LABEL = { knee: 'Knee', hip: 'Hip', back_core: 'Back', ankle_foot: 'Ankle / foot', shoulder_arm: 'Shoulder / arm',
  elbow_forearm: 'Elbow', wrist_hand: 'Wrist / hand', general_mobility: 'General mobility', other: 'Other' };

// Where the patient's care request is: sent -> matched -> accepted -> plan ready.
function CareTeam({ careTeam, intakes, hasPlan }) {
  const intake = intakes?.[0];
  const therapist = careTeam?.therapist ?? intake?.therapist;
  const accepted = intake && ['under_review', 'plan_drafted', 'approved', 'changes_requested'].includes(intake.status);
  const steps = intake ? [
    ['Request sent', fmtDateTime(intake.created_at), true],
    ['Matched with a physiotherapist', therapist ? (therapist.name || therapist.email) : 'Looking for a physiotherapist who covers this area', Boolean(intake.assigned_therapist_id)],
    ['Accepted', accepted ? 'Your physiotherapist took on your care' : 'Waiting for them to accept', accepted || hasPlan],
    ['Plan ready', hasPlan ? 'Your exercises are on your Today page' : 'Your physiotherapist will set your exercises', hasPlan],
  ] : [];
  return (
    <>
      <Panel title="Your physiotherapist" className="care-team-panel"
        action={<button type="button" className="secondary-button" onClick={() => go('/patient/intake')}><UserRoundPlus size={15} /> New request</button>}>
        {therapist ? (
          <div className="care-person">
            <span className="account-avatar therapist big">{(therapist.name || therapist.email).split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase()}</span>
            <div><strong>{therapist.name || therapist.email}</strong><span>{therapist.email}</span></div>
          </div>
        ) : <Note>{intake ? 'We are matching you with a physiotherapist who covers this area.' : 'You haven’t asked for help yet. Tell our assistant what’s going on to get matched with a physiotherapist.'}</Note>}
      </Panel>

      {intake && (
        <Panel title="Your request" subtitle={intake.affected_areas.map((a) => AREA_LABEL[a] ?? a).join(' · ') + ` · pain ${intake.pain_score}/10`}>
          <ol className="timeline">
            {steps.map(([label, detail, done], i) => {
              const current = !done && (i === 0 || steps[i - 1][2]);
              return (
                <li key={label} className={done ? 'done' : current ? 'now' : ''}>
                  <span className="tl-dot">{done && <Check size={12} strokeWidth={3} />}</span>
                  <div><strong>{label}</strong><small>{detail}</small></div>
                </li>
              );
            })}
          </ol>
          {intake.ai?.summary_for_therapist && (
            <div className="told-us">
              <span className="mini-label"><Sparkles size={13} /> What your physiotherapist sees</span>
              <p>{intake.ai.summary_for_therapist}</p>
              {intake.voice_transcript && <blockquote><Mic size={13} /> “{intake.voice_transcript}”</blockquote>}
            </div>
          )}
        </Panel>
      )}
    </>
  );
}

function SessionHistory({ sessions }) {
  if (!sessions?.length) return <p className="muted small">No sessions yet. Record your first one from the Today page.</p>;
  return (
    <table className="table">
      <thead><tr><th>Date</th><th>Exercise</th><th>Reps</th><th>Pain</th><th>Physio</th></tr></thead>
      <tbody>
        {sessions.slice().reverse().map((x) => (
          <tr key={x.id}>
            <td>{fmtDateTime(x.created_at)}</td>
            <td>{exerciseName(x.exercise)}</td>
            <td>{x.repetitions ?? '—'}</td>
            <td>{x.pain_score != null ? `${x.pain_score}/10` : '—'}</td>
            <td>{x.review ? (x.review.decision === 'approve' ? 'Approved' : 'Asked for changes') : x.stage === 'done' ? 'Waiting' : 'Analysing'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
