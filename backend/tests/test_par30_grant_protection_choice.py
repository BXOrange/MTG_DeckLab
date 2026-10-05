"""PAR-30 — "gains protection from the color of your choice until end of turn".

RULE 702.16. The engine primitive is Mother of Runes' `GrantProtectionEffect`
/ `RulesEngine.grant_protection_choice` (an interactive `grant_protection_
color` pick landing in `GameObject.temp_protections`, cleared at cleanup);
only the parser recognition of this exact phrasing (~27 SOLO) was missing.
`GrantProtectionEffect` gained a self (`target_kind=None`) and a
`previous_subject` mode.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_clause_forms():
    assert match_clause(
        "target creature you control gains protection from the color of your "
        "choice until end of turn"
    ) == [EffectSpec("grant_protection", {"target_kind": "creature_you_control"})]
    assert match_clause(
        "~ gains protection from the color of your choice until end of turn",
        self_subject=True,
    ) == [EffectSpec("grant_protection", {"target_kind": None})]
    assert match_clause(
        "it gains protection from the color of your choice until end of turn",
        previous_subject=True,
    ) == [EffectSpec("grant_protection", {"previous_subject": True})]


def test_real_cards_modeled():
    for name, text in [
        ("Gods Willing",
         "Target creature you control gains protection from the color of your "
         "choice until end of turn."),
        ("Feat of Resistance",
         "Put a +1/+1 counter on target creature you control. It gains "
         "protection from the color of your choice until end of turn."),
        ("Redeem the Lost",
         "Target creature you control gains protection from the color of your "
         "choice until end of turn. Clash with an opponent. If you win, return "
         "Redeem the Lost to its owner's hand."),
    ]:
        c = Card(id=name[:5], name=name, type_line="Instant", is_instant=True,
                 mana_cost_string="{W}", oracle_text=text)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


def test_grant_protection_choice_end_to_end():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    st = eng.state
    bear = GameObject(
        Card(id="BR", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bear.controller_id = "p1"
    st.add_to_battlefield(bear)
    src = GameObject(Card(id="GW", name="Gods Willing", type_line="Instant", is_instant=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    eff = build_effects(
        [EffectSpec("grant_protection", {"target_kind": "creature_you_control"})], src
    )[0]
    eff.apply(eng.rules.context, [bear])

    pc = getattr(st, "pending_choice", None)
    assert pc is not None and pc.get("kind") == "grant_protection_color"
    eng.resolve_pending_choice(pc["options"][3]["id"])  # pick "R"
    assert "R" in bear.temp_protections
