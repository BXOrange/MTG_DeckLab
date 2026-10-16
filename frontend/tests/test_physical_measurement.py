"""Shared-board factual-input UI fixture; backend measurement flow tested separately."""
import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('MTG_CACHE_DIR', str(ROOT / 'backend' / 'cache' / 'test'))
from playwright.sync_api import sync_playwright
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.game_session import GameSession


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class PhysicalMeasurementUiTest(unittest.TestCase):
    def test_strict_fact_input_keyboard_submit_busy_and_escaped_printing(self):
        engine = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
        view = GameSession(engine, require_setup=False).view()
        view['state']['pending_choice'] = {
            'kind': 'physical_property_measurement', 'property': 'printed_rules_lines',
            'player_id': 'p1', 'minimum': 0, 'maximum': 12,
            'subject': {'printing_id': 'exact-printing', 'face': 'back',
                        'printing_label': 'Unsanctioned · 19/96',
                        'name': '<img onerror="window.injected=true">', 'image_url': '/printing.png'},
        }
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1100})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/measurement-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
                    '<body><main id="board"></main></body></html>'))
                page.route('**/printing.png', lambda route: route.fulfill(content_type='image/svg+xml', body=
                    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="420"><text x="10" y="25">Exact printing</text></svg>'))
                page.goto(f'http://127.0.0.1:{server.server_port}/measurement-test')
                page.evaluate('''async view => {
                    const {createGameBoardView} = await import('/src/js/gameBoardView.js');
                    window.actions = [];
                    const board = createGameBoardView({allowRewind:false, transport:{sendAction: action => {
                        window.actions.push(action);
                        return new Promise(resolve => {window.finishAction = () => resolve({ok:false, error:'Fixture rejection'});});
                    }}});
                    window.measurementBoard = board;
                    window.measurementView = view;
                    board.mount(document.getElementById('board'));
                    board.start('measurement-ui-fixture', view);
                }''', view)
                field = page.locator('[data-measurement-value]')
                submit = page.locator('[data-measurement-submit]')
                self.assertEqual(field.input_value(), '')
                self.assertTrue(submit.is_disabled())
                for invalid in ('-1', '1.5', '1e1', '13', '9007199254740992', ' 4 ', '+4'):
                    field.fill(invalid)
                    self.assertTrue(submit.is_disabled(), invalid)
                field.fill('0')
                self.assertTrue(submit.is_enabled())
                field.press('Enter')
                page.wait_for_function('window.actions.length === 1')
                self.assertEqual(page.evaluate('window.actions'), [{'type': 'choose', 'option_id': '0'}])
                self.assertTrue(field.is_disabled())
                page.evaluate("document.querySelector('[data-physical-measurement]').requestSubmit()")
                self.assertEqual(page.evaluate('window.actions.length'), 1)
                page.evaluate('window.finishAction()')
                page.wait_for_function("!document.querySelector('[data-measurement-value]').disabled")
                self.assertEqual(field.input_value(), '0')
                field.fill('12')
                self.assertTrue(submit.is_enabled())
                field.fill('0004')
                submit.click()
                page.wait_for_function('window.actions.length === 2')
                self.assertEqual(page.evaluate('window.actions[1].option_id'), '4')
                self.assertFalse(page.evaluate('window.injected || false'))
                self.assertEqual(page.locator('[data-physical-measurement] img').count(), 1)
                self.assertIn('Unsanctioned · 19/96', page.locator('[data-physical-measurement]').inner_text())
                self.assertNotIn('exact-printing', page.locator('[data-physical-measurement]').inner_text())
                self.assertIn('back', page.locator('[data-physical-measurement]').inner_text())
                page.evaluate('window.finishAction()')
                page.wait_for_function("!document.querySelector('[data-measurement-value]').disabled")
                page.screenshot(path='/tmp/mec123-measurement-ui.png', full_page=True, animations='disabled')
                page.evaluate('''() => {
                    delete window.measurementView.state.pending_choice.subject.printing_label;
                    window.measurementBoard.refresh(window.measurementView);
                }''')
                self.assertEqual(field.input_value(), '0004')
                self.assertNotIn('exact-printing', page.locator('[data-physical-measurement]').inner_text())
                self.assertIn('back', page.locator('[data-physical-measurement]').inner_text())
                page.evaluate('''() => {
                    window.measurementView.state.pending_choice.subject.printing_id = 'different-internal-id';
                    window.measurementBoard.refresh(window.measurementView);
                }''')
                self.assertEqual(field.input_value(), '')
                self.assertNotIn('different-internal-id', page.locator('[data-physical-measurement]').inner_text())
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
