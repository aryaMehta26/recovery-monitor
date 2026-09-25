import * as React from 'react';
import { Activity, ArrowRight, BarChart3, Check, ClipboardList, HeartPulse, Inbox, LockKeyhole, ShieldCheck, Sparkles, Stethoscope, TrendingUp, UserRound, Users } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from './api.js';
import rehabMotionPerson from './assets/rehab-motion-person.png';
import rehabMotionPersonStanding from './assets/rehab-motion-person-standing.png';
import exerciseLibraryStrip from './assets/exercise-library-strip.png';
import { go, useLoad, usePoll, useRoute } from './hooks.js';
import { BrandMark, DeviceCard, NavGroup, Topbar } from './components/Shell.jsx';
import Evaluation from './pages/Evaluation.jsx';
import PatientHome from './pages/PatientHome.jsx';
import PhysioPatient from './pages/PhysioPatient.jsx';
import PhysioQueue from './pages/PhysioQueue.jsx';
import PhysioSession from './pages/PhysioSession.jsx';
import Privacy from './pages/Privacy.jsx';
import SignIn from './pages/SignIn.jsx';
import SignUp from './pages/SignUp.jsx';
import RoleSelect from './pages/RoleSelect.jsx';
import PatientOnboarding from './pages/PatientOnboarding.jsx';
import PatientIntake from './pages/PatientIntake.jsx';
import TherapistOnboarding from './pages/TherapistOnboarding.jsx';

export default function App() {
  const route = useRoute();
  const [area, a, b] = route;
  const isLanding = !area;
  const isAuthPage = ['signin', 'signup', 'role', 'onboarding'].includes(area);
  const health = usePoll(() => api.health(), 5000);
  const queue = usePoll(() => (area === 'physio' || area === 'evaluation' || area === 'privacy' ? api.reviewQueue().catch(() => null) : Promise.resolve(null)), 10000, [area]);
  const me = useLoad(() => api.authMe(), [area]);
  const intakes = usePoll(() => (me.data?.user?.role === 'therapist' ? api.therapistIntakes().catch(() => null) : Promise.resolve(null)), 10000, [me.data?.user?.role]);
  const newRequests = (intakes.data ?? []).filter((i) => ['pending', 'assigned'].includes(i.status)).length;
  // Who is signed in, checked again on every page change. `checkedFor` makes sure a decision is only taken
  // after the check for THIS page finished (not from a stale answer before sign-in).
  const [auth, setAuth] = useState({ checkedFor: null, user: null });
  useEffect(() => {
    let alive = true;
    api.authMe()
      .then((r) => alive && setAuth({ checkedFor: area, user: r.user ?? null }))
      .catch(() => alive && setAuth({ checkedFor: area, user: null }));
    return () => { alive = false; };
  }, [area]);
  const checked = auth.checkedFor === area;
  // Only the check for THIS page counts: a stale answer (e.g. the previous account right after switching users)
  // must never drive a redirect.
  const user = checked ? auth.user : null;

  // Page guard (the server enforces the same rules): signed-out users go to sign-in, patients only see their
  // own portal, therapists use the care-team pages.
  const needsLogin = area === 'patient' || area === 'physio';
  let redirect = null;
  if (needsLogin && checked && !user) redirect = '/signin';
  else if (user?.role === 'patient' && area === 'physio') redirect = `/patient/${user.id}`;
  else if (user?.role === 'patient' && area === 'patient' && a && a !== 'intake' && a !== user.id) redirect = `/patient/${user.id}`;
  else if (user?.role === 'therapist' && area === 'patient' && a && a !== 'intake') redirect = `/physio/patient/${a}`;
  useEffect(() => {
    if (redirect) go(redirect);
  }, [redirect]);
  if (needsLogin && (!checked || redirect)) {
    return <div className="auth-shell"><p className="muted">Checking your sign-in…</p></div>;
  }

  let page;
  if (area === 'signin') page = <SignIn />;
  else if (area === 'signup') page = <SignUp />;
  else if (area === 'role') page = <RoleSelect />;
  else if (area === 'onboarding' && a === 'patient') page = <PatientOnboarding />;
  else if (area === 'onboarding' && a === 'therapist') page = <TherapistOnboarding />;
  else if (area === 'patient' && a === 'intake') page = <PatientIntake />;
  else if (area === 'patient' && (a || me.data?.user?.role === 'patient')) page = <PatientHome key={`${a}-${b}`} patientId={a ?? me.data.user.id} view={['progress', 'care'].includes(b) ? b : 'today'} />;
  else if (area === 'physio' && a === 'session' && b) page = <PhysioSession key={b} sessionId={b} />;
  else if (area === 'physio' && a === 'patient' && b) page = <PhysioPatient key={b} patientId={b} />;
  else if (area === 'physio') page = <PhysioQueue key={a ?? 'queue'} view={['requests', 'patients'].includes(a) ? a : 'queue'} />;
  else if (area === 'evaluation') page = <Evaluation />;
  else if (area === 'privacy') page = <Privacy />;
  else page = <RolePicker user={me.data?.user} />;

  // Keep the signed-in person's own section in the sidebar on the shared pages (Accuracy, Privacy) too.
  const role = area === 'patient' || area === 'physio' ? area
    : { therapist: 'physio', patient: 'patient' }[me.data?.user?.role] ?? null;
  const patientRouteId = (area === 'patient' && a && a !== 'intake' && a) || me.data?.user?.id;
  const pa = area === 'patient';
  const nav = role === 'patient'
    ? [[`/patient/${patientRouteId}`, 'Today', HeartPulse, pa && a !== 'intake' && !b, null, 'pink'],
       [`/patient/${patientRouteId}/progress`, 'My progress', TrendingUp, pa && b === 'progress', null, 'blue'],
       [`/patient/${patientRouteId}/care`, 'Care team', Stethoscope, pa && b === 'care', null, 'green'],
       ['/patient/intake', 'Ask AI', Sparkles, pa && a === 'intake', null, 'violet']]
    : role === 'physio'
      ? [['/physio', 'Review queue', ClipboardList, area === 'physio' && (!a || a === 'session'), queue.data?.length, 'orange'],
         ['/physio/requests', 'New requests', Inbox, area === 'physio' && a === 'requests', newRequests, 'violet'],
         ['/physio/patients', 'Patients', Users, area === 'physio' && (a === 'patients' || a === 'patient'), null, 'blue']]
      : [];
  const h = health.data;
  const crumbs = area === 'physio'
    ? (a === 'requests' ? [['New requests']] : a === 'patients' ? [['Patients']]
      : a === 'patient' ? [['Patients', '/physio/patients'], ['Patient']]
        : [['Review queue', '/physio'], ...(a === 'session' ? [['Session review']] : [])])
    : area === 'patient' ? [[a === 'intake' ? 'Ask AI' : { progress: 'My progress', care: 'Care team' }[b] ?? 'Today']]
      : area === 'evaluation' ? [['Accuracy']] : area === 'privacy' ? [['Privacy']] : [['Recovery Monitor']];

  if (isAuthPage) return <div className="auth-shell">{page}</div>;

  return (
    <div className={`app-shell ${isLanding ? 'landing-shell' : ''}`}>
      <aside className="sidebar">
        <div className="sidebar-aurora" aria-hidden="true" />
        <button className="brand" onClick={() => go('/')}>
          <BrandMark />
          <span><strong>Recovery Monitor</strong><small>On-device rehab evidence</small></span>
        </button>
        {nav.length > 0 && <div className="nav-label">{role === 'patient' ? 'Patient' : 'Physiotherapist'}</div>}
        {nav.length > 0 && <NavGroup items={nav.map(([path, label, Icon, active, count, tint]) => ({ path, label, Icon, active, count, tint }))} />}
        <div className="nav-label lower">About this system</div>
        <NavGroup items={[
          { path: '/evaluation', label: 'Accuracy', Icon: BarChart3, tint: 'blue', active: area === 'evaluation' },
          { path: '/privacy', label: 'Privacy', Icon: LockKeyhole, tint: 'green', active: area === 'privacy' },
          { path: '/', label: 'Switch role', Icon: UserRound, tint: 'grey', active: false },
        ]} />
        <div className="spacer" />
        <DeviceCard health={h} />
      </aside>

      <main className="main-shell">
        <Topbar health={h} user={me.data?.user && { ...me.data.user, name: me.data.profile?.name }} crumbs={crumbs} />
        <div className="content">{page}</div>
      </main>
    </div>
  );
}

function RolePicker({ user }) {
  const patients = useLoad(() => api.patients(), []);
  const demoPatient = patients.data?.[0];
  const scrollToStory = () => document.getElementById('story')?.scrollIntoView({ behavior: 'smooth' });

  return (
    <div className="landing-page">
      <header className="landing-nav">
        <button className="landing-brand" onClick={() => go('/')} aria-label="Recovery Monitor home">
          <span className="brand-mark"><Activity size={18} /></span>
          <span><strong>Recovery Monitor</strong><small>On-device rehab evidence</small></span>
        </button>
        <nav className="landing-links" aria-label="About Recovery Monitor">
          <button onClick={scrollToStory}>How it works</button>
          <button onClick={() => go('/evaluation')}>Accuracy</button>
          <button onClick={() => go('/privacy')}>Privacy</button>
        </nav>
        <button className="nav-login" onClick={() => go(user ? (user.role === 'therapist' ? '/physio' : `/patient/${user.id}`) : '/signin')}>{user ? 'Open dashboard' : 'Sign in'} <ArrowRight size={15} /></button>
      </header>

      <main>
        <section className="landing-hero">
          <div className="hero-copy">
            <span className="eyebrow"><Sparkles size={13} /> Rehabilitation, made visible</span>
            <h1>The evidence layer <em>between appointments.</em></h1>
            <p className="hero-subtitle">Recovery Monitor turns everyday exercise into structured movement evidence—helping care teams see what is happening between visits, while keeping patients engaged in the work of recovery.</p>
            <div className="hero-actions">
              <button className="primary-button hero-button" onClick={() => go('/signin')}>Explore the patient experience <ArrowRight size={16} /></button>
              <button className="secondary-button hero-button" onClick={() => go('/signin')}>See the care-team workflow</button>
            </div>
            <p className="landing-note"><ShieldCheck size={15} /> Private by design. Analysis runs on this device.</p>
          </div>
          <div className="hero-orbit" aria-hidden="true">
            <div className="orbit-glow" />
            <div className="orbit-card orbit-card-main">
              <div className="orbit-card-top"><span className="mini-status"><span /> Live movement sample</span><span>Today</span></div>
              <div className="motion-figure-image"><img className="figure-standing" src={rehabMotionPersonStanding} alt="3D rehabilitation motion figure standing" /><img className="figure-squat" src={rehabMotionPerson} alt="3D rehabilitation motion figure in a squat" /></div>
              <div className="orbit-metric"><strong>04</strong><span>of 10 reps measured</span></div>
              <div className="orbit-bars"><i /><i /><i /><i /><i /><i /><i /><i /><i /><i /></div>
            </div>
            <div className="floating-chip chip-confidence"><Check size={14} /> Clear movement</div>
            <div className="floating-chip chip-local"><span className="pulse-dot" /> Local analysis</div>
          </div>
        </section>

        <section className="landing-exercises">
          <div className="section-intro"><span className="eyebrow">Dataset-backed movement library</span><h2>One platform. More ways to move.</h2><p>The research set spans six movement patterns. Squat is our current full product workflow; this library shows the path toward broader rehabilitation coverage.</p></div>
          <div className="exercise-strip-frame"><img src={exerciseLibraryStrip} alt="Six 3D rehabilitation exercise poses: arm abduction, arm V/W, push-up, leg abduction, lunge, and squat" /></div>
          <div className="exercise-labels" aria-label="Exercise coverage">
            <div><span>01</span><strong>Arm abduction</strong><small>Research coverage</small></div>
            <div><span>02</span><strong>Arm V/W</strong><small>Research coverage</small></div>
            <div><span>03</span><strong>Push-up</strong><small>Research coverage</small></div>
            <div><span>04</span><strong>Leg abduction</strong><small>Research coverage</small></div>
            <div><span>05</span><strong>Leg lunge</strong><small>Research coverage</small></div>
            <div className="exercise-live"><span>06</span><strong>Squat</strong><small>Current full workflow</small></div>
          </div>
        </section>

        <section className="landing-story" id="story">
          <div className="section-intro"><span className="eyebrow">The product loop</span><h2>Less guesswork. More useful signal.</h2><p>Recovery Monitor gives each side of the care relationship a clearer next step—without asking the patient to become a data scientist.</p></div>
          <div className="story-grid">
            <article><span className="story-number">01</span><h3>Capture the moment</h3><p>A short exercise video becomes a repeatable record of what happened at home.</p></article>
            <article><span className="story-number">02</span><h3>Translate movement</h3><p>Depth, timing, tracking quality, and change are organized into evidence people can understand.</p></article>
            <article><span className="story-number">03</span><h3>Extend the visit</h3><p>Therapists spend less time guessing what happened between appointments and more time deciding what to do next.</p></article>
          </div>
        </section>

        <section className="landing-proof">
          <div className="section-intro"><span className="eyebrow">Why this can matter at scale</span><h2>A clearer operating layer for recovery at home.</h2><p>Built around the moments that are usually invisible: the exercise, the signal, and the decision that follows.</p></div>
          <div className="proof-grid">
            <article className="proof-card proof-card-featured"><span className="proof-kicker">For care teams</span><h3>Make remote progress reviewable.</h3><p>Bring structured movement evidence into the space between appointments, with flags that invite a professional review rather than replace one.</p><button className="proof-link" onClick={() => go('/signin')}>Open the review workflow <ArrowRight size={15} /></button></article>
            <article className="proof-card"><span className="proof-kicker">For patients</span><h3>Make effort feel visible.</h3><p>Patients get a calmer feedback loop: record, understand the result, report how they feel, and keep going.</p></article>
            <article className="proof-card"><span className="proof-kicker">For organizations</span><h3>Privacy is part of the product.</h3><p>On-device inference keeps sensitive movement data close to the people and systems responsible for care.</p></article>
          </div>
        </section>

        <section className="landing-roles">
          <div className="section-intro"><span className="eyebrow">Two perspectives, one recovery</span><h2>Choose your space.</h2></div>
          <div className="role-grid">
            <div className="role-card landing-role-card patient-role">
              <div className="role-icon"><HeartPulse size={19} /></div><h2>For patients</h2><p>A gentle place to record today’s movement, understand the result, and share how your body feels.</p>
              <button className="text-button" onClick={() => go('/signin')}>Patient login <ArrowRight size={15} /></button>
              {patients.error && <span className="muted small">Demo access is temporarily unavailable.</span>}
            </div>
            <div className="role-card landing-role-card physio-role">
              <div className="role-icon"><ClipboardList size={19} /></div><h2>For physiotherapists</h2><p>A focused review queue for the sessions that deserve a closer look, with the final decision always yours.</p>
              <button className="text-button" onClick={() => go('/signin')}>Physiotherapist login <ArrowRight size={15} /></button>
            </div>
          </div>
        </section>

        <section className="landing-trust">
          <div><ShieldCheck size={23} /><strong>Your movement stays yours.</strong><p>Local inference, transparent measurements, and a clear therapist approval step.</p></div>
          <button className="secondary-button" onClick={() => go('/privacy')}>Explore privacy <ArrowRight size={15} /></button>
        </section>
      </main>
      <footer className="landing-footer"><span>Recovery Monitor</span><span>Demo experience · Not a medical device</span><span>Public sample data: REHAB24-6</span></footer>
    </div>
  );
}
