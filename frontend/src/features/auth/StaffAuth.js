import React, { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { csrf, errorText, hospitalGet, hospitalPost } from '../../services/api';
import { setAuthenticatedProfile, clearAuth } from './authSlice';
import ReceptionDashboard from '../../pages/ReceptionDashboard';
import NursingDashboard from '../../pages/NursingDashboard';
import AuthView from './AuthView';
import DoctorDashboard from '../../pages/DoctorDashboard';
import InvestigationDashboard from '../../pages/InvestigationDashboard';
import PharmacyDashboard from '../../pages/PharmacyDashboard';
import HospitalAdminDashboard from '../../pages/HospitalAdminDashboard';

export default function StaffAuth({ hospital }) {
  const slug = hospital.slug;
  const dispatch = useDispatch();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [code, setCode] = useState('');
  const [recoveryCode, setRecoveryCode] = useState('');
  const [stage, setStage] = useState('checking');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [setup, setSetup] = useState(null);
  const profile = useSelector(state => state.auth.profile);
  const setProfile = (value) => dispatch(value ? setAuthenticatedProfile(value) : clearAuth());
  const [recoveryCodes, setRecoveryCodes] = useState([]);

  // Restore only a session that Django confirms is authenticated and 2FA verified.
  // Do not modify the working login, verify, recovery, or logout handlers.
  useEffect(() => {
    let active = true;
    dispatch(clearAuth());
    setStage('checking');
    hospitalGet(slug, 'me')
      .then(({ data }) => {
        if (!active) return;
        if (data && data.authenticated !== false &&
            data.two_factor_verified !== false && data.requires_2fa !== true &&
            ['RECEPTION', 'NURSE', 'DOCTOR', 'LAB', 'PHARMACY', 'ADMIN'].includes(data.role)) {
          dispatch(setAuthenticatedProfile(data));
          setStage('dashboard');
        } else {
          setStage('login');
        }
      })
      .catch(() => { if (active) setStage('login'); });
    return () => { active = false; };
  }, [slug, dispatch]);

  function switchStage(next) {
    setStage(next); setError(''); setNotice(''); setCode(''); setRecoveryCode('');
  }
  async function run(action) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  async function loadProfile() {
    const response = await hospitalGet(slug, 'me');
    const data = response.data;
    if (!data || data.authenticated === false || data.two_factor_verified === false || data.requires_2fa === true) {
      throw new Error('Second-factor verification is required before accessing the dashboard.');
    }
    setProfile(data);
    switchStage('dashboard');
  }
  function login(event) {
    event.preventDefault();
    run(async () => {
      await csrf();
      const response = await hospitalPost(slug, 'login', { username, password });
      setPassword('');
      const next = response.data?.next_step;
      if (next === 'enroll' || next === 'setup') { switchStage('enroll'); return; }
      if (next === 'verify' || next === '2fa' || response.data?.detail === 'Second factor required') { switchStage('verify'); return; }
      throw new Error('The server did not explicitly require 2FA. Dashboard access is blocked.');
    });
  }
  function beginEnroll() {
    run(async () => { const response = await hospitalPost(slug, '2fa/enroll'); setSetup(response.data || {}); switchStage('confirm'); });
  }
  function confirm(event) {
    event.preventDefault();
    run(async () => {
      const response = await hospitalPost(slug, '2fa/confirm', { code });
      const codes = response.data?.recovery_codes || response.data?.backup_codes || [];
      setCode('');
      if (Array.isArray(codes) && codes.length) { setRecoveryCodes(codes); switchStage('recovery-save'); return; }
      setSetup(null); switchStage('login');
      setNotice('Authenticator enabled. Sign in again with your password, then enter a new authenticator code.');
    });
  }
  function verify(event) {
    event.preventDefault();
    run(async () => { await hospitalPost(slug, '2fa/verify', { code }); setCode(''); await loadProfile(); });
  }
  function recover(event) {
    event.preventDefault();
    run(async () => { await hospitalPost(slug, '2fa/recovery-login', { code: recoveryCode, recovery_code: recoveryCode }); setRecoveryCode(''); await loadProfile(); });
  }
  function logout() {
    run(async () => {
      try { await hospitalPost(slug, 'logout'); }
      finally {
        setProfile(null); setSetup(null); setRecoveryCodes([]); setUsername(''); setPassword('');
        switchStage('login'); await csrf().catch(() => {});
      }
    });
  }


  if (stage === 'checking') return <div role="status" style={{padding: 32, textAlign: 'center'}}>Checking hospital session…</div>;

  if (stage === 'dashboard' && profile?.role === 'ADMIN') return <HospitalAdminDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  if (stage === 'dashboard' && profile?.role === 'RECEPTION') return <ReceptionDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  if (stage === 'dashboard' && profile?.role === 'NURSE') return <NursingDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  if (stage === 'dashboard' && profile?.role === 'DOCTOR') return <DoctorDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  if (stage === 'dashboard' && profile?.role === 'PHARMACY') return <PharmacyDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  if (stage === 'dashboard' && profile?.role === 'LAB') return <InvestigationDashboard hospital={hospital} profile={profile} onLogout={logout}/>;
  return <AuthView {...{ hospital, username, setUsername, password, setPassword, showPassword, setShowPassword, code, setCode, recoveryCode, setRecoveryCode, stage, busy, error, notice, setup, profile, recoveryCodes, login, beginEnroll, confirm, verify, recover, logout, switchStage, setRecoveryCodes, setSetup, setNotice }} />;
}
