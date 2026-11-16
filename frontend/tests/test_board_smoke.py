"""Smoke tests for the shared game board against a real engine session.

They pin the user-visible flows (play a land, advance the step, declare an
attacker) so refactors of `gameBoardView.js` have a behavioural safety net.
Cast targeting is covered by test_modal_drag.py.
"""
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
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession
from test_cross_player_attachments import QuietHandler

BOARD_PAGE = ('<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
              '<body><main id="board"></main></body></html>')


def position(step='main1'):
    """P1 on their own turn with a Forest in hand and a Bear that may attack."""
    forest = Card(id='forest', name='Forest', type_line='Basic Land — Forest', is_land=True)
    engine = GameEngine.new_game([('p1', 'Human', [forest] * 10), ('p2', 'Bot', [forest] * 10)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_phase = 'precombat_main' if step == 'main1' else 'combat'
    engine.state.current_step = step
    land = GameObject(forest, owner_id='p1', zone=Zone.HAND)
    engine.state.player_by_id('p1').hand.append(land)
    bear = GameObject(Card(id='bear', name='Test Bear', type_line='Creature — Bear', is_creature=True,
                           power=2, toughness=2), owner_id='p1', zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(bear)
    bear.summoning_sick = False
    return GameSession(engine, mode='replay', require_setup=False), land, bear


class BoardSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def open_board(self, session):
        """Mount the board on `session`; actions go through the real engine and are recorded in `window.actions`."""
        page = self.browser.new_page(viewport={'width': 1600, 'height': 1000})
        self.addCleanup(page.close)
        self.errors = []
        page.on('pageerror', lambda error: self.errors.append(str(error)))
        page.route('**/smoke-test', lambda route: route.fulfill(content_type='text/html', body=BOARD_PAGE))

        def action(route):
            result = session.apply_action(route.request.post_data_json, actor_id='p1')
            route.fulfill(json={'ok': True, 'data': result})
        page.route('**/game-action', action)
        page.goto(f'http://127.0.0.1:{self.server.server_port}/smoke-test')
        page.evaluate('''async view => {
            const {createGameBoardView} = await import('/src/js/gameBoardView.js');
            window.actions = [];
            const board = createGameBoardView({allowRewind: false, transport: {sendAction: async action => {
                actions.push(action);
                const response = await fetch('/game-action', {method: 'POST',
                    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(action)});
                return window.lastResult = await response.json();
            }}});
            board.mount(document.getElementById('board'));
            board.start(view.session_id, view);
        }''', session.view(perspective='p1'))
        return page

    @staticmethod
    def click_action(page, action_type):
        """Click the rendered button whose `data-action` has this type (menu buttons live in popovers)."""
        page.evaluate('''type => [...document.querySelectorAll('[data-action]')]
            .find(el => JSON.parse(el.dataset.action).type === type).click()''', action_type)

    def test_playing_a_land_moves_it_to_the_battlefield(self):
        session, land, _ = position()
        page = self.open_board(session)
        self.click_action(page, 'play_land')
        page.wait_for_function('window.lastResult != null')
        self.assertEqual(page.evaluate('actions'), [{'type': 'play_land', 'instance_id': land.instance_id, 'name': 'Forest'}])
        player = session.engine.state.player_by_id('p1')
        self.assertEqual([o.name for o in player.hand], [])
        self.assertIn('Forest', [o.name for o in session.engine.state.battlefield])
        # The repaint no longer offers the land from hand.
        page.wait_for_function('!document.querySelector(\'[data-action*="play_land"]\')')
        self.assertEqual(self.errors, [])

    def test_advance_step_button_sends_advance_step(self):
        session, _, _ = position()
        page = self.open_board(session)
        page.locator('#gf-advance').click()
        page.wait_for_function('window.lastResult != null')
        self.assertEqual(page.evaluate('actions'), [{'type': 'advance_step'}])
        self.assertEqual(self.errors, [])

    def test_attacker_is_drafted_then_declared_on_confirm(self):
        session, _, bear = position('declare_attackers')
        page = self.open_board(session)
        self.click_action(page, 'declare_attackers')
        # Choosing an attacker only drafts it: nothing is sent until the player confirms.
        page.locator('[data-attack-confirm]').wait_for()
        self.assertEqual(page.evaluate('actions'), [])
        page.locator('[data-attack-confirm]').click()
        page.wait_for_function('window.actions.length > 0')
        sent = page.evaluate('actions')
        self.assertEqual([a['type'] for a in sent], ['declare_attackers'])
        self.assertEqual([d['instance_id'] for d in sent[0]['declarations']], [bear.instance_id])
        self.assertEqual(sent[0]['declarations'][0]['defender']['id'], 'p2')
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
