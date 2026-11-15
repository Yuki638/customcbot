// Small shared building blocks.

import { html, useEffect, useRef, useState } from '/vendor/preact-htm.js';
import { api } from '/api.js';
import { onMathReady, renderMarkdown } from '/md.js';

let showToast = () => {};

export function toast(message) {
  showToast(message);
}

export function ToastHost() {
  const [message, setMessage] = useState(null);
  useEffect(() => {
    let timer;
    showToast = (text) => {
      setMessage(text);
      clearTimeout(timer);
      timer = setTimeout(() => setMessage(null), 4000);
    };
    return () => clearTimeout(timer);
  }, []);
  return message && html`<div class="toast" role="status">${message}</div>`;
}

export function Dialog({ title, onClose, wide, footer, children }) {
  useEffect(() => {
    const onKey = (event) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return html`
    <div class="overlay" onMouseDown=${(event) => event.target === event.currentTarget && onClose()}>
      <div class=${`dialog${wide ? ' wide' : ''}`} role="dialog" aria-modal="true" aria-label=${title}>
        <header>
          <h2>${title}</h2>
          <button class="btn ghost icon" onClick=${onClose} aria-label="Close">✕</button>
        </header>
        <div class="body">${children}</div>
        ${footer && html`<footer>${footer}</footer>`}
      </div>
    </div>
  `;
}

export function Progress({ value, busy }) {
  const percent = Math.round(Math.max(0, Math.min(value || 0, 1)) * 100);
  return html`
    <div class=${`progress${busy ? ' busy' : ''}`} role="progressbar" aria-valuenow=${percent} aria-valuemin="0" aria-valuemax="100">
      <div style=${`width: ${percent}%`}></div>
    </div>
  `;
}

export function Markdown({ text, citations, onCite }) {
  const [, rerender] = useState(0);
  useEffect(() => onMathReady(() => rerender((n) => n + 1)), []);
  const onClick = (event) => {
    const button = event.target.closest('[data-cite]');
    if (button && onCite) onCite(Number(button.dataset.cite));
  };
  return html`<div class="md" onClick=${onClick} dangerouslySetInnerHTML=${{ __html: renderMarkdown(text, citations) }}></div>`;
}

// Tracks one background task (summary, quiz or flashcard generation) for a collection.
// Picks up a task that is already running, so progress survives a page reload.
export function useJob(collectionId, kinds, onDone) {
  const [job, setJob] = useState(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    let cancelled = false;
    setJob(null);
    api.get(`/api/collections/${collectionId}/jobs`).then((jobs) => {
      const running = jobs.find((j) => kinds.includes(j.kind));
      if (running && !cancelled) setJob(running);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [collectionId]);

  const active = job && (job.status === 'queued' || job.status === 'running');
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(async () => {
      try {
        const latest = await api.get(`/api/jobs/${job.id}`);
        setJob(latest);
        if (latest.status === 'done') onDoneRef.current && onDoneRef.current(latest);
      } catch { /* keep polling */ }
    }, 1000);
    return () => clearInterval(timer);
  }, [active, job && job.id]);

  return {
    job,
    active,
    error: job && job.status === 'error' && job.error !== 'Cancelled' ? job.error : null,
    async start(path, body) {
      try {
        setJob(await api.post(path, body));
      } catch (error) {
        toast(error.message);
      }
    },
    async cancel() {
      if (job) await api.del(`/api/jobs/${job.id}`).catch(() => {});
    },
    clear: () => setJob(null),
  };
}

export function JobProgress({ task, label }) {
  if (!task.active) {
    return task.error && html`
      <div class="banner err row">
        <span class="grow">${task.error}</span>
        <button class="btn small" onClick=${task.clear}>Dismiss</button>
      </div>`;
  }
  const job = task.job;
  return html`
    <div class="card stack">
      <div class="row">
        <strong class="grow">${job.status === 'queued' ? 'Waiting for other work to finish…' : job.stage || label}</strong>
        <button class="btn small" onClick=${task.cancel}>Cancel</button>
      </div>
      <${Progress} value=${job.progress} busy=${job.status === 'queued'} />
      <span class="muted small">This can take a few minutes. You can keep using the other tabs.</span>
    </div>
  `;
}
