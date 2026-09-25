import { Camera, CircleStop, Trash2, Upload, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { filmingTip } from '../exercises.js';
import { api, followSession } from '../api.js';
import { ErrorNote, Note } from './ui.jsx';

const STAGES = {
  queued: 'Waiting to start',
  converting: 'Preparing the video',
  pose: 'Finding your joints in each frame',
  analyze: 'Measuring each rep',
  render: 'Drawing the overlay',
  done: 'Done',
  failed: 'Failed',
};

// Record in the browser (camera) or upload a file, then follow the on-device analysis live.
export default function UploadPanel({ patientId, onDone, exercise }) {
  const [mode, setMode] = useState('idle'); // idle | camera | recording | selected | uploading | processing
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState(null);
  const [countdown, setCountdown] = useState(0);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedUrl, setSelectedUrl] = useState(null);
  const fileInput = useRef(null);
  const preview = useRef(null);
  const stream = useRef(null);
  const recorder = useRef(null);
  const chunks = useRef([]);
  const countdownTimer = useRef(null);

  useEffect(() => () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    if (selectedUrl) URL.revokeObjectURL(selectedUrl);
  }, [selectedUrl]);

  function selectFile(file) {
    if (!file) return;
    if (selectedUrl) URL.revokeObjectURL(selectedUrl);
    setSelectedFile(file);
    setSelectedUrl(URL.createObjectURL(file));
    setError(null);
    setMode('selected');
  }

  function discardSelection() {
    if (selectedUrl) URL.revokeObjectURL(selectedUrl);
    setSelectedFile(null);
    setSelectedUrl(null);
    if (fileInput.current) fileInput.current.value = '';
    setMode('idle');
  }

  async function submit(file, source) {
    setError(null);
    setMode('uploading');
    try {
      const { session_id } = await api.uploadSession(patientId, file, source);
      setMode('processing');
      setProgress({ stage: 'queued', progress: 0 });
      followSession(session_id, (s) => {
        setProgress(s);
        if (s.stage === 'done' || s.stage === 'failed') {
          setMode('idle');
          if (s.stage === 'failed') setError(new Error(s.error || 'Analysis failed.'));
          onDone?.(session_id);
        }
      });
    } catch (e) {
      setError(e);
      setMode('idle');
    }
  }

  async function openCamera() {
    setError(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
      setMode('camera');
      requestAnimationFrame(() => {
        if (preview.current) preview.current.srcObject = stream.current;
      });
    } catch {
      setError(new Error('Could not open the camera. Check permissions, or upload a video instead.'));
    }
  }

  function startRecording() {
    let n = 3;
    setCountdown(n);
    countdownTimer.current = setInterval(() => {
      n -= 1;
      setCountdown(n);
      if (n === 0) {
        clearInterval(countdownTimer.current);
        countdownTimer.current = null;
        chunks.current = [];
        recorder.current = new MediaRecorder(stream.current);
        recorder.current.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
        recorder.current.onstop = () => {
          stream.current.getTracks().forEach((t) => t.stop());
          const blob = new Blob(chunks.current, { type: recorder.current.mimeType || 'video/webm' });
          selectFile(new File([blob], 'recording.webm', { type: blob.type }));
        };
        recorder.current.start();
        setMode('recording');
      }
    }, 1000);
  }

  function closeCamera() {
    if (countdownTimer.current) clearInterval(countdownTimer.current);
    countdownTimer.current = null;
    if (recorder.current && recorder.current.state !== 'inactive') {
      recorder.current.onstop = null;
      recorder.current.stop();
    }
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    recorder.current = null;
    chunks.current = [];
    setCountdown(0);
    setMode('idle');
  }

  const busy = mode === 'uploading' || mode === 'processing';

  function submitSelected() {
    if (!selectedFile) return;
    const file = selectedFile;
    const source = file.name === 'recording.webm' ? 'camera' : 'upload';
    discardSelection();
    submit(file, source);
  }
  return (
    <div className="upload-panel">
      {(mode === 'camera' || mode === 'recording') && (
        <div className="camera">
          <video ref={preview} autoPlay muted playsInline />
          <div className="camera-guide">{filmingTip(exercise).split(". ")[0].replace(/\.$/, "")}</div>
          {countdown > 0 && <div className="countdown">{countdown}</div>}
          <div className="camera-actions">
            {mode === 'camera' && countdown === 0 && (
              <button className="primary-button" onClick={startRecording}><Camera size={15} /> Start recording</button>
            )}
            {mode === 'recording' && (
              <button className="danger-button" onClick={() => recorder.current.stop()}><CircleStop size={15} /> Stop recording</button>
            )}
            <button className="secondary-button camera-close" onClick={closeCamera}><X size={15} /> Close recording</button>
          </div>
        </div>
      )}

      {mode === 'selected' && (
        <div className="selected-video">
          <video src={selectedUrl} controls playsInline preload="metadata" />
          <div className="selected-video-actions">
            <button className="primary-button" onClick={submitSelected}><Upload size={15} /> Use this video</button>
            <button className="secondary-button danger-outline" onClick={discardSelection}><Trash2 size={15} /> Discard video</button>
          </div>
          <small>Preview the recording before analysis. You can discard it and choose another video.</small>
        </div>
      )}

      {mode === 'idle' && (
        <>
          <Note>{filmingTip(exercise)}</Note>
          <div className="upload-actions">
            <button className="primary-button" onClick={openCamera}><Camera size={15} /> Record with camera</button>
            <button className="secondary-button" onClick={() => fileInput.current.click()}><Upload size={15} /> Upload a video</button>
            <input ref={fileInput} type="file" accept="video/*" hidden
              onChange={(e) => selectFile(e.target.files[0])} />
          </div>
        </>
      )}

      {busy && (
        <div className="progress">
          <div className="progress-top">
            <strong>{mode === 'uploading' ? 'Uploading to this device…' : STAGES[progress?.stage] ?? 'Working…'}</strong>
            <span>{Math.round((progress?.progress ?? 0) * 100)}%</span>
          </div>
          <div className="bar"><div style={{ width: `${(progress?.progress ?? 0) * 100}%` }} /></div>
          <small>Analysed on this device. The video is not sent anywhere.</small>
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}
