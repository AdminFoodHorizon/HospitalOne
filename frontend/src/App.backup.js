import React, { useEffect, useState } from 'react';
import { Activity, ArrowLeft, ArrowRight, CheckCircle2, ClipboardList, Eye, EyeOff, HeartPulse, KeyRound, LockKeyhole, LogOut, ShieldCheck, Smartphone, Stethoscope, UserRound, Waves } from 'lucide-react';
import { api, csrf, errorText, hospitalGet, hospitalPost } from './services/api';
import './styles.css';

const HOSPITALS = [
  { slug: 'green-valley-hospital', name: 'Green Valley General Hospital' },
  { slug: 'sunrise-hospital', name: 'Sunrise Multi-Specialty Hospital' },
  { slug: 'city-care-hospital', name: 'City Care Community Hospital' },
];

function extractUri(data) { return data?.provisioning_uri || data?.otpauth_url || data?.otp_uri || data?.uri || data?.setup_uri || ''; }
function extractSecret(data) { return data?.secret || data?.manual_key || data?.totp_secret || ''; }
function TextField({ label, icon: Icon, type = 'text', value, onChange, placeholder, autoComplete, maxLength, trailing }) {
  return <label className="field"><span className="field-label">{label}</span><span className="input-wrap"><Icon size={19} aria-hidden="true"/><input required type={type} value={value} onChange={onChange} placeholder={placeholder} autoComplete={autoComplete} maxLength={maxLength}/>{trailing}</span></label>;
}

export default function App() {
  const hospital = window.location.pathname.match(/^\/hospital\/([a-z0-9-]+)\/login\/?$/)?.[1] || '';
  const validHospital = HOSPITALS.some((h) => h.slug === hospital);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [code, setCode] = useState('');
  const [recoveryCode, setRecoveryCode] = useState('');
  const [stage, setStage] = useState('login');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [setup, setSetup] = useState(null);
  const [profile, setProfile] = useState(null);
  const [recoveryCodes, setRecoveryCodes] = useState([]);

  useEffect(() => { if (validHospital) csrf().catch(() => setError('Unable to connect to Django. Check that the backend is running.')); }, [validHospital]);
  const selectedHospital = HOSPITALS.find((h) => h.slug === hospital);
  const switchStage = (next) => { setStage(next); setError(''); setNotice(''); setCode(''); setRecoveryCode(''); };
  async function run(action) { setBusy(true); setError(''); setNotice(''); try { await action(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); } }

  async function loadProfile() {
    const res = await hospitalGet(hospital, 'me');
    const data = res.data;
    if (data?.authenticated === false || data?.two_factor_verified === false || data?.requires_2fa === true) {
      throw new Error('Second-factor verification is required before accessing the dashboard.');
    }
    setProfile(data);
    switchStage('dashboard');
  }

  function login(e) {
    e.preventDefault();
    run(async () => {
      await csrf();
      const res = await hospitalPost(hospital, 'login', { username, password });
      setPassword('');
      const next = res.data?.next_step;
      if (next === 'enroll' || next === 'setup') { switchStage('enroll'); return; }
      if (next === 'verify' || next === '2fa' || res.data?.detail === 'Second factor required') { switchStage('verify'); return; }
      // Never assume a password-only response grants dashboard access.
      setError('The server did not explicitly require 2FA. Dashboard access is blocked pending security verification.');
    });
  }

  function beginEnroll() {
    run(async () => {
      const res = await hospitalPost(hospital, '2fa/enroll');
      setSetup(res.data || {});
      switchStage('confirm');
    });
  }

  function confirm(e) {
    e.preventDefault();
    run(async () => {
      const res = await hospitalPost(hospital, '2fa/confirm', { code });
      const codes = res.data?.recovery_codes || res.data?.backup_codes || [];
      setCode('');
      if (Array.isArray(codes) && codes.length) { setRecoveryCodes(codes); switchStage('recovery-save'); return; }
      setNotice('Authenticator setup confirmed. Continue to sign in with your code.');
      switchStage('verify');
    });
  }

  function verify(e) {
    e.preventDefault();
    run(async () => {
      await hospitalPost(hospital, '2fa/verify', { code });
      setCode('');
      await loadProfile();
    });
  }

  function recover(e) {
    e.preventDefault();
    run(async () => {
      await hospitalPost(hospital, '2fa/recovery-login', { code: recoveryCode, recovery_code: recoveryCode });
      setRecoveryCode('');
      await loadProfile();
    });
  }

  function logout() {
    run(async () => {
      try { await hospitalPost(hospital, 'logout'); } finally {
        setProfile(null); setSetup(null); setRecoveryCodes([]); setUsername(''); setPassword(''); switchStage('login');
        await csrf().catch(() => {});
      }
    });
  }

  if (!validHospital) return <main className="hospital-route-error"><div className="hospital-route-error-card"><h1>Hospital login link required</h1><p>Open the dedicated login URL supplied by your hospital administrator.</p><p>For security, hospital selection is not available on this page.</p></div></main>;

  return <div className="app-shell">
    <aside className="brand-panel">
      <div className="brand-mark"><div className="logo-box"><HeartPulse size={26}/></div><div><strong>HOSPITAL<span>ONE</span></strong><small>Connected care platform</small></div></div>
      <div className="brand-content"><div className="eyebrow"><span className="live-dot"/> A smarter way to care</div><h1>Better care starts with <em>better coordination.</em></h1><p>One connected workspace for every team, every department and every patient journey.</p><div className="brand-illustration"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="center-symbol"><HeartPulse size={68} strokeWidth={1.45}/></div><div className="float-tile tile-one"><Stethoscope size={19}/><span>Clinical care</span></div><div className="float-tile tile-two"><Activity size={19}/><span>Live workflow</span></div><div className="float-tile tile-three"><ClipboardList size={19}/><span>Patient records</span></div></div></div>
      <div className="brand-footer"><span><ShieldCheck size={16}/> Security-first design</span><span>© 2026 HospitalOne</span></div>
    </aside>
    <main className="auth-panel"><div className="mobile-brand"><div className="logo-box"><HeartPulse size={22}/></div><strong>HOSPITAL<span>ONE</span></strong></div><div className="auth-content">
      <div className="top-note"><span className="status-pip"/> Staff access portal</div>
      {stage === 'login' && <><div className="form-heading"><div className="heading-icon"><LockKeyhole size={24}/></div><h2>Welcome back</h2><p>Sign in securely to your hospital workspace.</p></div><form onSubmit={login} className="form-stack"><div className="hospital-identity"><span className="hospital-identity-label">HOSPITAL WORKSPACE</span><strong>{selectedHospital?.name}</strong></div><TextField label="Username" icon={UserRound} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Enter your staff username" autoComplete="username"/><TextField label="Password" icon={LockKeyhole} type={showPassword ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" autoComplete="current-password" trailing={<button type="button" className="reveal" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? 'Hide password' : 'Show password'}>{showPassword ? <EyeOff size={18}/> : <Eye size={18}/>}</button>}/><button className="primary-button" disabled={busy} type="submit">{busy ? 'Checking credentials…' : 'Continue securely'} <ArrowRight size={18}/></button></form></>}
      {stage === 'enroll' && <><div className="form-heading"><div className="heading-icon"><Smartphone size={24}/></div><h2>Protect your account</h2><p>Set up your authenticator app before accessing your dashboard.</p></div><div className="instruction-card"><div className="instruction-row"><span>01</span> Open Google Authenticator or Microsoft Authenticator.</div><div className="instruction-row"><span>02</span> Add a new account using the setup key.</div><div className="instruction-row"><span>03</span> Confirm using the six-digit code.</div></div><button className="primary-button" disabled={busy} onClick={beginEnroll}> {busy ? 'Preparing setup…' : 'Start authenticator setup'} <ArrowRight size={18}/></button></>}
      {stage === 'confirm' && <><div className="form-heading"><div className="heading-icon"><Smartphone size={24}/></div><h2>Connect authenticator</h2><p>Add this account to your authenticator app, then enter its six-digit code.</p></div><div className="setup-card"><span className="field-label">Manual setup key</span>{extractSecret(setup) ? <div className="secret-row"><code>{extractSecret(setup)}</code><button onClick={() => navigator.clipboard?.writeText(extractSecret(setup))} type="button">Copy</button></div> : <p className="helper">The server did not provide a manual key.</p>}{extractUri(setup) && <details><summary>Authenticator setup URI</summary><div className="uri-text">{extractUri(setup)}</div></details>}<p className="helper">Keep this key private. Never share it in a screenshot or message.</p></div><form onSubmit={confirm} className="form-stack"><TextField label="Authenticator code" icon={KeyRound} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} placeholder="6-digit code" maxLength={6} autoComplete="one-time-code"/><button className="primary-button" disabled={busy || code.length !== 6} type="submit">{busy ? 'Verifying…' : 'Confirm setup'} <ArrowRight size={18}/></button></form></>}
      {stage === 'verify' && <><div className="form-heading"><div className="heading-icon"><ShieldCheck size={24}/></div><h2>Verify it's you</h2><p>Enter the current six-digit code from your authenticator app.</p></div><form onSubmit={verify} className="form-stack"><TextField label="Security code" icon={KeyRound} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} placeholder="000000" maxLength={6} autoComplete="one-time-code"/><button className="primary-button" disabled={busy || code.length !== 6} type="submit">{busy ? 'Verifying…' : 'Verify & continue'} <ArrowRight size={18}/></button></form><button className="text-button" onClick={() => switchStage('recovery')}>Use a recovery code instead</button></>}
      {stage === 'recovery' && <><div className="form-heading"><div className="heading-icon"><KeyRound size={24}/></div><h2>Account recovery</h2><p>Use one of your unused recovery codes to finish signing in.</p></div><form onSubmit={recover} className="form-stack"><TextField label="Recovery code" icon={KeyRound} value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} placeholder="Enter your recovery code"/><button className="primary-button" disabled={busy || !recoveryCode.trim()} type="submit">{busy ? 'Checking…' : 'Use recovery code'} <ArrowRight size={18}/></button></form><button className="text-button" onClick={() => switchStage('verify')}><ArrowLeft size={16}/> Back to authenticator</button></>}
      {stage === 'recovery-save' && <><div className="form-heading"><div className="heading-icon"><CheckCircle2 size={24}/></div><h2>Save recovery codes</h2><p>Store these codes securely. Each can be used only once.</p></div><div className="codes-list">{recoveryCodes.map((item, i) => <code key={i}>{typeof item === 'string' ? item : JSON.stringify(item)}</code>)}</div><button className="primary-button" onClick={() => { setRecoveryCodes([]); switchStage('verify'); }}>I've saved my codes <ArrowRight size={18}/></button></>}
      {stage === 'dashboard' && <><div className="form-heading"><div className="heading-icon"><CheckCircle2 size={24}/></div><h2>Identity verified</h2><p>Signed in to {selectedHospital?.name}.</p></div><div className="success-panel"><ShieldCheck size={25}/><div><strong>Secure session active</strong><span>Clinical dashboards will be connected in the next phase.</span></div></div><div className="profile-box"><strong>Current session</strong><pre>{JSON.stringify({ username: profile?.username || profile?.user?.username || username, role: profile?.role || profile?.membership?.role || 'See server profile', hospital: selectedHospital?.name }, null, 2)}</pre></div><button className="primary-button" disabled={busy} onClick={logout}>Sign out <LogOut size={18}/></button></>}
      {error && <div role="alert" className="alert error-alert">{error}</div>}{notice && <div role="status" className="alert success-alert">{notice}</div>}
      {stage !== 'login' && stage !== 'dashboard' && <button className="back-link" onClick={() => { setSetup(null); setRecoveryCodes([]); switchStage('login'); }}><ArrowLeft size={16}/> Back to sign in</button>}
      <div className="auth-footnote"><ShieldCheck size={16}/> Protected access for authorized hospital staff only.</div>
    </div></main>
  </div>;
}
