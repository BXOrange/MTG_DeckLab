"""Real browser checks for synthesized sounds and committed-view event mapping.
Run: backend/venv/bin/python frontend/tests/test_game_audio.py
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from playwright.sync_api import sync_playwright


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class GameAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(
            QuietHandler, directory=str(Path(__file__).resolve().parents[1])))
        Thread(target=cls.server.serve_forever, daemon=True).start()
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
        self.page.goto(self.base + '/sound-lab.html')

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def test_live_controls_and_preferences(self):
        self.page.get_by_role('button', name='Tappen', exact=True).click()
        self.page.wait_for_function("document.querySelector('#status').textContent.startsWith('Tappen')")
        self.page.locator('#colors input[value="W"]').check()
        self.page.locator('#colors input[value="U"]').check()
        self.page.get_by_role('button', name='Spell casten', exact=True).click()
        self.page.wait_for_function("document.querySelector('#status').textContent.includes('W / U')")
        self.page.locator('#volume').fill('0.15')
        self.page.get_by_role('button', name='Stumm', exact=True).click()
        self.assertEqual({c['name']: c['value'] for c in self.page.context.cookies()}['gf_audio_enabled'], '0')
        self.page.reload()
        self.assertEqual(self.page.locator('#volume').input_value(), '0.15')

    def test_audio_settings_apply_to_existing_board_without_board_controls(self):
        from mtg_analyzer.game.game_engine import GameEngine
        from mtg_analyzer.services.game_session import GameSession
        engine = GameEngine.new_game([('p1', 'Human', []), ('p2', 'Bot', [])], starting_hand=0)
        view = GameSession(engine, require_setup=False).view(perspective='p1')
        self.page.evaluate('''async view => {
          const {createGameBoardView} = await import('./src/js/gameBoardView.js');
          document.body.innerHTML = '<main id="board"></main>';
          window.audioBoard = createGameBoardView({allowRewind: false});
          audioBoard.mount(document.querySelector('#board'));
          audioBoard.start('audio-test', view);
        }''', view)
        self.assertEqual(self.page.locator('.gf-audio-controls, #gf-audio-preview, a[href*="sound-lab"]').count(), 0)
        self.page.route('**/api/**', lambda route: route.fulfill(content_type='application/json', body='{}'))
        self.page.evaluate('''async () => {
          const {renderConnectionSettingsView} = await import('./src/js/connectionSettingsView.js');
          const settings = document.createElement('section');
          document.body.append(settings);
          renderConnectionSettingsView(settings);
        }''')
        self.page.locator('#settings-audio-enabled').check()
        self.page.locator('#settings-audio-volume').fill('0.2')
        state = self.page.evaluate('''async () => {
          const {getGameAudio} = await import('./src/js/gameAudio.js');
          return {enabled: getGameAudio().enabled, volume: getGameAudio().volume};
        }''')
        self.assertEqual(state, {'enabled': True, 'volume': 0.2})
        self.assertEqual(self.page.locator('[id*="preview"], a[href*="sound-lab"]').count(), 0)
        self.page.locator('#settings-audio-enabled').uncheck()
        self.assertFalse(self.page.evaluate("async () => (await import('./src/js/gameAudio.js')).getGameAudio().enabled"))
        self.page.evaluate('audioBoard.stop()')

    def test_signal_for_every_type_and_color_combination(self):
        result = self.page.evaluate('''async () => {
          const {createGameAudio} = await import('./src/js/gameAudio.js');
          const RealOffline = window.OfflineAudioContext;
          let offline;
          window.AudioContext = class extends RealOffline {
            constructor() { super(1, 44100, 44100); offline = this; }
            get state() { return 'running'; }
          };
          const failures = [];
          const signatures = [];
          const types = ['Creature', 'Instant', 'Sorcery', 'Enchantment', 'Artifact', 'Artifact Creature', 'Planeswalker', 'Battle'];
          for (const type_line of types) {
            for (let mask = 0; mask < 32; mask++) {
              const audio = createGameAudio();
              audio.setEnabled(true); audio.setVolume(0.3);
              await audio.unlock();
              audio.play({kind: 'cast', card: {type_line, colors: [...'WUBRG'].filter((c,i) => mask & (1 << i))}});
              const buffer = await offline.startRendering();
              const data = buffer.getChannelData(0);
              let energy = 0, peak = 0;
              for (const value of data) { energy += value * value; peak = Math.max(peak, Math.abs(value)); }
              if (!(energy > 0.001 && peak < 1 && Number.isFinite(energy))) failures.push([type_line,mask,energy,peak]);
              // Same blue/red colours: compare normalized energy over time,
              // and energy-weighted zero crossings for register differences.
              // Overall loudness alone cannot pass as a distinct gesture.
              if (mask === 10 && type_line !== 'Artifact Creature') {
                const bins = [];
                let weightedRegister = 0, totalWeight = 0;
                const binSize = 2205; // 50 ms at the offline sample rate.
                for (let start = 0; start < data.length; start += binSize) {
                  let sum = 0;
                  for (let i = start; i < Math.min(start + binSize, data.length); i++) sum += data[i] * data[i];
                  let crossings = 0;
                  for (let i = start + 1; i < Math.min(start + binSize, data.length); i++) {
                    if ((data[i] >= 0) !== (data[i - 1] >= 0)) crossings++;
                  }
                  weightedRegister += crossings * sum;
                  totalWeight += sum;
                  bins.push(Math.sqrt(sum));
                }
                const norm = Math.hypot(...bins);
                signatures.push({type_line, bins: bins.map(v => v / norm), register: weightedRegister / totalWeight});
              }

            }
          }
          for (let i = 0; i < signatures.length; i++) {
            for (let j = i + 1; j < signatures.length; j++) {
              const similarity = signatures[i].bins.reduce((sum, value, k) => sum + value * signatures[j].bins[k], 0);
              const registerDifference = Math.abs(signatures[i].register - signatures[j].register) / Math.max(signatures[i].register, signatures[j].register);
              if (similarity > 0.97 && registerDifference < 0.2) failures.push(['indistinct gesture', signatures[i].type_line, signatures[j].type_line, similarity, registerDifference]);
            }
          }
          for (const kind of ['tap','untap','land','damage','activate','draw','turn_end']) {
            const audio = createGameAudio(); audio.setEnabled(true); await audio.unlock();
            audio.play({kind, amount: 10});
            const buffer = await offline.startRendering();
            const data = buffer.getChannelData(0);
            if (!data.some(v => Math.abs(v) > 0.001)) failures.push(kind);
            if (kind === 'tap' || kind === 'untap') {
              // A click must finish promptly, including any room/filter tail.
              const late = data.slice(Math.floor(0.065 * buffer.sampleRate));
              if (late.some(v => Math.abs(v) > 0.0001)) failures.push(['click tail', kind]);
            }
          }
          return failures;
        }''')
        self.assertEqual(result, [])

    def test_draw_and_turn_handoff_use_confirmed_events(self):
        result = self.page.evaluate('''async () => {
          const {gameAudioEvents} = await import('./src/js/gameAudio.js');
          const previous = {move_log: ['start'], table_messages: [], state: {
            internal_turn: {number: 1}, active_player_id: 'p1', players: [],
            battlefield: [], stats: {timeline: []}
          }};
          const updated = (label) => {
            const next = structuredClone(previous);
            next.move_log.push(label);
            return next;
          };
          const pass = updated('pass_priority');
          const yieldTurn = updated('set_yield');
          const handoff = updated('pass_priority');
          handoff.state.internal_turn.number = 2;
          handoff.state.active_player_id = 'p2';
          handoff.state.stats.timeline.push({kind: 'draw', amount: 1});
          const extraTurn = updated('advance_step');
          extraTurn.state.internal_turn.number = 2;
          const drawDiscard = updated('choose');
          drawDiscard.state.stats.timeline.push({kind: 'draw', amount: 3});
          const movedToHand = updated('choose');
          movedToHand.state.players.push({hand: [{name: 'Returned card'}]});
          const eventKinds = view => gameAudioEvents(previous, view).map(e => e.kind);
          return {
            pass: eventKinds(pass), yieldTurn: eventKinds(yieldTurn),
            handoff: eventKinds(handoff), extraTurn: eventKinds(extraTurn),
            drawDiscard: gameAudioEvents(previous, drawDiscard), movedToHand: eventKinds(movedToHand),
            duplicate: gameAudioEvents(handoff, structuredClone(handoff)),
            undo: gameAudioEvents(handoff, previous), initial: gameAudioEvents(null, handoff)
          };
        }''')
        self.assertEqual(result['handoff'], ['turn_end', 'draw'])
        self.assertEqual(result['extraTurn'], ['turn_end'])
        self.assertEqual(result['drawDiscard'], [{'kind': 'draw', 'amount': 3}])
        for key in ('pass', 'yieldTurn', 'movedToHand', 'duplicate', 'undo', 'initial'):
            self.assertEqual(result[key], [])

    def test_land_play_announcement_not_just_land_entry(self):
        result = self.page.evaluate('''async () => {
          const {gameAudioEvents} = await import('./src/js/gameAudio.js');
          const previous = {move_log: ['start'], table_messages: [], state: {battlefield: []}};
          const land = {name: 'Forest', instance_id: 1, type_line: 'Basic Land — Forest', tapped: true};
          const next = structuredClone(previous);
          next.move_log.push('play_land: Forest');
          next.state.battlefield.push(land);
          next.table_messages.push({id: 1, kind: 'action', action: 'play_land', card_name: 'Forest'});
          const effectEntry = structuredClone(next);
          effectEntry.table_messages = [];
          return {
            play: gameAudioEvents(previous, next).map(e => e.kind),
            effectEntry: gameAudioEvents(previous, effectEntry),
            reconnect: gameAudioEvents(next, structuredClone(next)),
            undo: gameAudioEvents(next, previous),
            initial: gameAudioEvents(null, next)
          };
        }''')
        self.assertEqual(result['play'], ['land'])
        for key in ('effectEntry', 'reconnect', 'undo', 'initial'):
            self.assertEqual(result[key], [])

    def test_committed_events_and_silent_reconnect_undo(self):
        result = self.page.evaluate('''async () => {
          const {gameAudioEvents} = await import('./src/js/gameAudio.js');
          const old = {move_log: ['start'], table_messages: [], state: {
            battlefield: [{instance_id: 1, name: 'Source', tapped: false, mana_cost: '{W}{U}'}],
            players: [], stats: {timeline: []}
          }};
          const next = structuredClone(old);
          next.move_log.push('activate_ability: Source');
          next.state.battlefield[0].tapped = true;
          next.table_messages.push({id: 1, kind: 'action', action: 'activate_ability', card_name: 'Source'});
          next.state.stats.timeline.push({kind: 'damage_dealt', amount: 6});
          const events = gameAudioEvents(old,next);
          const undo = gameAudioEvents(next,old);
          const reconnect = gameAudioEvents(next,structuredClone(next));
          const initial = gameAudioEvents(null,next);
          return {events,undo,reconnect,initial};
        }''')
        self.assertEqual([e['kind'] for e in result['events']], ['tap', 'activate', 'damage'])
        self.assertEqual(result['events'][-1]['amount'], 6)
        for key in ('undo', 'reconnect', 'initial'):
            self.assertEqual(result[key], [])


if __name__ == '__main__':
    unittest.main()
