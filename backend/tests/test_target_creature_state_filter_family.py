""""target attacking/blocking/tapped/untapped creature" (RULE 508/509's
combat-state qualifiers) as a real `TargetSpec.creature_filter`, not just a
bare "creature" pick.

Found auditing PAR-79's own "target legendary/attacking creature can't be
blocked this turn" fix one layer down: `subgrammars._TARGET_ROWS`'s row for
this exact phrase collapses all four words onto the plain ``"creature"``
kind by design (RULE 115's own precision-loss convention), but nothing
preserved the discarded word elsewhere — so every handler that read
`resolve_target_kind` alone and threaded the result straight into
``target_kind`` silently dropped it. Confirmed via `inspect-db` against the
real card cache: **Assassinate** ("Destroy target tapped creature.") parsed
`MODELED` but the emitted spec (`destroy {"target_kind": "creature"}`) would
destroy *any* creature in an actual game, not just tapped ones — a live
rules bug on an already-shipped card, not a coverage gap.

New sibling function `subgrammars.resolve_target_creature_state_filter`
extracts the qualifier from the same raw target phrase as a
`combat.matches_object_filter` fragment (``{"tapped": True}``/``{"attacking":
True}``/…, "untapped" as ``{"tapped": False}``) and is merged into
``creature_filter`` by `_destroy`, `_exile`, `_exile_until_leaves`,
`_damage`/`_damage_x`, `_tap`, `_return_to_hand`, every `_pump_target(m)`
caller (via the shared `_pump_target_creature_filter` helper),
`_add_counters_target_params`, `_cant_be_blocked_turn`, and `_connive_target`.

A second, independent instance of the identical root shape was found in the
same sweep: `_pump_subtype_target`/`_grant_subtype_target`'s bare
``[a-z]+`` "subtype" capture blindly accepted "attacking"/"blocking" as if
they were real creature subtypes ("target attacking creature gets +1/+1" →
`creature_filter={"subtype": "Attacking"}`) — a filter that could then
*never* match any real creature (RULE 115 target-count of zero), worse than
Assassinate's over-wide match. Both now route through the same function
first.

`ConniveEffect` (`game/effects/choices_actions.py`) gained a real
`creature_filter` constructor param + registry forwarding as part of this
fix — the one card in the sweep (Raffine, Scheming Seer) needing an actual
engine addition, not just parser wiring, mirroring the shape every other
targeted effect already had.

87 real cards fixed (`Assassinate`, `Royal Assassin`, `Excoriate`, `Vanquish`,
`Anointer of Champions`, `Galestrike`, `Raffine, Scheming Seer`, … — the full
list is reproducible via a cache scan, not enumerated here), 0 coverage
change (every one was already `MODELED` — this corrects the emitted spec,
not the verdict), 0 regressed.

Reference: parser/oracle/catalogue/subgrammars.py, handlers.py;
game/effects/choices_actions.py, effects/registry.py; game/targeting.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import resolve_target_creature_state_filter
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _creature(name, power=2, toughness=2, oracle_text="", type_line="Creature — Bear"):
    return Card(id=name, name=name, type_line=type_line, is_creature=True,
                power=power, toughness=toughness, oracle_text=oracle_text)


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    return obj


# --- the resolver itself ---------------------------------------------------


def test_resolve_target_creature_state_filter():
    assert resolve_target_creature_state_filter("target tapped creature") == {"tapped": True}
    assert resolve_target_creature_state_filter("target untapped creature") == {"tapped": False}
    assert resolve_target_creature_state_filter("target attacking creature") == {"attacking": True}
    assert resolve_target_creature_state_filter("target blocking creature") == {"blocking": True}
    # No qualifier at all — a plain "target creature" carries no state info.
    assert resolve_target_creature_state_filter("target creature") is None
    assert resolve_target_creature_state_filter("target creature you control") is None


# --- parse: each retrofitted handler family ---------------------------------


def test_destroy_tapped_creature_parses():
    assert match_clause("destroy target tapped creature") == [
        EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"tapped": True}}),
    ]


def test_destroy_untapped_creature_parses():
    assert match_clause("destroy target untapped creature") == [
        EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"tapped": False}}),
    ]


def test_exile_attacking_creature_parses():
    assert match_clause("exile target attacking creature") == [
        EffectSpec("exile", {"target_kind": "creature", "creature_filter": {"attacking": True}}),
    ]


def test_damage_tapped_creature_parses():
    assert match_clause("~ deals 3 damage to target tapped creature") == [
        EffectSpec("damage", {
            "amount": 3, "target_kind": "creature", "creature_filter": {"tapped": True},
        }),
    ]


def test_tap_untapped_creature_parses():
    assert match_clause("tap target untapped creature") == [
        EffectSpec("tap", {"target_kind": "creature", "untap": False, "creature_filter": {"tapped": False}}),
    ]


def test_return_to_hand_tapped_creature_parses():
    assert match_clause("return target tapped creature to its owner's hand") == [
        EffectSpec("return_to_hand", {"target_kind": "creature", "creature_filter": {"tapped": True}}),
    ]


def test_pump_attacking_creature_parses():
    # `_pump` (the base pump handler behind `_pump_target`'s 13 callers).
    assert match_clause("target attacking creature gets +3/+3 until end of turn") == [
        EffectSpec("pump", {
            "power": 3, "toughness": 3, "target_kind": "creature",
            "creature_filter": {"attacking": True},
        }),
    ]


def test_add_counters_attacking_creature_parses():
    assert match_clause("put a +1/+1 counter on target attacking creature") == [
        EffectSpec("add_counters", {
            "count": 1, "kind": "+1/+1", "target_kind": "creature",
            "creature_filter": {"attacking": True},
        }),
    ]


def test_connive_attacking_creature_parses():
    assert match_clause(
        "target attacking creature connives x, where x is the number of attacking creatures"
    ) == [EffectSpec("connive", {
        "target_kind": "creature", "times_from_count_selector": "attacking_creatures",
        "creature_filter": {"attacking": True},
    })]


def test_unblockable_attacking_creature_still_correct():
    # PAR-79's own family — regression guard for the same fix applied there.
    # This bare (no "another") phrasing is claimed by `_cant_be_blocked_turn`
    # itself (its `TARGET` macro already has a dedicated "attacking/
    # blocking/tapped/untapped creature" row), not the `object_filter`-based
    # fallback row — so no extra `card_type` key here, unlike a *subtype*
    # word (e.g. "legendary"), which `TARGET` doesn't recognize at all and
    # which falls through to that other row instead.
    specs = match_clause("target attacking creature can't be blocked this turn")
    assert specs == [EffectSpec("unblockable", {
        "target_kind": "creature", "creature_filter": {"attacking": True},
    })]


# --- the second, independent bug: bogus "Attacking"/"Blocking" subtype -----


def test_pump_subtype_target_does_not_guess_attacking_as_a_subtype():
    # Previously: `creature_filter={"subtype": "Attacking"}` — a filter that
    # could never match any real creature (RULE 115 target-count 0), worse
    # than silently over-matching.
    assert match_clause("target attacking creature gets +2/+2 until end of turn") == [
        EffectSpec("pump", {
            "power": 2, "toughness": 2, "target_kind": "creature",
            "creature_filter": {"attacking": True},
        }),
    ]


def test_pump_subtype_target_real_subtype_still_works():
    # Adversarial: a genuine subtype must still resolve as one, not as a
    # (nonexistent) combat-state flag.
    assert match_clause("target sliver creature gets +2/+2 until end of turn") == [
        EffectSpec("pump", {
            "power": 2, "toughness": 2, "target_kind": "creature",
            "creature_filter": {"subtype": "Sliver"},
        }),
    ]


def test_grant_subtype_target_does_not_guess_blocking_as_a_subtype():
    assert match_clause("target blocking creature gains flying until end of turn") == [
        EffectSpec("pump", {
            "keywords": ["flying"], "target_kind": "creature",
            "creature_filter": {"blocking": True},
        }),
    ]


# --- execute: the engine actually restricts the offered targets ------------


def test_legal_targets_respects_tapped_creature_filter():
    # The direct proof this isn't just a parse-level fix: Assassinate must
    # not be able to see an untapped creature as a legal target at all.
    eng = _engine()
    state = eng.state
    tapped_one = _put(state, _creature("Tapped Bear"), controller="p2", tapped=True)
    untapped_one = _put(state, _creature("Untapped Bear"), controller="p2", tapped=False)
    continuous.recompute(state)

    spec = TargetSpec(kind="creature", creature_filter={"tapped": True})
    offered_ids = {d["instance_id"] for d in legal_targets(state, "p1", spec)}
    assert tapped_one.instance_id in offered_ids
    assert untapped_one.instance_id not in offered_ids


def test_legal_targets_respects_attacking_creature_filter():
    eng = _engine()
    state = eng.state
    attacker = _put(state, _creature("Attacker"), controller="p2")
    attacker.attacking = True
    bystander = _put(state, _creature("Bystander"), controller="p2")
    continuous.recompute(state)

    spec = TargetSpec(kind="creature", creature_filter={"attacking": True})
    offered_ids = {d["instance_id"] for d in legal_targets(state, "p1", spec)}
    assert attacker.instance_id in offered_ids
    assert bystander.instance_id not in offered_ids


# --- end-to-end: the real card ----------------------------------------------


def test_assassinate_is_correctly_modeled():
    card = _creature("Assassinate", oracle_text="Destroy target tapped creature.",
                      type_line="Sorcery")
    card.is_sorcery = True
    card.is_creature = False
    card.power = card.toughness = None
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    destroy_specs = [
        e for a in result.specs for e in (a.effects or []) if e.type == "destroy"
    ]
    assert destroy_specs == [
        EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"tapped": True}}),
    ]
