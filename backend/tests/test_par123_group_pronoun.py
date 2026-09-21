"""PAR-123 — a bare "it" under a group-subject trigger is the object that fired it.

"Whenever a creature you control becomes blocked, return it to its owner's hand" and
"whenever a creature you control attacks alone, untap ~" print the same untargeted
effect, and untargeted means "the ability's own source". The parser is the only place
the words are visible, so it stamps the pronoun reading (`target_kind:
"trigger_subject"`) and leaves "~" acting on the source. Parse tests pin the two
readings apart; execute tests make the triggers fire and watch which permanent moves.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _named
from tests.test_par120_count_phrase import _creature, _put

BOUNCE = "Whenever a creature you control becomes blocked, return it to its owner's hand."


def _effects(oracle: str, name: str = "Source", types: str = "Enchantment"):
    result = _parse(Card(id=name, name=name, type_line=types, oracle_text=oracle))
    assert result.modeled, oracle
    return [(s.trigger, e) for s in result.specs if s.ability_kind == "triggered" for e in s.effects]


# ---------------------------------------------------------------------------
# Parse: the pronoun and the explicit source read differently
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "oracle, effect_type",
    [
        (BOUNCE, "return_to_hand"),
        ("Whenever a creature you control attacks alone, untap it.", "tap"),
        ("Whenever a creature you control deals combat damage to a player, exile it.", "exile"),
        ("Whenever a creature you control deals combat damage to a player, "
         "exile it, then return it to the battlefield under its owner's control.", "blink"),
    ],
)
def test_a_bare_it_names_the_trigger_subject(oracle, effect_type):
    [(trigger, effect)] = _effects(oracle)
    assert effect.type == effect_type
    assert effect.params["target_kind"] == "trigger_subject"
    assert effect.params["trigger_event_key"] == "__group_subject__"


@pytest.mark.parametrize(
    "oracle, effect_type",
    [
        ("Whenever a creature you control becomes blocked, return this enchantment to its owner's hand.",
         "return_to_hand"),
        ("Whenever a creature you control attacks alone, untap this enchantment.", "tap"),
    ],
)
def test_an_explicit_source_stays_the_source(oracle, effect_type):
    [(trigger, effect)] = _effects(oracle)
    assert effect.type == effect_type
    assert effect.params.get("target_kind") is None


def test_the_source_named_first_keeps_a_following_it_on_the_source():
    # "~ … it": the pronoun continues the explicit subject, so nothing is retargeted.
    effects = _effects(
        "Whenever a creature you control attacks alone, exile this enchantment, "
        "then return it to the battlefield under its owner's control."
    )
    assert [e.type for _, e in effects] == ["exile", "return_self_to_battlefield"]
    assert all(e.params.get("target_kind") is None for _, e in effects if e.type == "exile")


@pytest.mark.parametrize(
    "name",
    ["Cunning Evasion", "Grazilaxx, Illithid Scholar", "Dissipation Field", "Finest Hour",
     "Raiyuu, Storm's Edge", "Gossip's Talent", "Baloth Prime"],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


def test_baloth_primes_untap_this_creature_is_not_retargeted():
    # "…create a Beast token and untap this creature" — the source, not the sacrificed land.
    result = parse_oracle(_named("Baloth Prime"))
    taps = [e for s in result.specs for e in s.effects if e.type == "tap"]
    assert [e.params.get("target_kind") for e in taps] == [None]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _blocked(engine, state, creature):
    state.fire_event(GameEvent(
        EventType.BECOMES_BLOCKED, attacker=creature.name, player_id=creature.controller_id,
        instance_id=creature.instance_id, object_types=sorted(creature.type_words), blocker_count=1,
    ))
    engine.resolve_until_stable()


def _zone_of(state, obj) -> str:
    if any(o is obj for o in state.battlefield):
        return "battlefield"
    return "hand" if any(o is obj for o in state.player_by_id(obj.owner_id).hand) else "elsewhere"


def test_the_blocked_creature_is_bounced_not_the_enchantment():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    aura = _put(state, BOUNCE, name="Evasion", types="Enchantment")
    attacker = _creature(state, "Attacker")
    bystander = _creature(state, "Bystander")
    _blocked(engine, state, attacker)
    assert _zone_of(state, attacker) == "hand"
    assert _zone_of(state, aura) == "battlefield"
    assert _zone_of(state, bystander) == "battlefield"


def test_an_opponents_blocked_creature_does_not_trigger_it():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    _put(state, BOUNCE, name="Evasion", types="Enchantment")
    theirs = _creature(state, "Theirs", owner="p2")
    _blocked(engine, state, theirs)
    assert _zone_of(state, theirs) == "battlefield"


def test_an_explicit_source_bounces_the_source():
    engine, state = _engine()
    state.current_step = "combat_declare_blockers"
    aura = _put(
        state,
        "Whenever a creature you control becomes blocked, return this enchantment to its owner's hand.",
        name="Evasion", types="Enchantment",
    )
    attacker = _creature(state, "Attacker")
    _blocked(engine, state, attacker)
    assert _zone_of(state, aura) == "hand"
    assert _zone_of(state, attacker) == "battlefield"


def test_dissipation_field_returns_the_permanent_that_dealt_the_damage():
    engine, state = _engine()
    state.current_step = "combat_damage"
    field = _put(state, "Whenever a permanent deals damage to you, return it to its owner's hand.",
                 name="Field", types="Enchantment")
    hitter = _creature(state, "Hitter", owner="p2")
    engine.rules.deal_damage(state.player_by_id("p1"), 1, source=hitter)
    engine.resolve_until_stable()
    assert _zone_of(state, hitter) == "hand"
    assert _zone_of(state, field) == "battlefield"


def test_blink_returns_the_creature_that_dealt_combat_damage():
    engine, state = _engine()
    state.current_step = "combat_damage"
    source = _put(
        state,
        "Whenever a creature you control deals combat damage to a player, "
        "exile it, then return it to the battlefield under its owner's control.",
        name="Talent", types="Enchantment",
    )
    hitter = _creature(state, "Hitter")
    hitter.counters["+1/+1"] = 2
    source.counters["+1/+1"] = 2
    engine.rules.deal_damage(state.player_by_id("p2"), 1, source=hitter, combat=True)
    engine.resolve_until_stable()
    # RULE 400.7: it re-entered as a new object, so its counters are gone; the source's are not
    assert _zone_of(state, hitter) == "battlefield"
    assert not hitter.counters.get("+1/+1")
    assert source.counters.get("+1/+1") == 2


def test_baloth_primes_untap_hits_the_source_only():
    engine, state = _engine()
    state.current_step = "main1"
    prime = _put(state, "Whenever you sacrifice a land, untap this creature.", name="Prime",
                 types="Creature — Beast")
    land_card = Card(id="Land", name="Land", type_line="Land", is_land=True)
    land = GameObject(land_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    land.controller_id = "p1"
    land.tapped = True
    state.add_to_battlefield(land)
    prime.tapped = True
    state.fire_event(GameEvent(
        EventType.SACRIFICE, player_id="p1", controller_id="p1", instance_id=land.instance_id,
        object_types=sorted(land.type_words),
    ))
    engine.resolve_until_stable()
    assert prime.tapped is False
    assert land.tapped is True


# ---------------------------------------------------------------------------
# "it gets +N/+N [and gains …] until end of turn" under a group trigger
# ---------------------------------------------------------------------------


def _power(state, obj) -> int:
    from mtg_analyzer.game import continuous  # noqa: F401  (recompute below)

    return obj.power


def test_the_attacker_that_fired_the_trigger_gets_the_pump_not_the_enchantment():
    engine, state = _engine()
    state.current_step = "declare_attackers"
    charge = _put(state, "Whenever a creature you control attacks, it gets +2/+2 until end of turn.",
                  name="Charge", types="Enchantment")
    attacker = _creature(state, "Attacker")
    bystander = _creature(state, "Bystander")
    attacker.summoning_sick = False
    engine.declare_attackers(state.active_player, [attacker])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert attacker.power == 3          # printed 1, +2
    assert bystander.power == 1
    assert charge.card.power is None


def test_a_pump_that_grants_a_keyword_too():
    engine, state = _engine()
    _put(state, "Whenever a creature you control enters, it gets +2/+0 and gains haste until end of turn.",
         name="Web", types="Enchantment")
    late = _creature(state, "Late")
    from tests.test_par119_object_trigger_head import _fire_enter

    _fire_enter(engine, state, late)
    engine.recompute_continuous_effects()
    assert late.power == 3
    assert "haste" in {k.lower() for k in late.granted_keywords} | {k.lower() for k in late.temp_keywords}
