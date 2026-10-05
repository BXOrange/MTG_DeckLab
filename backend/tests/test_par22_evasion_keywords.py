"""PAR-22 — the RULE 509.1b / 702.18b evasion & targeting keyword family
that was parser-*recognized* (flag keyword rows in
`parser/oracle/catalogue/keywords.py`, docked onto
`GameObject.intrinsic_keywords`) but never *enforced* by any engine code:

* **Shroud** (702.18b) — can't be targeted by any spell/ability, its own
  controller's included (`targeting._targetable_by`).
* **Fear** (702.36b) — blocked only by artifact and/or black creatures.
* **Intimidate** (702.13b) — blocked only by artifact creatures and/or
  creatures sharing a colour with the attacker.
* **Skulk** (702.118b) — can't be blocked by creatures with greater power.
* **Shadow** (702.28b/c) — blocks / is blocked by only creatures with
  shadow, both directions.

Each is exercised against `combat.can_block` / `targeting.legal_targets`
directly, and at least one against a real `GameEngine.declare_blockers`
refusal, per the project's "parse-only verification masks runtime bugs"
lesson (memory: oracle-parser-coverage).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, keywords=None, power=2, toughness=2, colors=None,
              type_line="Creature — Human"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text="",
        keywords=list(keywords or []), color_identity=set(colors or set()),
    )


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- the parser side still recognizes the keyword --------------------------


@pytest.mark.parametrize("kw", ["Shroud", "Fear", "Intimidate", "Skulk", "Shadow"])
def test_keyword_still_parses_as_a_flag_keyword(kw):
    card = _creature(f"{kw} Bearer", keywords=[kw])
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(obj)
    assert kw.lower() in combat._obj_keywords(obj)


# -- Shroud (RULE 702.18b) -----------------------------------------------


def test_shroud_blocks_targeting_even_by_own_controller():
    state = _engine().state
    shrouded = _put(state, _creature("Silhana Ledgewalker", keywords=["Shroud"]))
    plain = _put(state, _creature("Bear"))
    own_source = _put(state, _creature("Pinger"))

    assert targeting._targetable_by(plain, own_source)
    assert not targeting._targetable_by(shrouded, own_source)  # own controller too


def test_shroud_blocks_targeting_by_opponent():
    state = _engine().state
    shrouded = _put(state, _creature("Silhana Ledgewalker", keywords=["Shroud"]))
    opp_source = _put(state, _creature("Enemy Pinger"), controller="p2")
    assert not targeting._targetable_by(shrouded, opp_source)


def test_shroud_appears_via_legal_targets_offer():
    from mtg_analyzer.game.targeting import TargetSpec

    state = _engine().state
    shrouded = _put(state, _creature("Silhana Ledgewalker", keywords=["Shroud"]))
    plain = _put(state, _creature("Bear"))
    src = _put(state, _creature("Pinger"))
    offered = targeting.legal_targets(state, "p1", TargetSpec(kind="creature"), src)
    ids = {t["instance_id"] for t in offered}
    assert plain.instance_id in ids and shrouded.instance_id not in ids


# -- Fear (RULE 702.36b) -----------------------------------------------


def test_fear_can_only_be_blocked_by_artifact_or_black():
    state = _engine().state
    attacker = _put(state, _creature("Nightscape Familiar", keywords=["Fear"], colors={"U"}))
    white_blocker = _put(state, _creature("White Bear", colors={"W"}), controller="p2")
    black_blocker = _put(state, _creature("Black Bear", colors={"B"}), controller="p2")
    artifact_blocker = _put(
        state, _creature("Ornithopter", type_line="Artifact Creature — Thopter"),
        controller="p2",
    )

    assert not combat.can_block(attacker, white_blocker)
    assert combat.can_block(attacker, black_blocker)
    assert combat.can_block(attacker, artifact_blocker)


# -- Intimidate (RULE 702.13b) ----------------------------------------


def test_intimidate_needs_shared_colour_or_artifact():
    state = _engine().state
    attacker = _put(state, _creature("Goblin War Drums Goblin", keywords=["Intimidate"], colors={"R"}))
    red_blocker = _put(state, _creature("Red Bear", colors={"R"}), controller="p2")
    green_blocker = _put(state, _creature("Green Bear", colors={"G"}), controller="p2")
    artifact_blocker = _put(
        state, _creature("Ornithopter", type_line="Artifact Creature — Thopter"),
        controller="p2",
    )

    assert combat.can_block(attacker, red_blocker)
    assert not combat.can_block(attacker, green_blocker)
    assert combat.can_block(attacker, artifact_blocker)


def test_colourless_intimidate_only_artifacts_block():
    state = _engine().state
    attacker = _put(
        state,
        _creature("Ghostfire Blade Wielder", keywords=["Intimidate"], colors=set(),
                  type_line="Artifact Creature — Construct"),
    )
    colourless_creature = _put(
        state, _creature("Eldrazi Spawn", colors=set()), controller="p2"
    )
    artifact_blocker = _put(
        state, _creature("Ornithopter", type_line="Artifact Creature — Thopter"),
        controller="p2",
    )
    assert not combat.can_block(attacker, colourless_creature)
    assert combat.can_block(attacker, artifact_blocker)


# -- Skulk (RULE 702.118b) ------------------------------------------


def test_skulk_stops_bigger_blockers_only():
    state = _engine().state
    attacker = _put(state, _creature("Tricky Fae", keywords=["Skulk"], power=2, toughness=2))
    smaller = _put(state, _creature("Weenie", power=1, toughness=1), controller="p2")
    equal = _put(state, _creature("Peer", power=2, toughness=2), controller="p2")
    bigger = _put(state, _creature("Giant", power=5, toughness=5), controller="p2")

    assert combat.can_block(attacker, smaller)
    assert combat.can_block(attacker, equal)
    assert not combat.can_block(attacker, bigger)


# -- Shadow (RULE 702.28b/c) --------------------------------------


def test_shadow_only_interacts_with_shadow():
    state = _engine().state
    shadow_attacker = _put(state, _creature("Dauthi Slayer", keywords=["Shadow"]))
    shadow_blocker = _put(state, _creature("Dauthi Marauder", keywords=["Shadow"]), controller="p2")
    plain_blocker = _put(state, _creature("Bear"), controller="p2")

    # shadow vs shadow: fine
    assert combat.can_block(shadow_attacker, shadow_blocker)
    # shadow attacker, non-shadow blocker: refused
    assert not combat.can_block(shadow_attacker, plain_blocker)
    # non-shadow attacker, shadow blocker: also refused (702.28c)
    plain_attacker = _put(state, _creature("Ground Bear"))
    assert not combat.can_block(plain_attacker, shadow_blocker)


# -- end-to-end: the engine actually refuses the block --------------


def test_engine_declare_blockers_refuses_illegal_shadow_block():
    eng = _engine()
    state = eng.state
    attacker = _put(state, _creature("Dauthi Horror", keywords=["Shadow"]))
    blocker = _put(state, _creature("Bear"), controller="p2")
    eng.start()
    while state.current_step != "declare_attackers":
        eng.advance_step()
    eng.declare_attackers(state.active_player, [attacker])
    eng.advance_step()
    assert state.current_step == "declare_blockers"
    defender = state.player_by_id("p2")
    with pytest.raises(ValueError):
        eng.declare_blockers(defender, [{"blocker": blocker, "attacker": attacker}])
