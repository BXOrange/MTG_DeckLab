// Player documentation lives in the repository's user-docs/ folder.  The
// local static server exposes that folder as /user-docs/ so this view always
// displays the same files contributors edit, rather than a copied summary.

import { getLang, t } from './i18n.js';

const CHAPTERS = [
  ['01_getting_started', 'help.chapter.gettingStarted'],
  ['02_deck_import_and_saved_decks', 'help.chapter.deckImport'],
  ['03_deck_analysis', 'help.chapter.deckAnalysis'],
  ['04_goldfish_mode', 'help.chapter.goldfish'],
  ['05_replay_puzzle_mode', 'help.chapter.replay'],
  ['06_settings_and_card_art', 'help.chapter.settings'],
  ['07_card_cache', 'help.chapter.cardCache'],
  ['08_engine_status', 'help.chapter.engineStatus'],
  ['09_multiplayer', 'help.chapter.multiplayer'],
];

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function safeHref(value) {
  const href = value.trim();
  return /^(?:https?:|#|\/|\.\.?\/)/i.test(href) ? href : '#';
}

function inlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, label, href) =>
    `<a href="${escapeHtml(safeHref(href))}" target="_blank" rel="noopener noreferrer">${label}</a>`
  );
  return html;
}

// The guide deliberately uses a small, portable Markdown subset: headings,
// paragraphs, lists, inline links/emphasis and fenced command examples.
// Rendering it locally keeps the app dependency-free and works offline.
function renderMarkdown(markdown) {
  const lines = markdown.replaceAll('\r\n', '\n').split('\n');
  const output = [];
  let paragraph = [];
  let list = null;
  let code = null;

  const closeParagraph = () => {
    if (paragraph.length) output.push(`<p>${inlineMarkdown(paragraph.join(' '))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };

  for (const line of lines) {
    if (line.startsWith('```')) {
      closeParagraph();
      closeList();
      if (code === null) code = [];
      else {
        output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
        code = null;
      }
      continue;
    }
    if (code !== null) {
      code.push(line);
      continue;
    }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeParagraph();
      closeList();
      const level = heading[1].length;
      output.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const unordered = line.match(/^[-*]\s+(.+)$/);
    const ordered = line.match(/^\d+\.\s+(.+)$/);
    if (unordered || ordered) {
      closeParagraph();
      const type = unordered ? 'ul' : 'ol';
      if (list !== type) {
        closeList();
        output.push(`<${type}>`);
        list = type;
      }
      output.push(`<li>${inlineMarkdown((unordered || ordered)[1])}</li>`);
      continue;
    }

    if (!line.trim()) {
      closeParagraph();
      closeList();
      continue;
    }
    closeList();
    paragraph.push(line.trim());
  }

  if (code !== null) output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
  closeParagraph();
  closeList();
  return output.join('');
}

export function renderHelpView(container) {
  const lang = getLang();
  container.innerHTML = `
    <div class="help-view">
      <div class="help-heading">
        <div>
          <h2>${t('help.title')}</h2>
          <p class="hint">${t('help.intro')}</p>
        </div>
        <a class="help-source-link" href="/user-docs/${lang}/01_getting_started.md" target="_blank" rel="noopener noreferrer">${t('help.openSource')}</a>
      </div>
      <div class="help-layout">
        <nav class="help-chapters" aria-label="${t('help.chaptersAria')}">
          ${CHAPTERS.map(([file, label], index) =>
            `<button type="button" class="help-chapter${index === 0 ? ' active' : ''}" data-help-file="${file}">${index + 1}. ${t(label)}</button>`
          ).join('')}
        </nav>
        <article class="help-document" aria-live="polite"><p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('help.loading')}</p></article>
      </div>
    </div>`;

  const documentEl = container.querySelector('.help-document');
  const buttons = [...container.querySelectorAll('.help-chapter')];
  let selectedFile = CHAPTERS[0][0];
  let hasLoaded = false;

  async function loadChapter(file) {
    selectedFile = file;
    buttons.forEach((button) => button.classList.toggle('active', button.dataset.helpFile === file));
    documentEl.innerHTML = `<p class="empty-state"><span class="spinner" aria-hidden="true"></span>${t('help.loading')}</p>`;
    try {
      const response = await fetch(`/user-docs/${lang}/${file}.md`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      documentEl.innerHTML = renderMarkdown(await response.text());
    } catch (_error) {
      documentEl.innerHTML = `<p class="server-status warning">${t('help.unavailable')}</p><button type="button" class="help-retry">${t('help.retry')}</button>`;
      documentEl.querySelector('.help-retry').addEventListener('click', () => loadChapter(file));
    }
  }

  buttons.forEach((button) => button.addEventListener('click', () => loadChapter(button.dataset.helpFile)));
  container.addEventListener('view-shown', () => {
    if (!hasLoaded) {
      hasLoaded = true;
      loadChapter(selectedFile);
    }
  });
}
