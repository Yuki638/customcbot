// The chat tab: ask questions, read streamed answers, open the cited passages.

import { html, useEffect, useRef, useState } from '/vendor/preact-htm.js';
import { api, formatTime, streamChat } from '/api.js';
import { Dialog, Markdown, toast } from '/components/ui.js';

const SUGGESTIONS = [
  'Summarise the main ideas',
  'Explain the hardest part simply',
  'What are the key terms and what do they mean?',
  'Ask me three questions to test me',
];

function citationLink(citation) {
  if (citation.kind === 'note' || citation.kind === 'insight') return null;  // shown in full right here
  if (citation.kind === 'youtube' && citation.url) {
    return { href: citation.url, text: citation.start_sec !== null ? `Watch from ${formatTime(citation.start_sec)}` : 'Open the video' };
  }
  const file = `/api/sources/${citation.source_id}/file`;
  if (citation.kind === 'pdf') return { href: `${file}#page=${citation.page || 1}`, text: `Open page ${citation.page || 1}` };
  if (citation.kind === 'media') return { href: `${file}#t=${Math.floor(citation.start_sec || 0)}`, text: `Play from ${formatTime(citation.start_sec)}` };
  if (citation.kind === 'image') return { href: file, text: 'Open the image' };
  if (citation.kind === 'docx' || citation.kind === 'pptx') return { href: file, text: 'Download the file' };
  return null;
}

export function CitationDialog({ citation, onClose }) {
  const link = citationLink(citation);
  return html`
    <${Dialog} title=${citation.label} onClose=${onClose} footer=${link && html`
      <a class="btn primary" href=${link.href} target="_blank" rel="noopener">${link.text}</a>`}>
      <p class="muted small">${citation.kind === 'note' ? 'This is the part of your note that the answer used.' : 'This is the passage from your material that the answer used.'}</p>
      <div class="passage">${citation.text}</div>
    <//>
  `;
}

export function ChatTab({ collectionId, sourceIds, readyCount }) {
  const [chats, setChats] = useState([]);
  const [chatId, setChatId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [general, setGeneral] = useState(() => localStorage.getItem('customcbot.general') === '1');
  const [opened, setOpened] = useState(null);
  const scroller = useRef(null);
  const abort = useRef(null);
  const stick = useRef(true);

  const loadMessages = async (id) => {
    setChatId(id);
    setMessages(id ? await api.get(`/api/chats/${id}/messages`).catch(() => []) : []);
    stick.current = true;
  };

  useEffect(() => {
    let cancelled = false;
    api.get(`/api/collections/${collectionId}/chats`).then((list) => {
      if (cancelled) return;
      setChats(list);
      loadMessages(list.length ? list[0].id : null);
    }).catch((error) => toast(error.message));
    return () => { cancelled = true; if (abort.current) abort.current.abort(); };
  }, [collectionId]);

  // Follow the answer as it streams, unless the user has scrolled up to read.
  useEffect(() => {
    const box = scroller.current;
    if (box && stick.current) box.scrollTop = box.scrollHeight;
  }, [messages]);

  const onScroll = () => {
    const box = scroller.current;
    stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
  };

  const updateLast = (change) => setMessages((list) => {
    if (!list.length || list[list.length - 1].role !== 'assistant') return list;
    const next = list.slice();
    next[next.length - 1] = { ...next[next.length - 1], ...change(next[next.length - 1]) };
    return next;
  });

  const send = async (text) => {
    const question = (text ?? input).trim();
    if (!question || streaming) return;
    setInput('');
    setStreaming(true);
    stick.current = true;
    let id = chatId;
    try {
      if (!id) {
        const chat = await api.post(`/api/collections/${collectionId}/chats`);
        id = chat.id;
        setChatId(id);
      }
      setMessages((list) => [...list, { role: 'user', content: question }, { role: 'assistant', content: '', citations: [], pending: true }]);
      abort.current = new AbortController();
      await streamChat(id, { content: question, source_ids: sourceIds, general }, (event, data) => {
        if (event === 'sources') updateLast(() => ({ citations: data.citations }));
        else if (event === 'token') updateLast((last) => ({ content: last.content + data.text }));
        else if (event === 'done') updateLast((last) => ({ content: data.content ?? last.content, citations: data.citations, pending: false }));
        else if (event === 'error') updateLast(() => ({ error: data.message, pending: false }));
      }, abort.current.signal);
    } catch (error) {
      toast(error.message);
      updateLast(() => ({ error: error.message }));
    }
    updateLast(() => ({ pending: false }));
    setStreaming(false);
    api.get(`/api/collections/${collectionId}/chats`).then(setChats).catch(() => {});
  };

  const newChat = () => { if (!streaming) loadMessages(null); };

  const deleteChat = async () => {
    if (!chatId || streaming || !window.confirm('Delete this conversation?')) return;
    await api.del(`/api/chats/${chatId}`).catch(() => {});
    const list = await api.get(`/api/collections/${collectionId}/chats`).catch(() => []);
    setChats(list);
    loadMessages(list.length ? list[0].id : null);
  };

  const toggleGeneral = (event) => {
    setGeneral(event.target.checked);
    localStorage.setItem('customcbot.general', event.target.checked ? '1' : '0');
  };

  // Keep an answer: it becomes a note, titled with the question that was asked.
  const saveAsNote = async (index) => {
    const answer = messages[index];
    const question = messages.slice(0, index).reverse().find((m) => m.role === 'user');
    try {
      await api.post(`/api/collections/${collectionId}/notes`, {
        title: question ? question.content.slice(0, 110) : '', content: answer.content, note_type: 'ai',
      });
      setMessages((list) => list.map((m, i) => (i === index ? { ...m, saved: true } : m)));
      toast('Saved. You will find it in the Notes tab.');
    } catch (error) {
      toast(error.message);
    }
  };

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      send();
    }
  };

  return html`
    <div class="tab-body">
      <div class="chat-bar">
        <select aria-label="Conversation" value=${chatId ? String(chatId) : ''} disabled=${streaming}
          onChange=${(e) => loadMessages(e.target.value ? Number(e.target.value) : null)}>
          <option value="">New conversation</option>
          ${chats.map((chat) => html`<option value=${String(chat.id)}>${chat.title}</option>`)}
        </select>
        <button class="btn small" onClick=${newChat} disabled=${streaming || !chatId}>New chat</button>
        ${chatId && html`<button class="btn ghost small danger" onClick=${deleteChat} disabled=${streaming}>Delete</button>`}
        <span class="grow"></span>
        <label class="check small" title="When off, answers come only from your material">
          <input type="checkbox" checked=${general} onChange=${toggleGeneral} />
          Also use general knowledge
        </label>
      </div>

      <div class="messages" ref=${scroller} onScroll=${onScroll}>
        ${messages.length === 0 && html`
          <div class="empty">
            <h2>${readyCount ? 'Ask anything about your material' : 'Add some material to get started'}</h2>
            <p>${readyCount
              ? 'Answers come from what you added, with links back to the exact page or moment.'
              : 'Add a PDF, photos of your notes or a YouTube link on the left. When it says "Ready", ask away.'}</p>
            ${readyCount > 0 && html`
              <div class="suggestions">
                ${SUGGESTIONS.map((text) => html`<button class="btn small" onClick=${() => send(text)}>${text}</button>`)}
              </div>`}
          </div>`}

        ${messages.map((message, index) => message.role === 'user'
          ? html`<div class="msg user" key=${index}><div class="bubble">${message.content}</div></div>`
          : html`
            <div class="msg assistant" key=${index}>
              <div class="bubble">
                ${message.pending && !message.content && html`<span class="thinking">Reading your material…</span>`}
                <${Markdown} text=${message.content} citations=${message.citations || []}
                  onCite=${(n) => setOpened((message.citations || []).find((c) => c.n === n) || null)} />
                ${message.error && html`<div class="banner err" style="margin-top: 8px">${message.error}</div>`}
              </div>
              ${!message.pending && (message.citations || []).length > 0 && html`
                <div class="cites">
                  <span class="muted small">${message.citations[0].uncited ? 'Passages searched:' : 'Sources:'}</span>
                  ${message.citations.map((citation) => html`
                    <button class="cite-chip" onClick=${() => setOpened(citation)} title=${citation.label}>
                      <span class="n">${citation.n}</span><span class="label">${citation.label}</span>
                    </button>`)}
                </div>`}
              ${!message.pending && !message.error && message.content && html`
                <div class="msg-actions">
                  <button class="btn ghost small" disabled=${message.saved} onClick=${() => saveAsNote(index)}>
                    ${message.saved ? 'Saved to Notes' : 'Save as note'}
                  </button>
                </div>`}
            </div>`)}
      </div>

      <div class="composer">
        <form class="inner row" onSubmit=${(e) => { e.preventDefault(); send(); }}>
          <textarea class="grow" rows="1" placeholder="Ask a question about your material…" aria-label="Your question"
            value=${input} onInput=${(e) => setInput(e.target.value)} onKeyDown=${onKeyDown}></textarea>
          ${streaming
            ? html`<button type="button" class="btn" onClick=${() => abort.current && abort.current.abort()}>Stop</button>`
            : html`<button class="btn primary" disabled=${!input.trim()}>Send</button>`}
        </form>
      </div>

      ${opened && html`<${CitationDialog} citation=${opened} onClose=${() => setOpened(null)} />`}
    </div>
  `;
}
