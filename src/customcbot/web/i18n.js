// Interface languages.
//
// Components keep their English text. A language file in /locales maps each
// English phrase to its translation; a phrase that is not in the file stays
// English. Two things are translated:
//   - text and a few attributes written directly in an html`...` template,
//     which is done here by wrapping `html`, so components need no changes;
//   - a phrase chosen in code: one that is dropped into a template as a whole
//     is translated there too; anything else is passed through t('...').
// Everything else from the UI library is re-exported, so components import from here.

import { html as plainHtml } from '/vendor/preact-htm.js';

export * from '/vendor/preact-htm.js';

export const LANGUAGES = [
  ['en', 'English'], ['es', 'Español'], ['fr', 'Français'], ['pt', 'Português'], ['hi', 'हिन्दी'], ['zh', '中文'],
];
const TRANSLATED_ATTRIBUTES = /\b(placeholder|title|aria-label|alt)="([^"]+)"/g;

let dictionary = null;
let current = 'en';

export function language() {
  return current;
}

function wanted() {
  const saved = localStorage.getItem('customcbot.language');
  if (saved) return saved;
  const browser = (navigator.language || 'en').slice(0, 2).toLowerCase();
  return LANGUAGES.some(([code]) => code === browser) ? browser : 'en';
}

// Call once, before the first render.
export async function loadLanguage() {
  current = LANGUAGES.some(([code]) => code === wanted()) ? wanted() : 'en';
  document.documentElement.lang = current;
  if (current === 'en') return;
  try {
    const response = await fetch(`/locales/${current}.json`);
    dictionary = response.ok ? await response.json() : null;
  } catch {
    dictionary = null;  // no translation available: stay in English
  }
}

export function setLanguage(code) {
  localStorage.setItem('customcbot.language', code);
  window.location.reload();
}

// Translate a phrase chosen in code. {name} places are filled from `values`.
export function t(text, values) {
  let out = (dictionary && dictionary[text]) || text;
  if (values) for (const [name, value] of Object.entries(values)) out = out.split(`{${name}}`).join(value);
  return out;
}

function phrase(text) {
  const key = text.replace(/\s+/g, ' ').trim();
  const found = key && dictionary[key];
  if (!found) return text;
  return text.match(/^\s*/)[0] + found + text.match(/\s*$/)[0];
}

// The fixed parts of a template, with their text translated. `state.inTag`
// carries over from one part to the next, because a ${value} can sit inside a tag.
function translateParts(parts) {
  const state = { inTag: false, quote: '' };
  return parts.map((part) => {
    let out = '';
    let run = '';
    const flush = () => {
      if (!run) return;
      out += state.inTag ? run.replace(TRANSLATED_ATTRIBUTES, (_, name, value) => `${name}="${phrase(value)}"`) : phrase(run);
      run = '';
    };
    for (const char of part) {
      if (state.inTag) {
        run += char;
        if (state.quote) {
          if (char === state.quote) state.quote = '';
        } else if (char === '"' || char === "'") {
          state.quote = char;
        } else if (char === '>') {
          flush();
          state.inTag = false;
        }
      } else if (char === '<') {
        flush();
        state.inTag = true;
        run = char;
      } else {
        run += char;
      }
    }
    flush();
    return out;
  });
}

const translatedTemplates = new WeakMap();

export function html(parts, ...values) {
  if (!dictionary) return plainHtml(parts, ...values);
  let translated = translatedTemplates.get(parts);
  if (!translated) {
    translated = translateParts(parts);
    translatedTemplates.set(parts, translated);
  }
  // A phrase picked in code and dropped into the template, such as a button label
  // that changes with state, is translated when the language file knows it.
  // Only phrases starting with a capital are considered, so class names and other
  // code strings can never be swapped for a translation.
  return plainHtml(translated, ...values.map((value) => (
    (typeof value === 'string' && /^\p{Lu}/u.test(value) && dictionary[value]) || value)));
}
