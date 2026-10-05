"""'Spells your opponents cast that target ~ cost {N} more to cast.'
(RULE 601.2f — Icefall Regent / Boreal Elemental / Charix, the Raging Isle
/ Elderwood Scion / Pursued Whale).

`cost_reduction` gained a `targets_source` param; `continuous.
cost_reduction_for` takes the caster's already-chosen targets (RULE 601.2c
precedes 601.2f) and applies the tax only when one of them is this static's
own source. `_adjust_cost` threads `targets` through to it.
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
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse -----------------------------------------------------------------


def test_that_target_self_tax_parses():
    assert static_effect_specs(
        "spells your opponents cast that target ~ cost {2} more to cast"
    ) == [
        EffectSpec("cost_reduction", {
            "affects": "opponents_spells", "generic": 2, "increase": True,
            "targets_source": True,
        })
    ]


def test_plain_opponents_tax_still_has_no_targets_source():
    assert static_effect_specs("spells your opponents cast cost {1} more to cast") == [
        EffectSpec("cost_reduction", {
            "affects": "opponents_spells", "generic": 1, "increase": True,
        })
    ]


def test_real_card_modeled():
    c = Card(
        id="ir", name="Icefall Regent", type_line="Creature — Dragon",
        mana_cost_string="{3}{U}{U}", is_creature=True, power=4, toughness=3,
        oracle_text=("Flying\nWard {2}\nWhen Icefall Regent enters, tap target "
                     "creature an opponent controls. That creature doesn't untap "
                     "during its controller's untap step for as long as you "
                     "control Icefall Regent.\nSpells your opponents cast that "
                     "target Icefall Regent cost {2} more to cast."),
    )
    assert parse_oracle(c).coverage != UNMODELED, parse_oracle(c).unclaimed


# --- execute -------------------------------------------------------------------


def _regent(state, controller="p1"):
    o = GameObject(
        Card(id="ir", name="Icefall Regent", type_line="Creature — Dragon",
             is_creature=True, power=4, toughness=3,
             oracle_text="Spells your opponents cast that target Icefall Regent "
                         "cost {2} more to cast."),
        owner_id=controller, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = controller
    bind_from_catalogue(o)
    state.add_to_battlefield(o)
    return o


def _opp_bolt(state, caster="p2"):
    card = Card(id="blt", name="Bolt", type_line="Instant", is_instant=True,
                mana_cost_string="{R}", oracle_text="Bolt deals 3 damage to any target.")
    o = GameObject(card, owner_id=caster, zone=Zone.HAND)
    o.controller_id = caster
    bind_from_catalogue(o)
    state.player_by_id(caster).hand.append(o)
    return o


def test_tax_applies_only_when_the_opponent_spell_targets_the_regent():
    eng, state = _engine()
    regent = _regent(state, controller="p1")
    other = GameObject(Card(id="bystander", name="Bystander", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    state.add_to_battlefield(other)
    bolt = _opp_bolt(state, caster="p2")
    eng.recompute_continuous_effects()

    p2 = state.player_by_id("p2")
    no_target = eng.effective_cast_cost(p2, bolt)                 # {R} = mv 1
    hits_regent = eng.effective_cast_cost(p2, bolt, targets=[regent])
    hits_other = eng.effective_cast_cost(p2, bolt, targets=[other])

    assert no_target.converted_mana_cost == 1
    assert hits_regent.converted_mana_cost == 3   # {2}{R} — taxed
    assert hits_other.converted_mana_cost == 1    # not targeting the Regent


def test_the_controllers_own_spell_is_not_taxed():
    eng, state = _engine()
    regent = _regent(state, controller="p1")
    own_bolt = _opp_bolt(state, caster="p1")  # p1 controls the Regent
    eng.recompute_continuous_effects()

    cost = eng.effective_cast_cost(state.player_by_id("p1"), own_bolt, targets=[regent])
    assert cost.converted_mana_cost == 1  # affects="opponents_spells" spares the controller
