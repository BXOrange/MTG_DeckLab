import { getCookie, setCookie } from './cookies.js';

const THEME_COOKIE = 'mtg_visual_theme';
const COOKIE_MAX_AGE_DAYS = 365;
const SUPPORTED = ['white', 'blue', 'black', 'red', 'green'];

export const VISUAL_THEMES = [
  { code: 'white', labelKey: 'settings.theme.white' },
  { code: 'blue', labelKey: 'settings.theme.blue' },
  { code: 'black', labelKey: 'settings.theme.black' },
  { code: 'red', labelKey: 'settings.theme.red' },
  { code: 'green', labelKey: 'settings.theme.green' },
];

function normalize(theme) {
  return SUPPORTED.includes(theme) ? theme : 'green';
}

let currentTheme = normalize(getCookie(THEME_COOKIE));

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

applyTheme(currentTheme);

export function getVisualTheme() {
  return currentTheme;
}

export function setVisualTheme(theme) {
  currentTheme = normalize(theme);
  setCookie(THEME_COOKIE, currentTheme, COOKIE_MAX_AGE_DAYS);
  applyTheme(currentTheme);
  return currentTheme;
}
