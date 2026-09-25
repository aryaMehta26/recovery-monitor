import { AlertTriangle, ArrowLeft, ArrowRight, Check, Keyboard, Mic, RotateCcw, Send, Sparkles, Square } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { api } from '../api.js';
import { exerciseName } from '../exercises.js';
import { go } from '../hooks.js';

// Patient care request: pick the area -> tell the AI about it by voice (Whisper, on this device) -> check what it
// understood -> sent to a matching physiotherapist.
const AREAS = [['knee', 'Knee'], ['hip', 'Hip'], ['back_core', 'Back'], ['ankle_foot', 'Ankle / foot'],
  ['shoulder_arm', 'Shoulder / arm'], ['elbow_forearm', 'Elbow'], ['wrist_hand', 'Wrist / hand'], ['general_mobility', 'General mobility']];
const ISSUES = [['pain_during_movement', 'Pain when moving'], ['stiffness', 'Stiffness'], ['weakness', 'Weakness'],
  ['limited_range_of_motion', 'Can’t move fully'], ['balance_or_stability', 'Balance'], ['difficulty_exercising', 'Hard to exercise']];
const GOALS = [['reduce_pain', 'Less pain'], ['daily_activities', 'Everyday life'], ['return_to_sport', 'Back to sport'],
  ['improve_strength', 'Get stronger'], ['general_conditioning', 'Overall fitness']];
const DURATIONS = [['less_than_two_weeks', 'Under 2 weeks'], ['two_to_six_weeks', '2–6 weeks'],
  ['one_to_three_months', '1–3 months'], ['more_than_three_months', 'Over 3 months'], ['unknown', 'Not sure']];
const TRENDS = [['improving', 'Getting better'], ['unchanged', 'About the same'], ['getting_worse', 'Getting worse'], ['unknown', 'Not sure']];
const MOOD = { calm: 'Calm', hopeful: 'Hopeful', worried: 'Worried', frustrated: 'Frustrated', in_pain: 'In pain' };
const STAGES = ['Turning your voice into text on this device', 'Understanding what you described', 'Preparing your request'];
const toggle = (list, v) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

export default function PatientIntake() {
  const [step, setStep] = useState('where'); // where | talk | thinking | review | sent
  const [areas, setAreas] = useState([]);
  const [ai, setAi] = useState(null);
  const [form, setForm] = useState(null);
  const [error, setError] = useState(null);
  const [therapist, setTherapist] = useState(null);
  const [meId, setMeId] = useState(null);

  async function ask(input) {
    setError(null);
    setStep('thinking');
    try {
      const res = await api.intakeAssist({ ...input, areas });
      setAi(res);
      setForm({
        affected_areas: res.affected_areas, issue_types: res.issue_types, when_it_happens: res.when_it_happens,
        pain_score: res.pain_score, duration: res.duration, trend: res.trend, goals: res.goals, limitations: res.limitations,
      });
      setStep('review');
    } catch (e) {
      setError(e.message);
      setStep('talk');
    }
  }

  async function send() {
    setError(null);
    try {
      await api.createIntake({
        ...form,
        issue_types: form.issue_types.length ? form.issue_types : ['pain_during_movement'],
        goals: form.goals.length ? form.goals : ['daily_activities'],
        notes: ai.summary_for_therapist, voice_transcript: ai.text, ai,
      });
      const [team, me] = await Promise.all([api.patientCareTeam().catch(() => null), api.authMe().catch(() => null)]);
      setTherapist(team?.therapist ?? null);
      setMeId(me?.user?.id ?? null);
      setStep('sent');
    } catch (e) {
      setError(e.message);
    }
  }

  const steps = ['where', 'talk', 'review', 'sent'];
  const at = steps.indexOf(step === 'thinking' ? 'talk' : step);
  return (
    <div className="page intake-flow">
      <div className="intake-progress" aria-hidden="true">{steps.map((s, i) => <i key={s} className={i <= at ? 'on' : ''} />)}</div>

      {step === 'where' && (
        <section className="intake-step" key="where">
          <span className="eyebrow">Step 1 of 3</span>
          <h1>Where do you need help?</h1>
          <p className="page-subtitle">Pick everything that applies. Next, you can tell our assistant about it in your own words.</p>
          <div className="area-grid">
            {AREAS.map(([v, l]) => (
              <button key={v} type="button" className={`area-chip ${areas.includes(v) ? 'on' : ''}`} aria-pressed={areas.includes(v)}
                onClick={() => setAreas(toggle(areas, v))}>{areas.includes(v) && <Check size={14} />}{l}</button>
            ))}
          </div>
          <div className="intake-actions">
            <button className="secondary-button" onClick={() => go('/patient')}><ArrowLeft size={15} /> Back</button>
            <button className="primary-button" disabled={!areas.length} onClick={() => setStep('talk')}>Continue <ArrowRight size={15} /></button>
          </div>
        </section>
      )}

      {step === 'talk' && <Talk onAsk={ask} error={error} onBack={() => setStep('where')} />}
      {step === 'thinking' && <Thinking />}
      {step === 'review' && ai && form && (
        <Review ai={ai} form={form} setForm={setForm} error={error} onSend={send} onRetry={() => setStep('talk')} />
      )}

      {step === 'sent' && (
        <section className="intake-step sent" key="sent">
          <span className="done-mark"><Check size={34} strokeWidth={3} /></span>
          <h1>{therapist ? `You’re matched with ${therapist.name || therapist.email}` : 'Your request is on its way'}</h1>
          <p className="page-subtitle">
            {therapist
              ? 'Your physiotherapist has your request, including what you told us. They will set up your exercises; you’ll see them on your dashboard.'
              : 'A physiotherapist who covers this area will pick it up. You’ll see them on your dashboard once they do.'}
          </p>
          <div className="intake-actions center-row">
            <button className="secondary-button" onClick={() => go('/patient')}>Go to Today</button>
            <button className="primary-button" onClick={() => go(meId ? `/patient/${meId}/care` : '/patient')}>Track my request <ArrowRight size={15} /></button>
          </div>
        </section>
      )}
    </div>
  );
}

function Talk({ onAsk, error, onBack }) {
  const [rec, setRec] = useState(null); // { recorder, stream, ctx }
  const [seconds, setSeconds] = useState(0);
  const [typing, setTyping] = useState(false);
  const [text, setText] = useState('');
  const [micError, setMicError] = useState(null);
  const orb = useRef(null);
  const bars = useRef(null);
  const raf = useRef(0);
  const timer = useRef(0);

  useEffect(() => () => { cancelAnimationFrame(raf.current); clearInterval(timer.current); }, []);

  async function start() {
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        cancelAnimationFrame(raf.current);
        clearInterval(timer.current);
        ctx.close();
        onAsk({ audio: new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }), text });
      };
      // Live level meter: the orb and bars follow the patient's actual voice.
      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      ctx.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(data);
        const level = data.reduce((a, b) => a + b, 0) / data.length / 255;
        orb.current?.style.setProperty('--level', level.toFixed(3));
        bars.current?.querySelectorAll('i').forEach((b, i) => { b.style.transform = `scaleY(${0.12 + (data[i + 2] / 255) * 0.88})`; });
        raf.current = requestAnimationFrame(tick);
      };
      tick();
      recorder.start();
      setSeconds(0);
      timer.current = setInterval(() => setSeconds((s) => { if (s >= 119) recorder.stop(); return s + 1; }), 1000);
      setRec({ recorder });
    } catch {
      setMicError('We couldn’t open your microphone. Allow microphone access, or type instead.');
      setTyping(true);
    }
  }

  const recording = Boolean(rec);
  return (
    <section className="intake-step talk" key="talk">
      <span className="eyebrow">Step 2 of 3</span>
      <h1>Tell us what’s going on</h1>
      <p className="page-subtitle">Talk like you would to a physiotherapist: where it hurts, when it started, what makes it worse, and what you want to get back to.</p>

      <div className={`voice-stage ${recording ? 'live' : ''}`}>
        <button ref={orb} className="orb" onClick={recording ? () => rec.recorder.stop() : start}
          aria-label={recording ? 'Stop and send to the assistant' : 'Start talking to the assistant'}>
          <span className="orb-ring" /><span className="orb-ring r2" /><span className="orb-core">{recording ? <Square size={26} fill="currentColor" /> : <Mic size={34} />}</span>
        </button>
        <div className="voice-bars" ref={bars} aria-hidden="true">{Array.from({ length: 24 }, (_, i) => <i key={i} />)}</div>
        <p className="voice-hint">
          {recording ? <>Listening… <b>{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</b> · tap to finish</> : 'Tap and start talking'}
        </p>
        <p className="voice-private"><Sparkles size={13} /> Your voice is processed on this device and never sent to the cloud.</p>
      </div>

      {!recording && (
        typing ? (
          <div className="type-instead">
            <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} autoFocus
              placeholder="e.g. My right knee has hurt for two months when I go down stairs. It’s about a 6 out of 10…" />
            <button className="primary-button" disabled={text.trim().length < 10} onClick={() => onAsk({ text })}><Sparkles size={15} /> Ask the assistant</button>
          </div>
        ) : <button className="text-button type-toggle" onClick={() => setTyping(true)}><Keyboard size={14} /> I’d rather type</button>
      )}
      {(error || micError) && <p className="form-error">{error || micError}</p>}
      {!recording && <div className="intake-actions"><button className="secondary-button" onClick={onBack}><ArrowLeft size={15} /> Back</button></div>}
    </section>
  );
}

function Thinking() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = [setTimeout(() => setI(1), 2200), setTimeout(() => setI(2), 7000)];
    return () => t.forEach(clearTimeout);
  }, []);
  return (
    <section className="intake-step thinking" key="thinking" aria-live="polite">
      <div className="ai-orb" aria-hidden="true" />
      <h1>One moment…</h1>
      <ul className="stage-list">
        {STAGES.map((s, n) => <li key={s} className={n < i ? 'done' : n === i ? 'now' : ''}><span className="stage-dot">{n < i && <Check size={11} strokeWidth={3} />}</span>{s}</li>)}
      </ul>
    </section>
  );
}

function Typewriter({ text }) {
  const [n, setN] = useState(0);
  const words = text.split(' ');
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setN(words.length); return undefined; }
    const t = setInterval(() => setN((x) => (x >= words.length ? x : x + 1)), 45);
    return () => clearInterval(t);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps
  return <>{words.slice(0, n).join(' ')}<span className={n < words.length ? 'caret' : ''} /></>;
}

function Chips({ options, value, onChange }) {
  return (
    <div className="pick-row">
      {options.map(([v, l]) => (
        <button key={v} type="button" className={`pick ${value.includes(v) ? 'on' : ''}`} aria-pressed={value.includes(v)}
          onClick={() => onChange(toggle(value, v))}>{l}</button>
      ))}
    </div>
  );
}

function Review({ ai, form, setForm, error, onSend, onRetry }) {
  const set = (k) => (v) => setForm({ ...form, [k]: v });
  const [sending, setSending] = useState(false);
  return (
    <section className="intake-step review" key="review">
      <span className="eyebrow">Step 3 of 3</span>
      <div className="ai-bubble">
        <span className="ai-avatar"><Sparkles size={16} /></span>
        <div>
          <p><Typewriter text={ai.reply_to_patient} /></p>
          {ai.mood && <span className="mood">Sounds {MOOD[ai.mood]?.toLowerCase() ?? ai.mood}</span>}
        </div>
      </div>
      {ai.transcript && <blockquote className="you-said">“{ai.transcript}”</blockquote>}
      {ai.urgent && (
        <div className="attention urgent">
          <span className="attention-icon"><AlertTriangle size={18} /></span>
          <div><strong>We’ve marked this as a priority for your physiotherapist</strong>
            <p>{ai.red_flags.join(' · ')}. If it gets much worse, or you can’t put weight on it, contact a doctor.</p></div>
        </div>
      )}

      <div className="understood">
        <h2>Here’s what we understood</h2>
        <p className="muted small">Change anything that isn’t right. This is what your physiotherapist will see.</p>
        <div className="understood-grid">
          <div className="u-field wide"><span>Where</span><Chips options={AREAS} value={form.affected_areas} onChange={set('affected_areas')} /></div>
          <div className="u-field wide"><span>What you notice</span><Chips options={ISSUES} value={form.issue_types} onChange={set('issue_types')} /></div>
          <div className="u-field wide">
            <span>Pain right now {form.pain_score == null && <em>· tap a number</em>}</span>
            <div className="pain-picker">
              {Array.from({ length: 11 }, (_, n) => (
                <button key={n} type="button" className={form.pain_score === n ? 'on' : ''} style={{ '--h': `${120 - n * 12}` }}
                  onClick={() => set('pain_score')(n)} aria-label={`Pain ${n} out of 10`}>{n}</button>
              ))}
            </div>
          </div>
          <div className="u-field"><span>How long</span>
            <select value={form.duration} onChange={(e) => set('duration')(e.target.value)}>{DURATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          <div className="u-field"><span>Lately it’s</span>
            <select value={form.trend} onChange={(e) => set('trend')(e.target.value)}>{TRENDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></div>
          <div className="u-field wide"><span>Your goal</span><Chips options={GOALS} value={form.goals} onChange={set('goals')} /></div>
        </div>
        <div className="suggest">
          <div><span>Your physiotherapist may start you on</span><strong>{exerciseName(ai.suggested_exercise)}</strong><small>{ai.exercise_reason}</small></div>
          {ai.follow_up_questions?.length > 0 && (
            <div><span>They might ask you</span><ul>{ai.follow_up_questions.map((q) => <li key={q}>{q}</li>)}</ul></div>
          )}
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}
      <div className="intake-actions">
        <button className="secondary-button" onClick={onRetry}><RotateCcw size={15} /> Say it again</button>
        <button className="primary-button big" disabled={sending || form.pain_score == null || !form.affected_areas.length}
          onClick={async () => { setSending(true); await onSend(); setSending(false); }}>
          <Send size={15} /> {sending ? 'Sending…' : 'Send to a physiotherapist'}
        </button>
      </div>
      <p className="muted small center">Prepared by an AI assistant on this device ({ai.source === 'llm' ? ai.model : 'rules'}). It doesn’t diagnose; your physiotherapist decides your plan.</p>
    </section>
  );
}
