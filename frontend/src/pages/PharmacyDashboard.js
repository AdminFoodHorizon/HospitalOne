import React, {useCallback, useEffect, useMemo, useState} from 'react';
import {
  Pill,
  RefreshCw,
  Printer,
  LogOut,
  ClipboardCheck,
  Search,
  ShieldCheck,
  ArrowLeft,
  CheckCircle2,
  RotateCcw,
  Clock3,
  Megaphone,
} from 'lucide-react';
import {hospitalGet, hospitalPost, errorText} from '../services/api';
import './PharmacyDashboard.css';
const money=(n,c)=>{try{return new Intl.NumberFormat(undefined,{style:'currency',currency:c}).format(Number(n||0));}catch{return `${c} ${Number(n||0).toFixed(2)}`;}};
function Bill({bill,hospital,visit}){
 const issued=bill?.finalized_at?new Date(bill.finalized_at):null;
 const printed=issued&&!Number.isNaN(issued.getTime())?issued.toLocaleString(): '—';
 const lines=Array.isArray(bill?.lines)?bill.lines:[];
 const count=lines.reduce((n,x)=>n+Number(x.quantity||0),0);
 return <article className="ph-bill" id="ph-print-bill" aria-label="Pharmacy dispensing invoice">
  <div className="ph-bill-topline"/>
  <header className="ph-bill-head">
   <div className="ph-bill-identity">{hospital?.logo&&<img src={hospital.logo} alt={`${hospital?.name||'Hospital'} logo`}/>}<div><h2>{hospital?.name||'Hospital'}</h2>{hospital?.address&&<p>{hospital.address}</p>}<p>{[hospital?.phone,hospital?.email].filter(Boolean).join('  •  ')}</p></div></div>
   <div className="ph-bill-title"><span>PHARMACY</span><strong>Dispensing Bill</strong><small>Finalized dispensing record</small></div>
  </header>
  <div className="ph-bill-meta"><div><span>Bill number</span><strong>{bill.bill_number}</strong></div><div><span>Issued on</span><strong>{printed}</strong></div><div><span>Visit number</span><strong>{visit?.visit_number||'—'}</strong></div><div><span>Queue token</span><strong>{visit?.queue_token||'—'}</strong></div></div>
  <div className="ph-bill-patient"><div><span>DISPENSED TO</span><strong>{visit?.patient?.name||'—'}</strong><small>Patient ID: {visit?.patient?.number||'—'}</small></div><div><span>PRESCRIBING DOCTOR</span><strong>{visit?.doctor||'—'}</strong></div></div>
  <div className="ph-bill-section"><h3>Medicine details</h3><p>Only medicines and quantities recorded at finalization appear on this bill.</p></div>
  <table className="ph-bill-table"><thead><tr><th className="ph-bill-index">#</th><th>Medicine and directions</th><th className="ph-bill-num">Qty</th><th className="ph-bill-num">Unit price</th><th className="ph-bill-num">Amount</th></tr></thead><tbody>{lines.map((x,i)=><tr key={x.item_id}><td className="ph-bill-index">{i+1}</td><td><strong>{x.medicine}</strong>{x.code&&<small>Code: {x.code}</small>}<small>{[x.dose,x.route,x.frequency,x.duration].filter(Boolean).join(' · ')}</small>{x.instructions&&<small>Instructions: {x.instructions}</small>}{Number(x.quantity)<Number(x.prescribed_quantity)&&<small>Prescribed: {x.prescribed_quantity} · Dispensed: {x.quantity}</small>}</td><td className="ph-bill-num">{x.quantity}</td><td className="ph-bill-num">{money(x.unit_price,bill.currency)}</td><td className="ph-bill-num ph-bill-amount">{money(x.total,bill.currency)}</td></tr>)}</tbody></table>
  <div className="ph-bill-summary"><div className="ph-bill-summary-note"><strong>Dispensing summary</strong><span>{lines.length} medicine line{lines.length===1?'':'s'} · {count} unit{count===1?'':'s'} dispensed</span><span>Prices and quantities are recorded from the finalized hospital pharmacy bill.</span></div><div className="ph-bill-summary-total"><span>Grand total</span><strong>{money(bill.total,bill.currency)}</strong><small>Currency: {bill.currency}</small></div></div>
  <footer className="ph-bill-footer"><span>This is a pharmacy dispensing bill, not proof of payment.</span><span>Computer-generated document · Bill no. {bill.bill_number}</span></footer>
 </article>;
}
export default function PharmacyDashboard({hospital,profile,onLogout}){
 const [callQueue,setCallQueue]=useState([]),[queue,setQueue]=useState([]),[selected,setSelected]=useState(null),[qty,setQty]=useState({}),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[query,setQuery]=useState(''),[sending,setSending]=useState(false),[shareStatus,setShareStatus]=useState('');
 const refresh=useCallback(async()=>{try{const r=await hospitalGet(hospital.slug,'pharmacy/queue');setQueue(r.data.results||[]);const cq=await hospitalGet(hospital.slug,'pharmacy/call-queue');setCallQueue(cq.data.results||[]);setError('');}catch(e){setError(errorText(e));}finally{setLoading(false);}},[hospital.slug]);
 useEffect(()=>{refresh();const t=setInterval(()=>{if(!document.hidden)refresh();},30000);return()=>clearInterval(t);},[refresh]);
 const open=async(id)=>{setBusy(true);setError('');try{const r=await hospitalGet(hospital.slug,`pharmacy/visits/${id}`);setSelected(r.data);setQty(Object.fromEntries(r.data.items.map(x=>[String(x.id),x.quantity])));}catch(e){setError(errorText(e));}finally{setBusy(false);}};
 const submit=async()=>{if(!selected||selected.bill)return; if(!window.confirm('Finalize dispensing? Prescribed medicines cannot be changed and this action cannot be repeated.'))return;setBusy(true);setError('');try{await hospitalPost(hospital.slug,`pharmacy/visits/${selected.visit.id}/finalize`,{quantities:qty});await open(selected.visit.id);await refresh();}catch(e){setError(errorText(e));}finally{setBusy(false);}};
 const sendShare=async(channel)=>{if(!selected?.bill||sending)return;setSending(true);setShareStatus('');try{const r=await hospitalPost(hospital.slug,'reception/report-delivery/',{visit_id:selected.visit.id,channel});setShareStatus(r.data?.detail||'Notification accepted by provider; delivery not confirmed.');}catch(e){setShareStatus(errorText(e));}finally{setSending(false);}};
 const [callingId,setCallingId]=useState(null),[callNotice,setCallNotice]=useState('');
 const callPatient=async(entry,isRecall=false)=>{
   if(callingId!==null||busy)return;
   setCallingId(entry.id);setCallNotice('');setError('');
   try{
     const action=isRecall?'recall':'call';
     const response=await hospitalPost(hospital.slug,`pharmacy/queue/${entry.id}/${action}/`,{});
     setCallNotice(`${entry.token}: ${response.data?.detail||'Announcement sent to Central TV.'}`);
     await refresh();
   }catch(e){setError(errorText(e));}
   finally{setCallingId(null);}
 };
 const callStats={waiting:callQueue.filter(e=>e.status==='WAITING').length,called:callQueue.filter(e=>e.status==='CALLED').length,recall:callQueue.filter(e=>e.status==='RECALL_PENDING').length};
 const filtered=queue.filter(v=>`${v.queue_token} ${v.patient?.name} ${v.patient?.number}`.toLowerCase().includes(query.toLowerCase()));
 const total=useMemo(()=>selected?.items.reduce((sum,x)=>sum+Number(x.unit_price||0)*Number(qty[x.id]||0),0)||0,[selected,qty]);
 return <div className="ph-app"><header className="ph-header"><div className="ph-brand"><span className="ph-brand-icon"><Pill size={24}/></span><div><strong>{hospital.name}</strong><small>Pharmacy workspace</small></div></div><div className="ph-header-actions"><span>{profile?.username||'Pharmacy staff'}</span><button onClick={onLogout}><LogOut size={16}/> Sign out</button></div></header><main className="ph-main"><div className="ph-heading"><div><p className="ph-eyebrow">SECURE HOSPITAL WORKSPACE</p><h1>Pharmacy dispensing</h1><p>Dispense exactly the medicines prescribed by the doctor. Quantities may be reduced, not increased.</p></div><button className="ph-secondary" onClick={refresh}><RefreshCw size={17}/> Refresh</button></div>{error&&<div className="ph-error" role="alert">{error}</div>}{!selected?<><div className="ph-stats ph-queue-stats"><div><small>Awaiting dispensing</small><strong>{queue.length}</strong></div><div><small>Waiting to call</small><strong>{callStats.waiting}</strong></div><div><small>Called</small><strong>{callStats.called}</strong></div><div><small>Recall needed</small><strong>{callStats.recall}</strong></div></div>{callNotice&&<div className="ph-call-notice" role="status"><CheckCircle2 size={18}/>{callNotice}</div>}<section className="ph-card"><div className="ph-card-head"><h2>Prescription queue</h2><label className="ph-search"><Search size={17}/><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search patient or token"/></label></div><div className="ph-scroll"><table><thead><tr><th>Token</th><th>Patient</th><th>Prescribing doctor</th><th>Registered</th><th>Call / Recall</th><th>Action</th></tr></thead><tbody>{filtered.map(v=><tr key={v.id}><td><strong>{v.queue_token||'—'}</strong></td><td>{v.patient.name}<small>{v.patient.number}</small></td><td>{v.doctor}</td><td>{new Date(v.registered_at).toLocaleString()}</td><td>{(()=>{const e=callQueue.find(x=>x.visit_id===v.id);if(!e)return <span className="ph-queue-muted">Queue unavailable</span>;const called=e.status==='CALLED',recall=e.status==='RECALL_PENDING',pending=callingId===e.id;return <div className="ph-call-cell"><span className={`ph-queue-status ${recall?'ph-queue-status-recall':called?'ph-queue-status-called':'ph-queue-status-waiting'}`}>{recall?'Recall needed':called?'Called':'Waiting'}</span><button type="button" className={`ph-call-button ${recall?'ph-call-button-recall':''}`} disabled={busy||callingId!==null||called} onClick={()=>callPatient(e,recall)}>{recall?<RotateCcw size={16}/>:called?<Clock3 size={16}/>:<Megaphone size={16}/>} {pending?'Sending…':recall?'Recall patient':called?'Awaiting arrival':'Call patient'}</button></div>;})()}</td><td><button className="ph-primary" disabled={busy||callingId!==null} onClick={()=>open(v.id)}>Open prescription</button></td></tr>)}</tbody></table></div>{!filtered.length&&<p className="ph-empty">{loading?'Loading patients…':'No patients awaiting pharmacy dispensing.'}</p>}</section></>:<><button className="ph-back" onClick={()=>{setSelected(null);refresh();}}><ArrowLeft size={17}/> Back to queue</button><section className="ph-card"><div className="ph-card-head"><div><h2>{selected.visit.patient.name}</h2><p>{selected.visit.patient.number} · Token {selected.visit.queue_token} · Dr. {selected.visit.doctor}</p></div><span className="ph-chip">{selected.bill?'Dispensed':'Awaiting dispensing'}</span></div>{selected.bill?<><Bill bill={selected.bill} hospital={selected.hospital} visit={selected.visit}/><button className="ph-primary ph-print" onClick={()=>window.print()}><Printer size={18}/> Print bill</button><div className="ph-share-actions" style={{display:'flex',gap:10,flexWrap:'wrap',margin:'12px 0'}}><button type="button" className="ph-secondary" disabled={busy||sending} onClick={()=>sendShare('email')}>Email Summary PDF</button></div>{shareStatus&&<p role="status" className="ph-success">{shareStatus}</p>}<p className="ph-success"><ClipboardCheck size={18}/> Submitted to Reception for final patient summary.</p></>:<><div className="ph-scroll"><table><thead><tr><th>Prescribed medicine (read-only)</th><th>Directions (read-only)</th><th>Prescribed qty</th><th>Dispense qty</th><th>Unit price</th><th>Line total</th></tr></thead><tbody>{selected.items.map(x=><tr key={x.id}><td><strong>{x.medicine}</strong><small>{x.code}</small></td><td>{x.dose} · {x.route}<small>{x.frequency} · {x.duration}</small><small>{x.instructions}</small></td><td>{x.quantity}</td><td><input aria-label={`Dispensed quantity for ${x.medicine}`} type="number" min="0" max={x.quantity} step="1" value={qty[x.id]??x.quantity} onChange={e=>setQty(old=>({...old,[x.id]:e.target.value===''?'':Number(e.target.value)}))}/></td><td>{x.unit_price===null?'Price missing':money(x.unit_price,selected.hospital.currency)}</td><td>{money(Number(x.unit_price||0)*Number(qty[x.id]||0),selected.hospital.currency)}</td></tr>)}</tbody></table></div><div className="ph-final"><div><small>Estimated medicine bill</small><strong>{money(total,selected.hospital.currency)}</strong><p>Prices come from this hospital's medicine catalog.</p></div><button className="ph-primary" disabled={busy||selected.items.some(x=>x.unit_price===null||!Number.isInteger(qty[x.id])||qty[x.id]<0||qty[x.id]>x.quantity)} onClick={submit}><ClipboardCheck size={18}/>{busy?'Submitting…':'Finalize dispensing'}</button></div></>}</section></>}<footer><ShieldCheck size={15}/> Hospital-specific records · Staff authentication and 2FA required</footer></main></div>;
}
export {Bill,money};
