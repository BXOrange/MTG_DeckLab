"""Strategic decisions and full-engine play by the additional bot."""
import random

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.bot_strategy import build_strategy
from mtg_analyzer.services.bots import SmartBot, GoldfishBot, run_bots, _one_bot_action
from tests.services.test_bots import bear, land, make_game, keep, drive


def spell(name, text='', cost='{G}', mv=1, types='Sorcery', identity=None):
    return Card(id=name, name=name, oracle_text=text, type_line=types,
                mana_cost_string=cost, converted_mana_cost=mv, color_identity=identity or {'G'},
                is_instant=types == 'Instant', is_sorcery=types == 'Sorcery')


def view(hand=None, board=None, command=None, stack=None):
    return {'setup': {'complete': True}, 'pending_choice': None,
            'state': {'active_player_id': 'ann', 'priority_player_id': 'ann',
                      'current_step': 'main1', 'internal_turn': {'number': 1},
                      'stack': stack or [], 'battlefield': board or [],
                      'players': [{'id': 'ann', 'life': 40, 'mana_pool': {},
                                   'hand': hand or [], 'command': command or [], 'library': []},
                                  {'id': 'bob', 'life': 40, 'hand': [], 'library': []}]}}


def obj(i, name, owner='ann', **attrs):
    return {'instance_id': i, 'name': name, 'controller_id': owner, **attrs}


def combo():
    return [{'uses': [{'name': 'Engine'}, {'name': 'Outlet'}],
             'produces': ['Infinite damage'], 'requirements': []}]


def bot():
    b = SmartBot('ann')
    b.strategy = build_strategy([spell('Engine', types='Enchantment'),
                                 spell('Outlet', types='Artifact'), bear('Bear'), land()], [], combo())
    return b


def test_strategy_detects_identity_commander_themes_and_quantities():
    commander = spell('Token Commander', 'Whenever you cast a noncreature spell, create a 1/1 token.',
                      identity={'R', 'W'}, types='Legendary Creature')
    strategy = build_strategy([land(), bear()], [commander], combos=[])
    assert strategy.identity == {'R', 'W', 'G'}
    assert strategy.commanders == {'token commander'}
    assert {'tokens', 'spellslinger'} <= strategy.themes
    conditional = combo()[0] | {'requirements': ['Any creature']}
    quantity = combo()[0] | {'uses': [{'name': 'Engine', 'quantity': 2}, {'name': 'Outlet'}]}
    assert not build_strategy([spell('Engine'), spell('Outlet')], [], [conditional, quantity]).combos


def test_combo_piece_beats_unrelated_cheap_spell():
    b = bot()
    v = view(hand=[obj(1, 'Outlet'), obj(2, 'Bear')], board=[obj(3, 'Engine')])
    actions = [{'type': 'cast_spell', 'instance_id': 2, 'mana_value': 1},
               {'type': 'cast_spell', 'instance_id': 1, 'mana_value': 4}]
    assert b.play(v, actions)['instance_id'] == 1


def test_tutor_finds_missing_piece_instead_of_duplicate():
    b = bot()
    v = view(board=[obj(3, 'Engine')])
    v['pending_choice'] = {'kind': 'search'}
    answers = [{'type': 'decline'}, {'type': 'choose', 'option_id': '1', 'name': 'Engine'},
               {'type': 'choose', 'option_id': '2', 'name': 'Outlet'}]
    assert b.answer_choice(v, answers)['option_id'] == '2'


def test_library_contents_never_count_as_combo_progress():
    b = bot()
    v = view()
    baseline = b._combo_value(v, 'Outlet')
    v['state']['players'][0]['library'] = [obj(5, 'Engine')]
    assert b._combo_value(v, 'Outlet') == baseline


def test_pregame_exile_preserves_combo_piece_over_unrelated_card():
    b = bot()
    v = view(hand=[obj(1, 'Outlet'), obj(2, 'Bear')])
    v['state']['current_step'] = ''
    v['pending_choice'] = {'kind': 'choose_objects', 'action': 'exile'}
    answers = [{'type': 'choose', 'option_id': str(i), 'instance_id': i}
               for i in (1, 2)]
    assert b.answer_choice(v, answers)['instance_id'] == 2


def test_land_selection_fixes_colours_needed_in_hand():
    b = SmartBot('ann')
    forest = spell('Forest', types='Basic Land — Forest', identity={'G'})
    island = spell('Island', types='Basic Land — Island', identity={'U'})
    blue = spell('Blue spell', cost='{U}{U}', identity={'U'})
    b.strategy = build_strategy([forest, island, blue], [], [])
    v = view(hand=[obj(1, 'Forest'), obj(2, 'Island'), obj(3, 'Blue spell')])
    actions = [{'type': 'play_land', 'instance_id': i, 'enters_tapped': False} for i in (1, 2)]
    assert b.play(v, actions)['instance_id'] == 2


def test_holds_counter_until_opponent_has_a_spell_and_targets_opponent():
    b = SmartBot('ann')
    b.strategy = build_strategy([spell('Counterspell', 'Counter target spell.', '{U}{U}', identity={'U'})], [], [])
    action = {'type': 'cast_spell', 'instance_id': 1, 'requires_target': True,
              'targets': [{'count': 1, 'polarity': 'harmful', 'options': [{'instance_id': 4}, {'instance_id': 5}]}]}
    v = view(hand=[obj(1, 'Counterspell')])
    assert b.play(v, [action]) is None
    v['state']['stack'] = [{'controller_id': 'ann', 'object': obj(4, 'Our spell')},
                           {'controller_id': 'bob', 'object': obj(5, 'Their spell', 'bob')}]
    chosen = b.play(v, [action])
    assert chosen['targets'] == [{'instance_id': 5}]
    v['state']['stack'].pop()
    assert b.play(v, [action]) is None


def test_preserves_combo_piece_in_combat_and_attacks_with_safe_creature():
    b = bot()
    defender = {'kind': 'player', 'id': 'bob'}
    v = view(board=[obj(1, 'Engine', is_creature=True, power=2, toughness=2),
                    obj(2, 'Bear', is_creature=True, power=2, toughness=2)])
    offers = [{'type': 'attack', 'instance_id': i, 'legal_defenders': [defender]} for i in (1, 2)]
    assert b.play(v, offers)['instance_ids'] == [2]
    v['state']['battlefield'].append(obj(3, 'Big blocker', 'bob', is_creature=True, power=5, toughness=5))
    assert b.play(v, offers) is None


def test_does_not_tap_unused_mana_or_remove_own_creatures():
    b = bot()
    v = view(board=[obj(1, 'Bear')])
    removal = {'type': 'cast_spell', 'instance_id': 9, 'requires_target': True,
               'targets': [{'polarity': 'harmful', 'options': [{'instance_id': 1}]}]}
    assert b.play(v, [removal, {'type': 'tap_for_mana', 'instance_id': 8}]) is None


def test_mulligan_and_london_bottom_are_bounded_and_keep_combo_piece():
    b = bot()
    v = view(hand=[obj(1, 'Engine')])
    v['setup'] = {'complete': False, 'mulligan_count': 0}
    actions = [{'type': 'mulligan'}, {'type': 'keep_hand', 'bottom_count': 0}]
    assert b.decide(v, actions) == {'type': 'mulligan'}
    v['setup']['mulligan_count'] = 2
    v['state']['players'][0]['hand'] = [obj(1, 'Engine'), obj(2, 'Bear'),
                                      obj(3, 'Forest', is_land=True), obj(4, 'Forest', is_land=True)]
    actions[1]['bottom_count'] = 1
    assert b.decide(v, actions)['bottom_instance_ids'] == [2]


def test_real_engine_smart_bot_casts_commander_develops_and_wins_combat():
    deck = [land()] * 20 + [bear(f'Bear{i}', '{G}', 1, 4, 4) for i in range(20)]
    random.Random(3).shuffle(deck)
    commander = bear('Commander', '{G}', 1, 4, 4)
    session = make_game(ann_deck=deck, bob_deck=[land()] * 80, ann_commanders=[commander])
    b = SmartBot('ann')
    keep(session, 'bob')
    drive(session, {'ann': b, 'bob': GoldfishBot('bob')}, limit=2000)
    assert b.strategy.commanders == {'commander'}
    assert session.engine.state.game_over
    assert session.engine.state.player_by_id('bob').has_lost
    assert any('Commander' in move for move in session.move_log)
    assert not b._failed


def test_local_missing_snapshot_never_downloads(monkeypatch, tmp_path):
    from mtg_analyzer.services import commander_spellbook_database as module
    db = module.CommanderSpellbookDatabase(tmp_path / 'missing.db')
    monkeypatch.setattr(module, 'CommanderSpellbookDatabase', lambda: db)
    monkeypatch.setattr(db, '_refresh', lambda: (_ for _ in ()).throw(AssertionError('network')))
    assert build_strategy([bear()], []).archetype == 'aggro'
    assert not (tmp_path / 'missing.db').exists()


def test_session_memory_survives_bot_rebuild_and_resets_on_restart():
    session = make_game()
    keep(session, 'bob')
    _one_bot_action(session, {'ann': SmartBot('ann')})
    session._smart_ability_uses['ann'][(1, ('activate_ability', 7))] = 64
    _one_bot_action(session, {'ann': SmartBot('ann')})
    assert session._smart_ability_uses['ann']
    session.restart()
    assert session._smart_ability_uses == {}


def test_real_engine_oracle_consultation_line_wins_with_trigger_on_stack():
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    from mtg_analyzer.models.game.game_object import GameObject, Zone

    island = Card(id='Island', name='Island', type_line='Basic Land — Island', is_land=True, color_identity={'U'})
    swamp = Card(id='Swamp', name='Swamp', type_line='Basic Land — Swamp', is_land=True, color_identity={'B'})
    oracle = Card(id='oracle', name="Thassa's Oracle", type_line='Creature — Merfolk Wizard',
                  is_creature=True, mana_cost_string='{U}{U}', converted_mana_cost=2,
                  color_identity={'U'}, power=1, toughness=3)
    consultation = spell('Demonic Consultation', cost='{B}', types='Instant', identity={'B'})
    session = make_game(ann_deck=[island] * 40, bob_deck=[land()] * 40)
    session._bot_decklists['ann'] = {'cards': [island] * 30 + [swamp] * 10 + [oracle, consultation], 'commanders': []}
    keep(session, 'ann', 'bob')
    state = session.engine.state
    ann = state.player_by_id('ann')
    # Construct the mana and hand for the real win sequence; the rest of
    # the game still runs exclusively through validated client actions.
    for c in (island, island, swamp):
        o = GameObject(c, owner_id='ann', zone=Zone.BATTLEFIELD)
        bind_from_catalogue(o)
        state.add_to_battlefield(o)
    for c in (oracle, consultation):
        o = GameObject(c, owner_id='ann', zone=Zone.HAND)
        bind_from_catalogue(o)
        ann.add_to_zone(o, Zone.HAND)
    b = SmartBot('ann')
    drive(session, {'ann': b}, human_ids=('bob',), limit=100)
    assert state.game_over, session.move_log
    assert not ann.has_lost
    assert state.player_by_id('bob').has_lost
    assert not ann.library
    assert not b._failed


def test_repeatable_ability_requires_actual_progress_and_is_bounded():
    b = bot()
    v = view(board=[obj(1, 'Engine'), obj(2, 'Outlet')])
    ability = {'type': 'activate_ability', 'instance_id': 2, 'ability_index': 0,
               'description': 'Deal 1 damage to each opponent.'}
    assert b.play(v, [ability]) is not None
    assert b.play(v, [ability]) is None
    v['state']['players'][1]['life'] -= 1
    assert b.play(v, [ability]) is not None
    v['state']['internal_turn']['number'] = 2
    assert b.play(v, [ability]) is not None


def test_combo_sacrifice_outlet_waits_for_other_piece_then_activates():
    b = bot()
    b.strategy = build_strategy([spell('Engine', types='Enchantment'),
                                 spell('Outlet', 'Sacrifice another creature: Draw a card.', types='Artifact')], [], combo())
    ability = {'type': 'activate_ability', 'instance_id': 2, 'ability_index': 0,
               'description': 'Draw a card.'}
    v = view(board=[obj(2, 'Outlet')])
    assert b.play(v, [ability]) is None
    v['state']['battlefield'].append(obj(1, 'Engine'))
    assert b.play(v, [ability]) is not None


def test_oracle_waits_for_coherent_blue_blue_black_mana():
    b = SmartBot('ann')
    oracle = spell("Thassa's Oracle", cost='{U}{U}', types='Creature', identity={'U'})
    consultation = spell('Demonic Consultation', cost='{B}', types='Instant', identity={'B'})
    b.strategy = build_strategy([oracle, consultation], [], [])
    v = view(hand=[obj(1, "Thassa's Oracle"), obj(2, 'Demonic Consultation')])
    v['state']['players'][0]['library_count'] = 30
    # Two dual lands may each offer either colour; independent maxima
    # would incorrectly claim UU+B could be paid by only two sources.
    v['mana_potential'] = {'ann': {'open': {'U': 2, 'B': 2}, 'variations': [
        {'mana': {'U': 2}}, {'mana': {'U': 1, 'B': 1}}, {'mana': {'B': 2}}]}}
    actions = [{'type': 'cast_spell', 'instance_id': i} for i in (1, 2)]
    assert b.play(v, actions) is None
    v['mana_potential']['ann']['variations'].append({'mana': {'U': 2, 'B': 1}})
    assert b.play(v, actions)['instance_id'] == 1


def test_initialized_local_spellbook_snapshot_drives_profile(monkeypatch, tmp_path):
    from mtg_analyzer.services import commander_spellbook_database as module
    from tests.services.test_commander_spellbook_database import _variant, _write_snapshot
    db = module.CommanderSpellbookDatabase(tmp_path / 'combos.db')
    snapshot = _write_snapshot(tmp_path / 'snapshot.gz', [
        _variant('matched', [('Engine', 1), ('Outlet', 1)], produces=['Infinite damage']),
        _variant('conditional', [('Engine', 1)], requirements=['Any artifact']),
        _variant('absent', [('Engine', 1), ('Missing', 1)])])
    db.ingest_snapshot(snapshot)
    monkeypatch.setattr(module, 'CommanderSpellbookDatabase', lambda: db)
    monkeypatch.setattr(db, '_refresh', lambda: (_ for _ in ()).throw(AssertionError('network')))
    strategy = build_strategy([spell('Engine'), spell('Outlet')], [])
    assert strategy.archetype == 'combo'
    assert len(strategy.combos) == 1
    assert strategy.combos[0].pieces == (('engine', 1), ('outlet', 1))
    assert strategy.combos[0].outputs == ('Infinite damage',)


def test_multiplayer_attack_prefers_low_life_and_blocks_deathtouch_carefully():
    b = bot()
    defenders = [{'kind': 'player', 'id': 'bob'}, {'kind': 'player', 'id': 'cara'}]
    v = view(board=[obj(1, 'Bear', is_creature=True, power=2, toughness=2)])
    v['state']['players'].append({'id': 'cara', 'life': 2})
    action = {'type': 'attack', 'instance_id': 1, 'legal_defenders': defenders}
    assert b.play(v, [action])['defender']['id'] == 'cara'
    v['state']['battlefield'].append(obj(2, 'Snake', 'bob', power=1, toughness=4, keywords=['Deathtouch']))
    assert b.blocks(v, [{'type': 'declare_blockers', 'instance_id': 1,
                       'legal_attackers': [{'instance_id': 2}]}]) == []


def test_sacrifice_choice_preserves_combo_piece_and_uses_fodder():
    b = bot()
    v = view(board=[obj(1, 'Engine'), obj(2, 'Bear')])
    v['pending_choice'] = {'kind': 'choose_objects', 'action': 'sacrifice'}
    answers = [{'type': 'choose', 'option_id': str(i), 'instance_id': i} for i in (1, 2)]
    assert b.answer_choice(v, answers)['instance_id'] == 2


# -- BUG-3: combo pieces / commander were never cast ------------------------

KINNAN_COST = '{G}{U}'


def kinnan_bot(*extra):
    b = SmartBot('ann')
    kinnan = spell('Kinnan', 'Whenever you tap a nonland permanent for mana, add one mana.',
                   KINNAN_COST, 2, 'Legendary Creature — Human Druid', {'G', 'U'})
    b.strategy = build_strategy([land(), *extra], [kinnan], [])
    return b


def petal_actions():
    """Soporific Springs ({U}) and Lotus Petal (any colour, sacrificed)."""
    petal = [{'index': i, 'mana': {c: 1}} for i, c in enumerate('WUBRG')]
    return [{'type': 'tap_for_mana', 'instance_id': 10, 'name': 'Springs', 'ability_index': 0,
             'cost_label': '{T}', 'options': [{'index': 0, 'mana': {'U': 1}}]},
            {'type': 'tap_for_mana', 'instance_id': 11, 'name': 'Lotus Petal', 'ability_index': 0,
             'cost_label': '{T}, Sacrifice ~', 'options': petal}]


def kinnan_view(variations, casts=None):
    v = view(command=[obj(1, 'Kinnan')], board=[obj(10, 'Springs'), obj(11, 'Lotus Petal')])
    v['mana_potential'] = {'ann': {'open': {'U': 2, 'G': 1}, 'variations': variations}}
    if casts is not None:
        v['state']['players'][0]['commander_casts'] = casts
    return v


def test_commander_unlocked_by_sacrifice_mana_the_engine_does_not_offer():
    b = kinnan_bot()
    v = kinnan_view([{'mana': {'U': 1, 'G': 1}, 'total': 2}])
    tap = b.play(v, petal_actions())
    # The scarcest missing colour (G) comes from the Petal, not from the land.
    assert (tap['type'], tap['instance_id'], tap['option_index']) == ('tap_for_mana', 11, 4)
    # One unlock per card and turn: an unexpected refusal cannot burn sources.
    assert b.play(v, petal_actions()) is None


def test_commander_not_unlocked_when_unaffordable_or_taxed():
    b = kinnan_bot()
    assert b.play(kinnan_view([{'mana': {'U': 2}, 'total': 2}]), petal_actions()) is None
    taxed = kinnan_view([{'mana': {'U': 1, 'G': 1}, 'total': 2}], casts={'1': 1})
    assert kinnan_bot().play(taxed, petal_actions()) is None  # {G}{U} + {2} tax needs 4 mana


def test_offered_commander_is_cast_instead_of_tapping_a_source():
    b = kinnan_bot()
    v = kinnan_view([{'mana': {'U': 1, 'G': 1}, 'total': 2}])
    cast = {'type': 'cast_spell', 'instance_id': 1, 'mana_value': 2}
    assert b.play(v, [cast, *petal_actions()])['type'] == 'cast_spell'


def test_one_shot_mana_is_not_wasted_on_a_non_key_card():
    b = kinnan_bot(spell('Bear', cost='{G}', identity={'G'}, types='Creature'))
    v = kinnan_view([{'mana': {'U': 1, 'G': 1}, 'total': 2}])
    v['state']['players'][0]['command'] = []
    v['state']['players'][0]['hand'] = [obj(2, 'Bear')]
    assert b.play(v, petal_actions()) is None


def test_hand_mana_source_can_unlock_a_key_permanent():
    b = kinnan_bot()
    v = kinnan_view([{'mana': {'U': 1, 'G': 1}, 'total': 2}])
    guide = {'type': 'activate_hand_mana', 'instance_id': 12, 'name': 'Elvish Spirit Guide',
             'ability_index': 0, 'cost_label': 'Exile from hand',
             'options': [{'index': 0, 'mana': {'G': 1}}]}
    acts = [petal_actions()[0], guide]
    assert b.play(v, acts)['type'] == 'activate_hand_mana'


def shock_choice(life=40, hand=True):
    v = view(hand=[obj(1, 'Bear')] if hand else [])
    v['state']['players'][0]['life'] = life
    v['pending_choice'] = {'kind': 'land_tapped'}
    return v, [{'type': 'choose', 'option_id': 'pay'}, {'type': 'decline'}]


def test_shock_land_is_paid_for_only_when_the_mana_is_needed_and_life_allows():
    b = bot()
    v, answers = shock_choice()
    assert b.answer_choice(v, answers)['option_id'] == 'pay'
    v, answers = shock_choice(life=8)
    assert b.answer_choice(v, answers)['type'] == 'decline'
    v, answers = shock_choice(hand=False)
    assert b.answer_choice(v, answers)['type'] == 'decline'


def test_reveal_land_always_reveals():
    v = view(); v['pending_choice'] = {'kind': 'land_tapped_reveal'}
    answers = [{'type': 'choose', 'option_id': 'reveal'}, {'type': 'decline'}]
    assert bot().answer_choice(v, answers)['option_id'] == 'reveal'


def test_mox_diamond_discards_a_land_instead_of_losing_itself():
    v = view(hand=[obj(5, 'Forest'), obj(6, 'Island')])
    v['pending_choice'] = {'kind': 'enter_or_graveyard'}
    answers = [{'type': 'choose', 'option_id': '5', 'instance_id': 5},
               {'type': 'choose', 'option_id': '6', 'instance_id': 6}, {'type': 'decline'}]
    assert bot().answer_choice(v, answers)['type'] == 'choose'


def test_mox_diamond_is_cast_only_with_a_land_to_spare():
    mox = spell('Mox Diamond', 'If Mox Diamond would enter the battlefield, you may discard a land card instead.',
                '{0}', 0, 'Artifact', set())
    b = SmartBot('ann')
    b.strategy = build_strategy([mox, land()], [], [])
    cast = [{'type': 'cast_spell', 'instance_id': 1, 'mana_value': 0}]
    assert b.play(view(hand=[obj(1, 'Mox Diamond')]), cast) is None
    spare = view(hand=[obj(1, 'Mox Diamond'), obj(2, 'Forest', is_land=True), obj(3, 'Forest', is_land=True)])
    assert b.play(spare, cast)['instance_id'] == 1


def mulligan_view(hand):
    v = view(hand=hand)
    v['setup'] = {'complete': False, 'mulligan_count': 0}
    return v


def test_mulligan_counts_cheap_mana_sources_not_only_lands():
    sol = spell('Sol Ring', 'T: Add {C}{C}.', '{1}', 1, 'Artifact', set())
    b = SmartBot('ann')
    b.strategy = build_strategy([land(), sol, bear('Bear')], [], [])
    actions = [{'type': 'mulligan'}, {'type': 'keep_hand', 'bottom_count': 0}]
    forest = lambda i: obj(i, 'Forest', is_land=True)
    keep_hand = [forest(1), obj(2, 'Sol Ring')] + [obj(i, 'Bear') for i in range(3, 8)]
    assert b.setup(mulligan_view(keep_hand), actions)['type'] == 'keep_hand'
    no_sources = [forest(1)] + [obj(i, 'Bear') for i in range(3, 9)]
    assert b.setup(mulligan_view(no_sources), actions)['type'] == 'mulligan'
    no_land = [obj(2, 'Sol Ring')] + [obj(i, 'Bear') for i in range(3, 9)]
    assert b.setup(mulligan_view(no_land), actions)['type'] == 'mulligan'


def test_fetch_land_is_not_a_tutor_and_does_not_outscore_a_combo_piece():
    fetch = Card(id='Strand', name='Flooded Strand', type_line='Land', is_land=True,
                 oracle_text='{T}, Pay 1 life, Sacrifice Flooded Strand: Search your library for a Plains or Island card.')
    strategy = build_strategy([fetch], [], combo())
    assert 'tutor' not in strategy.cards['flooded strand'].roles


def test_land_mana_ability_is_not_activated_for_nothing():
    grove = Card(id='Grove', name='Waterlogged Grove', type_line='Land', is_land=True,
                 oracle_text='{T}, Pay 1 life: Add {G} or {U}.')
    b = SmartBot('ann')
    b.strategy = build_strategy([grove], [], [])
    v = view(board=[obj(1, 'Waterlogged Grove', is_land=True)])
    assert b.play(v, [{'type': 'activate_ability', 'instance_id': 1, 'ability_index': 0}]) is None


def test_cost_requirements_and_public_commander_casts():
    from collections import Counter
    from mtg_analyzer.models.game.player import Player
    from mtg_analyzer.services.bot_strategy import cost_requirements
    assert cost_requirements('{2}{G}{U}{X}') == (Counter({'G': 1, 'U': 1}), 2)
    assert cost_requirements('{G/U}{C}') == (Counter({'C': 1}), 1)
    player = Player('ann'); player.commander_casts[7] = 2
    assert player.to_dict()['commander_casts'] == {'7': 2}
