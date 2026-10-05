"""PAR-81: "Switch target creature's power and toughness until end of turn"
— the resolving one-shot form (Twisted Image-shaped).

`"pt_switch"` already existed as a `StaticAbility` layer 7e type (RULE
613.4d/701.28) for a granted/printed standing ability — this ticket wires
the identical swap into a *resolving* spell/ability effect body instead.
New primitive: `SwitchPowerToughnessEffect` (`game/effects/counters_
tokens.py`) stamps `GameObject.temp_pt_switch`, read by `continuous.
recompute`'s own layer 7e pass alongside any static `pt_switch` ability on
the same object, and swept at cleanup the same way `temp_power`/
`temp_unblockable` already are.

Reference: docs/implementation-state/Done_Backend.md's "Oracle-Text Parser
Front-End" PAR-81 entry (once closed).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _card(name, type_line="Creature — Bear", cost="{1}{U}", cmc=2, **kw):
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
# Parse-level: all four shapes
# ---------------------------------------------------------------------------


def test_target_form_parses():
    assert parse_effect_body(
        "switch target creature's power and toughness until end of turn."
    ) == [EffectSpec("switch_power_toughness", {"target_kind": "creature"})]


def test_self_form_with_tilde_parses():
    assert parse_effect_body(
        "switch ~'s power and toughness until end of turn."
    ) == [EffectSpec("switch_power_toughness", {})]


def test_self_form_with_its_parses():
    assert parse_effect_body(
        "switch its power and toughness until end of turn."
    ) == [EffectSpec("switch_power_toughness", {})]


def test_mass_form_parses():
    assert parse_effect_body(
        "switch each creature's power and toughness until end of turn."
    ) == [EffectSpec("switch_power_toughness", {"selector": "all_creatures"})]


def test_multi_target_up_to_n_parses():
    assert parse_effect_body(
        "switch the power and toughness of each of up to 2 target creatures "
        "until end of turn."
    ) == [EffectSpec("switch_power_toughness", {
        "target_kind": "creature", "count": 2, "optional": True,
    })]


def test_multi_target_any_number_parses():
    assert parse_effect_body(
        "switch the power and toughness of each of any number of target "
        "creatures until end of turn."
    ) == [EffectSpec("switch_power_toughness", {
        "target_kind": "creature", "count": 10, "optional": True,
    })]


# ---------------------------------------------------------------------------
# End-to-end: real cards
# ---------------------------------------------------------------------------


def test_sample_real_cards_now_modeled():
    for entry in [
        ("About Face", "Instant",
         "Switch target creature's power and toughness until end of turn."),
        ("Aeromoeba", "Creature — Homunculus",
         "Flying\nDiscard a card: Switch ~'s power and toughness until end "
         "of turn."),
        ("Valakut Fireboar", "Creature — Boar",
         "Whenever ~ attacks, switch its power and toughness until end of "
         "turn."),
        ("Mannichi, the Fevered Dream", "Legendary Creature — Spirit",
         "{1}{R}: Switch each creature's power and toughness until end of "
         "turn."),
        ("Invert // Invent", "Instant",
         "Switch the power and toughness of each of up to 2 target "
         "creatures until end of turn."),
    ]:
        name, type_line, text = entry
        card = _card(name, type_line=type_line, oracle_text=text, keywords=[])
        result = parse_oracle(card)
        assert result.modeled, f"{name} stayed UNMODELED: {result.unclaimed}"


# ---------------------------------------------------------------------------
# Execute: the temp_pt_switch flag actually swaps P/T and reverts at cleanup
# ---------------------------------------------------------------------------


def test_target_switch_executes_and_reverts_at_cleanup():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    spell = GameObject(
        _card("About Face", type_line="Instant", oracle_text=(
            "Switch target creature's power and toughness until end of turn."
        )),
        owner_id="p1", zone=Zone.HAND,
    )
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    target = _bf(state, _card("Target", power=1, toughness=5), controller="p2")

    p1.mana_pool.add_many({"U": 2})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (5, 1)

    eng._step_cleanup()
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (1, 5)


def test_mass_switch_affects_every_creature_independently():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    mannichi = _bf(state, _card(
        "Mannichi, the Fevered Dream", power=3, toughness=3,
        oracle_text="{1}{R}: Switch each creature's power and toughness until end of turn.",
    ))
    t1 = _bf(state, _card("Bear1", power=1, toughness=4), controller="p2")
    t2 = _bf(state, _card("Bear2", power=2, toughness=6), controller="p1")

    p1.mana_pool.add_many({"R": 2})
    eng.activate_ability(p1, mannichi, ability_index=0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    assert (mannichi.power, mannichi.toughness) == (3, 3)
    assert (t1.power, t1.toughness) == (4, 1)
    assert (t2.power, t2.toughness) == (6, 2)


def test_double_switch_cancels_out():
    # RULE 613 timestamp order: two independent switches on the same
    # object correctly cancel each other back to the original values.
    eng = _engine()
    state = eng.state
    p1, p2 = state.players
    target = _bf(state, _card("Target", power=1, toughness=5), controller="p2")

    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.counters_tokens import SwitchPowerToughnessEffect

    effect = SwitchPowerToughnessEffect(target_kind="creature")
    effect.source = target
    context = GameContext(state, eng.rules)
    effect.apply(context, [target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (5, 1)

    effect2 = SwitchPowerToughnessEffect(target_kind="creature")
    effect2.source = target
    effect2.apply(context, [target])
    eng.recompute_continuous_effects()
    assert (target.power, target.toughness) == (1, 5)
