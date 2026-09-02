"""MEC-52 — The Master, Gallifrey's End (hand-authored) + the two general
villainous-choice primitives it drove.

"Whenever a nontoken artifact creature you control dies, you may exile it.
If you do, choose an opponent with the most life among your opponents. That
player faces a villainous choice — They lose 4 life, or you create a token
that's a copy of that card."

- `FaceVillainousChoiceEffect.subject == "opponent_with_most_life"` — RULE
  701.55 pre-selection (ties → first in APNAP order).
- `FaceVillainousChoiceEffect.capture_previous` — the just-exiled card is
  baked into the choice so option B's `copy_permanent` `referent="previous"`
  resolves once the choice is *answered*.
- `ExileEffect`'s trigger-subject branch now seeds `context.previous_targets`.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine(players=3, life=20):
    seats = [(f"p{i+1}", chr(65 + i), []) for i in range(players)]
    eng = GameEngine.new_game(seats, starting_life=life, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    for p in eng.state.players:
        for i in range(5):
            p.library.append(GameObject(
                Card(id=f"{p.id}L{i}", name="Filler", type_line="Land — Plains"),
                owner_id=p.id, zone=Zone.LIBRARY,
            ))
    return eng, eng.state


def _master(st) -> GameObject:
    c = Card(
        id="TMGE", name="The Master, Gallifrey's End",
        type_line="Legendary Creature — Time Lord Rogue",
        is_creature=True, is_legendary=True, power=4, toughness=3,
        mana_cost_string="{2}{B}{R}", converted_mana_cost=4,
        oracle_text=(
            "Make Them Pay — Whenever a nontoken artifact creature you control "
            "dies, you may exile it. If you do, choose an opponent with the "
            "most life among your opponents. That player faces a villainous "
            "choice — They lose 4 life, or you create a token that's a copy "
            "of that card."
        ),
    )
    o = GameObject(c, owner_id="p1", zone=Zone.BATTLEFIELD)
    o.controller_id = "p1"
    st.add_to_battlefield(o)
    bind_from_catalogue(o)
    return o


def _artifact_creature(st, pid="p1", name="Servo") -> GameObject:
    c = Card(id=name[:6], name=name, type_line="Artifact Creature — Construct",
             is_creature=True, power=2, toughness=2)
    o = GameObject(c, owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


def test_registered_and_binds_one_triggered_ability():
    from mtg_analyzer.game import ability_catalogue as ac
    card = Card(id="x", name="The Master, Gallifrey's End",
                type_line="Legendary Creature — Time Lord Rogue",
                is_creature=True, power=4, toughness=3)
    specs = ac.specs_for(card)
    assert specs is not None and len(specs) == 1
    assert specs[0].ability_kind == "triggered"
    assert specs[0].optional is True
    # fresh objects each call
    again = ac.specs_for(card)
    assert again is not specs and again[0] is not specs[0]


def _run_dies_and_accept(eng, st, artifact):
    eng.rules.destroy(artifact)
    eng.resolve_until_stable()
    # RULE 603.5 "you may" — a `trigger_target` choice with a "do" sentinel.
    if st.pending_choice and st.pending_choice.get("kind") == "trigger_target":
        eng.resolve_pending_choice("do")
        eng.resolve_until_stable()


def test_dies_trigger_targets_the_highest_life_opponent_and_option_a_drains():
    eng, st = _engine(3)
    st.player_by_id("p2").life = 25   # most life
    st.player_by_id("p3").life = 12
    _master(st)
    art = _artifact_creature(st)

    _run_dies_and_accept(eng, st, art)

    assert art.zone == Zone.EXILE, "the dying artifact creature was exiled"
    assert st.pending_choice is not None
    assert st.pending_choice["kind"] == "villainous_choice"
    assert st.pending_choice["player_id"] == "p2", "the most-life opponent faces it"
    eng.resolve_pending_choice("0")   # they lose 4 life
    eng.resolve_until_stable()
    assert st.player_by_id("p2").life == 21
    assert st.pending_choice is None


def test_option_b_makes_a_copy_of_the_exiled_artifact_creature():
    eng, st = _engine(2)
    _master(st)
    art = _artifact_creature(st, name="Golem")

    _run_dies_and_accept(eng, st, art)
    assert st.pending_choice["player_id"] == "p2"
    eng.resolve_pending_choice("1")   # you create a token that's a copy of that card
    eng.resolve_until_stable()

    tokens = [o for o in st.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].card.name == "Golem"
    assert tokens[0].controller_id == "p1"
    assert st.player_by_id("p2").life == 20  # option A not taken


def test_a_token_artifact_creature_dying_does_not_trigger():
    eng, st = _engine(2)
    _master(st)
    art = _artifact_creature(st, name="Token Servo")
    art.is_token = True

    eng.rules.destroy(art)
    eng.resolve_until_stable()
    assert st.pending_choice is None, "nontoken filter — a token doesn't trigger it"
