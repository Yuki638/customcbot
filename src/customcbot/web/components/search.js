// The Search tab: find passages, or get a thorough answer built from several searches.

import { html, useEffect, useRef, useState } from '/i18n.js';
import { api, streamEvents } from '/api.js';
import { CitationDialog } from '/components/chat.js';
import { Markdown, toast } from '/components/ui.js';

const KINDS = [['source', 'Sources'], ['note', 'Notes'], ['insight', 'Summaries and task results']];
const HOW = [['both', 'Words and meaning'], ['words', 'Exact words only'], ['meaning', 'Similar meaning only']];

function Find({ collectionId }) {
  const [query, setQuery] = useState('');
  const [how, setHow] = useState('both');
  const [kinds, setKinds] = useState(['source', 'note', 'insight']);
  const [results, setResults] = useState(null);
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState(null);

  useEffect(() => { setResults(null); }, [collectionId]);
  const run = async (event) => {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    try {
      const found = await api.post(`/api/collections/${collectionId}/search`, { query, mode: how, kinds });
      setResults(found.results);
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  };
  const toggle = (kind) => setKinds(kinds.includes(kind) ? kinds.filter((k) => k !== kind) : [...kinds, kind]);

  return html`
    <form class="stack" onSubmit=${run}>
      <div class="row">
        <input type="text" class="grow" placeholder="A word, a name or a phrase" aria-label="What to look for"
          value=${query} onInput=${(e) => setQuery(e.target.value)} />
        <button class="btn primary" disabled=${busy || !query.trim() || !kinds.length}>${busy ? 'Looking…' : 'Find'}</button>
      </div>
      <div class="row wrap small">
        <select class="inline" aria-label="How to search" value=${how} onChange=${(e) => setHow(e.target.value)}>
          ${HOW.map(([id, label]) => html`<option value=${id} key=${id}>${label}</option>`)}
        </select>
        ${KINDS.map(([id, label]) => html`
          <label class="row" key=${id}>
            <input type="checkbox" checked=${kinds.includes(id)} onChange=${() => toggle(id)} /> ${label}
          </label>`)}
      </div>
    </form>
    ${results && results.length === 0 && html`<p class="muted">Nothing found. Try other words, or "Similar meaning only".</p>`}
    ${results && results.map((result) => html`
      <button class="list-row result-row" key=${result.chunk_id} onClick=${() => setOpened(result)}>
        <span class="grow">
          <strong>${result.label}</strong>
          <span class="muted small snippet">${result.text.slice(0, 260)}${result.text.length > 260 ? '…' : ''}</span>
        </span>
      </button>`)}
    ${opened && html`<${CitationDialog} citation=${opened} onClose=${() => setOpened(null)} />`}
  `;
}

function Ask({ collectionId, sourceIds }) {
  const [question, setQuestion] = useState('');
  const [run, setRun] = useState(null);  // { question, searches, notes, answer, citations, error, done, saved }
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState(null);
  const abort = useRef(null);

  useEffect(() => { setRun(null); return () => abort.current && abort.current.abort(); }, [collectionId]);

  const start = async (event) => {
    event.preventDefault();
    const asked = question.trim();
    if (!asked || busy) return;
    setBusy(true);
    setRun({ question: asked, searches: null, notes: [], answer: '', citations: [], pool: [] });
    const change = (update) => setRun((current) => ({ ...current, ...update(current) }));
    abort.current = new AbortController();
    try {
      await streamEvents(`/api/collections/${collectionId}/ask`, { question: asked, source_ids: sourceIds }, (name, data) => {
        if (name === 'strategy') change(() => ({ searches: data.searches }));
        else if (name === 'answer') change((current) => ({ notes: [...current.notes, data] }));
        else if (name === 'sources') change(() => ({ pool: data.citations }));
        else if (name === 'token') change((current) => ({ answer: current.answer + data.text }));
        else if (name === 'done') change(() => ({ answer: data.content, citations: data.citations, done: true }));
        else if (name === 'error') change(() => ({ error: data.message }));
      }, abort.current.signal);
    } catch (error) {
      change(() => ({ error: error.message }));
    }
    setBusy(false);
  };

  const keep = async () => {
    try {
      await api.post(`/api/collections/${collectionId}/notes`, { title: run.question.slice(0, 110), content: run.answer, note_type: 'ai' });
      setRun({ ...run, saved: true });
      toast('Saved. You will find it in the Notes tab.');
    } catch (error) {
      toast(error.message);
    }
  };

  const shown = run ? (run.done ? run.citations : run.pool) : [];
  return html`
    <form class="stack" onSubmit=${start}>
      <textarea rows="2" placeholder="A question that needs more than one passage, for example: How do the two kinds of fermentation differ?"
        aria-label="Your question" value=${question} onInput=${(e) => setQuestion(e.target.value)}></textarea>
      <div class="row">
        <span class="grow muted small">The AI plans a few searches, takes notes from each, then writes one answer. Slower than Chat, but it covers more of your material.</span>
        ${busy
          ? html`<button type="button" class="btn" onClick=${() => abort.current && abort.current.abort()}>Stop</button>`
          : html`<button class="btn primary" disabled=${!question.trim()}>Ask</button>`}
      </div>
    </form>
    ${run && html`
      <div class="card stack">
        <strong>${run.question}</strong>
        <div class="steps stack">
          ${!run.searches && !run.error && html`<span class="muted small">Planning what to look up…</span>`}
          ${run.searches && run.searches.map((search, index) => {
            const note = run.notes.find((n) => n.index === index);
            return html`
              <details key=${index}>
                <summary>${note ? (note.text ? 'Read' : 'Nothing found for') : (index === run.notes.length ? 'Reading about' : 'Next:')} "${search.term}"</summary>
                ${note && note.text && html`<div class="small" style="margin-top: 6px"><${Markdown} text=${note.text} citations=${note.citations}
                  onCite=${(n) => setOpened(note.citations.find((c) => c.n === n) || null)} /></div>`}
              </details>`;
          })}
          ${run.searches && run.notes.length === run.searches.length && !run.done && !run.error && !run.answer && html`
            <span class="muted small">Writing the answer…</span>`}
        </div>
        ${run.answer && html`<${Markdown} text=${run.answer} citations=${shown}
          onCite=${(n) => setOpened(shown.find((c) => c.n === n) || null)} />`}
        ${run.error && html`<div class="banner err">${run.error}</div>`}
        ${run.done && run.citations.length > 0 && html`
          <div class="cites">
            <span class="muted small">Sources:</span>
            ${run.citations.map((citation) => html`
              <button class="cite-chip" onClick=${() => setOpened(citation)} title=${citation.label}>
                <span class="n">${citation.n}</span><span class="label">${citation.label}</span>
              </button>`)}
          </div>`}
        ${run.done && html`
          <div><button class="btn small" disabled=${run.saved} onClick=${keep}>${run.saved ? 'Saved to Notes' : 'Save as note'}</button></div>`}
      </div>`}
    ${opened && html`<${CitationDialog} citation=${opened} onClose=${() => setOpened(null)} />`}
  `;
}

export function SearchTab({ collectionId, sourceIds, readyCount }) {
  const [mode, setMode] = useState('find');
  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <div class="row">
        <h2 class="grow">Search</h2>
        <div class="segmented" role="tablist">
          <button class=${mode === 'find' ? 'on' : ''} role="tab" aria-selected=${mode === 'find'} onClick=${() => setMode('find')}>Find passages</button>
          <button class=${mode === 'ask' ? 'on' : ''} role="tab" aria-selected=${mode === 'ask'} onClick=${() => setMode('ask')}>Ask in depth</button>
        </div>
      </div>
      ${!readyCount && html`<p class="muted">Add some material first. Once a source says "Ready", you can search it.</p>`}
      ${mode === 'find'
        ? html`<${Find} collectionId=${collectionId} />`
        : html`<${Ask} collectionId=${collectionId} sourceIds=${sourceIds} />`}
    </div></div></div>
  `;
}
