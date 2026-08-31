"""PAR-29 — RULE 701.65 Airbend (Avatar: The Last Airbender).

"Airbend target X" = exile it; while it's exiled its owner may cast it for
a fixed {2} rather than its mana cost. Built on `ExileEffect`'s existing
`grant_owner_play_permission` (→ `GameState.exile_cast_condition`) plus a
new `owner_play_permission_cost` that stamps `GameState.
exile_cast_cost_override`, which `GameEngine.effective_cast_cost` consults
as a fixed alternative cost (like Flashback/Escape's graveyard alt cost).

Reference: models/game_state.py (`exile_cast_cost_override`), game/
effects.py (`ExileEffect.owner_play_permission_cost`), game/engine/
casting_mixin.py (`effective_cast_cost`), parser/oracle/catalogue/
handlers.py (`_airbend`).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


# --- parse -----------------------------------------------------------------


def test_airbend_clause_forms():
    a = match_clause("airbend target nonland permanent")
    assert a and a[0].type == "exile"
    assert a[0].params["target_kind"] == "nonland_permanent"
    assert a[0].params["grant_owner_play_permission"] is True
    assert a[0].params["owner_play_permission_cost"] == "{2}"

    b = match_clause("airbend up to 2 target creatures")
    assert b and b[0].params == {
        "target_kind": "creature", "grant_owner_play_permission": True,
        "owner_play_permission_cost": "{2}", "count": 2, "optional": True,
    }

    # "creature or spell" (exile off the stack) stays unclaimed
    assert match_clause("airbend up to 1 other target creature or spell") is None


def test_real_airbend_cards_modeled():
    for name, text in [
        ("Airbending Lesson", "Airbend target nonland permanent.\nDraw a card."),
        ("Whirlwind Technique", "Airbend up to two target creatures."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Sorcery", is_sorcery=True,
                 mana_cost_string="{2}{W}", oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def test_airbend_exiles_and_grants_fixed_cost_cast_permission():
    eng, state = _engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    victim = GameObject(
        Card(id="V", name="Big Bear", type_line="Creature — Bear", is_creature=True,
             power=5, toughness=5, mana_cost_string="{4}{G}{G}", converted_mana_cost=6),
        owner_id="p2", zone=Zone.BATTLEFIELD,
    )
    victim.controller_id = "p2"
    state.add_to_battlefield(victim)

    spell = GameObject(
        Card(id="AL", name="Airbending Lesson", type_line="Sorcery", is_sorcery=True,
             oracle_text="Airbend target nonland permanent.\nDraw a card."),
        owner_id="p1", zone=Zone.STACK,
    )
    spell.controller_id = "p1"
    bind_from_catalogue(spell)
    for eff in spell.spell_effects:
        eff.apply(eng.rules.context, [victim])

    assert victim not in state.battlefield
    assert victim in p2.exile
    # owner (p2) may cast it from exile...
    assert eng._has_conditional_exile_permission(victim, p2)
    assert not eng._has_conditional_exile_permission(victim, p1)   # not the airbender
    # ...for a fixed {2}, not its printed {4}{G}{G}
    assert state.exile_cast_cost_override.get(victim.instance_id) == "{2}"
    assert eng.effective_cast_cost(p2, victim).converted_mana_cost == 2
