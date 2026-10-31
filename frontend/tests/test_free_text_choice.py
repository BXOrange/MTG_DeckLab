"""PAR-203: a choice whose answer space is not enumerable (a card name, a creature type) offers a typed answer."""
import sys
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from playwright.sync_api import sync_playwright
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.game_session import GameSession
from test_cross_player_attachments import QuietHandler


def _view(free_text):
    engine = GameEngine.new_game([('p1', 'Human', []), ('p2', 'Bot', [])], starting_hand=0)
    session = GameSession(engine, require_setup=False)
    choice = {'kind': 'choose_for_source', 'player_id': 'p1', 'prompt': 'Choose a card name', 'what': 'card_name',
              'source_id': 1, 'options': [{'id': 'Fireball', 'label': 'Fireball'}]}
    if free_text:
        choice['free_text'] = True
    engine.rules.open_choice(choice)
    return session.view(perspective='p1')


class FreeTextChoiceTest(unittest.TestCase):
    def _render(self, page, server, view):
        page.route('**/free-text-test', lambda route: route.fulfill(
            content_type='text/html', body='<html><body><main id="board"></main></body></html>'))
        page.goto(f'http://127.0.0.1:{server.server_port}/free-text-test')
        page.evaluate('''async view => {
            const {createGameBoardView} = await import('/src/js/gameBoardView.js');
            window.actions = [];
            window.__view = view;
            window.board = createGameBoardView({transport:{sendAction: action => {
                actions.push(action);
                return new Promise(() => {});
            }}});
            board.mount(document.getElementById('board'));
            board.start('free-text-test', view);
        }''', view)

    def test_typed_answer_is_sent_as_the_option_id_and_survives_a_repaint(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                self._render(page, server, _view(True))
                self.assertEqual(page.locator('[data-choice-text-value]').count(), 1)
                submit = page.locator('[data-choice-text-submit]')
                self.assertTrue(submit.is_disabled())  # nothing typed yet
                page.fill('[data-choice-text-value]', 'Lightning Bolt')
                self.assertFalse(submit.is_disabled())
                # a repaint (a polled view) keeps what was typed
                page.evaluate('() => board.refresh(structuredClone(window.__view))')
                self.assertEqual(page.input_value('[data-choice-text-value]'), 'Lightning Bolt')
                submit.click()
                self.assertEqual(page.evaluate('actions'),
                                 [{'type': 'choose', 'free_text': True, 'option_id': 'Lightning Bolt'}])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_a_plain_choice_has_no_text_field(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                self._render(page, server, _view(False))
                self.assertEqual(page.locator('[data-choice-text-value]').count(), 0)
                self.assertEqual(page.locator('.gf-choice-options button').count(), 1)
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
