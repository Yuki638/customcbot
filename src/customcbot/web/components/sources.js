// The list of material in a collection, and the ways to add to it.

import { html, useEffect, useRef, useState } from '/vendor/preact-htm.js';
import { api, formatTime } from '/api.js';
import { Dialog, Progress, toast } from '/components/ui.js';
import { SourceChatDialog } from '/components/chat.js';

const KIND_LABELS = { pdf: 'PDF', image: 'Image', youtube: 'YouTube', media: 'Audio/video', docx: 'Word', pptx: 'Slides', text: 'Text' };
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.bmp,.gif,.tif,.tiff,.docx,.pptx,.txt,.md,.csv,.mp3,.wav,.m4a,.ogg,.flac,.aac,.opus,.mp4,.mkv,.webm,.mov,.avi';

export function SourcesPane({ collectionId, sources, reload, excluded, setExcluded }) {
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [links, setLinks] = useState('');
  const [rejected, setRejected] = useState([]);
  const [pasting, setPasting] = useState(false);
  const [viewing, setViewing] = useState(null);
  const [asking, setAsking] = useState(null);
  const fileInput = useRef(null);

  const finish = async (result) => {
    setRejected(result.rejected || []);
    await reload();
  };

  const addFiles = async (fileList) => {
    const files = [...fileList];
    if (!files.length) return;
    const form = new FormData();
    files.forEach((file) => form.append('files', file));
    setBusy(true);
    try {
      await finish(await api.post(`/api/collections/${collectionId}/sources/files`, form));
    } catch (error) {
      toast(error.message);
    }
    setBusy(false);
  };

  const addLinks = async (event) => {
    event.preventDefault();
    const urls = links.split(/\s+/).filter(Boolean);
    if (!urls.length) return;
    setBusy(true);
    try {
      await finish(await api.post(`/api/collections/${collectionId}/sources/links`, { urls }));
      setLinks('');
    } catch (error) {
      toast(error.message);
    }
    setBusy(false);
  };

  const remove = async (source) => {
    if (!window.confirm(`Remove "${source.title}" from this collection?`)) return;
    await api.del(`/api/sources/${source.id}`).catch((error) => toast(error.message));
    await reload();
  };

  const retry = async (source) => {
    await api.post(`/api/sources/${source.id}/retry`).catch((error) => toast(error.message));
    await reload();
  };

  const toggle = (id) => {
    const next = new Set(excluded);
    if (next.has(id)) next.delete(id); else next.add(id);
    setExcluded(next);
  };

  return html`
    <div class="sources-pane">
      <div
        class=${`drop${over ? ' over' : ''}`}
        role="button" tabindex="0"
        onClick=${() => fileInput.current.click()}
        onKeyDown=${(e) => (e.key === 'Enter' || e.key === ' ') && fileInput.current.click()}
        onDragOver=${(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave=${() => setOver(false)}
        onDrop=${(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files); }}
      >
        <strong>${busy ? 'Adding…' : 'Add files'}</strong>
        <span class="muted small">Drop them here or click to choose. PDFs, photos of notes, Word, slides, text, audio and video.</span>
        <input ref=${fileInput} type="file" multiple hidden accept=${ACCEPT} onChange=${(e) => { addFiles(e.target.files); e.target.value = ''; }} />
      </div>

      <form class="row" onSubmit=${addLinks}>
        <input type="text" class="grow" placeholder="Paste YouTube links" aria-label="YouTube links" value=${links} onInput=${(e) => setLinks(e.target.value)} />
        <button class="btn" disabled=${busy || !links.trim()}>Add</button>
      </form>
      <div><button class="btn ghost small" onClick=${() => setPasting(true)}>+ Paste text instead</button></div>

      ${rejected.length > 0 && html`
        <div class="banner warn stack" style="gap: 4px">
          ${rejected.map((item) => html`<div><strong>${item.name}</strong>: ${item.reason}</div>`)}
          <div><button class="btn small" onClick=${() => setRejected([])}>Dismiss</button></div>
        </div>`}

      ${sources.length === 0 && html`<p class="muted small center">Nothing here yet. Add your first file or link above.</p>`}

      ${sources.map((source) => html`
        <div class="source stack" style="gap: 4px" key=${source.id}>
          <div class="row">
            ${source.status === 'ready' && html`
              <input type="checkbox" checked=${!excluded.has(source.id)} onChange=${() => toggle(source.id)}
                title="Use this source for answers, quizzes and cards" aria-label=${`Use ${source.title}`} />`}
            <button class="title grow" onClick=${() => source.status === 'ready' && setViewing(source)} title=${source.title}>${source.title}</button>
            ${source.status === 'ready' && html`
              <button class="btn ghost small" onClick=${() => setAsking(source)} title="Ask questions about this source only"
                aria-label=${`Ask about ${source.title}`}>Ask</button>`}
            <button class="btn ghost icon small" onClick=${() => remove(source)} aria-label=${`Remove ${source.title}`}>✕</button>
          </div>
          <div class="row meta">
            <span class="kind">${KIND_LABELS[source.kind] || source.kind}</span>
            ${source.status === 'ready' && html`<span class="badge ok">Ready</span>`}
            ${source.status === 'queued' && html`<span>Waiting…</span>`}
            ${source.status === 'processing' && html`<span class="grow">${source.stage || 'Working…'}</span>`}
            ${source.status === 'error' && html`<span class="badge err">Problem</span>`}
          </div>
          ${source.status === 'processing' && html`<${Progress} value=${source.progress} />`}
          ${source.status === 'queued' && html`<${Progress} busy />`}
          ${source.status === 'error' && html`
            <div class="banner err">${source.error}</div>
            <div><button class="btn small" onClick=${() => retry(source)}>Try again</button></div>`}
          ${source.status === 'ready' && source.note && html`
            <button class="btn ghost small" style="justify-content: flex-start; color: var(--warn)" onClick=${() => setViewing(source)}>
              Check what was read
            </button>`}
        </div>
      `)}

      ${pasting && html`<${PasteDialog} collectionId=${collectionId} onClose=${() => setPasting(false)} onAdded=${reload} />`}
      ${viewing && html`<${SourceViewer} sourceId=${viewing.id} onClose=${() => setViewing(null)} />`}
      ${asking && html`<${SourceChatDialog} source=${asking} onClose=${() => setAsking(null)} />`}
    </div>
  `;
}

function PasteDialog({ collectionId, onClose, onAdded }) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const add = async () => {
    try {
      await api.post(`/api/collections/${collectionId}/sources/text`, { title, text });
      await onAdded();
      onClose();
    } catch (error) {
      toast(error.message);
    }
  };
  return html`
    <${Dialog} title="Paste text" onClose=${onClose} footer=${html`
      <button class="btn" onClick=${onClose}>Cancel</button>
      <button class="btn primary" disabled=${!text.trim()} onClick=${add}>Add</button>`}>
      <label class="field">Title (optional)
        <input type="text" value=${title} onInput=${(e) => setTitle(e.target.value)} />
      </label>
      <label class="field">Text
        <textarea rows="12" value=${text} onInput=${(e) => setText(e.target.value)}></textarea>
      </label>
    <//>
  `;
}

const METHOD_LABELS = { vision: 'read by the AI model', ocr: 'basic text recognition', whisper: 'speech-to-text', captions: 'captions' };

// Shows what was extracted from a source and lets the user correct it.
function SourceViewer({ sourceId, onClose }) {
  const [data, setData] = useState(null);
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => api.get(`/api/sources/${sourceId}/units`).then(setData).catch((error) => toast(error.message));
  useEffect(() => { load(); }, [sourceId]);

  const save = async (unit) => {
    setSaving(true);
    try {
      await api.put(`/api/units/${unit.id}`, { text: draft });
      await load();
      setEditing(null);
      toast('Saved. Answers will use the corrected text.');
    } catch (error) {
      toast(error.message);
    }
    setSaving(false);
  };

  if (!data) return html`<${Dialog} title="Loading…" onClose=${onClose} wide><p class="muted">Loading…</p><//>`;
  const { source, units } = data;
  const original = source.kind === 'youtube' ? source.origin : source.kind === 'text' ? null : `/api/sources/${source.id}/file`;
  const timed = units.some((unit) => unit.start_sec !== null);
  // Hundreds of caption lines are not useful to edit one by one; show long transcripts read-only.
  const transcript = timed && units.length > 60;

  return html`
    <${Dialog} title=${source.title} onClose=${onClose} wide>
      ${source.note && html`<div class="banner warn">${source.note}</div>`}
      <div class="row muted small">
        <span class="grow">This is the text customcbot read from your source. Answers are based on it.</span>
        ${original && html`<a href=${original} target="_blank" rel="noopener">Open original</a>`}
      </div>
      ${transcript
        ? html`<div class="passage">${units.map((unit) => `[${formatTime(unit.start_sec)}] ${unit.text}`).join('\n')}</div>`
        : units.map((unit) => html`
          <div class="unit stack" style="gap: 6px" key=${unit.id}>
            <div class="row small muted">
              <strong class="grow">
                ${unit.start_sec !== null ? formatTime(unit.start_sec) : unit.page !== null ? `${source.kind === 'pptx' ? 'Slide' : 'Page'} ${unit.page}` : `Part ${unit.ord + 1}`}
                ${METHOD_LABELS[unit.method] ? ` · ${METHOD_LABELS[unit.method]}` : ''}
              </strong>
              ${editing !== unit.id && html`<button class="btn small" onClick=${() => { setEditing(unit.id); setDraft(unit.text); }}>Edit</button>`}
            </div>
            ${editing === unit.id
              ? html`
                <textarea value=${draft} onInput=${(e) => setDraft(e.target.value)}></textarea>
                <div class="row">
                  <button class="btn primary small" disabled=${saving || !draft.trim()} onClick=${() => save(unit)}>${saving ? 'Saving…' : 'Save'}</button>
                  <button class="btn small" onClick=${() => setEditing(null)}>Cancel</button>
                </div>`
              : html`<div class="text">${unit.text}</div>`}
          </div>`)}
    <//>
  `;
}
