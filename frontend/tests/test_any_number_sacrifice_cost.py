"""MEC-169: "Sacrifice ~ and any number of other non-Eldrazi creatures" (Emrakul's Evangel) lets the player announce
how many creatures join the source: one optional pick per candidate, finished whenever they have chosen enough (zero
allowed), answered in `tap_choices` with exactly the chosen creatures."""
import sys
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from playwright.sync_api import sync_playwright
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSession
from test_cross_player_attachments import QuietHandler


def position():
    database = CardDatabase(DEFAULT_DB_PATH)
    bears = database.get_card('Grizzly Bears')
    engine = GameEngine.new_game([('p1', 'Human', [bears] * 10), ('p2', 'Bot', [bears] * 10)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_phase = 'precombat_main'
    engine.state.current_step = 'main1'
    objects = []
    for name in ("Emrakul's Evangel", 'Grizzly Bears', 'Savannah Lions', 'Hill Giant'):
        obj = GameObject(database.get_card(name), owner_id='p1')
        obj.summoning_sick = False
        bind_from_catalogue(obj)
        engine.state.add_to_battlefield(obj)
        objects.append(obj)
    return GameSession(engine, mode='replay', require_setup=False), objects


class AnyNumberSacrificeCostTest(unittest.TestCase):
    def test_player_announces_the_group(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                session, (evangel, bears, lions, giant) = position()
                page.route('**/any-number-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
                    '<body><main id="board"></main></body></html>'))

                def action(route):
                    result = session.apply_action(route.request.post_data_json, actor_id='p1')
                    route.fulfill(json={'ok': True, 'data': result})
                page.route('**/game-action', action)
                page.goto(f'http://127.0.0.1:{server.server_port}/any-number-test')
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
                page.locator(f'[data-card-menu][data-instance-id="{evangel.instance_id}"]').click(button='right')
                page.locator('.gf-card-menu:popover-open [data-sacrifice-choice-start]').first.click()
                # Pick two of the three candidates, then finish: the third is never sacrificed.
                for name in ('Grizzly Bears', 'Savannah Lions'):
                    page.locator('[data-cast-target-pick]', has_text=name).first.click()
                page.locator('[data-cast-target-pick].gf-decline').click()
                page.wait_for_function('window.lastResult != null')
                sent = page.evaluate('actions[0].tap_choices')
                self.assertEqual(sorted(sent), sorted([bears.instance_id, lions.instance_id]))
                self.assertTrue(page.evaluate('lastResult.ok'))
                self.assertEqual(giant.zone.value, 'battlefield')
                self.assertEqual(bears.zone.value, 'graveyard')
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
