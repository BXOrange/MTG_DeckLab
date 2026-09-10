"""MEC-82 — conditional magnitude replacement (RULE 614).

"Target creature gets -2/-2 until end of turn. If this spell was kicked,
that creature gets -6/-6 until end of turn instead." — the trailing "instead"
sentence *replaces* the pump's own printed P/T magnitude; it is not a second
additive effect and is **not** routed through `if_else`. `PumpEffect` gains
`power_if_kicked`/`toughness_if_kicked` (+ the Bargain siblings), the
`DealDamageEffect.amount_if_kicked` shape for the pump axis, resolved off the
source's `kicker_count`/`bargained` flags via the shared
`_resolve_amount_override` chain.

Reference: game/effects/core.py (`PumpEffect._kicked_magnitude` / `_pump_one`),
parser/oracle/segmenter.py (`_KICKED_MAGNITUDE_OVERRIDE_RE`).
"""

from __future__ import annotations

from mtg_analyzer.game.effects.core import GameContext, PumpEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, name="Bear", power=4, toughness=4, controller="p2"):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=power, toughness=toughness),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = controller
    state.add_to_battlefield(o)
    return o


def _spell_source(state, name="Final Flourish"):
    src = GameObject(Card(id=name[:6], name=name, type_line="Sorcery"),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"
    return src


# --- parser -----------------------------------------------------------


def test_pump_kicked_override_stamps_the_before_pump():
    assert parse_effect_body(
        "target creature gets -2/-2 until end of turn. "
        "if this spell was kicked, that creature gets -6/-6 until end of turn instead"
    ) == [
        EffectSpec("pump", {
            "power": -2, "toughness": -2, "target_kind": "creature",
            "power_if_kicked": -6, "toughness_if_kicked": -6,
        }),
    ]


def test_bargain_sibling():
    assert parse_effect_body(
        "target creature gets -3/-3 until end of turn. "
        "if this spell was bargained, that creature gets -5/-5 until end of turn instead"
    ) == [
        EffectSpec("pump", {
            "power": -3, "toughness": -3, "target_kind": "creature",
            "power_if_bargained": -5, "toughness_if_bargained": -5,
        }),
    ]


def test_keyword_grant_rider_is_not_claimed_as_an_override():
    # Colossal Growth: "instead that creature gets +4/+4 and gains trample and
    # haste" — magnitude *plus* a keyword grant, more than a RULE 614 override.
    assert parse_effect_body(
        "target creature gets +3/+3 until end of turn. if this spell was kicked, "
        "instead that creature gets +4/+4 and gains trample and haste until end of turn"
    ) is None


def test_no_pump_to_override_fails_closed():
    assert parse_effect_body(
        "draw a card. if this spell was kicked, that creature gets -6/-6 "
        "until end of turn instead"
    ) is None


def test_real_cards_modeled():
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Final Flourish", "Vayne's Treachery", "Explosive Growth",
                 "Might of Murasa", "Candy Grapple", "Vicious Offering",
                 "Eject the Warp Core", "Gift of Growth", "Dauntless Unity"):
        c = db.get_card(name)
        assert c is not None, name
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute ----------------------------------------------------------


def test_kicked_spell_applies_the_override_magnitude():
    eng = _engine()
    src = _spell_source(eng.state)
    src.kicker_count = 1
    victim = _creature(eng.state, toughness=5)
    eng.recompute_continuous_effects()

    PumpEffect(power=-2, toughness=-2, power_if_kicked=-6, toughness_if_kicked=-6,
               target_kind="creature", source=src).apply(
        GameContext(eng.state, eng.rules), [victim]
    )
    eng.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (4 - 6, 5 - 6)  # -6/-6, not -2/-2


def test_unkicked_spell_applies_the_printed_magnitude():
    eng = _engine()
    src = _spell_source(eng.state)
    src.kicker_count = 0
    victim = _creature(eng.state, toughness=5)
    eng.recompute_continuous_effects()

    PumpEffect(power=-2, toughness=-2, power_if_kicked=-6, toughness_if_kicked=-6,
               target_kind="creature", source=src).apply(
        GameContext(eng.state, eng.rules), [victim]
    )
    eng.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (4 - 2, 5 - 2)


def test_bargained_flag_drives_the_bargain_override():
    eng = _engine()
    src = _spell_source(eng.state, "Candy Grapple")
    src.bargained = True
    victim = _creature(eng.state, toughness=6)
    eng.recompute_continuous_effects()

    PumpEffect(power=-3, toughness=-3, power_if_bargained=-5, toughness_if_bargained=-5,
               target_kind="creature", source=src).apply(
        GameContext(eng.state, eng.rules), [victim]
    )
    eng.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (4 - 5, 6 - 5)


def test_kicked_end_to_end_kills_via_sba():
    eng = _engine()
    src = _spell_source(eng.state)
    src.kicker_count = 1
    victim = _creature(eng.state, power=3, toughness=4)
    eng.recompute_continuous_effects()

    PumpEffect(power=-2, toughness=-2, power_if_kicked=-6, toughness_if_kicked=-6,
               target_kind="creature", source=src).apply(
        GameContext(eng.state, eng.rules), [victim]
    )
    eng.rules.check_state_based_actions()
    # -6 toughness on a 4-toughness creature → 0 or less → dies (RULE 704.5f)
    assert victim not in eng.state.battlefield
