"""ENG-62: a two-cost kicker spell ("Kicker {1}{U} and/or {B}") shows one toggle per cost in the cast form and
sends the checked costs as a list of cost indices; a cost no affordable combination includes is disabled."""
import sys
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from playwright.sync_api import sync_playwright
from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.game_session import GameSession
from test_cross_player_attachments import QuietHandler

ANAVOLVER_TEXT = (
    'Kicker {1}{U} and/or {B} (You may pay an additional {1}{U} and/or {B} as you cast this spell.)\n'
    'If this creature was kicked with its {1}{U} kicker, it enters with two +1/+1 counters on it and with flying.\n'
    'If this creature was kicked with its {B} kicker, it enters with a +1/+1 counter on it and with '
    '"Pay 3 life: Regenerate this creature."')


def position(mana):
    forest = Card(id='forest', name='Forest', type_line='Basic Land — Forest', is_land=True)
    engine = GameEngine.new_game([('p1', 'Human', [forest] * 10), ('p2', 'Bot', [forest] * 10)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_phase = 'precombat_main'
    engine.state.current_step = 'main1'
    card = Card(id='ana', name='Anavolver', type_line='Creature — Volver', is_creature=True, power=3, toughness=3,
                mana_cost_string='{3}{G}', converted_mana_cost=4, oracle_text=ANAVOLVER_TEXT, keywords=['Kicker'])
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    attach_to_object(spell, parse_oracle(card).specs)
    player = engine.state.player_by_id('p1')
    player.hand.append(spell)
    player.mana_pool.add_many(mana)
    return GameSession(engine, mode='replay', require_setup=False), spell


class KickerCastFormTest(unittest.TestCase):
    def open_menu(self, page, server, session, spell):
        page.route('**/kicker-test', lambda route: route.fulfill(content_type='text/html', body=
            '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
            '<body><main id="board"></main></body></html>'))

        def action(route):
            result = session.apply_action(route.request.post_data_json, actor_id='p1')
            route.fulfill(json={'ok': True, 'data': result})
        page.route('**/game-action', action)
        page.goto(f'http://127.0.0.1:{server.server_port}/kicker-test')
        view = session.view(perspective='p1')
        page.evaluate('''async view => {
            const {createGameBoardView} = await import('/src/js/gameBoardView.js');
            window.actions = [];
            const board = createGameBoardView({allowRewind:false, transport:{sendAction:async action => {
                actions.push(action);
                const response = await fetch('/game-action', {method:'POST',
                    headers:{'Content-Type':'application/json'}, body:JSON.stringify(action)});
                return window.lastResult = await response.json();
            }}});
            board.mount(document.getElementById('board'));board.start(view.session_id, view);
        }''', view)
        page.locator(f'[data-card-menu][data-instance-id="{spell.instance_id}"]').click(button='right')

    def run_case(self, mana, check_indices, expect_disabled, expect_kicked):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                session, spell = position(mana)
                self.open_menu(page, server, session, spell)
                boxes = page.locator('.gf-card-menu:popover-open input[data-kicker-cost-input]')
                self.assertEqual(boxes.count(), 2)
                labels = page.locator('.gf-card-menu:popover-open .gf-kicker-cost').all_inner_texts()
                self.assertEqual([text.strip() for text in labels], ['Kicker {1}{U}', 'Kicker {B}'])
                self.assertEqual([boxes.nth(i).is_disabled() for i in range(2)], expect_disabled)
                for index in check_indices:
                    boxes.nth(index).check()
                page.locator('.gf-card-menu:popover-open [data-cast-x]').click()
                page.wait_for_function('window.lastResult != null')
                self.assertEqual(page.evaluate('actions[0].kicked'), expect_kicked)
                self.assertTrue(page.evaluate('lastResult.ok'))
                self.assertEqual(tuple(spell.kicker_costs_paid), tuple(expect_kicked))
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()

    def test_toggle_each_cost(self):
        rich = {'C': 6, 'G': 1, 'U': 1, 'B': 1}
        self.run_case(rich, [0], [False, False], [0])
        self.run_case(rich, [1], [False, False], [1])
        self.run_case(rich, [0, 1], [False, False], [0, 1])
        self.run_case(rich, [], [False, False], [])

    def test_unaffordable_cost_is_disabled(self):
        # {3}{G} + {B} fits 5 mana; {1}{U} on top would not (and has no blue).
        self.run_case({'C': 4, 'G': 1, 'B': 1}, [1], [True, False], [1])


if __name__ == '__main__':
    unittest.main()
