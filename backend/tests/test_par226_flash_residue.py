"""PAR-226 residue: temporary (until your next turn), owned-card, conditional-standing and free-cast flash forms.

RULE 702.8 / 601.3b timing permissions, composed from the existing `flash_permission` static, `grant_until`
durations (RULE 611.2b) and `free_cast_condition`; each form is parsed and then executed through `GameEngine.can_cast`.
"""
from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.continuous import has_standing_flash_permission
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_hooks import parse_effect_body
from mtg_analyzer.parser.oracle.gate import parse_oracle


def engine(step='declare_attackers'):
    eng = GameEngine.new_game([('p1', 'Alice', []), ('p2', 'Bob', [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = step  # combat: only flash-speed casts are legal (RULE 307.1 / 702.8a)
    return eng


def put(eng, name, type_line, text='', zone=Zone.BATTLEFIELD, owner='p1', **kw):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, **kw)
    obj = GameObject(card, owner_id=owner, zone=zone)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    elif zone == Zone.HAND:
        eng.state.player_by_id(owner).add_to_zone(obj, Zone.HAND)
    return obj


def hand(eng, name, type_line, text='', owner='p1', **kw):
    return put(eng, name, type_line, text, zone=Zone.HAND, owner=owner, **kw)


def effect_types(text, type_line='Creature — Bear'):
    creature_card = type_line.startswith('Creature')
    result = parse_oracle(Card(id='x', name='Probe Card', type_line=type_line, oracle_text=text,
                               is_creature=creature_card, is_instant=type_line == 'Instant',
                               **({'power': 2, 'toughness': 2} if creature_card else {})))
    return result, [(e.type, e.params) for a in result.specs for e in a.effects]


def creature(eng, name, owner='p1', subtype='Bear', **kw):
    return hand(eng, name, f'Creature — {subtype}', owner=owner, is_creature=True, power=2, toughness=2,
                mana_cost_string='{G}', **kw)


# -- until your next turn ---------------------------------------------------------------------------------------


def test_until_next_turn_flash_parses_to_floating_flash_permission():
    specs = parse_effect_body('until your next turn, you may cast sorcery spells as though they had flash')
    assert [(s.type, s.params) for s in specs] == [('grant_until', {
        'target_kind': None, 'duration': 'your_next_turn',
        'static': {'type': 'flash_permission', 'params': {'type_filter': ['sorcery']}}})]
    # A one-turn clock stays the existing temporary-flash row (no floating static needed).
    eot = parse_effect_body('you may cast sorcery spells this turn as though they had flash')
    assert eot[0].type != 'grant_until'


def test_arlinn_plus_one_flash_and_counter_run_until_your_next_turn():
    result, effects = effect_types(
        '+1: Until your next turn, you may cast creature spells as though they had flash, and each creature you '
        'control enters with an additional +1/+1 counter on it.')
    assert result.modeled
    assert [e[0] for e in effects] == ['grant_until', 'grant_until']
    assert {e[1]['duration'] for e in effects} == {'your_next_turn'}
    assert [e[1]['static']['type'] for e in effects] == ['flash_permission', 'extra_etb_counter']

    eng = engine()
    walker = put(eng, 'Arlinn Probe', 'Planeswalker — Arlinn')
    bear = creature(eng, 'Bear')
    sorcery = hand(eng, 'Plan', 'Sorcery', is_sorcery=True, mana_cost_string='{G}')
    p1 = eng.state.player_by_id('p1')
    assert not has_standing_flash_permission(eng.state, p1, bear.card, bear)
    specs = parse_effect_body(
        'until your next turn, you may cast creature spells as though they had flash, and each creature you control '
        'enters with an additional +1/+1 counter on it')
    for effect in build_effects(specs, walker):
        effect.apply(GameContext(eng.state, eng.rules), None)
    eng.recompute_continuous_effects()
    assert has_standing_flash_permission(eng.state, p1, bear.card, bear)
    assert not has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)  # creature spells only
    assert not has_standing_flash_permission(eng.state, eng.state.player_by_id('p2'), bear.card, bear)
    assert continuous.extra_etb_counters_for(eng.state, bear) == {'+1/+1': 1}
    # RULE 611.2b: both lapse when p1's next turn begins, not at the end of the turn they were made in.
    eng.state.internal_turn.number = 1
    eng.begin_turn()
    assert has_standing_flash_permission(eng.state, p1, bear.card, bear)
    eng.begin_turn()
    assert not has_standing_flash_permission(eng.state, p1, bear.card, bear)
    assert continuous.extra_etb_counters_for(eng.state, bear) == {}


# -- owned cards / familiar spells / sorcery-timing restriction -------------------------------------------------


def test_teferi_mage_owned_creature_cards_have_flash_and_opponents_are_sorcery_speed():
    result, effects = effect_types(
        "Creature cards you own that aren't on the battlefield have flash.\n"
        'Each opponent can cast spells only any time they could cast a sorcery.')
    assert result.modeled
    assert [e[0] for e in effects] == ['flash_permission', 'sorcery_speed_only']
    eng = engine()
    put(eng, 'Teferi Probe', 'Legendary Creature — Human Wizard',
        "Creature cards you own that aren't on the battlefield have flash.\n"
        'Each opponent can cast spells only any time they could cast a sorcery.',
        is_creature=True, power=3, toughness=4)
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    mine = creature(eng, 'Mine')
    theirs = creature(eng, 'Theirs', owner='p2')
    sorcery = hand(eng, 'Plan', 'Sorcery', is_sorcery=True, mana_cost_string='{G}')
    assert has_standing_flash_permission(eng.state, p1, mine.card, mine)
    assert not has_standing_flash_permission(eng.state, p1, mine.card)  # owner unknown: fail closed
    assert not has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)
    assert not has_standing_flash_permission(eng.state, p2, theirs.card, theirs)  # the grant is p1's, owner scope
    assert continuous.forced_sorcery_speed_only(eng.state, p2)
    assert not continuous.forced_sorcery_speed_only(eng.state, p1)


def test_owned_card_scope_excludes_a_creature_the_caster_does_not_own():
    eng = engine()
    put(eng, 'Teferi Probe', 'Legendary Creature — Human Wizard',
        "Creature cards you own that aren't on the battlefield have flash.", is_creature=True, power=3, toughness=4)
    p1 = eng.state.player_by_id('p1')
    borrowed = creature(eng, 'Borrowed', owner='p2')
    borrowed.controller_id = 'p1'
    assert not has_standing_flash_permission(eng.state, p1, borrowed.card, borrowed)


def test_chea_familiar_spells_have_flash():
    _, effects = effect_types('Familiar spells you cast have flash.')
    assert effects == [('flash_permission', {'type_filter': ['familiar']})]
    eng = engine()
    put(eng, 'Chea Probe', 'Legendary Creature — Elf Druid', 'Familiar spells you cast have flash.',
        is_creature=True, power=1, toughness=1)
    p1 = eng.state.player_by_id('p1')
    cat = creature(eng, 'Plain Cat', subtype='Cat')
    named = creature(eng, "Witch's Familiar", subtype='Frog')
    named.card.type_line = 'Creature — Goblin'  # the name alone makes it a familiar
    bear = creature(eng, 'Bear')
    assert has_standing_flash_permission(eng.state, p1, cat.card, cat)
    assert has_standing_flash_permission(eng.state, p1, named.card, named)
    assert not has_standing_flash_permission(eng.state, p1, bear.card, bear)


# -- conditional standing and self flash ------------------------------------------------------------------------


def test_conditions_parse_to_whitelisted_kinds():
    _, mar_vell = effect_types('As long as an opponent has cast a spell this turn, you may cast spells as though they had flash.')
    assert mar_vell == [('flash_permission', {'active_if': {'kind': 'opponent_cast_spell_this_turn'}})]
    _, kianne = effect_types("As long as ~'s power is even, you may cast noncreature spells as though they had flash.")
    assert kianne[0][1]['active_if'] == {'kind': 'power_parity', 'parity': 'even'}
    _, phantom = effect_types("During each opponent's end step, you may cast spells as though they had flash.")
    assert phantom[0][1]['active_if'] == {'kind': 'all', 'conditions': [
        {'kind': 'not_your_turn'}, {'kind': 'during_step', 'step': 'end'}]}
    _, spirit = effect_types('You may cast the first creature spell you cast each turn as though it had flash.')
    assert spirit == [('flash_permission', {'creature_only': True, 'active_if': {'kind': 'first_creature_spell_this_turn'}})]


def test_kianne_power_parity_gates_the_permission():
    text = "As long as ~'s power is even, you may cast noncreature spells as though they had flash."
    for power, expected in ((2, True), (3, False), (0, True)):
        eng = engine()
        put(eng, 'Kianne Probe', 'Legendary Creature — Human', text, is_creature=True, power=power, toughness=2)
        p1 = eng.state.player_by_id('p1')
        sorcery = hand(eng, 'Plan', 'Sorcery', is_sorcery=True, mana_cost_string='{G}')
        eng.recompute_continuous_effects()
        assert has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery) is expected, power


def test_final_word_phantom_only_in_an_opponents_end_step():
    eng = engine()
    put(eng, 'Phantom Probe', 'Creature — Spirit', "During each opponent's end step, you may cast spells as though "
        'they had flash.', is_creature=True, power=2, toughness=2)
    p1 = eng.state.player_by_id('p1')
    sorcery = hand(eng, 'Plan', 'Sorcery', is_sorcery=True, mana_cost_string='{G}')
    eng.state.current_step = 'end'
    assert not has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)  # my own end step
    eng.state.active_player_index = 1
    assert has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)
    eng.state.current_step = 'main2'
    assert not has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)


def test_blue_spirit_first_creature_spell_only():
    eng = engine()
    put(eng, 'Spirit Probe', 'Creature — Spirit',
        'You may cast the first creature spell you cast each turn as though it had flash.',
        is_creature=True, power=2, toughness=2)
    p1 = eng.state.player_by_id('p1')
    bear = creature(eng, 'Bear')
    p1.mana_pool.add('G', 1)
    assert eng.can_cast(p1, bear)
    eng.cast_spell(p1, bear)
    second = creature(eng, 'Second')
    p1.mana_pool.add('G', 1)
    assert not eng.can_cast(p1, second)


def test_graveyard_shift_and_hungering_yeti_self_flash_conditions():
    shift = parse_oracle(Card(
        id='gs', name='Graveyard Shift', type_line='Sorcery', is_sorcery=True,
        oracle_text='This spell has flash as long as there are 5 or more mana values among cards in your graveyard.'))
    flashes = [a.conditional_flash for a in shift.specs if a.conditional_flash]
    assert flashes == [{'active_if': {'kind': 'distinct_mana_values_in_graveyard_at_least', 'min': 5}}]
    yeti = parse_oracle(Card(
        id='hy', name='Hungering Yeti', type_line='Creature — Yeti', is_creature=True, power=4, toughness=4,
        oracle_text='As long as you control a green or blue permanent, you may cast this spell as though it had flash.'))
    gate = [a.conditional_flash for a in yeti.specs if a.conditional_flash][0]['active_if']
    assert gate['kind'] == 'control_count'
    assert gate['selector']['filter'] == {'color_any': ['G', 'U']}

    eng = engine()
    spell = hand(eng, 'Shift', 'Sorcery', 'This spell has flash as long as there are 5 or more mana values among '
                 'cards in your graveyard.', is_sorcery=True, mana_cost_string='{G}')
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('G', 1)
    assert not eng.can_cast(p1, spell)
    for mv in range(5):
        filler = put(eng, f'Filler{mv}', 'Artifact', zone=Zone.GRAVEYARD, mana_cost_string='{%d}' % mv, converted_mana_cost=mv)
        p1.graveyard.append(filler)
    assert eng.can_cast(p1, spell)


def test_ride_the_avalanche_parses_next_spell_flash_and_counter_rider():
    result, effects = effect_types(
        'The next spell you cast this turn can be cast as though it had flash. When you next cast a spell this turn, '
        'put X +1/+1 counters on up to one target creature, where X is the mana value of that spell.', type_line='Instant')
    assert result.modeled
    assert [e[0] for e in effects] == ['grant_flash_until_eot', 'create_turn_trigger']
    assert effects[1][1]['once'] is True
    assert effects[1][1]['effects'][0]['params']['amount_from_trigger_event'] == 'mana_value'


# -- Qasali Ambusher: free cast + bundled flash -----------------------------------------------------------------


def test_qasali_ambusher_free_flash_cast_needs_attacker_forest_and_plains():
    eng = engine()
    ambusher = hand(eng, 'Qasali Ambusher', 'Creature — Cat Archer', is_creature=True, power=2, toughness=3,
                    mana_cost_string='{3}{G}')
    p1 = eng.state.player_by_id('p1')
    assert not eng.can_cast(p1, ambusher, free=True)  # nothing attacking, no lands
    forest = put(eng, 'Forest', 'Basic Land — Forest', is_land=True)
    plains = put(eng, 'Plains', 'Basic Land — Plains', is_land=True)
    attacker = put(eng, 'Raider', 'Creature — Goblin', is_creature=True, power=2, toughness=2, owner='p2')
    attacker.attacking = True
    attacker.combat_defender = {'kind': 'player', 'id': 'p2'}
    assert not eng.can_cast(p1, ambusher, free=True)  # attacking the wrong player
    attacker.combat_defender = {'kind': 'player', 'id': 'p1'}
    assert eng.can_cast(p1, ambusher, free=True)
    # RULE 702.8: the flash is part of the free permission only; the printed {3}{G} cast keeps sorcery timing.
    p1.mana_pool.add('G', 4)
    assert not eng.can_cast(p1, ambusher)
    plains.zone = Zone.GRAVEYARD
    eng.state.battlefield.remove(plains)
    assert not eng.can_cast(p1, ambusher, free=True)  # a Forest alone is not enough
    assert forest in eng.state.battlefield


def test_hungering_yeti_flashes_only_with_a_green_or_blue_permanent():
    eng = engine()
    yeti = hand(eng, 'Yeti', 'Creature — Yeti',
                'As long as you control a green or blue permanent, you may cast this spell as though it had flash.',
                is_creature=True, power=4, toughness=4, mana_cost_string='{G}')
    p1 = eng.state.player_by_id('p1')
    p1.mana_pool.add('G', 1)
    put(eng, 'Red Guy', 'Creature — Goblin', is_creature=True, power=1, toughness=1, mana_cost_string='{R}')
    assert not eng.can_cast(p1, yeti)
    put(eng, 'Blue Guy', 'Creature — Merfolk', is_creature=True, power=1, toughness=1, mana_cost_string='{U}')
    assert eng.can_cast(p1, yeti)


def test_captain_mar_vell_flashes_after_an_opponent_casts():
    eng = engine()
    put(eng, 'Mar-Vell Probe', 'Creature — Kree', 'As long as an opponent has cast a spell this turn, you may cast '
        'spells as though they had flash.', is_creature=True, power=2, toughness=2)
    p1, p2 = eng.state.player_by_id('p1'), eng.state.player_by_id('p2')
    sorcery = hand(eng, 'Plan', 'Sorcery', is_sorcery=True, mana_cost_string='{G}')
    bolt = hand(eng, 'Bolt', 'Instant', owner='p2', is_instant=True, mana_cost_string='{R}')
    assert not has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)
    p2.mana_pool.add('R', 1)
    eng.cast_spell(p2, bolt)
    assert has_standing_flash_permission(eng.state, p1, sorcery.card, sorcery)
