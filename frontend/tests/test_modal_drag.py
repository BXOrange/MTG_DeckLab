"""BUG-49: dragging Opera Love Song preserves the player's mode and target choice."""
import json
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
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import GameSession
from test_cross_player_attachments import QuietHandler


def position():
    forest = Card(id='forest', name='Forest', type_line='Basic Land — Forest', is_land=True)
    engine = GameEngine.new_game([('p1', 'Human', [forest] * 10), ('p2', 'Bot', [forest] * 10)], starting_hand=0)
    engine.begin_turn()
    engine.state.current_phase = 'precombat_main'
    engine.state.current_step = 'main1'
    card = Card(id='opera', name='Opera Love Song', type_line='Instant', is_instant=True,
                mana_cost_string='{1}{R}', converted_mana_cost=2,
                oracle_text='Choose one —\n• Exile the top two cards of your library. You may play those cards until your next end step.\n• One or two target creatures each get +2/+0 until end of turn.')
    spell = GameObject(card, owner_id='p1', zone=Zone.HAND)
    bind_from_catalogue(spell)
    player = engine.state.player_by_id('p1')
    player.hand.append(spell)
    player.mana_pool.add_many({'R': 1, 'C': 1})
    creature = GameObject(Card(id='bear', name='Test Bear', type_line='Creature — Bear', is_creature=True,
                               power=2, toughness=2), owner_id='p1', zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(creature)
    return GameSession(engine, mode='replay', require_setup=False), spell, creature


class ModalDragTest(unittest.TestCase):
    def test_both_modes_are_chosen_explicitly_and_resolve_the_selected_effect(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(ROOT / 'frontend')))
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                for mode in (0, 1):
                    with self.subTest(mode=mode):
                        session, spell, creature = position()
                        page = browser.new_page(viewport={'width': 1600, 'height': 1000})
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.route('**/modal-test', lambda route: route.fulfill(content_type='text/html', body=
                            '<html><head><link rel="stylesheet" href="/src/styles/main.css"></head>'
                            '<body><main id="board"></main></body></html>'))
                        def action(route):
                            result = session.apply_action(route.request.post_data_json, actor_id='p1')
                            route.fulfill(json={'ok': True, 'data': result})
                        page.route('**/game-action', action)
                        page.goto(f'http://127.0.0.1:{server.server_port}/modal-test')
                        view = session.view(perspective='p1')
                        view['test_language'] = 'en' if mode == 0 else 'de'
                        # BUG-51: real rendered translations must include cost, source and outcome.
                        view['table_messages'] = [dict(id=i, kind='action', action=outcome, actor_id='p2',
                            author='Bot', card_name='Rhystic Study', cost_label='{1}')
                            for i, outcome in enumerate(('pay_cost', 'decline_cost'), 1)]
                        page.evaluate('''async view => {
                            const {setLang} = await import('/src/js/i18n.js');
                            setLang(view.test_language);
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
                        page.evaluate('''iid => {
                            const slot = document.querySelector(`[data-card-menu][data-instance-id="${iid}"]`);
                            const dt = new DataTransfer();
                            slot.querySelector('[data-draggable-card="true"]').dispatchEvent(new DragEvent('dragstart',
                                {bubbles:true, dataTransfer:dt}));
                            slot.closest('[data-player-id]').querySelector('[data-drop-zone="battlefield"]')
                                .dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:dt}));
                        }''', spell.instance_id)
                        self.assertEqual(page.locator('.gf-card-menu:popover-open').count(), 1)
                        self.assertEqual(page.evaluate('actions'), [])
                        feed = page.locator('.gf-chat').inner_text()
                        if mode == 0:
                            self.assertIn('pays 1️⃣ for Rhystic Study.', feed)
                            self.assertIn('does not pay 1️⃣ for Rhystic Study.', feed)
                        else:
                            self.assertIn('bezahlt 1️⃣ für Rhystic Study.', feed)
                            self.assertIn('bezahlt 1️⃣ für Rhystic Study nicht.', feed)
                        if mode == 0:
                            page.evaluate('''() => {
                                const menu = document.querySelector('.gf-card-menu:popover-open');
                                [...menu.querySelectorAll('[data-action]')].find(el => JSON.parse(el.dataset.action).mode === 0).click();
                            }''')
                        else:
                            page.locator('.gf-card-menu:popover-open [data-cast-target-start]').click()
                            page.evaluate('''iid => [...document.querySelectorAll('[data-cast-target-pick]')]
                                .find(el => JSON.parse(el.dataset.castTargetPick).target?.instance_id === iid).click()''', creature.instance_id)
                            # The second creature is optional; finish with the selected single target.
                            page.evaluate('''() => [...document.querySelectorAll('[data-cast-target-pick]')]
                                .find(el => JSON.parse(el.dataset.castTargetPick).target === null).click()''')
                        page.wait_for_function('window.lastResult != null')
                        self.assertTrue(page.evaluate('lastResult.ok'))
                        self.assertEqual(page.evaluate('actions.length'), 1)
                        self.assertEqual(page.evaluate('actions[0].mode'), mode)
                        engine = session.engine
                        player = engine.state.player_by_id('p1')
                        before = len(player.library)
                        engine.resolve_until_stable()
                        if mode == 0:
                            self.assertEqual(len(player.exile), 2)
                            self.assertEqual(len(player.library), before - 2)
                            self.assertEqual(creature.power, 2)
                        else:
                            engine.recompute_continuous_effects()
                            self.assertEqual(creature.power, 4)
                            self.assertEqual(len(player.exile), 0)
                        self.assertEqual(errors, [])
                        page.close()
                browser.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
