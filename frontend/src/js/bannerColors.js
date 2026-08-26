// Banner colours: the palette a multiplayer seat flies on its board title bar.
//
// A banner colour is a *set* of the five MTG colours — any subset, so a
// seat can fly its deck's whole colour identity — or none of them, which is
// the grey "colourless" banner. Backend side that's `Seat.banner_color`
// (`services/lobby.py`'s `normalize_banner_color`), stored as the letters in
// WUBRG order: `"wu"`, `"bg"`, `"wubrg"`, `"c"`.
//
// The 32 combinations are **derived, not enumerated**: two hexes per colour
// (a deep one for the banner itself and a bright one for the hairline strip
// on top of it) and a gradient across whichever ones are picked. That's why
// there is no CSS class per combination — `bannerStyle()` hands the two
// gradients to CSS as custom properties, and one rule in main.css draws
// every banner there can be.
//
// The hues are the app's existing colour-pip pastels (`.color-pip--*` in
// main.css, used for deck colour identity in the saved-decks list) taken
// down to the dark theme's lightness, so a Simic banner and a Simic pip
// read as the same green-blue rather than as two unrelated palettes. The
// deep ones are all dark enough to carry the board's near-white banner
// text at 5:1 or better — white is the palest hue and therefore the one
// that sets that floor (which is why its "deep" is a dark khaki).

/** WUBRG order — every key, label and gradient below is built from this. */
export const BANNER_COLORS = [
  { code: 'w', label: 'Weiß', symbol: 'W', deep: '#6f6849', bright: '#f8f6d8' },
  { code: 'u', label: 'Blau', symbol: 'U', deep: '#2f5f80', bright: '#aee0fa' },
  { code: 'b', label: 'Schwarz', symbol: 'B', deep: '#4c453f', bright: '#b7aca4' },
  { code: 'r', label: 'Rot', symbol: 'R', deep: '#8a463a', bright: '#f9aa8f' },
  { code: 'g', label: 'Grün', symbol: 'G', deep: '#3d6d51', bright: '#9bd3ae' },
];

/** The grey banner: a colourless deck, i.e. none of the five picked. */
export const COLORLESS_BANNER = 'c';
const COLORLESS = { code: 'c', label: 'Farblos', symbol: 'C', deep: '#4e535c', bright: '#d8d8d8' };

const BY_CODE = new Map([...BANNER_COLORS, COLORLESS].map((c) => [c.code, c]));

// Guild/shard/wedge names, so a banner reads as "Azorius" rather than as two
// letters. Only the two- and three-colour combinations have names players
// actually use; four and five colours fall back to a plain count below.
const COMBO_NAMES = {
  wu: 'Azorius', ub: 'Dimir', br: 'Rakdos', rg: 'Gruul', wg: 'Selesnya',
  wb: 'Orzhov', ur: 'Izzet', bg: 'Golgari', wr: 'Boros', ug: 'Simic',
  wub: 'Esper', ubr: 'Grixis', brg: 'Jund', wrg: 'Naya', wbg: 'Abzan',
  wur: 'Jeskai', ubg: 'Sultai', wbr: 'Mardu', urg: 'Temur',
};

/**
 * Canonicalize a banner key, mirroring `normalize_banner_color` on the
 * server so both ends agree on what "the same colours" means.
 * @returns {string} WUBRG-ordered letters, or `'c'` for colourless.
 */
export function normalizeBannerColor(value) {
  const letters = new Set(String(value ?? '').toLowerCase().split(''));
  const picked = BANNER_COLORS.filter((c) => letters.has(c.code)).map((c) => c.code);
  return picked.length ? picked.join('') : COLORLESS_BANNER;
}

/** The colour records a key is made of (`[COLORLESS]` for the grey banner). */
export function bannerColorsOf(key) {
  const normalized = normalizeBannerColor(key);
  if (normalized === COLORLESS_BANNER) return [COLORLESS];
  return normalized.split('').map((code) => BY_CODE.get(code));
}

/** A human label: "Azorius (WU)", "Grün", "Farblos", "Fünf Farben". */
export function bannerColorLabel(key) {
  const normalized = normalizeBannerColor(key);
  const colors = bannerColorsOf(normalized);
  const symbols = colors.map((c) => c.symbol).join('');
  if (colors.length === 1) return `${colors[0].label} (${symbols})`;
  const name = COMBO_NAMES[normalized] || (normalized.length === 5 ? 'Fünf Farben' : 'Vier Farben');
  return `${name} (${symbols})`;
}

/**
 * The two gradients a banner is painted with, as CSS values.
 *
 * A single colour still gets a gradient — from the colour to a slightly
 * darker copy of itself — so one-, two- and five-colour banners all have
 * the same soft left-to-right sheen instead of one of them looking flat.
 */
export function bannerGradients(key) {
  const colors = bannerColorsOf(key);
  const stops = colors.length > 1 ? colors : [colors[0], { ...colors[0], deep: shade(colors[0].deep, -0.22), bright: shade(colors[0].bright, -0.14) }];
  return {
    background: `linear-gradient(100deg, ${stops.map((c) => c.deep).join(', ')})`,
    strip: `linear-gradient(100deg, ${stops.map((c) => c.bright).join(', ')})`,
  };
}

/**
 * A `style="…"` attribute body handing those gradients to CSS, or `''` for a
 * seat that has no banner colour at all — which leaves the board's own felt
 * header exactly as it was before any of this existed.
 */
export function bannerStyle(key) {
  if (key == null || key === '') return '';
  const { background, strip } = bannerGradients(key);
  return `--banner-bg: ${background}; --banner-strip: ${strip};`;
}

/** A deck's `colorIdentity` (`['W','U']`, `[]`) as a banner key. */
export function bannerColorForIdentity(colorIdentity) {
  if (!colorIdentity) return null;
  return normalizeBannerColor(colorIdentity.join(''));
}

/** Darken (`amount < 0`) or lighten a `#rrggbb` by a fraction of full scale. */
function shade(hex, amount) {
  const n = parseInt(hex.slice(1), 16);
  const channels = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) =>
    Math.max(0, Math.min(255, Math.round(v + amount * 255))),
  );
  return `#${channels.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}
