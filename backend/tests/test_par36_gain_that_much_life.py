"""PAR-36 — "Whenever ~ deals damage, you gain that much life." trigger body.

`_DAMAGE_TRIGGER_RE` already parsed the condition (a bare "deals damage",
any instance — combat or not); only the "you gain that much life" body was
blocked. New `gain_life_from_trigger_amount` handler → `EffectSpec(
"gain_life", {"amount_from_trigger_event": "amount"})`, and
`GainLifeEffect` gained the matching `amount_from_trigger_event` param (the
gain sibling of `LoseLifeEffect`/`DealDamageEffect`'s same field), reading
the firing DAMAGE event's `amount`.

Real cards: El-Hajjâj / Exalted Angel / Horned Cheetah / Warrior Angel /
Wall of Hope (creatures), Spirit Link / Vampiric Link / Spirit Loop /
Noble Purpose (the Aura/enchantment grant forms).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, name, text, controller="p1", power=2, toughness=2):
    obj = GameObject(
        Card(id=name[:8], name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness, oracle_text=text),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# --- parse -----------------------------------------------------------------


def test_gain_that_much_life_body_parses():
    assert parse_effect_body("you gain that much life") == [
        EffectSpec("gain_life", {"amount_from_trigger_event": "amount"})
    ]


def test_plain_gain_n_life_still_literal():
    assert parse_effect_body("you gain 3 life") == [
        EffectSpec("gain_life", {"amount": 3})
    ]


def test_real_cards_modeled():
    for name, text in [
        ("El-Hajjâj", "Whenever El-Hajjâj deals damage, you gain that much life."),
        ("Exalted Angel",
         "Flying\nWhenever Exalted Angel deals damage, you gain that much life."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Creature — Angel", is_creature=True,
                 power=4, toughness=5, oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def test_gains_life_equal_to_combat_damage_dealt():
    eng = _engine()
    state = eng.state
    angel = _bf(state, "Exalted Angel",
                "Whenever ~ deals damage, you gain that much life.", power=4, toughness=5)

    eng.rules.deal_damage(state.player_by_id("p2"), 4, source=angel, combat=True)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.player_by_id("p1").life == 24  # +4 = the damage just dealt


def test_also_fires_on_noncombat_damage():
    eng = _engine()
    state = eng.state
    # a bare "deals damage" clause is not combat-restricted
    pinger = _bf(state, "Rod of Pinging",
                 "Whenever ~ deals damage, you gain that much life.")
    victim = _bf(state, "Their Bear", "", controller="p2", toughness=5)

    eng.rules.deal_damage(victim, 3, source=pinger, combat=False)
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.player_by_id("p1").life == 23


def test_does_not_fire_for_a_different_sources_damage():
    eng = _engine()
    state = eng.state
    angel = _bf(state, "Exalted Angel",
                "Whenever ~ deals damage, you gain that much life.", power=4, toughness=5)
    other = _bf(state, "Random Bear", "")

    eng.rules.deal_damage(state.player_by_id("p2"), 2, source=other, combat=True)
    assert eng.rules.put_triggers_on_stack() == 0
    assert state.player_by_id("p1").life == 20
