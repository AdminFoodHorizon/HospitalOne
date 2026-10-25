import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, CheckCircle2, ClipboardList, HeartPulse, LogOut, Menu, RefreshCw, Search, ShieldCheck, Stethoscope, Users, X } from 'lucide-react';
import { hospitalGet, hospitalPost, errorText } from '../services/api';
import './NursingDashboard.css';

const EMPTY = { height_cm:'', weight_kg:'', blood_pressure:'', temperature_c:'', pulse_bpm:'', spo2_percent:'', respiratory_rate:'', pain_score:'', notes:'' };
const FIELDS = [
  ['height_cm','Height','cm'], ['weight_kg','Weight','kg'], ['blood_pressure','Blood pressure','e.g. 120/80'],
  ['temperature_c','Temperature','°C'], ['pulse_bpm','Pulse','bpm'], ['spo2_percent','Oxygen saturation','%'],
  ['respiratory_rate','Respiratory rate','/min'], ['pain_score','Pain score','0–10'],
];
const time = v => v ? new Date(v).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) : '—';

export default function NursingDashboard({ hospital, profile, onLogout }) {
  const [entries,setEntries] = useState([]);
  const [loading,setLoading] = useState(true);
  const [refreshing,setRefreshing] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [query,setQuery] = useState('');
  const [selected,setSelected] = useState(null);
  const [draft,setDraft] = useState(EMPTY);
  const [started,setStarted] = useState({});
  const [busy,setBusy] = useState(false);
  const [menuOpen,setMenuOpen] = useState(false);
  const [lastSync,setLastSync] = useState(null);

  const refresh = useCallback(async (quiet=false) => {
    if (!quiet) setRefreshing(true);
    try {
      const res = await hospitalGet(hospital.slug,'nursing/queue');
      setEntries(Array.isArray(res.data?.entries) ? res.data.entries : []);
      setLastSync(new Date()); setError('');
    } catch (e) { setError(errorText(e)); }
    finally { setLoading(false); setRefreshing(false); }
  },[hospital.slug]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(() => { if (!document.hidden) refresh(true); }, 15000);
    return () => window.clearInterval(id);
  },[refresh]);

  const counts = useMemo(() => ({
    initial: entries.filter(e=>e.kind==='NURSING_INITIAL').length,
    called: entries.filter(e=>e.status==='CALLED').length,
  }),[entries]);
  const filtered = entries.filter(e => e.kind==='NURSING_INITIAL' && [e.token,e.patient?.full_name,e.patient?.patient_number].join(' ').toLowerCase().includes(query.toLowerCase()));
  const bmi = Number(draft.height_cm)>0 && Number(draft.weight_kg)>0 ? (Number(draft.weight_kg)/(Number(draft.height_cm)/100)**2).toFixed(1) : '—';

  async function action(entry, suffix, payload, success) {
    setBusy(true); setError(''); setNotice('');
    try {
      const res = await hospitalPost(hospital.slug,`nursing/queue/${entry.queue_entry_id}/${suffix}`,payload);
      setNotice(res.data?.detail || success);
      await refresh(true);
      return res.data;
    } catch (e) { setError(errorText(e)); return null; }
    finally { setBusy(false); }
  }
  async function call(entry) { await action(entry,'call',{},'Patient called'); }
  async function recall(entry) { await action(entry,'call',{},'Patient recalled'); }
  async function begin(entry) {
    const res = await action(entry,'start',{},'Assessment started');
    if (res) {
      setSelected(entry); setStarted(prev=>({...prev,[entry.queue_entry_id]:true}));
      const a=res.assessment||{};
      setDraft(Object.fromEntries(Object.keys(EMPTY).map(k=>[k,a[k]??''])));
    }
  }
  function payload() { return Object.fromEntries(Object.entries(draft).map(([k,v])=>[k,typeof v==='string'?v.trim():v])); }
  async function save() { if (selected) await action(selected,'assessment',payload(),'Draft saved'); }
  async function complete() {
    if (!selected || !window.confirm('Complete Nursing and send patient to the assigned doctor?')) return;
    const saved = await action(selected,'assessment',payload(),'Draft saved');
    if (!saved) return;
    const result = await action(selected,'complete',{confirm_complete:true},'Nursing completed');
    if (result) { setSelected(null); setDraft(EMPTY); setStarted(prev=>({...prev,[selected.queue_entry_id]:false})); }
  }
  function openEntry(entry) {
    if (started[entry.queue_entry_id]) { setSelected(entry); }
    else { begin(entry); }
  }

  return <div className="nur-app">
    <aside className={'nur-sidebar '+(menuOpen?'nur-sidebar-open':'')}>
      <div className="nur-logo"><span className="nur-logo-mark"><HeartPulse size={25}/></span><span className="nur-brand-name">{hospital?.name || "Hospital"}<small>Nursing workspace</small></span><button className="nur-mobile-close" onClick={()=>setMenuOpen(false)} aria-label="Close menu"><X size={20}/></button></div>
      <div className="nur-nav-caption">WORKSPACE</div>
      <div className="nur-nav-active"><Activity size={19}/> Nursing overview</div>
      <div className="nur-nav-caption">PATIENT QUEUES</div>
      <div className="nur-nav nur-nav-current"><Users size={18}/> Initial Nursing <span>{counts.initial}</span></div>
      <div className="nur-sidebar-bottom"><div className="nur-hospital"><ShieldCheck size={20}/><span><strong>{hospital.name}</strong><small>Protected clinical workspace</small></span></div><button className="nur-signout" onClick={onLogout}><LogOut size={18}/> Sign out</button></div>
    </aside>
    {menuOpen && <button className="nur-overlay" onClick={()=>setMenuOpen(false)} aria-label="Close menu"/>}
    <div className="nur-content">
      <header className="nur-topbar"><button className="nur-menu" onClick={()=>setMenuOpen(true)} aria-label="Open menu"><Menu size={22}/></button><span>Hospital workspace <b>/ Nursing</b></span><span className="nur-user"><ShieldCheck size={17}/> {profile?.username || profile?.user?.username || 'Nursing staff'}</span></header>
      <main className="nur-main">
        <div className="nur-heading"><div><div className="nur-eyebrow">NURSING WORKSPACE</div><h1>Nursing dashboard<span>.</span></h1><p>Call patients, record optional vital signs and coordinate doctor handoffs.</p></div><button className="nur-refresh" disabled={refreshing} onClick={()=>refresh()}><RefreshCw size={17}/> {refreshing?'Refreshing…':'Refresh'}</button></div>
        {error && <div className="nur-alert" role="alert">{error}</div>}
        {notice && <div className="nur-notice" role="status">{notice}</div>}
        <div className="nur-stats"><div className="nur-stat"><Users/><span>Initial Nursing</span><strong>{loading?'—':counts.initial}</strong><small>New patient queue</small></div><div className="nur-stat"><Activity/><span>Currently called</span><strong>{loading?'—':counts.called}</strong><small>On central announcement TV</small></div><div className="nur-stat"><Stethoscope/><span>Shared destination</span><strong>{entries.find(e=>e.room_number)?.room_number||'—'}</strong><small>Nursing Station room</small></div></div>
        <section className="nur-panel"><div className="nur-panel-head"><div><h2>Initial Nursing queue</h2><p>Showing queue entries from the last 24 hours. Recall restarts the TV countdown.</p></div><small>{lastSync?`Updated ${time(lastSync)}`:'Connecting…'}</small></div>
          <div className="nur-toolbar"><span className="nur-queue-label">Initial Nursing · Last 24 hours</span><label className="nur-search"><Search size={17}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search token or patient" aria-label="Search patients"/></label></div>
          <div className="nur-table-scroll"><table className="nur-table"><thead><tr><th>TOKEN</th><th>PATIENT</th><th>ARRIVED</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{filtered.map(e=><tr key={e.queue_entry_id}><td><strong className="nur-token">{e.token}</strong></td><td><strong>{e.patient?.full_name||'—'}</strong><small>{e.patient?.patient_number||''}</small></td><td>{time(e.queued_at)}</td><td><span className={'nur-status '+(e.status==='CALLED'?'called':'waiting')}>{e.status==='CALLED'?'Called':'Waiting'}</span></td><td>{e.status==='WAITING' ? <button disabled={busy} className="nur-action" onClick={()=>call(e)}>Call patient</button> : e.status==='CALLED' ? <div className="nur-recall-actions"><button disabled={busy} className="nur-action" onClick={()=>recall(e)} title="Announce this token again and restart the five-minute call timer">Recall patient</button><button disabled={busy} className="nur-action" onClick={()=>openEntry(e)}>{started[e.queue_entry_id]?'Continue assessment':'Start assessment'}</button></div> : <button disabled={busy} className="nur-action" onClick={()=>openEntry(e)}>{started[e.queue_entry_id]?'Continue assessment':'Open assessment'}</button>}</td></tr>)}</tbody></table></div>
          {!loading && !filtered.length && <div className="nur-empty"><ClipboardList size={28}/><strong>No patients in this queue</strong><span>New entries will appear automatically.</span></div>}
        </section>
        <div className="nur-foot"><ShieldCheck size={16}/> Hospital-scoped clinical records · Staff login and verified 2FA required</div>
      </main>
    </div>
    {selected && <div className="nur-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!busy)setSelected(null)}}><section className="nur-modal" role="dialog" aria-modal="true" aria-labelledby="nur-assessment-title"><header className="nur-modal-head"><div><div className="nur-eyebrow">INITIAL NURSING</div><h2 id="nur-assessment-title">Patient assessment</h2><p>{selected.token} · {selected.patient?.full_name} · Room {selected.room_number||'—'}</p></div><button disabled={busy} onClick={()=>setSelected(null)} aria-label="Close"><X size={22}/></button></header>
      <div className="nur-modal-body"><div className="nur-info"><CheckCircle2 size={18}/> All measurements are optional. Leave any unmeasured value blank.</div><div className="nur-fields">{FIELDS.map(([key,label,unit])=><label key={key}><span>{label} <small>({unit})</small></span><input type="text" inputMode={key==='blood_pressure'?'text':'decimal'} value={draft[key]} onChange={e=>setDraft({...draft,[key]:e.target.value})} placeholder="Optional"/></label>)}</div><div className="nur-bmi">Calculated BMI: <strong>{bmi}</strong> <small>Only when height and weight are entered</small></div><label className="nur-notes"><span>Nursing notes (optional)</span><textarea rows={3} value={draft.notes} onChange={e=>setDraft({...draft,notes:e.target.value})} placeholder="Patient symptoms, observations or other notes…"/></label></div>
      <footer className="nur-modal-actions"><button className="nur-secondary" disabled={busy} onClick={()=>setSelected(null)}>Close</button><button className="nur-secondary" disabled={busy} onClick={save}>Save draft</button><button className="nur-primary" disabled={busy} onClick={complete}>{busy?'Working…':'Complete Nursing & release'}</button></footer>
    </section></div>}
  </div>;
}
