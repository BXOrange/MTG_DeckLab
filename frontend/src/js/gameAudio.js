// Synthesized tabletop sounds: no downloads, samples or external dependencies.
import { getCookie, setCookie } from './cookies.js';

const PREF_DAYS = 365;
const DEFAULT_VOLUME = 0.3;
const MAX_VOICES = 40; // Bound automatic mana payments and large token battles.
const MIN_GAIN = 0.0001; // Exponential envelopes cannot reach zero.
const MAX_BATCH = 8;
const MAX_DRAW_BRUSHES = 3; // A batch draw gets one short shuffle, not an audio queue.
const ROOM_SECONDS = 0.24; // Small tabletop space; short enough for repeated actions.
const ROOM_LEVEL = 0.07;
const PITCH_VARIATION = 0.008; // Subtle material variation rather than a chorus effect.
const NOISE_FLOOR_HZ = 180; // Keep texture out of the sub-bass.
const randomBetween = (low, high) => low + Math.random() * (high - low);
const COLOR_ORDER = ['W', 'U', 'B', 'R', 'G'];
export const COLOR_VOICES = {
  W: { frequency: 784, wave: 'sine', ratio: 1.5 },
  U: { frequency: 440, wave: 'sine', ratio: 2 },
  B: { frequency: 110, wave: 'triangle', ratio: 1.06 },
  R: { frequency: 196, wave: 'triangle', ratio: 1.5 },
  G: { frequency: 262, wave: 'triangle', ratio: 1.33 },
  C: { frequency: 587, wave: 'sine', ratio: 2.76 },
};
// Each type has its own rhythm, register and material. Colours are a quiet
// trailing accent so a shared mana colour cannot hide the cast gesture.
// Notes: offset, duration, start/end Hz, waveform, gain, noise, attack fraction.
const TYPE_VOICES = {
  creature: [
    [0, 0.19, 170, 78, 'triangle', 0.26],
    [0.008, 0.065, 650, 280, 'sine', 0.32, true],
    [0.065, 0.12, 245, 210, 'sine', 0.1],
  ],
  instant: [
    [0, 0.11, 900, 3900, 'sine', 0.65, true],
    [0.018, 0.085, 1250, 2100, 'sine', 0.12],
    [0.08, 0.045, 2800, 1800, 'sine', 0.09],
  ],
  sorcery: [
    [0, 0.5, 230, 1700, 'sine', 0.5, true, 0.68],
    [0.06, 0.48, 92, 146, 'triangle', 0.2, false, 0.65],
    [0.34, 0.2, 160, 55, 'sine', 0.24],
  ],
  enchantment: [
    [0, 0.55, 660, 660, 'sine', 0.15, false, 0.2],
    [0.13, 0.5, 990, 990, 'sine', 0.12, false, 0.2],
    [0.26, 0.48, 1320, 1320, 'sine', 0.09, false, 0.2],
  ],
  artifact: [
    [0, 0.035, 2500, 1400, 'sine', 0.4, true],
    [0, 0.36, 830, 825, 'sine', 0.2],
    [0.002, 0.24, 1937, 1930, 'sine', 0.11],
    [0.006, 0.13, 3460, 3440, 'sine', 0.07],
  ],
  planeswalker: [
    [0, 0.22, 196, 196, 'triangle', 0.15],
    [0.16, 0.24, 294, 294, 'triangle', 0.16],
    [0.32, 0.42, 392, 392, 'triangle', 0.18],
    [0.32, 0.42, 588, 588, 'sine', 0.09],
  ],
  battle: [
    [0, 0.13, 115, 50, 'triangle', 0.26],
    [0, 0.07, 850, 320, 'sine', 0.4, true],
    [0.18, 0.2, 150, 55, 'triangle', 0.3],
    [0.18, 0.09, 1200, 380, 'sine', 0.45, true],
  ],
  spell: [[0, 0.24, 330, 495, 'sine', 0.15]],
};

export function spellKind(card = {}) {
  const types = (card.type_line || '').split(/[—–]/)[0].toLowerCase();
  // Artifact creatures retain the creature gesture plus a metallic accent.
  return Object.keys(TYPE_VOICES).find((type) => types.includes(type)) || 'spell';
}

export function cardColors(card = {}) {
  // Prefer actual colours when supplied; mana cost is a best-effort fallback
  // for the current board wire format (colour indicators/devoid differ).
  if (Array.isArray(card.colors)) return COLOR_ORDER.filter((c) => card.colors.includes(c));
  return COLOR_ORDER.filter((c) => (card.mana_cost || '').includes(c));
}

export function createGameAudio() {
  let enabled = getCookie('gf_audio_enabled') === '1';
  const stored = getCookie('gf_audio_volume');
  let volume = stored !== null && Number.isFinite(Number(stored))
    ? Math.max(0, Math.min(1, Number(stored))) : DEFAULT_VOLUME;
  let context;
  let master;
  let noise;
  let roomImpulse;
  let room;
  let roomReturn;

  function resetRoom() {
    room?.disconnect();
    roomReturn?.disconnect();
    if (!context) return;
    room = context.createConvolver();
    room.buffer = roomImpulse;
    roomReturn = context.createGain();
    roomReturn.gain.value = ROOM_LEVEL;
    room.connect(roomReturn);
    roomReturn.connect(master);
  }
  const voices = new Set();

  function stop() {
    for (const source of [...voices]) {
      try { source.stop(); } catch { /* Already ended. */ }
    }
    voices.clear();
    resetRoom();
  }

  async function unlock() {
    if (!enabled) return false;
    try {
      if (!context) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return false;
        context = new AudioContext();
        master = context.createGain();
        master.gain.value = volume;
        const limiter = context.createDynamicsCompressor();
        const warmth = context.createBiquadFilter();
        warmth.type = 'lowpass';
        warmth.frequency.value = 5800; // Soften bright transients on small speakers.
        master.connect(warmth);
        warmth.connect(limiter);
        limiter.connect(context.destination);
        noise = context.createBuffer(1, context.sampleRate, context.sampleRate);
        const data = noise.getChannelData(0);
        // Correlated noise gives cloth/air texture instead of digital hiss.
        let previous = 0;
        for (let i = 0; i < data.length; i++) {
          previous = (previous + randomBetween(-0.35, 0.35)) / 1.18;
          data[i] = previous;
        }
        roomImpulse = context.createBuffer(2, Math.ceil(context.sampleRate * ROOM_SECONDS), context.sampleRate);
        for (let channel = 0; channel < roomImpulse.numberOfChannels; channel++) {
          const reflection = roomImpulse.getChannelData(channel);
          let smooth = 0;
          for (let i = 0; i < reflection.length; i++) {
            smooth = (smooth + randomBetween(-1, 1)) / 2;
            const progress = i / reflection.length;
            reflection[i] = smooth * Math.pow(1 - progress, 3);
          }
        }
        resetRoom();
      }
      if (context.state !== 'running') await context.resume();
      return context.state === 'running';
    } catch { return false; } // Audio availability must never interrupt a game.
  }

  function voice(start, duration, frequency, endFrequency, wave, level, noisy = false, attackFraction = null, roomSend = true) {
    if (voices.size >= MAX_VOICES) return;
    const source = noisy ? context.createBufferSource() : context.createOscillator();
    const filter = context.createBiquadFilter();
    filter.type = noisy ? 'bandpass' : 'lowpass';
    filter.Q.value = noisy ? 0.65 : 0.5;
    const cutoff = noisy ? frequency : Math.min(4200, frequency * 5);
    filter.frequency.setValueAtTime(Math.max(NOISE_FLOOR_HZ, cutoff), start);
    filter.frequency.exponentialRampToValueAtTime(Math.max(NOISE_FLOOR_HZ, (noisy ? endFrequency : cutoff * 0.45)), start + duration);
    if (noisy) source.buffer = noise;
    else {
      source.type = wave;
      const variation = randomBetween(1 - PITCH_VARIATION, 1 + PITCH_VARIATION);
      source.frequency.setValueAtTime(frequency * variation, start);
      // Most pitch settling happens at the attack, as with struck material.
      source.frequency.exponentialRampToValueAtTime(endFrequency * variation, start + duration * 0.3);
      source.frequency.exponentialRampToValueAtTime(endFrequency * variation * 0.997, start + duration);
    }
    const envelope = context.createGain();
    envelope.gain.setValueAtTime(MIN_GAIN, start);
    const attack = attackFraction == null
      ? Math.min(noisy ? 0.025 : 0.008, duration / 4) : duration * attackFraction;
    const peak = level * randomBetween(0.9, 1);
    envelope.gain.linearRampToValueAtTime(peak, start + attack);
    envelope.gain.exponentialRampToValueAtTime(Math.max(MIN_GAIN, peak * 0.3), start + attack + (duration - attack) * 0.4);
    envelope.gain.exponentialRampToValueAtTime(MIN_GAIN, start + duration);
    source.connect(filter);
    filter.connect(envelope);
    envelope.connect(master);
    if (roomSend) envelope.connect(room);
    voices.add(source);
    source.onended = () => {
      voices.delete(source);
      source.disconnect();
      filter.disconnect();
      envelope.disconnect();
    };
    if (noisy) source.start(start, randomBetween(0, 0.4));
    else source.start(start);
    source.stop(start + duration + 0.01);
  }

  function play(event) {
    if (!enabled || !context || context.state !== 'running' || document.hidden || volume === 0) return;
    const now = context.currentTime + 0.005;
    const tone = (offset, duration, from, to, wave = 'sine', level = 0.15) =>
      voice(now + offset, duration, from, to, wave, level);
    if (event.kind === 'tap' || event.kind === 'untap') {
      const up = event.kind === 'untap';
      // Dry, single clicks: no brush, sustained pitch or room tail.
      voice(now, 0.014, up ? 4300 : 3100, 1800, 'sine', 0.3, true, 0.08, false);
      voice(now, up ? 0.026 : 0.022, up ? 1480 : 920, up ? 1280 : 760,
        'sine', 0.2, false, 0.04, false);
      return;
    }
    if (event.kind === 'land') {
      // A card settling onto the table: broad soft contact, then low body.
      voice(now, 0.1, 1100, 380, 'sine', 0.36, true, 0.1);
      tone(0.012, 0.19, 185, 105, 'triangle', 0.2);
      tone(0.028, 0.12, 310, 255, 'sine', 0.065);
      return;
    }
    if (event.kind === 'draw') {
      // Sliding paper, followed by a soft edge catching against the hand.
      const count = Math.min(MAX_DRAW_BRUSHES, Math.max(1, Math.floor(event.amount || 1)));
      for (let i = 0; i < count; i++) {
        const offset = i * 0.045;
        voice(now + offset, 0.15, 1900, 700, 'sine', 0.48 / Math.sqrt(count), true, 0.22);
        voice(now + offset + 0.095, 0.035, 2800, 1400, 'sine', 0.2 / Math.sqrt(count), true);
        tone(offset + 0.11, 0.05, 460, 390, 'sine', 0.035);
      }
      return;
    }
    if (event.kind === 'turn_end') {
      // A restrained two-part handoff, distinct from taps and spell chimes.
      tone(0, 0.12, 350, 330, 'sine', 0.14);
      tone(0.13, 0.18, 245, 220, 'sine', 0.12);
      voice(now + 0.045, 0.16, 700, 350, 'sine', 0.16, true);
      return;
    }
    if (event.kind === 'damage') {
      const weight = Math.min(1, Math.log2(1 + Math.max(1, event.amount || 1)) / 5);
      tone(0, 0.18 + weight * 0.15, 95 + weight * 20, 52, 'sine', 0.25);
      tone(0.009, 0.12, 178, 148, 'triangle', 0.08);
      voice(now, 0.16, 550 + weight * 1400, 700, 'sine', 0.38, true);
      return;
    }
    const card = event.card || {};
    if (event.kind === 'cast') {
      for (const [offset, duration, from, to, wave, gain, noisy, attack] of TYPE_VOICES[spellKind(card)]) {
        voice(now + offset, duration, from, to, wave, gain, noisy, attack);
      }
      if (/artifact/i.test(card.type_line || '') && spellKind(card) !== 'artifact') {
        tone(0.025, 0.24, 1510, 1490, 'sine', 0.08);
      }
    } else {
      voice(now, 0.12, 1300, 650, 'sine', 0.2, true);
      tone(0.012, 0.13, 285, 305, 'sine', 0.07);
    }
    const colors = cardColors(card);
    const palette = colors.length ? colors : ['C'];
    palette.forEach((color, i) => {
      const v = COLOR_VOICES[color];
      const offset = (event.kind === 'cast' ? 0.22 : 0.035) + i * 0.027 + randomBetween(0, 0.009);
      const level = (event.kind === 'cast' ? 0.025 : 0.1) / Math.sqrt(palette.length);
      tone(offset, 0.34, v.frequency * 1.012, v.frequency, v.wave, level);
      tone(offset + 0.025, 0.22, v.frequency * v.ratio, v.frequency * v.ratio, 'sine', level / 2);
      // Air, embers and wood body keep colour motifs tactile and distinct.
      const texture = { W: 2800, U: 950, B: 350, R: 2200, G: 650, C: 1900 }[color];
      voice(now + offset, color === 'U' ? 0.3 : 0.16, texture, texture, 'sine', level * 1.4, true);
      if (color === 'R') {
        voice(now + offset + 0.045, 0.035, 3200, 3200, 'sine', level, true);
        voice(now + offset + 0.1, 0.025, 1800, 1800, 'sine', level * 0.7, true);
      }
    });
  }

  return {
    get enabled() { return enabled; },
    get volume() { return volume; },
    unlock, play, stop,
    setEnabled(value) {
      enabled = Boolean(value);
      setCookie('gf_audio_enabled', enabled ? '1' : '0', PREF_DAYS);
      if (!enabled) stop();
      if (master) master.gain.setTargetAtTime(enabled ? volume : 0, context.currentTime, 0.015);
    },
    setVolume(value) {
      if (!Number.isFinite(Number(value))) return;
      volume = Math.max(0, Math.min(1, Number(value)));
      setCookie('gf_audio_volume', String(volume), PREF_DAYS);
      if (master) master.gain.setTargetAtTime(enabled ? volume : 0, context.currentTime, 0.015);
    },
  };
}

// Settings and all game modes share one live audio controller.
let sharedAudio;
export function getGameAudio() {
  return sharedAudio ||= createGameAudio();
}

function visibleCards(view) {
  const state = view?.state || {};
  return [...(state.battlefield || []), ...(state.stack || []).flatMap((i) => [i.object, i.source]),
    ...(state.players || []).flatMap((p) => ['hand', 'graveyard', 'exile', 'command'].flatMap((z) => p[z] || []))]
    .filter((c) => c && typeof c === 'object');
}

// Consume only confirmed server views. No sound on failed clicks, first load,
// reconnect duplicates or undo. A burst is summarized instead of replaying a backlog.
export function gameAudioEvents(previous, next) {
  if (!previous || !next || (next.move_log?.length || 0) <= (previous.move_log?.length || 0)) return [];
  const events = [];
  const previousTurn = previous.state?.internal_turn?.number;
  const nextTurn = next.state?.internal_turn?.number;
  const turnChanged = Number.isFinite(previousTurn) && Number.isFinite(nextTurn)
    ? nextTurn > previousTurn
    : previous.state?.active_player_id && next.state?.active_player_id
      && previous.state.active_player_id !== next.state.active_player_id;
  // Actual turn handoff, including consecutive turns by the same player.
  // Passing priority or arming a yield alone does not end the turn.
  if (turnChanged && !next.state?.game_over) events.push({ kind: 'turn_end' });
  const before = new Map((previous.state?.battlefield || []).map((c) => [c.instance_id, c]));
  let tapped = false;
  let untapped = false;
  for (const card of next.state?.battlefield || []) {
    const old = before.get(card.instance_id);
    if (!old) continue;
    if (!old.tapped && card.tapped) tapped = true;
    if (old.tapped && !card.tapped) untapped = true;
  }
  if (tapped) events.push({ kind: 'tap' });
  if (untapped) events.push({ kind: 'untap' });
  const cards = [...visibleCards(next), ...visibleCards(previous)];
  const oldIds = new Set((previous.table_messages || []).map((m) => m.id));
  for (const message of next.table_messages || []) {
    if (oldIds.has(message.id) || message.kind !== 'action') continue;
    const kind = message.action === 'play_land' ? 'land'
      : message.action === 'cast_spell' ? 'cast'
      : ['activate_ability', 'activate_hand_mana'].includes(message.action) ? 'activate' : null;
    if (!kind) continue;
    // Never resolve an unnamed/face-down card using a hidden-zone cache.
    const card = message.card_name ? cards.find((c) => c.name === message.card_name) : null;
    events.push({ kind, card: card || {} });
  }
  const oldTimeline = previous.state?.stats?.timeline || [];
  const added = (next.state?.stats?.timeline || []).slice(oldTimeline.length);
  const draws = added.filter((r) => r.kind === 'draw').reduce((sum, r) => sum + r.amount, 0);
  if (draws > 0) events.push({ kind: 'draw', amount: draws });
  const damage = added.filter((r) => r.kind === 'damage_dealt').reduce((sum, r) => sum + r.amount, 0);
  if (damage > 0) events.push({ kind: 'damage', amount: damage });
  // Damage has priority even when many spells were cast in one bot update.
  return events.length <= MAX_BATCH ? events : [...events.slice(0, MAX_BATCH - 1), events.at(-1)];
}
