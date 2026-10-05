"""MEC-78 — Heal (RULE 701.69a).

`RulesEngine.heal(obj)` removes all marked damage from a permanent and
returns how much it removed. `effects.HealEffect` (registered `heal`) is
the resolve-time "heal all damage from `<permanent>`" clause, with an
optional `group_selector_objects` `selector`. `_heal_others_on_damage_`
`replacement` (`heal_others_on_damage`) is Wolverine, Fierce Fighter's
replacement: a hit lands unchanged but every point already marked on the
source is healed first, so its effective toughness for lethality is
measured against the latest hit alone.

Reference: game/rules/damage_death_mixin.py (`heal`), game/effects/core.py
(`HealEffect`, `_heal_others_on_damage_replacement`), parser/oracle/
catalogue/{handlers,replacements}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import isa
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, HealEffect, ReplacementRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(state, name="Bear", power=2, toughness=2, controller="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=power, toughness=toughness),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


# --- primitive -----------------------------------------------------------


def test_heal_removes_all_marked_damage_and_reports_amount():
    eng = _engine()
    bear = _creature(eng.state, toughness=5)
    bear.damage_marked = 3
    assert eng.rules.heal(bear) == 3
    assert bear.damage_marked == 0
    assert eng.rules.heal(bear) == 0  # nothing to remove now


def test_heal_effect_self_target_and_group():
    eng = _engine()
    a = _creature(eng.state, "A", toughness=5)
    b = _creature(eng.state, "B", toughness=5)
    opp = _creature(eng.state, "Opp", toughness=5, controller="p2")
    for o in (a, b, opp):
        o.damage_marked = 2

    HealEffect(source=a).apply(eng.rules.context)          # self
    assert (a.damage_marked, b.damage_marked) == (0, 2)

    HealEffect(source=a).apply(eng.rules.context, targets=[b])  # targeted
    assert b.damage_marked == 0

    b.damage_marked = 2
    HealEffect(selector="creatures_you_control", source=a).apply(eng.rules.context)
    assert (a.damage_marked, b.damage_marked, opp.damage_marked) == (0, 0, 2)


# --- Wolverine replacement -------------------------------------------


def _wolverine_repl(source):
    eff = ReplacementRegistry.create("heal_others_on_damage", {})
    eff.source = source
    source.replacement_effects.append(eff)
    return eff


def test_heal_on_damage_replacement_never_accumulates():
    eng = _engine()
    w = _creature(eng.state, "Wolv", power=3, toughness=5)
    _wolverine_repl(w)

    eng.rules.deal_damage(w, 2)
    assert w.damage_marked == 2
    eng.rules.deal_damage(w, 3)          # heals the 2 first
    assert w.damage_marked == 3
    eng.rules.deal_damage(w, 4)
    assert w.damage_marked == 4          # 2+3+4 would be lethal; it isn't
    eng.rules.check_state_based_actions()
    assert w in eng.state.battlefield

    eng.rules.deal_damage(w, 6)          # a single hit >= toughness still kills
    eng.rules.check_state_based_actions()
    assert w not in eng.state.battlefield


def test_heal_on_damage_replacement_only_heals_its_own_source():
    eng = _engine()
    w = _creature(eng.state, "Wolv", toughness=5)
    other = _creature(eng.state, "Other", toughness=5)
    _wolverine_repl(w)
    other.damage_marked = 2

    eng.rules.deal_damage(w, 1)
    assert other.damage_marked == 2  # untouched


# --- parser --------------------------------------------------------


def test_heal_clause_parses():
    assert match_clause("heal all damage from ~") == [EffectSpec("heal", {})]
    assert match_clause("heal all damage from each creature you control") == [
        EffectSpec("heal", {"selector": "creatures_you_control"})
    ]
    assert match_clause("heal 2") is None  # RULE 701.69a is only ever "all"


def test_wolverine_is_healed_clause_is_a_replacement():
    # a standing replacement clause — reached through the segmenter's
    # permanent-static fallback, not `parse_effect_body`.
    from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs

    specs = replacement_clause_specs(
        "if damage would be dealt to ~, instead that damage is dealt, "
        "but all other damage already dealt to him is healed"
    )
    assert specs == [EffectSpec("heal_others_on_damage", {})]


def test_heal_effect_registered_and_classified():
    assert EffectRegistry.is_registered("heal")
    assert ReplacementRegistry.is_registered("heal_others_on_damage")
    assert isa.EFFECT_TYPES["heal"].instruction == "heal"


def test_wolverine_fierce_fighter_fully_modeled():
    card = _db().get_card("Wolverine, Fierce Fighter")
    assert card is not None
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    kinds = {s.ability_kind for s in result.specs}
    assert "triggered" in kinds and "replacement" in kinds
    assert any(
        e.type == "heal_others_on_damage" for s in result.specs for e in s.effects
    )


def test_personified_pronoun_fight_clause_parses():
    # the `_FIGHT_PRONOUN_RE` widening — "he fights …" only resolves in a
    # self-subject context (a trigger body of the source), so drive it
    # through a real ETB trigger rather than a bare clause.
    card = Card(
        id="Pf", name="Personified", type_line="Creature — Hero",
        is_creature=True, power=2, toughness=2,
        oracle_text="When Personified enters, he fights up to one other target creature.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    trig = next(s for s in result.specs if s.ability_kind == "triggered")
    assert [e.type for e in trig.effects] == ["fight"]
