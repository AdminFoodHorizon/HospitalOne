import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, BellRing, Clock3, FileText, Printer, RefreshCw, RotateCcw, Search, Send, X } from 'lucide-react';
import { hospitalGet, hospitalPost, errorText } from '../services/api';
import './InvestigationBills.css';

const money = (value, currency='INR') => {
  try { return new Intl.NumberFormat('en-IN', {style:'currency', currency}).format(Number(value || 0)); }
  catch { return `${currency} ${Number(value || 0).toFixed(2)}`; }
};
export default function InvestigationBills({hospital}) {
  const [bills,setBills] = useState([]), [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(null), [error,setError] = useState(''), [notice,setNotice] = useState('');
  const [query,setQuery] = useState(''), [filter,setFilter] = useState('WAITING_RECEPTION');
  const [selected,setSelected] = useState(null);
  const refresh = useCallback(async () => {
    try { const response=await hospitalGet(hospital.slug,'reception/investigation-bills');
      setBills(Array.isArray(response.data?.bills)?response.data.bills:[]); setError(''); }
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
      <div className="rec-table-wrap"><table className="rec-table"><thead><tr><th>BILL</th><th>PATIENT</th><th>TOKEN</th><th>AMOUNT</th><th>STATUS</th><th>ACTION</th></tr></thead><tbody>{filtered.map(b=><tr key={b.id}><td><strong>{b.bill_number}</strong><small>{new Date(b.created_at).toLocaleString()}</small></td><td><strong>{b.patient_name}</strong><small>{b.patient_number}</small></td><td><span className="rec-token">{b.token}</span></td><td><strong>{money(b.total_amount,b.currency)}</strong></td><td><span className={'rec-status '+(b.status==='RELEASED'?'green':'amber')}>{b.status==='RELEASED'?'Released':'Waiting at Reception'}{b.status==='WAITING_RECEPTION'?` · ${b.queue_status||'WAITING'}`:''}</span></td><td><button className="rec-review-button" onClick={()=>setSelected(b)}><FileText size={15}/> View bill</button></td></tr>)}</tbody></table>{!loading&&!filtered.length&&<div className="rec-table-empty">No investigation bills match your filter.</div>}{loading&&<div className="rec-table-empty">Loading investigation bills…</div>}</div></section>
    {selected&&<div className="rec-modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!busy)setSelected(null)}}><div className="rec-modal inv-modal" role="dialog" aria-modal="true" aria-label="Investigation bill"><div className="rec-modal-head"><div><span className="rec-overline">INVESTIGATION PRICE SUMMARY</span><h2>{selected.bill_number}</h2><p>{selected.patient_name} · Token {selected.token}</p></div><button onClick={()=>setSelected(null)} disabled={!!busy} aria-label="Close"><X size={20}/></button></div><div className="inv-line-table"><table><thead><tr><th>Test</th><th>Department</th><th>Price</th></tr></thead><tbody>{selected.lines.map((x,i)=><tr key={i}><td><strong>{x.test_name}</strong><small>{x.test_code}</small></td><td>{x.department_name}</td><td>{money(x.amount,selected.currency)}</td></tr>)}</tbody></table></div><div className="inv-total">Total <strong>{money(selected.total_amount,selected.currency)}</strong></div><div className="inv-actions"><button onClick={()=>printBill(selected)} className="inv-action"><Printer size={16}/> Print bill</button>{selected.status==='WAITING_RECEPTION'&&<>{['WAITING','RECALL_PENDING'].includes(selected.queue_status)&&<button disabled={!!busy} onClick={()=>act(selected,'call')} className="inv-action"><BellRing size={16}/>{selected.queue_status==='RECALL_PENDING'?'Call again':'Call patient'}</button>}{selected.queue_status==='CALLED'&&<button disabled={!!busy} onClick={()=>act(selected,'recall-pending')} className="inv-action"><RotateCcw size={16}/> Recall pending</button>}{selected.queue_status==='CALLED'&&<button disabled={!!busy} onClick={()=>act(selected,'release')} className="rec-main-action"><Send size={16}/> Send to investigations <ArrowRight size={15}/></button>}</>}</div><p className="inv-hint">No payment is collected or tracked here. Calling a patient creates a Central TV announcement.</p></div></div>}
  </div>;
}
