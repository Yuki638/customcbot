// Talks to the local server.

async function request(method, path, body) {
  const options = { method, headers: {} };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error('Cannot reach customcbot. Is it still running?');
  }
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json()).detail;
    } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : 'Something went wrong. Please try again.');
  }
  return response.json();
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body = {}) => request('PUT', path, body),
  patch: (path, body = {}) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
};

// Sends a chat message and calls onEvent(name, data) for each streamed event.
export async function streamChat(chatId, body, onEvent, signal) {
  let response;
  try {
    response = await fetch(`/api/chats/${chatId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error.name === 'AbortError') return;
    throw new Error('Cannot reach customcbot. Is it still running?');
  }
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.json()).detail;
    } catch { /* not JSON */ }
    throw new Error(typeof detail === 'string' && detail ? detail : 'Something went wrong. Please try again.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let end;
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let name = 'message';
        let data = '';
        for (const line of block.split('\n')) {
          if (line.startsWith('event: ')) name = line.slice(7);
          else if (line.startsWith('data: ')) data += line.slice(6);
        }
        if (data) onEvent(name, JSON.parse(data));
      }
    }
  } catch (error) {
    if (error.name !== 'AbortError') throw error;
  }
}

export function formatTime(seconds) {
  const total = Math.floor(seconds || 0);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}
