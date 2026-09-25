// All backend calls in one place. URLs are relative (/api/...): Vite proxies them in development and the
// backend serves this app in the demo build.

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new Error('The Recovery Monitor service on this device is not reachable.');
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.status === 204 ? null : res.json();
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request('/api/health'),
  evalSummary: () => request('/api/eval/summary'),

  authSignup: (data) => request('/api/auth/signup', json('POST', data)),
  authLogin: (data) => request('/api/auth/login', json('POST', data)),
  authMe: () => request('/api/auth/me'),
  authLogout: () => request('/api/auth/logout', { method: 'POST' }),
  patientCareTeam: () => request('/api/patient/care-team'),
  createIntake: (data) => request('/api/patient/intakes', json('POST', data)),
  intakeAssist: ({ audio, text, areas }) => {
    const body = new FormData();
    if (audio) body.append('audio', audio, 'voice.webm');
    body.append('text', text || '');
    body.append('areas', JSON.stringify(areas || []));
    return request('/api/patient/intakes/assist', { method: 'POST', body });
  },
  patientIntakes: () => request('/api/patient/intakes'),
  therapistIntakes: () => request('/api/therapist/intakes'),
  claimIntake: (id) => request("/api/therapist/intakes/" + id + "/claim", { method: "POST" }),
  declineIntake: (id) => request("/api/therapist/intakes/" + id + "/decline", { method: "POST" }),
  onboarding: () => request('/api/onboarding'),
  patientOnboarding: (data) => request('/api/onboarding/patient', json('PUT', data)),
  therapistOnboarding: (data) => request('/api/onboarding/therapist', json('PUT', data)),

  patients: () => request('/api/patients'),
  patient: (id) => request(`/api/patients/${id}`),
  patientSessions: (id) => request(`/api/patients/${id}/sessions`),
  setProtocol: (id, protocol) => request(`/api/patients/${id}/protocol`, json('POST', protocol)),

  session: (id) => request(`/api/sessions/${id}`),
  uploadSession: (patientId, file, source = 'upload') => {
    const body = new FormData();
    body.append('video', file, file.name || 'recording.webm');
    body.append('source', source);
    return request(`/api/patients/${patientId}/sessions`, { method: 'POST', body });
  },
  checkIn: (patientId, sessionId, data) =>
    request(`/api/patients/${patientId}/sessions/${sessionId}/check-in`, json('POST', data)),
  deleteSession: (id) => request(`/api/sessions/${id}`, { method: 'DELETE' }),

  voiceNote: (patientId, sessionId, blob) => {
    const body = new FormData();
    body.append('audio', blob, blob.name || 'voice.webm');
    return request(`/api/patients/${patientId}/sessions/${sessionId}/voice`, { method: 'POST', body });
  },
  regenerateReport: (sessionId) => request(`/api/sessions/${sessionId}/report`, { method: 'POST' }),

  reviewQueue: () => request('/api/review-queue'),
  review: (sessionId, data) => request(`/api/sessions/${sessionId}/review`, json('POST', data)),
  referenceVideos: (exercise = 'squat') => request(`/api/reference-videos?exercise=${encodeURIComponent(exercise)}`),
  sessionTutorials: (sessionId) => request(`/api/sessions/${sessionId}/tutorials`),
  createTutorial: (sessionId, referenceVideoId) => request(`/api/sessions/${sessionId}/tutorials`, json('POST', { reference_video_id: referenceVideoId })),
  tutorial: (id) => request(`/api/tutorials/${id}`),
  updateTutorial: (id, data) => request(`/api/tutorials/${id}`, json('PATCH', data)),
  approveTutorial: (id, notes = '') => request(`/api/tutorials/${id}/approve`, json('POST', { notes })),
  requestTutorialChanges: (id, notes = '') => request(`/api/tutorials/${id}/request-changes`, json('POST', { notes })),
  patientTutorials: () => request('/api/patient/tutorials'),

};

// Live analysis progress over Server-Sent Events. Returns a function that stops listening.
export function followSession(sessionId, onUpdate) {
  const es = new EventSource(`/api/sessions/${sessionId}/events`);
  const handle = (e) => onUpdate(JSON.parse(e.data));
  es.addEventListener('progress', handle);
  es.addEventListener('done', (e) => {
    handle(e);
    es.close();
  });
  es.addEventListener('failed', (e) => {
    handle(e);
    es.close();
  });
  es.onerror = () => es.close();
  return () => es.close();
}
