"""PAR-43 — "~ gets +P/+T for each `<X>`" general standing self-anthem.

`static_handlers._SELF_ANTHEM_FOR_EACH_RE` + `_SELF_ANTHEM_FOR_EACH_
SELECTORS` map a whitelist of "for each …" quantities that already have a
`continuous.count_selector` onto a self `anthem` with `power_count`/
`toughness_count` (the same shape the PAR-30 graveyard-subtype row emits).
Any quantity with no wired selector fails closed. Real cards: Akiri,
Line-Slinger ("+1/+0 for each artifact you control"), Goblin Gaveleer /
the Nim cycle ("+N/+0 for each Equipment attached to it"), Earth Servant
("+0/+1 for each Mountain you control").
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _perm(state, name, type_line, pid="p1", **flags):
    o = GameObject(Card(id=name[:8], name=name, type_line=type_line, **flags),
                   owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


# --- parse -----------------------------------------------------------------


def test_for_each_artifact_you_control_parses():
    assert static_effect_specs("~ gets +1/+0 for each artifact you control") == [
        EffectSpec("anthem", {
            "affects": "self", "power": 1, "toughness": 0,
            "power_count": "artifacts_you_control",
            "toughness_count": "artifacts_you_control",
        })
    ]


def test_for_each_equipment_attached_to_it_parses():
    assert static_effect_specs("~ gets +2/+0 for each equipment attached to it")[0].params[
        "power_count"
    ] == "equipment_attached_to_self"


def test_for_each_basic_land_type_you_control_parses():
    assert static_effect_specs("~ gets +0/+1 for each mountain you control")[0].params[
        "toughness_count"
    ] == "lands_you_control_of_type_mountain"


def test_unwired_quantity_fails_closed():
    # "Equipment you control" (board-wide) has no count_selector — must not
    # be silently claimed as the "attached to it" one.
    assert static_effect_specs("~ gets +1/+1 for each equipment you control") is None
    assert static_effect_specs("~ gets +1/+1 for each experience counter you have") is None
    assert static_effect_specs("~ gets +1/+1 for each opponent you have") is None


def test_real_cards_modeled():
    for name, text in [
        ("Akiri, Line-Slinger", "Akiri, Line-Slinger gets +1/+0 for each artifact you control."),
        ("Goblin Gaveleer", "Goblin Gaveleer gets +2/+0 for each Equipment attached to it."),
        ("Earth Servant", "Earth Servant gets +0/+1 for each Mountain you control."),
    ]:
        c = Card(id=name[:4], name=name, type_line="Creature", is_creature=True,
                 power=1, toughness=1, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_anthem_scales_with_artifact_count_live():
    eng, state = _engine()
    akiri = _perm(state, "Akiri", "Creature — Dwarf", is_creature=True, power=0, toughness=3,
                  oracle_text="Akiri gets +1/+0 for each artifact you control.")
    bind_from_catalogue(akiri)
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (0, 3)  # Akiri herself is not an artifact

    _perm(state, "Sol Ring", "Artifact")
    _perm(state, "Signet", "Artifact")
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (2, 3)

    # an opponent's artifact doesn't count
    _perm(state, "Their Bauble", "Artifact", pid="p2")
    eng.recompute_continuous_effects()
    assert akiri.power == 2

    state.battlefield[:] = [o for o in state.battlefield if not o.card.is_artifact]
    eng.recompute_continuous_effects()
    assert (akiri.power, akiri.toughness) == (0, 3)
