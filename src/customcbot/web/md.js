// Renders model output: Markdown, maths and clickable citation numbers.
// Everything is sanitised before it reaches the page.

import { marked } from '/vendor/marked.js';
import DOMPurify from '/vendor/purify.js';

marked.setOptions({ gfm: true, breaks: true });

let katex = null;
let katexLoading = null;
const katexListeners = new Set();

function loadKatex() {
  if (katexLoading) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/vendor/katex/katex.min.css';
  document.head.appendChild(link);
  katexLoading = import('/vendor/katex/katex.js')
    .then((module) => {
      katex = module.default;
      katexListeners.forEach((listener) => listener());
    })
    .catch(() => { /* maths stays as plain text */ });
}

// Components call this to re-render once the maths library has loaded.
export function onMathReady(listener) {
  katexListeners.add(listener);
  return () => katexListeners.delete(listener);
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const MATH = [
  { pattern: /\$\$([\s\S]+?)\$\$/g, display: true },
  { pattern: /\\\[([\s\S]+?)\\\]/g, display: true },
  { pattern: /\\\(([\s\S]+?)\\\)/g, display: false },
  // Inline $...$: no spaces just inside, and not followed by a digit (so "$5 and $10" is left alone).
  { pattern: /\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)/g, display: false },
];

export function renderMarkdown(text, citations = []) {
  // 1. Lift maths out so Markdown does not mangle underscores and asterisks in it.
  const maths = [];
  let source = text || '';
  for (const { pattern, display } of MATH) {
    source = source.replace(pattern, (_, body) => {
      maths.push({ body, display });
      return `@@MATH${maths.length - 1}@@`;
    });
  }

  // 2. Markdown to HTML, then strip anything unsafe.
  let html = DOMPurify.sanitize(marked.parse(source), { USE_PROFILES: { html: true } });

  // 3. Citation markers like [1], [2, 3] or [Source 1] become buttons, if that source exists.
  const known = new Set(citations.map((c) => c.n));
  html = html.replace(/\[(?:source\s*)?(\d+(?:\s*,\s*\d+)*)\]/gi, (whole, list) => {
    const numbers = list.split(',').map((n) => parseInt(n, 10));
    if (!numbers.every((n) => known.has(n))) return whole;
    return numbers.map((n) => `<button type="button" class="cite" data-cite="${n}">${n}</button>`).join('');
  });

  // 4. Put the maths back, typeset when the library is available.
  if (maths.length) {
    if (!katex) loadKatex();
    html = html.replace(/@@MATH(\d+)@@/g, (_, index) => {
      const { body, display } = maths[Number(index)];
      if (katex) {
        try {
          return katex.renderToString(body, { displayMode: display, throwOnError: false });
        } catch { /* fall through to plain text */ }
      }
      return escapeHtml(display ? `$$${body}$$` : `$${body}$`);
    });
  }
  return html;
}
