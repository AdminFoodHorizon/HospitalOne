import React,{useCallback,useEffect,useState} from 'react';
import {RefreshCw,ClipboardCheck,Printer,ArrowLeft,Search,Mail} from 'lucide-react';
import {hospitalGet,hospitalPost,errorText} from '../services/api';
import './ReceptionPatientRecords.css';

const date=v=>v?new Date(v).toLocaleString():'Not recorded';
const value=v=>v===null||v===undefined||v===''?'Not recorded':String(v);
function Section({title,children}){return <section className="rs-section"><h3>{title}</h3>{children}</section>}
function Summary({data}){
 const p=data.patient||{},v=data.visit||{};
 return <article className="rs-summary" id="rs-summary-print">
  <header className="rs-print-head">{data.hospital?.logo&&<img src={data.hospital.logo} alt="Hospital logo"/>}<div><h2>{data.hospital?.name}</h2><p>{data.hospital?.address}</p><p>{data.hospital?.phone} {data.hospital?.email}</p><strong>Patient visit and discharge summary</strong></div></header>
  <Section title="Patient and visit details"><div className="rs-grid">{[['Patient',p.name],['Patient ID',p.number],['Visit ID',v.visit_number],['Queue token',v.queue_token],['Date of birth',p.date_of_birth],['Sex',p.sex],['Phone',p.phone],['Email',p.email],['Address',p.address],['Registered',date(v.registered_at)],['Assigned doctor',v.doctor],['Visit state',v.state],['Completed',date(data.completed_at)]].map(([k,x])=><div key={k}><small>{k}</small><strong>{value(x)}</strong></div>)}</div></Section>
  <Section title="Clinical history and safety information"><div className="rs-grid">{[['Recorded allergies',p.allergies],['Current medications',p.current_medications],['Medical history',p.medical_history]].map(([k,x])=><div key={k}><small>{k}</small><strong>{value(x)}</strong></div>)}</div></Section>
  <Section title="Nursing assessments">{data.nursing?.length?data.nursing.map((n,i)=><div className="rs-entry" key={i}><small>{date(n.completed_at)}</small><div className="rs-grid">{[['Blood pressure',n.blood_pressure],['Pulse (bpm)',n.pulse_bpm],['Temperature (°C)',n.temperature_c],['Oxygen saturation (%)',n.spo2_percent],['Respiratory rate',n.respiratory_rate],['Height (cm)',n.height_cm],['Weight (kg)',n.weight_kg],['Pain score',n.pain_score],['Notes',n.notes]].map(([k,x])=><div key={k}><small>{k}</small><strong>{value(x)}</strong></div>)}</div></div>):<p>None recorded.</p>}</Section>
  <Section title="Doctor consultations">{data.consultations?.length?data.consultations.map(c=><div className="rs-entry" key={c.id}><strong>{c.doctor} · {value(c.department)}</strong><p>Started: {date(c.started_at)} · Ended: {date(c.ended_at)} · {c.status}</p><p><b>Diagnosis:</b> {value(c.diagnosis)}</p><p><b>Clinical notes:</b> {value(c.notes)}</p></div>):<p>None recorded.</p>}</Section>
  <Section title="Investigations and released reports">{data.investigations?.length?data.investigations.map(t=><div className="rs-entry" key={t.item_id}><strong>{t.test_name}</strong><p>Status: {t.status} · Ordered: {date(t.ordered_at)} · Ready: {date(t.report_ready_at)}</p>{t.released?<><p><b>Findings:</b> {value(t.findings)}</p><p><b>Impression:</b> {value(t.impression)}</p><p><b>Recommendations:</b> {value(t.recommendations)}</p><p className="rs-muted">Verified report recorded. Use the existing Investigation Reports module to view its original PDF.</p></>:<p className="rs-muted">No verified report available for this test.</p>}</div>):<p>No investigations recorded.</p>}</Section>
  <Section title="Doctor-prescribed medicines">{data.prescriptions?.length?<div className="rs-table-wrap"><table><thead><tr><th>Medicine</th><th>Qty</th><th>Dose / route</th><th>Frequency / duration</th><th>Instructions</th></tr></thead><tbody>{data.prescriptions.map((m,i)=><tr key={i}><td>{m.medicine}<small>{date(m.prescribed_at)}</small></td><td>{m.quantity}</td><td>{m.dose} / {m.route}</td><td>{m.frequency} / {m.duration}</td><td>{value(m.instructions)}</td></tr>)}</tbody></table></div>:<p>No prescriptions recorded.</p>}</Section>
  <Section title="Pharmacy dispensing and bill">{data.bill?<><p><b>Bill:</b> {data.bill.bill_number} · <b>Finalized:</b> {date(data.bill.finalized_at)}</p><div className="rs-table-wrap"><table><thead><tr><th>Medicine</th><th>Prescribed</th><th>Dispensed</th><th>Unit price</th><th>Amount</th></tr></thead><tbody>{data.bill.lines.map((m,i)=><tr key={i}><td>{m.medicine}</td><td>{m.prescribed_quantity}</td><td>{m.quantity}</td><td>{m.unit_price}</td><td>{m.total}</td></tr>)}</tbody></table></div><p className="rs-total">Total: {data.bill.currency} {data.bill.total}</p></>:<p>No finalized pharmacy bill for this visit.</p>}</Section>
  <Section title="Visit timeline">{data.timeline?.length?<ol className="rs-timeline">{data.timeline.map((t,i)=><li key={i}><strong>{date(t.at)}</strong> · {t.to} · {value(t.reason)} <small>({t.actor})</small></li>)}</ol>:<p>No timeline events recorded.</p>}</Section>
  <footer className="rs-document-footer">Generated from hospital records for authorized review. This document does not replace original signed clinical reports.</footer>
 </article>;
}
export function ReceptionPatientHistory({hospital}) {
  const [q,setQ] = useState('');
  const [matches,setMatches] = useState([]);
  const [patient,setPatient] = useState(null);
  const [visits,setVisits] = useState([]);
  const [detail,setDetail] = useState(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [notice,setNotice] = useState('');
  const [sendingPatientId,setSendingPatientId] = useState(null);

  const search = async (event) => {
    event.preventDefault();
    if (q.trim().length < 2) return;
    setBusy(true);
    setError('');
    try {
      // Important: put the query in Axios params, not in the endpoint string.
      // hospitalGet appends the endpoint's trailing slash.
      const response = await hospitalGet(hospital.slug, 'reception/patient-history', {
        params: { q: q.trim() }
      });
      setMatches(response.data?.results || []);
      setPatient(null);
      setVisits([]);
      setDetail(null);
    } catch (err) {
      setMatches([]);
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const select = async (record) => {
    setBusy(true);
    setError('');
    try {
      const response = await hospitalGet(hospital.slug, `reception/patient-history/${record.id}/visits`);
      setPatient(record);
      setVisits(response.data?.results || []);
      setDetail(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const open = async (id) => {
    setBusy(true);
    setError('');
    try {
      const response = await hospitalGet(hospital.slug, `reception/visit-history/${id}`);
      setDetail(response.data);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const sendHistoryEmail = async (record) => {
    if (sendingPatientId !== null || busy) return;
    setSendingPatientId(record.id);
    setError('');
    setNotice('');
    try {
      const response = await hospitalPost(hospital.slug, 'reception/report-delivery', {
        visit_id: record.id,
        channel: 'email',
      });
      setNotice(response.data?.detail || 'Email request accepted.');
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSendingPatientId(null);
    }
  };

  return <div className="rs-workspace">
    <div className="rs-toolbar"><div>
      <h2>Previous patient records</h2>
      <p>Search by patient ID, name or phone. Results are restricted to this hospital.</p>
    </div></div>
    {error && <p role="alert" className="rs-error">{error}</p>}
    {notice && <p role="status">{notice}</p>}

    {detail ? <>
      <div className="rs-actions">
        <button type="button" onClick={() => setDetail(null)}><ArrowLeft size={16}/> Back to visits</button>
        <button type="button" onClick={() => window.print()}><Printer size={16}/> Print / Save PDF</button><button type="button" disabled={sendingPatientId!==null} onClick={()=>sendHistoryEmail(detail.visit)}><Mail size={16}/> {sendingPatientId===detail.visit.id?'Sending…':'Email Summary PDF'}</button>
      </div>
      <Summary data={detail}/>
    </> : <>
      <form className="rs-search" onSubmit={search}>
        <input aria-label="Patient ID, name or phone" value={q} onChange={e => setQ(e.target.value)} placeholder="Patient ID, name or phone"/>
        <button type="submit" disabled={busy || q.trim().length < 2}><Search size={16}/> {busy ? 'Searching…' : 'Search'}</button>
      </form>
      {patient ? <>
        <button type="button" className="rs-link" onClick={() => {setPatient(null);setVisits([]);}}>← Back to search results</button>
        <h3>{patient.name} · {patient.number}</h3>
        <div className="rs-table-wrap"><table><thead><tr><th>Visit</th><th>Registered</th><th>Doctor</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>{visits.map(v => <tr key={v.id}>
            <td>{v.visit_number}</td><td>{date(v.registered_at)}</td><td>{v.doctor}</td><td>{v.state}</td>
            <td><button type="button" onClick={() => open(v.id)} disabled={busy}>Review visit</button> <button type="button" disabled={busy||sendingPatientId!==null} onClick={()=>sendHistoryEmail(v)}><Mail size={16}/> Email PDF</button></td>
          </tr>)}</tbody></table></div>
        {!visits.length && <p>No visits found.</p>}
      </> : <div className="rs-patients">
        {matches.map(p => <div className="rs-patient-result" key={p.id}>
          <div className="rs-patient-identity"><strong>{p.name}</strong><span>Patient ID: {p.number}</span></div>
          <div className="rs-patient-actions">
            <button type="button" onClick={() => select(p)} disabled={busy}>Previous records</button>
          </div>
        </div>)}
        {!matches.length && <p>{busy ? 'Searching patient records…' : 'No matching patients displayed. Search by patient ID, name or phone.'}</p>}
      </div>}
    </>}
  </div>;
}

export default function ReceptionPharmacyFinalization({hospital,refreshVisits}){
 const [rows,setRows]=useState([]),[current,setCurrent]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [mailNotice,setMailNotice]=useState('');
 const refresh=useCallback(async()=>{try{const r=await hospitalGet(hospital.slug,'reception/pharmacy-completed');setRows(r.data.results||[]);setError('');}catch(e){setError(errorText(e));}},[hospital.slug]);
 useEffect(()=>{refresh();const t=setInterval(()=>{if(!document.hidden)refresh();},30000);return()=>clearInterval(t);},[refresh]);
 const open=async id=>{setBusy(true);setMailNotice('');try{const r=await hospitalGet(hospital.slug,`reception/pharmacy-completed/${id}`);setCurrent(r.data);setError('');}catch(e){setError(errorText(e));}finally{setBusy(false)}};
 const reports=(current?.investigations||[]).filter(t=>t.released && t.item_id);
 const email=(current?.patient?.email||'').trim();
 const allEmailed=(current?.investigations||[]).every(t=>t.released && t.email_accepted);
 const sendReport=async item=>{
   if(!email){setError('Patient has no registered email. Update the patient intake contact before sending.');return;}
   if(!window.confirm(`Send ${item.test_name} PDF to the registered address ${email}?`))return;
   setBusy(true);setError('');setMailNotice('');
   try{
     const r=await hospitalPost(hospital.slug,`reception/investigation-reports/${item.item_id}/email-pdf`,{confirm_recipient:true,recipient:email});
     const updated=await hospitalGet(hospital.slug,`reception/pharmacy-completed/${current.visit.id}`);
     setCurrent(updated.data);
     setMailNotice(r.data?.detail||'Email provider accepted the PDF. Delivery is not guaranteed.');
   }catch(e){setError(errorText(e));}finally{setBusy(false)}
 };
 const finalize=async()=>{
   if(!current||busy)return;
   if(!allEmailed){setError('Send every finalized investigation report before finalizing.');return;}
   if(!window.confirm('The email provider accepted the listed reports. Finalize this visit?'))return;
   setBusy(true);setError('');
   try{await hospitalPost(hospital.slug,`reception/pharmacy-completed/${current.visit.id}/finalize`,{});setCurrent(null);await refresh();if(refreshVisits)refreshVisits();}
   catch(e){setError(errorText(e));}finally{setBusy(false)}
 };
 return <div className="rs-workspace"><div className="rs-toolbar"><div><h2>Pharmacy completed · Reception finalization</h2><p>Review the visit, email finalized investigation reports, then finalize.</p></div><button onClick={()=>{refresh();if(current)open(current.visit.id);}}><RefreshCw size={16}/> Refresh</button></div>
 {error&&<p role="alert" className="rs-error">{error}</p>}{mailNotice&&<p role="status" className="rs-mail-success">{mailNotice}</p>}
 {!current?<><div className="rs-table-wrap"><table><thead><tr><th>Token</th><th>Patient</th><th>Doctor</th><th>Action</th></tr></thead><tbody>{rows.map(v=><tr key={v.id}><td>{v.queue_token}</td><td>{v.patient.name}<small>{v.patient.number}</small></td><td>{v.doctor}</td><td><button disabled={busy} onClick={()=>open(v.id)}>Review summary</button></td></tr>)}</tbody></table></div>{!rows.length&&<p>No patients awaiting finalization.</p>}</>:
 <><div className="rs-actions"><button onClick={()=>setCurrent(null)}><ArrowLeft size={16}/> Back</button><button onClick={()=>window.print()}><Printer size={16}/> Print / Save PDF</button><button disabled={busy||current.visit.state!=='PHARMACY'||!allEmailed} onClick={finalize}><ClipboardCheck size={16}/> {busy?'Processing…':'Finalize visit'}</button></div>
 <section className="rs-mail-panel"><h3><Mail size={19}/> Complete patient visit summary</h3><p>Includes nursing, doctor consultations, released investigations, prescriptions, pharmacy bill and timeline.</p><button type="button" disabled={busy||!email} onClick={async()=>{setBusy(true);setError('');try{const r=await hospitalPost(hospital.slug,'reception/report-delivery',{visit_id:current.visit.id,channel:'email'});window.alert(r.data.detail);}catch(e){setError(errorText(e));}finally{setBusy(false);}}}><Mail size={16}/> Email Complete Summary PDF</button></section>
 <section className="rs-mail-panel" aria-label="Email investigation reports"><h3><Mail size={19}/> Email finalized investigation reports</h3><p>Registered recipient: <strong>{email||'Not recorded'}</strong></p>
 {reports.length===0?<p>No finalized investigation PDFs listed for this visit.</p>:<div className="rs-mail-list">{reports.map(t=><div className="rs-mail-row" key={t.item_id}><div><strong>{t.test_name}</strong><small>{t.email_accepted?'Gmail accepted (saved on server)':'Not yet emailed'}</small></div><button type="button" disabled={busy||!email||!!t.email_accepted} onClick={()=>sendReport(t)}><Mail size={16}/>{t.email_accepted?'Email accepted':'Email PDF'}</button></div>)}</div>}
 <p className="rs-mail-note">Email acceptance does not guarantee delivery. Acceptance status is stored by the server. Finalization is also checked by the server. If a report changes, it must be emailed again.</p></section>
 <Summary data={current}/></>}
 </div>;
}
