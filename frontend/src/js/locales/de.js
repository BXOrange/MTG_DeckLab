// German UI catalog. MUST have the identical key set as en.js
// (frontend/scripts/i18n-verify.mjs enforces this). Same value rules as
// en.js — see its header.

// Focused catalogs are merged here to keep the public import stable.
import interfaceCatalog from './de/interface.js';
import analysisCatalog from './de/analysis.js';
import boardCatalog from './de/board.js';
import play_modesCatalog from './de/play-modes.js';

export default {
  ...interfaceCatalog,
  ...analysisCatalog,
  ...boardCatalog,
  ...play_modesCatalog,
};
