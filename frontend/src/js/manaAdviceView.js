import { t, fmtNumber } from './i18n.js';
import { escapeHtml } from './cardTile.js';
import { jointDrawProbability, requiredRampCount } from './manaAdvice.js';

const fmt = (value) => fmtNumber(value, { maximumFractionDigits: 2 });
const percent = (value) => `${fmtNumber(value * 100, { maximumFractionDigits: 1 })}%`;
const names = (cards) => cards.map((card) => `${card.name}${card.quantity > 1 ? ` ×${card.quantity}` : ''}`).join(', ');

function rampTargetHtml(size, lands, current, target) {
  const required = requiredRampCount(size, target, 9, lands);
  return required === null ? t('an.manaAdvice.unreachable') : escapeHtml(t('an.manaAdvice.rampTarget', {
    target: percent(target), required, current, additional: Math.max(0, required - current),
  }));
}

export function manaAdviceHtml(state) {
  if (!state || state.error) return `<h4>${t('an.manaAdvice.heading')}</h4><p class="hint">${t('an.manaAdvice.unavailable')}</p>`;
  const rows = state.probabilities.map((row) => `<tr>
    <td>${row.turn ? escapeHtml(t('an.manaAdvice.turn', { turn: row.turn })) : t('an.manaAdvice.opening')}</td>
    <td>${row.draws}</td><td>${percent(row.rampChance)}</td>
    <td>${escapeHtml(t('an.manaAdvice.jointRequirement', { lands: row.minLands, ramp: 1 }))}: ${percent(row.jointChance)}</td>
  </tr>`).join('');
  return `<h4>${t('an.manaAdvice.heading')}</h4>
    <p>${escapeHtml(t('an.manaAdvice.landEstimate', {
      lands: state.landTarget === null ? '—' : state.landTarget,
      current: state.lands, effective: fmt(state.effectiveTarget), credit: fmt(state.mdfcCredit),
    }))}</p>
    <p class="hint">${escapeHtml(t('an.manaAdvice.formula', {
      average: fmt(state.averageManaValue), draw: state.cheapDraw, ramp: state.cheapRamp,
    }))}</p>
    ${state.unknownMdfcs ? `<p class="hint">${t('an.manaAdvice.unknownMdfcs')}</p>` : ''}
    ${state.size !== 99 ? `<p class="hint">${escapeHtml(t('an.manaAdvice.sizeNotice', { size: state.size }))}</p>` : ''}
    <h5>${t('an.manaAdvice.rampHeading')}</h5>
    <p class="hint">${escapeHtml(t('an.manaAdvice.earlyCount', { count: state.earlyRamp }))}</p>
    <div class="mana-advice-table-scroll"><table class="advice-color-table">
      <thead><tr><th>${t('an.manaAdvice.when')}</th><th>${t('an.manaAdvice.seen')}</th><th>${t('an.manaAdvice.rampProbability')}</th><th>${t('an.manaAdvice.jointProbability')}</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div data-mana-probability-controls data-size="${state.size}" data-lands="${state.lands}" data-ramp="${state.earlyRamp}">
      <label>${t('an.manaAdvice.reliability')}
        <select data-mana-reliability>
          ${[70, 80, 90].map((value) => `<option value="${value / 100}"${value === 80 ? ' selected' : ''}>${value}%</option>`).join('')}
        </select>
      </label>
      <p data-mana-ramp-target>${rampTargetHtml(state.size, state.lands, state.earlyRamp, 0.8)}</p>
      <p class="hint">${t('an.manaAdvice.targetNote')}</p>
      <h5>${t('an.manaAdvice.openingRequirement')}</h5>
      <label>${t('an.manaAdvice.minimumLands')} <select data-mana-min-lands>${[2, 3, 4].map((value) => `<option value="${value}">${value}</option>`).join('')}</select></label>
      <label>${t('an.manaAdvice.minimumRamp')} <select data-mana-min-ramp>${[0, 1, 2].map((value) => `<option value="${value}"${value === 1 ? ' selected' : ''}>${value}</option>`).join('')}</select></label>
      <p><span>${t('an.manaAdvice.openingChance')}: </span><strong data-mana-joint-target>${percent(jointDrawProbability(state.size, state.lands, state.earlyRamp, 7))}</strong></p>
    </div>
    <details><summary>${t('an.manaAdvice.details')}</summary>
      <p class="hint">${t('an.manaAdvice.assumptions')}</p>
      <p class="hint">${t('an.manaAdvice.empiricalLimit')}</p>
      <p class="hint">${escapeHtml(t('an.manaAdvice.drawCards', { cards: names(state.drawCards) || '—' }))}</p>
      <p class="hint">${escapeHtml(t('an.manaAdvice.rampCards', { cards: names(state.rampCards) || '—' }))}</p>
      <p class="hint">${escapeHtml(t('an.manaAdvice.earlyCards', { cards: names(state.earlyRampCards) || '—' }))}</p>
      <p class="hint"><a href="https://www.peasant-magic.com/articles/magic-deckbuilding/how-many-lands-do-you-need-in-your-deck-an-updated-analysis" target="_blank" rel="noopener noreferrer">${t('an.manaAdvice.source')}</a></p>
    </details>`;
}

// One delegated listener survives deck changes and combo HTML refreshes.
// Keep the selected values on the stable Analyze container across refreshes.
export function wireManaAdviceControls(container) {
  const apply = (root) => {
    const size = Number(root.dataset.size);
    const lands = Number(root.dataset.lands);
    const ramp = Number(root.dataset.ramp);
    const reliability = root.querySelector('[data-mana-reliability]');
    const minLands = root.querySelector('[data-mana-min-lands]');
    const minRamp = root.querySelector('[data-mana-min-ramp]');
    reliability.value = container.dataset.manaPreferenceReliability || '0.8';
    minLands.value = container.dataset.manaPreferenceMinLands || '2';
    minRamp.value = container.dataset.manaPreferenceMinRamp || '1';
    root.querySelector('[data-mana-ramp-target]').innerHTML = rampTargetHtml(size, lands, ramp, Number(reliability.value));
    root.querySelector('[data-mana-joint-target]').textContent = percent(jointDrawProbability(size, lands, ramp, 7, Number(minLands.value), Number(minRamp.value)));
  };
  container.addEventListener('change', (event) => {
    const root = event.target.closest('[data-mana-probability-controls]');
    if (!root) return;
    container.dataset.manaPreferenceReliability = root.querySelector('[data-mana-reliability]').value;
    container.dataset.manaPreferenceMinLands = root.querySelector('[data-mana-min-lands]').value;
    container.dataset.manaPreferenceMinRamp = root.querySelector('[data-mana-min-ramp]').value;
    apply(root);
  });
  return () => {
    const root = container.querySelector('[data-mana-probability-controls]');
    if (root) apply(root);
  };
}
