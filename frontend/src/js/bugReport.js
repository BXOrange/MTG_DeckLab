import { getServerUrl } from './settings.js';
import { t } from './i18n.js';

// Match the backend default and retained session history limit.
const DEFAULT_ACTION_COUNT = 12;
const MAX_ACTION_COUNT = 100;

export function initBugReport() {
  const dialog = document.createElement('dialog');
  dialog.className = 'bug-report-dialog';
  dialog.innerHTML = `<form>
    <h2></h2><p class="bug-context"></p>
    <label class="bug-description-label" for="bug-description"></label>
    <textarea id="bug-description" required maxlength="20000" rows="6"></textarea>
    <label class="bug-actions-label" for="bug-action-count"></label>
    <input id="bug-action-count" type="number" min="1" max="${MAX_ACTION_COUNT}" value="${DEFAULT_ACTION_COUNT}" required>
    <p class="bug-result" role="status" aria-live="polite"></p>
    <div class="bug-report-buttons"><button type="button" class="bug-cancel"></button><button type="submit" class="bug-save"></button></div>
  </form>`;
  document.body.append(dialog);
  const form = dialog.querySelector('form');
  const description = dialog.querySelector('textarea');
  const count = dialog.querySelector('input');
  const result = dialog.querySelector('.bug-result');
  const save = dialog.querySelector('.bug-save');
  let context = null;
  document.getElementById('bug-report-button').addEventListener('click', () => {
    const view = document.querySelector('.view.active');
    const board = view?.matches('[data-bug-report-session]') ? view : view?.querySelector('[data-bug-report-session]');
    context = { session_id: board?.dataset.bugReportSession || null, view: view?.id || '' };
    dialog.querySelector('h2').textContent = t('bug.title');
    dialog.querySelector('.bug-context').textContent = t(context.session_id ? 'bug.context' : 'bug.noGame');
    dialog.querySelector('.bug-description-label').textContent = t('bug.description');
    dialog.querySelector('.bug-actions-label').textContent = t('bug.actions');
    dialog.querySelector('.bug-cancel').textContent = t('common.close');
    save.textContent = t('bug.save');
    count.disabled = !context.session_id;
    result.textContent = '';
    dialog.showModal();
    description.focus();
  });
  dialog.querySelector('.bug-cancel').addEventListener('click', () => dialog.close());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!description.value.trim()) { description.focus(); return; }
    save.disabled = true;
    result.textContent = t('common.loading');
    try {
      const response = await fetch(`${getServerUrl()}/api/bug-reports`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...context, description: description.value, action_count: Number(count.value) }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const report = await response.json();
      result.textContent = t('bug.saved', { filename: report.filename });
      description.value = '';
    } catch {
      result.textContent = t('bug.error');
    } finally {
      save.disabled = false;
    }
  });
}
