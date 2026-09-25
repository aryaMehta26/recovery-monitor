import { AlertCircle, ArrowRight, CheckCircle2, ChevronRight, Inbox, Mic, Play, Sparkles, Users } from 'lucide-react';
import { useState } from 'react';
import { api } from '../api.js';
import { exerciseName } from '../exercises.js';
import { ErrorNote, FlagBadge, Initials, Panel } from '../components/ui.jsx';
import { fmtDateTime, go, usePoll } from '../hooks.js';

export default function PhysioQueue({ view = 'queue' }) {
  const queue = usePoll(() => api.reviewQueue(), 5000);
  const patients = usePoll(() => api.patients(), 15000);
  const intakes = usePoll(() => api.therapistIntakes(), 10000);
  const [filter, setFilter] = useState('all');
  const [decisionError, setDecisionError] = useState(null);
  const sessions = queue.data ?? [];
  const patientList = patients.data ?? [];
  const newRequests = (intakes.data ?? []).filter((i) => ['pending', 'assigned'].includes(i.status));
  const urgentCount = sessions.filter((s) => s.flag?.severity === 'urgent').length;
  const visibleSessions = filter === 'urgent'
    ? sessions.filter((s) => s.flag?.severity === 'urgent')
    : filter === 'form'
      ? sessions.filter((s) => s.flag?.severity !== 'urgent')
      : sessions;

  return (
    <div className="page care-dashboard">
      <header className="page-heading queue-hero">
        <div>
          <span className="eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</span>
          <h1>{{ queue: 'Review queue', requests: 'New requests', patients: 'Patients' }[view]}</h1>
          <p className="page-subtitle">{{
            queue: 'Sessions the on-device models flagged for your attention. Urgent first.',
            requests: 'Patients matched to you by specialty. Each request was written up by the AI assistant from what the patient said.',
            patients: 'Open a patient to see what they told us, their trend, and to set or change their plan.',
          }[view]}</p>
        </div>
        <span className="chip"><span className="status-dot" style={{ color: '#34c759' }} /> Updates live</span>
      </header>
      <ErrorNote error={queue.error || patients.error || intakes.error || decisionError} />

      {view === 'queue' && newRequests.length > 0 && (
        <button className="banner" onClick={() => go('/physio/requests')}>
          <span className="ai-avatar"><Inbox size={16} /></span>
          <span><strong>{newRequests.length} new patient request{newRequests.length > 1 ? 's' : ''}</strong> waiting for you</span>
          <ArrowRight size={16} />
        </button>
      )}

      {view === 'queue' && <section className="care-overview" aria-label="Overview">
        <div className="care-stat"><div className="care-stat-icon amber"><AlertCircle size={17} /></div><span>Waiting for review</span><strong>{queue.data ? sessions.length : '—'}</strong><small>flagged sessions</small></div>
        <div className="care-stat"><div className="care-stat-icon red"><AlertCircle size={17} /></div><span>Urgent</span><strong>{queue.data ? urgentCount : '—'}</strong><small>pain or red-flag words</small></div>
        <div className="care-stat"><div className="care-stat-icon blue"><Users size={17} /></div><span>Your patients</span><strong>{patients.data ? patientList.length : '—'}</strong><small>with a plan or sessions</small></div>
        <div className="care-stat"><div className="care-stat-icon green"><Inbox size={17} /></div><span>New requests</span><strong>{intakes.data ? newRequests.length : '—'}</strong><small>patients asking for care</small></div>
      </section>}

      {view === 'requests' && newRequests.length === 0 && (
        <Panel><div className="empty-state"><Inbox size={24} /><p>No new requests.</p><small>When a patient describes their problem to the AI assistant, their request appears here.</small></div></Panel>
      )}
      {view === 'requests' && newRequests.length > 0 && (
        <Panel title={`${newRequests.length} waiting`} subtitle="Assigned to you by specialty. Written up by the AI assistant from what the patient said.">
          <div className="request-list">
            {newRequests.map((intake) => (
              <IntakeCard key={intake.id} intake={intake} onError={setDecisionError}
                onAccept={async () => { await api.claimIntake(intake.id); go(`/physio/patient/${intake.patient_user_id}`); }}
                onDecline={async () => { await api.declineIntake(intake.id); intakes.reload(); }} />
            ))}
          </div>
        </Panel>
      )}

      {view === 'queue' && <Panel title={`${queue.data?.length ?? '—'} sessions waiting`} action={
        <div className="queue-filters" role="group" aria-label="Filter review queue">
          {[['all', 'All'], ['urgent', 'Urgent'], ['form', 'Movement']].map(([value, label]) => (
            <button key={value} className={filter === value ? 'on' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>
          ))}
        </div>
      }>
        {queue.data?.length === 0 && (
          <div className="empty-state"><CheckCircle2 size={24} /><p>All caught up. New flagged sessions appear here automatically.</p></div>
        )}
        {queue.data?.length > 0 && visibleSessions.length === 0 && (
          <div className="empty-state"><CheckCircle2 size={22} /><p>No sessions match this filter.</p></div>
        )}
        <div className="queue">
          {visibleSessions.map((s) => (
            <button key={s.id} className={`queue-row ${s.flag?.severity === 'urgent' ? 'urgent' : ''}`} onClick={() => go(`/physio/session/${s.id}`)}>
              <span className="queue-thumb">
                {s.thumbnail_url ? <img src={s.thumbnail_url} alt="" /> : <span className="thumb-empty" />}
                <span className="play"><Play size={13} fill="currentColor" /></span>
              </span>
              <div className="queue-main">
                <div className="queue-top">
                  <strong>{s.patient?.name ?? s.patient_id}</strong>
                  <FlagBadge flag={s.flag} />
                </div>
                <div className="queue-sub">
                  {exerciseName(s.exercise)} · {s.repetitions ?? '—'} reps{s.pain_score != null ? ` · pain ${s.pain_score}/10` : ''} · {fmtDateTime(s.created_at)}
                </div>
                {s.flag?.reasons?.length > 0 && <ul className="reasons">{s.flag.reasons.slice(0, 3).map((x) => <li key={x}>{x}</li>)}</ul>}
              </div>
              <ChevronRight size={18} className="muted" />
            </button>
          ))}
        </div>
      </Panel>}

      {view === 'patients' && <Panel title={`${patientList.length} patients`} subtitle="Open a patient to review their trend and adjust their plan.">
        <div className="patient-grid">
          {patients.data?.map((p) => (
            <button key={p.id} className="patient-card" onClick={() => go(`/physio/patient/${p.id}`)}>
              <Initials name={p.name} />
              <div>
                <strong>{p.name}</strong>
                <span>{p.protocol ? `${p.protocol.target_reps} × ${exerciseName(p.protocol.exercise).toLowerCase()} · plan v${p.protocol.version}` : 'No plan yet'}</span>
                <span>{p.last_session_at ? `Last session ${fmtDateTime(p.last_session_at)}` : 'No sessions yet'} · {p.sessions_awaiting_review} awaiting review</span>
              </div>
            </button>
          ))}
        </div>
      </Panel>}
    </div>
  );
}

const AREA_LABEL = { knee: 'Knee', hip: 'Hip', back_core: 'Back', ankle_foot: 'Ankle / foot', shoulder_arm: 'Shoulder / arm',
  elbow_forearm: 'Elbow', wrist_hand: 'Wrist / hand', general_mobility: 'General mobility', other: 'Other' };
const MOOD = { calm: 'Calm', hopeful: 'Hopeful', worried: 'Worried', frustrated: 'Frustrated', in_pain: 'In pain' };

function IntakeCard({ intake, onAccept, onDecline, onError }) {
  const [busy, setBusy] = useState(false);
  const ai = intake.ai;
  const name = intake.patient?.name || intake.patient?.email || intake.patient_user_id;
  const act = (fn) => async () => { setBusy(true); try { await fn(); } catch (e) { onError(e); } setBusy(false); };
  return (
    <article className={`request-card ${ai?.urgent ? 'urgent' : ''}`}>
      <header>
        <Initials name={name} />
        <div className="request-who">
          <strong>{name}</strong>
          <span>{intake.affected_areas.map((a) => AREA_LABEL[a] ?? a).join(' · ')} · pain {intake.pain_score}/10 · {fmtDateTime(intake.created_at)}</span>
        </div>
        {ai?.urgent ? <span className="badge badge-red">Priority</span> : intake.assigned_therapist_id ? <span className="badge badge-grey">Assigned to you</span> : null}
      </header>
      {ai ? (
        <>
          <p className="request-summary"><Sparkles size={14} /> {ai.summary_for_therapist}</p>
          {intake.voice_transcript && <blockquote><Mic size={13} /> “{intake.voice_transcript}”</blockquote>}
          <div className="request-facts">
            {ai.mood && <span className="chip">Mood: {MOOD[ai.mood] ?? ai.mood}</span>}
            {ai.suggested_exercise && <span className="chip">AI suggests: {exerciseName(ai.suggested_exercise)}</span>}
            {ai.red_flags?.map((f) => <span key={f} className="chip warn">{f}</span>)}
          </div>
          {ai.follow_up_questions?.length > 0 && (
            <details className="request-more"><summary>Questions to ask</summary><ul>{ai.follow_up_questions.map((q) => <li key={q}>{q}</li>)}</ul></details>
          )}
        </>
      ) : <p className="request-summary">{intake.notes || 'New patient care request'}</p>}
      <footer>
        <button className="secondary-button" disabled={busy} onClick={act(onDecline)}>Not for me</button>
        <button className="primary-button" disabled={busy} onClick={act(onAccept)}>Accept & set plan <ArrowRight size={15} /></button>
      </footer>
    </article>
  );
}
