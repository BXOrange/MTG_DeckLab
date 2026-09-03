#!/usr/bin/env node
// Read-only i18n consistency check. Run manually:
//
//   node frontend/scripts/i18n-verify.mjs
//
// Reports, exits non-zero if (a) or (c) find problems:
//   (a) key-set drift between locales/en.js and locales/de.js, and plural
//       shape mismatches ({one,other} vs string)
//   (b) still-inline German string literals in frontend/src/js/**/*.js and
//       frontend/index.html (heuristic — a stop-word list), as file:line
//   (c) t('…') / tPlural('…') calls whose literal key is in neither catalog
//   (d) alert(…) / confirm(…) calls with a string-literal argument
//
// Writes nothing.

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const JS_DIR = join(ROOT, 'src', 'js');
const LOCALES = join(JS_DIR, 'locales');

// --- load catalogs ---------------------------------------------------------
async function loadCatalog(name) {
  const mod = await import(join(LOCALES, name));
  return mod.default;
}

const en = await loadCatalog('en.js');
const de = await loadCatalog('de.js');

let hardFail = false;

// (a) key-set + plural shape ---------------------------------------------
const enKeys = new Set(Object.keys(en));
const deKeys = new Set(Object.keys(de));
const missingInDe = [...enKeys].filter((k) => !deKeys.has(k));
const missingInEn = [...deKeys].filter((k) => !enKeys.has(k));
if (missingInDe.length) {
  hardFail = true;
  console.error(`\n[a] ${missingInDe.length} key(s) in en.js missing from de.js:`);
  missingInDe.forEach((k) => console.error(`    ${k}`));
}
if (missingInEn.length) {
  hardFail = true;
  console.error(`\n[a] ${missingInEn.length} key(s) in de.js missing from en.js:`);
  missingInEn.forEach((k) => console.error(`    ${k}`));
}
const shapeMismatch = [...enKeys]
  .filter((k) => deKeys.has(k))
  .filter((k) => {
    const ep = en[k] && typeof en[k] === 'object';
    const dp = de[k] && typeof de[k] === 'object';
    return ep !== dp;
  });
if (shapeMismatch.length) {
  hardFail = true;
  console.error(`\n[a] ${shapeMismatch.length} key(s) with plural/string shape mismatch:`);
  shapeMismatch.forEach((k) => console.error(`    ${k}`));
}
if (!missingInDe.length && !missingInEn.length && !shapeMismatch.length) {
  console.log(`[a] OK — ${enKeys.size} keys, en/de in sync, plural shapes match.`);
}

const allKeys = new Set([...enKeys, ...deKeys]);

// --- walk source files -------------------------------------------------
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const p = join(dir, entry);
    const st = statSync(p);
    if (st.isDirectory()) out.push(...walk(p));
    else if (entry.endsWith('.js')) out.push(p);
  }
  return out;
}
const sourceFiles = walk(JS_DIR).filter((p) => !p.startsWith(LOCALES));
sourceFiles.push(join(ROOT, 'index.html'));

// (b) inline German heuristic -----------------------------------------
// Words that are strong German markers and unlikely to appear in an
// identifier or English sentence. Umlauts alone already catch a lot.
const GERMAN_STOPWORDS = [
  'ä', 'ö', 'ü', 'ß',
  ' der ', ' die ', ' das ', ' und ', ' oder ', ' nicht ', ' mit ', ' für ',
  ' ein ', ' eine ', ' kein ', ' wird ', ' sind ', ' wählen', ' Karte', ' Karten',
  ' Deck ', ' Zug ', ' Züge', ' Hand', ' Spiel', ' Spieler', ' Fehler', ' laden',
  ' Regel ', 'erreichbar', 'Verbindung', 'Einstellung', 'gespeichert', 'löschen',
  'Abbrechen', 'Schließen', 'Hochladen', 'Zurück', 'Weiter',
];
const STRING_LITERAL = /(['"`])((?:\\.|(?!\1)[^\\])*)\1/g;
let inlineHits = 0;
for (const file of sourceFiles) {
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) return;
    let m;
    STRING_LITERAL.lastIndex = 0;
    while ((m = STRING_LITERAL.exec(line))) {
      const lit = m[2];
      const low = ` ${lit} `.toLowerCase();
      if (GERMAN_STOPWORDS.some((w) => low.includes(w.toLowerCase()))) {
        inlineHits += 1;
        console.log(`[b] ${relative(ROOT, file)}:${i + 1}  ${lit.slice(0, 80)}`);
        break;
      }
    }
  });
}
console.log(`[b] ${inlineHits} candidate inline German literal line(s).`);

// (c) unknown t() keys ----------------------------------------------
const T_CALL = /\bt(?:Plural)?\(\s*(['"])((?:\\.|(?!\1)[^\\])*)\1/g;
let unknownKeys = 0;
for (const file of sourceFiles) {
  if (file.endsWith('index.html')) continue;
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    let m;
    T_CALL.lastIndex = 0;
    while ((m = T_CALL.exec(line))) {
      const key = m[2];
      if (!allKeys.has(key)) {
        unknownKeys += 1;
        hardFail = true;
        console.error(`[c] ${relative(ROOT, file)}:${i + 1}  unknown key: ${key}`);
      }
    }
  });
}
if (!unknownKeys) console.log('[c] OK — every t()/tPlural() key exists in a catalog.');

// (d) literal alert/confirm ---------------------------------------
const ALERT_LIT = /\b(?:window\.)?(alert|confirm)\(\s*(['"`])/g;
let alertHits = 0;
for (const file of sourceFiles) {
  if (file.endsWith('index.html')) continue;
  const text = readFileSync(file, 'utf8');
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    ALERT_LIT.lastIndex = 0;
    if (ALERT_LIT.test(line)) {
      alertHits += 1;
      console.log(`[d] ${relative(ROOT, file)}:${i + 1}  ${line.trim().slice(0, 90)}`);
    }
  });
}
console.log(`[d] ${alertHits} alert()/confirm() call(s) with a string-literal argument.`);

process.exit(hardFail ? 1 : 0);
