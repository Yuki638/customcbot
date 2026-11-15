// Signing in, and the password section of Settings.

import { html, useEffect, useState } from '/i18n.js';
import { api } from '/api.js';
import { toast } from '/components/ui.js';

export function SignIn({ onDone }) {
  const [password, setPassword] = useState('');
  const [problem, setProblem] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.post('/api/auth/login', { password });
      onDone();
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  };
  return html`
    <form class="card stack signin" onSubmit=${submit}>
      <h2>customcbot</h2>
      <p class="muted">This copy of customcbot is protected by a password.</p>
      <label class="field">Password
        <input type="password" autocomplete="current-password" autofocus value=${password} onInput=${(e) => setPassword(e.target.value)} />
      </label>
      ${problem && html`<div class="banner err" role="alert">${problem}</div>`}
      <div><button class="btn primary" disabled=${busy || !password}>Sign in</button></div>
    </form>
  `;
}

export function PasswordSettings() {
  const [status, setStatus] = useState(null);
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [open, setOpen] = useState(false);

  const load = () => api.get('/api/auth/status').then(setStatus).catch(() => {});
  useEffect(() => { load(); }, []);
  if (!status) return null;

  const save = async (value) => {
    try {
      await api.put('/api/auth/password', { new_password: value, current_password: current });
      setCurrent('');
      setNext('');
      setOpen(false);
      await load();
      toast(value ? 'Password saved.' : 'Password removed.');
    } catch (error) {
      toast(error.message);
    }
  };

  if (status.fixed) {
    return html`<p class="muted small">A password is set where the app is started (CUSTOMCBOT_PASSWORD). It cannot be changed here.</p>`;
  }
  return html`
    <div class="stack" style="gap: 8px">
      <div class="row wrap">
        <div class="grow">
          <strong>Password</strong>
          <div class="muted small">${status.required
            ? 'A password is set. Anyone opening the app has to sign in.'
            : 'No password. That is fine while only this computer can open the app.'}</div>
        </div>
        ${!open && html`<button class="btn" onClick=${() => setOpen(true)}>${status.required ? 'Change' : 'Set a password'}</button>`}
      </div>
      ${open && html`
        ${status.required && html`
          <label class="field">Current password
            <input type="password" autocomplete="current-password" value=${current} onInput=${(e) => setCurrent(e.target.value)} />
          </label>`}
        <label class="field">New password (at least 6 characters)
          <input type="password" autocomplete="new-password" value=${next} onInput=${(e) => setNext(e.target.value)} />
        </label>
        <div class="row wrap">
          <button class="btn primary" disabled=${next.length < 6} onClick=${() => save(next)}>Save password</button>
          ${status.required && html`<button class="btn danger" disabled=${!current} onClick=${() => save('')}>Remove password</button>`}
          <button class="btn" onClick=${() => setOpen(false)}>Cancel</button>
        </div>`}
    </div>
  `;
}
