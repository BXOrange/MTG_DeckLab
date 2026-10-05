"""The last two "Combat statics" gaps (RULE 508.1a/509.1b) —
`test_qualified_combat_restrictions.py`/`test_combat_requirements_and_
multiblock.py`'s batches deliberately left these two as narrow *parser*
gaps, not engine gaps (see `BACKLOG.md`'s "Combat statics" entry):

* A filter whose threshold is itself a board count, not a literal int —
  "Creatures with power less than the number of Islands you control can't
  block ~." (Kraken of the Straits-shaped). `combat.matches_object_filter`
  gains a ``power_lt_count_selector`` key (`continuous.count_selector`'s
  vocabulary, plus a new ``lands_you_control_of_type_<x>`` entry), evaluated
  fresh at combat time against the *attacker's* controller (RULE 613.7c:
  "you" always means the ability's own source's controller, not the blocker
  being checked) rather than a literal baked in at parse time.
* A group scope with its own qualifier — "Each creature you control **with
  power 4 or greater** can't be blocked by more than one creature."
  (Challenger Troll/Flopsie, Bumi's Buddy-shaped; Delney, Streetwise
  Lookout combines this with a filtered tail in the same sentence).
  `group_selector_objects` gains ``min_power``/``max_power``/
  ``min_toughness``/``max_toughness`` scope qualifiers, read off each
  affected object's own *derived* characteristics — which is also why
  `continuous.recompute` now stamps ``combat_restriction`` *after* the
  layer-7 P/T pass instead of before it (an anthem firing earlier in the
  very same recompute must already be visible to the qualifier).

Each test drives real oracle text through `parse_oracle` (asserting the card
is fully `MODELED`) **and** binds + exercises it against a real
`GameEngine`, per the project's "parse-only verification has masked real
runtime bugs" lesson (memory: oracle-parser-coverage).

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/{combat,continuous,game_engine}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _creature(name, oracle_text="", power=2, toughness=2, keywords=None,
              type_line="Creature — Dragon"):
    return Card(
        id=name, name=name, type_line=type_line, is_creature=True,
        power=power, toughness=toughness, oracle_text=oracle_text,
        keywords=list(keywords or []),
    )


def _land(name, type_line="Land — Island"):
    return Card(id=name, name=name, type_line=type_line, is_land=True, oracle_text="")


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


def _modeled(card):
    result = parse_oracle(card)
    assert result.coverage != UNMODELED, result.unclaimed
    assert result.unclaimed == []
    return result


def _attack(attacker, defender_id="p2"):
    attacker.attacking = True
    attacker.combat_defender = {"kind": "player", "id": defender_id, "label": defender_id}


# -- A dynamic count-selector threshold (Kraken of the Straits) -------------


def test_power_less_than_islands_you_control_blocks_dynamically():
    card = _creature(
        "Kraken of the Straits",
        "Creatures with power less than the number of Islands you control can't block ~.",
        power=7, toughness=7,
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    weak = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    strong = _put(state, _creature("Ogre", power=4, toughness=4), controller="p2")
    _put(state, _land("Island 1"))
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    # 1 Island controlled by Kraken's controller: power 1 < 1 is False, so the
    # weak blocker is *not* excluded yet; power 4 is nowhere near "less than 1".
    assert eng.can_block(defender, weak, attacker) is True
    assert eng.can_block(defender, strong, attacker) is True

    # Three more Islands: the threshold rises to 4. Power 1 < 4 excludes the
    # weak blocker; power 4 < 4 is False, so the strong one is still legal —
    # re-evaluated fresh, not baked in at parse time.
    _put(state, _land("Island 2"))
    _put(state, _land("Island 3"))
    _put(state, _land("Island 4"))
    continuous.recompute(state)
    assert eng.can_block(defender, weak, attacker) is False
    assert eng.can_block(defender, strong, attacker) is True


def test_power_less_than_islands_scoped_to_attackers_controller():
    # RULE 613.7c: "you" in the restriction means the ability's own source's
    # controller (Kraken's, here p1) — Islands the *blocker's* controller
    # (p2) has should never enter into it.
    card = _creature(
        "Kraken of the Straits",
        "Creatures with power less than the number of Islands you control can't block ~.",
        power=7, toughness=7,
    )
    eng = _engine()
    state = eng.state
    attacker = _put(state, card)
    weak = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    for i in range(5):
        _put(state, _land(f"p2 Island {i}"), controller="p2")
    continuous.recompute(state)
    _attack(attacker)

    defender = state.player_by_id("p2")
    # p1 (Kraken's controller) controls zero Islands: threshold is 0, so
    # "power less than 0" excludes nobody.
    assert eng.can_block(defender, weak, attacker) is True


# -- A qualified group scope (Challenger Troll / Flopsie, Bumi's Buddy) ------


def test_each_creature_with_power_qualifier_scopes_max_blockers():
    card = _creature(
        "Challenger Troll",
        "Each creature you control with power 4 or greater can't be blocked by more than one creature.",
        power=4, toughness=4,
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    big = _put(state, card)
    small = _put(state, _creature("Runt", power=2, toughness=2))
    continuous.recompute(state)

    assert combat.max_blockers(big) == 1
    assert combat.max_blockers(small) is None


def test_qualified_group_scope_reads_same_pass_anthem():
    # The qualifier has to see an anthem that fires in the *same* recompute
    # pass (`continuous.recompute` stamps combat_restriction after layer 7
    # for exactly this reason) — a creature pushed to qualifying power this
    # pass must be caught immediately, not one recompute later.
    lord = _creature(
        "Anthem Lord", "Other creatures you control get +2/+0.", power=1, toughness=1,
    )
    card = _creature(
        "Challenger Troll",
        "Each creature you control with power 4 or greater can't be blocked by more than one creature.",
        power=2, toughness=2,
    )
    eng = _engine()
    state = eng.state
    _put(state, lord)
    troll = _put(state, card)
    continuous.recompute(state)

    # 2 (base) + 2 (anthem) = 4 — qualifies in the very same pass.
    assert troll.power == 4
    assert combat.max_blockers(troll) == 1


def test_qualified_group_scope_with_filtered_tail():
    # Delney, Streetwise Lookout-shaped: the *subject* carries a qualifier
    # ("Creatures you control with power 2 or less") and the *tail* carries
    # its own independent filter ("blocked by creatures with power 3 or
    # greater") — two separate qualifier mechanisms in one clause.
    card = _creature(
        "Delney, Streetwise Lookout",
        "Creatures you control with power 2 or less can't be blocked by creatures with power 3 or greater.",
        power=2, toughness=2,
    )
    _modeled(card)

    eng = _engine()
    state = eng.state
    small = _put(state, card)
    big_ally = _put(state, _creature("Big Ally", power=3, toughness=3))
    continuous.recompute(state)
    weak_opp = _put(state, _creature("Squire", power=1, toughness=1), controller="p2")
    strong_opp = _put(state, _creature("Ogre", power=4, toughness=4), controller="p2")
    continuous.recompute(state)
    _attack(small)
    _attack(big_ally)

    defender = state.player_by_id("p2")
    # `small` (power 2) is in scope: a power-3+ blocker is excluded.
    assert eng.can_block(defender, weak_opp, small) is True
    assert eng.can_block(defender, strong_opp, small) is False
    # `big_ally` (power 3) is out of scope — its own restriction never
    # applies, so even the strong blocker is unaffected by *this* clause.
    assert eng.can_block(defender, strong_opp, big_ally) is True
