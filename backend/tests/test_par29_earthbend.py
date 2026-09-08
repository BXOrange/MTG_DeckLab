"""PAR-29 — RULE 701.66 Earthbend (Avatar: The Last Airbender).

"Earthbend N" = a target land you control becomes a 0/0 creature with haste
that's still a land, then gets N +1/+1 counters. `RulesEngine.earthbend`
parks two `rest_of_game` floating statics (a layer-4 `type_change` to a 0/0
Creature, a layer-6 `grant_keyword` haste) scoped to that one land, then
`add_counters`. `effects.EarthbendEffect` targets `land_you_control` (or a
`previous_subject` land).

**Documented simplification:** the "When it dies or is exiled, return it to
the battlefield tapped." reminder-text clause is not modeled.

Reference: game/rules/mana_counters_mixin.py (`earthbend`), game/effects/core.py
(`EarthbendEffect`), parser/oracle/catalogue/handlers.py (`_earthbend`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse -----------------------------------------------------------------


def test_earthbend_clause_parses():
    assert match_clause("earthbend 4") == [EffectSpec("earthbend", {"amount": 4})]
    # "that creature's power" now claimed as a dying-subject read (PAR-30
    # v143, Beifong's Bounty Hunters); an un-modeled dynamic form still isn't
    assert match_clause("earthbend x, where x is that creature's power") == [
        EffectSpec("earthbend", {"amount_from_trigger_event": "power"})
    ]
    assert match_clause("earthbend x, where x is the highest mana value among creatures you control") is None


def test_real_earthbend_cards_modeled():
    for name, type_line, kw, text in [
        ("Earthbending Lesson", "Sorcery", {},
         "Earthbend 4. (Target land you control becomes a 0/0 creature with "
         "haste that's still a land. Put four +1/+1 counters on it. When it "
         "dies or is exiled, return it to the battlefield tapped.)"),
        ("Cracked Earth Technique", "Sorcery", {},
         "Earthbend 3, then earthbend 3. You gain 3 life."),
    ]:
        c = Card(id=name[:3], name=name, type_line=type_line,
                 is_sorcery=True, mana_cost_string="{2}{G}", oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _land(state, pid, name="Forest"):
    c = Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_earthbend_animates_land_and_adds_counters():
    eng, state = _engine()
    land = _land(state, "p1")
    assert land.is_land and not land.is_creature

    eng.rules.earthbend(land, 4, source=land)
    eng.recompute_continuous_effects()

    assert land.is_land          # still a land
    assert land.is_creature      # now a creature
    assert land.counters.get("+1/+1") == 4
    assert land.power == 4 and land.toughness == 4   # 0/0 base + 4 counters
    assert "haste" in {k.lower() for k in (land.granted_keywords or set())}


def test_earthbend_persists_across_turns_rest_of_game():
    eng, state = _engine()
    land = _land(state, "p1")
    eng.rules.earthbend(land, 2, source=land)
    eng.recompute_continuous_effects()
    assert land.is_creature and land.power == 2

    # advance a full turn cycle — a rest_of_game grant must not expire
    for _ in range(12):
        eng.advance_step()
    eng.recompute_continuous_effects()
    assert land.is_creature and land.power == 2 and land.toughness == 2


def test_earthbend_missing_land_is_a_noop():
    eng, state = _engine()
    eng.rules.earthbend(None, 3, source=None)  # no crash, nothing happens
    # a land not on the battlefield is ignored too
    off = GameObject(Card(id="x", name="X", type_line="Land", is_land=True),
                     owner_id="p1", zone=Zone.HAND)
    eng.rules.earthbend(off, 3, source=None)
    assert off.counters.get("+1/+1", 0) == 0


def test_earthbend_via_binder_end_to_end():
    eng, state = _engine()
    p1 = state.player_by_id("p1")
    land = _land(state, "p1")
    spell = Card(id="EL", name="Earthbending Lesson", type_line="Sorcery",
                 is_sorcery=True, mana_cost_string="{2}{G}",
                 oracle_text="Earthbend 3.")
    obj = GameObject(spell, owner_id="p1", zone=Zone.STACK)
    obj.controller_id = "p1"
    bind_from_catalogue(obj)
    assert obj.spell_effects, "earthbend spec should bind to a spell effect"

    for eff in obj.spell_effects:
        eff.apply(eng.rules.context, [land])
    eng.recompute_continuous_effects()
    assert land.is_creature and land.is_land
    assert land.counters.get("+1/+1") == 3
