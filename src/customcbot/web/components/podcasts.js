// The Podcast tab: turn your material into a spoken episode, and choose who speaks.

import { html, useEffect, useState } from '/vendor/preact-htm.js';
import { api, formatTime } from '/api.js';
import { Dialog, JobProgress, toast, useJob } from '/components/ui.js';

function VoicesEditor({ profile, voices, onClose, onSaved }) {
  const [name, setName] = useState(profile.name || '');
  const [speakers, setSpeakers] = useState(profile.speakers || [{ name: '', voice: voices[0].id, role: '' }]);
  const [busy, setBusy] = useState(false);

  const change = (index, field, value) => setSpeakers(speakers.map((s, i) => (i === index ? { ...s, [field]: value } : s)));
  const run = async (work) => {
    setBusy(true);
    try {
      await work();
      await onSaved();
      onClose();
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => {
    const body = { name, description: profile.description || '', speakers };
    return profile.id ? api.put(`/api/speaker-profiles/${profile.id}`, body) : api.post('/api/speaker-profiles', body);
  });

  return html`
    <${Dialog} title=${profile.id ? `Voices: ${profile.name}` : 'New set of voices'} wide onClose=${onClose} footer=${html`
      ${profile.id && html`<button class="btn danger" disabled=${busy}
        onClick=${() => window.confirm(`Delete "${profile.name}"?`) && run(() => api.del(`/api/speaker-profiles/${profile.id}`))}>Delete</button>`}
      <button class="btn" onClick=${onClose}>Cancel</button>
      <button class="btn primary" disabled=${busy || !name.trim()} onClick=${save}>Save</button>`}>
      <label class="field">Name
        <input type="text" placeholder="For example: Two hosts" value=${name} onInput=${(e) => setName(e.target.value)} />
      </label>
      ${speakers.map((speaker, index) => html`
        <div class="card stack" key=${index}>
          <div class="row wrap">
            <label class="field grow">Speaker ${index + 1}
              <input type="text" placeholder="A first name" value=${speaker.name} onInput=${(e) => change(index, 'name', e.target.value)} />
            </label>
            <label class="field grow">Voice
              <select value=${speaker.voice} onChange=${(e) => change(index, 'voice', e.target.value)}>
                ${voices.map((voice) => html`<option value=${voice.id} key=${voice.id}>${voice.label}</option>`)}
              </select>
            </label>
            ${speakers.length > 1 && html`
              <button class="btn small ghost danger" onClick=${() => setSpeakers(speakers.filter((_, i) => i !== index))}>Remove</button>`}
          </div>
          <label class="field">What this speaker is like
            <input type="text" placeholder="For example: a curious student who asks questions" value=${speaker.role}
              onInput=${(e) => change(index, 'role', e.target.value)} />
          </label>
        </div>`)}
      ${speakers.length < 4 && html`
        <div><button class="btn small" onClick=${() => setSpeakers([...speakers, { name: '', voice: voices[0].id, role: '' }])}>Add a speaker</button></div>`}
      <p class="muted small">Pick voices in the language of your material. The English voices are the best tested.</p>
    <//>`;
}

function KindEditor({ kind, speakerProfiles, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: kind.name || '', briefing: kind.briefing || '', segments: kind.segments || 3,
    speaker_profile_id: kind.speaker_profile_id || (speakerProfiles[0] && speakerProfiles[0].id),
  });
  const [busy, setBusy] = useState(false);
  const run = async (work) => {
    setBusy(true);
    try {
      await work();
      await onSaved();
      onClose();
    } catch (error) {
      toast(error.message);
    } finally {
      setBusy(false);
    }
  };
  const body = { ...form, segments: Number(form.segments), speaker_profile_id: Number(form.speaker_profile_id), description: kind.description || '' };
  return html`
    <${Dialog} title=${kind.id ? `Kind of episode: ${kind.name}` : 'New kind of episode'} wide onClose=${onClose} footer=${html`
      ${kind.id && html`<button class="btn danger" disabled=${busy}
        onClick=${() => window.confirm(`Delete "${kind.name}"?`) && run(() => api.del(`/api/episode-profiles/${kind.id}`))}>Delete</button>`}
      <button class="btn" onClick=${onClose}>Cancel</button>
      <button class="btn primary" disabled=${busy || !form.name.trim() || !form.briefing.trim()}
        onClick=${() => run(() => (kind.id ? api.put(`/api/episode-profiles/${kind.id}`, body) : api.post('/api/episode-profiles', body)))}>Save</button>`}>
      <label class="field">Name
        <input type="text" placeholder="For example: Study recap" value=${form.name} onInput=${(e) => setForm({ ...form, name: e.target.value })} />
      </label>
      <label class="field">What the episode should be like
        <textarea rows="4" placeholder="For example: A friendly recap that walks through the key ideas."
          value=${form.briefing} onInput=${(e) => setForm({ ...form, briefing: e.target.value })}></textarea>
      </label>
      <div class="row wrap">
        <label class="field grow">Who speaks
          <select value=${String(form.speaker_profile_id)} onChange=${(e) => setForm({ ...form, speaker_profile_id: e.target.value })}>
            ${speakerProfiles.map((p) => html`<option value=${String(p.id)} key=${p.id}>${p.name} (${p.speakers.map((s) => s.name).join(', ')})</option>`)}
          </select>
        </label>
        <label class="field">Length
          <select value=${String(form.segments)} onChange=${(e) => setForm({ ...form, segments: e.target.value })}>
            ${[1, 2, 3, 4, 5, 6].map((n) => html`<option value=${String(n)} key=${n}>${n} part${n === 1 ? '' : 's'} (about ${n}–${n * 2} minutes)</option>`)}
          </select>
        </label>
      </div>
    <//>`;
}

function ProfilesDialog({ data, onClose, reload }) {
  const [editing, setEditing] = useState(null);  // { type: 'kind' | 'voices', item }
  if (editing && editing.type === 'kind') {
    return html`<${KindEditor} kind=${editing.item} speakerProfiles=${data.speakerProfiles} onClose=${() => setEditing(null)} onSaved=${reload} />`;
  }
  if (editing) {
    return html`<${VoicesEditor} profile=${editing.item} voices=${data.voices} onClose=${() => setEditing(null)} onSaved=${reload} />`;
  }
  return html`
    <${Dialog} title="Episode kinds and voices" wide onClose=${onClose} footer=${html`<button class="btn primary" onClick=${onClose}>Done</button>`}>
      <div class="row"><h3 class="grow">Kinds of episode</h3>
        <button class="btn small" onClick=${() => setEditing({ type: 'kind', item: {} })}>New kind</button></div>
      ${data.kinds.map((kind) => html`
        <div class="list-row" key=${kind.id}>
          <span class="grow"><strong>${kind.name}</strong>
            <span class="muted small" style="display: block">${kind.description || kind.briefing.slice(0, 100)}</span></span>
          <button class="btn small" onClick=${() => setEditing({ type: 'kind', item: kind })}>Edit</button>
        </div>`)}
      <div class="row"><h3 class="grow">Sets of voices</h3>
        <button class="btn small" onClick=${() => setEditing({ type: 'voices', item: {} })}>New set</button></div>
      ${data.speakerProfiles.map((profile) => html`
        <div class="list-row" key=${profile.id}>
          <span class="grow"><strong>${profile.name}</strong>
            <span class="muted small" style="display: block">${profile.speakers.map((s) => s.name).join(' and ')}</span></span>
          <button class="btn small" onClick=${() => setEditing({ type: 'voices', item: profile })}>Edit</button>
        </div>`)}
    <//>`;
}

function Episode({ summary, onRemoved }) {
  const [full, setFull] = useState(null);
  const showScript = async (event) => {
    if (event.target.open && !full) setFull(await api.get(`/api/podcasts/${summary.id}`).catch(() => null));
  };
  const remove = async () => {
    if (!window.confirm(`Delete the episode "${summary.title}"?`)) return;
    await api.del(`/api/podcasts/${summary.id}`).catch((error) => toast(error.message));
    onRemoved();
  };
  const audio = `/api/podcasts/${summary.id}/audio`;
  return html`
    <div class="card stack">
      <div class="row wrap">
        <strong class="grow">${summary.title}</strong>
        ${summary.duration_sec && html`<span class="muted small">${formatTime(summary.duration_sec)}</span>`}
        <button class="btn small ghost danger" onClick=${remove}>Delete</button>
      </div>
      ${summary.status === 'error' && html`<div class="banner err">${summary.error || 'This episode could not be made.'}</div>`}
      ${summary.status === 'ready' && html`
        <audio controls preload="none" src=${audio} style="width: 100%"></audio>
        <div class="row">
          <a class="btn small" href=${`${audio}?download=true`}>Download MP3</a>
        </div>
        <details onToggle=${showScript}>
          <summary>Read the script</summary>
          <div class="stack" style="margin-top: 10px; gap: 6px">
            ${!full && html`<span class="muted small">Loading…</span>`}
            ${full && (full.transcript || []).map((line, index) => html`<p key=${index}><strong>${line.speaker}:</strong> ${line.text}</p>`)}
          </div>
        </details>`}
    </div>`;
}

export function PodcastTab({ collectionId, sourceIds, readyCount }) {
  const [data, setData] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [kindId, setKindId] = useState('');
  const [wishes, setWishes] = useState('');
  const [managing, setManaging] = useState(false);

  const loadEpisodes = () => api.get(`/api/collections/${collectionId}/podcasts`).then(setEpisodes).catch((error) => toast(error.message));
  const loadProfiles = async () => {
    try {
      const [kinds, speakerProfiles, voices] = await Promise.all([
        api.get('/api/episode-profiles'), api.get('/api/speaker-profiles'), api.get('/api/podcast-voices'),
      ]);
      setData({ kinds, speakerProfiles, voices });
      setKindId((current) => (kinds.some((k) => String(k.id) === current) ? current : String(kinds[0] ? kinds[0].id : '')));
    } catch (error) {
      toast(error.message);
    }
  };
  useEffect(() => { loadProfiles(); }, []);
  useEffect(() => { setEpisodes([]); loadEpisodes(); }, [collectionId]);
  const task = useJob(collectionId, ['generate_podcast'], loadEpisodes);
  useEffect(() => { if (!task.active) loadEpisodes(); }, [task.active]);

  const kind = data && data.kinds.find((k) => String(k.id) === kindId);
  const voices = kind && data.speakerProfiles.find((p) => p.id === kind.speaker_profile_id);
  const finished = episodes.filter((e) => e.status === 'ready' || e.status === 'error');
  const make = () => task.start(`/api/collections/${collectionId}/podcasts`,
    { episode_profile_id: Number(kindId), briefing: wishes, source_ids: sourceIds });

  return html`
    <div class="tab-body"><div class="scroll"><div class="narrow stack">
      <${JobProgress} task=${task} label="Making the episode" />
      <div class="card stack">
        <div class="row">
          <h2 class="grow">Make a podcast episode</h2>
          <button class="btn small" disabled=${!data} onClick=${() => setManaging(true)}>Kinds and voices</button>
        </div>
        <p class="muted small">Listen to your material instead of reading it. The script is written from your sources and spoken by voices that run on this computer.</p>
        ${!readyCount && html`<p class="muted">Add some material first. Once a source says "Ready", you can make an episode from it.</p>`}
        ${data && readyCount > 0 && html`
          <label class="field">Kind of episode
            <select value=${kindId} onChange=${(e) => setKindId(e.target.value)}>
              ${data.kinds.map((k) => html`<option value=${String(k.id)} key=${k.id}>${k.name}</option>`)}
            </select>
            ${kind && html`<span class="muted small">${kind.description || kind.briefing}
              ${voices ? ` Spoken by ${voices.speakers.map((s) => s.name).join(' and ')}.` : ''}</span>`}
          </label>
          <label class="field">Anything to add for this episode (optional)
            <input type="text" placeholder="For example: focus on the electron transport chain" value=${wishes} onInput=${(e) => setWishes(e.target.value)} />
          </label>
          <div class="row">
            <span class="grow muted small">Takes a few minutes. The first episode also downloads the voices (about 350 MB, once).</span>
            <button class="btn primary" disabled=${task.active || !kindId} onClick=${make}>Make episode</button>
          </div>`}
      </div>
      ${finished.length > 0 && html`<h3>Episodes</h3>`}
      ${finished.map((episode) => html`<${Episode} summary=${episode} onRemoved=${loadEpisodes} key=${episode.id} />`)}
    </div></div></div>
    ${managing && data && html`<${ProfilesDialog} data=${data} onClose=${() => setManaging(false)} reload=${loadProfiles} />`}
  `;
}
