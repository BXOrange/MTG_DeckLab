import { getState } from '../state.js';
import { cardImageUrl, sendGameAction } from '../api.js';

const TABLE_EMOTES = ['👍', '👏', 'GG', '🤔', '⏳'];
const EMOJI_CATEGORIES = [
  { key: 'faces', icon: '😀', emoji: '😀 😃 😄 😁 😆 😅 😂 🤣 😊 🙂 🙃 😉 😍 🥰 😘 😎 🤓 🧐 🤔 🤨 😐 😑 🙄 😏 😴 🤯 🥳 😇 😈 😬 😱 😭 😢 😤 😡 🤬 🥺 🫡 🤗 🤫 🤭 🫠 🫢 🫣 🤩 😋 🤤 🤮 🤒 🥶 🥵 💀 👻 👽 🤖 💩'.split(' ') },
  { key: 'gestures', icon: '👋', emoji: '👋 🤚 ✋ 🖐️ 🖖 👌 🤌 🤏 ✌️ 🤞 🤟 🤘 🤙 👈 👉 👆 👇 ☝️ 👍 👎 ✊ 👊 🤛 🤜 👏 🙌 👐 🤲 🤝 🙏 💪 🦾 🫶 🫵 ✍️ 👀 🧠 👑 🧙 🧝 🧛 🧟 🧚 🦸 🦹 👩‍💻 👨‍💻 👩‍🚀 👨‍🚀'.split(' ') },
  { key: 'nature', icon: '🐱', emoji: '🐶 🐱 🐭 🐹 🐰 🦊 🐻 🐼 🐨 🐯 🦁 🐮 🐷 🐸 🐵 🐔 🐧 🦉 🦇 🐺 🐗 🐴 🦄 🐝 🦋 🐌 🐞 🦂 🕷️ 🐢 🐍 🦎 🐉 🐲 🦖 🦕 🐙 🦑 🦀 🐠 🦈 🐬 🐳 🌵 🌲 🌳 🌴 🌱 🍀 🍄 🌹 🌻 🌞 🌙 ⭐ 🌈 🔥 💧 ❄️ ⚡ 🌪️'.split(' ') },
  { key: 'food', icon: '🍕', emoji: '🍏 🍎 🍐 🍊 🍋 🍌 🍉 🍇 🍓 🫐 🍒 🍑 🥭 🍍 🥝 🥑 🥦 🥕 🌽 🌶️ 🥔 🍞 🥐 🥨 🧀 🍳 🥞 🥓 🍔 🍟 🍕 🌭 🌮 🌯 🍜 🍣 🍙 🍤 🍦 🍩 🍪 🎂 🍰 🍫 🍿 ☕ 🍵 🧋 🍺 🍻 🥂 🍷 🧃 🥤'.split(' ') },
  { key: 'objects', icon: '🎲', emoji: '🎲 🃏 🎴 ♟️ 🎯 🏆 🥇 🎮 🕹️ 🎭 🎨 🎸 🎵 🎶 🎧 🎤 🎬 📷 📱 💻 💡 🔦 🕯️ 📚 📖 📜 ✉️ 📦 🎁 🎈 🎉 🎊 🪄 🔮 🧿 💎 💰 🪙 ⚔️ 🛡️ 🏹 🪓 🔨 🔧 ⚙️ 🧪 ⚗️ 🧬 💣 🧨 🚀 🛸 🏰 🏔️ 🗺️ ⛵ ✈️ 🏎️ ⏳ ⌛ ⏰'.split(' ') },
  { key: 'symbols', icon: '❤️', emoji: '❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🤎 🩷 🩵 🩶 💔 ❤️‍🔥 💕 💞 💓 💗 💖 💘 💝 💯 💢 💥 💫 💦 💤 ✅ ❌ ❎ ❗ ❓ 🛑 🚸 ⚠️ 🚫 ⛔ 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪ 🟤 🔺 🔻 🔶 🔷 ✨ ♻️ ♾️ ⚔️ 🏳️ 🏴 🏳️‍🌈 🇩🇪 🇦🇹 🇨🇭 🇺🇸 🇬🇧 🇫🇷 🇪🇸 🇮🇹 🇯🇵 🇨🇦 🇧🇷 🇦🇺'.split(' ') },
];

export function createBoardChat({
  getView,
  getSessionId,
  getTransport,
  getRoot,
  applyView,
  render,
  resolveImageUrl,
  t,
  escapeHtml,
  escapeAttr,
  renderOracleText,
}) {
  let chatSending = false;
  let chatError = '';
  let customEmojiOpen = false;
  let emojiCategory = EMOJI_CATEGORIES[0].key;
  let revealItems = [];
  let lastRevealId = 0;
  let revealAside = true;

  function resetSession() {
    chatError = '';
    customEmojiOpen = false;
    emojiCategory = EMOJI_CATEGORIES[0].key;
    revealItems = [];
    lastRevealId = 0;
    revealAside = true;
  }

  function updateRevealPopup(data) {
    const messages = (data.table_messages || []).filter(message => message.action === 'reveal');
    const available = new Set(messages.map(message => message.id));
    revealItems = revealItems.filter(message => available.has(message.id));
    const fresh = messages.filter(message => message.id > lastRevealId);
    if (fresh.length) {
      revealItems.push(...fresh);
      lastRevealId = Math.max(lastRevealId, ...fresh.map(message => message.id));
      revealAside = true;
    }
  }

  function revealPopupHtml() {
    if (!revealItems.length) return '';
    return `<div class="gf-modal-overlay gf-revealed-modal${revealAside ? ' aside' : ''}">
      <section class="gf-modal" role="dialog" aria-modal="${!revealAside}" aria-label="${escapeAttr(t('bd.reveal.heading'))}" tabindex="-1">
        <div class="gf-modal-head"><div><h4>${escapeHtml(t('bd.reveal.heading'))}</h4></div>
          <button type="button" class="gf-modal-aside" data-reveal-aside>${escapeHtml(t(revealAside ? 'bd.choice.asideShow' : 'bd.choice.asidePush'))}</button>
          <button type="button" data-reveal-close aria-label="${escapeAttr(t('bd.reveal.close'))}">×</button>
        </div>
        <ul class="gf-revealed-list">${revealItems.map(message => {
          const card = message.revealed_card || { name: message.card_name, card_id: message.card_id };
          const image = resolveImageUrl(card, getState().imageCache);
          return `<li><span>${escapeHtml(message.author)}</span><strong data-hover-card="${escapeAttr(card.name || '')}">${escapeHtml(card.name || '')}</strong>
            ${image ? `<img src="${escapeAttr(image)}" alt="${escapeAttr(card.name || '')}" loading="lazy" data-hover-card="${escapeAttr(card.name || '')}" />` : ''}</li>`;
        }).join('')}</ul>
      </section></div>`;
  }

  function chatPanelHtml() {
    const view = getView();
    const messages = (view.table_messages || []).map((message) => {
      const card = message.card_name || t('bd.chat.faceDownSpell');
      const text = message.kind === 'emote' ? message.text
        : t(`bd.chat.${message.action}`, { card, cost: message.cost_label || '' }) + (message.ability_text ? ` ${message.ability_text}` : '');
      const reveal = message.action === 'reveal' && message.card_id
        ? `<img class="gf-chat-reveal" src="${escapeAttr(cardImageUrl(message.card_id))}" alt="${escapeAttr(card)}" data-hover-card="${escapeAttr(card)}" loading="lazy">`
        : '';
      return `<li class="gf-chat-message ${message.kind === 'emote' ? 'is-chat' : 'is-announcement'}" data-message-id="${escapeAttr(message.id)}">`
        + `<span class="gf-chat-author">${escapeHtml(message.author)}</span>`
        + `<span>${renderOracleText(text)}</span>`
        + (message.action === 'reveal' ? `<button type="button" data-reveal-open="${message.id}" aria-label="${escapeAttr(t('bd.reveal.heading'))}">👁</button>` : '')
        + reveal
        + '</li>';
    }).join('');
    return `<section class="gf-chat" aria-label="${escapeAttr(t('bd.chat.heading'))}">
      <h4>${escapeHtml(t('bd.chat.heading'))}</h4>
      <ol class="gf-chat-messages" role="log" aria-live="polite" aria-relevant="additions" tabindex="0">
        ${messages || `<li class="hint">${escapeHtml(t('bd.chat.empty'))}</li>`}
      </ol>
      ${view.observer ? '' : `<div class="gf-chat-emotes">${TABLE_EMOTES.map((text, index) => `<button type="button" data-chat-emote="${escapeAttr(text)}" title="${escapeAttr(t(`bd.chat.emote${index}`))}" aria-label="${escapeAttr(t(`bd.chat.emote${index}`))}" ${chatSending ? 'disabled' : ''}>${escapeHtml(text)}</button>`).join('')}<button type="button" data-chat-custom aria-expanded="${customEmojiOpen}" title="${escapeAttr(t('bd.chat.custom'))}" aria-label="${escapeAttr(t('bd.chat.custom'))}">☺️＋</button></div>
      ${customEmojiOpen ? emojiPickerHtml() : ''}`}
      ${chatError ? `<p class="gf-chat-error" role="alert">${escapeHtml(chatError)}</p>` : ''}
    </section>`;
  }

  function emojiPickerHtml() {
    const selected = EMOJI_CATEGORIES.find(category => category.key === emojiCategory) || EMOJI_CATEGORIES[0];
    return `<section class="gf-emoji-picker" aria-label="${escapeAttr(t('bd.chat.custom'))}">
      <div class="gf-emoji-categories" aria-label="${escapeAttr(t('bd.chat.categories'))}">${EMOJI_CATEGORIES.map(category =>
        `<button type="button" data-emoji-category="${category.key}" aria-pressed="${category.key === selected.key}" title="${escapeAttr(t(`bd.chat.category.${category.key}`))}" aria-label="${escapeAttr(t(`bd.chat.category.${category.key}`))}">${category.icon}</button>`
      ).join('')}</div>
      <h5>${escapeHtml(t(`bd.chat.category.${selected.key}`))}</h5>
      <div class="gf-emoji-grid">${selected.emoji.map(emoji => `<button type="button" data-chat-emote="${escapeAttr(emoji)}" aria-label="${escapeAttr(t('bd.chat.sendEmoji', { emoji }))}" ${chatSending ? 'disabled' : ''}>${emoji}</button>`).join('')}</div>
    </section>`;
  }

  async function sendChat(emote) {
    const sessionId = getSessionId();
    if (!sessionId || chatSending || typeof emote !== 'string' || !emote.trim()) return;
    chatSending = true;
    chatError = '';
    render();
    try {
      const action = { type: 'emote', emote };
      const transport = getTransport();
      const res = transport.sendAction ? await transport.sendAction(action)
        : await sendGameAction(sessionId, action);
      if (res.ok) {
        customEmojiOpen = false;
        if (res.data) applyView(res.data);
      } else {
        chatError = t('bd.chat.failed');
      }
    } finally {
      chatSending = false;
      render();
    }
  }

  function wireEvents() {
    const root = getRoot();
    root.querySelector('[data-chat-custom]')?.addEventListener('click', () => {
      customEmojiOpen = !customEmojiOpen;
      render();
      getRoot().querySelector('.gf-emoji-categories button')?.focus();
    });
    root.querySelectorAll('[data-emoji-category]').forEach((button) => {
      button.addEventListener('click', () => {
        emojiCategory = button.dataset.emojiCategory;
        render();
        getRoot().querySelector(`[data-emoji-category="${emojiCategory}"]`)?.focus();
      });
    });
    root.querySelector('.gf-emoji-picker')?.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        customEmojiOpen = false;
        render();
        getRoot().querySelector('[data-chat-custom]')?.focus();
      }
    });
    root.querySelectorAll('[data-chat-emote]').forEach((button) => {
      button.addEventListener('click', () => sendChat(button.dataset.chatEmote));
    });

    const closeReveal = () => {
      revealItems = [];
      render();
    };
    root.querySelector('[data-reveal-close]')?.addEventListener('click', closeReveal);
    root.querySelector('[data-reveal-aside]')?.addEventListener('click', () => {
      revealAside = !revealAside;
      render();
      getRoot().querySelector('.gf-revealed-modal .gf-modal')?.focus();
    });
    root.querySelector('.gf-revealed-modal')?.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { event.stopPropagation(); closeReveal(); }
    });
    root.querySelectorAll('[data-reveal-open]').forEach((button) => button.addEventListener('click', () => {
      const message = (getView().table_messages || []).find(item => item.id === Number(button.dataset.revealOpen));
      if (!message) return;
      revealItems = [message];
      revealAside = true;
      render();
      getRoot().querySelector('.gf-revealed-modal .gf-modal')?.focus();
    }));
  }

  return {
    chatPanelHtml,
    resetSession,
    revealPopupHtml,
    sendChat,
    updateRevealPopup,
    wireEvents,
  };
}
