import React, { useState } from 'react';

// Render this component ONLY inside an already authenticated hospital ADMIN page.
// The backend independently enforces membership and fresh TOTP verification.
export default function DisplayPairingApproval({ hospitalSlug }) {
  const [pairingCode, setPairingCode] = useState('');
  const [totpCode, setTotpCode] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setMessage('');
    try {
      await fetch('/api/hospital/csrf/', { credentials: 'same-origin' });
      const token = document.cookie.split('; ').find(x => x.startsWith('csrftoken='))?.split('=').slice(1).join('=') || '';
      const response = await fetch(`/api/hospital/${encodeURIComponent(hospitalSlug)}/announcement/display/pairing/approve/`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(token) },
        body: JSON.stringify({ pairing_code: pairingCode, totp_code: totpCode }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Approval failed');
      setMessage('TV approved. It will connect automatically.');
      setPairingCode('');
    } catch (err) {
      setMessage(err.message);
    } finally {
      setTotpCode('');
      setBusy(false);
    }
  }

  return <section style={{ maxWidth: 420, margin: '2rem auto' }}>
    <h2>Approve Central Announcement TV</h2>
    <p>Check the code on the physical TV before approving.</p>
    <form onSubmit={submit}>
      <label htmlFor="tv-code">TV pairing code</label>
      <input id="tv-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6}
        autoComplete="off" required value={pairingCode}
        onChange={e => setPairingCode(e.target.value)} />
      <label htmlFor="tv-totp">Fresh authenticator code</label>
      <input id="tv-totp" inputMode="numeric" pattern="[0-9]{6}" maxLength={6}
        autoComplete="one-time-code" required value={totpCode}
        onChange={e => setTotpCode(e.target.value)} />
      <button disabled={busy} type="submit">{busy ? 'Approving…' : 'Approve TV'}</button>
    </form>
    {message && <p role="status">{message}</p>}
  </section>;
}
