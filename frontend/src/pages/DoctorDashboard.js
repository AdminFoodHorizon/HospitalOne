import React, { useCallback, useEffect, useState } from 'react';
import { Activity, ArrowRight, CheckCircle2, Clock3, HeartPulse, LogOut, RefreshCw, ShieldCheck, Stethoscope, Users, Plus, Trash2, X, Save, FlaskConical, Pill, FileText, Download, AlertTriangle } from 'lucide-react';
import './DoctorDashboard.css';

const emptyMedicine = () => ({ medicine_id: '', dose: '', route: '', frequency: '', duration: '', quantity: '', instructions: '' });
const emptyTest = () => ({ test_id: '' });
const initialForm = () => ({ notes: '', diagnosis: '', medicines: [], tests: [] });

export default function DoctorDashboard({ hospital, profile, onLogout }) {
  const slug = typeof hospital === 'string' ? hospital : (hospital?.slug || profile?.hospital_slug);
  const hospitalName = (typeof hospital === 'object' && hospital?.name) || profile?.hospital_name || 'Hospital';
  const base = `/api/hospital/${encodeURIComponent(slug || '')}/doctor`;
  const [data, setData] = useState({ waiting: [], called: [], recall: [], review: [] });
  const [active, setActive] = useState([]);
  const [catalog, setCatalog] = useState({ medicines: [], tests: [] });
  const [editor, setEditor] = useState(null);
  const [form, setForm] = useState(initialForm);
  const [tab, setTab] = useState('history');
  const [reportError, setReportError] = useState('');
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [now, setNow] = useState(Date.now());

  const csrfToken = () => {
    const value = document.cookie.split('; ').find(x => x.startsWith('csrftoken='));
    return value ? decodeURIComponent(value.split('=').slice(1).join('=')) : '';
  };

  const api = useCallback(async (url, method = 'GET', body) => {
    const response = await fetch(url, {
      method, credentials: 'include',
      headers: method === 'GET' ? {} : { 'X-CSRFToken': csrfToken(), 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let payload;
    try { payload = await response.json(); } catch { payload = {}; }
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    return payload;
  }, []);

  const refresh = useCallback(async (spinner = false) => {
    if (!slug) return;
    if (spinner) setRefreshing(true);
    try {
      const [queue, consultations] = await Promise.all([
        api(`${base}/queue/`), api(`${base}/consultations/active/`),
      ]);
      setData({ waiting: [], called: [], recall: [], review: [], ...queue });
      setActive(consultations.consultations || []);
      setError('');
    } catch (e) { setError(e.message); }
    finally { if (spinner) setRefreshing(false); }
  }, [api, base, slug]);

  useEffect(() => {
    refresh();
    const poll = setInterval(() => { if (!document.hidden) refresh(); }, 15000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(poll); clearInterval(clock); };
  }, [refresh]);

  useEffect(() => {
    if (!editor) return undefined;
    const beforeUnload = (event) => {
      if (dirty) { event.preventDefault(); event.returnValue = ''; }
    };
    window.addEventListener('beforeunload', beforeUnload);
    return () => window.removeEventListener('beforeunload', beforeUnload);
  }, [dirty, editor]);

  const openConsultation = async (id) => {
    setBusy(`open-${id}`); setError(''); setMessage('');
    try {
      const [detail, choices] = await Promise.all([
        api(`${base}/consultations/${id}/`),
        api(`${base}/consultations/catalog/`),
      ]);
      if (detail.status !== 'ACTIVE' || detail.visit_state !== 'DOCTOR_ACTIVE') {
        throw new Error('This consultation is no longer active.');
      }
      setCatalog(choices);
      setEditor(detail);
      setForm({
        notes: detail.notes || '',
        diagnosis: detail.diagnosis || '',
        medicines: (detail.medicines || []).map(m => ({ ...emptyMedicine(), ...m })),
        tests: (detail.tests || []).map(t => ({ ...emptyTest(), ...t })),
      });
      setTab((detail.investigation_reports || []).length ? 'reports' : 'history'); setReportError(''); setDirty(false);
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  const openReportPdf = async (itemId) => {
    setReportError('');
    try {
      const response = await fetch(`${base}/consultations/${editor.consultation_id}/reports/${itemId}/pdf/`, { credentials: 'include' });
      if (!response.ok) {
        const details = await response.json().catch(() => ({}));
        throw new Error(details.detail || `PDF unavailable (${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `investigation-${itemId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (err) { setReportError(err.message); }
  };

  const queueAction = async (entry, verb) => {
    if (busy !== null || data.on_duty === false) return;
    setBusy(`queue-${entry.id}`); setError(''); setMessage('');
    try {
      const result = await api(`${base}/queue/${entry.id}/${verb}/`, 'POST');
      await refresh();
      if (verb === 'start') {
        if (!result.consultation_id) throw new Error('Consultation started, but its ID was not returned. Use Resume Consultation.');
        await openConsultation(result.consultation_id);
      } else {
        setMessage(result.detail || 'Queue updated.');
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  const updateField = (field, value) => {
    setForm(previous => ({ ...previous, [field]: value })); setDirty(true);
  };
  const addRow = (field) => {
    setForm(previous => ({ ...previous, [field]: [...previous[field], field === 'medicines' ? emptyMedicine() : emptyTest()] }));
    setDirty(true);
  };
  const editRow = (field, index, key, value) => {
    setForm(previous => ({ ...previous, [field]: previous[field].map((row, i) => i === index ? { ...row, [key]: value } : row) }));
    setDirty(true);
  };
  const removeRow = (field, index) => {
    setForm(previous => ({ ...previous, [field]: previous[field].filter((_, i) => i !== index) }));
    setDirty(true);
  };

  const normalized = () => ({
    notes: form.notes,
    diagnosis: form.diagnosis,
    medicines: form.medicines.map(m => ({ ...m, medicine_id: Number(m.medicine_id), quantity: Number(m.quantity) })),
    tests: form.tests.map(t => ({ test_id: Number(t.test_id) })),
  });

  const validate = () => {
    for (let i = 0; i < form.medicines.length; i++) {
      const m = form.medicines[i];
      if (!m.medicine_id || !m.dose.trim() || !m.route.trim() || !m.frequency.trim() || !m.duration.trim() ||
          !Number.isInteger(Number(m.quantity)) || Number(m.quantity) < 1) {
        setTab('medicines');
        throw new Error(`Medicine ${i + 1}: select a medicine and complete dose, route, frequency, duration and positive quantity.`);
      }
    }
    if (form.tests.some(t => !t.test_id)) { setTab('tests'); throw new Error('Select a test for each investigation row.'); }
    const ids = form.tests.map(t => String(t.test_id));
    if (new Set(ids).size !== ids.length) { setTab('tests'); throw new Error('Remove duplicate investigations.'); }
  };

  const saveOrSubmit = async (verb) => {
    if (!editor || busy !== null) return;
    setError(''); setMessage('');
    try {
      validate();
      if (verb === 'send-for-tests' && form.tests.length === 0) {
        setTab('tests'); throw new Error('Add at least one investigation before sending for tests.');
      }
      if (verb === 'finish' && form.tests.length > 0) {
        setTab('tests'); throw new Error('Investigations are selected. Use Send for Tests, or remove the tests before finishing.');
      }
      if (verb !== 'save') {
        const question = verb === 'finish'
          ? 'Finish this consultation and send prescribed medicines to Pharmacy (if any)?'
          : 'Submit these investigations to the relevant departments? This will close the active consultation.';
        if (!window.confirm(question)) return;
      }
      setBusy(verb);
      const result = await api(`${base}/consultations/${editor.consultation_id}/${verb}/`, 'POST', normalized());
      if (verb === 'save') {
        setDirty(false);
        setMessage(result.detail || 'Draft saved.');
      } else {
        setEditor(null); setDirty(false);
        setMessage(result.detail || 'Consultation submitted.');
        await refresh();
      }
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  const closeEditor = () => {
    if (dirty && !window.confirm('You have unsaved changes. Close without saving them?')) return;
    setEditor(null); setDirty(false); setError('');
    refresh();
  };

  const countdown = entry => {
    if (!entry.called_at) return '—';
    const seconds = Math.max(0, Math.ceil((new Date(entry.called_at).getTime() + 300000 - now) / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  const fmtTime = value => value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

  const section = (title, description, items, verb, label, icon, tone) => (
    <section className="doc-panel" key={title}>
      <div className="doc-panel-title">
        <div className={`doc-panel-icon ${tone}`}>{icon}</div>
        <div className="doc-panel-heading"><h2>{title}</h2><p>{description}</p></div>
        <span className="doc-panel-count">{items.length}</span>
      </div>
      <div className="doc-scroll"><table className="doc-table"><thead><tr>
        <th>QUEUE TOKEN</th><th>PATIENT</th><th>PATIENT NO.</th><th>QUEUED AT</th>
        {verb === 'start' && <th>TIME LEFT</th>}<th>ACTION</th>
      </tr></thead><tbody>
        {items.length === 0 && <tr><td colSpan={verb === 'start' ? 6 : 5} className="doc-empty">No patients in this queue</td></tr>}
        {items.map(entry => <tr key={entry.id}>
          <td><span className="doc-token">{entry.token || '—'}</span></td>
          <td className="doc-patient-name">{entry.patient_name || '—'}</td>
          <td>{entry.patient_number || '—'}</td>
          <td>{fmtTime(entry.queued_at)}</td>
          {verb === 'start' && <td><span className="doc-countdown"><Clock3 size={14}/>{countdown(entry)}</span></td>}
          <td><button className="doc-action" disabled={busy !== null || data.on_duty === false} onClick={() => queueAction(entry, verb)}>
            {busy === `queue-${entry.id}` ? 'Please wait…' : label}<ArrowRight size={15}/>
          </button></td>
        </tr>)}
      </tbody></table></div>
    </section>
  );

  return <main className="doc-dashboard">
    <header className="doc-header">
      <div className="doc-brand"><span className="doc-brand-icon"><HeartPulse size={22}/></span><div>{hospitalName}<small>Doctor workspace</small></div></div>
      <div className="doc-header-actions"><span className="doc-secure"><ShieldCheck size={15}/> Secure session</span>
        <button onClick={() => refresh(true)} disabled={refreshing}><RefreshCw size={16} className={refreshing ? 'doc-spin' : ''}/> Refresh</button>
        {onLogout && <button onClick={onLogout}><LogOut size={16}/> Sign out</button>}
      </div>
    </header>
    <div className="doc-main">
      <div className="doc-heading"><div><div className="doc-overline">LAST 24 HOURS · CLINICAL WORKSPACE</div><h1>Doctor Dashboard<span>.</span></h1><p>{data.doctor || profile?.username || 'Doctor'} · Room {data.room_number || 'Not assigned'}</p></div><div className="doc-duty"><span className={data.on_duty === false ? 'doc-duty-off' : 'doc-duty-on'}/>{data.on_duty === false ? 'Off duty' : 'On duty'}</div></div>
      <div className="doc-stats">
        {[{label:'Waiting to call',value:data.waiting?.length || 0,icon:<Users size={20}/>,tone:'teal'}, {label:'Called patients',value:data.called?.length || 0,icon:<Clock3 size={20}/>,tone:'blue'}, {label:'Waiting for recall',value:data.recall?.length || 0,icon:<Activity size={20}/>,tone:'amber'}, {label:'Returned from reports',value:data.review?.length || 0,icon:<Stethoscope size={20}/>,tone:'violet'}].map(s=><div className="doc-stat" key={s.label}><div className="doc-stat-top"><span>{s.label}</span><div className={`doc-stat-icon ${s.tone}`}>{s.icon}</div></div><strong>{s.value}</strong><small>Last 24 hours</small></div>)}
      </div>
      {data.on_duty === false && <div className="doc-warning">You are off duty. Calling is disabled until your hospital administrator marks you on duty.</div>}
      {error && <div className="doc-error" role="alert">{error}</div>}
      {message && <div className="doc-message" role="status"><CheckCircle2 size={17}/>{message}</div>}
      {active.length > 0 && <div className="doc-resume-bar">
        <div className="doc-resume-heading"><Stethoscope size={19}/><strong>Continue consultations</strong><span>{active.length} active</span></div>
        <div className="doc-resume-list">{active.map(item => <div className="doc-resume-item" key={item.consultation_id}>
          <span className="doc-token">{item.token}</span>
          <span className="doc-patient-name">{item.patient_name}</span>
          <span className="doc-resume-number">{item.patient_number}</span>
          <button className="doc-action" disabled={busy !== null} onClick={() => openConsultation(item.consultation_id)}>
            Resume Consultation <ArrowRight size={15}/>
          </button>
        </div>)}</div>
      </div>}
      {section('Returned From Reports — Priority', 'Reception-forwarded patients; call these patients first', data.review || [], 'call', 'Call for Review', <Stethoscope size={19}/>, 'violet')}
      {section('Waiting to Call', 'New patients assigned for initial consultation', data.waiting || [], 'call', 'Call Patient', <Users size={19}/>, 'teal')}
      {section('Called Patients — 5 Minutes', 'Patients announced and awaiting attendance', data.called || [], 'start', 'Start Consultation', <Clock3 size={19}/>, 'blue')}
      {section('Waiting for Recall', 'Patients who missed their previous call', data.recall || [], 'recall', 'Recall Patient', <Activity size={19}/>, 'amber')}
      <div className="doc-footer"><ShieldCheck size={15}/> Hospital-scoped patient queues · Verified staff access</div>
    </div>

    {editor && <div className="doc-modal-backdrop" role="presentation">
      <div className="doc-consultation" role="dialog" aria-modal="true" aria-label="Patient consultation">
        <div className="doc-consultation-head">
          <div><div className="doc-overline">ACTIVE CONSULTATION</div><h2>{editor.patient_name}</h2>
            <p>Token {editor.token} · Patient No. {editor.patient_number}</p></div>
          <button type="button" className="doc-close" onClick={closeEditor} aria-label="Close consultation"><X size={22}/></button>
        </div>
        <div className="doc-consultation-body">
          <div className="doc-patient-context">
            <div className="doc-context-title"><HeartPulse size={19}/><div><strong>Nurse assessment & patient history</strong><small>Read-only clinical handover · Latest assessment first</small></div></div>
            {(editor.nursing_assessments || []).length === 0 ? <div className="doc-history-empty">No nursing assessment has been recorded for this visit.</div> : (
              <div className="doc-nursing-list">{editor.nursing_assessments.map((a, idx) => <details className="doc-nursing-entry" key={a.id} open={idx === 0}>
                <summary>Assessment {idx + 1} · {a.nurse_name || 'Nurse'} · {a.completed_at ? new Date(a.completed_at).toLocaleString() : 'Time not recorded'}</summary>
                <div className="doc-vitals-grid">{[
                  ['Blood pressure', a.blood_pressure, 'mmHg'], ['Pulse', a.pulse_bpm, 'bpm'],
                  ['Temperature', a.temperature_c, '°C'], ['SpO₂', a.spo2_percent, '%'],
                  ['Respiratory rate', a.respiratory_rate, '/min'], ['Pain score', a.pain_score, '/10'],
                  ['Height', a.height_cm, 'cm'], ['Weight', a.weight_kg, 'kg'],
                ].map(([label, value, unit]) => <div className="doc-vital" key={label}><small>{label}</small><strong>{value === null || value === undefined || value === '' ? 'Not recorded' : `${value} ${unit}`}</strong></div>)}</div>
                <div className="doc-nurse-notes"><strong>Nurse observations / history</strong><p>{a.notes || 'Not recorded'}</p></div>
              </details>)}</div>
            )}
            <details className="doc-past-visits"><summary>Previous visits ({(editor.previous_visits || []).length})</summary>
              {(editor.previous_visits || []).length ? editor.previous_visits.map(v => <div className="doc-previous-visit" key={v.visit_number}><strong>{v.visit_number}</strong> · {new Date(v.registered_at).toLocaleDateString()} · {v.state}<p>{v.diagnoses?.join('; ') || 'No diagnosis recorded'}</p></div>) : <p>No previous visits recorded in this hospital.</p>}
            </details>
            <div className="doc-safety-note">Allergy and current-medication history are not structured fields in the existing nursing assessment model. Confirm these directly before prescribing.</div>
          </div>
          <section className="doc-intake-summary" aria-label="Patient safety information">
            <h3><AlertTriangle size={18}/> Patient safety & clinical history</h3>
            <div className="doc-intake-grid">
              <div><strong>Recorded allergies</strong><p>{editor.patient_intake?.allergies || 'Not documented — verify with patient'}</p></div>
              <div><strong>Current medicines</strong><p>{editor.patient_intake?.current_medications || 'Not documented — verify with patient'}</p></div>
              <div><strong>Past medical history</strong><p>{editor.patient_intake?.medical_history || 'Not documented'}</p></div>
            </div>
            <small>Historical intake entries are not independently verified. Confirm allergies and medication interactions before prescribing.</small>
          </section>
          <div className="doc-clinical-fields">
            <label>Clinical notes / symptoms<textarea value={form.notes} onChange={e => updateField('notes', e.target.value)} rows={3} maxLength={20000} placeholder="History, symptoms, examination findings…" /></label>
            <label>Diagnosis<textarea value={form.diagnosis} onChange={e => updateField('diagnosis', e.target.value)} rows={2} maxLength={10000} placeholder="Clinical assessment and diagnosis…" /></label>
          </div>
          <div className="doc-tabs" role="tablist" aria-label="Consultation sections">
            <button type="button" role="tab" aria-selected={tab === 'reports'} className={tab === 'reports' ? 'selected' : ''} onClick={() => setTab('reports')}><FileText size={18}/> Completed Reports ({(editor.investigation_reports || []).length})</button>
            <button type="button" role="tab" aria-selected={tab === 'history'} className={tab === 'history' ? 'selected' : ''} onClick={() => setTab('history')}><HeartPulse size={18}/> Patient Summary</button>
            <button type="button" role="tab" aria-selected={tab === 'medicines'} className={tab === 'medicines' ? 'selected' : ''} onClick={() => setTab('medicines')}><Pill size={18}/> Medicines ({form.medicines.length})</button>
            <button type="button" role="tab" aria-selected={tab === 'tests'} className={tab === 'tests' ? 'selected' : ''} onClick={() => setTab('tests')}><FlaskConical size={18}/> Blood Tests / Investigations ({form.tests.length})</button>
          </div>
          {tab === 'reports' ? <div className="doc-tab-content doc-reports-tab" role="tabpanel">
            <div className="doc-tab-heading"><div><h3>Verified investigation reports</h3><p>Read-only results released by Laboratory, Radiology and ECG for this patient visit.</p></div></div>
            {reportError && <div className="doc-error" role="alert">{reportError}</div>}
            {(editor.investigation_reports || []).length === 0 ? <div className="doc-form-empty">No verified, released investigation reports are available for this visit.</div> :
              editor.investigation_reports.map(report => <article className="doc-report-card" key={report.item_id}>
                <div className="doc-report-head"><div><small>{report.department || 'Investigation'} · {report.format?.replaceAll('_', ' ')}</small><h4>{report.test_name}</h4><span className="doc-report-status">{report.status === 'AMENDED' ? 'Amended report' : 'Final verified report'}</span></div>
                  <button type="button" className="doc-secondary doc-pdf-button" onClick={() => openReportPdf(report.item_id)}><Download size={16}/> Download PDF</button></div>
                <p className="doc-report-meta">Verified by {report.verified_by} · {new Date(report.verified_at).toLocaleString()}</p>
                {report.values?.length > 0 && <div className="doc-report-table-wrap"><table className="doc-report-table"><thead><tr><th>Investigation / parameter</th><th>Result</th><th>Unit</th><th>Reference (as reported)</th><th>Flag</th></tr></thead><tbody>
                  {report.values.map((v, i) => <tr key={i}><td><strong>{v.label}</strong>{v.section && <small>{v.section}</small>}{v.comment && <small>{v.comment}</small>}</td><td>{v.value === null || v.value === undefined || v.value === '' ? 'Not recorded' : String(v.value)}</td><td>{v.unit || '—'}</td><td>{v.reference || '—'}</td><td>{v.flag || '—'}</td></tr>)}
                </tbody></table></div>}
                {['findings','impression','recommendations'].map(key => report[key] ? <div className="doc-report-narrative" key={key}><strong>{key[0].toUpperCase()+key.slice(1)}</strong><p>{report[key]}</p></div> : null)}
              </article>)}
          </div> : tab === 'history' ? <div className="doc-tab-content doc-summary-tab" role="tabpanel"><h3>Clinical summary</h3><p>Review the nursing assessment above, document findings and diagnosis, then select Medicines or Investigations. No medication is prescribed automatically.</p><div className="doc-summary-actions"><button type="button" className="doc-add" onClick={() => setTab('medicines')}><Pill size={16}/> Prescribe Medicines</button><button type="button" className="doc-secondary" onClick={() => setTab('tests')}><FlaskConical size={16}/> Order Investigations</button></div></div> : tab === 'medicines' ? <div className="doc-tab-content" role="tabpanel">
            <div className="doc-tab-heading"><div><h3>Medicine prescription</h3><p>Enter the exact medication, prescribed dose, route, schedule, duration and dispensing quantity. Verify allergies and interactions before submission.</p></div>
              <button className="doc-add" type="button" onClick={() => addRow('medicines')}><Plus size={16}/> Add Medicine</button></div>
            {form.medicines.length === 0 && <div className="doc-form-empty">No medicines added. You may prescribe medicines, order tests, or both.</div>}
            {form.medicines.map((m, i) => <div className="doc-form-row" key={i}>
              <div className="doc-form-row-title"><strong>Medicine {i + 1}</strong><button type="button" className="doc-remove" onClick={() => removeRow('medicines', i)}><Trash2 size={16}/> Remove</button></div>
              <div className="doc-form-grid">
                <label className="doc-wide">Medicine<select value={m.medicine_id} onChange={e => editRow('medicines', i, 'medicine_id', e.target.value)}><option value="">Select medicine</option>{catalog.medicines.map(choice => <option value={choice.id} key={choice.id}>{choice.name} {choice.code ? `(${choice.code})` : ''}</option>)}</select></label>
                <label>Dose<input value={m.dose} onChange={e => editRow('medicines', i, 'dose', e.target.value)} placeholder="Doctor-entered dose" maxLength={100}/></label>
                <label>Route<input value={m.route} onChange={e => editRow('medicines', i, 'route', e.target.value)} placeholder="e.g. oral" maxLength={60}/></label>
                <label>Frequency<input value={m.frequency} onChange={e => editRow('medicines', i, 'frequency', e.target.value)} placeholder="Enter frequency" maxLength={100}/></label>
                <label>Duration<input value={m.duration} onChange={e => editRow('medicines', i, 'duration', e.target.value)} placeholder="Enter duration" maxLength={100}/></label>
                <label>Quantity<input type="number" min="1" max="100000" step="1" value={m.quantity} onChange={e => editRow('medicines', i, 'quantity', e.target.value)} placeholder="Units"/></label>
                <label className="doc-wide">Instructions<textarea rows={2} maxLength={5000} value={m.instructions} onChange={e => editRow('medicines', i, 'instructions', e.target.value)} placeholder="Additional patient instructions"/></label>
              </div>
            </div>)}
          </div> : <div className="doc-tab-content" role="tabpanel">
             <div className="doc-tab-heading"><div><h3>Select investigations</h3><p>Choose investigations by department. Review available completed reports above to avoid unnecessary repeat orders; all selections must be clinically justified.</p></div></div>
             {catalog.tests.length === 0 && <div className="doc-form-empty">No investigations configured for this hospital.</div>}
             {Array.from(new Set(catalog.tests.map(t => t.department || 'Other Investigations'))).map(dept => (
               <section className="doc-investigation-group" key={dept}>
                 <h4>{dept}</h4>
                 <div className="doc-investigation-grid">
                   {catalog.tests.filter(t => (t.department || 'Other Investigations') === dept).map(choice => (
                     <label className="doc-investigation-choice" key={choice.id}>
                       <input type="checkbox" checked={form.tests.some(t => String(t.test_id) === String(choice.id))}
                         onChange={e => {
                           const checked = e.target.checked;
                           setForm(previous => ({...previous, tests: checked
                             ? [...previous.tests.filter(t => String(t.test_id) !== String(choice.id)), {test_id: String(choice.id)}]
                             : previous.tests.filter(t => String(t.test_id) !== String(choice.id))}));
                           setDirty(true);
                         }}/>
                       <span>{choice.name}</span>
                     </label>
                   ))}
                 </div>
               </section>
             ))}
             <p className="doc-investigation-count">{form.tests.length} investigation(s) selected</p>
          </div>}
        </div>
        <div className="doc-consultation-foot">
          <span className="doc-draft-indicator">{dirty ? 'Unsaved changes' : 'No unsaved changes'}</span>
          <div className="doc-form-actions">
            <button type="button" className="doc-secondary" disabled={busy !== null} onClick={() => saveOrSubmit('save')}><Save size={16}/> Save Draft</button>
            <button type="button" className="doc-primary-alt" disabled={busy !== null || form.tests.length === 0} onClick={() => saveOrSubmit('send-for-tests')}><FlaskConical size={16}/> Send for Tests</button>
            <button type="button" className="doc-primary" disabled={busy !== null || form.tests.length > 0} onClick={() => saveOrSubmit('finish')}><CheckCircle2 size={16}/> Finish Consultation</button>
          </div>
        </div>
      </div>
    </div>}
  </main>;
}
