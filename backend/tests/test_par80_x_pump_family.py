"""PAR-80: X-spell "target creature gets +X/+`<N>` until end of turn."

The variable-power/fixed-toughness pump family (an X spell/ability whose
caster-chosen X sets one axis of the buff, or a "where X is `<board-state
count>`" tail instead). No new engine primitive: `RulesEngine._substitute_x`
already walks any bound effect's own `power`/`toughness` for the literal
`"x"`/`"-x"` sentinel (Bring to Light/Toxic Deluge's own precedent), and
`PumpEffect.amount_from_count_selector`/`amount_from_count_selector_axis`
already read a live board count on one or both axes — this is pure parser
recognition of two shapes (`_pump_target_x`, `_pump_target_x_selector`)
plus a closed phrase table for the count-selector referents that already
have a `continuous.count_selector` name.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-80 entry (once closed).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Instant", cost="{1}{R}", cmc=2, **kw):
    lowered = type_line.lower()
    for flag in ("instant", "sorcery", "land", "creature"):
        kw.setdefault(f"is_{flag}", flag in lowered)
    if kw.get("is_creature"):
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost,
                converted_mana_cost=cmc, **kw)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


# ---------------------------------------------------------------------------
# Parse-level: base X-spell (no "where x is" tail)
# ---------------------------------------------------------------------------


def test_bare_x_power_only_parses():
    assert parse_effect_body("target creature gets +x/+0 until end of turn.") == [
        EffectSpec("pump", {"power": "x", "toughness": 0, "target_kind": "creature"}),
    ]


def test_bare_x_both_axes_parses():
    assert parse_effect_body("target creature gets +x/+x until end of turn.") == [
        EffectSpec("pump", {"power": "x", "toughness": "x", "target_kind": "creature"}),
    ]


def test_bare_x_with_keyword_tail_parses():
    assert parse_effect_body(
        "target creature gets +x/+0 and gains trample until end of turn."
    ) == [
        EffectSpec("pump", {
            "power": "x", "toughness": 0, "keywords": ["trample"], "target_kind": "creature",
        }),
    ]


# ---------------------------------------------------------------------------
# Parse-level: "where x is <count-selector phrase>" tail
# ---------------------------------------------------------------------------


def test_selector_phrase_power_axis_only_parses():
    assert parse_effect_body(
        "target creature gets +x/+0 until end of turn, where x is the "
        "number of creatures you control."
    ) == [
        EffectSpec("pump", {
            "amount_from_count_selector": "creatures_you_control",
            "amount_from_count_selector_axis": "power",
            "target_kind": "creature",
        }),
    ]


def test_selector_phrase_both_axes_parses():
    assert parse_effect_body(
        "target creature gets +x/+x until end of turn, where x is the "
        "number of creature cards in your graveyard."
    ) == [
        EffectSpec("pump", {
            "amount_from_count_selector": "creature_cards_in_your_graveyard",
            "target_kind": "creature",
        }),
    ]


def test_selector_phrase_land_type_parses():
    assert parse_effect_body(
        "target creature gets +x/+0 until end of turn, where x is the "
        "number of mountains you control."
    ) == [
        EffectSpec("pump", {
            "amount_from_count_selector": "lands_you_control_of_type_mountain",
            "amount_from_count_selector_axis": "power",
            "target_kind": "creature",
        }),
    ]


def test_selector_phrase_life_gained_two_clause_body_parses():
    assert parse_effect_body(
        "you gain 2 life. target creature gets +x/+x until end of turn, "
        "where x is the amount of life you gained this turn."
    ) == [
        EffectSpec("gain_life", {"amount": 2}),
        EffectSpec("pump", {
            "amount_from_count_selector": "life_gained_this_turn",
            "target_kind": "creature",
        }),
    ]


def test_unrecognized_selector_phrase_stays_unclaimed():
    # "the greatest mana value among permanents you control" isn't in the
    # closed phrase table — must fail closed, not guess a selector.
    assert parse_effect_body(
        "target creature gets +x/+x until end of turn, where x is the "
        "greatest mana value among permanents you control."
    ) is None


# ---------------------------------------------------------------------------
# End-to-end: real cards
# ---------------------------------------------------------------------------


def test_sample_real_cards_now_modeled():
    for entry in [
        ("Bloodcurdling Scream", "Instant",
         "Target creature gets +X/+0 until end of turn."),
        ("Enrage", "Sorcery", "Target creature gets +X/+0 until end of turn."),
        ("Downhill Charge", "Sorcery",
         "Target creature gets +X/+0 until end of turn, where X is the "
         "number of Mountains you control."),
        ("Ghoul's Feast", "Instant",
         "Target creature gets +X/+0 until end of turn, where X is the "
         "number of creature cards in your graveyard."),
        ("Fortifying Draught", "Instant",
         "You gain 2 life. Target creature gets +X/+X until end of turn, "
         "where X is the amount of life you gained this turn."),
        ("Test Kessig Wolf Run", "Land",
         "{T}: Add {C}.\n{X}{R}{G}, {T}: Target creature gets +X/+0 and "
         "gains trample until end of turn."),
    ]:
        name, type_line, text = entry
        card = _card(name, type_line=type_line, oracle_text=text, keywords=[])
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# Execute: RulesEngine._substitute_x actually resolves the "x" sentinel
# ---------------------------------------------------------------------------


def test_x_spell_pump_executes_with_the_announced_x():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    spell = GameObject(
        _card("Bloodcurdling Scream", oracle_text="Target creature gets +X/+0 until end of turn."),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    target = _bf(state, _card("Target", type_line="Creature — Bear", is_creature=True, power=2, toughness=2))

    p1.mana_pool.add_many({"R": 3})
    eng.cast_spell(p1, spell, x=3, targets=[target])
    eng.resolve_until_stable()

    eng.recompute_continuous_effects()
    assert target.power == 5  # 2 base + 3 from X
    assert target.toughness == 2  # unchanged


def test_x_spell_pump_selector_executes_off_board_state():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    spell = GameObject(
        _card(
            "Downhill Charge",
            oracle_text=(
                "Target creature gets +X/+0 until end of turn, where X is "
                "the number of Mountains you control."
            ),
        ),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    target = _bf(state, _card("Target", type_line="Creature — Bear", is_creature=True, power=2, toughness=2))
    for i in range(2):
        _bf(state, _card(f"Mountain {i}", type_line="Basic Land — Mountain", is_land=True))

    p1.mana_pool.add_many({"R": 1})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()

    eng.recompute_continuous_effects()
    assert target.power == 4  # 2 base + 2 mountains
    assert target.toughness == 2
