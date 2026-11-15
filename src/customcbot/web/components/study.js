// Summary, quiz and flashcard tabs.

import { html, useEffect, useState } from '/vendor/preact-htm.js';
import { api } from '/api.js';
import { Dialog, JobProgress, Markdown, toast, useJob } from '/components/ui.js';

function NeedsMaterial() {
  return html`
    <div class="empty">
      <h2>Add some material first</h2>
      <p>Once a source says "Ready", you can make summaries, quizzes and flashcards from it.</p>
    </div>`;
}

// ---- summary -----------------------------------------------------------

function TasksDialog({ tasks, onClose, onChanged }) {
  const blank = { title: '', prompt: '', apply_default: false };
  const [editing, setEditing] = useState(null);  // a task being edited, or `blank` for a new one
  const [busy, setBusy] = useState(false);

  const run = async (work) => {
    setBusy(true);
    try {
      await work();
      await onChanged();
      setEditing(null);
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => {
    const body = { title: editing.title, description: editing.description || '', prompt: editing.prompt, apply_default: editing.apply_default };
    return editing.id ? api.put(`/api/transformations/${editing.id}`, body) : api.post('/api/transformations', body);
  });

  if (editing) {
    return html`
      <${Dialog} title=${editing.id ? `Edit "${editing.title}"` : 'New task'} wide onClose=${() => setEditing(null)} footer=${html`
        ${editing.id && editing.builtin && editing.changed && html`
          <button class="btn" disabled=${busy} onClick=${() => run(() => api.post(`/api/transformations/${editing.id}/reset`))}>Put back the original wording</button>`}
        ${editing.id && !editing.builtin && html`
          <button class="btn danger" disabled=${busy} onClick=${() => window.confirm(`Delete the task "${editing.title}"?`) && run(() => api.del(`/api/transformations/${editing.id}`))}>Delete</button>`}
        <button class="btn" onClick=${() => setEditing(null)}>Cancel</button>
        <button class="btn primary" disabled=${busy || !editing.title.trim() || !editing.prompt.trim()} onClick=${save}>Save</button>`}>
        <label class="field">Name
          <input type="text" placeholder="For example: Timeline" value=${editing.title} onInput=${(e) => setEditing({ ...editing, title: e.target.value })} />
        </label>
        <label class="field">What the AI should do with a source
          <textarea rows="6" placeholder="For example: List every date in order, with what happened on it."
            value=${editing.prompt} onInput=${(e) => setEditing({ ...editing, prompt: e.target.value })}></textarea>
        </label>
        <label class="row small">
          <input type="checkbox" checked=${editing.apply_default} onChange=${(e) => setEditing({ ...editing, apply_default: e.target.checked })} />
          <span>Do this by itself for every new source (it takes time for each one)</span>
        </label>
      <//>`;
  }
  return html`
    <${Dialog} title="Tasks" onClose=${onClose} footer=${html`
      <button class="btn" onClick=${() => setEditing(blank)}>New task</button>
      <button class="btn primary" onClick=${onClose}>Done</button>`}>
      <p class="muted small">A task is something the AI does with one source, such as listing its key points. Change the wording, or add your own.</p>
      ${tasks.map((item) => html`
        <div class="list-row" key=${item.id}>
          <span class="grow">
            <strong>${item.title}</strong>
            ${item.apply_default && html`${' '}<span class="badge">every new source</span>`}
            ${item.changed && html`${' '}<span class="badge">reworded</span>`}
            <span class="muted small" style="display: block">${item.description || item.prompt.slice(0, 90)}</span>
          </span>
          <button class="btn small" onClick=${() => setEditing(item)}>Edit</button>
        </div>`)}
    <//>`;
}

export function SummaryTab({ collectionId, readyCount }) {
  const [data, setData] = useState(null);
  const [insights, setInsights] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [chosen, setChosen] = useState({});  // source id -> task id picked in its menu
  const [managing, setManaging] = useState(false);

  const loadTasks = () => api.get('/api/transformations').then(setTasks).catch((error) => toast(error.message));
  const load = () => Promise.all([
    api.get(`/api/collections/${collectionId}/summary`).then(setData),
    api.get(`/api/collections/${collectionId}/insights`).then(setInsights),
  ]).catch((error) => toast(error.message));
  useEffect(() => { setData(null); load(); }, [collectionId, readyCount]);
  useEffect(() => { loadTasks(); }, []);
  const task = useJob(collectionId, ['summary_source', 'summary_collection', 'run_transformation'], load);
  const path = `/api/collections/${collectionId}/summary`;

  const keep = async (insight) => {
    try {
      await api.post(`/api/insights/${insight.id}/save-as-note`);
      toast('Saved. You will find it in the Notes tab.');
    } catch (error) {
      toast(error.message);
    }
  };
  const remove = async (insight) => {
    if (!window.confirm(`Delete this ${insight.insight_type.toLowerCase()}?`)) return;
    await api.del(`/api/insights/${insight.id}`).catch((error) => toast(error.message));
    load();
  };

  if (!readyCount) return html`<div class="tab-body"><div class="scroll"><${NeedsMaterial} /></div></div>`;
  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <${JobProgress} task=${task} label="Working" />
      <div class="card stack">
        <div class="row">
          <h2 class="grow">Overview of everything</h2>
          <button class="btn ${data && data.summary ? '' : 'primary'}" disabled=${task.active} onClick=${() => task.start(path, {})}>
            ${data && data.summary ? 'Write again' : 'Write overview'}
          </button>
        </div>
        ${data && data.summary
          ? html`<${Markdown} text=${data.summary} />`
          : html`<p class="muted">A study guide covering all your sources: the key ideas, important terms and questions to test yourself.</p>`}
      </div>
      <div class="row">
        <h3 class="grow">By source</h3>
        <button class="btn small" onClick=${() => setManaging(true)}>Edit tasks</button>
      </div>
      <p class="muted small">Pick what you want for a source and press Make. Results stay here; "Save as note" copies one into your notes.</p>
      ${data && data.sources.map((source) => {
        const made = insights.filter((i) => i.source_id === source.id);
        const picked = chosen[source.id] || (tasks[0] && tasks[0].id);
        return html`
          <div class="card stack" key=${source.id}>
            <div class="row wrap">
              <strong class="grow">${source.title}</strong>
              <select class="inline" aria-label=${`What to make from ${source.title}`} value=${String(picked || '')}
                onChange=${(e) => setChosen({ ...chosen, [source.id]: Number(e.target.value) })}>
                ${tasks.map((item) => html`<option value=${String(item.id)} key=${item.id}>${item.title}</option>`)}
              </select>
              <button class="btn small ${made.length ? '' : 'primary'}" disabled=${task.active || !picked}
                onClick=${() => task.start(`/api/sources/${source.id}/insights`, { transformation_id: picked })}>Make</button>
            </div>
            ${made.map((insight) => html`
              <details key=${insight.id}>
                <summary>${insight.insight_type}</summary>
                <div style="margin-top: 10px"><${Markdown} text=${insight.content} /></div>
                <div class="row" style="margin-top: 8px">
                  <button class="btn small" onClick=${() => keep(insight)}>Save as note</button>
                  <button class="btn small ghost danger" onClick=${() => remove(insight)}>Delete</button>
                </div>
              </details>`)}
          </div>`;
      })}
    </div></div></div>
    ${managing && html`<${TasksDialog} tasks=${tasks} onClose=${() => setManaging(false)} onChanged=${loadTasks} />`}
  `;
}

// ---- quiz --------------------------------------------------------------

export function QuizTab({ collectionId, sourceIds, readyCount }) {
  const [quizzes, setQuizzes] = useState([]);
  const [taking, setTaking] = useState(null);
  const [count, setCount] = useState('5');
  const [style, setStyle] = useState('mcq');
  const load = () => api.get(`/api/collections/${collectionId}/quizzes`).then(setQuizzes).catch((error) => toast(error.message));
  useEffect(() => { setTaking(null); load(); }, [collectionId]);

  const open = (id) => api.get(`/api/quizzes/${id}`).then(setTaking).catch((error) => toast(error.message));
  const task = useJob(collectionId, ['quiz'], (job) => { load(); if (job.result) open(job.result.quiz_id); });

  const remove = async (quiz) => {
    if (!window.confirm('Delete this quiz?')) return;
    await api.del(`/api/quizzes/${quiz.id}`).catch(() => {});
    load();
  };

  if (taking) {
    return html`<div class="tab-body"><div class="scroll"><div class="narrow">
      <${QuizRunner} quiz=${taking} onExit=${() => { setTaking(null); load(); }} />
    </div></div></div>`;
  }
  if (!readyCount) return html`<div class="tab-body"><div class="scroll"><${NeedsMaterial} /></div></div>`;
  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <${JobProgress} task=${task} label="Writing questions" />
      <div class="card stack">
        <h2>New quiz</h2>
        <div class="row wrap">
          <label class="field">Questions
            <select value=${count} onChange=${(e) => setCount(e.target.value)}>
              <option value="5">5</option><option value="10">10</option><option value="15">15</option>
            </select>
          </label>
          <label class="field grow">Type
            <select value=${style} onChange=${(e) => setStyle(e.target.value)}>
              <option value="mcq">Multiple choice</option>
              <option value="short">Written answers (checked by the AI)</option>
              <option value="mixed">A mix of both</option>
            </select>
          </label>
        </div>
        <div><button class="btn primary" disabled=${task.active}
          onClick=${() => task.start(`/api/collections/${collectionId}/quizzes`, { count: Number(count), style, source_ids: sourceIds })}>
          Make quiz</button></div>
        <p class="muted small">Questions are drawn from across the sources ticked on the left.</p>
      </div>
      ${quizzes.length > 0 && html`<h3>Your quizzes</h3>`}
      ${quizzes.map((quiz) => html`
        <div class="list-row" key=${quiz.id}>
          <div class="grow">
            <strong>${quiz.title}</strong>
            <div class="muted small">${quiz.best_score !== null ? `Best score ${Math.round(quiz.best_score * 100)}%` : 'Not taken yet'}</div>
          </div>
          <button class="btn small primary" onClick=${() => open(quiz.id)}>${quiz.best_score !== null ? 'Retake' : 'Start'}</button>
          <button class="btn ghost small danger" onClick=${() => remove(quiz)}>Delete</button>
        </div>`)}
    </div></div></div>
  `;
}

function QuizRunner({ quiz, onExit }) {
  const [index, setIndex] = useState(0);
  const [results, setResults] = useState({});  // question id -> { correct, picked?, feedback? }
  const [draft, setDraft] = useState('');
  const [grading, setGrading] = useState(false);
  const total = quiz.questions.length;
  const finished = index >= total;

  useEffect(() => {
    if (!finished) return;
    const right = Object.values(results).filter((r) => r.correct).length;
    api.post(`/api/quizzes/${quiz.id}/score`, { score: right / total }).catch(() => {});
  }, [finished]);

  if (finished) {
    const right = Object.values(results).filter((r) => r.correct).length;
    const missed = quiz.questions.filter((q) => !results[q.id].correct);
    return html`
      <div class="card stack center">
        <h2>You got ${right} of ${total}</h2>
        <p class="muted">${right === total ? 'Perfect score.' : missed.length <= total / 2 ? 'Good work. Review the ones you missed below.' : 'Worth another look at the material, then try again.'}</p>
        <div class="row" style="justify-content: center">
          <button class="btn primary" onClick=${() => { setResults({}); setIndex(0); }}>Try again</button>
          <button class="btn" onClick=${onExit}>Back to quizzes</button>
        </div>
      </div>
      ${missed.length > 0 && html`
        <div class="stack" style="margin-top: 14px">
          <h3>To review</h3>
          ${missed.map((q) => html`
            <div class="card stack" style="gap: 6px">
              <strong>${q.question}</strong>
              <div>Answer: ${q.type === 'mcq' ? q.options[q.answer_index] : q.answer}</div>
              ${q.explanation && html`<div class="muted small">${q.explanation}</div>`}
              <div class="muted small">From ${q.where}</div>
            </div>`)}
        </div>`}
    `;
  }

  const question = quiz.questions[index];
  const result = results[question.id];
  const record = (value) => setResults((all) => ({ ...all, [question.id]: value }));

  const check = async () => {
    setGrading(true);
    try {
      const graded = await api.post(`/api/quizzes/${quiz.id}/grade`, { question_id: question.id, answer: draft });
      record({ correct: graded.correct, feedback: graded.feedback });
    } catch (error) {
      toast(error.message);
    }
    setGrading(false);
  };

  const next = () => { setDraft(''); setIndex(index + 1); };

  return html`
    <div class="stack">
      <div class="row">
        <span class="muted grow">Question ${index + 1} of ${total}</span>
        <button class="btn ghost small" onClick=${onExit}>Leave quiz</button>
      </div>
      <div class="card stack">
        <h2>${question.question}</h2>
        ${question.type === 'mcq'
          ? question.options.map((option, i) => {
            let state = '';
            if (result) state = i === question.answer_index ? ' right' : i === result.picked ? ' wrong' : '';
            return html`
              <button class=${`option${state}`} disabled=${!!result} onClick=${() => record({ correct: i === question.answer_index, picked: i })}>
                <span class="letter">${'ABCDEF'[i]}</span><span>${option}</span>
              </button>`;
          })
          : html`
            <textarea rows="3" placeholder="Type your answer" aria-label="Your answer" disabled=${!!result} value=${draft} onInput=${(e) => setDraft(e.target.value)}></textarea>
            ${!result && html`<div class="row">
              <button class="btn primary" disabled=${!draft.trim() || grading} onClick=${check}>${grading ? 'Checking…' : 'Check answer'}</button>
              <button class="btn ghost" disabled=${grading} onClick=${() => record({ correct: false, feedback: 'Skipped.' })}>I don't know</button>
            </div>`}`}
        ${result && html`
          <div class=${`banner ${result.correct ? 'ok' : 'err'}`}>
            <strong>${result.correct ? 'Correct.' : 'Not quite.'}</strong>
            ${' '}${question.type === 'mcq' ? question.explanation : result.feedback}
            ${question.type === 'short' && html`<div style="margin-top: 4px">Reference answer: ${question.answer}</div>`}
          </div>
          <div class="row">
            <span class="muted small grow">From ${question.where}</span>
            <button class="btn primary" onClick=${next}>${index + 1 === total ? 'See results' : 'Next question'}</button>
          </div>`}
      </div>
    </div>
  `;
}

// ---- flashcards --------------------------------------------------------

export function FlashcardsTab({ collectionId, sourceIds, readyCount }) {
  const [cards, setCards] = useState([]);
  const [queue, setQueue] = useState([]);
  const [revealed, setRevealed] = useState(false);
  const [view, setView] = useState('review');
  const [count, setCount] = useState('10');
  const [editing, setEditing] = useState(null);

  const load = async () => {
    try {
      const [all, due] = await Promise.all([
        api.get(`/api/collections/${collectionId}/flashcards`),
        api.get(`/api/collections/${collectionId}/flashcards?due=true`),
      ]);
      setCards(all);
      setQueue(due);
      setRevealed(false);
    } catch (error) {
      toast(error.message);
    }
  };
  useEffect(() => { load(); }, [collectionId]);
  const task = useJob(collectionId, ['flashcards'], load);

  const answer = async (known) => {
    const [card, ...rest] = queue;
    await api.post(`/api/flashcards/${card.id}/review`, { known }).catch((error) => toast(error.message));
    // A missed card comes round again at the end of this session.
    setQueue(known ? rest : [...rest, card]);
    setRevealed(false);
    api.get(`/api/collections/${collectionId}/flashcards`).then(setCards).catch(() => {});
  };

  useEffect(() => {
    const onKey = (event) => {
      if (view !== 'review' || !queue.length || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)) return;
      if (event.key === ' ') { event.preventDefault(); setRevealed(true); }
      else if (revealed && event.key === '1') answer(false);
      else if (revealed && event.key === '2') answer(true);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  const saveEdit = async () => {
    try {
      await api.put(`/api/flashcards/${editing.id}`, { front: editing.front, back: editing.back });
      setEditing(null);
      load();
    } catch (error) {
      toast(error.message);
    }
  };

  const remove = async (card) => {
    await api.del(`/api/flashcards/${card.id}`).catch(() => {});
    load();
  };

  if (!readyCount && !cards.length) return html`<div class="tab-body"><div class="scroll"><${NeedsMaterial} /></div></div>`;
  const current = queue[0];
  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <${JobProgress} task=${task} label="Writing cards" />
      <div class="row wrap">
        <button class=${`tab${view === 'review' ? ' active' : ''}`} onClick=${() => setView('review')}>Review (${queue.length} due)</button>
        <button class=${`tab${view === 'all' ? ' active' : ''}`} onClick=${() => setView('all')}>All cards (${cards.length})</button>
        <span class="grow"></span>
        <select style="width: auto" aria-label="How many cards to make" value=${count} onChange=${(e) => setCount(e.target.value)}>
          <option value="10">10 cards</option><option value="20">20 cards</option><option value="30">30 cards</option>
        </select>
        <button class="btn primary" disabled=${task.active || !readyCount}
          onClick=${() => task.start(`/api/collections/${collectionId}/flashcards`, { count: Number(count), source_ids: sourceIds })}>
          Make cards</button>
      </div>

      ${view === 'review' && (current
        ? html`
          <div class="card flash" role="button" tabindex="0" onClick=${() => setRevealed(true)}
            onKeyDown=${(e) => e.key === 'Enter' && setRevealed(true)}>
            <span class="side">Question</span>
            <div>${current.front}</div>
            ${revealed
              ? html`<div class="answer"><span class="side">Answer</span><div>${current.back}</div></div>`
              : html`<span class="muted small">Click or press Space to show the answer</span>`}
          </div>
          ${revealed && html`
            <div class="row" style="justify-content: center">
              <button class="btn" onClick=${() => answer(false)}>Didn't know (1)</button>
              <button class="btn primary" onClick=${() => answer(true)}>Knew it (2)</button>
            </div>`}
          <p class="muted small center">Cards you know come back after longer and longer gaps. Cards you miss come back sooner.</p>`
        : html`
          <div class="empty">
            <h2>${cards.length ? 'All done for now' : 'No flashcards yet'}</h2>
            <p>${cards.length
              ? 'Nothing is due. Come back tomorrow, or make more cards.'
              : 'Press "Make cards" and customcbot will write flashcards from the sources ticked on the left.'}</p>
          </div>`)}

      ${view === 'all' && cards.map((card) => html`
        <div class="card stack" style="gap: 6px" key=${card.id}>
          ${editing && editing.id === card.id
            ? html`
              <label class="field">Front<textarea rows="2" value=${editing.front} onInput=${(e) => setEditing({ ...editing, front: e.target.value })}></textarea></label>
              <label class="field">Back<textarea rows="3" value=${editing.back} onInput=${(e) => setEditing({ ...editing, back: e.target.value })}></textarea></label>
              <div class="row">
                <button class="btn primary small" onClick=${saveEdit}>Save</button>
                <button class="btn small" onClick=${() => setEditing(null)}>Cancel</button>
              </div>`
            : html`
              <div class="row">
                <strong class="grow">${card.front}</strong>
                <span class="badge" title="Higher levels are shown less often">Level ${card.box}</span>
              </div>
              <div>${card.back}</div>
              <div class="row">
                <button class="btn small" onClick=${() => setEditing({ id: card.id, front: card.front, back: card.back })}>Edit</button>
                <button class="btn ghost small danger" onClick=${() => remove(card)}>Delete</button>
              </div>`}
        </div>`)}
    </div></div></div>
  `;
}
