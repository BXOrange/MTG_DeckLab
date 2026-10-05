"""PAR-30 — "return that creature to its owner's hand at the beginning of
the next end step / at end of combat" trailing clause.

The hand-return sibling of the delayed sacrifice/exile/destroy tail
(`_DELAYED_SAC_EXILE_TAIL_RE`), over `create_delayed_trigger` with the same
`capture="previous_or_self"`. New inner effect `return_specific_to_hand`
(`ReturnSpecificToHandEffect`, an `.objects` list baked in by
`CreateDelayedTriggerEffect`). Ilharg, the Raze-Boar; Zara; Alora, Merry
Thief; and the "when ~ attacks or blocks, return it … at end of combat"
Phantom-Whelp cycle.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _engine():
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


# --- parse ----------------------------------------------------------------


def test_return_that_creature_next_end_step_parses():
    specs = match_clause(
        "return that creature to its owner's hand at the beginning of the next end step"
    )
    assert specs is not None
    s = specs[0]
    assert s.type == "create_delayed_trigger"
    assert s.params["step"] == "end"
    assert s.params["effects"][0]["type"] == "return_specific_to_hand"


def test_return_it_at_end_of_combat_parses():
    specs = match_clause("return it to its owner's hand at end of combat")
    assert specs is not None
    assert specs[0].params["step"] == "end_combat"
    assert specs[0].params["effects"][0]["type"] == "return_specific_to_hand"


def test_return_to_your_hand_parses():
    specs = match_clause(
        "return that creature to your hand at the beginning of the next end step"
    )
    assert specs is not None
    assert specs[0].params["effects"][0]["type"] == "return_specific_to_hand"


def test_return_without_a_delay_is_not_this_handler():
    assert match_clause("return that creature to its owner's hand") is None


# --- real cards ---------------------------------------------------------


def test_alora_merry_thief_modeled():
    c = Card(id="al", name="Alora, Merry Thief",
             type_line="Legendary Creature — Halfling Rogue", is_creature=True,
             oracle_text=("Whenever you attack, up to one target attacking creature "
                          "can't be blocked this turn. Return that creature to its "
                          "owner's hand at the beginning of the next end step."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


def test_phantom_whelp_modeled():
    c = Card(id="pw", name="Phantom Whelp", type_line="Creature — Illusion Drake",
             is_creature=True, oracle_text=(
                 "When this creature attacks or blocks, return it to its owner's "
                 "hand at end of combat."))
    res = parse_oracle(c)
    assert res.coverage != UNMODELED, res.unclaimed


# --- execute ----------------------------------------------------------


def test_previous_target_is_baked_into_the_delayed_return():
    eng, st = _engine()
    src = GameObject(Card(id="S", name="Ilharg", type_line="Creature"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    loaned = GameObject(Card(id="l", name="Loaned", type_line="Creature — Bear",
                             is_creature=True, power=3, toughness=3),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    loaned.controller_id = "p1"
    st.add_to_battlefield(loaned)

    ctx = GameContext(st, eng.rules)
    ctx.previous_targets = [loaned]
    build_effects(
        match_clause(
            "return that creature to its owner's hand at the beginning of the next end step"
        ),
        source=src,
    )[0].apply(ctx, [loaned])

    assert len(st.delayed_triggers) == 1
    inner = st.delayed_triggers[0].effects[0]
    assert type(inner).__name__ == "ReturnSpecificToHandEffect"
    assert inner.objects == [loaned]


def test_delayed_return_fires_and_bounces():
    eng, st = _engine()
    src = GameObject(Card(id="S", name="Src", type_line="Sorcery", is_sorcery=True),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    loaned = GameObject(Card(id="l", name="Loaned", type_line="Creature — Bear",
                             is_creature=True, power=3, toughness=3),
                        owner_id="p1", zone=Zone.BATTLEFIELD)
    loaned.controller_id = "p1"
    st.add_to_battlefield(loaned)

    ctx = GameContext(st, eng.rules)
    ctx.previous_targets = [loaned]
    build_effects(
        match_clause("return it to its owner's hand at the beginning of the next end step"),
        source=src,
    )[0].apply(ctx, [loaned])

    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert loaned not in st.battlefield
    assert loaned in st.player_by_id("p1").hand
