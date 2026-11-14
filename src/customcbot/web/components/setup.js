// First-run wizard and the Settings dialog.

import { html, useEffect, useState } from '/vendor/preact-htm.js';
import { api } from '/api.js';
import { Dialog, Progress, toast } from '/components/ui.js';

function gigabytes(bytes) {
  return (bytes / 1e9).toFixed(1);
}

function describeHardware(hw) {
  const parts = [`${hw.ram_gb} GB memory`, `${hw.cpu_cores} processor cores`];
  parts.push(hw.gpu ? `${hw.gpu}${hw.system === 'Darwin' ? '' : ` (${hw.gpu_gb} GB)`}` : 'no dedicated graphics card');
  return parts.join(', ');
}

function serviceLabel(status) {
  const service = status.online_services.find((s) => s.id === status.settings.online_service);
  if (service && service.id !== 'custom') return service.label;
  try {
    return new URL(status.settings.api_base_url).host;  // "Another service" says little; show its address
  } catch {
    return 'an online service';
  }
}

// A short line saying where answers come from right now.
export function describeMode(status) {
  if (status.fake) return 'Demo mode';
  if (status.mode === 'online') return `Online: ${serviceLabel(status)}`;
  return 'On this computer';
}

export function Setup({ status, refresh, onDone, onCancel }) {
  // null: still choosing where the AI runs.
  const [mode, setMode] = useState(null);

  // Keep checking, so the wizard moves on by itself when Ollama starts or a download finishes.
  useEffect(() => {
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, []);

  const { pull } = status;
  const working = pull.active || pull.done;
  const step = working ? 3 : mode ? 2 : 1;

  let content;
  if (pull.active) {
    const known = pull.total > 0;
    content = html`
      <h2>${pull.model ? 'Step 3: Downloading' : 'Step 3: Getting ready'}</h2>
      <p>${pull.model ? html`Getting <strong>${pull.model}</strong>${pull.steps > 1 ? ` (${pull.step} of ${pull.steps})` : ''}.` : `${pull.status}…`}</p>
      <${Progress} value=${known ? pull.completed / pull.total : 0} busy=${!known} />
      <p class="muted small">
        ${known ? `${gigabytes(pull.completed)} of ${gigabytes(pull.total)} GB. ` : ''}
        This happens once. You can leave this page open and come back.
      </p>
    `;
  } else if (pull.done) {
    content = html`
      <h2>All set</h2>
      <p>${status.mode === 'online'
        ? html`Connected to <strong>${serviceLabel(status)}</strong>, using <strong>${status.settings.api_model}</strong>.`
        : 'The model is installed.'}
        ${' '}Create a collection, add your material, and start asking questions.</p>
      <div><button class="btn primary" onClick=${onDone}>Start</button></div>
    `;
  } else if (mode === 'local') {
    content = html`<${LocalSetup} status=${status} refresh=${refresh} onBack=${() => setMode(null)} />`;
  } else if (mode === 'online') {
    content = html`<${OnlineSetup} status=${status} refresh=${refresh} onBack=${() => setMode(null)} />`;
  } else {
    const best = status.recommended_mode;
    const choices = [
      ['local', 'On this computer',
        'Private: nothing you add leaves your computer, and it works without internet.',
        'Needs a one-time download of 1 to 8 GB. Answers are best with 8 GB of memory or more.'],
      ['online', 'Free online service',
        'Good, fast answers on any computer, with nothing large to download.',
        'Needs a free key from a service such as Groq or Google Gemini. The passages used for each answer are sent to that service.'],
    ];
    if (best === 'online') choices.reverse();
    content = html`
      <h2>Step 1: Where should the AI run?</h2>
      <p class="muted">Your computer: ${describeHardware(status.hardware)}.
        ${best === 'online' ? ' That is too little memory for a good local model, so an online service will give much better answers.' : ''}</p>
      ${pull.error && html`<div class="banner err">Setup did not finish: ${pull.error}</div>`}
      <div class="tiers">
        ${choices.map(([id, title, good, cost]) => html`
          <button class="card tier" onClick=${() => setMode(id)} key=${id}>
            <span class="row">
              <strong class="grow">${title}</strong>
              ${id === best && html`<span class="badge ok">Recommended</span>`}
              ${status.ready && id === status.mode && html`<span class="badge">In use</span>`}
            </span>
            <span class="small">${good}</span>
            <span class="size">${cost}</span>
          </button>`)}
      </div>
      <p class="muted small">You can switch at any time in Settings. Your files, the search index and speech-to-text always stay on this computer.</p>
      ${onCancel && html`<div><button class="btn" onClick=${onCancel}>Cancel</button></div>`}
    `;
  }

  return html`
    <div class="setup">
      <div class="panel">
        <div class="brand"><img src="/favicon.svg" alt="" /> customcbot</div>
        <div class="steps" aria-hidden="true">
          ${[1, 2, 3].map((n) => html`<span class=${n <= step ? 'on' : ''}></span>`)}
        </div>
        <div class="card stack">${content}</div>
      </div>
    </div>
  `;
}

function LocalSetup({ status, refresh, onBack }) {
  const tier = status.settings.tier;
  const [choice, setChoice] = useState(tier && tier !== 'custom' ? tier : status.recommended);
  const [customModel, setCustomModel] = useState('');
  const [customVision, setCustomVision] = useState('');
  const [starting, setStarting] = useState(false);
  const { ollama, pull } = status;

  const install = async (body) => {
    setStarting(true);
    try {
      await api.post('/api/setup/install', body);
      await refresh();
    } catch (error) {
      toast(error.message);
    }
    setStarting(false);
  };

  if (!ollama.running) {
    return html`
      <h2>Step 2: Install Ollama</h2>
      <p>
        customcbot uses <strong>Ollama</strong>, a free program that runs AI models on your own computer.
        Nothing you upload leaves your machine.
      </p>
      <ol>
        <li>Download it from <a href="https://ollama.com/download" target="_blank" rel="noopener">ollama.com/download</a> and install it.</li>
        <li>Open Ollama once so it is running (you will see its icon near the clock).</li>
        <li>Come back here. This page continues by itself.</li>
      </ol>
      <div class="banner info row">
        <span class="grow">Looking for Ollama at ${ollama.url}…</span>
        <button class="btn small" onClick=${refresh}>Check again</button>
      </div>
      <div><button class="btn" onClick=${onBack}>Back</button></div>
    `;
  }
  return html`
    <h2>Step 2: Choose a model size</h2>
    <p class="muted">Your computer: ${describeHardware(status.hardware)}.</p>
    ${pull.error && html`<div class="banner err">The download did not finish: ${pull.error}</div>`}
    <div class="tiers">
      ${status.tiers.map((item) => html`
        <button class=${`card tier${choice === item.id ? ' selected' : ''}`} onClick=${() => setChoice(item.id)} aria-pressed=${choice === item.id}>
          <span class="row">
            <strong class="grow">${item.label}</strong>
            ${item.id === status.recommended && html`<span class="badge ok">Recommended</span>`}
          </span>
          <span class="size">${item.download_gb} GB download · needs ${item.min_ram_gb} GB memory</span>
          <span class="small">${item.blurb}</span>
        </button>
      `)}
    </div>
    <div class="row">
      <button class="btn primary" disabled=${starting} onClick=${() => install({ tier: choice })}>Download and continue</button>
      <button class="btn" onClick=${onBack}>Back</button>
    </div>
    <details>
      <summary>Use a different Ollama model (advanced)</summary>
      <div class="stack" style="margin-top: 10px">
        <label class="field">Chat model
          <input type="text" placeholder="for example qwen3.5:4b" value=${customModel} onInput=${(e) => setCustomModel(e.target.value)} />
        </label>
        <label class="field">Model for reading images and handwriting (optional)
          <input type="text" placeholder="a vision-capable model, or leave empty" value=${customVision} onInput=${(e) => setCustomVision(e.target.value)} />
        </label>
        <div><button class="btn" disabled=${!customModel.trim() || starting} onClick=${() => install({ chat_model: customModel, vision_model: customVision })}>Download this model</button></div>
      </div>
    </details>
  `;
}

function OnlineSetup({ status, refresh, onBack }) {
  const settings = status.settings;
  const services = status.online_services;
  const [serviceId, setServiceId] = useState(settings.online_service || services[0].id);
  const service = services.find((s) => s.id === serviceId) || services[0];
  const sameAsSaved = settings.online_service === service.id;
  const [address, setAddress] = useState(sameAsSaved ? settings.api_base_url || '' : service.base_url || '');
  const [key, setKey] = useState('');
  const [models, setModels] = useState(null);
  const [model, setModel] = useState('');
  const [vision, setVision] = useState(sameAsSaved ? settings.api_vision : service.vision);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  const keySaved = sameAsSaved && settings.api_key_saved;
  const editableAddress = !service.base_url || service.id === 'freellmapi';

  const pick = (id) => {
    const next = services.find((s) => s.id === id);
    const saved = settings.online_service === id;
    setServiceId(id);
    setAddress(saved ? settings.api_base_url || '' : next.base_url || '');
    setVision(saved ? settings.api_vision : next.vision);
    setKey('');
    setModels(null);
    setModel('');
    setProblem('');
  };

  const body = () => ({ service: service.id, base_url: address.trim() || null, api_key: key.trim() || null });

  const check = async (event) => {
    event.preventDefault();
    setBusy(true);
    setProblem('');
    try {
      const found = await api.post('/api/setup/online/models', body());
      setAddress(found.base_url);
      setModels(found.models);
      setModel(sameAsSaved && found.models.includes(settings.api_model) ? settings.api_model : found.suggested || '');
    } catch (error) {
      setModels(null);
      setProblem(error.message);
    }
    setBusy(false);
  };

  const connect = async () => {
    setBusy(true);
    setProblem('');
    try {
      await api.post('/api/setup/online', { ...body(), model, vision });
      await refresh();
    } catch (error) {
      setProblem(error.message);
    }
    setBusy(false);
  };

  const canCheck = (key.trim() || keySaved || !service.needs_key) && (address.trim() || service.base_url);

  return html`
    <h2>Step 2: Connect a free online service</h2>
    <div class="banner info">
      With an online service, your question and the passages that match it are sent to that service to write the answer.
      Your files, the search index and speech-to-text stay on this computer.
    </div>
    <label class="field">Service
      <select value=${service.id} onChange=${(e) => pick(e.target.value)}>
        ${services.map((s) => html`<option value=${s.id} key=${s.id}>${s.label}</option>`)}
      </select>
    </label>
    <p class="small" style="margin: 0">${service.blurb}</p>
    <form class="stack" onSubmit=${check}>
      ${service.key_url && service.id !== 'freellmapi' && html`
        <ol class="small" style="margin: 0">
          <li>Open <a href=${service.key_url} target="_blank" rel="noopener">${service.key_url.replace('https://', '')}</a> and sign in or create a free account.</li>
          <li>Create an API key and copy it.</li>
          <li>Paste it below.</li>
        </ol>`}
      ${service.id === 'freellmapi' && html`
        <p class="small" style="margin: 0">Start FreeLLMAPI first
          (<a href=${service.key_url} target="_blank" rel="noopener">how to install it</a>),
          then copy the key that starts with “freellmapi-” from its dashboard.</p>`}
      ${editableAddress && html`
        <label class="field">Address
          <input type="text" placeholder="for example http://localhost:1234/v1" value=${address}
            onInput=${(e) => { setAddress(e.target.value); setModels(null); }} />
        </label>`}
      <label class="field">${service.needs_key ? 'Key' : 'Key (leave empty if the service needs none)'}
        <input type="password" autocomplete="off" value=${key}
          placeholder=${keySaved ? 'A key is saved. Leave empty to keep it.' : 'Paste your key here'}
          onInput=${(e) => { setKey(e.target.value); setModels(null); }} />
      </label>
      ${problem && html`<div class="banner err" role="alert">${problem}</div>`}
      ${!models && html`
        <div class="row">
          <button class="btn primary" disabled=${busy || !canCheck}>${busy ? 'Checking…' : 'Check'}</button>
          <button type="button" class="btn" onClick=${onBack}>Back</button>
        </div>`}
    </form>
    ${models && html`
      <div class="banner ok">Connected. ${models.length} model${models.length === 1 ? '' : 's'} available.</div>
      <label class="field">Model
        ${models.length
          ? html`<select value=${model} onChange=${(e) => setModel(e.target.value)}>
              ${models.map((name, index) => html`<option value=${name} key=${name}>${name}${index === 0 ? ' (suggested)' : ''}</option>`)}
            </select>`
          : html`<input type="text" placeholder="the model name" value=${model} onInput=${(e) => setModel(e.target.value)} />`}
      </label>
      <label class="row small">
        <input type="checkbox" checked=${vision} onChange=${(e) => setVision(e.target.checked)} />
        <span>This model can read images. Use it for handwriting and scanned pages (the page images are then sent to the service).</span>
      </label>
      <div class="row">
        <button class="btn primary" disabled=${busy || !model.trim()} onClick=${connect}>${busy ? 'Testing…' : 'Use this service'}</button>
        <button class="btn" onClick=${onBack}>Back</button>
      </div>`}
  `;
}

export function Settings({ status, onClose, onChangeModel, refresh }) {
  const settings = status.settings;
  const online = status.mode === 'online';
  const [numCtx, setNumCtx] = useState(settings.num_ctx);
  const [whisper, setWhisper] = useState(settings.whisper_model);
  const [url, setUrl] = useState(settings.ollama_url || '');

  const save = async () => {
    try {
      const values = { whisper_model: whisper };
      if (!online) {
        values.ollama_url = url;
        if (Number(numCtx) !== settings.num_ctx) {
          values.num_ctx = Number(numCtx);
          values.context_chars = Number(numCtx) >= 8192 ? 9000 : 5000;
        }
      }
      await api.put('/api/settings', { values });
      await refresh();
      toast('Settings saved.');
      onClose();
    } catch (error) {
      toast(error.message);
    }
  };

  return html`
    <${Dialog} title="Settings" onClose=${onClose} footer=${html`
      <button class="btn" onClick=${onClose}>Cancel</button>
      <button class="btn primary" onClick=${save}>Save</button>`}>
      ${status.fake && html`<div class="banner warn">Demo mode: answers are placeholders, not from a real model.</div>`}
      <div class="row wrap">
        <div class="grow">
          <strong>${online ? `Answers come from ${serviceLabel(status)}` : 'Answers come from this computer'}</strong>
          <div class="muted small">
            Model: ${(online ? settings.api_model : settings.chat_model) || 'none'}.
            ${' '}${status.vision_available ? 'Can read handwriting and scanned pages.' : 'Reads printed text only; handwriting is unreliable.'}
          </div>
          ${online && html`<div class="muted small">Questions and the passages that match them are sent to this service.</div>`}
        </div>
        <button class="btn" onClick=${onChangeModel}>Change</button>
      </div>
      ${!online && html`
        <label class="field">Memory use
          <select value=${String(numCtx)} onChange=${(e) => setNumCtx(e.target.value)}>
            <option value="4096">Low: shorter passages per answer (best under 12 GB of memory)</option>
            <option value="8192">Normal: more of your material per answer</option>
          </select>
        </label>`}
      <label class="field">Speech-to-text quality, for videos without captions and audio files
        <select value=${whisper} onChange=${(e) => setWhisper(e.target.value)}>
          <option value="tiny">Fastest (tiny)</option>
          <option value="base">Balanced (base)</option>
          <option value="small">Most accurate, slow on older computers (small)</option>
        </select>
      </label>
      ${!online && html`
        <label class="field">Ollama address (leave empty for this computer)
          <input type="text" placeholder="http://127.0.0.1:11434" value=${url} onInput=${(e) => setUrl(e.target.value)} />
        </label>`}
      <p class="muted small">Hardware: ${describeHardware(status.hardware)}.</p>
    <//>
  `;
}
