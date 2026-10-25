import React, { useState } from 'react';
import { hospitalPost, errorText } from '../services/api';
import './ReceptionDirectEmail.css';

export default function ReceptionDirectEmail({ hospital, itemId, patientName, email, testName }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [error, setError] = useState('');
  const valid = !!(email && String(email).includes('@'));
  const send = async () => {
    if (!valid || busy) return;
    setBusy(true); setError(''); setResult('');
    try {
      const response = await hospitalPost(hospital.slug,
        `reception/investigation-reports/${itemId}/email-pdf`,
        { confirm_recipient: true, recipient: email });
      setResult(response.data?.detail || 'Gmail accepted the report.');
      setOpen(false);
    } catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  };
  return <span className="rec-direct-email">
    <button type="button" className="rec-report-btn rec-direct-email-trigger"
      onClick={() => { setOpen(true); setError(''); setResult(''); }}>
      Email PDF
    </button>
    {result && <span role="status" className="rec-direct-email-success">{result}</span>}
    {error && <span role="alert" className="rec-direct-email-error">{error}</span>}
    {open && <div className="rec-direct-email-overlay" role="presentation">
      <div className="rec-direct-email-modal" role="dialog" aria-modal="true" aria-label="Send investigation report">
        <h3>Send finalized report</h3>
        <p><strong>Patient:</strong> {patientName || 'Patient'}</p>
        <p><strong>Investigation:</strong> {testName || 'Report'}</p>
        <p><strong>Registered email:</strong> {email || 'Not available'}</p>
        <p>The PDF will be generated in memory and sent directly as a Gmail attachment. It will not expire after sending.</p>
        {!valid && <p className="rec-direct-email-error">Add the patient's email in Reception before sending.</p>}
        {error && <p role="alert" className="rec-direct-email-error">{error}</p>}
        <div className="rec-direct-email-actions">
          <button type="button" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
          <button type="button" onClick={send} disabled={!valid || busy}>{busy ? 'Sending…' : 'Confirm and send PDF'}</button>
        </div>
      </div>
    </div>}
  </span>;
}
