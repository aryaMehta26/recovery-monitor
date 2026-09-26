import { Check, FileText, RefreshCw, Save, Sparkles, Video, Volume2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../api.js';
import { ErrorNote, Panel } from './ui.jsx';
import { useLoad } from '../hooks.js';

const splitLines = (value) => value.split('\n').map((item) => item.trim()).filter(Boolean);
const joinLines = (items = []) => items.join('\n');

export default function TutorialPanel({ session, referenceVideos = [] }) {
  const tutorials = useLoad(() => api.sessionTutorials(session.id), [session.id]);
  const [tutorial, setTutorial] = useState(null);
  const [referenceId, setReferenceId] = useState('');
  const [form, setForm] = useState(null);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [state, setState] = useState({ saving: false, mediaSaving: false, error: null });

  useEffect(() => {
    const existing = tutorials.data?.[0];
    if (existing) {
      setTutorial(existing);
      setFormFrom(existing);
    }
  }, [tutorials.data]);

  useEffect(() => {
    if (!referenceId && referenceVideos.length) {
      setReferenceId(String(session.protocol?.reference_video_id ?? referenceVideos[0].id));
    }
  }, [referenceId, referenceVideos, session.protocol?.reference_video_id]);

  function setFormFrom(value) {
    setForm({
      verified_findings: joinLines(value.verified_findings),
      coaching_cues: joinLines(value.coaching_cues),
      warnings: joinLines(value.warnings),
      captions: joinLines(value.captions),
      script: value.script || '',
    });
  }

  useEffect(() => {
    if (!tutorial?.id || !['queued', 'processing'].includes(tutorial.media?.status)) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.tutorial(tutorial.id);
        setTutorial(updated);
      } catch (error) {
        setState((current) => ({ ...current, error }));
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [tutorial?.id, tutorial?.media?.status]);

  function edit(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function generateDraft() {
    setState({ saving: true, error: null });
    try {
      const created = await api.createTutorial(session.id, Number(referenceId));
      setTutorial(created);
      setFormFrom(created);
    } catch (error) {
      setState({ saving: false, error });
      return;
    }
    setState({ saving: false, error: null });
  }

  async function generateMedia() {
    setState((current) => ({ ...current, mediaSaving: true, error: null }));
    try {
      await api.generateTutorialMedia(tutorial.id, voiceEnabled);
      setTutorial(await api.tutorial(tutorial.id));
      setState((current) => ({ ...current, mediaSaving: false }));
    } catch (error) {
      setState((current) => ({ ...current, mediaSaving: false, error }));
    }
  }

  async function saveAnd(action) {
    setState({ saving: true, error: null });
    try {
      const payload = {
        verified_findings: splitLines(form.verified_findings),
        coaching_cues: splitLines(form.coaching_cues),
        warnings: splitLines(form.warnings),
        captions: splitLines(form.captions),
        script: form.script,
      };
      let updated = await api.updateTutorial(tutorial.id, payload);
      if (action === 'approve') updated = await api.approveTutorial(tutorial.id);
      if (action === 'changes') updated = await api.requestTutorialChanges(tutorial.id);
      setTutorial(updated);
      setFormFrom(updated);
      setState({ saving: false, error: null });
      tutorials.reload();
    } catch (error) {
      setState({ saving: false, error });
    }
  }

  const editing = tutorial && tutorial.status !== 'approved';
  const reference = tutorial?.reference_video;
  const referenceUrl = reference?.url || (reference?.id ? `/api/reference-videos/${reference.id}/video` : null);
  const media = tutorial?.media;
  const mediaUrl = media?.url || null;

  return (
    <Panel title={<><Sparkles size={16} /> AI exercise tutorial</>} subtitle="Text tutorial plus an approved reference video">
      {tutorials.error && <ErrorNote error={tutorials.error} />}
      {!tutorial && (
        <>
          {!session.review && <p className="muted small">Review and decide this session first, then generate a tutorial draft from its verified evidence.</p>}
          {session.review && (
            <>
              <label className="field"><span>Approved reference video</span>
                <select value={referenceId} onChange={(event) => setReferenceId(event.target.value)} disabled={!referenceVideos.length}>
                  {!referenceVideos.length && <option value="">No reference videos available</option>}
                  {referenceVideos.map((video) => <option key={video.id} value={video.id}>{video.title}</option>)}
                </select>
              </label>
              <button type="button" className="primary-button" disabled={state.saving || !referenceId} onClick={generateDraft}>
                <Sparkles size={15} /> {state.saving ? 'Generating draft…' : 'Generate tutorial draft'}
              </button>
            </>
          )}
        </>
      )}

      {tutorial && form && (
        <div className="tutorial-editor">
          <div className="tutorial-meta"><span className={`badge ${tutorial.status === 'approved' ? 'badge-green' : tutorial.status === 'request_changes' ? 'badge-amber' : 'badge-grey'}`}>{tutorial.status.replace('_', ' ')}</span><span className="muted small">{tutorial.exercise} · {tutorial.target_reps} repetitions{tutorial.target_depth_deg ? ` · ${tutorial.target_depth_deg}° depth` : ''}</span></div>
          {referenceUrl && <div className="reference"><span className="mini-label"><Video size={13} /> Approved reference video: {reference?.title}</span><video src={referenceUrl} controls playsInline preload="metadata" /></div>}
          <div className="tutorial-media-controls">
            <label className="check"><input type="checkbox" checked={voiceEnabled} onChange={(event) => setVoiceEnabled(event.target.checked)} disabled={state.mediaSaving || media?.status === "queued" || media?.status === "processing"} /> <Volume2 size={14} /> Add local voice guidance</label>
            <button type="button" className="primary-button" disabled={state.mediaSaving || !referenceUrl || media?.status === "queued" || media?.status === "processing"} onClick={generateMedia}>
              <Video size={15} /> {state.mediaSaving ? "Generating tutorial video…" : media?.status === "ready" ? "Regenerate tutorial video" : "Generate tutorial video"}
            </button>
            {media?.status === "queued" || media?.status === "processing" ? <p className="muted small">Media generation is {media.status}…</p> : null}
            {media?.status === "failed" ? <p className="error-text">Tutorial media could not be generated. You can try again.</p> : null}
            {media?.voice_status === "unavailable" ? <p className="muted small">Video generated without voice guidance because no local TTS engine was available.</p> : null}
            {mediaUrl && <div className="reference"><span className="mini-label"><Video size={13} /> Generated tutorial preview</span><video src={mediaUrl} controls playsInline preload="metadata" /><a className="text-button" href={mediaUrl} download>Download tutorial video</a></div>}
          </div>

          <label className="field"><span>Verified movement findings</span><textarea rows={3} value={form.verified_findings} onChange={(event) => edit('verified_findings', event.target.value)} disabled={!editing} /></label>
          <label className="field"><span>Personalized coaching cues <small>(one per line)</small></span><textarea rows={3} value={form.coaching_cues} onChange={(event) => edit('coaching_cues', event.target.value)} disabled={!editing} /></label>
          <label className="field"><span>Warnings <small>(one per line)</small></span><textarea rows={3} value={form.warnings} onChange={(event) => edit('warnings', event.target.value)} disabled={!editing} /></label>
          <label className="field"><span>Captions <small>(one per line)</small></span><textarea rows={3} value={form.captions} onChange={(event) => edit('captions', event.target.value)} disabled={!editing} /></label>
          <label className="field"><span>Instruction script</span><textarea rows={4} value={form.script} onChange={(event) => edit('script', event.target.value)} disabled={!editing} /></label>
          {editing && <div className="decision-actions">
            <button type="button" className="secondary-button" disabled={state.saving} onClick={() => saveAnd('changes')}><RefreshCw size={14} /> Request changes</button>
            <button type="button" className="secondary-button" disabled={state.saving} onClick={() => saveAnd('save')}><Save size={14} /> Save edits</button>
            <button type="button" className="primary-button success" disabled={state.saving} onClick={() => saveAnd('approve')}><Check size={14} /> Approve tutorial</button>
          </div>}
          {!editing && <p className="muted small"><FileText size={13} /> This approved tutorial is now available to the patient.</p>}
          <ErrorNote error={state.error} />
        </div>
      )}
    </Panel>
  );
}
