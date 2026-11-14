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

export function Setup({ status, refresh, onDone, onCancel }) {
  const [choice, setChoice] = useState(status.settings.tier && status.settings.tier !== 'custom' ? status.settings.tier : status.recommended);
  const [customModel, setCustomModel] = useState('');
  const [customVision, setCustomVision] = useState('');
  const [starting, setStarting] = useState(false);

  // Keep checking, so the wizard moves on by itself when Ollama starts or a download finishes.
  useEffect(() => {
    const timer = setInterval(refresh, 1500);
    return () => clearInterval(timer);
  }, []);

  const { ollama, pull } = status;
  const step = !ollama.running ? 1 : pull.active || pull.done ? 3 : 2;

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

  let content;
  if (step === 1) {
    content = html`
      <h2>Step 1: Install Ollama</h2>
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
    `;
  } else if (step === 2) {
    content = html`
      <h2>Step 2: Choose a model size</h2>
      <p class="muted">Your computer: ${describeHardware(status.hardware)}.</p>
      ${pull.error && html`<div class="banner err">The download did not finish: ${pull.error}</div>`}
      <div class="tiers">
        ${status.tiers.map((tier) => html`
          <button class=${`card tier${choice === tier.id ? ' selected' : ''}`} onClick=${() => setChoice(tier.id)} aria-pressed=${choice === tier.id}>
            <span class="row">
              <strong class="grow">${tier.label}</strong>
              ${tier.id === status.recommended && html`<span class="badge ok">Recommended</span>`}
            </span>
            <span class="size">${tier.download_gb} GB download · needs ${tier.min_ram_gb} GB memory</span>
            <span class="small">${tier.blurb}</span>
          </button>
        `)}
      </div>
      <div class="row">
        <button class="btn primary" disabled=${starting} onClick=${() => install({ tier: choice })}>Download and continue</button>
        ${onCancel && html`<button class="btn" onClick=${onCancel}>Cancel</button>`}
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
  } else if (pull.active) {
    const known = pull.total > 0;
    content = html`
      <h2>Step 3: Downloading</h2>
      <p>${pull.model ? html`Getting <strong>${pull.model}</strong>${pull.steps > 1 ? ` (${pull.step} of ${pull.steps})` : ''}.` : pull.status}</p>
      <${Progress} value=${known ? pull.completed / pull.total : 0} busy=${!known} />
      <p class="muted small">
        ${known ? `${gigabytes(pull.completed)} of ${gigabytes(pull.total)} GB. ` : ''}
        This happens once. You can leave this page open and come back.
      </p>
    `;
  } else {
    content = html`
      <h2>All set</h2>
      <p>The model is installed. Create a collection, add your material, and start asking questions.</p>
      <div><button class="btn primary" onClick=${onDone}>Start</button></div>
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

export function Settings({ status, onClose, onChangeModel, refresh }) {
  const settings = status.settings;
  const [numCtx, setNumCtx] = useState(settings.num_ctx);
  const [whisper, setWhisper] = useState(settings.whisper_model);
  const [url, setUrl] = useState(settings.ollama_url || '');

  const save = async () => {
    try {
      const values = { whisper_model: whisper, ollama_url: url };
      if (Number(numCtx) !== settings.num_ctx) {
        values.num_ctx = Number(numCtx);
        values.context_chars = Number(numCtx) >= 8192 ? 9000 : 5000;
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
          <strong>Model: ${settings.chat_model || 'none'}</strong>
          <div class="muted small">
            ${status.vision_available ? 'Can read handwriting and scanned pages.' : 'Reads printed text only; handwriting is unreliable.'}
          </div>
        </div>
        <button class="btn" onClick=${onChangeModel}>Change model size</button>
      </div>
      <label class="field">Memory use
        <select value=${String(numCtx)} onChange=${(e) => setNumCtx(e.target.value)}>
          <option value="4096">Low: shorter passages per answer (best under 12 GB of memory)</option>
          <option value="8192">Normal: more of your material per answer</option>
        </select>
      </label>
      <label class="field">Speech-to-text quality, for videos without captions and audio files
        <select value=${whisper} onChange=${(e) => setWhisper(e.target.value)}>
          <option value="tiny">Fastest (tiny)</option>
          <option value="base">Balanced (base)</option>
          <option value="small">Most accurate, slow on older computers (small)</option>
        </select>
      </label>
      <label class="field">Ollama address (leave empty for this computer)
        <input type="text" placeholder="http://127.0.0.1:11434" value=${url} onInput=${(e) => setUrl(e.target.value)} />
      </label>
      <p class="muted small">Hardware: ${describeHardware(status.hardware)}.</p>
    <//>
  `;
}
