// English UI catalog (reference / default language). See i18n.js.
//
// Rules:
//   * Keys are namespaced dotted strings. de.js MUST have the identical key
//     set (frontend/scripts/i18n-verify.mjs enforces this).
//   * A value is either a string or a plural object { one, other } (used via
//     tPlural). `{token}` placeholders are interpolated from params.
//   * NO HTML tags in values — interpolate data, never concatenate markup.
//     Where the German original wrapped markup around text, the text is split
//     into several keys around the tags at the call site.

// Focused catalogs are merged here to keep the public import stable.
import interfaceCatalog from './en/interface.js';
import analysisCatalog from './en/analysis.js';
import boardCatalog from './en/board.js';
import play_modesCatalog from './en/play-modes.js';

export default {
  ...interfaceCatalog,
  ...analysisCatalog,
  ...boardCatalog,
  ...play_modesCatalog,
};
