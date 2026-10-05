"""PAR-29 — RULE 701.55 Face a Villainous Choice (Doctor Who).

`RulesEngine._request_villainous_choice` runs an APNAP sweep (a
`villainous_choice` pending_choice per facing player, the `_request_vote`
sweep minus the tally); each facing player picks one of two option
effect-lists and it resolves **for them** (`_apply_effect_specs` with
`targets=[facing]`). `effects.FaceVillainousChoiceEffect` resolves the
facing players from `subject` (each_opponent / target / trigger_target_
player). `handlers._face_villainous_choice` mini-parses the two options.

Only cards whose *both* options parse are MODELED (Damocles Base, The
Dalek Emperor); the rest are tracked in PAR-30.

Reference: game/effects/core.py (`FaceVillainousChoiceEffect`), game/rules/
misc_mixin.py (`_request_villainous_choice` / `_advance_villainous_choice`
/ `_resume_villainous_choice`), game/engine/turn_loop_mixin.py dispatch.
"""

from __future__ import annotations

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle


# --- parse -----------------------------------------------------------------


def test_villainous_parse_edict_vs_lose_life():
    r = match_clause(
        "that player faces a villainous choice — they sacrifice a nontoken "
        "creature of their choice, or they lose 2 life and you draw 2 cards."
    )
    assert r and r[0].type == "face_villainous_choice"
    p = r[0].params
    assert p["subject"] == "trigger_target_player"
    assert p["option_a"] == [{"type": "sacrifice", "params": {"what": "nontoken_creature", "count": 1}}]
    assert p["option_b"][0] == {"type": "lose_life", "params": {"amount": 2, "target_kind": "player"}}


def test_villainous_parse_unmodelable_option_fails_closed():
    # option B ("create a token that's a copy of that card" — a
    # previously-referenced *card*, PAR-30) is not modeled → whole clause
    # unclaimed. ("cast a spell without paying" and the target-player edict
    # are modeled now, ENG-33.)
    assert match_clause(
        "target opponent faces a villainous choice — they discard 3 cards, or "
        "you create a token that's a copy of that card."
    ) is None


def test_real_villainous_cards_modeled():
    for name, text in [
        ("The Dalek Emperor",
         "At the beginning of combat on your turn, each opponent faces a "
         "villainous choice — that player sacrifices a creature of their "
         "choice, or you create a 3/3 black Dalek artifact creature token with menace."),
    ]:
        c = Card(id=name[:3], name=name, type_line="Legendary Creature — Alien",
                 is_creature=True, power=4, toughness=4, oracle_text=text)
        assert parse_oracle(c).modeled, (name, parse_oracle(c).unclaimed)


# --- execute -------------------------------------------------------------------


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cara", [])],
        starting_life=20, starting_hand=0,
    )


def _creature(state, pid, name):
    c = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
             power=2, toughness=2)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    state.add_to_battlefield(o)
    return o


def test_each_opponent_faces_and_applies_own_pick():
    eng = _engine()
    st = eng.state
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    p2_bear = _creature(st, "p2", "P2Bear")
    _creature(st, "p3", "P3Bear")

    eng.rules._request_villainous_choice(
        source=src, controller_id="p1",
        facing_ids=["p2", "p3"],
        option_a=[{"type": "sacrifice", "params": {"what": "creature", "count": 1}}],
        option_b=[{"type": "lose_life", "params": {"amount": 3, "target_kind": "player"}}],
    )
    # p2 (asked first) picks A -> sacrifices their bear
    assert st.pending_choice["kind"] == "villainous_choice"
    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("0")
    eng.resolve_until_stable()
    assert p2_bear not in st.battlefield
    assert st.player_by_id("p2").life == 20

    # p3 picks B -> loses 3 life, keeps their bear
    assert st.pending_choice["player_id"] == "p3"
    eng.resolve_pending_choice("1")
    eng.resolve_until_stable()
    assert st.player_by_id("p3").life == 17
    assert len([o for o in st.battlefield if o.controller_id == "p3" and o.is_creature]) == 1
    assert st.pending_choice is None


def test_you_clause_stays_controller_scoped():
    eng = _engine()
    st = eng.state
    src = GameObject(Card(id="s", name="Src", type_line="Enchantment"),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    _creature(st, "p2", "P2Bear")

    eng.rules._request_villainous_choice(
        source=src, controller_id="p1",
        facing_ids=["p2"],
        option_a=[{"type": "sacrifice", "params": {"what": "creature", "count": 1}}],
        option_b=[{"type": "gain_life", "params": {"amount": 5}}],   # "you gain 5 life"
    )
    eng.resolve_pending_choice("1")   # p2 picks B
    eng.resolve_until_stable()
    # the "you" (controller = p1) gains the life, not the facing player p2
    assert st.player_by_id("p1").life == 25
    assert st.player_by_id("p2").life == 20
