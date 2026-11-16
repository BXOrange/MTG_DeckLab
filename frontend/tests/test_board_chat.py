"""Shared board chat and reveal interactions."""
import sys
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from playwright.sync_api import sync_playwright
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.game_session import GameSession


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class BoardChatTest(unittest.TestCase):
    def test_reveal_and_custom_emote_remain_wired(self):
        engine = GameEngine.new_game([('p1', 'Human', []), ('p2', 'Bot', [])], starting_hand=0)
        view = GameSession(engine, require_setup=False).view(perspective='p1')
        view['table_messages'] = [{
            'id': 1,
            'kind': 'action',
            'action': 'reveal',
            'author': 'Human',
            'card_name': 'Revealed card',
            'revealed_card': {'name': 'Revealed card'},
        }]
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/board-chat-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><body><main id="board"></main></body></html>'))
                page.goto(f'http://127.0.0.1:{server.server_port}/board-chat-test')
                page.evaluate('''async view => {
                    const {createGameBoardView} = await import('/src/js/gameBoardView.js');
                    window.actions = [];
                    window.boardView = view;
                    const board = createGameBoardView({transport:{sendAction:async action => {
                        actions.push(action);
                        return {ok:true, data:boardView};
                    }}});
                    board.mount(document.getElementById('board'));
                    board.start('board-chat-test', view);
                }''', view)

                page.locator('[data-reveal-open]').click()
                self.assertEqual(page.locator('.gf-revealed-modal').count(), 1)
                self.assertIn('Revealed card', page.locator('.gf-revealed-modal').inner_text())
                page.locator('[data-reveal-close]').click()
                self.assertEqual(page.locator('.gf-revealed-modal').count(), 0)

                page.locator('[data-chat-custom]').click()
                page.locator('[data-emoji-category="objects"]').click()
                page.locator('.gf-emoji-grid button').first.click()
                self.assertEqual(page.evaluate('actions'), [{'type': 'emote', 'emote': '🎲'}])
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
