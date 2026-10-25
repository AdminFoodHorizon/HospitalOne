import ReceptionDirectEmail from './ReceptionDirectEmail';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, ArrowRight, CalendarDays, CheckCircle2, ClipboardPlus, Clock3, HeartPulse, LayoutDashboard, LogOut, Menu, RefreshCw, Search, ShieldCheck, Stethoscope, Ticket, UserRound, Users, X } from 'lucide-react';
import { hospitalGet, hospitalPost, errorText } from '../services/api';
import './ReceptionDashboard.css';
import ReceptionPharmacyFinalization from './ReceptionPharmacyFinalization';
import {
  ReceptionPatientHistory
} from './ReceptionPharmacyFinalization';
import './InvestigationBills.css';
import {
  FileText,
  BellRing,
  RotateCcw,
  Send,
  Printer
} from 'lucide-react';

const stateNames = { NURSING_INITIAL:'Nursing queue', DOCTOR_WAIT:'Waiting for doctor', DOCTOR_ACTIVE:'With doctor', TEST_POOL:'Tests in progress', NURSING_RETURN:'Return to nursing', DOCTOR_RECALL:'Doctor recall', PHARMACY:'Pharmacy', COMPLETE:'Completed', CANCELLED:'Cancelled' };
const stateTones = { NURSING_INITIAL:'amber', DOCTOR_WAIT:'amber', DOCTOR_ACTIVE:'blue', TEST_POOL:'violet', NURSING_RETURN:'amber', DOCTOR_RECALL:'amber', PHARMACY:'blue', COMPLETE:'green', CANCELLED:'red' };
const fmtTime = value => value ? new Date(value).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '—';
const initialForm = {full_name:'',date_of_birth:'',sex:'',phone:'',email:'',address:'',emergency_contact_name:'',emergency_contact_phone:'',allergies:'',current_medications:'',medical_history:'',doctor_id:'',patient_id:'',mode:'new'};

export default function ReceptionDashboard({ hospital, profile, onLogout }) {
  const [doctors,setDoctors] = useState([]);
  const [visits,setVisits] = useState([]);
  const [loading,setLoading] = useState(true);
  const [refreshing,setRefreshing] = useState(false);
  const [error,setError] = useState('');
  const [formError,setFormError] = useState('');
  const [form,setForm] = useState(initialForm);
  const [submitting,setSubmitting] = useState(false);
  const [registration,setRegistration] = useState(null);
  const [showForm,setShowForm] = useState(false);
  const [query,setQuery] = useState('');
  const [filter,setFilter] = useState('ALL');
  const [menuOpen,setMenuOpen] = useState(false);
  const [lastSync,setLastSync] = useState(null);
  const [patientSearch,setPatientSearch] = useState('');
  const [patientMatches,setPatientMatches] = useState([]);
  const [searchingPatients,setSearchingPatients] = useState(false);
  const [selectedPatient,setSelectedPatient] = useState(null);
  const [searchError,setSearchError] = useState('');
  const [reviewVisit,setReviewVisit] = useState(null);
  const [reviewSubmitting,setReviewSubmitting] = useState(false);
  const [reviewError,setReviewError] = useState('');
  const [reviewNotice,setReviewNotice] = useState('');
  const [workspaceTab,setWorkspaceTab] = useState('dashboard');

  const refresh = useCallback(async (quiet=false) => {
    if (!quiet) setRefreshing(true);
    try {
      const [doctorResponse,visitResponse] = await Promise.all([
        hospitalGet(hospital.slug,'reception/doctors'),
        hospitalGet(hospital.slug,'reception/visits')
      ]);
      setDoctors(Array.isArray(doctorResponse.data?.doctors) ? doctorResponse.data.doctors : []);
      setVisits(Array.isArray(visitResponse.data?.visits) ? visitResponse.data.visits : []);
      setError(''); setLastSync(new Date());
    } catch (e) { setError(errorText(e)); }
    finally { setLoading(false); setRefreshing(false); }
  },[hospital.slug]);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(() => { if (!document.hidden) refresh(true); }, 30000);
    return () => window.clearInterval(interval);
  },[refresh]);

  const counts = useMemo(() => ({
    total:visits.length,
    waiting:visits.filter(v=>['NURSING_INITIAL','DOCTOR_WAIT','NURSING_RETURN','DOCTOR_RECALL'].includes(v.state)).length,
    active:visits.filter(v=>['DOCTOR_ACTIVE','TEST_POOL','PHARMACY'].includes(v.state)).length,
    completed:visits.filter(v=>v.state==='COMPLETE').length
  }),[visits]);
  const filtered = useMemo(() => visits.filter(v => {
    if (filter==='WAITING' && !['NURSING_INITIAL','DOCTOR_WAIT','NURSING_RETURN','DOCTOR_RECALL'].includes(v.state)) return false;
    if (filter==='ACTIVE' && !['DOCTOR_ACTIVE','TEST_POOL','PHARMACY'].includes(v.state)) return false;
    if (filter==='COMPLETE' && v.state!=='COMPLETE') return false;
    const haystack = [v.queue_token,v.patient?.full_name,v.patient?.patient_number,v.visit_number,v.doctor?.name].join(' ').toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  }),[visits,filter,query]);

  useEffect(() => {
    if (!showForm || form.mode !== 'existing' || patientSearch.trim().length < 2) {
      setPatientMatches([]); setSearchingPatients(false); return;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setSearchingPatients(true); setSearchError('');
      try {
        const response = await hospitalGet(hospital.slug, 'reception/patients/search', {params:{q:patientSearch.trim()}});
        if (!cancelled) setPatientMatches(response.data?.patients || []);
      } catch (e) { if (!cancelled) {setPatientMatches([]);setSearchError(errorText(e));} }
      finally {if (!cancelled) setSearchingPatients(false);}
    }, 350);
    return () => { cancelled=true; window.clearTimeout(timer); };
  }, [hospital.slug,patientSearch,form.mode,showForm]);

  function changeMode(mode) {
    setForm({...initialForm,mode}); setSelectedPatient(null);
    setPatientSearch('');setPatientMatches([]);setFormError('');setSearchError('');
  }

  async function submit(e) {
    e.preventDefault(); setFormError(''); setRegistration(null);
    if (!form.doctor_id) {setFormError('Please select an available doctor.');return;}
    if (form.mode==='new' && !form.full_name.trim()) {setFormError('Full name is required.');return;}
    if (form.mode==='existing' && !selectedPatient) {setFormError('Search for and select an existing patient.');return;}
    setSubmitting(true);
    try {
      const payload={doctor_id:Number(form.doctor_id)};
      if (form.mode==='existing') payload.patient_id=selectedPatient.id;
      else ['full_name','date_of_birth','sex','phone','email','address','emergency_contact_name','emergency_contact_phone','allergies','current_medications','medical_history'].forEach(key=>{payload[key]=form[key].trim();});
      const response=await hospitalPost(hospital.slug,'reception/register',payload);
      setRegistration(response.data?.visit || null);setForm(initialForm);
      setSelectedPatient(null);setPatientSearch('');setPatientMatches([]);
      await refresh(true);
    } catch (err) {setFormError(errorText(err));}
    finally {setSubmitting(false);}
  }

  async function confirmReview() {
    if (!reviewVisit || reviewSubmitting) return;
    setReviewSubmitting(true);
    setReviewError('');
    try {
      await hospitalPost(
        hospital.slug,
        `reception/visits/${reviewVisit.id}/return-for-review`,
        {}
      );
      setReviewNotice(`${reviewVisit.patient?.full_name || 'Patient'} sent to the doctor's review queue.`);
      setReviewVisit(null);
      await refresh(true);
    } catch (err) {
      setReviewError(errorText(err));
    } finally {
      setReviewSubmitting(false);
    }
  }

  const title = hospital.name;
  return <div className="rec-app">
    <aside className={'rec-sidebar '+(menuOpen?'rec-sidebar-open':'')}>
      <div className="rec-logo"><span className="rec-logo-icon"><HeartPulse size={24}/></span><span className="rec-brand-name">{hospital?.name || 'Hospital'}<small>Reception workspace</small></span><button className="rec-mobile-close" onClick={()=>setMenuOpen(false)} aria-label="Close navigation"><X size={20}/></button></div>
      <div className="rec-sidebar-section">WORKSPACE</div>
      <button type="button" className={workspaceTab==='dashboard'?'rec-nav-active':'rec-nav-disabled'} onClick={()=>{setWorkspaceTab('dashboard');setMenuOpen(false);}}><LayoutDashboard size={19}/> Reception workspace</button>
      <button type="button" className={workspaceTab==='reports'?'rec-nav-active':'rec-nav-disabled'} onClick={()=>{setWorkspaceTab('reports');setMenuOpen(false);}}><FileText size={19}/> Investigation Reports</button>
      <button type="button" className={workspaceTab==='pharmacy'?'rec-nav-active':'rec-nav-disabled'} onClick={()=>{setWorkspaceTab('pharmacy');setMenuOpen(false);}}><ClipboardPlus size={19}/> Pharmacy completed</button>
      <button type="button" className={workspaceTab==='history'?'rec-nav-active':'rec-nav-disabled'} onClick={()=>{setWorkspaceTab('history');setMenuOpen(false);}}><Search size={19}/> More · Patient records</button>
      <div className="rec-sidebar-bottom"><div className="rec-hospital-card"><span className="rec-hospital-icon"><ShieldCheck size={18}/></span><div><strong>{title}</strong><small>Protected hospital workspace</small></div></div><button className="rec-signout" onClick={onLogout}><LogOut size={18}/> Sign out</button></div>
    </aside>
    {menuOpen && <button className="rec-overlay" onClick={()=>setMenuOpen(false)} aria-label="Close navigation"/>}
    <div className="rec-content">
      <header className="rec-topbar"><div className="rec-top-left"><button className="rec-menu" onClick={()=>setMenuOpen(true)} aria-label="Open navigation"><Menu size={22}/></button><div className="rec-breadcrumb">Hospital workspace <span>/</span> <strong>Reception</strong></div></div><div className="rec-top-right"><span className="rec-live"><span/> Secure session</span><div className="rec-user"><div className="rec-avatar"><UserRound size={19}/></div><div><strong>{profile?.username || profile?.user?.username || 'Reception staff'}</strong><small>Reception staff</small></div></div></div></header>
      <main className="rec-main">
        {workspaceTab === 'reports' ? <ReceptionReports hospital={hospital} doctors={doctors} refreshVisits={()=>refresh(true)}/> : workspaceTab === 'pharmacy' ? <ReceptionPharmacyFinalization hospital={hospital} refreshVisits={()=>refresh(true)}/> : workspaceTab === 'history' ? <ReceptionPatientHistory hospital={hospital}/> : <>
        <div className="rec-heading"><div><div className="rec-overline"><span/> RECEPTION WORKSPACE</div><h1>Reception dashboard<span className="rec-heading-dot">.</span></h1><p>Register patients, assign doctors and manage today's hospital visits.</p></div><button className="rec-main-action" onClick={()=>{setShowForm(true);setRegistration(null);setFormError('');}}><ClipboardPlus size={19}/> New registration <ArrowRight size={17}/></button></div>
        {reviewNotice && <div className="rec-review-notice" role="status"><CheckCircle2 size={18}/><span>{reviewNotice}</span><button type="button" onClick={()=>setReviewNotice('')} aria-label="Dismiss message"><X size={16}/></button></div>}
        {error && <div className="rec-alert" role="alert">{error} <button onClick={()=>refresh()}>Try again</button></div>}
        <div className="rec-stats">
          {[{label:'Total visits today',value:counts.total,icon:Users,style:'teal',sub:'Registered today'},{label:'Waiting patients',value:counts.waiting,icon:Clock3,style:'amber',sub:'Awaiting next stage'},{label:'In progress',value:counts.active,icon:Activity,style:'blue',sub:'Receiving care'},{label:'Completed visits',value:counts.completed,icon:CheckCircle2,style:'green',sub:'Finished today'}].map(s=><div className="rec-stat" key={s.label}><div className="rec-stat-top"><span>{s.label}</span><div className={'rec-stat-icon '+s.style}><s.icon size={21}/></div></div><div className="rec-stat-value">{loading?'—':s.value}</div><div className="rec-stat-sub">{s.sub}</div></div>)}
        </div>
        <div className="rec-section-grid"><section className="rec-panel rec-doctors"><div className="rec-panel-header"><div><h2>Available doctors</h2><p>Currently on-duty medical staff</p></div><span className="rec-count">{doctors.length} on duty</span></div><div className="rec-doctor-list">{doctors.length ? doctors.map(d=><div className="rec-doctor" key={d.id}><div className="rec-doctor-icon"><Stethoscope size={20}/></div><div className="rec-doctor-details"><strong>{d.name}</strong><span>{d.department || 'Medical department'}</span></div><div className="rec-room"><span>ROOM</span><strong>{d.room_number || 'Not set'}</strong></div></div>) : <div className="rec-empty-inline">No on-duty doctors available. Ask your hospital administrator to update doctor availability.</div>}</div></section><section className="rec-panel rec-guide"><div className="rec-panel-header"><div><h2>Registration workflow</h2><p>How each new visit begins</p></div><Ticket size={22}/></div><div className="rec-steps"><div><span>01</span><p><strong>Register a visit</strong><small>Complete the patient intake or search existing records.</small></p></div><div><span>02</span><p><strong>Assign an on-duty doctor</strong><small>The doctor is linked to the visit.</small></p></div><div><span>03</span><p><strong>Issue a queue token</strong><small>Django creates a monthly token and nursing queue entry.</small></p></div></div></section></div>
        <section className="rec-panel rec-visits"><div className="rec-panel-header rec-visits-header"><div><h2>Today's patient visits</h2><p>Live records from your hospital database</p></div><div className="rec-sync"><span>{lastSync?`Updated ${fmtTime(lastSync)}`:'Connecting…'}</span><button disabled={refreshing} onClick={()=>refresh()} aria-label="Refresh patient visits"><RefreshCw size={17} className={refreshing?'rec-spin':''}/></button></div></div><div className="rec-table-toolbar"><div className="rec-search"><Search size={18}/><input aria-label="Search visits" placeholder="Search token, patient, visit or doctor" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="rec-filters">{[['ALL','All'],['WAITING','Waiting'],['ACTIVE','In progress'],['COMPLETE','Completed']].map(([id,label])=><button key={id} className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div></div><div className="rec-table-wrap"><table className="rec-table"><thead><tr><th>QUEUE TOKEN</th><th>PATIENT</th><th>ASSIGNED DOCTOR</th><th>REGISTERED</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{filtered.map(v=><tr key={v.id}><td><span className="rec-token">{v.queue_token || '—'}</span></td><td><strong>{v.patient?.full_name || '—'}</strong><small>{v.patient?.patient_number || '—'}</small></td><td><strong>{v.doctor?.name || '—'}</strong><small>{v.doctor?.department || '—'}{v.doctor?.room_number?` · Room ${v.doctor.room_number}`:''}</small></td><td>{fmtTime(v.registered_at)}</td><td><span className={'rec-status '+(stateTones[v.state]||'gray')}><span/>{stateNames[v.state]||v.state}</span></td><td>{v.state==='TEST_POOL' ? <button type="button" className="rec-review-button" onClick={()=>setWorkspaceTab('reports')}>Investigation reports <ArrowRight size={15}/></button> : <span className="rec-no-action">—</span>}</td></tr>)}</tbody></table>{!loading&&!filtered.length&&<div className="rec-table-empty"><CalendarDays size={29}/><strong>{visits.length?'No matching visits':'No visits registered today'}</strong><span>{visits.length?'Try changing your search or filter.':'New registrations will appear here automatically.'}</span></div>}{loading&&<div className="rec-table-empty">Loading today's visits…</div>}</div><div className="rec-table-foot">Showing {filtered.length} of {visits.length} most recent visits today · Refreshes every 30 seconds</div></section>
        <div className="rec-bottom-note"><ShieldCheck size={16}/> Hospital-scoped records · Access requires verified staff authentication</div>
        <ReceptionInvestigationSection hospital={hospital}/>
        </>}
      </main>
    </div>
    {reviewVisit && <div className="rec-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!reviewSubmitting)setReviewVisit(null)}}>
      <div className="rec-modal rec-review-modal" role="dialog" aria-modal="true" aria-labelledby="rec-review-title">
        <div className="rec-modal-head"><div><div className="rec-overline">PATIENT RETURN CONFIRMATION</div><h2 id="rec-review-title">Return for doctor review</h2><p>Confirm the patient has physically returned to Reception. Django will verify test readiness before allowing the transfer.</p></div><button type="button" aria-label="Close review dialog" disabled={reviewSubmitting} onClick={()=>setReviewVisit(null)}><X size={20}/></button></div>
        <div className="rec-review-summary"><span className="rec-token">{reviewVisit.queue_token || '—'}</span><div><strong>{reviewVisit.patient?.full_name || 'Patient'}</strong><small>{reviewVisit.patient?.patient_number || '—'}</small></div></div>
        <div className="rec-review-detail"><Stethoscope size={19}/><div><strong>Assigned doctor</strong><span>{reviewVisit.doctor?.name || '—'}{reviewVisit.doctor?.room_number ? ` · Room ${reviewVisit.doctor.room_number}` : ''}</span></div></div>
        <p className="rec-review-help">Only confirm after the patient is present. If reports are incomplete, the server will reject the transfer and the patient will remain in the test stage.</p>
        {reviewError && <div className="rec-alert" role="alert">{reviewError}</div>}
        <div className="rec-review-actions"><button type="button" className="rec-secondary-action" disabled={reviewSubmitting} onClick={()=>setReviewVisit(null)}>Cancel</button><button type="button" className="rec-main-action" disabled={reviewSubmitting} onClick={confirmReview}>{reviewSubmitting ? 'Checking reports…' : 'Confirm return for review'} <ArrowRight size={17}/></button></div>
      </div>
    </div>}
    {showForm && <div className="rec-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!submitting)setShowForm(false)}}>
      <div className="rec-modal rec-intake-modal" role="dialog" aria-modal="true" aria-labelledby="rec-modal-title">
        <div className="rec-modal-head"><div><div className="rec-overline">SECURE PATIENT INTAKE</div><h2 id="rec-modal-title">{registration?'Registration successful':'Patient registration'}</h2><p>{registration?'Visit added to the nursing queue.':'Register a new patient or retrieve an existing hospital record.'}</p></div><button type="button" onClick={()=>setShowForm(false)} disabled={submitting} aria-label="Close registration"><X size={20}/></button></div>
        {registration ? <div className="rec-confirmation"><CheckCircle2 size={40}/><span>QUEUE TOKEN</span><strong>{registration.queue_token}</strong><p>{registration.patient?.full_name} · {registration.doctor?.name}</p><small>Initial destination: Nursing Station</small><button className="rec-main-action" onClick={()=>{setRegistration(null);setForm(initialForm);setFormError('');}}>Register another patient <ArrowRight size={17}/></button><button className="rec-secondary-action" onClick={()=>setShowForm(false)}>Return to dashboard</button></div> :
        <form onSubmit={submit} className="rec-form rec-intake-form">
          <div className="rec-form-toggle"><button type="button" className={form.mode==='new'?'selected':''} onClick={()=>changeMode('new')}>New patient</button><button type="button" className={form.mode==='existing'?'selected':''} onClick={()=>changeMode('existing')}>Returning patient</button></div>
          {form.mode==='new' ? <>
            <section className="rec-intake-section"><div className="rec-intake-section-head"><UserRound size={19}/><div><h3>Personal information</h3><p>Details used to identify the patient</p></div></div><div className="rec-intake-grid">
              <label className="rec-span-2">Full name <span className="rec-required">*</span><input required maxLength={180} value={form.full_name} onChange={e=>setForm({...form,full_name:e.target.value})} placeholder="Enter patient’s full name"/></label>
              <label>Date of birth<input type="date" value={form.date_of_birth} max={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)} onChange={e=>setForm({...form,date_of_birth:e.target.value})}/></label>
              <label>Sex<select value={form.sex} onChange={e=>setForm({...form,sex:e.target.value})}><option value="">Select (optional)</option><option value="Female">Female</option><option value="Male">Male</option><option value="Other">Other</option><option value="Prefer not to say">Prefer not to say</option></select></label>
              <label>Phone number<input type="tel" maxLength={40} value={form.phone} onChange={e=>setForm({...form,phone:e.target.value})} placeholder="Contact number"/></label>
              <label>Email<input type="email" maxLength={254} value={form.email} onChange={e=>setForm({...form,email:e.target.value})} placeholder="Optional email"/></label>
              <label className="rec-span-2">Residential address<textarea rows={2} maxLength={2000} value={form.address} onChange={e=>setForm({...form,address:e.target.value})} placeholder="Address (optional)"/></label>
            </div></section>
            <section className="rec-intake-section"><div className="rec-intake-section-head"><Users size={19}/><div><h3>Emergency contact</h3><p>Who should the hospital contact in an emergency?</p></div></div><div className="rec-intake-grid"><label>Contact name<input maxLength={180} value={form.emergency_contact_name} onChange={e=>setForm({...form,emergency_contact_name:e.target.value})} placeholder="Full name"/></label><label>Contact phone<input type="tel" maxLength={40} value={form.emergency_contact_phone} onChange={e=>setForm({...form,emergency_contact_phone:e.target.value})} placeholder="Phone number"/></label></div></section>
            <section className="rec-intake-section"><div className="rec-intake-section-head"><HeartPulse size={19}/><div><h3>Medical background</h3><p>Private clinical information — not displayed on public screens</p></div></div><div className="rec-intake-grid"><label className="rec-span-2">Known allergies<textarea rows={2} maxLength={4000} value={form.allergies} onChange={e=>setForm({...form,allergies:e.target.value})} placeholder="Enter allergies, if known"/></label><label className="rec-span-2">Current medications<textarea rows={2} maxLength={4000} value={form.current_medications} onChange={e=>setForm({...form,current_medications:e.target.value})} placeholder="Current medications, if known"/></label><label className="rec-span-2">Medical history<textarea rows={2} maxLength={8000} value={form.medical_history} onChange={e=>setForm({...form,medical_history:e.target.value})} placeholder="Relevant history (optional)"/></label></div></section>
          </> : <section className="rec-intake-section"><div className="rec-intake-section-head"><Search size={19}/><div><h3>Find returning patient</h3><p>Search this hospital’s records; verify identity before selecting</p></div></div><label>Patient name, number or phone<input autoComplete="off" value={patientSearch} onChange={e=>{setPatientSearch(e.target.value);setSelectedPatient(null);}} placeholder="Type at least 2 characters"/></label>{searchingPatients&&<p className="rec-search-hint">Searching patient records…</p>}{searchError&&<div className="rec-alert" role="alert">{searchError}</div>}
          <div className="rec-patient-results">{patientMatches.map(p=><button type="button" key={p.id} className={'rec-patient-choice '+(selectedPatient?.id===p.id?'rec-patient-selected':'')} onClick={()=>setSelectedPatient(p)}><span className="rec-patient-initial">{p.full_name?.slice(0,1)?.toUpperCase()||'P'}</span><span><strong>{p.full_name}</strong><small>{p.patient_number} {p.date_of_birth?` · DOB ${p.date_of_birth}`:''} {p.phone?` · ${p.phone}`:''}</small></span>{selectedPatient?.id===p.id&&<CheckCircle2 size={21}/>}</button>)}{patientSearch.trim().length>=2&&!searchingPatients&&!patientMatches.length&&!searchError&&<p className="rec-search-hint">No matching patients in this hospital.</p>}</div>
          {selectedPatient&&<div className="rec-selected-note"><ShieldCheck size={18}/> Selected: <strong>{selectedPatient.full_name}</strong>. Confirm the patient's identity before registering today's visit.</div>}</section>}
          <section className="rec-intake-section rec-intake-consult"><div className="rec-intake-section-head"><Stethoscope size={19}/><div><h3>Today's consultation</h3><p>Choose an available doctor to begin the nursing workflow</p></div></div><label>Assign on-duty doctor <span className="rec-required">*</span><select required value={form.doctor_id} onChange={e=>setForm({...form,doctor_id:e.target.value})}><option value="">Select an available doctor</option>{doctors.map(d=><option key={d.id} value={d.id}>{d.name} — {d.department||'Doctor'}{d.room_number?` · Room ${d.room_number}`:''}{typeof d.waiting_count==='number'?` · ${d.waiting_count} waiting`:''}</option>)}</select></label><div className="rec-form-info"><Ticket size={19}/><span>Django will create a new consultation, generate the next monthly token and add the visit to Nursing Station.</span></div></section>
          {formError&&<div className="rec-alert" role="alert">{formError}</div>}
          <div className="rec-intake-actions"><button type="button" className="rec-secondary-action" onClick={()=>setShowForm(false)} disabled={submitting}>Cancel</button><button className="rec-main-action rec-submit" type="submit" disabled={submitting||!doctors.length||(form.mode==='existing'&&!selectedPatient)}>{submitting?'Registering…':'Register consultation & issue token'} <ArrowRight size={17}/></button></div>
        </form>}
      </div>
    </div>}
  </div>;
}


const money = (value, currency='INR') => {
  try { return new Intl.NumberFormat('en-IN', {style:'currency', currency}).format(Number(value || 0)); }
  catch { return `${currency} ${Number(value || 0).toFixed(2)}`; }
};

function ReceptionReports({hospital, doctors, refreshVisits}) {
  const [rows,setRows] = useState([]);
  const [loading,setLoading] = useState(true);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [busy,setBusy] = useState(null);
  const [doctorChoices,setDoctorChoices] = useState({});
  const refresh = useCallback(async () => {
    try {
      const response = await hospitalGet(hospital.slug, 'reception/investigation-reports');
      setRows(response.data?.results || []);
      setError('');
    } catch (e) {setError(errorText(e));}
    finally {setLoading(false);}
  }, [hospital.slug]);
  useEffect(()=>{refresh();const timer=window.setInterval(()=>{if(!document.hidden)refresh();},30000);return ()=>window.clearInterval(timer);},[refresh]);
  const act = async (row, action, body={}) => {
    setBusy(`${row.id}-${action}`);setError('');setNotice('');
    try {
      const response = await hospitalPost(hospital.slug, `reception/visits/${row.id}/${action}`,body);
      setNotice(response.data?.detail || 'Updated successfully');
      await Promise.all([refresh(), refreshVisits()]);
    } catch(e){setError(errorText(e));}
    finally {setBusy(null);}
  };
  const viewReport = async itemId => {
    // Open a tab synchronously to avoid popup blockers after the async request.
    const tab=window.open('', '_blank');
    if(!tab){setError('Allow pop-ups for this hospital to view reports.');return;}
    try {
      tab.document.title='Loading investigation report';
      const response=await hospitalGet(hospital.slug,
        `investigations/items/${itemId}/structured-report/pdf`, {responseType:'blob'});
      const blob=new Blob([response.data],{type:'application/pdf'});
      const url=URL.createObjectURL(blob);
      tab.location.href=url;
      window.setTimeout(()=>URL.revokeObjectURL(url), 120000);
    } catch(e) {tab.close();setError('Could not open the PDF. Please check your session and report permissions.');}
  };
  const reassign = async row => {
    const id=Number(doctorChoices[row.id] || row.doctor?.id);
    if(!id || id===row.doctor?.id){setError('Select a different on-duty doctor first.');return;}
    const reason=window.prompt('Reason for changing the assigned doctor (required):');
    if(reason===null)return;
    if(reason.trim().length<5){setError('Enter at least 5 characters for the reassignment reason.');return;}
    await act(row,'reassign-doctor',{doctor_id:id,reason:reason.trim()});
  };
  return <>
    <div className="rec-heading"><div><div className="rec-overline"><span/> RECEPTION WORKSPACE</div><h1>Investigation reports<span className="rec-heading-dot">.</span></h1><p>Review completed investigations, change the doctor when needed, and forward returning patients to the priority queue.</p></div><button type="button" className="rec-main-action" onClick={refresh}><RefreshCw size={18}/> Refresh</button></div>
    {error&&<div className="rec-alert" role="alert">{error}</div>}
    {notice&&<div className="rec-review-notice" role="status"><CheckCircle2 size={18}/>{notice}</div>}
    <section className="rec-panel rec-visits"><div className="rec-panel-header"><div><h2>Reports completed</h2><p>Only visits with all required non-cancelled reports finalized</p></div><span className="rec-count">{rows.length} patients</span></div>
      <div className="rec-table-wrap"><table className="rec-table"><thead><tr><th>TOKEN</th><th>PATIENT</th><th>REPORTS</th><th>ASSIGNED DOCTOR</th><th>STATUS</th><th>ACTIONS</th></tr></thead><tbody>
      {rows.map(row=><tr key={row.id}><td><span className="rec-token">{row.queue_token||'—'}</span></td><td><strong>{row.patient?.full_name}</strong><small>{row.patient?.patient_number}</small></td><td><strong>{row.report_count} finalized</strong><small>{row.reports.map(r=>r.test_name).join(', ')}</small>{row.reports.map(r=><button key={r.item_id} type="button" className="rec-report-btn rec-report-btn-view" onClick={()=>viewReport(r.item_id)}>View {r.test_name} PDF</button>)}{row.reports.map(r=><ReceptionDirectEmail key={`email-${r.item_id}`} hospital={hospital} itemId={r.item_id} patientName={row.patient?.full_name} email={row.patient?.email} testName={r.test_name}/>)}</td>
        <td><strong>{row.doctor?.name}</strong><select aria-label={`Change doctor for ${row.patient?.full_name}`} value={doctorChoices[row.id]||row.doctor?.id||''} onChange={e=>setDoctorChoices(v=>({...v,[row.id]:e.target.value}))}><option value={row.doctor?.id}>{row.doctor?.name} (current)</option>{doctors.filter(d=>d.id!==row.doctor?.id).map(d=><option key={d.id} value={d.id}>{d.name} · {d.waiting_count} waiting</option>)}</select><button type="button" className="rec-report-btn rec-report-btn-change" disabled={!!busy} onClick={()=>reassign(row)}>Change doctor</button></td>
        <td><span className={'rec-status '+(row.forwarded?'green':row.reviewed?'blue':'amber')}><span/>{row.forwarded?'Forwarded':row.reviewed?'Reviewed':'Awaiting review'}</span></td>
        <td>{!row.reviewed&&!row.forwarded&&<button type="button" className="rec-report-btn rec-report-btn-review" disabled={!!busy} onClick={()=>act(row,'review-reports')}>Mark reports reviewed</button>}{row.reviewed&&!row.forwarded&&<button type="button" className="rec-report-btn rec-report-btn-forward" disabled={!!busy} onClick={()=>{if(window.confirm(`Confirm ${row.patient?.full_name} has returned and forward to ${row.doctor?.name}?`))act(row,'return-for-review');}}>Forward to doctor <ArrowRight size={15}/></button>}{row.forwarded&&<strong>Priority doctor queue</strong>}</td></tr>)}
      </tbody></table>{!rows.length&&<div className="rec-table-empty">{loading?'Loading completed investigations…':'No finalized investigation visits are currently eligible for Reception review.'}</div>}</div>
    </section>
    <div className="rec-bottom-note"><ShieldCheck size={16}/> Report review is administrative; only departments finalize clinical reports.</div>
  </>;
}

function ReceptionInvestigationSection({hospital}) {
  const [bills,setBills] = useState([]), [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(null), [error,setError] = useState(''), [notice,setNotice] = useState('');
  const [query,setQuery] = useState(''), [filter,setFilter] = useState('WAITING_RECEPTION');
  const [selected,setSelected] = useState(null);
  const refresh = useCallback(async () => {
    try { const response=await hospitalGet(hospital.slug,'reception/investigation-bills');
      const updated=Array.isArray(response.data?.bills)?response.data.bills:[]; setBills(updated); setSelected(current=>current ? (updated.find(b=>b.id===current.id)||null) : null); setError(''); }
    catch(e){setError(errorText(e));} finally {setLoading(false);}
  },[hospital.slug]);
  useEffect(()=>{refresh(); const id=window.setInterval(()=>{if(!document.hidden)refresh();},30000);return ()=>window.clearInterval(id);},[refresh]);
  const filtered=useMemo(()=>bills.filter(b=>(filter==='ALL'||b.status===filter)&&
    [b.bill_number,b.patient_name,b.patient_number,b.token].join(' ').toLowerCase().includes(query.toLowerCase().trim())),[bills,filter,query]);
  async function act(b,action){setBusy(b.id);setError('');setNotice('');try{
    const result=await hospitalPost(hospital.slug,`reception/investigation-bills/${b.id}/${action}`,{});
    setNotice(result.data?.detail||'Updated.'); await refresh();
    if(action==='release')setSelected(null);
  }catch(e){setError(errorText(e));}finally{setBusy(null);}}
  function printBill(b){const w=window.open('','_blank','width=760,height=900');if(!w){setError('Allow popups to print this bill.');return;}
    const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    w.document.write(`<!doctype html><html><head><title>Investigation Bill ${escape(b.bill_number)}</title><style>body{font:14px Arial;padding:35px;color:#173247}h1{color:#087f76}table{width:100%;border-collapse:collapse;margin-top:25px}th,td{border-bottom:1px solid #ddd;text-align:left;padding:12px}th{background:#eef8f6}.total{text-align:right;font-weight:bold;font-size:18px;margin-top:20px}.foot{margin-top:35px;color:#678;font-size:12px}</style></head><body><h1>${escape(hospital.name)}</h1><h2>Investigation Bill — Test Price Summary</h2><p><b>Bill:</b> ${escape(b.bill_number)}<br><b>Patient:</b> ${escape(b.patient_name)}<br><b>Patient number:</b> ${escape(b.patient_number)}<br><b>Queue token:</b> ${escape(b.token)}<br><b>Created:</b> ${escape(new Date(b.created_at).toLocaleString())}</p><table><thead><tr><th>Test</th><th>Department</th><th>Price</th></tr></thead><tbody>${b.lines.map(x=>`<tr><td>${escape(x.test_name)} (${escape(x.test_code)})</td><td>${escape(x.department_name)}</td><td>${escape(money(x.amount,b.currency))}</td></tr>`).join('')}</tbody></table><div class="total">Total: ${escape(money(b.total_amount,b.currency))}</div><p class="foot">Investigation test price summary only. No payment transaction is recorded in this investigation bill.</p></body></html>`);
    w.document.close();w.focus();setTimeout(()=>w.print(),250);
  }
  return <div className="inv-root"><div className="inv-header"><div><span className="rec-overline">RECEPTION · INVESTIGATIONS</span><h1>Investigation bills<span className="rec-heading-dot">.</span></h1><p>Call patients, print itemized test prices, and release investigations.</p></div><button className="inv-refresh" onClick={refresh}><RefreshCw size={17}/> Refresh</button></div>
    {error&&<div className="rec-alert" role="alert">{error}</div>}{notice&&<div className="inv-notice" role="status">{notice}<button onClick={()=>setNotice('')} aria-label="Dismiss"><X size={16}/></button></div>}
    <div className="inv-stats">{[['Waiting at Reception',bills.filter(x=>x.status==='WAITING_RECEPTION').length],['Sent to Investigations',bills.filter(x=>x.status==='RELEASED').length],['Total Bills',bills.length]].map(([label,n])=><div className="inv-stat" key={label}><small>{label}</small><strong>{n}</strong></div>)}</div>
    <section className="rec-panel inv-panel"><div className="inv-toolbar"><div className="rec-search"><Search size={18}/><input aria-label="Search investigation bills" placeholder="Search patient, token or bill" value={query} onChange={e=>setQuery(e.target.value)}/></div><div className="rec-filters">{[['WAITING_RECEPTION','Waiting'],['RELEASED','Released'],['ALL','All']].map(([id,label])=><button key={id} className={filter===id?'active':''} onClick={()=>setFilter(id)}>{label}</button>)}</div></div>
      <div className="rec-table-wrap"><table className="rec-table"><thead><tr><th>BILL</th><th>PATIENT</th><th>TOKEN</th><th>AMOUNT</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{filtered.map(b=><tr key={b.id}><td><strong>{b.bill_number}</strong><small>{new Date(b.created_at).toLocaleString()}</small></td><td><strong>{b.patient_name}</strong><small>{b.patient_number}</small></td><td><span className="rec-token">{b.token}</span></td><td><strong>{money(b.total_amount,b.currency)}</strong></td><td><span className={'rec-status '+(b.status==='RELEASED'?'green':'amber')}>{b.status==='RELEASED'?'Released':'Waiting at Reception'}{b.status==='WAITING_RECEPTION'?` · ${b.queue_status||'WAITING'}`:''}</span></td><td><div className="inv-row-actions">
        <button type="button" className="rec-review-button" onClick={()=>setSelected(b)}><FileText size={15}/> View bill</button>
        {b.status==='WAITING_RECEPTION' && ['WAITING','RECALL_PENDING'].includes(b.queue_status) &&
          <button type="button" disabled={busy!==null} className="inv-action" onClick={()=>act(b,'call')}><BellRing size={15}/>{b.queue_status==='RECALL_PENDING'?'Call again':'Call patient'}</button>}
        {b.status==='WAITING_RECEPTION' && b.queue_status==='CALLED' && <>
          <button type="button" disabled={busy!==null} className="inv-action" onClick={()=>act(b,'recall-pending')}><RotateCcw size={15}/> Recall pending</button>
          <button type="button" disabled={busy!==null} className="rec-main-action inv-row-release" onClick={()=>act(b,'release')}><Send size={15}/> Send to investigations</button>
        </>}
      </div></td></tr>)}</tbody></table>{!loading&&!filtered.length&&<div className="rec-table-empty">No investigation bills match your filter.</div>}{loading&&<div className="rec-table-empty">Loading investigation bills…</div>}</div></section>
    {selected&&<div className="rec-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!busy)setSelected(null)}}><div className="rec-modal inv-modal" role="dialog" aria-modal="true" aria-label="Investigation bill"><div className="rec-modal-head"><div><span className="rec-overline">INVESTIGATION PRICE SUMMARY</span><h2>{selected.bill_number}</h2><p>{selected.patient_name} · Token {selected.token}</p></div><button onClick={()=>setSelected(null)} disabled={!!busy} aria-label="Close"><X size={20}/></button></div><div className="inv-line-table"><table><thead><tr><th>Test</th><th>Department</th><th>Price</th></tr></thead><tbody>{selected.lines.map((x,i)=><tr key={i}><td><strong>{x.test_name}</strong><small>{x.test_code}</small></td><td>{x.department_name}</td><td>{money(x.amount,selected.currency)}</td></tr>)}</tbody></table></div><div className="inv-total">Total <strong>{money(selected.total_amount,selected.currency)}</strong></div><div className="inv-actions"><button onClick={()=>printBill(selected)} className="inv-action"><Printer size={16}/> Print bill</button></div><p className="inv-hint">No payment is collected or tracked here. Calling a patient creates a Central TV announcement.</p></div></div>}
  </div>;
}
