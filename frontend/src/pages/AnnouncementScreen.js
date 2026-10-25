import React, { useEffect, useRef, useState } from 'react';
import './AnnouncementScreen.css';

const CSRF_URL = '/api/hospital/csrf/';
const POLL_MS = 2000;
const MAX_ACTIVE = 8;

function csrfToken() {
  const raw = document.cookie.split('; ').find((part) => part.startsWith('csrftoken='));
  return raw ? decodeURIComponent(raw.slice('csrftoken='.length)) : '';
}

async function apiRequest(url, method = 'GET', body) {
  if (method !== 'GET') {
    await fetch(CSRF_URL, { credentials: 'same-origin' });
  }
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    cache: 'no-store',
    headers: method === 'GET' ? {} : {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrfToken(),
    },
    body: method === 'GET' ? undefined : JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok && response.status !== 202) {
    const error = new Error(data.detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function secondsLeft(entry, now) {
  const expiry = Date.parse(entry.expires_at || '');
  return Number.isFinite(expiry) ? Math.max(0, Math.ceil((expiry - now) / 1000)) : 0;
}

function countdown(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

export default function AnnouncementScreen({ hospital, hospitalSlug }) {
  const root = `/api/hospital/${encodeURIComponent(hospitalSlug)}/announcement/display/`;
  const [mode, setMode] = useState('loading');
  const [pairing, setPairing] = useState(null);
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState('');
  const [sound, setSound] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [connected, setConnected] = useState(false);
  const lastSeenId = useRef(null);
  const soundRef = useRef(false);
  const speechQueue = useRef([]);
  const speaking = useRef(false);
  const speakNextRef = useRef(null);

  speakNextRef.current = () => {
    if (!soundRef.current || speaking.current || !('speechSynthesis' in window)) return;
    const event = speechQueue.current.shift();
    if (!event) return;
    speaking.current = true;
    const utterance = new SpeechSynthesisUtterance(
      `Token ${event.token}. Please proceed to ${event.department}, room ${event.room_number}.`
    );
    utterance.lang = 'en-US';
    utterance.rate = 0.88;
    utterance.volume = 1;
    const finish = () => {
      speaking.current = false;
      speakNextRef.current?.();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  };

  const startPairing = async () => {
    setError('');
    setMode('loading');
    try {
      const result = await apiRequest(root + 'pairing/request/', 'POST', {
        device_name: 'Central Announcement TV',
      });
      setPairing(result);
      setMode('pairing');
    } catch (err) {
      setError(err.message);
      setMode('error');
    }
  };

  useEffect(() => {
    let cancelled = false;
    lastSeenId.current = null;
    speechQueue.current = [];
    setEntries([]);
    setMode('loading');
    setError('');
    async function initialize() {
      try {
        const data = await apiRequest(root + 'events/');
        if (cancelled) return;
        const items = Array.isArray(data.entries) ? data.entries : [];
        lastSeenId.current = items.reduce((max, e) => Math.max(max, Number(e.event_id) || 0), 0);
        setEntries(items);
        setConnected(true);
        setMode('live');
      } catch (err) {
        if (cancelled) return;
        if (err.status !== 403) {
          setError(err.message);
          setMode('error');
          return;
        }
        try {
          const result = await apiRequest(root + 'pairing/request/', 'POST', {
            device_name: 'Central Announcement TV',
          });
          if (cancelled) return;
          setPairing(result);
          setMode('pairing');
        } catch (pairErr) {
          if (cancelled) return;
          setError(pairErr.message);
          setMode('error');
        }
      }
    }
    initialize();
    return () => {
      cancelled = true;
      speechQueue.current = [];
      speaking.current = false;
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    };
  }, [root]);

  useEffect(() => {
    if (mode !== 'pairing' || !pairing) return undefined;
    let cancelled = false;
    let running = false;
    async function poll() {
      if (running) return;
      running = true;
      try {
        const result = await apiRequest(root + 'pairing/claim/', 'POST', {
          request_id: pairing.request_id,
          pairing_secret: pairing.pairing_secret,
        });
        if (!cancelled && result.status === 'PAIRED') {
          lastSeenId.current = null;
          setPairing(null);
          setEntries([]);
          setError('');
          setMode('live');
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setMode('error');
        }
      } finally {
        running = false;
      }
    }
    const timer = setInterval(poll, 2500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [mode, pairing, root]);

  useEffect(() => {
    if (mode !== 'live') return undefined;
    let cancelled = false;
    let running = false;
    async function poll() {
      if (running) return;
      running = true;
      try {
        const data = await apiRequest(root + 'events/');
        if (cancelled) return;
        const items = Array.isArray(data.entries) ? data.entries : [];
        const maxId = items.reduce((max, e) => Math.max(max, Number(e.event_id) || 0), 0);
        if (lastSeenId.current === null) {
          lastSeenId.current = maxId;
        } else {
          const fresh = items.filter((e) => Number(e.event_id) > lastSeenId.current)
            .sort((a, b) => Number(a.event_id) - Number(b.event_id));
          lastSeenId.current = Math.max(lastSeenId.current, maxId);
          if (soundRef.current && fresh.length) {
            speechQueue.current.push(...fresh);
            speakNextRef.current?.();
          }
        }
        setEntries(items);
        setConnected(true);
        setError('');
      } catch (err) {
        if (cancelled) return;
        setConnected(false);
        setError(err.message);
        if (err.status === 403) {
          setEntries([]);
          setMode('error');
        }
      } finally {
        running = false;
      }
    }
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [mode, root]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const enableSound = () => {
    if (!('speechSynthesis' in window)) {
      setError('Voice announcements are not supported by this browser.');
      return;
    }
    soundRef.current = true;
    setSound(true);
    window.speechSynthesis.cancel();
    speaking.current = false;
    const confirmation = new SpeechSynthesisUtterance('Hospital announcements enabled');
    confirmation.lang = 'en-US';
    confirmation.rate = 0.9;
    window.speechSynthesis.speak(confirmation);
  };

  const active = entries.filter((entry) => secondsLeft(entry, now) > 0).slice(0, MAX_ACTIVE);
  const latest = active[0] || null;
  const others = active.slice(1);

  return (
    <main className="ho-tv">
      <header className="ho-tv-header">
        <div className="ho-tv-brand">
          <div className="ho-tv-kicker">CENTRAL ANNOUNCEMENTS</div>
          <h1>{hospital?.name || 'Hospital'}</h1>
        </div>
        <div className="ho-tv-actions">
          {mode === 'live' && <span className={`ho-tv-live ${connected ? '' : 'ho-tv-offline'}`}>{connected ? '● LIVE' : '● RECONNECTING'}</span>}
          {mode === 'live' && (!sound ? <button className="ho-tv-sound" onClick={enableSound}>Enable sound</button> : <span className="ho-tv-sound-on">🔊 Sound on</span>)}
        </div>
      </header>

      {mode === 'loading' && <section className="ho-tv-center"><h2>Connecting to announcements…</h2></section>}

      {mode === 'pairing' && pairing && (
        <section className="ho-tv-center ho-tv-pairing">
          <h2>TV Authorization Required</h2>
          <p>Ask the hospital administrator to approve this TV.</p>
          <div className="ho-tv-code">{pairing.pairing_code}</div>
          <p>Pairing code expires in five minutes · Waiting for approval</p>
        </section>
      )}

      {mode === 'live' && (
        <section className="ho-tv-board">
          <div className="ho-tv-board-head">
            <span>ACTIVE PATIENT CALLS</span>
            <strong>{active.length} / {MAX_ACTIVE}</strong>
          </div>
          {latest ? (
            <div className="ho-tv-layout">
              <article className="ho-tv-featured" key={latest.event_id}>
                <span className="ho-tv-card-label">LATEST CALL</span>
                <div className="ho-tv-featured-token">{latest.token}</div>
                <div className="ho-tv-featured-dept">{latest.department}</div>
                <div className="ho-tv-featured-room">ROOM {latest.room_number}</div>
                <div className="ho-tv-featured-time">Remaining {countdown(secondsLeft(latest, now))}</div>
              </article>
              <div className="ho-tv-grid">
                {others.map((entry) => {
                  const remaining = secondsLeft(entry, now);
                  return (
                    <article className="ho-tv-card" key={entry.event_id}>
                      <div className="ho-tv-card-dept">{entry.department}</div>
                      <div className="ho-tv-card-token">{entry.token}</div>
                      <div className="ho-tv-card-room">ROOM {entry.room_number}</div>
                      <div className={`ho-tv-card-time ${remaining <= 60 ? 'ho-tv-urgent' : ''}`}>{countdown(remaining)} remaining</div>
                    </article>
                  );
                })}
                {Array.from({ length: Math.max(0, 7 - others.length) }, (_, index) => (
                  <div className="ho-tv-empty-slot" key={`empty-${index}`} aria-hidden="true" />
                ))}
              </div>
            </div>
          ) : (
            <div className="ho-tv-waiting">
              <div className="ho-tv-waiting-icon">◌</div>
              <h2>Waiting for next call</h2>
              <p>New patient calls appear automatically.</p>
            </div>
          )}
        </section>
      )}

      {mode === 'error' && (
        <section className="ho-tv-center">
          <h2>TV Setup Required</h2>
          <p>Reconnect or authorize this TV to resume announcements.</p>
          <button className="ho-tv-retry" onClick={startPairing}>Generate new pairing code</button>
        </section>
      )}

      <footer className="ho-tv-footer">
        <span>Check your token and proceed to the displayed room.</span>
        {error && <span className="ho-tv-error" role="alert">{error}</span>}
        <span>Calls expire after 5 minutes</span>
      </footer>
    </main>
  );
}
