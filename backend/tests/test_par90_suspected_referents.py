"""PAR-90 — suspected-state conditions in effect bodies."""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_repeat_offender_uses_complementary_source_suspected_conditions():
    card = Card(id="ro", name="Repeat Offender", type_line="Creature",
                is_creature=True, oracle_text=(
                    "{2}{B}: If this creature is suspected, put a +1/+1 counter on it. "
                    "Otherwise, suspect it."))
    result = parse_oracle(card)
    assert result.modeled
    effects = result.specs[0].effects
    assert effects[0].condition == {"source_is_suspected": True}
    assert effects[1].condition == {"source_is_suspected": False}


def test_rubblebelt_braggart_uses_negated_source_suspected_condition():
    card = Card(id="rb", name="Rubblebelt Braggart", type_line="Creature",
                is_creature=True, oracle_text=(
                    "Whenever this creature attacks, if it's not suspected, you may suspect it."))
    result = parse_oracle(card)
    assert result.modeled
    assert result.specs[0].effects[0].condition == {
        "kind": "not", "condition": {"kind": "flag", "flag": "is_suspected", "of": "source"},
    }


def test_agency_coroner_reads_the_sacrificed_cost_creatures_suspected_state():
    result = parse_oracle(Card(
        id="ac", name="Agency Coroner", type_line="Creature", is_creature=True,
        oracle_text=("{2}{B}, Sacrifice another creature: Draw a card. If the "
                     "sacrificed creature was suspected, draw 2 cards instead."),
    ))
    assert result.modeled
    assert [(effect.type, effect.params, effect.condition) for effect in result.specs[0].effects] == [
        ("draw", {"count": 1}, {"sacrificed_cost_was_suspected": False}),
        ("draw", {"count": 2}, {"sacrificed_cost_was_suspected": True}),
    ]


def test_primetime_suspect_uses_its_auras_host_as_the_condition_subject():
    result = parse_oracle(Card(
        id="ps", name="Primetime Suspect", type_line="Enchantment — Aura",
        oracle_text=("Whenever enchanted creature attacks, you may search your library for a "
                     "land card, put that card onto the battlefield tapped, then shuffle. If "
                     "enchanted creature is suspected, you search for 2 lands instead."),
    ))
    assert result.modeled
    assert [effect.condition for effect in result.specs[0].effects] == [
        {"attached_is_suspected": False}, {"attached_is_suspected": True},
    ]
    assert result.specs[0].effects[1].params["count"] == 2


def test_frantic_scapegoats_optional_pick_suspects_then_clears_the_source():
    oracle = ("Whenever one or more other creatures you control enter, if this creature is "
              "suspected, you may suspect one of the other creatures. If you do, this creature "
              "is no longer suspected.")
    result = parse_oracle(Card(id="fs", name="Frantic Scapegoat", type_line="Creature",
                               is_creature=True, oracle_text=oracle))
    assert result.modeled
    effect = result.specs[0].effects[0]
    assert effect.params["selection_kind"] == "other_creature_you_control"

    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    source = GameObject(Card(id="source", name="Source", type_line="Creature", is_creature=True),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    candidate = GameObject(Card(id="candidate", name="Candidate", type_line="Creature", is_creature=True),
                           owner_id="p1", zone=Zone.BATTLEFIELD)
    for obj in (source, candidate):
        obj.controller_id = "p1"
        engine.state.add_to_battlefield(obj)
    engine.rules.suspect(source)
    # The intervening source-state condition is asserted by the parsed spec
    # above; exercise the asynchronous choice/tail machinery independently.
    executable = EffectSpec(effect.type, dict(effect.params))
    _apply_effects_partitioned(build_effects([executable], source), engine.rules.context,
                               None, None, source=source)
    assert engine.state.pending_choice["kind"] == "choose_objects"
    engine.rules._resume_choose_objects(engine.state.pending_choice, candidate.instance_id)
    assert candidate.is_suspected is True
    assert source.is_suspected is False
