"""Shared board groups Auras with their hosts across controller boundaries."""
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
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class CrossPlayerAttachmentTest(unittest.TestCase):
    def test_aura_follows_opposing_host_and_retains_controller_and_actions(self):
        engine = GameEngine.new_game([('p1', 'Human', []), ('p2', 'Bot', [])], starting_hand=0)
        def permanent(name, controller, creature=False):
            obj = GameObject(Card(id=name, name=name, type_line='Creature' if creature else 'Enchantment — Aura',
                                  is_creature=creature,
                                  power=3 if creature else None, toughness=3 if creature else None),
                             owner_id=controller, zone=Zone.BATTLEFIELD)
            engine.state.add_to_battlefield(obj)
            return obj
        host = permanent('Kodama of the West Tree', 'p2', True)
        aura = permanent('Betrayal', 'p1')
        aura.attached_to = host.instance_id
        own_aura = permanent('Bear Umbra', 'p2')
        own_aura.attached_to = host.instance_id
        nested = permanent('Nested Aura', 'p1')
        nested.attached_to = own_aura.instance_id
        loose = permanent('Unattached Aura', 'p1')
        view = GameSession(engine, require_setup=False).view(perspective='p1')
        view['legal_actions'] = [{'type': 'activate_ability', 'instance_id': aura.instance_id,
                                  'ability_index': 0, 'description': 'Test activation'}]
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.route('**/attachment-test', lambda route: route.fulfill(content_type='text/html', body=
                    '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
                    '<body><main id="board"></main></body></html>'))
                page.goto(f'http://127.0.0.1:{server.server_port}/attachment-test')
                page.evaluate('''async view => {
                    const {createGameBoardView} = await import('/src/js/gameBoardView.js');
                    window.attachmentBoard = createGameBoardView({allowRewind:false});
                    attachmentBoard.mount(document.getElementById('board'));
                    attachmentBoard.start('attachment-test', view);
                }''', view)
                group = page.locator('[data-player-id="p2"] .gf-attach-group')
                self.assertEqual(group.count(), 1)
                for name in (host.name, aura.name, own_aura.name, nested.name):
                    self.assertEqual(group.locator(f'[data-hover-card="{name}"]').count(), 1)
                    self.assertEqual(page.locator(f'[data-hover-card="{name}"]').count(), 1)
                self.assertIn('Human', group.locator('.gf-foreign-attachment').first.inner_text())
                self.assertEqual(page.locator('[data-player-id="p1"] [data-hover-card="Unattached Aura"]').count(), 1)
                self.assertEqual(group.locator('.gf-card-action').count(), 1)
                self.assertEqual(errors, [])
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
