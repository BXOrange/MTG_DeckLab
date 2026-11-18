"""PAR-284 milestone 19: "put into your graveyard this way" tallies (RULE 701.17a, 608.2c) and damage / life event amounts.

A milled card is "put into its owner's graveyard", so "for each creature card put into their graveyard this way" reads
the `milled` pool (`effect_amounts.THIS_WAY_POOLS`) -- but only behind a real `mill` instruction.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.test_par284_this_way_windows import _card, _engine


def _stock_library(player, kinds):
    """Library listed bottom-first (the top card is the last entry): each entry a card-type word."""
    for i, kind in enumerate(kinds):
        card = _card(f"L{player.id}{i}", "Creature — Bear" if kind == "creature" else "Land",
                     is_creature=kind == "creature", is_land=kind == "land")
        player.library.append(GameObject(card, owner_id=player.id, zone=Zone.LIBRARY))


def _cast(eng, oracle, *, targets=None, x=0, name="Probe Spell"):
    card = _card(name, "Sorcery", oracle, is_sorcery=True)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"C": 1 + x})
    eng.cast_spell(p1, obj, targets=targets, x=x)
    eng.resolve_until_stable()
    return p1


def test_put_into_graveyard_this_way_is_the_milled_pool():
    specs = parse_effect_body("target player mills 4 cards. you draw a card for each creature card put into their graveyard this way.")
    bind = next(s for s in specs if s.type == "bind")
    assert bind.params["amount"] == {"kind": "this_way_count", "pool": "milled", "card_type": "creature"}


def test_comma_then_form_splits_before_the_payoff():
    specs = parse_effect_body("target opponent mills 3 cards, then you draw a card for each land card put into their graveyard this way.")
    assert [s.type for s in specs] == ["mill", "bind"]


@pytest.mark.parametrize("oracle", [
    # a pile put into the graveyard is not a mill (Intrude on the Mind): no `mill` producer, so it stays unclaimed
    "Put that pile into your hand and the other into your graveyard. Draw a card for each card put into your graveyard this way.",
])
def test_non_mill_producer_is_refused(oracle):
    assert not parse_oracle(_card("Odd", "Sorcery", oracle, is_sorcery=True)).modeled


def test_coerced_confession_draws_for_each_milled_creature():
    eng = _engine()
    p1, p2 = eng.state.players
    _stock_library(p2, ["land", "creature", "creature", "creature", "land"])  # the top four: 3 creatures, 1 land
    _stock_library(p1, ["land"] * 5)
    _cast(eng, "Target player mills four cards. You draw a card for each creature card put into their graveyard this way.",
          targets=[p2])
    assert len(p2.graveyard) == 4
    assert sum(1 for o in p1.hand if o.card.name.startswith("L")) == 3


def test_liliana_indignation_drains_two_per_milled_creature_and_announces_its_target():
    eng = _engine()
    p1, p2 = eng.state.players
    _stock_library(p1, ["land", "creature", "creature", "land", "creature", "creature"])  # the top four: 3 creatures
    _cast(eng, "Mill X cards. Target player loses 2 life for each creature card put into your graveyard this way.",
          targets=[p2], x=4)
    assert p2.life == 20 - 2 * 3
    assert p1.life == 20


# -- damage / life event amounts -----------------------------------------------------------------------------------


def _board(eng, oracle, *, name="Host", type_line="Creature — Bear", owner="p1", power=1, toughness=3):
    card = _card(name, type_line, oracle, is_creature="Creature" in type_line, power=power if "Creature" in type_line else None,
                 toughness=toughness if "Creature" in type_line else None)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    attach_to_object(obj, result.specs)
    eng.state.add_to_battlefield(obj)
    return obj


@pytest.mark.parametrize("phrase, expected", [
    ("the damage dealt to your opponents this turn", {"subject": "player", "scope": "not_you", "recipient": True}),
    ("the amount of damage dealt to it this turn", {"subject": "self", "recipient": True}),
    ("the damage dealt to you so far this turn by artifacts",
     {"subject": "group", "controller": "any", "other": False, "filter": {"card_type": "artifact"}, "recipient_is_you": True}),
])
def test_damage_taken_phrases_sum_the_turns_damage_events(phrase, expected):
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    from mtg_analyzer.parser.oracle.segmenter.overrides_and_amounts import event_amount

    amount = event_amount(phrase, reading=ClauseReading(self_subject=True))
    assert amount["kind"] == "event_count" and amount["sum_amount"] is True
    assert amount["trigger"]["event"] == "DAMAGE" and amount["trigger"]["condition"] == expected


@pytest.mark.parametrize("phrase", [
    "the damage dealt to ~ this turn by other sources named ~",  # a named-source qualifier is not modeled
    "the damage dealt to your opponents this turn by creatures",  # a source group beyond "you" is not modeled
])
def test_unmodeled_damage_qualifiers_fail_closed(phrase):
    from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
    from mtg_analyzer.parser.oracle.segmenter.overrides_and_amounts import event_amount

    assert event_amount(phrase, reading=ClauseReading(self_subject=True)) is None


def test_tangled_colony_makes_a_rat_per_damage_it_took_this_turn():
    eng = _engine()
    p1 = eng.state.players[0]
    colony = _board(eng, 'When ~ dies, create X 1/1 black Rat creature tokens with "~ can\'t block," where X is the '
                         "amount of damage dealt to it this turn.", name="Tangled Colony", toughness=3)
    eng.rules.deal_damage(colony, 2)
    eng.rules.deal_damage(colony, 1)
    eng.resolve_until_stable()
    assert colony.zone is Zone.GRAVEYARD
    assert sum(1 for o in eng.state.battlefield if o.is_token and o.controller_id == "p1") == 3


def test_reverse_polarity_doubles_only_artifact_damage_dealt_to_you():
    eng = _engine()
    p1 = eng.state.players[0]
    artifact = _board(eng, "", name="Spike", type_line="Artifact", owner="p2")
    bear = _board(eng, "", name="Bear", owner="p2")
    eng.rules.deal_damage(p1, 3, source=artifact)
    eng.rules.deal_damage(p1, 4, source=bear)  # not an artifact: ignored
    assert p1.life == 20 - 7
    _cast(eng, "You gain X life, where X is twice the damage dealt to you so far this turn by artifacts.")
    assert p1.life == 20 - 7 + 6


def test_blood_tyrant_counts_every_life_actually_lost_this_way():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng = _engine()
    tyrant = _board(eng, "At the beginning of your upkeep, each player loses 1 life. Put a +1/+1 counter on ~ for each "
                         "1 life lost this way.", name="Blood Tyrant")
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", player_id="p1", controller_id="p1"))
    eng.resolve_until_stable()
    assert [p.life for p in eng.state.players] == [19, 19]
    assert tyrant.counters.get("+1/+1") == 2


def test_event_payload_amount_needs_the_matching_trigger():
    # A spell has no life-gained event to read: stays unclaimed rather than measuring 0.
    spell = _card("Odd", "Instant", "Target creature gets +X/+X until end of turn, where X is the amount of life you gained.",
                  is_instant=True)
    assert not parse_oracle(spell).modeled
    wrong = _card("Odd2", "Creature — Bear", "Whenever you lose life, target creature gets +X/+X until end of turn, where X "
                  "is the amount of life you gained.", is_creature=True, power=1, toughness=1)
    assert not parse_oracle(wrong).modeled
    right = _card("Odd3", "Creature — Bear", "Whenever you gain life, target creature gets +X/+X until end of turn, where X "
                  "is the amount of life you gained.", is_creature=True, power=1, toughness=1)
    assert parse_oracle(right).modeled


def test_gain_life_trigger_pumps_by_the_gained_amount():
    eng = _engine()
    host = _board(eng, "Whenever you gain life, target creature gets +X/+X until end of turn, where X is the amount of "
                       "life you gained.", name="Pumper")
    eng.rules.gain_life(eng.state.players[0], 3)
    eng.resolve_until_stable()
    eng.resolve_pending_choice(eng.state.pending_choice["options"][0]["id"])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert host.power == 1 + 3
