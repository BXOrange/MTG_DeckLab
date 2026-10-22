"""A redacted bot choice blocks human passing without blocking bot updates."""
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
from mtg_analyzer.services.game_session import GameSession, MULTIPLAYER
from test_cross_player_attachments import QuietHandler


class WaitingBotChoiceTest(unittest.TestCase):
    def test_redacted_choice_prevents_auto_skip_countdown_and_manual_pass(self):
        engine = GameEngine.new_game([('p1', 'Human', []), ('p2', 'Bot', [])], starting_hand=0)
        engine.state.active_player_index = 1
        engine.state.priority_player_index = 0
        engine.state.current_step = 'combat_damage'
        session = GameSession(engine, mode=MULTIPLAYER, require_setup=False, spell_timer_seconds=1)
        engine.rules.open_choice({'kind': 'search', 'player_id': 'p2', 'prompt': 'Find a basic land',
                                  'options': [{'id': 'secret-id', 'label': 'Forest'}]})
        view = session.view(perspective='p1')
        self.assertIsNone(view['pending_choice'])
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1400, 'height': 1000})
                page.route('**/waiting-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><body><main id="board"></main></body></html>'))
                page.goto(f'http://127.0.0.1:{server.server_port}/waiting-test')
                page.evaluate('''async view => {
                    const {createGameBoardView} = await import('/src/js/gameBoardView.js');
                    window.actions = [];
                    window.waitingView = view;
                    window.waitingBoard = createGameBoardView({transport:{sendAction: action => {
                        actions.push(action);
                        return new Promise(() => {});
                    }}});
                    waitingBoard.mount(document.getElementById('board'));
                    waitingBoard.start('waiting-test', view);
                }''', view)
                self.assertEqual(page.evaluate('actions'), [], 'The waiting marker must suppress immediate auto-skip')
                page.wait_for_timeout(1200)
                self.assertEqual(page.evaluate('actions'), [], 'The response timer must remain stopped')
                self.assertTrue(page.locator('[data-pass-priority]').is_disabled())
                self.assertEqual(page.locator('[data-timer-count]').count(), 0)
                page.keyboard.press('Space')
                self.assertEqual(page.evaluate('actions'), [])
                page.evaluate('''() => {
                    const resumed = structuredClone(waitingView);
                    delete resumed.state.waiting_on_choice;
                    waitingBoard.refresh(resumed);
                }''')
                self.assertEqual(page.evaluate('actions'), [{'type': 'pass_priority'}])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
