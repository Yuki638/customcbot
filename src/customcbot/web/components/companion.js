// The study companion: a named character with a face, who answers in chat,
// reacts in quizzes and remembers a few things about you.

import { html, t, useEffect, useState } from '/i18n.js';
import { api } from '/api.js';
import { Dialog, toast } from '/components/ui.js';

// One copy of the companion's settings, shared by every component that shows the face.
let current = { enabled: false, name: '', memory: false };
let version = 0;  // added to picture addresses, so a new picture shows without reloading
const listeners = new Set();

function set(next) {
  current = next;
  version += 1;
  listeners.forEach((listener) => listener(current));
}

export async function loadCompanion() {
  try { set(await api.get('/api/companion')); } catch { /* the app works without it */ }
}

export function useCompanion() {
  const [value, setValue] = useState(current);
  useEffect(() => {
    listeners.add(setValue);
    setValue(current);
    return () => listeners.delete(setValue);
  }, []);
  return value;
}

// mood: neutral, happy, thinking or sad.
export function Face({ mood = 'neutral', size = 36 }) {
  const companion = useCompanion();
  if (!companion.enabled) return null;
  return html`<img class="face" src=${`/api/companion/face/${mood}?v=${version}`} alt=${companion.name}
    width=${size} height=${size} style=${`width: ${size}px; height: ${size}px`} />`;
}

function Memories({ name }) {
  const [list, setList] = useState(null);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(null);  // { id, content }

  const load = () => api.get('/api/memories').then(setList).catch((error) => toast(error.message));
  useEffect(() => { load(); }, []);

  const act = async (work) => {
    try { await work(); await load(); } catch (error) { toast(error.message); }
  };
  const add = (event) => {
    event.preventDefault();
    act(async () => { await api.post('/api/memories', { content: draft }); setDraft(''); });
  };
  const saveEdit = () => act(async () => {
    await api.put(`/api/memories/${editing.id}`, { content: editing.content });
    setEditing(null);
  });
  const forgetAll = () => {
    if (window.confirm(t('Forget everything? This cannot be undone.'))) act(() => api.del('/api/memories'));
  };

  if (!list) return html`<p class="muted">Loading…</p>`;
  return html`
    <div class="stack">
      ${list.length === 0 && html`<p class="muted small">${t('Nothing yet. Tell {name} your name, what you are studying or when your exam is, or add it here.', { name })}</p>`}
      ${list.map((memory) => html`
        <div class="list-row" key=${memory.id}>
          ${editing && editing.id === memory.id
            ? html`
              <input class="grow" type="text" maxlength="200" aria-label="Memory" value=${editing.content}
                onInput=${(e) => setEditing({ ...editing, content: e.target.value })} />
              <button class="btn primary small" onClick=${saveEdit}>Save</button>
              <button class="btn small" onClick=${() => setEditing(null)}>Cancel</button>`
            : html`
              <span class="grow">${memory.content}</span>
              <button class="btn small" onClick=${() => setEditing({ id: memory.id, content: memory.content })}>Edit</button>
              <button class="btn ghost small danger" onClick=${() => act(() => api.del(`/api/memories/${memory.id}`))}>Forget</button>`}
        </div>`)}
      <form class="row" onSubmit=${add}>
        <input class="grow" type="text" maxlength="200" placeholder="For example: my exam is on 12 June" aria-label="Something to remember"
          value=${draft} onInput=${(e) => setDraft(e.target.value)} />
        <button class="btn" disabled=${!draft.trim()}>Remember</button>
      </form>
      ${list.length > 0 && html`<div><button class="btn ghost small danger" onClick=${forgetAll}>Forget everything</button></div>`}
    </div>`;
}

export function CompanionDialog({ onClose }) {
  const companion = useCompanion();
  const [name, setName] = useState(companion.name);

  const change = async (values) => {
    try { set(await api.put('/api/companion', values)); } catch (error) { toast(error.message); }
  };

  return html`
    <${Dialog} title="Study companion" wide onClose=${onClose}
      footer=${html`<button class="btn primary" onClick=${onClose}>Done</button>`}>
      <label class="check">
        <input type="checkbox" checked=${companion.enabled} onChange=${(e) => change({ enabled: e.target.checked })} />
        Show a study companion
      </label>
      <p class="muted small">A character who answers your questions in a friendly voice and reacts in quizzes. The answers still come from your material, with the same sources.</p>
      ${companion.enabled && html`
        <div class="row companion-card">
          <${Face} mood="happy" size=${72} />
          <form class="row grow" onSubmit=${(e) => { e.preventDefault(); change({ name }); }}>
            <label class="field grow">Name
              <input type="text" maxlength="24" value=${name} onInput=${(e) => setName(e.target.value)} />
            </label>
            <button class="btn" disabled=${!name.trim() || name.trim() === companion.name}>Save</button>
          </form>
        </div>
        <p class="muted small">${companion.own_pictures
          ? 'Using your own pictures from this folder:'
          : 'To use your own character, put pictures named neutral, happy, thinking and sad (PNG, JPG, WebP or GIF) in this folder. One picture named neutral is enough.'}
          ${' '}<code>${companion.pictures_folder}</code></p>

        <h3>${t('What {name} remembers about you', { name: companion.name })}</h3>
        <label class="check">
          <input type="checkbox" checked=${companion.memory} onChange=${(e) => change({ memory: e.target.checked })} />
          Remember things about me
        </label>
        <p class="muted small">Kept on this computer only. When it is on, your messages are also read for things worth remembering, by the same model that answers you.</p>
        ${companion.memory && html`<${Memories} name=${companion.name} />`}`}
    <//>
  `;
}
