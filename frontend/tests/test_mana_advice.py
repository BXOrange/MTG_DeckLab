"""Browser regression checks for the empirical land advice and exact draw probabilities.
Run: backend/venv/bin/python frontend/tests/test_mana_advice.py
Uses real ES modules; serves only local fixture data.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
from itertools import combinations
from threading import Thread
import unittest

from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ManaAdviceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.page = self.browser.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.route('**/mana-test', lambda route: route.fulfill(
            content_type='text/html', body='<html><head><link rel="stylesheet" href="/src/styles/main.css"></head><body><main id="test"></main></body></html>'))
        self.page.goto(self.base + '/mana-test')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_exact_probabilities_against_exhaustive_hands(self):
        cases = []
        for draws in (0, 3, 7):
            for min_lands in (0, 2, 4):
                for min_ramp in (0, 1, 2):
                    hands = list(combinations(range(8), draws))
                    successes = sum(
                        sum(card < 3 for card in hand) >= min_lands
                        and sum(3 <= card < 5 for card in hand) >= min_ramp
                        for hand in hands
                    )
                    cases.append([draws, min_lands, min_ramp, successes / len(hands)])
        actual = self.page.evaluate('''async cases => {
          const {jointDrawProbability}=await import('/src/js/manaAdvice.js');
          return cases.map(([draws,l,r])=>jointDrawProbability(8,3,2,draws,l,r));
        }''', cases)
        for case, value in zip(cases, actual):
            self.assertAlmostEqual(value, case[3], places=12)

    def test_reference_ramp_probabilities_and_targets(self):
        result = self.page.evaluate('''async () => {
          const {drawProbability,requiredRampCount,jointDrawProbability}=await import('/src/js/manaAdvice.js');
          return {chances:[10,12,14,16].map(r=>drawProbability(99,r,9)),
            targets:[.7,.8,.9].map(t=>requiredRampCount(99,t,9,36)),
            empty:drawProbability(99,0,9),all:drawProbability(99,99,9),
            impossible:requiredRampCount(99,.9,9,98),
            joint:jointDrawProbability(99,36,12,7),
            independent:drawProbability(99,36,7,2)*drawProbability(99,12,7)};
        }''')
        self.assertEqual([round(p * 100, 1) for p in result['chances']], [63.3, 70.4, 76.2, 81.0])
        self.assertEqual(result['targets'], [12, 16, 22])
        self.assertEqual(result['empty'], 0)
        self.assertAlmostEqual(result['all'], 1)
        self.assertIsNone(result['impossible'])
        self.assertNotAlmostEqual(result['joint'], result['independent'], places=4)

    def test_empirical_formula_inputs_mdfcs_and_classification(self):
        result = self.page.evaluate('''async () => {
          const {analyzeManaAdvice,cheapCardKind,isEarlyRamp}=await import('/src/js/manaAdvice.js');
          const cards=[
            {name:'Forest',is_land:true,type_line:'Basic Land'},
            {name:'Rock',converted_mana_cost:2,type_line:'Artifact',oracle_text:'{T}: Add {C}.'},
            {name:'Three',converted_mana_cost:3},
            {name:'Four',converted_mana_cost:4},
            {name:'Commander',converted_mana_cost:12},
          ];
          const resolved=new Map(cards.map(c=>[c.name.toLowerCase(),{card:c}]));
          const parsed={commanders:[{name:'Commander',qty:1}],mainDeck:[{name:'Forest',qty:36},{name:'Rock',qty:10},{name:'Three',qty:43},{name:'Four',qty:10}]};
          const advice=analyzeManaAdvice(parsed,resolved);
          const both={converted_mana_cost:2,oracle_text:'Draw a card. Search your library for a basic land card and put it onto the battlefield tapped.'};
          const ritual={converted_mana_cost:1,is_instant:true,oracle_text:'Add {B}{B}{B}.'};
          const handSearch={converted_mana_cost:2,is_sorcery:true,oracle_text:'Search your library for a land card, reveal it, put it into your hand, then shuffle.'};
          const modal=rarity=>({name:rarity,converted_mana_cost:4,layout:'modal_dfc',back_type_line:'Land',rarity});
          const modals=['rare','mythic'].map(modal);
          const modalDeck={commanders:parsed.commanders,mainDeck:modals.map(c=>({name:c.name,qty:1}))};
          modals.forEach(c=>resolved.set(c.name.toLowerCase(),{card:c}));
          const mdfcs=analyzeManaAdvice(modalDeck,resolved);
          resolved.get('rare').card.rarity='';
          const missingRarity=analyzeManaAdvice(modalDeck,resolved);
          return {advice,mdfcs,missingRarity,
            both:cheapCardKind(both),ritual:cheapCardKind(ritual),earlyRitual:isEarlyRamp(ritual),
            search:cheapCardKind(handSearch),earlySearch:isEarlyRamp(handSearch),
            expensive:cheapCardKind({converted_mana_cost:3,oracle_text:'Draw two cards.'}),
            cycling:cheapCardKind({converted_mana_cost:6,oracle_text:'Cycling {1}'}),
            cyclingTwo:cheapCardKind({converted_mana_cost:6,oracle_text:'Cycling {1}{U}'}),
            unresolved:analyzeManaAdvice(parsed,new Map()).error};
        }''')
        advice = result['advice']
        self.assertEqual(advice['size'], 99)
        self.assertEqual(advice['averageManaValue'], 3)
        self.assertAlmostEqual(advice['effectiveTarget'], 38.01)
        self.assertEqual(advice['landTarget'], 38)
        self.assertEqual((advice['cheapRamp'], advice['earlyRamp']), (10, 10))
        self.assertEqual(result['both'], 'draw')
        self.assertEqual(result['ritual'], 'ramp')
        self.assertFalse(result['earlyRitual'])
        self.assertEqual(result['search'], 'ramp')
        self.assertFalse(result['earlySearch'])
        self.assertIsNone(result['expensive'])
        self.assertEqual(result['cycling'], 'draw')
        self.assertIsNone(result['cyclingTwo'])
        self.assertAlmostEqual(result['mdfcs']['mdfcCredit'], 1.12)
        self.assertIsNone(result['missingRarity']['landTarget'])
        self.assertTrue(result['unresolved'])

    def test_localized_rendering_escaping_and_probability_controls(self):
        result = self.page.evaluate('''async () => {
          const {analyzeManaAdvice}=await import('/src/js/manaAdvice.js');
          const {manaAdviceHtml,wireManaAdviceControls}=await import('/src/js/manaAdviceView.js');
          const {setLang}=await import('/src/js/i18n.js');
          const cards=[{name:'Commander',converted_mana_cost:4},{name:'Forest',is_land:true},
            {name:'Rock',type_line:'Artifact',converted_mana_cost:2,oracle_text:'{T}: Add {C}.'},
            {name:'Spell',converted_mana_cost:3}];
          const state=analyzeManaAdvice({commanders:[{name:'Commander',qty:1}],mainDeck:[{name:'Forest',qty:36},{name:'Rock',qty:12},{name:'Spell',qty:51}]},new Map(cards.map(c=>[c.name.toLowerCase(),{card:c}])));
          state.drawCards=[{name:'<unsafe>',quantity:1}];
          const root=document.querySelector('#test');
          root.innerHTML=manaAdviceHtml(state);
          const restore=wireManaAdviceControls(root);
          restore();
          const before=root.querySelector('[data-mana-ramp-target]').textContent;
          const select=root.querySelector('[data-mana-reliability]');
          select.value='.9'.replace(/^\\./,'0.');select.dispatchEvent(new Event('change',{bubbles:true}));
          const after=root.querySelector('[data-mana-ramp-target]').textContent;
          const jointBefore=root.querySelector('[data-mana-joint-target]').textContent;
          const lands=root.querySelector('[data-mana-min-lands]');
          lands.value='4';lands.dispatchEvent(new Event('change',{bubbles:true}));
          const jointAfter=root.querySelector('[data-mana-joint-target]').textContent;
          root.innerHTML=manaAdviceHtml(state);restore();
          const preserved=root.querySelector('[data-mana-reliability]').value;
          const escaped=!root.querySelector('unsafe');
          const en=root.textContent;
          setLang('de');const de=manaAdviceHtml(state);
          return {before,after,jointBefore,jointAfter,preserved,escaped,en,de};
        }''')
        self.assertIn('16 early ramp cards', result['before'])
        self.assertIn('22 early ramp cards', result['after'])
        self.assertNotEqual(result['jointBefore'], result['jointAfter'])
        self.assertEqual(result['preserved'], '0.9')
        self.assertTrue(result['escaped'])
        self.assertIn('Empirical land estimate', result['en'])
        self.assertIn('Empirische Länderschätzung', result['de'])
        self.assertNotIn('an.manaAdvice.', result['de'])

    def test_analyze_view_refresh_and_deck_switch_without_workers(self):
        cards = {
            'Commander': {'name': 'Commander', 'converted_mana_cost': 4, 'is_creature': True, 'type_line': 'Legendary Creature', 'color_identity': ['G']},
            'Forest': {'name': 'Forest', 'is_land': True, 'type_line': 'Basic Land — Forest', 'oracle_text': '{T}: Add {G}.', 'color_identity': ['G']},
            'Spell': {'name': 'Spell', 'converted_mana_cost': 3, 'is_creature': True, 'type_line': 'Creature'},
            'Elf': {'name': 'Elf', 'converted_mana_cost': 1, 'is_creature': True, 'type_line': 'Creature', 'oracle_text': '{T}: Add {G}.'},
        }
        for name, card in cards.items():
            card.setdefault('oracle_text', '')
            card.setdefault('color_identity', [])
            card.setdefault('mana_cost', {})
            card['id'] = name

        def api(route):
            if '/cards/resolve' in route.request.url:
                payload = {'cards': cards, 'notFound': []}
            elif '/combos/matches' in route.request.url:
                payload = {'combos': [], 'recommendations': []}
            elif '/archetypes/analyze' in route.request.url:
                route.fulfill(status=503, body='{}')
                return
            else:
                payload = []
            route.fulfill(content_type='application/json', body=json.dumps(payload))

        self.page.route('**/api/**', api)
        self.page.evaluate('''async () => {
          window.Worker=class {constructor(){throw Error('Mana advice must not start a worker');}};
          const {renderAnalyzeView}=await import('/src/js/analyzeView.js');
          window.view=renderAnalyzeView(document.querySelector('#test'));
          view.loadDeck({id:'first',name:'First',commanderText:'1 Commander',mainboardText:'36 Forest\\n8 Elf\\n55 Spell'});
        }''')
        self.page.wait_for_function("document.querySelector('[data-mana-advice] tbody tr') !== null")
        self.page.wait_for_function("!document.querySelector('#advice-content .spinner')")
        self.page.locator('[data-subtab="advice"]').click()
        self.assertIn('8 cards qualify as early ramp', self.page.locator('[data-mana-advice]').inner_text())
        self.page.locator('[data-mana-reliability]').select_option('0.9')
        self.page.evaluate("view.loadDeck({id:'second',name:'Second',commanderText:'1 Commander',mainboardText:'40 Forest\\n4 Elf\\n55 Spell'})")
        self.page.wait_for_function("document.querySelector('[data-mana-advice]').textContent.includes('4 cards qualify as early ramp')")
        self.page.wait_for_function("!document.querySelector('#advice-content .spinner')")
        self.page.locator('[data-subtab="advice"]').click()
        self.assertTrue(self.page.locator('[data-mana-advice] table').first.is_visible())
        self.assertEqual(self.page.locator('[data-mana-reliability]').input_value(), '0.9')
        self.assertNotIn('Simulation estimate', self.page.locator('#advice-content').inner_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
