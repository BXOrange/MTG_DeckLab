"""End-to-end checks for the "Wyleth Equip" commander deck's hand-authored
catalogue entries (`game/ability_catalogue.py`) and the engine primitives
they lean on (mass board wipes, the "combat damage to a player"/"equipped
creature" trigger family, Living Weapon, Renown, per-count static buffs).

Reference: CLAUDE.md's "Hand-authoring a card's abilities directly" section;
docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md §13's testing checklist.
Not exhaustive over every card in the deck — one end-to-end test per
*mechanic family* the deck introduced, using real cached cards.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import (
    DestroyEffect,
    ExileGainLifeToControllerEffect,
    TargetPlayerDrawLoseLifeEffect,
    UnattachTapIndestructibleEffect,
)
from mtg_analyzer.game import continuous
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _bound_battlefield_obj(state, card: Card, controller="p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=40, starting_hand=0
    )


def test_wyleth_draws_a_card_per_attached_aura_and_equipment():
    eng = _engine()
    state = eng.state
    wyleth = _bound_battlefield_obj(state, _card("Wyleth, Soul of Steel"))
    sword = _bound_battlefield_obj(state, _card("Sword of the Animist"))
    umbra = _bound_battlefield_obj(state, _card("Hyena Umbra"))
    sword.attached_to = wyleth.instance_id
    umbra.attached_to = wyleth.instance_id
    continuous.recompute(state)
    # Sword of the Animist has its *own* "whenever equipped creature attacks"
    # trigger (search a basic land) that also fires here — an empty library
    # makes that a harmless no-op instead of opening a second pending choice.
    mountain = _card("Mountain")
    for _ in range(5):
        state.active_player.library.append(GameObject(mountain, owner_id="p1", zone=Zone.LIBRARY))

    eng.begin_turn()
    state.current_step = "declare_attackers"
    before = len(state.active_player.hand)
    eng.declare_attackers(state.active_player, [wyleth])
    eng.resolve_until_stable()
    if state.pending_choice and state.pending_choice.get("kind") == "search":
        eng.rules.resolve_search_choice(None)  # decline Sword of the Animist's land tutor
        eng.resolve_until_stable()

    assert len(state.active_player.hand) - before == 2


def test_akiri_second_ability_unattaches_taps_and_grants_indestructible():
    eng = _engine()
    state = eng.state
    host = _bound_battlefield_obj(state, _card("Sun Titan"))
    equip = _bound_battlefield_obj(state, _card("Colossus Hammer"))
    equip.attached_to = host.instance_id

    UnattachTapIndestructibleEffect(target=equip).apply(eng.rules.context)

    assert equip.attached_to is None
    assert host.tapped is True
    assert "indestructible" in host.temp_keywords


def test_living_weapon_creates_a_germ_and_self_attaches():
    eng = _engine()
    state = eng.state
    kaldra = GameObject(_card("Kaldra Compleat"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(kaldra)
    state.add_to_battlefield(kaldra)

    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=kaldra.name,
            instance_id=kaldra.instance_id, object_types=sorted(kaldra.type_words),
        )
    )
    eng.resolve_until_stable()

    germs = [o for o in state.battlefield if "Germ" in o.name]
    assert len(germs) == 1
    assert kaldra.attached_to == germs[0].instance_id


def test_relic_seeker_renown_fires_the_search_for_equipment():
    eng = _engine()
    state = eng.state
    relic = _bound_battlefield_obj(state, _card("Relic Seeker"))
    state.active_player.library.append(
        GameObject(_card("Colossus Hammer"), owner_id="p1", zone=Zone.LIBRARY)
    )

    eng.begin_turn()
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [relic])
    state.current_step = "declare_blockers"
    eng.declare_blockers(state.player_by_id("p2"), [])
    state.current_step = "combat_damage"
    eng._step_combat_damage()
    eng.resolve_until_stable()

    assert relic.renowned is True
    assert relic.plus_one_counters == 1
    # "you may search…" is itself an optional trigger (RULE 603.5) — a
    # do/decline choice comes first, reusing the "trigger_target" kind
    # (`RulesEngine._trigger_may_choice`); answering "do" resolves it and
    # opens the actual library-search choice.
    assert state.pending_choice is not None
    assert state.pending_choice.get("kind") == "trigger_target"
    eng.rules.resolve_trigger_target_choice("do")
    eng.resolve_until_stable()
    assert state.pending_choice is not None
    assert state.pending_choice.get("kind") == "search"


def test_swords_to_plowshares_exiles_and_gains_life_equal_to_power():
    eng = _engine()
    state = eng.state
    titan = _bound_battlefield_obj(state, _card("Sun Titan"), controller="p2")
    continuous.recompute(state)
    power = titan.power
    life_before = state.player_by_id("p2").life

    ExileGainLifeToControllerEffect(target=titan).apply(eng.rules.context)

    assert titan not in state.battlefield
    assert state.player_by_id("p2").life == life_before + power


def test_wrath_of_god_destroys_every_creature_and_ignores_regeneration():
    eng = _engine()
    state = eng.state
    mine = _bound_battlefield_obj(state, _card("Sun Titan"), controller="p1")
    theirs = _bound_battlefield_obj(state, _card("Relic Seeker"), controller="p2")
    eng.rules.regenerate(theirs)  # a shield up — still shouldn't save it

    DestroyEffect(selector="all_creatures", can_be_regenerated=False).apply(eng.rules.context)

    assert mine not in state.battlefield
    assert theirs not in state.battlefield


def test_sign_in_blood_draws_and_loses_life_on_the_same_target():
    eng = _engine()
    state = eng.state
    opponent = state.player_by_id("p2")
    for _ in range(3):
        opponent.library.append(GameObject(_card("Sun Titan"), owner_id="p2", zone=Zone.LIBRARY))
    before_hand, before_life = len(opponent.hand), opponent.life

    TargetPlayerDrawLoseLifeEffect(draw_count=2, life_loss=2, target=opponent).apply(eng.rules.context)

    assert len(opponent.hand) - before_hand == 2
    assert opponent.life == before_life - 2


def test_colossus_hammer_grants_pump_and_strips_flying():
    eng = _engine()
    state = eng.state
    host = _bound_battlefield_obj(state, _card("Armored Skyhunter"))  # printed Flying
    from mtg_analyzer.game import combat

    assert combat.has(host, "flying") is True  # sanity: it does start with flying

    hammer = _bound_battlefield_obj(state, _card("Colossus Hammer"))
    hammer.attached_to = host.instance_id
    continuous.recompute(state)

    assert host.power == host.card.power + 10
    assert host.toughness == host.card.toughness + 10
    assert combat.has(host, "flying") is False


def test_austere_command_offers_six_choose_two_modal_cast_combinations():
    eng = _engine()
    state = eng.state
    obj = GameObject(_card("Austere Command"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.active_player.hand.append(obj)
    eng.begin_turn()
    state.current_step = "main1"
    state.active_player.mana_pool.add("W", 3)
    state.active_player.mana_pool.add("C", 3)

    assert obj.spell_modes is not None
    assert len(obj.spell_modes) == 4
    assert obj.spell_modes_choose == 2

    actions = [
        a for a in eng.legal_actions(state.active_player)
        if a.get("type") == "cast_spell" and a.get("instance_id") == obj.instance_id
    ]
    # C(4, 2) = 6 legal mode combinations, each offered as its own cast action.
    assert len(actions) == 6


def test_sunforger_unattaches_itself_and_free_casts_a_found_instant():
    eng = _engine()
    state = eng.state
    host = _bound_battlefield_obj(state, _card("Sun Titan"))
    sunforger = _bound_battlefield_obj(state, _card("Sunforger"))
    sunforger.attached_to = host.instance_id
    continuous.recompute(state)
    state.active_player.library.append(
        GameObject(_card("Swords to Plowshares"), owner_id="p1", zone=Zone.LIBRARY)
    )
    state.active_player.mana_pool.add("R", 1)
    state.active_player.mana_pool.add("W", 1)

    ability = sunforger.activated_abilities[0]
    assert eng.can_activate(state.active_player, sunforger, ability)
    eng.activate_ability(state.active_player, sunforger, 0)
    eng.resolve_until_stable()

    assert sunforger.attached_to is None  # "Unattach this Equipment" cost paid
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    assert choice["destination"] == "cast_free"
    found = next(o for o in choice["options"] if o.get("instance_id"))
    eng.rules.resolve_search_choice(found["instance_id"])

    assert any(
        getattr(item.obj, "name", None) == "Swords to Plowshares" for item in state.stack
    )


def test_nettlecyst_living_weapon_and_per_artifact_static():
    eng = _engine()
    state = eng.state
    nettlecyst = GameObject(_card("Nettlecyst"), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(nettlecyst)
    state.add_to_battlefield(nettlecyst)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, controller_id="p1", object=nettlecyst.name,
            instance_id=nettlecyst.instance_id, object_types=sorted(nettlecyst.type_words),
        )
    )
    eng.resolve_until_stable()

    germs = [o for o in state.battlefield if "Germ" in o.name]
    assert len(germs) == 1
    germ = germs[0]
    assert nettlecyst.attached_to == germ.instance_id
    assert germ.power == 1 and germ.toughness == 1  # Nettlecyst itself: one artifact

    _bound_battlefield_obj(state, _card("Sol Ring"))
    continuous.recompute(state)
    assert germ.power == 2 and germ.toughness == 2  # + Sol Ring
