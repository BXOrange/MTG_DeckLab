import { getCookie, setCookie } from './cookies.js';

export const BOARD_LAYOUT_MODES = ['banner-inside', 'banner-outside', 'battlefield-inside', 'battlefield-outside'];

export function getBoardLayout() {
  return {
    moreBattlefield: getCookie('gf_board_layout') !== 'banner',
    zonesInside: getCookie('gf_zones_pod') === 'inside',
  };
}

export function setBoardLayout(mode) {
  if (!BOARD_LAYOUT_MODES.includes(mode)) return;
  const [layout, zones] = mode.split('-');
  setCookie('gf_board_layout', layout, 365);
  setCookie('gf_zones_pod', zones, 365);
  window.dispatchEvent(new Event('board-layout-changed'));
}
