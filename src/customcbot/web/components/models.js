// "AI services and models": save several services, and choose which model does which job.

import { html, useEffect, useState } from '/i18n.js';
import { api } from '/api.js';
import { Dialog, toast } from '/components/ui.js';

const JOBS = [
  { id: 'chat', label: 'Answering questions', hint: 'Used in the Chat tab.' },
  { id: 'transformation', label: 'Summaries, quizzes and flashcards', hint: 'Longer work that runs in the background.', fallback: 'Same as answering questions' },
  { id: 'vision', label: 'Reading handwriting and scanned pages', hint: 'Needs a model that can read images.', fallback: 'The chat model, if it can read images' },
];

function AddService({ providers, onAdded }) {
  const online = providers.filter((p) => !p.local);
  const [providerId, setProviderId] = useState(online[0] ? online[0].id : '');
  const provider = online.find((p) => p.id === providerId);
  const [address, setAddress] = useState('');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);

  if (!provider) return null;
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.post('/api/credentials', { provider: provider.id, base_url: address, api_key: key });
      setKey('');
      setAddress('');
      toast(`${provider.label} is saved. Now add a model from it.`);
      await onAdded();
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  };

  return html`
    <form class="card stack" onSubmit=${submit}>
      <strong>Add a service</strong>
      <label class="field">Service
        <select value=${providerId} onChange=${(e) => { setProviderId(e.target.value); setProblem(null); }}>
          ${online.map((p) => html`<option value=${p.id} key=${p.id}>${p.label}</option>`)}
        </select>
      </label>
      <p class="muted small">${provider.blurb}
        ${provider.key_url && html`${' '}<a href=${provider.key_url} target="_blank" rel="noreferrer">Get a key</a>.`}</p>
      ${(!provider.base_url || provider.id === 'freellmapi') && html`
        <label class="field">Address
          <input type="text" placeholder=${provider.base_url || 'https://…/v1'} value=${address} onInput=${(e) => setAddress(e.target.value)} />
        </label>`}
      <label class="field">${provider.needs_key ? 'Key' : 'Key (leave empty if the service needs none)'}
        <input type="password" autocomplete="off" placeholder="Paste your key here" value=${key} onInput=${(e) => setKey(e.target.value)} />
      </label>
      ${problem && html`<div class="banner err" role="alert">${problem}</div>`}
      <div><button class="btn primary" disabled=${busy || (provider.needs_key && !key.trim())}>${busy ? 'Checking…' : 'Check and save'}</button></div>
    </form>
  `;
}

function AddModel({ credential, onAdded }) {
  const [offered, setOffered] = useState(null);
  const [name, setName] = useState('');
  const [vision, setVision] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState(null);

  const open = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const found = await api.get(`/api/credentials/${credential.id}/discover`);
      const fresh = found.models.filter((m) => !m.saved).map((m) => m.name);
      setOffered(fresh);
      setName(found.suggested || fresh[0] || '');
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  };
  const add = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await api.post('/api/models', { credential_id: credential.id, name, vision });
      setOffered(null);
      setVision(false);
      await onAdded();
    } catch (error) {
      setProblem(error.message);
    } finally {
      setBusy(false);
    }
  };

  if (offered === null) {
    return html`
      ${problem && html`<div class="banner err" role="alert">${problem}</div>`}
      <div><button class="btn small" disabled=${busy} onClick=${open}>${busy ? 'Looking…' : 'Add a model'}</button></div>`;
  }
  return html`
    <div class="stack">
      <label class="field">Model to add
        ${offered.length
          ? html`<select value=${name} onChange=${(e) => setName(e.target.value)}>
              ${offered.map((n) => html`<option value=${n} key=${n}>${n}</option>`)}
            </select>`
          : html`<input type="text" placeholder="the model name" value=${name} onInput=${(e) => setName(e.target.value)} />`}
      </label>
      <label class="row small">
        <input type="checkbox" checked=${vision} onChange=${(e) => setVision(e.target.checked)} />
        <span>This model can read images</span>
      </label>
      ${problem && html`<div class="banner err" role="alert">${problem}</div>`}
      <div class="row">
        <button class="btn primary small" disabled=${busy || !name.trim()} onClick=${add}>${busy ? 'Testing…' : 'Test and add'}</button>
        <button class="btn small" onClick=${() => setOffered(null)}>Cancel</button>
      </div>
    </div>`;
}

function Service({ credential, reload }) {
  const act = async (work) => {
    try {
      await work();
      await reload();
    } catch (error) {
      toast(error.message);
    }
  };
  return html`
    <div class="card stack">
      <div class="row wrap">
        <div class="grow">
          <strong>${credential.name}</strong>
          <div class="muted small">
            ${credential.local ? 'Runs on this computer. Nothing is sent anywhere.' : credential.base_url}
            ${!credential.local && html` · ${credential.has_key ? 'key saved' : 'no key'}`}
          </div>
        </div>
        ${!credential.local && html`
          <button class="btn small danger" onClick=${() => act(() => api.del(`/api/credentials/${credential.id}`))}>Remove</button>`}
      </div>
      ${credential.models.length === 0 && html`<p class="muted small">No models saved from this service yet.</p>`}
      ${credential.models.map((model) => html`
        <div class="list-row" key=${model.id}>
          <span class="grow">${model.name}</span>
          <label class="row small" title="Tick this if the model can read images">
            <input type="checkbox" checked=${model.vision}
              onChange=${(e) => act(() => api.patch(`/api/models/${model.id}`, { vision: e.target.checked }))} />
            <span>reads images</span>
          </label>
          <button class="btn small ghost danger" onClick=${() => act(() => api.del(`/api/models/${model.id}`))}>Remove</button>
        </div>`)}
      <${AddModel} credential=${credential} onAdded=${reload} />
    </div>
  `;
}

export function ModelsDialog({ onClose, refresh }) {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(null);

  const reload = async () => {
    try {
      const [providers, credentials, models] = await Promise.all([
        api.get('/api/providers'), api.get('/api/credentials'), api.get('/api/models'),
      ]);
      setData({ providers, credentials, models: models.models, defaults: models.defaults });
      setFailed(null);
      await refresh();
    } catch (error) {
      setFailed(error.message);
    }
  };
  useEffect(() => { reload(); }, []);

  const choose = async (job, value) => {
    try {
      await api.put('/api/models/defaults', { [job]: value === '' ? null : Number(value) });
      await reload();
    } catch (error) {
      toast(error.message);
    }
  };

  return html`
    <${Dialog} title="AI services and models" wide onClose=${onClose}
      footer=${html`<button class="btn primary" onClick=${onClose}>Done</button>`}>
      ${failed && html`<div class="banner err" role="alert">${failed}</div>`}
      ${!data && !failed && html`<p class="muted">Loading…</p>`}
      ${data && html`
        <h3>Which model does what</h3>
        <p class="muted small">You can use a different model for each kind of work, for example a fast one for chat and a larger one for quizzes.</p>
        ${JOBS.map((job) => {
          const state = data.defaults[job.id];
          const choices = data.models.filter((m) => m.type === 'language' && (job.id !== 'vision' || m.vision));
          return html`
            <label class="field" key=${job.id}>${job.label}
              <select value=${state.model_id === null ? '' : String(state.model_id)} onChange=${(e) => choose(job.id, e.target.value)}>
                ${job.fallback && html`<option value="">${job.fallback}</option>`}
                ${choices.map((m) => html`<option value=${String(m.id)} key=${m.id}>${m.name} (${m.service})</option>`)}
              </select>
              <span class="muted small">${job.hint}
                ${' '}${state.uses ? `Now: ${state.uses.name} (${state.uses.service}).` : (job.id === 'vision' ? 'Now: none, so only printed text is read.' : 'Now: none.')}</span>
            </label>`;
        })}
        <h3>Saved services</h3>
        ${data.credentials.map((credential) => html`<${Service} credential=${credential} reload=${reload} key=${credential.id} />`)}
        ${data.credentials.length === 0 && html`<p class="muted small">Nothing is saved yet.</p>`}
        <${AddService} providers=${data.providers} onAdded=${reload} />
        <p class="muted small">With an online model, your question and the passages that match it are sent to that service. If it reads images, the page images are sent too.</p>`}
    <//>
  `;
}
