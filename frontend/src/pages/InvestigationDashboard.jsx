import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { Activity, BellRing, ClipboardList, LogOut, RefreshCw, RotateCcw, Send, Stethoscope, CheckCircle2, DoorOpen, FilePenLine, FileText, Search } from 'lucide-react';

import { api, hospitalGet, hospitalPost, errorText } from '../services/api';

import './InvestigationDashboard.css';

import InvestigationReportForm from './InvestigationReportForm';



const pending = item => ['WAITING', 'IN_PROGRESS', 'PERFORMED'].includes(item.status);



export default function InvestigationDashboard({ hospital, profile, onLogout }) {

  const slug = hospital.slug;

  const pdfBlobUrls = useRef([]);

  useEffect(() => {

    const urls = pdfBlobUrls.current;

    return () => urls.forEach(url => URL.revokeObjectURL(url));

  }, []);

  const [entries, setEntries] = useState([]);

  const [departments, setDepartments] = useState([]);

  const [selectedDepartment, setSelectedDepartment] = useState('all');

  const [busy, setBusy] = useState('');

  const [error, setError] = useState('');

  const [notice, setNotice] = useState('');

  const [openId, setOpenId] = useState(null);

  const [reportItem, setReportItem] = useState(null);

  const [archive, setArchive] = useState([]);

  const [archiveTotal, setArchiveTotal] = useState(0);

  const [archivePage, setArchivePage] = useState(1);

  const [archiveHasNext, setArchiveHasNext] = useState(false);

  const [archiveError, setArchiveError] = useState('');

  const [search, setSearch] = useState('');

  const [fromDate, setFromDate] = useState('');

  const [toDate, setToDate] = useState('');

  const [historyFilters, setHistoryFilters] = useState({q:'',from:'',to:''});

  const [today, setToday] = useState([]);

  const [todayCount, setTodayCount] = useState(0);

  const [todayPage, setTodayPage] = useState(1);

  const [todayHasNext, setTodayHasNext] = useState(false);

  const todayKey = new Intl.DateTimeFormat('en-CA', {timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());

  const loadReports = useCallback(async (page = 1, filters = {q:'',from:'',to:''}, dayPage = 1) => {

    try {

      const [historyRes, todayRes] = await Promise.all([

        hospitalGet(slug, 'investigations/reports/completed', { params: {...filters, page} }),

        hospitalGet(slug, 'investigations/reports/completed', { params: {from: todayKey, to: todayKey, page: dayPage} })

      ]);

      setArchive(historyRes.data.results || []);

      setArchiveTotal(historyRes.data.total || 0);

      setArchiveHasNext(!!historyRes.data.has_next);

      setArchivePage(page);

      setToday(todayRes.data.results || []);

      setTodayCount(todayRes.data.total || 0);

      setTodayHasNext(!!todayRes.data.has_next);

      setTodayPage(dayPage);

      setArchiveError('');

    } catch (e) { setArchiveError(errorText(e)); }

  }, [slug, todayKey]);



  const load = useCallback(async () => {

    try {

      const { data } = await hospitalGet(slug, 'investigations/queue');

      setEntries(data.entries || []);

      setDepartments(data.departments || []);

    } catch (e) { setError(errorText(e)); }

  }, [slug]);



  useEffect(() => {

    load();

    loadReports(1, {q:'',from:'',to:''}, 1);

    const timer = setInterval(() => { load(); loadReports(archivePage, historyFilters, todayPage); }, 12000);

    return () => clearInterval(timer);

  }, [load, loadReports, archivePage, todayPage, historyFilters]);



  // Rolling 24-hour window for the ACTIVE patient list only.
  // The investigation queue API must return queued_at (ISO timestamp) per entry.
  // Entries without a timestamp are excluded rather than showing older patients.
  const [queueClock, setQueueClock] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setQueueClock(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);

  const visible = useMemo(() => entries.filter(e => {
    const timestamp = e.queued_at;
    const queuedAt = typeof timestamp === 'string' ? Date.parse(timestamp) : NaN;
    const within24Hours = Number.isFinite(queuedAt) &&
      queuedAt <= queueClock && queuedAt >= queueClock - 24 * 60 * 60 * 1000;
    return within24Hours &&
      (selectedDepartment === 'all' || String(e.department_id) === selectedDepartment);
  }), [entries, selectedDepartment, queueClock]);



  async function action(route, label, payload = {}) {

    if (busy) return;

    setBusy(route); setError(''); setNotice('');

    try {

      const { data } = await hospitalPost(slug, route, payload);

      setNotice(data.detail || label);

      await load();

      await loadReports(archivePage, historyFilters, todayPage);

    } catch (e) { setError(errorText(e)); }

    finally { setBusy(''); }

  }



  // Download using the authenticated Axios client, preserving the current

  // localhost (or production domain) session and all Django 2FA checks.

  async function openReportPdf(report) {

    const path = report?.pdf_url;

    const expectedPrefix = `/api/hospital/${encodeURIComponent(slug)}/investigations/items/`;

    if (typeof path !== 'string' || !path.startsWith(expectedPrefix) ||

        !/^\d+\/structured-report\/pdf\/$/.test(path.slice(expectedPrefix.length))) {

      setArchiveError('Invalid report PDF address.');

      return;

    }

    // Open a tab immediately during the click, before the async request,

    // to avoid popup blocking. No patient data is sent to other websites.

    const tab = window.open('about:blank', '_blank');

    if (!tab) {

      setArchiveError('Please allow pop-ups for this hospital website to view reports.');

      return;

    }

    tab.opener = null;

    try {

      setArchiveError('');

      const response = await api.get(path, { responseType: 'blob' });

      const type = response.headers?.['content-type'] || response.data?.type || '';

      if (!type.toLowerCase().includes('application/pdf')) {

        throw new Error('Server did not return a PDF.');

      }

      const blobUrl = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));

      tab.location.replace(blobUrl);

      // Keep the object URL alive for viewing and printing. It is revoked

      // when the dashboard page is unloaded.

      pdfBlobUrls.current.push(blobUrl);

    } catch (e) {

      tab.close();

      setArchiveError(errorText(e));

    }

  }



  const showResults = (entry) => {

    setOpenId(entry.id);

    const first = entry.items.find(i => ['IN_PROGRESS', 'PERFORMED', 'REPORT_READY'].includes(i.status));

    if (first) setReportItem(first.id);

  };



  const control = (label, Icon, enabled, handler, reason, primary = false) =>

    <button type="button" className={`inv-button ${primary ? 'inv-primary' : 'inv-outline'}`}

      disabled={!enabled || !!busy} title={enabled ? label : reason} onClick={handler}>

      <Icon size={15}/>{label}

    </button>;



  return <div className="inv-layout">

    <aside className="inv-sidebar">

      <div className="inv-brand"><span className="inv-brand-icon"><Activity size={24}/></span><span className="inv-brand-text"><strong>{hospital?.name || profile?.hospital_name || "Hospital"}</strong><small>Investigation workspace</small></span></div>

      <div className="inv-nav"><ClipboardList size={18}/> Investigation workspace</div>

      <div className="inv-side-caption">HOSPITAL</div>

      <div className="inv-side-name">{hospital.name}</div>

      <button className="inv-logout" onClick={onLogout}><LogOut size={17}/> Sign out</button>

    </aside>

    <main className="inv-main">

      <div className="inv-topline"><div><div className="inv-eyebrow">CLINICAL OPERATIONS</div><h1>Investigation Dashboard</h1><p>Patient attendance and report completion are tracked separately.</p></div>

        <button className="inv-button inv-outline" onClick={() => {load();loadReports(archivePage,historyFilters,todayPage);}}><RefreshCw size={16}/> Refresh</button></div>

      <div className="inv-metrics">

        <div><small>Patients · last 24 hours</small><strong>{visible.length}</strong></div>

        <div><small>Waiting / Available</small><strong>{visible.filter(e=>e.physical_status==='WAITING' && e.status==='WAITING').length}</strong></div>

        <div><small>Called (not attending)</small><strong>{visible.filter(e=>e.status==='CALLED' && e.physical_status!=='ATTENDING').length}</strong></div>

        <div><small>Physically attending</small><strong>{visible.filter(e=>e.physical_status==='ATTENDING').length}</strong></div>

      </div>

      <section className="inv-card">

        <div className="inv-section-head"><div><h2>Department queue</h2><p>Patients queued in the last 24 hours. Unavailable actions remain visible and disabled.</p></div>

          {departments.length > 1 && <select aria-label="Filter department" value={selectedDepartment} onChange={e=>setSelectedDepartment(e.target.value)}>

            <option value="all">All authorized departments</option>

            {departments.map(d=><option key={d.id} value={String(d.id)}>{d.name}</option>)}

          </select>}</div>

        {error && <div className="inv-alert inv-error" role="alert">{error}</div>}

        {notice && <div className="inv-alert inv-notice" role="status">{notice}</div>}

        <div className="inv-scroll"><table className="inv-table"><thead><tr><th>Token / Patient</th><th>Department</th><th>Tests</th><th>Patient availability</th><th>Actions</th></tr></thead>

          <tbody>{visible.map(e => {

            const available = e.physical_status === 'WAITING';

            const attending = e.physical_status === 'ATTENDING';

            const called = e.status === 'CALLED';

            const canCall = available && e.visit_state === 'TEST_POOL' && ['WAITING', 'RECALL_PENDING'].includes(e.status) && e.items.some(i => i.status === 'WAITING');

            const canStart = available && called && e.visit_state === 'TEST_POOL' && e.items.some(i => ['WAITING', 'IN_PROGRESS'].includes(i.status));

            const canRelease = attending && called && e.items.some(i => i.status === 'IN_PROGRESS');

            const canEnter = e.items.some(i => ['IN_PROGRESS', 'PERFORMED', 'REPORT_READY'].includes(i.status));

            const completable = e.items.filter(i => i.status === 'PERFORMED' && i.report_status === 'DRAFT');

            const canRecall = available && called;

            const physicalText = attending ? 'Attending this department' : e.physical_status === 'BUSY_ELSEWHERE' ? `Attending ${e.busy_department}` : 'Waiting / Available';

            return <React.Fragment key={e.id}><tr>

              <td><strong>{e.token}</strong><span>{e.patient_name}</span></td>

              <td>{e.department}<span>{e.room_number ? `Room ${e.room_number}` : ''}</span></td>

              <td>{e.items.map(i => i.name).join(', ')}</td>

              <td><span className={`inv-status inv-${e.status.toLowerCase()}`}>{physicalText}</span><small className="inv-substatus">Queue: {e.status.replaceAll('_',' ')}</small></td>

              <td><div className="inv-actions inv-actions-six">

                {control('Call Patient', BellRing, canCall, () => action(`investigations/queue/${e.id}/call`, 'Patient called'), 'Requires available patient, investigation stage, and waiting test.', true)}

                {control('Start Test', Stethoscope, canStart, () => action(`investigations/queue/${e.id}/start`, 'Patient attending'), 'Patient must have been called, be present, and not attending another department.', true)}

                {control('Release Patient', DoorOpen, canRelease, () => {

                  if (window.confirm('Confirm sample collection / physical procedure is finished and the patient can leave this department? Reports will remain pending.'))

                    action(`investigations/queue/${e.id}/release`, 'Patient released');

                }, 'Start Test first. Release is separate from report completion.', true)}

                {control('Enter Results', FilePenLine, canEnter, () => showResults(e), 'Start the test before entering results.')}

                {control('Complete Report', CheckCircle2, completable.length > 0, () => {

                  setOpenId(e.id);

                  if (completable.length === 1) {

                    if (window.confirm(`Finalize ${completable[0].name} and generate its PDF now?`))

                      action(`investigations/items/${completable[0].id}/complete-test`, 'Report completed and PDF generated');

                  } else {

                    setNotice('Multiple reports have saved drafts. Complete each report separately below.');

                  }

                }, 'Release patient and save a result draft first; complete each report separately.', true)}

                {control('Recall Pending', RotateCcw, canRecall, () => action(`investigations/queue/${e.id}/recall-pending`, 'Recall pending'), 'Only a called patient who has not started attending can be recalled.')}

              </div><button className="inv-button inv-outline inv-view-tests" onClick={()=>setOpenId(openId===e.id?null:e.id)}>{openId===e.id?'Hide tests':'View tests'}</button></td>

            </tr>

            {openId===e.id && <tr className="inv-expanded"><td colSpan={5}>

              <h3>Individual investigations — {e.token}</h3>

              <p className="inv-explain">Release Patient ends physical attendance. Complete Report finalizes one saved result and generates its PDF immediately.</p>

              {e.items.map(i => <div className="inv-test" key={i.id}>

                <div><strong>{i.name}</strong><span>{i.code} · Procedure: {i.status.replaceAll('_',' ')} · Report: {i.report_status.replaceAll('_',' ')}</span></div>

                <div className="inv-actions">

                  {control('Enter Results', FilePenLine, ['IN_PROGRESS','PERFORMED','REPORT_READY'].includes(i.status), () => setReportItem(reportItem===i.id?null:i.id), 'Test has not started.')}

                  {control('Complete Report', CheckCircle2, i.status==='PERFORMED' && i.report_status==='DRAFT', () => {

                    if (window.confirm(`Finalize ${i.name} and generate its PDF now?`)) action(`investigations/items/${i.id}/complete-test`, 'Report completed and PDF generated');

                  }, 'Requires patient release and saved report draft.', true)}

                </div>

                {reportItem===i.id && <InvestigationReportForm key={`${i.id}-${i.report_status}`} slug={slug} item={i} onUpdated={load} />}

              </div>)}

            </td></tr>}

            </React.Fragment>;

          })}

          {!visible.length && <tr><td colSpan={5} className="inv-empty">No released investigation patients for your assigned department.</td></tr>}

          </tbody></table></div>

      </section>

      <section className="inv-card inv-history-section">

        <div className="inv-section-head"><div><h2>Completed Today</h2><p>Finalized investigation reports. Released patients without final reports remain in the active queue.</p></div><strong>{todayCount} reports</strong></div>

        <div className="inv-scroll"><table className="inv-table"><thead><tr><th>Token / Patient</th><th>Department</th><th>Investigation</th><th>Completed</th><th>PDF</th></tr></thead><tbody>

          {today.filter(r => selectedDepartment === 'all' || String(r.department_id) === selectedDepartment).map(r => <tr key={r.report_id}><td><strong>{r.token}</strong><span>{r.patient_name}</span></td><td>{r.department}</td><td>{r.test_name}</td><td>{new Date(r.completed_at).toLocaleString()}</td><td><button type="button" className="inv-button inv-outline" onClick={() => openReportPdf(r)}><FileText size={15}/> View / Print PDF</button></td></tr>)}

          {!today.length && <tr><td colSpan={5} className="inv-empty">No finalized reports today.</td></tr>}

        </tbody></table></div>

        <div className="inv-pagination"><button className="inv-button inv-outline" disabled={todayPage===1} onClick={()=>loadReports(archivePage,historyFilters,todayPage-1)}>Previous</button><span>Page {todayPage}</span><button className="inv-button inv-outline" disabled={!todayHasNext} onClick={()=>loadReports(archivePage,historyFilters,todayPage+1)}>Next</button></div>

      </section>

      <section className="inv-card inv-history-section">

        <div className="inv-section-head"><div><h2>Report History</h2><p>Search finalized reports for your authorized department. All PDFs remain access-controlled.</p></div><strong>{archiveTotal} reports</strong></div>

        <form className="inv-history-filters" onSubmit={e=>{e.preventDefault();const f={q:search,from:fromDate,to:toDate};setHistoryFilters(f);loadReports(1,f,todayPage);}}>

          <label>Search token, patient, test<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search reports" /></label>

          <label>From date<input type="date" value={fromDate} onChange={e=>setFromDate(e.target.value)} /></label>

          <label>To date<input type="date" value={toDate} onChange={e=>setToDate(e.target.value)} /></label>

          <button type="submit" className="inv-button inv-primary"><Search size={15}/> Search</button>

          <button type="button" className="inv-button inv-outline" onClick={()=>{setSearch('');setFromDate('');setToDate('');setHistoryFilters({q:'',from:'',to:''});loadReports(1,{q:'',from:'',to:''},todayPage);}}>Clear</button>

        </form>

        {archiveError && <div className="inv-alert inv-error">{archiveError}</div>}

        <div className="inv-scroll"><table className="inv-table"><thead><tr><th>Token / Patient</th><th>Department</th><th>Investigation</th><th>Completed</th><th>PDF</th></tr></thead><tbody>

          {archive.filter(r => selectedDepartment === 'all' || String(r.department_id) === selectedDepartment).map(r => <tr key={r.report_id}><td><strong>{r.token}</strong><span>{r.patient_name}</span></td><td>{r.department}</td><td>{r.test_name}</td><td>{new Date(r.completed_at).toLocaleString()}</td><td><button type="button" className="inv-button inv-outline" onClick={() => openReportPdf(r)}><FileText size={15}/> View / Print PDF</button></td></tr>)}

          {!archive.length && <tr><td colSpan={5} className="inv-empty">No completed reports found.</td></tr>}

        </tbody></table></div>

        <div className="inv-pagination"><button className="inv-button inv-outline" disabled={archivePage===1} onClick={()=>loadReports(archivePage-1,historyFilters,todayPage)}>Previous</button><span>Page {archivePage}</span><button className="inv-button inv-outline" disabled={!archiveHasNext} onClick={()=>loadReports(archivePage+1,historyFilters,todayPage)}>Next</button></div>

      </section>

      <p className="inv-footer"><Send size={14}/> After release, the patient may attend another department immediately. After all reports are completed, Reception confirms return for doctor review.</p>

    </main>

  </div>;

}
