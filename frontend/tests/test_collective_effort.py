"""Real shared-board Escalate picker against a live GameSession over local HTTP."""
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
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.support.deck_batch import RICH, card, filler, game, main_phase


class Handler(SimpleHTTPRequestHandler):
    session = None

    def log_message(self, *args):
        pass

    def respond(self, value):
        body = json.dumps(value).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/game-view':
            self.respond(self.session.view())
        else:
            super().do_GET()

    def do_POST(self):
        action = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/game-action':
            try:
                self.respond({'ok': True, 'data': self.session.apply_action(action)})
            except Exception as error:
                self.respond({'ok': False, 'error': str(error)})
        else:
            self.respond({'ok': True})  # UI-draft persistence is incidental to this picker test.


class CollectiveEffortBrowserTest(unittest.TestCase):
    def test_targets_precede_distinct_tap_costs_and_selected_creatures_are_paid(self):
        engine = game()
        main_phase(engine)
        spell = card(engine, 'Collective Effort', zone=Zone.HAND)
        big = filler(engine, 'Destroy creature', player='p2', power=5, toughness=5)
        enchantment = filler(engine, 'Destroy enchantment', 'Enchantment', player='p2')
        small = filler(engine, 'Keep untapped', power=1, toughness=2)
        chosen = [filler(engine, f'Chosen {i}', power=4 + i, toughness=6) for i in range(2)]
        engine.state.player_by_id('p1').mana_pool.add_many(RICH)
        Handler.session = GameSession(engine, session_id='browser-test', require_setup=False)
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'frontend')))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/collective-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
                    '<body><main id="board"></main></body></html>'))
                page.goto(f'http://127.0.0.1:{server.server_port}/collective-test')
                page.evaluate('''async () => {
                    const {createGameBoardView} = await import('/src/js/gameBoardView.js');
                    const board = createGameBoardView({allowRewind:false, transport:{sendAction:async action => {
                        window.lastAction = action;
                        const response = await fetch('/game-action', {method:'POST',
                            headers:{'Content-Type':'application/json'}, body:JSON.stringify(action)});
                        return window.lastResult = await response.json();
                    }}});
                    board.mount(document.getElementById('board'));
                    board.start('browser-test', await (await fetch('/game-view')).json());
                }''')
                page.evaluate('''iid => {
                    const button = [...document.querySelectorAll('[data-cast-target-start]')].find(el => {
                        const data = JSON.parse(el.dataset.castTargetStart);
                        return data.iid === iid && JSON.stringify(data.mode) === '[0,1,2]';
                    });
                    if (!button) throw new Error('Missing three-mode cast action');
                    button.click();
                }''', spell.instance_id)
                def pick(target):
                    page.evaluate('''target => {
                        const button = [...document.querySelectorAll('[data-cast-target-pick]')].find(el => {
                            const candidate = JSON.parse(el.dataset.castTargetPick).target;
                            return candidate && Object.keys(target).every(key => candidate[key] === target[key]);
                        });
                        if (!button) throw new Error('Missing picker candidate');
                        button.click();
                    }''', target)
                pick({'instance_id': big.instance_id})
                pick({'instance_id': enchantment.instance_id})
                pick({'player_id': 'p1'})
                self.assertIsNone(page.evaluate('window.lastAction || null'))
                pick({'instance_id': chosen[0].instance_id})
                self.assertFalse(page.evaluate('''iid => [...document.querySelectorAll('[data-cast-target-pick]')]
                    .some(el => JSON.parse(el.dataset.castTargetPick).target?.instance_id === iid)''', chosen[0].instance_id))
                pick({'instance_id': chosen[1].instance_id})
                page.wait_for_function('window.lastResult != null')
                self.assertTrue(page.evaluate('window.lastResult.ok'))
                self.assertEqual(page.evaluate('window.lastAction.tap_choices'), [obj.instance_id for obj in chosen])
                self.assertTrue(all(Handler.session.engine.state.find_object(obj.instance_id).tapped for obj in chosen))
                self.assertFalse(Handler.session.engine.state.find_object(small.instance_id).tapped)
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
