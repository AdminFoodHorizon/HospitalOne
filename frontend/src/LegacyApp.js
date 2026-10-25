
import React, { useEffect, useState } from 'react';

import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Eye,
  EyeOff,
  HeartPulse,
  KeyRound,
  LockKeyhole,
  LogOut,
  ShieldCheck,
  Smartphone,
  Stethoscope,
  UserRound,
} from 'lucide-react';

import {
  api,
  csrf,
  errorText,
  hospitalGet,
  hospitalPost,
} from './services/api';

import { QRCodeSVG } from 'qrcode.react';

import './styles.css';

import ReceptionDashboard from './pages/ReceptionDashboard';
import NursingDashboard from './pages/NursingDashboard';

// ----------------------------------------------------
// DYNAMIC HOSPITAL ROUTING
// ----------------------------------------------------

// Example URL:
// /hospital/green-valley-hospital/login
//
// The slug comes from the URL.
// No hospital names or slugs are stored in React.

function getHospitalSlug() {
  const match = window.location.pathname.match(
    /^\/hospital\/([a-z0-9-]+)\/login\/?$/
  );

  return match ? match[1] : '';
}

// ----------------------------------------------------
// AUTHENTICATOR HELPERS
// ----------------------------------------------------

function extractUri(data) {
  return (
    data?.otpauth_uri ||
    data?.provisioning_uri ||
    data?.otpauth_url ||
    data?.otp_uri ||
    data?.uri ||
    data?.setup_uri ||
    ''
  );
}

function extractSecret(data) {
  const explicit =
    data?.secret ||
    data?.manual_key ||
    data?.totp_secret;

  if (explicit) {
    return explicit;
  }

  const uri = extractUri(data);

  if (!uri) {
    return '';
  }

  try {
    const url = new URL(uri);

    return url.protocol === 'otpauth:'
      ? url.searchParams.get('secret') || ''
      : '';
  } catch {
    return '';
  }
}

// ----------------------------------------------------
// REUSABLE INPUT
// ----------------------------------------------------

function TextField({
  label,
  icon: Icon,
  type = 'text',
  value,
  onChange,
  placeholder,
  autoComplete,
  maxLength,
  trailing,
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
      </span>

      <span className="input-wrap">
        <Icon
          size={19}
          aria-hidden="true"
        />

        <input
          required
          type={type}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          autoComplete={autoComplete}
          maxLength={maxLength}
        />

        {trailing}
      </span>
    </label>
  );
}

// ----------------------------------------------------
// MAIN APP
// ----------------------------------------------------

export default function App() {
  const hospitalSlug = getHospitalSlug();

  // Hospital information is supplied by Django.
  // It is never defined in a frontend list.

  const [hospital, setHospital] = useState(null);

  const [hospitalLoading, setHospitalLoading] =
    useState(Boolean(hospitalSlug));

  const [hospitalError, setHospitalError] =
    useState('');

  const [username, setUsername] =
    useState('');

  const [password, setPassword] =
    useState('');

  const [showPassword, setShowPassword] =
    useState(false);

  const [code, setCode] =
    useState('');

  const [recoveryCode, setRecoveryCode] =
    useState('');

  const [stage, setStage] =
    useState('login');

  const [busy, setBusy] =
    useState(false);

  const [error, setError] =
    useState('');

  const [notice, setNotice] =
    useState('');

  const [setup, setSetup] =
    useState(null);

  const [profile, setProfile] =
    useState(null);

  const [recoveryCodes, setRecoveryCodes] =
    useState([]);

  // --------------------------------------------------
  // LOAD HOSPITAL FROM DJANGO
  // --------------------------------------------------

  useEffect(() => {
    if (!hospitalSlug) {
      return;
    }

    let cancelled = false;

    async function loadHospital() {
      setHospitalLoading(true);
      setHospitalError('');
      setHospital(null);

      try {
        await csrf();

        const response = await api.get(
          `/api/hospital/${encodeURIComponent(
            hospitalSlug
          )}/public-info/`
        );

        const data = response.data;

        if (
          !data ||
          typeof data.name !== 'string' ||
          !data.name.trim() ||
          data.slug !== hospitalSlug ||
          data.is_active !== true
        ) {
          throw new Error(
            'This hospital is unavailable or its configuration is invalid.'
          );
        }

        if (!cancelled) {
          setHospital({
            slug: data.slug,
            name: data.name,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setHospitalError(
            errorText(err) ||
              'Unable to load hospital information.'
          );
        }
      } finally {
        if (!cancelled) {
          setHospitalLoading(false);
        }
      }
    }

    loadHospital();

    return () => {
      cancelled = true;
    };
  }, [hospitalSlug]);

  // --------------------------------------------------
  // COMMON HELPERS
  // --------------------------------------------------

  function switchStage(next) {
    setStage(next);
    setError('');
    setNotice('');
    setCode('');
    setRecoveryCode('');
  }

  async function run(action) {
    setBusy(true);
    setError('');
    setNotice('');

    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  // --------------------------------------------------
  // LOAD VERIFIED STAFF PROFILE
  // --------------------------------------------------

  async function loadProfile() {
    const response = await hospitalGet(
      hospitalSlug,
      'me'
    );

    const data = response.data;

    if (
      !data ||
      data.authenticated === false ||
      data.two_factor_verified === false ||
      data.requires_2fa === true
    ) {
      throw new Error(
        'Second-factor verification is required before accessing the dashboard.'
      );
    }

    setProfile(data);
    switchStage('dashboard');
  }

  // --------------------------------------------------
  // PASSWORD LOGIN
  // --------------------------------------------------

  function login(event) {
    event.preventDefault();

    if (!hospital) {
      setError(
        'Hospital information has not been verified.'
      );
      return;
    }

    run(async () => {
      await csrf();

      const response = await hospitalPost(
        hospitalSlug,
        'login',
        {
          username,
          password,
        }
      );

      setPassword('');

      const next = response.data?.next_step;

      if (
        next === 'enroll' ||
        next === 'setup'
      ) {
        switchStage('enroll');
        return;
      }

      if (
        next === 'verify' ||
        next === '2fa' ||
        response.data?.detail ===
          'Second factor required'
      ) {
        switchStage('verify');
        return;
      }

      setError(
        'The server did not explicitly require 2FA. Dashboard access is blocked pending security verification.'
      );
    });
  }

  // --------------------------------------------------
  // 2FA ENROLLMENT
  // --------------------------------------------------

  function beginEnroll() {
    run(async () => {
      const response = await hospitalPost(
        hospitalSlug,
        '2fa/enroll'
      );

      setSetup(response.data || {});
      switchStage('confirm');
    });
  }

  function confirm(event) {
    event.preventDefault();

    run(async () => {
      const response = await hospitalPost(
        hospitalSlug,
        '2fa/confirm',
        {
          code,
        }
      );

      const codes =
        response.data?.recovery_codes ||
        response.data?.backup_codes ||
        [];

      setCode('');

      if (
        Array.isArray(codes) &&
        codes.length > 0
      ) {
        setRecoveryCodes(codes);
        switchStage('recovery-save');
        return;
      }

      setSetup(null);
      switchStage('login');

      setNotice(
        'Authenticator enabled. Sign in again with your password, then enter a new authenticator code.'
      );
    });
  }

  // --------------------------------------------------
  // VERIFY 2FA
  // --------------------------------------------------

  function verify(event) {
    event.preventDefault();

    run(async () => {
      await hospitalPost(
        hospitalSlug,
        '2fa/verify',
        {
          code,
        }
      );

      setCode('');

      await loadProfile();
    });
  }

  // --------------------------------------------------
  // RECOVERY LOGIN
  // --------------------------------------------------

  function recover(event) {
    event.preventDefault();

    run(async () => {
      await hospitalPost(
        hospitalSlug,
        '2fa/recovery-login',
        {
          code: recoveryCode,
          recovery_code: recoveryCode,
        }
      );

      setRecoveryCode('');

      await loadProfile();
    });
  }

  // --------------------------------------------------
  // LOGOUT
  // --------------------------------------------------

  function logout() {
    run(async () => {
      try {
        await hospitalPost(
          hospitalSlug,
          'logout'
        );
      } finally {
        setProfile(null);
        setSetup(null);
        setRecoveryCodes([]);

        setUsername('');
        setPassword('');

        switchStage('login');

        await csrf().catch(() => {});
      }
    });
  }

  // --------------------------------------------------
  // INVALID URL
  // --------------------------------------------------

  if (!hospitalSlug) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <h1>
            Hospital login link required
          </h1>

          <p>
            Open the dedicated login URL supplied
            by your hospital administrator.
          </p>

          <p>
            Hospital selection is not available
            on this page.
          </p>
        </div>
      </main>
    );
  }

  // --------------------------------------------------
  // HOSPITAL LOADING
  // --------------------------------------------------

  if (hospitalLoading) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <HeartPulse size={36} />

          <h1>
            Loading hospital workspace
          </h1>

          <p>
            Verifying hospital information...
          </p>
        </div>
      </main>
    );
  }

  // --------------------------------------------------
  // HOSPITAL NOT FOUND / INACTIVE
  // --------------------------------------------------

  if (hospitalError || !hospital) {
    return (
      <main className="hospital-route-error">
        <div className="hospital-route-error-card">
          <ShieldCheck size={36} />

          <h1>
            Hospital workspace unavailable
          </h1>

          <p>
            {hospitalError ||
              'This hospital could not be found.'}
          </p>

          <p>
            Check your hospital login link or
            contact your administrator.
          </p>
        </div>
      </main>
    );
  }

  // --------------------------------------------------
  // RECEPTION DASHBOARD
  // --------------------------------------------------

  if (
    stage === 'dashboard' &&
    profile?.role === 'RECEPTION'
  ) {
    return (
      <ReceptionDashboard
        hospital={hospital}
        profile={profile}
        onLogout={logout}
      />
    );
  }

  // --------------------------------------------------
  // NURSING DASHBOARD
  // --------------------------------------------------

  if (
    stage === 'dashboard' &&
    profile?.role === 'NURSE'
  ) {
    return (
      <NursingDashboard
        hospital={hospital}
        profile={profile}
        onLogout={logout}
      />
    );
  }

  // --------------------------------------------------
  // AUTHENTICATION UI
  // --------------------------------------------------

  return (
    <div className="app-shell">
      <aside className="brand-panel">
        <div className="brand-mark">
          <div className="logo-box">
            <HeartPulse size={26} />
          </div>

          <div>
            <strong>
              HOSPITAL<span>ONE</span>
            </strong>

            <small>
              Connected care platform
            </small>
          </div>
        </div>

        <div className="brand-content">
          <div className="eyebrow">
            <span className="live-dot" />
            A smarter way to care
          </div>

          <h1>
            Better care starts with{' '}
            <em>better coordination.</em>
          </h1>

          <p>
            One connected workspace for every
            team, every department and every
            patient journey.
          </p>

          <div className="brand-illustration">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />

            <div className="center-symbol">
              <HeartPulse
                size={68}
                strokeWidth={1.45}
              />
            </div>

            <div className="float-tile tile-one">
              <Stethoscope size={19} />
              <span>Clinical care</span>
            </div>

            <div className="float-tile tile-two">
              <Activity size={19} />
              <span>Live workflow</span>
            </div>

            <div className="float-tile tile-three">
              <ClipboardList size={19} />
              <span>Patient records</span>
            </div>
          </div>
        </div>

        <div className="brand-footer">
          <span>
            <ShieldCheck size={16} />
            Security-first design
          </span>

          <span>
            © {new Date().getFullYear()} HospitalOne
          </span>
        </div>
      </aside>

      <main className="auth-panel">
        <div className="mobile-brand">
          <div className="logo-box">
            <HeartPulse size={22} />
          </div>

          <strong>
            HOSPITAL<span>ONE</span>
          </strong>
        </div>

        <div className="auth-content">
          <div className="top-note">
            <span className="status-pip" />
            Staff access portal
          </div>

          {/* LOGIN */}

          {stage === 'login' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <LockKeyhole size={24} />
                </div>

                <h2>
                  Welcome back
                </h2>

                <p>
                  Sign in securely to your
                  hospital workspace.
                </p>
              </div>

              <form
                onSubmit={login}
                className="form-stack"
              >
                <div className="hospital-identity">
                  <span className="hospital-identity-label">
                    HOSPITAL WORKSPACE
                  </span>

                  <strong>
                    {hospital.name}
                  </strong>
                </div>

                <TextField
                  label="Username"
                  icon={UserRound}
                  value={username}
                  onChange={(event) =>
                    setUsername(event.target.value)
                  }
                  placeholder="Enter your staff username"
                  autoComplete="username"
                />

                <TextField
                  label="Password"
                  icon={LockKeyhole}
                  type={
                    showPassword
                      ? 'text'
                      : 'password'
                  }
                  value={password}
                  onChange={(event) =>
                    setPassword(event.target.value)
                  }
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  trailing={
                    <button
                      type="button"
                      className="reveal"
                      onClick={() =>
                        setShowPassword(
                          !showPassword
                        )
                      }
                      aria-label={
                        showPassword
                          ? 'Hide password'
                          : 'Show password'
                      }
                    >
                      {showPassword ? (
                        <EyeOff size={18} />
                      ) : (
                        <Eye size={18} />
                      )}
                    </button>
                  }
                />

                <button
                  className="primary-button"
                  disabled={busy}
                  type="submit"
                >
                  {busy
                    ? 'Checking credentials…'
                    : 'Continue securely'}

                  <ArrowRight size={18} />
                </button>
              </form>
            </>
          )}

          {/* 2FA ENROLLMENT */}

          {stage === 'enroll' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <Smartphone size={24} />
                </div>

                <h2>
                  Protect your account
                </h2>

                <p>
                  Set up your authenticator app
                  before accessing your dashboard.
                </p>
              </div>

              <div className="instruction-card">
                <div className="instruction-row">
                  <span>01</span>
                  Open Google Authenticator or
                  Microsoft Authenticator.
                </div>

                <div className="instruction-row">
                  <span>02</span>
                  Add a new account using the
                  setup key.
                </div>

                <div className="instruction-row">
                  <span>03</span>
                  Confirm using the six-digit code.
                </div>
              </div>

              <button
                className="primary-button"
                disabled={busy}
                onClick={beginEnroll}
              >
                {busy
                  ? 'Preparing setup…'
                  : 'Start authenticator setup'}

                <ArrowRight size={18} />
              </button>
            </>
          )}

          {/* 2FA SETUP CONFIRMATION */}

          {stage === 'confirm' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <Smartphone size={24} />
                </div>

                <h2>
                  Connect authenticator
                </h2>

                <p>
                  Add this account to your
                  authenticator app, then enter
                  its six-digit code.
                </p>
              </div>

              <div className="setup-card">
                {extractUri(setup) && (
                  <div className="qr-wrap">
                    <QRCodeSVG
                      value={extractUri(setup)}
                      size={190}
                      level="M"
                      marginSize={2}
                      title="Authenticator setup QR code"
                    />

                    <p className="helper">
                      Scan with your authenticator
                      app. Do not share this QR code.
                    </p>
                  </div>
                )}

                <span className="field-label">
                  Manual setup key
                </span>

                {extractSecret(setup) ? (
                  <div className="secret-row">
                    <code>
                      {extractSecret(setup)}
                    </code>

                    <button
                      type="button"
                      onClick={() =>
                        navigator.clipboard?.writeText(
                          extractSecret(setup)
                        )
                      }
                    >
                      Copy
                    </button>
                  </div>
                ) : (
                  <p className="helper">
                    The server did not provide
                    a manual key.
                  </p>
                )}

                <p className="helper">
                  Keep this key private.
                  Never share it in a screenshot
                  or message.
                </p>
              </div>

              <form
                onSubmit={confirm}
                className="form-stack"
              >
                <TextField
                  label="Authenticator code"
                  icon={KeyRound}
                  value={code}
                  onChange={(event) =>
                    setCode(
                      event.target.value.replace(
                        /\D/g,
                        ''
                      )
                    )
                  }
                  placeholder="6-digit code"
                  maxLength={6}
                  autoComplete="one-time-code"
                />

                <button
                  className="primary-button"
                  disabled={
                    busy || code.length !== 6
                  }
                  type="submit"
                >
                  {busy
                    ? 'Verifying…'
                    : 'Confirm setup'}

                  <ArrowRight size={18} />
                </button>
              </form>
            </>
          )}

          {/* VERIFY 2FA */}

          {stage === 'verify' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <ShieldCheck size={24} />
                </div>

                <h2>
                  Verify it's you
                </h2>

                <p>
                  Enter the current six-digit code
                  from your authenticator app.
                </p>
              </div>

              <form
                onSubmit={verify}
                className="form-stack"
              >
                <TextField
                  label="Security code"
                  icon={KeyRound}
                  value={code}
                  onChange={(event) =>
                    setCode(
                      event.target.value.replace(
                        /\D/g,
                        ''
                      )
                    )
                  }
                  placeholder="000000"
                  maxLength={6}
                  autoComplete="one-time-code"
                />

                <button
                  className="primary-button"
                  disabled={
                    busy || code.length !== 6
                  }
                  type="submit"
                >
                  {busy
                    ? 'Verifying…'
                    : 'Verify & continue'}

                  <ArrowRight size={18} />
                </button>
              </form>

              <button
                className="text-button"
                onClick={() =>
                  switchStage('recovery')
                }
              >
                Use a recovery code instead
              </button>
            </>
          )}

          {/* RECOVERY LOGIN */}

          {stage === 'recovery' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <KeyRound size={24} />
                </div>

                <h2>
                  Account recovery
                </h2>

                <p>
                  Use one of your unused recovery
                  codes to finish signing in.
                </p>
              </div>

              <form
                onSubmit={recover}
                className="form-stack"
              >
                <TextField
                  label="Recovery code"
                  icon={KeyRound}
                  value={recoveryCode}
                  onChange={(event) =>
                    setRecoveryCode(
                      event.target.value
                    )
                  }
                  placeholder="Enter your recovery code"
                />

                <button
                  className="primary-button"
                  disabled={
                    busy ||
                    !recoveryCode.trim()
                  }
                  type="submit"
                >
                  {busy
                    ? 'Checking…'
                    : 'Use recovery code'}

                  <ArrowRight size={18} />
                </button>
              </form>

              <button
                className="text-button"
                onClick={() =>
                  switchStage('verify')
                }
              >
                <ArrowLeft size={16} />
                Back to authenticator
              </button>
            </>
          )}

          {/* SAVE RECOVERY CODES */}

          {stage === 'recovery-save' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <CheckCircle2 size={24} />
                </div>

                <h2>
                  Save recovery codes
                </h2>

                <p>
                  Store these codes securely.
                  Each can be used only once.
                </p>
              </div>

              <div className="codes-list">
                {recoveryCodes.map(
                  (item, index) => (
                    <code key={index}>
                      {typeof item === 'string'
                        ? item
                        : JSON.stringify(item)}
                    </code>
                  )
                )}
              </div>

              <button
                className="primary-button"
                onClick={() => {
                  setRecoveryCodes([]);
                  setSetup(null);

                  switchStage('login');

                  setNotice(
                    'Authenticator enabled. Sign in again with your password, then enter a new authenticator code.'
                  );
                }}
              >
                I've saved my codes —
                sign in again

                <ArrowRight size={18} />
              </button>
            </>
          )}

          {/* OTHER STAFF ROLES */}

          {stage === 'dashboard' && (
            <>
              <div className="form-heading">
                <div className="heading-icon">
                  <CheckCircle2 size={24} />
                </div>

                <h2>
                  Identity verified
                </h2>

                <p>
                  Signed in to {hospital.name}.
                </p>
              </div>

              <div className="success-panel">
                <ShieldCheck size={25} />

                <div>
                  <strong>
                    Secure session active
                  </strong>

                  <span>
                    Your dashboard will be
                    connected in the next phase.
                  </span>
                </div>
              </div>

              <div className="profile-box">
                <strong>
                  Current session
                </strong>

                <pre>
                  {JSON.stringify(
                    {
                      username:
                        profile?.username ||
                        profile?.user?.username ||
                        username,

                      role:
                        profile?.role ||
                        profile?.membership?.role ||
                        'See server profile',

                      hospital:
                        hospital.name,
                    },
                    null,
                    2
                  )}
                </pre>
              </div>

              <button
                className="primary-button"
                disabled={busy}
                onClick={logout}
              >
                Sign out

                <LogOut size={18} />
              </button>
            </>
          )}

          {/* ERRORS */}

          {error && (
            <div
              role="alert"
              className="alert error-alert"
            >
              {error}
            </div>
          )}

          {/* SUCCESS MESSAGES */}

          {notice && (
            <div
              role="status"
              className="alert success-alert"
            >
              {notice}
            </div>
          )}

          {/* BACK TO LOGIN */}

          {stage !== 'login' &&
            stage !== 'dashboard' && (
              <button
                className="back-link"
                onClick={() => {
                  setSetup(null);
                  setRecoveryCodes([]);

                  switchStage('login');
                }}
              >
                <ArrowLeft size={16} />
                Back to sign in
              </button>
            )}

          <div className="auth-footnote">
            <ShieldCheck size={16} />
            Protected access for authorized
            hospital staff only.
          </div>
        </div>
      </main>
    </div>
  );
}
