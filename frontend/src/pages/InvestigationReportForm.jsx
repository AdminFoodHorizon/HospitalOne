import React, { useCallback, useEffect, useState } from 'react';
import { hospitalGet, hospitalPost, errorText } from '../services/api';

export default function InvestigationReportForm({ slug, item, onUpdated }) {
  const [report, setReport] = useState(null);
  const [fields, setFields] = useState({});
  const [texts, setTexts] = useState({ findings: '', impression: '', recommendations: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await hospitalGet(slug, `investigations/items/${item.id}/structured-report`);
      setReport(data);
      setFields(Object.fromEntries(data.fields.map(f => [f.key, {
        value: f.value ?? '', flag: f.flag || '', comment: f.comment || ''
      }])));
      setTexts({ findings: data.findings || '', impression: data.impression || '', recommendations: data.recommendations || '' });
      setMissing(false);
    } catch (e) {
      const status = e?.response?.status;
      if (status === 404 && /template/i.test(errorText(e))) setMissing(true);
      else setError(errorText(e));
    }
  }, [slug, item.id]);

  useEffect(() => { load(); }, [load]);

  const locked = report?.status === 'FINAL' || report?.status === 'AMENDED';
  const editable = !locked && ['IN_PROGRESS', 'PERFORMED'].includes(item.status);

  function change(key, prop, value) {
    setFields(old => ({ ...old, [key]: { ...old[key], [prop]: value } }));
  }

  async function perform(kind) {
    setBusy(true); setError(''); setNotice('');
    try {
      let route = `investigations/items/${item.id}/structured-report/`;
      let data;
      if (kind === 'draft') {
        const res = await hospitalPost(slug, route + 'draft', { ...texts, values: fields });
        data = res.data;
      } else {
        const res = await hospitalPost(slug, route + 'complete');
        data = res.data;
      }
      setNotice(data.detail || 'Updated');
      await load();
      await onUpdated();
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  if (missing) return <div className="inv-report-message">No template configured for this test. Ask the hospital administrator to configure an approved template.</div>;
  if (!report) return <div className="inv-report-message">{error || 'Loading reporting form...'}</div>;
  const sections = [...new Set(report.fields.map(f => f.section || 'Results'))];
  return <div className="inv-report-form">
    <div className="inv-report-heading"><div><strong>{report.template.name}</strong><small>{report.template.format.replaceAll('_', ' ')} · Template v{report.template.version}</small></div><span className="inv-report-status">{report.status.replaceAll('_', ' ')}</span></div>
    {sections.map(section => <div key={section} className="inv-report-section">
      <h4>{section}</h4>
      <div className="inv-report-grid">{report.fields.filter(f => (f.section || 'Results') === section).map(f => <label key={f.key} className="inv-report-field">
        <span>{f.label}{f.required ? ' *' : ''}{f.unit ? ` (${f.unit})` : ''}</span>
        {f.value_type === 'BOOLEAN' ? <select disabled={!editable} value={fields[f.key]?.value === '' ? '' : String(fields[f.key]?.value)} onChange={e => change(f.key, 'value', e.target.value === '' ? '' : e.target.value === 'true')}><option value="">Not entered</option><option value="true">Yes</option><option value="false">No</option></select>
        : f.value_type === 'CHOICE' ? <select disabled={!editable} value={fields[f.key]?.value ?? ''} onChange={e => change(f.key, 'value', e.target.value)}><option value="">Select...</option>{f.choice_options.map(option => <option key={option} value={option}>{option}</option>)}</select>
        : f.value_type === 'LONG_TEXT' ? <textarea disabled={!editable} rows={3} value={fields[f.key]?.value ?? ''} onChange={e => change(f.key, 'value', e.target.value)} />
        : <input disabled={!editable} type={f.value_type === 'DATE' ? 'date' : f.value_type === 'NUMBER' ? 'number' : 'text'} step={f.value_type === 'NUMBER' ? 'any' : undefined} value={fields[f.key]?.value ?? ''} onChange={e => change(f.key, 'value', e.target.value)} />}
        {f.reference_text && <small>Reference: {f.reference_text}</small>}
        <div className="inv-flag-row"><select aria-label={`Flag for ${f.label}`} disabled={!editable} value={fields[f.key]?.flag || ''} onChange={e => change(f.key, 'flag', e.target.value)}>{['', 'NORMAL', 'LOW', 'HIGH', 'ABNORMAL', 'CRITICAL'].map(x => <option key={x} value={x}>{x || 'No flag'}</option>)}</select><input aria-label={`Comment for ${f.label}`} disabled={!editable} placeholder="Optional comment" value={fields[f.key]?.comment || ''} onChange={e => change(f.key, 'comment', e.target.value)} /></div>
      </label>)}</div>
    </div>)}
    <div className="inv-report-grid">{[['findings', 'Findings'], ['impression', 'Impression'], ['recommendations', 'Recommendations']].map(([key, label]) => <label className="inv-report-field" key={key}><span>{label}</span><textarea rows={3} disabled={!editable} value={texts[key]} onChange={e => setTexts(old => ({ ...old, [key]: e.target.value }))} /></label>)}</div>
    <div className="inv-report-buttons">
      {editable && <button className="inv-button inv-outline" disabled={busy} onClick={() => perform('draft')}>Save Draft</button>}
      {report.status === 'DRAFT' && item.status === 'PERFORMED' && <button type="button" className="inv-button inv-primary" disabled={busy} onClick={() => { if (window.confirm(`Finalize ${item.name} and generate its PDF? This report will become read-only.`)) perform('complete'); }}>Complete Report & Generate PDF</button>}
      {report.status === 'DRAFT' && item.status !== 'PERFORMED' && <small>Draft saved. Release the patient before completing the report.</small>}
      {report.status === 'FINAL' && <a className="inv-button inv-outline" href={`/api/hospital/${encodeURIComponent(slug)}/investigations/items/${item.id}/structured-report/pdf/`} target="_blank" rel="noopener noreferrer">View / Print Final PDF</a>}

    </div>
    <small>Only authorized staff can complete a report. Completed reports become read-only. Clinically appropriate reference intervals and results must be checked by the responsible professional before completion.</small>
    {error && <div className="inv-alert inv-error" role="alert">{error}</div>}
    {notice && <div className="inv-alert inv-notice" role="status">{notice}</div>}
  </div>;
}
