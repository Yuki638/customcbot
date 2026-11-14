// App shell: setup gate, collections sidebar, and the tabs of the open collection.

import { html, render, useEffect, useState } from '/vendor/preact-htm.js';
import { api } from '/api.js';
import { ChatTab } from '/components/chat.js';
import { Settings, Setup } from '/components/setup.js';
import { SourcesPane } from '/components/sources.js';
import { FlashcardsTab, QuizTab, SummaryTab } from '/components/study.js';
import { Dialog, toast, ToastHost } from '/components/ui.js';

const TABS = [['chat', 'Chat'], ['summary', 'Summary'], ['quiz', 'Quiz'], ['flashcards', 'Flashcards']];

function readHash() {
  const match = window.location.hash.match(/^#\/c\/(\d+)(?:\/(\w+))?/);
  return match ? { id: Number(match[1]), tab: match[2] || 'chat' } : { id: null, tab: 'chat' };
}

function App() {
  const [status, setStatus] = useState(null);
  const [failed, setFailed] = useState(false);
  const [changingModel, setChangingModel] = useState(false);

  const refresh = () => api.get('/api/setup')
    .then((next) => { setStatus(next); setFailed(false); return next; })
    .catch(() => setFailed(true));
  useEffect(() => { refresh(); }, []);

  if (!status) {
    return html`<p class="boot">${failed ? 'Cannot reach customcbot. Is it still running?' : 'Starting…'}</p>`;
  }
  // Stay on the wizard after a download until the user presses Start.
  if (changingModel || !status.ready || status.pull.done) {
    const finish = async () => {
      await api.post('/api/setup/finish').catch(() => {});
      await refresh();
      setChangingModel(false);
    };
    return html`
      <${Setup} status=${status} refresh=${refresh} onDone=${finish}
        onCancel=${changingModel && !status.pull.active ? () => setChangingModel(false) : null} />
      <${ToastHost} />`;
  }
  return html`
    <${Main} status=${status} refresh=${refresh} onChangeModel=${() => setChangingModel(true)} />
    <${ToastHost} />`;
}

function Main({ status, refresh, onChangeModel }) {
  const [collections, setCollections] = useState(null);
  const [route, setRoute] = useState(readHash());
  const [creating, setCreating] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const load = () => api.get('/api/collections').then((list) => { setCollections(list); return list; }).catch((error) => toast(error.message));
  useEffect(() => {
    load();
    const onHash = () => setRoute(readHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const go = (id, tab = 'chat') => { window.location.hash = id ? `#/c/${id}/${tab}` : '#/'; };

  // Open the most recent collection when none is selected, or the selected one is gone.
  useEffect(() => {
    if (!collections) return;
    const exists = collections.some((c) => c.id === route.id);
    if (!exists && collections.length) go(collections[0].id);
    else if (!exists && route.id) go(null);
  }, [collections, route.id]);

  const current = collections && collections.find((c) => c.id === route.id);

  return html`
    <div class="shell">
      <nav class="sidebar" aria-label="Collections">
        <div class="brand"><img src="/favicon.svg" alt="" /><span>customcbot</span></div>
        <button class="btn primary" onClick=${() => setCreating(true)}>+ New collection</button>
        <div class="nav-list">
          ${(collections || []).map((collection) => html`
            <button class=${`nav-item${collection.id === route.id ? ' active' : ''}`} onClick=${() => go(collection.id)} key=${collection.id}>
              <span class="name">${collection.name}</span>
            </button>`)}
        </div>
        <button class="nav-item" onClick=${() => setShowSettings(true)}><span class="name">Settings</span></button>
      </nav>

      <div class="main">
        ${status.fake && html`<div class="banner warn" style="border-radius: 0">Demo mode: answers are placeholders, not from a real model.</div>`}
        ${current
          ? html`<${CollectionView} key=${current.id} collection=${current} tab=${route.tab} go=${go} reloadCollections=${load} />`
          : html`
            <div class="empty">
              <h2>Welcome to customcbot</h2>
              <p>A collection holds the material for one subject or project: PDFs, lecture videos, photos of your notes.
                Create one, add your material, then chat with it, summarise it, or quiz yourself.</p>
              <button class="btn primary" onClick=${() => setCreating(true)}>Create your first collection</button>
            </div>`}
      </div>

      ${creating && html`<${NameDialog} title="New collection" action="Create" onClose=${() => setCreating(false)}
        onSubmit=${async (name) => { const made = await api.post('/api/collections', { name }); await load(); go(made.id); }} />`}
      ${showSettings && html`<${Settings} status=${status} refresh=${refresh} onClose=${() => setShowSettings(false)}
        onChangeModel=${() => { setShowSettings(false); onChangeModel(); }} />`}
    </div>
  `;
}

function NameDialog({ title, action, initial = '', onSubmit, onClose }) {
  const [name, setName] = useState(initial);
  const submit = async (event) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await onSubmit(name.trim());
      onClose();
    } catch (error) {
      toast(error.message);
    }
  };
  return html`
    <${Dialog} title=${title} onClose=${onClose}>
      <form class="stack" onSubmit=${submit}>
        <label class="field">Name
          <input type="text" autofocus placeholder="For example: Biology 101" value=${name} onInput=${(e) => setName(e.target.value)}
            ref=${(element) => element && !element.dataset.focused && (element.dataset.focused = '1', element.focus())} />
        </label>
        <div class="row" style="justify-content: flex-end">
          <button type="button" class="btn" onClick=${onClose}>Cancel</button>
          <button class="btn primary" disabled=${!name.trim()}>${action}</button>
        </div>
      </form>
    <//>
  `;
}

function CollectionView({ collection, tab, go, reloadCollections }) {
  const [sources, setSources] = useState([]);
  const [excluded, setExcluded] = useState(new Set());
  const [renaming, setRenaming] = useState(false);

  const reload = () => api.get(`/api/collections/${collection.id}/sources`).then(setSources).catch(() => {});
  useEffect(() => { reload(); }, [collection.id]);

  // Refresh while anything is still being processed.
  const working = sources.some((s) => s.status === 'queued' || s.status === 'processing');
  useEffect(() => {
    if (!working) return undefined;
    const timer = setInterval(reload, 1200);
    return () => clearInterval(timer);
  }, [working, collection.id]);

  const ready = sources.filter((s) => s.status === 'ready');
  const included = ready.filter((s) => !excluded.has(s.id));
  // null means "everything"; a list narrows answers, quizzes and cards to the ticked sources.
  const sourceIds = included.length === ready.length ? null : included.map((s) => s.id);
  const readyCount = included.length;

  const remove = async () => {
    if (!window.confirm(`Delete "${collection.name}" and everything in it? This cannot be undone.`)) return;
    await api.del(`/api/collections/${collection.id}`).catch((error) => toast(error.message));
    await reloadCollections();
  };

  const props = { collectionId: collection.id, sourceIds, readyCount };
  return html`
    <div class="topbar">
      <h1 title=${collection.name}>${collection.name}</h1>
      <button class="btn ghost small" onClick=${() => setRenaming(true)}>Rename</button>
      <button class="btn ghost small danger" onClick=${remove}>Delete</button>
      <div class="tabs" role="tablist">
        <button class=${`tab only-narrow${tab === 'sources' ? ' active' : ''}`} role="tab" aria-selected=${tab === 'sources'} onClick=${() => go(collection.id, 'sources')}>Sources (${sources.length})</button>
        ${TABS.map(([id, label]) => html`
          <button class=${`tab${tab === id ? ' active' : ''}`} role="tab" aria-selected=${tab === id} onClick=${() => go(collection.id, id)}>${label}</button>`)}
      </div>
    </div>
    <div class=${`workspace tab-${tab}`}>
      <${SourcesPane} collectionId=${collection.id} sources=${sources} reload=${reload} excluded=${excluded} setExcluded=${setExcluded} />
      ${tab === 'summary' ? html`<${SummaryTab} ...${props} />`
        : tab === 'quiz' ? html`<${QuizTab} ...${props} />`
        : tab === 'flashcards' ? html`<${FlashcardsTab} ...${props} />`
        : html`<${ChatTab} ...${props} />`}
    </div>
    ${renaming && html`<${NameDialog} title="Rename collection" action="Save" initial=${collection.name} onClose=${() => setRenaming(false)}
      onSubmit=${async (name) => { await api.patch(`/api/collections/${collection.id}`, { name }); await reloadCollections(); }} />`}
  `;
}

render(html`<${App} />`, document.getElementById('app'));
