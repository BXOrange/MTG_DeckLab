"""Gameplay regressions for Sans Soleil MWI catalogue coverage."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "",
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 3, "U": 3, "B": 3, "R": 3, "G": 3, "C": 5}




def _spell(engine, name='Test spell', player='p2', zone=Zone.HAND, kind='Instant', mv=0):
    return _filler(engine, name, kind, player=player, zone=zone, mv=mv)


def _stack_spell(engine, player='p2', mv=0):
    obj = _spell(engine, player=player, mv=mv)
    p = engine.state.player_by_id(player)
    p.mana_pool.add_many({'C': mv})
    engine.cast_spell(p, obj)
    return obj


@pytest.mark.parametrize('name,gift', [('Reprieve', False), ("Bilbo's Gambit", False), ("Bilbo's Gambit", True)])
def test_spell_bounce_ignores_uncounterability_and_gift_locks_every_player(name, gift):
    e = _game()
    victim = _stack_spell(e)
    victim.cant_be_countered = True
    old = len(e.state.player_by_id('p1').hand)
    _cast(e, _card(e, name, zone=Zone.HAND), RICH, [victim], gift_opponent_id='p2' if gift else None)
    assert victim.zone == Zone.HAND and not e.state.stack
    if name == 'Reprieve':
        assert len(e.state.player_by_id('p1').hand) == old + 1
    for pid in ('p1', 'p2'):
        assert e.can_cast(e.state.player_by_id(pid), _spell(e, player=pid)) == (not gift)


def test_abeyance_restricts_only_chosen_player_instant_sorcery_and_nonmana_abilities():
    e = _game()
    p2 = e.state.player_by_id('p2')
    source = _card(e, 'Fomori Vault', 'p2')
    _spell(e, player='p2')  # discard cost
    p2.mana_pool.add_many(RICH)
    _cast(e, _card(e, 'Abeyance', zone=Zone.HAND), RICH, [p2])
    assert not e.can_cast(p2, _spell(e, player='p2'))
    assert e.can_cast(e.state.player_by_id('p1'), _spell(e, player='p1'))
    assert not e.can_activate(p2, source, source.activated_abilities[0])
    e.tap_for_mana(p2, source)
    assert source.tapped
    e._step_cleanup()
    assert e.can_cast(p2, p2.hand[0])


@pytest.mark.parametrize('kicked', [0, 1])
def test_orims_chant_target_lock_and_kicked_attack_ban(kicked):
    e = _game()
    p2 = e.state.player_by_id('p2')
    bear = _filler(e, power=2, toughness=2)
    _cast(e, _card(e, "Orim's Chant", zone=Zone.HAND), RICH, [p2], kicked=kicked)
    assert not e.can_cast(p2, _spell(e, player='p2'))
    assert combat.has(bear, 'cant_attack') == bool(kicked)
    later = _filler(e, 'Later', power=2, toughness=2)
    e.recompute_continuous_effects()
    assert combat.has(later, 'cant_attack') == bool(kicked)


def test_calamitys_wake_exiles_all_graveyards_and_itself_but_allows_creatures():
    e = _game()
    gy = [_spell(e, player=p, zone=Zone.GRAVEYARD) for p in ('p1', 'p2')]
    spell = _card(e, "Calamity's Wake", zone=Zone.HAND)
    _cast(e, spell, RICH)
    assert spell.zone == Zone.EXILE and all(o.zone == Zone.EXILE for o in gy)
    assert not e.can_cast(e.state.player_by_id('p1'), _spell(e, player='p1'))
    assert e.can_cast(e.state.player_by_id('p1'), _filler(e, 'Bear spell', power=2, toughness=2, zone=Zone.HAND))


@pytest.mark.parametrize('type_line', ['Creature', 'Enchantment', 'Planeswalker'])
def test_get_lost_gives_the_targets_controller_two_functional_maps(type_line):
    e = _game()
    victim = _filler(e, 'Victim', type_line, 'p2', power=2 if type_line == 'Creature' else None, toughness=2 if type_line == 'Creature' else None)
    if type_line == 'Planeswalker':
        victim.counters['loyalty'] = 3
    _cast(e, _card(e, 'Get Lost', zone=Zone.HAND), RICH, [victim])
    assert victim.zone == Zone.GRAVEYARD
    maps = _named(e, 'Map', 'p2')
    assert len(maps) == 2
    explorer = _filler(e, 'Explorer', 'Creature', 'p2', power=2, toughness=2)
    p2 = e.state.player_by_id('p2')
    e.state.active_player_index = 1
    p2.mana_pool.add_many({'C': 1})
    _activate(e, maps[0], targets=[explorer], player='p2')
    assert maps[0].zone == Zone.GRAVEYARD and len(p2.hand) == 1


def test_portable_hole_rejects_expensive_targets_and_returns_linked_permanent():
    e = _game()
    cheap = _filler(e, 'Cheap', 'Enchantment', 'p2', mv=2)
    pricey = _filler(e, 'Pricey', 'Enchantment', 'p2', mv=3)
    hole = _card(e, 'Portable Hole', zone=Zone.HAND)
    _cast(e, hole, RICH)
    choice = e.state.pending_choice
    assert choice and any(o.get('instance_id') == cheap.instance_id for o in choice['options'])
    assert not any(o.get('instance_id') == pricey.instance_id for o in choice['options'])
    _answer(e)
    assert cheap.zone == Zone.EXILE
    e.rules.destroy(hole)
    e.resolve_until_stable()
    assert cheap.zone == Zone.BATTLEFIELD


def test_disruptor_flute_name_choice_taxes_spells_and_preserves_mana_abilities():
    e = _game()
    flute = _card(e, 'Disruptor Flute', zone=Zone.HAND)
    _cast(e, flute, RICH)
    assert e.state.pending_choice['kind'] == 'choose_card_name'
    e.resolve_pending_choice('Fomori Vault')
    e.resolve_until_stable()
    vault = _card(e, 'Fomori Vault')
    _spell(e, player='p1')
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    assert not e.can_activate(e.state.player_by_id('p1'), vault, vault.activated_abilities[0])
    e.tap_for_mana(e.state.player_by_id('p1'), vault)
    # The same chosen name controls the spell tax; lands themselves are not spells.
    named = _filler(e, 'Fomori Vault', 'Artifact', zone=Zone.HAND, mv=2)
    assert continuous.cost_reduction_for(e.state, e.state.player_by_id('p1'), named)[0] == -3
    flute.chosen_card_name = 'Different'
    assert continuous.cost_reduction_for(e.state, e.state.player_by_id('p1'), named)[0] == 0


@pytest.mark.parametrize('pool,expected', [({'C': 2}, Zone.GRAVEYARD), ({'W': 1, 'C': 1}, Zone.BATTLEFIELD)])
def test_void_mirror_uses_actual_mana_spent_including_generic_payments(pool, expected):
    e = _game()
    _card(e, 'Void Mirror')
    spell = _filler(e, 'Artifact spell', 'Artifact', zone=Zone.HAND, mv=2)
    e.state.current_step = 'main1'
    e.state.player_by_id('p1').mana_pool.add_many(pool)
    e.cast_spell(e.state.player_by_id('p1'), spell)
    e.resolve_until_stable()
    assert spell.zone == expected


def test_scouts_warning_draws_and_only_next_creature_can_be_cast_off_turn():
    e = _game()
    p = e.state.player_by_id('p1')
    e.state.current_step = 'upkeep'
    warning = _card(e, "Scout's Warning", zone=Zone.HAND)
    p.mana_pool.add_many({'W': 1})
    e.cast_spell(p, warning)
    e.resolve_until_stable()
    assert len(p.hand) == 1
    first = _filler(e, 'First', power=2, toughness=2, zone=Zone.HAND)
    second = _filler(e, 'Second', power=2, toughness=2, zone=Zone.HAND)
    assert e.can_cast(p, first)
    e.cast_spell(p, first)
    e.resolve_until_stable()
    assert first.zone == Zone.BATTLEFIELD
    assert not e.can_cast(p, second)
    e._step_cleanup()
    assert not e.state.next_spell_flash_grants


def test_fomori_vault_pays_discard_then_looks_at_artifact_count():
    e = _game()
    p = e.state.player_by_id('p1')
    vault = _card(e, 'Fomori Vault')
    for i in range(3):
        _filler(e, f'Artifact {i}', 'Artifact')
    discarded = _spell(e, player='p1')
    p.mana_pool.add_many({'C': 3})
    top = p.library[-1]
    _activate(e, vault)
    assert discarded.zone == Zone.GRAVEYARD and vault.tapped
    assert e.state.pending_choice and len([o for o in e.state.pending_choice['options'] if o.get('instance_id')]) == 3
    _answer(e, lambda c: str(top.instance_id))
    assert top.zone == Zone.HAND


def test_gleaming_splendor_draws_for_two_players_and_rewards_only_second_opponent_draw():
    e = _game()
    source = _card(e, 'Gleaming Splendor')
    p1, p2 = e.state.players
    p1.mana_pool.add_many(RICH)
    _activate(e, source, targets=[p1, p2])
    assert len(p1.hand) == len(p2.hand) == 1 and not _named(e, 'Treasure')
    p1.mana_pool.add_many(RICH)
    _activate(e, source, targets=[p1, p2])
    assert len(_named(e, 'Treasure')) == 1
    e.rules.draw(p2, 1)
    e.resolve_until_stable()
    assert len(_named(e, 'Treasure')) == 1


def test_eldrazi_confluence_can_repeat_modes_and_scions_sacrifice_for_mana():
    e = _game()
    _cast(e, _card(e, 'Eldrazi Confluence', zone=Zone.HAND), RICH, mode=[2, 2, 2])
    scions = _named(e, 'Eldrazi Scion')
    assert len(scions) == 3
    e.tap_for_mana(e.state.player_by_id('p1'), scions[0])
    assert scions[0].zone == Zone.GRAVEYARD


def test_eldrazi_confluence_pump_and_blink_are_separate_target_groups():
    e = _game()
    bear = _filler(e, 'Bear', power=2, toughness=5)
    victim = _filler(e, 'Victim', 'Artifact', 'p2')
    _cast(e, _card(e, 'Eldrazi Confluence', zone=Zone.HAND), RICH,
          groups=[[bear], [victim]], mode=[0, 1, 2])
    assert (bear.power, bear.toughness) == (5, 2)
    assert victim.zone == Zone.BATTLEFIELD and victim.tapped and victim.controller_id == 'p2'


def test_charitable_levy_collects_from_both_players_then_sacrifices_draws_and_searches():
    e = _game()
    levy = _card(e, 'Charitable Levy')
    plains = _card(e, 'Plains', zone=Zone.LIBRARY)
    _spell(e, 'Draw first', 'p1', zone=Zone.LIBRARY)
    p1, p2 = e.state.players
    for pid in ('p1', 'p2', 'p1'):
        player = e.state.player_by_id(pid)
        player.mana_pool.add_many({'C': 1})
        spell = _spell(e, player=pid)
        e.cast_spell(player, spell)
        e.resolve_until_stable()
    assert levy.zone == Zone.GRAVEYARD and len(p1.hand) == 1
    _answer(e, lambda c: str(plains.instance_id) if any(o.get('instance_id') == plains.instance_id for o in c['options']) else None)
    assert plains.zone == Zone.BATTLEFIELD and plains.tapped


def test_kozileks_command_tokens_and_scry_draw_use_independent_player_targets():
    e = _game()
    p1, p2 = e.state.players
    _cast(e, _card(e, "Kozilek's Command", zone=Zone.HAND), RICH, groups=[[p2], [p1]], mode=[0, 1], x=2)
    assert len(_named(e, 'Eldrazi Spawn', 'p2')) == 2
    assert e.state.pending_choice and e.state.pending_choice['player_id'] == 'p1'
    _answer(e)
    assert len(p1.hand) == 1 and not p2.hand


def test_kozileks_command_exile_modes_validate_x_and_exile_multiple_graveyards():
    e = _game()
    bear = _filler(e, 'Bear', 'Creature', 'p2', mv=2, power=2, toughness=2)
    gy = [_spell(e, name=f'Grave {pid}', player=pid, zone=Zone.GRAVEYARD) for pid in ('p1', 'p2')]
    _cast(e, _card(e, "Kozilek's Command", zone=Zone.HAND), RICH, groups=[[bear], gy], mode=[2, 3], x=2)
    assert bear.zone == Zone.EXILE and all(o.zone == Zone.EXILE for o in gy)


def test_mandate_of_peace_only_in_combat_exiles_stack_and_skips_end_combat():
    e = _game()
    p1, p2 = e.state.players
    mandate = _card(e, 'Mandate of Peace', zone=Zone.HAND)
    p1.mana_pool.add_many(RICH)
    e.state.current_phase = 'main'
    assert not e.can_cast(p1, mandate)
    while e.state.current_step != 'declare_attackers':
        e.advance_step()
    bear = _filler(e, 'Bear', power=2, toughness=2)
    e.declare_attackers(p1, [{'attacker': bear, 'defender': p2}])
    other = _stack_spell(e)
    p1.mana_pool.add_many(RICH)
    e.cast_spell(p1, mandate)
    e.resolve_until_stable()
    assert mandate.zone == other.zone == Zone.EXILE
    assert not bear.attacking and not e.state.stack
    assert e.advance_step()[1] == 'main2'
    assert not e.can_cast(p2, _spell(e, player='p2'))


def test_petrified_hamlet_names_a_land_at_entry_and_grants_colorless_mana():
    e = _game()
    vault = _card(e, 'Fomori Vault')
    hamlet = _card(e, 'Petrified Hamlet', zone=Zone.HAND)
    e.state.current_step = 'main1'
    e.play_land(e.state.player_by_id('p1'), hamlet)
    e.resolve_until_stable()
    assert e.state.pending_choice['kind'] == 'name_card'
    e.resolve_pending_choice('Fomori Vault')
    e.resolve_until_stable()
    assert hamlet.chosen_card_name == 'Fomori Vault'
    assert not e.can_activate(e.state.player_by_id('p1'), vault, vault.activated_abilities[0])
    e.tap_for_mana(e.state.player_by_id('p1'), vault)
    assert vault.tapped


def test_paladin_class_turn_scoped_tax_level_anthem_and_attack_trigger():
    e = _game()
    source = _card(e, 'Paladin Class')
    p1, p2 = e.state.players
    spell = _spell(e, player='p2')
    assert continuous.cost_reduction_for(e.state, p2, spell)[0] == -1
    e.state.active_player_index = 1
    assert continuous.cost_reduction_for(e.state, p2, spell)[0] == 0
    e.state.active_player_index = 0
    a = _filler(e, 'Attacker', power=2, toughness=2)
    b = _filler(e, 'Other', power=2, toughness=2)
    assert a.power == 2
    p1.mana_pool.add_many(RICH)
    _activate(e, source, index=0)
    assert a.power == 3
    p1.mana_pool.add_many(RICH)
    _activate(e, source, index=1)
    e.state.current_step = 'declare_attackers'
    e.declare_attackers(p1, [{'attacker': a, 'defender': p2}, {'attacker': b, 'defender': p2}])
    e._fire_player_attacked_events()
    e.resolve_until_stable()
    _answer(e, lambda c: str(a.instance_id))
    e.recompute_continuous_effects()
    assert a.power == 4 and combat.has(a, 'double_strike')
    assert b.power == 3 and not combat.has(b, 'double_strike')


def test_dack_fayden_reveals_one_creature_per_opponent_then_chooses_distinct_recipients():
    e = _game(players=3)
    first = _filler(e, 'First', power=2, toughness=2, zone=Zone.LIBRARY)
    _spell(e, 'Miss', 'p1', zone=Zone.LIBRARY)
    second = _filler(e, 'Second', power=3, toughness=3, zone=Zone.LIBRARY)
    # This new printing is absent from older isolated test caches. Its catalogue
    # needs only the canonical name; keep its real printed characteristics here.
    dack = _filler(e, 'Dack Fayden, Helping Hand', 'Legendary Creature — Human Advisor',
                   mv=6, power=4, toughness=6, zone=Zone.HAND)
    dack.card.mana_cost_string = '{4}{W}{W}'
    dack.card.mana_cost = {'generic': 4, 'W': 2}
    _cast(e, dack, RICH)
    assert first.zone == second.zone == Zone.BATTLEFIELD
    assert e.state.pending_choice['kind'] == 'creature_recipient'
    e.resolve_pending_choice('p3')
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert second.controller_id == 'p3' and first.controller_id == 'p2'
    assert 'p1' in first.goaded_permanently and 'p1' in second.goaded_permanently
    e._step_cleanup()
    assert second.controller_id == 'p3'


def test_apple_of_eden_exiles_opponents_hand_plays_with_any_mana_and_returns_unused_cards():
    e = _game()
    p1, p2 = e.state.players
    apple = _card(e, 'Apple of Eden, Isu Relic')
    bear = _filler(e, 'Green Bear', 'Creature', 'p2', power=2, toughness=2, zone=Zone.HAND)
    bear.card.mana_cost_string = '{G}'
    bear.card.mana_cost = {'G': 1}
    land = _card(e, 'Plains', 'p2', Zone.HAND)
    unused = _spell(e, 'Unused', 'p2')
    _activate(e, apple, targets=[p2])
    assert apple.zone == Zone.GRAVEYARD and p1.life == 16
    assert not p2.hand and all(o.face_down_in_exile for o in (bear, land, unused))
    p1.mana_pool.add_many({'C': 1})
    assert e.can_cast(p1, bear)
    e.cast_spell(p1, bear)
    e.resolve_until_stable()
    assert bear.controller_id == 'p1' and len(p2.hand) == 1
    e.play_land(p1, land)
    e.resolve_until_stable()
    assert land.controller_id == 'p1' and len(p2.hand) == 2
    e._fire_delayed_triggers('end')
    e.resolve_until_stable()
    assert unused.zone == Zone.HAND and not unused.face_down_in_exile
    assert bear.zone == land.zone == Zone.BATTLEFIELD


def _loyalty_at(e, walker, index, targets=None):
    walker.activated_loyalty_this_turn = False
    _activate(e, walker, index=index, targets=targets)
    e.recompute_continuous_effects()


def test_gideon_prevents_damage_until_his_controllers_next_turn_and_animates_with_shield():
    e = _game()
    p1, p2 = e.state.players
    gideon = _card(e, 'Gideon of the Trials')
    gideon.counters['loyalty'] = 3
    source = _filler(e, 'Source', power=2, toughness=2)
    _loyalty_at(e, gideon, 0, [source])
    e.rules.deal_damage(p2, 3, source=source)
    assert p2.life == 20
    e._step_cleanup()
    e.rules.deal_damage(p2, 3, source=source)
    assert p2.life == 20
    _loyalty_at(e, gideon, 1)
    assert gideon.is_creature and (gideon.power, gideon.toughness) == (4, 4)
    assert combat.has(gideon, 'indestructible')
    e.rules.deal_damage(gideon, 5, source=source)
    assert gideon.damage_marked == 0
    e.begin_turn()
    e.begin_turn()
    e.rules.deal_damage(p2, 3, source=source)
    assert p2.life == 17


def test_gideon_emblem_is_active_only_while_controlling_a_gideon_planeswalker():
    e = _game()
    p1, p2 = e.state.players
    gideon = _card(e, 'Gideon of the Trials')
    gideon.counters['loyalty'] = 3
    _loyalty_at(e, gideon, 2)
    assert len(p1.emblems) == 1
    assert continuous.player_cant_lose(e.state, p1) and continuous.player_cant_win(e.state, p2)
    e.rules.exile(gideon)
    e.recompute_continuous_effects()
    assert not continuous.player_cant_lose(e.state, p1)
    assert not continuous.player_cant_win(e.state, p2)


def test_tezzeret_artifact_entry_loyalty_untap_counter_and_search():
    e = _game()
    tez = _card(e, 'Tezzeret, Cruel Captain')
    tez.counters['loyalty'] = 4
    bear = _filler(e, 'Artifact Bear', 'Artifact Creature', power=2, toughness=2)
    _enter(e, bear)
    assert tez.counters['loyalty'] == 5
    bear.tapped = True
    _loyalty_at(e, tez, 0, [bear])
    assert not bear.tapped and bear.counters['+1/+1'] == 1
    found = _filler(e, 'Search hit', 'Artifact', mv=1, zone=Zone.LIBRARY)
    _loyalty_at(e, tez, 1)
    _answer(e, lambda c: str(found.instance_id))
    assert found.zone == Zone.HAND


def test_tezzeret_emblem_animates_noncreature_artifact_and_preserves_existing_creature_base():
    e = _game()
    tez = _card(e, 'Tezzeret, Cruel Captain')
    tez.counters['loyalty'] = 8
    _loyalty_at(e, tez, 2)
    artifact = _filler(e, 'Noncreature', 'Artifact')
    _step(e, 'begin_combat')
    _answer(e, lambda c: str(artifact.instance_id))
    e.recompute_continuous_effects()
    assert artifact.is_creature and (artifact.power, artifact.toughness) == (3, 3)
    assert continuous.has_subtype(artifact, 'Robot')


def test_dack_does_not_overwrite_a_creatures_as_enters_choice():
    e = _game()
    revoker = _card(e, 'Phyrexian Revoker', zone=Zone.LIBRARY)
    dack = _filler(e, 'Dack Fayden, Helping Hand', 'Legendary Creature — Human Advisor',
                   mv=6, power=4, toughness=6, zone=Zone.HAND)
    _cast(e, dack, RICH)
    assert e.state.pending_choice['kind'] == 'choose_card_name'
    e.resolve_pending_choice('Sol Ring')
    e.resolve_until_stable()
    assert e.state.pending_choice['kind'] == 'creature_recipient'
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert revoker.chosen_card_name == 'Sol Ring' and revoker.controller_id == 'p2'


def test_mandate_preserves_a_separately_scheduled_additional_combat():
    from copy import deepcopy
    e = _game()
    while e.state.current_step != 'declare_attackers':
        e.advance_step()
    phase = e._turn_steps[e._cursor - 1][0]
    extra = deepcopy(phase)
    end = next(i for i in range(e._cursor, len(e._turn_steps)) if e._turn_steps[i][0] is not phase)
    e._turn_steps[end:end] = [(extra, step) for step in extra.steps]
    p = e.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    mandate = _card(e, 'Mandate of Peace', zone=Zone.HAND)
    e.cast_spell(p, mandate)
    e.resolve_until_stable()
    assert e.advance_step()[1] == 'begin_combat'


def test_charitable_levy_sacrifice_rider_survives_finality_replacement():
    e = _game()
    levy = _card(e, 'Charitable Levy')
    levy.counters.update(collection=2, finality=1)
    p1 = e.state.player_by_id('p1')
    p1.mana_pool.add_many({'C': 1})
    e.cast_spell(p1, _spell(e, player='p1'))
    e.resolve_until_stable()
    assert levy.zone == Zone.EXILE and len(p1.hand) == 1


def test_charitable_levy_cannot_sacrifice_a_source_taken_before_its_trigger_resolves():
    e = _game()
    levy = _card(e, 'Charitable Levy')
    levy.counters['collection'] = 2
    p1 = e.state.player_by_id('p1')
    p1.mana_pool.add_many({'C': 1})
    e.cast_spell(p1, _spell(e, player='p1'))
    levy.controller_id = 'p2'
    e.resolve_until_stable()
    assert levy.zone == Zone.BATTLEFIELD and not p1.hand and not e.state.pending_choice
