"""Real gameplay for every paused Revival Trance catalogue entry."""
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
        engine.recompute_continuous_effects()
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
        engine.recompute_continuous_effects()
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
RICH = {"W": 5, "U": 5, "B": 5, "R": 5, "G": 5, "C": 15}






def _grave(e, name, player='p1', kind='Creature', mv=2, power=2, toughness=2):
    return _filler(e, name, kind, player, mv=mv,
                   power=power if 'Creature' in kind else None,
                   toughness=toughness if 'Creature' in kind else None, zone=Zone.GRAVEYARD)


def _top(e, name, player='p1', kind='Creature', mv=2, power=2, toughness=2, **kw):
    return _filler(e, name, kind, player, mv=mv,
                   power=power if 'Creature' in kind else None,
                   toughness=toughness if 'Creature' in kind else None, zone=Zone.LIBRARY, **kw)


def _attack(e, attackers, defender='p2', player='p1', damage=False):
    p = e.state.player_by_id(player)
    e.state.current_phase, e.state.current_step = 'combat', 'declare_attackers'
    e.declare_attackers(p, [{'attacker': o, 'defender': e.state.player_by_id(defender)} for o in attackers])
    e._fire_player_attacked_events()
    e.resolve_until_stable()
    if damage:
        e.state.current_step = 'combat_damage'
        e._step_combat_damage()
        e.resolve_until_stable()


def _choice_id(choice, obj):
    return next(str(o['id']) for o in choice['options'] if o.get('instance_id') == obj.instance_id)


def test_archfiend_only_reduces_the_active_opponents_creatures_to_two():
    e = _game(players=3)
    _card(e, 'Archfiend of Depravity')
    theirs = [_filler(e, f'Creature {i}', player='p2', power=2, toughness=2) for i in range(4)]
    third = _filler(e, 'Third', player='p3', power=2, toughness=2)
    _step(e, 'end', 'p1')
    assert all(o.zone == Zone.BATTLEFIELD for o in theirs)
    e.state.active_player_index = 1
    _step(e, 'end', 'p2')
    assert e.state.pending_choice['player_id'] == 'p2'
    _answer(e)
    assert sum(o.zone == Zone.BATTLEFIELD for o in theirs) == 2
    assert third.zone == Zone.BATTLEFIELD


def test_banon_allows_one_newly_milled_creature_cast_but_not_a_dead_creature():
    e = _game()
    banon = _card(e, "Banon, the Returners' Leader")
    p1 = e.state.player_by_id('p1')
    milled = _top(e, 'Milled')
    e.rules.mill(p1, 1)
    e.resolve_until_stable()
    died = _filler(e, 'Died', power=2, toughness=2, zone=Zone.HAND)
    _cast(e, died, RICH)
    e.rules.destroy(died)
    e.resolve_until_stable()
    e.state.current_step = 'main1'
    p1.mana_pool.add_many(RICH)
    assert e.can_cast(p1, milled) and not e.can_cast(p1, died)
    e.cast_spell(p1, milled)
    e.resolve_until_stable()
    later = _top(e, 'Later')
    e.rules.mill(p1, 1)
    e.resolve_until_stable()
    assert not e.can_cast(p1, later)
    banon.controller_id = 'p2'
    assert not e.can_cast(p1, later)


def test_banon_attack_can_pay_one_and_discard_then_draw():
    e = _game()
    banon = _card(e, "Banon, the Returners' Leader")
    old = _filler(e, 'Discard', 'Instant', zone=Zone.HAND)
    e.state.player_by_id('p1').mana_pool.add_many({'C': 1})
    _attack(e, [banon])
    _answer(e)
    assert old.zone == Zone.GRAVEYARD
    assert len(e.state.player_by_id('p1').hand) == 1


def test_celes_can_discard_nonpermanents_and_draws_number_plus_one():
    e = _game()
    p = e.state.player_by_id('p1')
    old = [_filler(e, 'Instant', 'Instant', zone=Zone.HAND),
           _filler(e, 'Sorcery', 'Sorcery', zone=Zone.HAND)]
    _cast(e, _card(e, 'Celes, Rune Knight', zone=Zone.HAND), RICH)
    _answer(e)
    assert all(o.zone == Zone.GRAVEYARD for o in old)
    assert len(p.hand) == 3


def test_celes_reanimated_batch_counters_all_creatures_once():
    e = _game()
    celes = _card(e, 'Celes, Rune Knight')
    old = [_grave(e, 'A'), _grave(e, 'B')]
    _cast(e, _card(e, 'Rise of the Dark Realms', zone=Zone.HAND), RICH)
    assert all(o.zone == Zone.BATTLEFIELD for o in old)
    assert all(o.counters.get('+1/+1') == 1 for o in [celes, *old])


def test_coin_of_fate_tracks_cost_exiles_after_its_source_is_sacrificed():
    e = _game()
    coin = _card(e, 'Coin of Fate', zone=Zone.HAND)
    _cast(e, coin, RICH)
    _answer(e)
    cheap, expensive = _grave(e, 'Cheap', mv=2), _grave(e, 'Expensive', mv=5)
    p = e.state.player_by_id('p1')
    p.mana_pool.add_many(RICH)
    _activate(e, coin)
    assert coin.zone == Zone.GRAVEYARD and cheap.zone == Zone.BATTLEFIELD and cheap.tapped
    assert expensive.zone == Zone.LIBRARY and p.library[0] is expensive
    assert e.state.monarch_id == 'p1'


def test_edgar_graveyard_artifact_enters_tapped_and_permission_is_once_per_turn():
    e = _game()
    edgar = _card(e, 'Edgar, Master Machinist')
    first = _grave(e, 'First artifact', kind='Artifact')
    second = _grave(e, 'Second artifact', kind='Artifact')
    _cast(e, first, RICH)
    assert first.zone == Zone.BATTLEFIELD and first.tapped
    assert not e.can_cast(e.state.player_by_id('p1'), second)
    huge = _filler(e, 'Huge artifact', 'Artifact', mv=9)
    before = edgar.power
    _attack(e, [edgar])
    assert edgar.power == before + 9 and huge.zone == Zone.BATTLEFIELD


def test_espers_exiles_only_opponents_graveyards_and_creates_artifact_only_copy():
    e = _game(players=3)
    mine = _grave(e, 'Mine')
    chosen = _grave(e, 'Chosen', 'p2', mv=6, power=6, toughness=6)
    other = _grave(e, 'Other', 'p3', kind='Instant')
    _cast(e, _card(e, 'Espers to Magicite', zone=Zone.HAND), RICH)
    assert mine.zone == Zone.GRAVEYARD and chosen.zone == other.zone == Zone.EXILE
    copies = _named(e, 'Chosen')
    assert len(copies) == 1 and copies[0].is_token and copies[0].card.is_artifact
    assert not copies[0].is_creature and copies[0].power is None


def test_flayer_undying_return_really_triggers_damage_from_the_returned_creature():
    e = _game()
    flayer = _card(e, 'Flayer of the Hatebound')
    p2 = e.state.player_by_id('p2')
    e.rules.destroy(flayer)
    e.resolve_until_stable()
    _answer(e, lambda c: 'p2' if c['kind'] == 'trigger_target' else None)
    assert flayer.zone == Zone.BATTLEFIELD and flayer.counters['+1/+1'] == 1
    assert p2.life == 20 - flayer.power


def test_gogo_copy_pumps_both_creatures_and_cleanup_restores_original():
    e = _game()
    gogo = _card(e, 'Gogo, Mysterious Mime')
    original = gogo.card
    other = _filler(e, 'Other', power=2, toughness=3)
    _step(e, 'begin_combat')
    _answer(e, lambda c: str(other.instance_id) if c['kind'] == 'trigger_target' else None)
    assert gogo.name == 'Gogo, Mysterious Mime'
    assert gogo.power == other.power == 4
    assert combat.has(gogo, 'haste') and combat.has(other, 'attacks_if_able')
    e._step_cleanup()
    assert gogo.card is original and other.power == 2


def test_kefka_own_turn_indestructibility_and_free_cast_owner_life_loss():
    e = _game()
    kefka = _card(e, 'Kefka, Dancing Mad')
    hit = _grave(e, 'Foreign creature', 'p2', mv=4)
    assert combat.has(kefka, 'indestructible')
    _step(e, 'end')
    assert hit.zone == Zone.EXILE
    p1, p2 = e.state.players
    e.cast_spell(p1, hit, free=True)
    e.resolve_until_stable()
    assert hit.zone == Zone.BATTLEFIELD and hit.controller_id == 'p1'
    assert p2.life == 16
    e.state.active_player_index = 1
    e.recompute_continuous_effects()
    assert not combat.has(kefka, 'indestructible')


def test_legions_to_ashes_exiles_only_same_name_tokens_of_targets_controller():
    e = _game(players=3)
    target = _filler(e, 'Same name', 'Artifact', 'p2')
    token = _filler(e, 'Same name', 'Artifact', 'p2')
    token.is_token = True
    nontoken = _filler(e, 'Same name', 'Artifact', 'p2')
    third = _filler(e, 'Same name', 'Artifact', 'p3')
    third.is_token = True
    _cast(e, _card(e, 'Legions to Ashes', zone=Zone.HAND), RICH, [target])
    assert target.zone == token.zone == Zone.EXILE
    assert nontoken.zone == third.zone == Zone.BATTLEFIELD


def test_locke_can_cast_one_milled_spell_from_an_opponents_graveyard():
    e = _game(players=3)
    locke = _card(e, 'Locke, Treasure Hunter')
    own = _top(e, 'Own spell', kind='Instant')
    _top(e, 'Land hit', 'p2', kind='Land')
    foreign = _top(e, 'Foreign spell', 'p3', kind='Instant')
    _attack(e, [locke])
    assert len(_named(e, 'Treasure')) == 1
    p1 = e.state.player_by_id('p1')
    p1.mana_pool.add_many(RICH)
    assert e.can_cast(p1, foreign)
    e.cast_spell(p1, foreign)
    e.resolve_until_stable()
    assert foreign.zone == Zone.GRAVEYARD and foreign.owner_id == 'p3'
    assert not e.can_cast(p1, own)


def test_mog_discard_choices_and_both_riders_include_new_token():
    e = _game(players=3)
    mog = _card(e, 'Mog, Moogle Warrior')
    creature = _filler(e, 'Creature', power=2, toughness=2, zone=Zone.HAND)
    noncreature = _filler(e, 'Spell', 'Instant', 'p2', zone=Zone.HAND)
    declined = _filler(e, 'Decline', 'Instant', 'p3', zone=Zone.HAND)
    _step(e, 'end')
    _answer(e, lambda c: 'decline' if c.get('player_id') == 'p3' else None)
    assert creature.zone == noncreature.zone == Zone.GRAVEYARD
    assert declined.zone == Zone.HAND
    assert len(e.state.player_by_id('p1').hand) == len(e.state.player_by_id('p2').hand) == 1
    tokens = _named(e, 'Moogle')
    assert len(tokens) == 1 and (tokens[0].power, tokens[0].toughness) == (2, 3)
    assert combat.has(tokens[0], 'lifelink') and mog.counters['+1/+1'] == 1


def test_palace_jailer_returns_exile_when_opponent_becomes_monarch_after_jailer_dies():
    e = _game()
    victim = _filler(e, 'Victim', player='p2', power=2, toughness=2)
    jailer = _card(e, 'Palace Jailer', zone=Zone.HAND)
    _cast(e, jailer, RICH)
    _answer(e)
    assert e.state.monarch_id == 'p1' and victim.zone == Zone.EXILE
    e.rules.destroy(jailer)
    e.resolve_until_stable()
    assert victim.zone == Zone.EXILE
    e.rules.become_monarch(e.state.player_by_id('p2'))
    e.resolve_until_stable()
    assert victim.zone == Zone.BATTLEFIELD and victim.controller_id == 'p2'


@pytest.mark.parametrize('mode', [0, 1])
def test_phoenix_down_both_modes_exile_the_source_as_cost(mode):
    e = _game()
    source = _card(e, 'Phoenix Down')
    victim = _grave(e, 'Return', mv=4) if mode == 0 else _filler(e, 'Zombie', 'Creature — Zombie', 'p2', power=2, toughness=2)
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    _activate(e, source, targets=[victim], mode=mode)
    assert source.zone == Zone.EXILE
    assert victim.zone == (Zone.BATTLEFIELD if mode == 0 else Zone.EXILE)
    if mode == 0:
        assert victim.tapped


def test_rejoin_opponents_choose_distinct_cards_starting_after_caster():
    e = _game(players=3)
    e.state.active_player_index = 1
    hits = [_grave(e, 'A', 'p2'), _grave(e, 'B', 'p2')]
    spell = _card(e, 'Rejoin the Fight', 'p2', Zone.HAND)
    _cast(e, spell, RICH)
    assert e.state.pending_choice['player_id'] == 'p3'
    _answer(e)
    assert all(o.zone == Zone.BATTLEFIELD and o.controller_id == 'p2' for o in hits)


def test_rise_returns_all_creatures_from_all_graveyards_under_caster_control():
    e = _game(players=3)
    creatures = [_grave(e, f'Creature {p}', p) for p in ('p1', 'p2', 'p3')]
    spell = _grave(e, 'Not a creature', 'p2', kind='Sorcery')
    _cast(e, _card(e, 'Rise of the Dark Realms', zone=Zone.HAND), RICH)
    assert all(o.zone == Zone.BATTLEFIELD and o.controller_id == 'p1' for o in creatures)
    assert spell.zone == Zone.GRAVEYARD


def test_sepulchral_may_return_one_creature_from_each_opponents_graveyard():
    e = _game(players=3)
    hits = [_grave(e, 'p2 card', 'p2'), _grave(e, 'p3 card', 'p3')]
    _cast(e, _card(e, 'Sepulchral Primordial', zone=Zone.HAND), RICH)
    _answer(e)
    assert all(o.zone == Zone.BATTLEFIELD and o.controller_id == 'p1' for o in hits)


def test_setzer_blackjack_can_crew_attack_and_win_coin_for_tapped_treasures(monkeypatch):
    e = _game()
    _cast(e, _card(e, 'Setzer, Wandering Gambler', zone=Zone.HAND), RICH)
    ship = _named(e, 'The Blackjack')[0]
    assert not ship.is_creature and ship.card.is_artifact and combat.has(ship, 'flying')
    crew = _filler(e, 'Crew', power=2, toughness=2)
    _activate(e, ship, tap_choices=[crew.instance_id])
    assert crew.tapped and ship.is_creature and (ship.power, ship.toughness) == (3, 3)
    ship.summoning_sick = False
    monkeypatch.setattr(e.rules, 'coin_flip', lambda: True)
    _attack(e, [ship], damage=True)
    treasures = _named(e, 'Treasure')
    assert len(treasures) == 2 and all(o.tapped for o in treasures)


def test_shadow_sacrifices_another_nonland_for_draw_and_mana_value_life_loss():
    e = _game()
    shadow = _card(e, 'Shadow, Mysterious Assassin')
    offering = _filler(e, 'Offering', 'Artifact', mv=4)
    land = _card(e, 'Plains')
    _attack(e, [shadow], damage=True)
    choice = e.state.pending_choice
    assert choice and all(o.get('instance_id') not in (shadow.instance_id, land.instance_id) for o in choice['options'])
    _answer(e, lambda c: _choice_id(c, offering) if any(o.get('instance_id') == offering.instance_id for o in c['options']) else None)
    assert offering.zone == Zone.GRAVEYARD and len(e.state.player_by_id('p1').hand) == 2
    assert e.state.player_by_id('p2').life == 20 - shadow.power - 4


def test_siegfried_mills_before_counting_all_graveyard_creatures_twice():
    e = _game()
    _grave(e, 'Already there')
    _top(e, 'Creature one')
    _top(e, 'Creature two')
    _top(e, 'Miss', kind='Instant')
    siegfried = _card(e, 'Siegfried, Famed Swordsman', zone=Zone.HAND)
    _cast(e, siegfried, RICH)
    assert siegfried.counters['+1/+1'] == 6 and combat.has(siegfried, 'menace')


def test_snort_each_player_can_accept_or_decline_and_only_accepting_opponents_take_damage():
    e = _game(players=3)
    old = [_filler(e, f'Hand {p}', 'Instant', p, zone=Zone.HAND) for p in ('p1', 'p2', 'p3')]
    snort = _card(e, 'Snort', zone=Zone.HAND)
    _cast(e, snort, RICH)
    _answer(e, lambda c: 'decline' if c.get('player_id') == 'p2' else None)
    assert old[0].zone == old[2].zone == Zone.GRAVEYARD and old[1].zone == Zone.HAND
    assert len(e.state.player_by_id('p1').hand) == len(e.state.player_by_id('p3').hand) == 5
    assert e.state.player_by_id('p2').life == 20 and e.state.player_by_id('p3').life == 15
    assert e.can_cast(e.state.player_by_id('p1'), snort)  # real flashback permission


def test_strago_digs_opponents_library_creature_has_haste_and_end_step_sacrifice():
    e = _game()
    source = _card(e, 'Strago and Relm')
    hit = _top(e, 'Foreign creature', 'p2', mv=6)
    misses = [_top(e, 'Artifact miss', 'p2', kind='Artifact'), _top(e, 'Land miss', 'p2', kind='Land')]
    p1, p2 = e.state.players
    p1.mana_pool.add_many(RICH)
    _activate(e, source, targets=[p2])
    assert hit.zone == Zone.EXILE and all(o.zone == Zone.EXILE for o in misses)
    e.cast_spell(p1, hit, free=True)
    e.resolve_until_stable()
    assert hit.controller_id == 'p1' and hit.zone == Zone.BATTLEFIELD and combat.has(hit, 'haste')
    e._fire_delayed_triggers('end')
    e.resolve_until_stable()
    assert hit.zone == Zone.GRAVEYARD


def test_valigarmanda_chapters_link_exile_produce_lore_mana_and_allow_wildcard_cast():
    e = _game()
    mine = _grave(e, 'Mine', kind='Instant', mv=1)
    foreign = _grave(e, 'Foreign', 'p2', kind='Instant', mv=1)
    foreign.card.mana_cost_string, foreign.card.mana_cost = '{U}', {'U': 1}
    saga = _card(e, 'Summon: Esper Valigarmanda', zone=Zone.HAND)
    _cast(e, saga, RICH)
    assert saga.counters['lore'] == 1 and mine.zone == foreign.zone == Zone.EXILE
    p1 = e.state.player_by_id('p1')
    p1.mana_pool.empty()
    e.rules.advance_sagas(p1)
    e.resolve_until_stable()
    assert p1.mana_pool.pool['R'] == 2
    assert e.can_cast(p1, foreign)
    e.cast_spell(p1, foreign)
    e.resolve_until_stable()
    assert foreign.zone == Zone.GRAVEYARD and foreign.owner_id == 'p2'
    e.rules.advance_sagas(p1)
    e.resolve_until_stable()
    e.rules.advance_sagas(p1)
    e.resolve_until_stable()
    assert saga.zone == Zone.GRAVEYARD


def test_warring_triad_targets_mana_and_mill_cost_turns_on_creature_type_at_eight():
    e = _game()
    triad = _card(e, 'The Warring Triad')
    for i in range(7):
        _grave(e, f'Grave {i}', kind='Instant')
    e.recompute_continuous_effects()
    assert not triad.is_creature
    p2 = e.state.player_by_id('p2')
    _activate(e, triad, targets=[p2])
    assert triad.tapped and triad.is_creature and e.state.pending_choice['player_id'] == 'p2'
    e.resolve_pending_choice('G')
    assert p2.mana_pool.pool['G'] == 1


@pytest.mark.parametrize('mode', [0, 1, 2])
def test_umaro_random_modes_are_not_selected_by_player(monkeypatch, mode):
    e = _game()
    umaro = _card(e, 'Umaro, Raging Yeti')
    other = _filler(e, 'Other', power=2, toughness=2)
    old = _filler(e, 'Old hand', 'Instant', zone=Zone.HAND)
    monkeypatch.setattr(e.rules, 'random_choice', lambda values: list(values)[mode])
    _step(e, 'begin_combat')
    assert not e.state.pending_choice or e.state.pending_choice['kind'] != 'trigger_mode'
    if mode == 0:
        assert other.power == 5 and combat.has(other, 'trample')
    elif mode == 1:
        assert old.zone == Zone.GRAVEYARD and len(e.state.player_by_id('p1').hand) == 4
    else:
        _answer(e, lambda c: 'p2')
        assert e.state.player_by_id('p2').life == 15
    assert umaro.zone == Zone.BATTLEFIELD


def test_celes_discard_decline_still_draws_one():
    e = _game()
    old = _filler(e, 'Keep', 'Instant', zone=Zone.HAND)
    _cast(e, _card(e, 'Celes, Rune Knight', zone=Zone.HAND), RICH)
    _answer(e, lambda c: 'decline')
    assert old.zone == Zone.HAND and len(e.state.player_by_id('p1').hand) == 2


def test_banon_arrival_permission_is_own_turn_only_and_expires_with_the_turn():
    e = _game()
    _card(e, "Banon, the Returners' Leader")
    old = _top(e, 'Flash card', oracle_text='Flash', keywords=['Flash'])
    p1 = e.state.player_by_id('p1')
    e.rules.mill(p1, 1)
    e.resolve_until_stable()
    p1.mana_pool.add_many(RICH)
    e.state.current_step = 'main1'
    assert e.can_cast(p1, old)
    e.begin_turn()
    assert e.state.active_player.id == 'p2' and not e.can_cast(p1, old)
    e.begin_turn()
    e._step_untap()
    e.state.current_step = 'main1'
    p1.mana_pool.add_many(RICH)
    assert not e.can_cast(p1, old)
    new = _top(e, 'Fresh')
    e.rules.mill(p1, 1)
    e.resolve_until_stable()
    assert e.can_cast(p1, new)


def test_locke_permission_survives_source_removal_but_expires_at_cleanup():
    e = _game()
    locke = _card(e, 'Locke, Treasure Hunter')
    foreign = _top(e, 'Foreign', 'p2', kind='Instant')
    other = _grave(e, 'Not milled', 'p2', kind='Instant')
    _attack(e, [locke])
    e.rules.destroy(locke)
    e.resolve_until_stable()
    p1 = e.state.player_by_id('p1')
    p1.mana_pool.add_many(RICH)
    assert e.can_cast(p1, foreign) and not e.can_cast(p1, other)
    e._step_cleanup()
    assert not e.can_cast(p1, foreign)
    assert not e.state.temp_graveyard_cast_permission_groups


def test_locke_multiple_milled_lands_still_make_one_treasure_and_cannot_be_played():
    e = _game(players=3)
    locke = _card(e, 'Locke, Treasure Hunter')
    land = _top(e, 'Our land', kind='Land')
    _top(e, 'Their land', 'p2', kind='Land')
    _attack(e, [locke])
    assert len(_named(e, 'Treasure')) == 1
    e.state.current_step = 'main1'
    assert not e.can_play_land(e.state.player_by_id('p1'), land)


def test_locke_mill_suspension_keeps_every_milled_spell_in_the_single_cast_group():
    from mtg_analyzer.game.effects.core import ReplacementEffect
    e = _game()
    locke = _card(e, 'Locke, Treasure Hunter')
    own = [_top(e, f'Own {i}', kind='Instant') for i in range(3)]
    foreign = _top(e, 'Foreign', 'p2', kind='Instant')
    p1 = e.state.player_by_id('p1')
    for _ in range(2):
        p1.player_effects.append(ReplacementEffect(
            event_type=EventType.WOULD_MILL,
            condition=lambda event, context: event.get('player_id') == 'p1',
            replacement_fn=lambda event, context: event.copy_with(count=event.get('count') + 1),
        ))
    _attack(e, [locke])
    assert e.state.pending_choice['kind'] == 'replacement_order'
    _answer(e)
    p1.mana_pool.add_many(RICH)
    assert all(o.zone == Zone.GRAVEYARD and e.can_cast(p1, o) for o in [*own, foreign])
    e.cast_spell(p1, foreign)
    e.resolve_until_stable()
    assert all(not e.can_cast(p1, o) for o in own)


def test_mog_counter_rider_waits_for_token_creation_replacement_choice():
    e = _game()
    mog = _card(e, 'Mog, Moogle Warrior')
    _card(e, 'Doubling Season')
    _card(e, 'Parallel Lives')
    _filler(e, 'Creature', power=2, toughness=2, zone=Zone.HAND)
    _filler(e, 'Spell', 'Instant', 'p2', zone=Zone.HAND)
    _step(e, 'end')
    _answer(e)
    tokens = _named(e, 'Moogle')
    assert len(tokens) == 4 and all((o.power, o.toughness) == (3, 4) for o in tokens)
    assert mog.counters['+1/+1'] == 2


def test_strago_unused_hit_stays_exiled_and_activation_is_sorcery_only():
    e = _game()
    source = _card(e, 'Strago and Relm')
    hit = _top(e, 'Uncast', 'p2', mv=6)
    p1, p2 = e.state.players
    p1.mana_pool.add_many(RICH)
    e.state.current_step = 'upkeep'
    assert not e.can_activate(p1, source, source.activated_abilities[0])
    _activate(e, source, targets=[p2])
    e._fire_delayed_triggers('end')
    e.resolve_until_stable()
    e._step_cleanup()
    assert hit.zone == Zone.EXILE and not e.can_cast(p1, hit)


def test_espers_with_no_opponent_creature_exiles_graveyards_without_copy():
    e = _game()
    foreign = _grave(e, 'Foreign', 'p2', kind='Instant')
    _cast(e, _card(e, 'Espers to Magicite', zone=Zone.HAND), RICH)
    assert foreign.zone == Zone.EXILE and not any(o.is_token for o in e.state.battlefield)


def test_warring_triad_needs_a_library_card_for_its_mill_cost():
    e = _game(library=0)
    triad = _card(e, 'The Warring Triad')
    e.state.current_step = 'main1'
    assert not e.can_activate(e.state.player_by_id('p1'), triad, triad.activated_abilities[0])


def test_valigarmanda_permissions_end_at_cleanup_and_do_not_cover_unlinked_cards():
    e = _game()
    linked = _grave(e, 'Linked', 'p2', kind='Instant')
    unrelated = _filler(e, 'Unrelated', 'Instant', 'p2', zone=Zone.EXILE)
    saga = _card(e, 'Summon: Esper Valigarmanda', zone=Zone.HAND)
    _cast(e, saga, RICH)
    e.rules.advance_sagas(e.state.player_by_id('p1'))
    e.resolve_until_stable()
    p1 = e.state.player_by_id('p1')
    assert e.can_cast(p1, linked) and not e.can_cast(p1, unrelated)
    e._step_cleanup()
    assert not e.can_cast(p1, linked)


def test_locke_casts_are_offered_to_ui_and_execute_through_game_session():
    from mtg_analyzer.services.game_session import GameSession
    e = _game()
    locke = _card(e, 'Locke, Treasure Hunter')
    own = _top(e, 'Own', kind='Instant')
    foreign = _top(e, 'Foreign', 'p2', kind='Instant')
    unrelated = _grave(e, 'Unrelated', 'p2', kind='Instant')
    _attack(e, [locke])
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    session = GameSession(e, mode='replay', require_setup=False)
    view = session.view(perspective='p1')
    casts = [a for a in view['legal_actions'] if a['type'] == 'cast_spell']
    ids = {a['instance_id'] for a in casts}
    assert {own.instance_id, foreign.instance_id} <= ids and unrelated.instance_id not in ids
    session.apply_action(next(a for a in casts if a['instance_id'] == foreign.instance_id), actor_id='p1')
    assert foreign.zone == Zone.STACK and foreign.controller_id == 'p1'
    assert not any(a.get('instance_id') == own.instance_id and a['type'] == 'cast_spell'
                   for a in session.view(perspective='p1')['legal_actions'])
