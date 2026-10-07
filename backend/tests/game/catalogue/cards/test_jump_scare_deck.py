"""Real gameplay for the Jump Scare! (Duskmourn: House of Horror Commander) catalogue entries."""

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=12):
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
                power=power, toughness=toughness, mana_cost_string="{%d}" % mv if mv else "", **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=None, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _face_down(engine, player="p1"):
    return [o for o in engine.state.battlefield if o.face_down and o.controller_id == player]


def _answer_all(engine, pick_first=True, limit=12):
    """Answer pending choices, always taking the first option."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        engine.resolve_pending_choice(str(options[0]["id"]) if options and pick_first else None)


def _commander(engine, player="p1"):
    obj = _filler(engine, "Their Commander", power=1, toughness=1, player=player)
    obj.is_commander = True
    return obj


def test_arixmethes_is_a_land_while_it_has_slumber_counters_and_wakes_when_they_run_out():
    engine = _game()
    p1, _ = engine.state.players
    arix = _card(engine, "Arixmethes, Slumbering Isle", zone=Zone.HAND)
    _cast(engine, arix, {"G": 1, "U": 1, "C": 2})
    assert arix.zone == Zone.BATTLEFIELD and arix.tapped
    assert arix.counters.get("slumber") == 5
    continuous.recompute(engine.state)
    assert arix.is_land and not arix.is_creature
    arix.counters["slumber"] = 1
    for _ in range(1):
        spell = _filler(engine, "Spell", "Sorcery", zone=Zone.HAND)
        engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", controller_id="p1",
                                          instance_id=spell.instance_id, object=spell.name))
        engine.resolve_until_stable()
        _answer_all(engine)
    assert arix.counters.get("slumber", 0) == 0
    continuous.recompute(engine.state)
    assert arix.is_creature and not arix.is_land


def test_curator_beastie_manifests_dread_and_gives_colorless_creatures_two_counters():
    engine = _game()
    p1, _ = engine.state.players
    beastie = _card(engine, "Curator Beastie", zone=Zone.HAND)
    _cast(engine, beastie, {"G": 2, "C": 4})
    _answer_all(engine)
    manifested = _face_down(engine)
    assert len(manifested) == 1
    assert manifested[0].counters.get("+1/+1") == 2  # a face-down 2/2 is colorless
    assert beastie.counters.get("+1/+1", 0) == 0 and beastie.zone == Zone.BATTLEFIELD
    continuous.recompute(engine.state)
    assert (manifested[0].power, manifested[0].toughness) == (4, 4)


def test_deathmist_raptor_returns_when_a_permanent_is_turned_face_up_face_up_or_face_down():
    engine = _game()
    p1, _ = engine.state.players
    raptor = _card(engine, "Deathmist Raptor", zone=Zone.GRAVEYARD)
    flipper = _filler(engine, "Flipper", power=2, toughness=2)
    engine.rules.turn_face_down(flipper, "manifest")
    assert flipper.face_down
    engine.rules.turn_face_up(flipper)
    engine.resolve_until_stable()
    # Optional trigger, then the face up/down choice.
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice("face_down" if "face_down" in ids else (ids[0] if ids else "accept"))
    assert raptor.zone == Zone.BATTLEFIELD and raptor.face_down


def test_disorienting_choice_ramps_for_each_permanent_that_stays():
    engine = _game(library=0)
    p1, p2 = engine.state.players
    keep = _filler(engine, "Their Rock", "Artifact", mv=2, player="p2")
    forest = CardDatabase(DB_PATH).get_card("Forest")
    for _ in range(3):
        o = GameObject(forest, owner_id="p1", zone=Zone.LIBRARY)
        p1.library.append(o)
    spell = _card(engine, "Disorienting Choice", zone=Zone.HAND)
    _cast(engine, spell, {"G": 1, "C": 3}, targets=[keep])
    # The target was announced; its controller declines to exile it; we fetch one land.
    for _ in range(6):
        choice = engine.state.pending_choice
        if choice is None:
            break
        if choice.get("player_id") == "p2":
            engine.resolve_pending_choice("decline")
        else:
            ids = [str(o["id"]) for o in choice.get("options", [])]
            engine.resolve_pending_choice(str(keep.instance_id) if str(keep.instance_id) in ids else ids[0])
    lands = [o for o in engine.state.battlefield if o.controller_id == "p1" and o.is_land]
    assert keep.zone == Zone.BATTLEFIELD
    assert len(lands) == 1 and lands[0].tapped


def test_disorienting_choice_fetches_nothing_if_the_permanent_is_exiled():
    engine = _game(library=0)
    p1, p2 = engine.state.players
    keep = _filler(engine, "Their Rock", "Artifact", mv=2, player="p2")
    forest = CardDatabase(DB_PATH).get_card("Forest")
    p1.library.append(GameObject(forest, owner_id="p1", zone=Zone.LIBRARY))
    spell = _card(engine, "Disorienting Choice", zone=Zone.HAND)
    _cast(engine, spell, {"G": 1, "C": 3}, targets=[keep])
    for _ in range(6):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(str(keep.instance_id) if str(keep.instance_id) in ids else ids[0])
    assert keep.zone == Zone.EXILE
    assert not [o for o in engine.state.battlefield if o.controller_id == "p1" and o.is_land]


def test_experimental_lab_manifests_dread_and_pumps_that_creature():
    engine = _game()
    lab = _card(engine, "Experimental Lab // Staff Room", zone=Zone.HAND)
    _cast(engine, lab, {"G": 1, "C": 3})
    _answer_all(engine)
    manifested = _face_down(engine)
    assert len(manifested) == 1
    assert manifested[0].counters.get("+1/+1") == 2 and manifested[0].counters.get("trample") == 1


def test_growing_dread_manifests_and_grows_permanents_as_they_turn_face_up():
    engine = _game()
    dread = _card(engine, "Growing Dread", zone=Zone.HAND)
    _cast(engine, dread, {"G": 1, "U": 1})
    _answer_all(engine)
    flipper = _filler(engine, "Flipper", power=2, toughness=2)
    engine.rules.turn_face_down(flipper, "manifest")
    engine.rules.turn_face_up(flipper)
    engine.resolve_until_stable()
    assert flipper.counters.get("+1/+1") == 1


def test_kheru_spellsnatcher_counters_a_spell_exiles_it_and_lets_you_cast_it_free_later():
    engine = _game()
    p1, p2 = engine.state.players
    snatcher = _card(engine, "Kheru Spellsnatcher")
    engine.rules.turn_face_down(snatcher, "morph")
    foe = _filler(engine, "Their Bolt", "Sorcery", mv=2, player="p2", zone=Zone.HAND)
    engine.state.current_step = "main1"
    p2.mana_pool.add_many({"C": 2})
    engine.state.active_player_index = 1
    engine.cast_spell(p2, foe, targets=None, target_groups=None)
    assert foe in [i.obj for i in engine.state.stack]
    engine.rules.turn_face_up(snatcher)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "trigger_target"
    engine.resolve_pending_choice(str(foe.instance_id))
    engine.resolve_until_stable()
    assert foe.zone == Zone.EXILE
    assert engine.state.exile_cast_condition[foe.instance_id][0] == "p1"
    assert foe.instance_id in engine.state.free_cast_instance_ids


@pytest.mark.parametrize("counters,power_is_even", [(0, True), (1, False), (2, True)])
def test_kianne_flash_depends_on_the_parity_of_its_power(counters, power_is_even):
    engine = _game()
    p1, _ = engine.state.players
    kianne = _card(engine, "Kianne, Corrupted Memory")
    kianne.counters["+1/+1"] = counters
    continuous.recompute(engine.state)
    assert (kianne.power % 2 == 0) is power_is_even
    sorcery = _filler(engine, "Sorcery", "Sorcery", zone=Zone.HAND)
    creature = _filler(engine, "Creature", "Creature", power=1, toughness=1, zone=Zone.HAND)
    assert continuous.has_standing_flash_permission(engine.state, p1, sorcery.card) is power_is_even
    assert continuous.has_standing_flash_permission(engine.state, p1, creature.card) is (not power_is_even)


def test_kianne_grows_when_you_draw():
    engine = _game()
    p1, _ = engine.state.players
    kianne = _card(engine, "Kianne, Corrupted Memory")
    engine.rules.draw(p1, 1)
    engine.resolve_until_stable()
    assert kianne.counters.get("+1/+1") == 1


def test_primordial_mist_exiles_a_face_down_permanent_so_you_can_play_it_this_turn():
    engine = _game()
    p1, _ = engine.state.players
    mist = _card(engine, "Primordial Mist")
    hidden = _filler(engine, "Hidden Bear", "Creature — Bear", mv=2, power=2, toughness=2)
    engine.rules.turn_face_down(hidden, "manifest")
    engine.state.current_step = "main1"
    engine.activate_ability(p1, mist, 0)
    engine.resolve_until_stable()
    assert hidden.zone == Zone.EXILE and not hidden.face_down
    assert engine.state.temp_play_permissions.get(hidden.instance_id) is not None
    assert engine.state.temp_play_permission_player.get(hidden.instance_id) == "p1"


def test_primordial_mist_needs_a_face_down_permanent_to_activate():
    engine = _game()
    p1, _ = engine.state.players
    mist = _card(engine, "Primordial Mist")
    engine.state.current_step = "main1"
    assert not engine.can_activate(p1, mist, mist.activated_abilities[0])


def test_rashmi_casts_a_cheaper_top_card_free_otherwise_it_goes_to_hand():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Rashmi, Eternities Crafter")
    cheap = _filler(engine, "Cheap Bear", "Creature — Bear", mv=1, power=1, toughness=1, zone=Zone.LIBRARY)
    pricey = _filler(engine, "Pricey Bear", "Creature — Bear", mv=5, power=5, toughness=5, zone=Zone.LIBRARY)
    p1.library[:] = [o for o in p1.library if o not in (cheap, pricey)] + [pricey, cheap]  # cheap on top
    spell = _filler(engine, "Three Spell", "Sorcery", mv=3, zone=Zone.HAND)
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", controller_id="p1",
                                      instance_id=spell.instance_id, object=spell.name, mana_value=3))
    engine.resolve_until_stable()
    _answer_all(engine)
    assert cheap.zone in (Zone.STACK, Zone.BATTLEFIELD) and cheap not in p1.hand


def test_rashmi_puts_a_more_expensive_top_card_into_your_hand():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Rashmi, Eternities Crafter")
    pricey = _filler(engine, "Pricey Bear", "Creature — Bear", mv=5, power=5, toughness=5, zone=Zone.LIBRARY)
    p1.library[:] = [o for o in p1.library if o is not pricey] + [pricey]
    spell = _filler(engine, "Three Spell", "Sorcery", mv=3, zone=Zone.HAND)
    engine.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", controller_id="p1",
                                      instance_id=spell.instance_id, object=spell.name, mana_value=3))
    engine.resolve_until_stable()
    _answer_all(engine)
    assert pricey in p1.hand


def test_sandwurm_convergence_stops_flyers_from_attacking_you_and_makes_wurms():
    engine = _game()
    p1, p2 = engine.state.players
    _card(engine, "Sandwurm Convergence", player="p2")
    flyer = _filler(engine, "Flyer", "Creature — Bird", power=1, toughness=1, keywords=["Flying"])
    walker = _filler(engine, "Walker", power=1, toughness=1)
    continuous.recompute(engine.state)
    defender = engine.legal_defenders_for(engine.state.active_player)[0]
    assert not engine._can_attack(p1, flyer, p2)
    assert engine._can_attack(p1, walker, p2)


def test_sandwurm_convergence_makes_a_wurm_at_your_end_step():
    engine = _game()
    _card(engine, "Sandwurm Convergence")
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    wurms = _named(engine, "Wurm")
    assert len(wurms) == 1 and (wurms[0].power, wurms[0].toughness) == (5, 5)


def test_scroll_of_fate_manifests_a_card_from_your_hand():
    engine = _game()
    p1, _ = engine.state.players
    scroll = _card(engine, "Scroll of Fate")
    held = _filler(engine, "Held Bear", "Creature — Bear", mv=2, power=3, toughness=3, zone=Zone.HAND)
    engine.state.current_step = "main1"
    engine.activate_ability(p1, scroll, 0)
    engine.resolve_until_stable()
    _answer_all(engine)
    assert held.zone == Zone.BATTLEFIELD and held.face_down
    assert (held.power, held.toughness) == (2, 2)


def test_shriekwood_devourer_untaps_lands_up_to_the_greatest_attacking_power():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Shriekwood Devourer")
    lands = [_filler(engine, f"Forest{i}", "Basic Land — Forest") for i in range(4)]
    for land in lands:
        land.tapped = True
    big = _filler(engine, "Big", power=3, toughness=3)
    small = _filler(engine, "Small", power=1, toughness=1)
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    first = engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": big, "defender": first}, {"attacker": small, "defender": first}])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    for _ in range(6):
        choice = state.pending_choice
        if choice is None:
            break
        options = choice.get("options") or []
        engine.resolve_pending_choice(str(options[0]["id"]) if options else "decline")
    assert sum(1 for land in lands if not land.tapped) == 3


def test_they_came_from_the_pipes_manifests_dread_twice_and_draws_for_each():
    engine = _game()
    p1, _ = engine.state.players
    hand_before = len(p1.hand)
    pipes = _card(engine, "They Came from the Pipes", zone=Zone.HAND)
    _cast(engine, pipes, {"U": 1, "C": 4})
    _answer_all(engine, limit=20)
    assert len(_face_down(engine)) == 2
    assert len(p1.hand) == hand_before + 2


@pytest.mark.parametrize("has_commander", [True, False])
def test_thunderfoot_baloth_gives_the_team_two_two_and_trample_with_your_commander(has_commander):
    engine = _game()
    baloth = _card(engine, "Thunderfoot Baloth")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    if has_commander:
        _commander(engine)
    continuous.recompute(engine.state)
    base_power = int(baloth.card.power)
    bonus = 2 if has_commander else 0
    assert baloth.power == base_power + bonus
    assert bear.power == 2 + bonus
    assert combat.has(bear, "trample") is has_commander


def test_whisperwood_elemental_manifests_at_end_step():
    engine = _game()
    _card(engine, "Whisperwood Elemental")
    engine.state.current_step = "end"
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id="p1", controller_id="p1"))
    engine.resolve_until_stable()
    assert len(_face_down(engine)) == 1


def test_whisperwood_elemental_sacrifice_makes_dying_face_up_nontoken_creatures_manifest():
    engine = _game()
    p1, _ = engine.state.players
    whisper = _card(engine, "Whisperwood Elemental")
    bear = _filler(engine, "Bear", power=2, toughness=2)
    engine.state.current_step = "main1"
    engine.activate_ability(p1, whisper, 0)
    engine.resolve_until_stable()
    assert whisper.zone == Zone.GRAVEYARD
    before = len(_face_down(engine))
    engine.rules.destroy(bear)
    engine.resolve_until_stable()
    assert bear in p1.graveyard
    assert len(_face_down(engine)) == before + 1


def test_whisperwood_elemental_grant_skips_face_down_creatures():
    engine = _game()
    p1, _ = engine.state.players
    whisper = _card(engine, "Whisperwood Elemental")
    hidden = _filler(engine, "Hidden", power=2, toughness=2)
    engine.rules.turn_face_down(hidden, "manifest")
    engine.state.current_step = "main1"
    engine.activate_ability(p1, whisper, 0)
    engine.resolve_until_stable()
    before = len(_face_down(engine))
    engine.rules.destroy(hidden)
    engine.resolve_until_stable()
    assert hidden in p1.graveyard
    assert len(_face_down(engine)) == before - 1  # it died and manifested nothing


def test_yedora_returns_a_dying_nontoken_creature_as_a_face_down_forest():
    engine = _game()
    p1, _ = engine.state.players
    _card(engine, "Yedora, Grave Gardener")
    victim = _filler(engine, "Victim", "Creature — Elf", power=2, toughness=2)
    engine.rules.destroy(victim)
    engine.resolve_until_stable()
    for _ in range(4):
        choice = engine.state.pending_choice
        if choice is None:
            break
        ids = [str(o["id"]) for o in choice.get("options", [])]
        engine.resolve_pending_choice(ids[0] if ids else "accept")
    assert victim.zone == Zone.BATTLEFIELD and victim.face_down
    continuous.recompute(engine.state)
    assert victim.is_land and not victim.is_creature
    assert "forest" in victim.card.type_line.lower()
    from mtg_analyzer.game import mana_abilities

    assert mana_abilities.mana_abilities_for(victim, engine.state)


def test_yedora_ignores_tokens_and_itself():
    engine = _game()
    p1, _ = engine.state.players
    yedora = _card(engine, "Yedora, Grave Gardener")
    engine.rules.destroy(yedora)
    engine.resolve_until_stable()
    assert not any(o.face_down for o in engine.state.battlefield)
