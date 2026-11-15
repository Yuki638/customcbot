// The Notes tab: your own notes, and answers or results you chose to keep.

import { html, useEffect, useState } from '/vendor/preact-htm.js';
import { api } from '/api.js';
import { Dialog, Markdown, toast } from '/components/ui.js';

function NoteDialog({ collectionId, note, onClose, onSaved }) {
  const [title, setTitle] = useState(note ? note.title : '');
  const [content, setContent] = useState(note ? note.content : '');
  const [preview, setPreview] = useState(false);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const body = { title, content };
      if (note) await api.put(`/api/notes/${note.id}`, body);
      else await api.post(`/api/collections/${collectionId}/notes`, body);
      await onSaved();
      onClose();
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  };

  return html`
    <${Dialog} title=${note ? 'Edit note' : 'New note'} wide onClose=${onClose} footer=${html`
      <button class="btn" onClick=${() => setPreview(!preview)}>${preview ? 'Keep writing' : 'Preview'}</button>
      <button class="btn" onClick=${onClose}>Cancel</button>
      <button class="btn primary" disabled=${busy || !(title.trim() || content.trim())} onClick=${save}>Save</button>`}>
      <label class="field">Title
        <input type="text" placeholder="Leave empty to use the first line" value=${title} onInput=${(e) => setTitle(e.target.value)} />
      </label>
      ${preview
        ? html`<div class="card"><${Markdown} text=${content || '*Nothing written yet.*'} /></div>`
        : html`<label class="field">Note
            <textarea rows="14" placeholder="Write here. Markdown works: # heading, - list, **bold**." value=${content}
              onInput=${(e) => setContent(e.target.value)}></textarea>
          </label>`}
      <p class="muted small">Notes are searched together with your sources, so answers in Chat can use and cite them.</p>
    <//>
  `;
}

export function NotesTab({ collectionId }) {
  const [notes, setNotes] = useState(null);
  const [editing, setEditing] = useState(null);  // null: closed, {}: new, {id…}: existing
  const [open, setOpen] = useState(null);

  const load = () => api.get(`/api/collections/${collectionId}/notes`).then(setNotes).catch((error) => toast(error.message));
  useEffect(() => { setNotes(null); setOpen(null); load(); }, [collectionId]);

  const show = (id) => api.get(`/api/notes/${id}`).then(setOpen).catch((error) => toast(error.message));
  const remove = async (note) => {
    if (!window.confirm(`Delete the note "${note.title}"?`)) return;
    await api.del(`/api/notes/${note.id}`).catch((error) => toast(error.message));
    setOpen(null);
    load();
  };

  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <div class="row">
        <h2 class="grow">Notes</h2>
        <button class="btn primary" onClick=${() => setEditing({})}>New note</button>
      </div>
      ${notes && notes.length === 0 && html`
        <div class="empty">
          <h2>No notes yet</h2>
          <p>Write your own notes here, or press "Save as note" under an answer in Chat or a result in Summary to keep it.</p>
        </div>`}
      ${open && html`
        <div class="card stack">
          <div class="row wrap">
            <h3 class="grow">${open.title}</h3>
            <button class="btn small" onClick=${() => setEditing(open)}>Edit</button>
            <button class="btn small danger" onClick=${() => remove(open)}>Delete</button>
            <button class="btn small" onClick=${() => setOpen(null)}>Close</button>
          </div>
          <${Markdown} text=${open.content} />
        </div>`}
      ${notes && notes.filter((n) => !open || n.id !== open.id).map((note) => html`
        <button class="list-row note-row" key=${note.id} onClick=${() => show(note.id)}>
          <span class="grow">
            <strong>${note.title}</strong>
            ${note.note_type === 'ai' && html`${' '}<span class="badge">saved answer</span>`}
            <span class="muted small preview">${note.preview.replace(/^[#*\-\s]+/, '')}</span>
          </span>
        </button>`)}
    </div></div></div>
    ${editing && html`<${NoteDialog} collectionId=${collectionId} note=${editing.id ? editing : null}
      onClose=${() => setEditing(null)} onSaved=${async () => { await load(); if (editing.id) await show(editing.id); }} />`}
  `;
}
