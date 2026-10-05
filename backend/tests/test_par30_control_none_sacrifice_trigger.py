"""PAR-30-adjacent — "When you control no <basic land type>, sacrifice ~."
(RULE 603.8 state trigger — Bog Serpent / Sea Serpent / Dandân cycle).

Modeled as a `LEAVES_BATTLEFIELD` trigger gated on `effect_binder`'s new
`controls_none_of_type` predicate (a live battlefield scan for the
controller's own permanents of that printed land subtype).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def _seg(text):
    return segment_line(text, allow_spell_effect=False, provenance=ParserProvenance())


# --- parse ---------------------------------------------------------------------


def test_control_none_swamps_parses_to_a_leaves_battlefield_trigger():
    seg = _seg("when you control no swamps, sacrifice ~")
    assert seg.claimed and seg.spec is not None
    assert seg.spec.ability_kind == "triggered"
    assert seg.spec.trigger["event"] == "LEAVES_BATTLEFIELD"
    assert seg.spec.trigger["controls_none_of_type"] == "swamp"
    assert [e.type for e in seg.spec.effects] == ["sacrifice_self"]


def test_islands_plural_normalises_to_singular():
    seg = _seg("when you control no islands, sacrifice this creature")
    assert seg.spec.trigger["controls_none_of_type"] == "island"


def test_plains_stays_plains():
    seg = _seg("when you control no plains, sacrifice ~")
    assert seg.spec.trigger["controls_none_of_type"] == "plains"


def test_non_basic_type_is_not_claimed_here():
    # "control no creatures" is a different (much broader) shape.
    seg = _seg("when you control no creatures, sacrifice ~")
    assert not seg.claimed or seg.spec is None


def test_bog_serpent_modeled():
    c = Card(id="bs", name="Bog Serpent", type_line="Creature — Serpent",
             is_creature=True, power=3, toughness=3, oracle_text=(
                 "Bog Serpent can't attack unless defending player controls a "
                 "Swamp.\nWhen you control no Swamps, sacrifice Bog Serpent."))
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _bf(state, eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def test_serpent_is_sacrificed_when_its_last_swamp_leaves():
    eng, state = _engine()
    swamp = _bf(state, eng, Card(id="sw", name="Swamp", type_line="Basic Land — Swamp"))
    serpent = _bf(state, eng, Card(
        id="bs", name="Bog Serpent", type_line="Creature — Serpent",
        is_creature=True, power=3, toughness=3,
        oracle_text="When you control no Swamps, sacrifice Bog Serpent.",
    ))
    assert serpent in state.battlefield

    eng.rules.destroy(swamp)
    eng.rules.check_state_based_actions()
    # the state trigger fired and went on the stack — drain it
    eng.resolve_until_stable()

    assert serpent not in state.battlefield
    assert serpent in state.player_by_id("p1").graveyard


def test_serpent_survives_while_a_swamp_remains():
    eng, state = _engine()
    swamp_a = _bf(state, eng, Card(id="sa", name="Swamp", type_line="Basic Land — Swamp"))
    _bf(state, eng, Card(id="sb", name="Swamp", type_line="Basic Land — Swamp"))
    serpent = _bf(state, eng, Card(
        id="bs", name="Bog Serpent", type_line="Creature — Serpent",
        is_creature=True, power=3, toughness=3,
        oracle_text="When you control no Swamps, sacrifice Bog Serpent.",
    ))

    eng.rules.destroy(swamp_a)
    eng.resolve_until_stable()

    assert serpent in state.battlefield  # one Swamp still out
