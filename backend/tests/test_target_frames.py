"""ENG-34 S0b — `TargetSpec.kind` decomposes into a structured frame.

`14_` §4 names `targeting.py` as the place axis 2 (operands) is spelled out
instead of declared: opaque `kind` strings dispatched by one hand-written
branch apiece, with union types written as single words rather than
composed. `TARGET_FRAMES` is the decomposition; these tests keep it honest,
the same way `test_isa_inventory.py` keeps the effect-type classification
honest.

Nothing here asserts *behaviour* — the 6,500-test suite already covers what
`legal_targets` returns, and ENG-34 is a no-behaviour-change ticket. What
these guard is that the vocabulary stays total and that the kinds
deliberately left un-framed stay the documented, irreducible list rather
than quietly growing back.
"""
from __future__ import annotations

import inspect

import pytest

from mtg_analyzer.game import targeting


#: The kinds that legitimately keep a hand-written branch: each reads from
#: somewhere other than the battlefield, or carries attachment-legality
#: logic of its own. Written out rather than derived so that adding a new
#: opaque kind fails this test and forces the "can this be a frame?"
#: question — which is the whole point of S0b.
IRREDUCIBLE_KINDS = frozenset({
    # attachment legality (equip/fortify/reconfigure/enchant) off the
    # source's own parametric keywords
    "permanent",
    # plain player lists ("another target player": every player but the one the firing event names — The Lord of Pain)
    "player", "opponent", "player_other_than_event_player",
    # a per-turn damage record, not the board
    "player_dealt_combat_damage_by_source",
    # "any target" — the RULE 115.1 union of creature/planeswalker/battle
    # /player, with its own damage-redirection interactions
    "any",
    # RULE 115.6 self-exclusion variants that interact with the attachment
    # branch above
    "creature", "creature_including_self",
    # reads combat assignments (`source.blocking` / `source.additional_blocking`
    # or, conversely, blockers that name the source)
    "creature_source_is_blocking", "creature_blocking_source",
    # the stack, not the battlefield
    "spell", "spell_you_control", "spell_you_dont_control", "ability", "ability_you_control", "spell_or_ability",
    "spell_or_creature", "spell_or_nonland_permanent_you_dont_control",
    # the stack, the battlefield and every graveyard at once (Endless Detour) — no single zone for a frame to read
    "spell_nonland_permanent_or_graveyard_card",
})


def _graveyard_kinds() -> frozenset[str]:
    """The already-composed graveyard family (scope × type-filter)."""
    return frozenset(targeting._GRAVEYARD_TARGET_KINDS)


class TestFrameTotality:
    def test_every_battlefield_kind_has_a_frame(self) -> None:
        unframed = sorted(
            k for k in targeting.ALLOWED_TARGET_KINDS
            if k not in targeting.TARGET_FRAMES
            and k not in IRREDUCIBLE_KINDS
            and k not in _graveyard_kinds()
        )
        assert not unframed, (
            f"{len(unframed)} target kind(s) have neither a frame nor a "
            f"documented reason to stay opaque: {unframed}. Either add a "
            f"`TARGET_FRAMES` row or add it to IRREDUCIBLE_KINDS with the "
            f"reason — 14_ §4's whole complaint is that these strings do not "
            f"decompose."
        )

    def test_no_frame_names_an_unknown_kind(self) -> None:
        # `equipment_attached_to_source` is reachable via an effect param's
        # `target_kind` (see `parser/oracle/catalogue/handlers.py`'s
        # destroy-attached-Equipment handler) without being a whitelisted
        # `TargetSpec.kind`, so it is allowed here but nothing else is.
        known = set(targeting.ALLOWED_TARGET_KINDS) | {"equipment_attached_to_source"}
        unknown = sorted(set(targeting.TARGET_FRAMES) - known)
        assert not unknown, f"frames for unknown kinds: {unknown}"

    def test_irreducible_kinds_are_all_real(self) -> None:
        unknown = sorted(IRREDUCIBLE_KINDS - set(targeting.ALLOWED_TARGET_KINDS))
        assert not unknown, f"IRREDUCIBLE_KINDS lists dead kinds: {unknown}"

    def test_a_kind_is_not_both_framed_and_irreducible(self) -> None:
        both = sorted(set(targeting.TARGET_FRAMES) & IRREDUCIBLE_KINDS)
        assert not both


class TestFrameWellFormedness:
    @pytest.mark.parametrize("kind", sorted(targeting.TARGET_FRAMES))
    def test_frame_names_a_real_type_predicate(self, kind: str) -> None:
        frame = targeting.TARGET_FRAMES[kind]
        assert frame.types in targeting._FRAME_TYPE_PREDICATES, (
            f"{kind} names unknown type predicate {frame.types!r}"
        )

    @pytest.mark.parametrize("kind", sorted(targeting.TARGET_FRAMES))
    def test_frame_names_a_real_scope(self, kind: str) -> None:
        frame = targeting.TARGET_FRAMES[kind]
        assert frame.scope in {
            targeting.SCOPE_ANY, targeting.SCOPE_YOU, targeting.SCOPE_NOT_YOU,
            targeting.SCOPE_NOT_YOU_STRICT,
            targeting.SCOPE_NEITHER_OWN_NOR_CONTROL, targeting.SCOPE_OWNER_YOU,
            targeting.SCOPE_DEFENDING, targeting.SCOPE_THAT_PLAYER,
        }, f"{kind} names unknown scope {frame.scope!r}"

    @pytest.mark.parametrize("kind", sorted(targeting.TARGET_FRAMES))
    def test_frame_attachment_mode_is_known(self, kind: str) -> None:
        assert targeting.TARGET_FRAMES[kind].attached in (
            "", "any", "to_source", "host_you_control"
        )

    def test_players_first_only_with_opponents(self) -> None:
        for kind, frame in targeting.TARGET_FRAMES.items():
            if frame.players_first:
                assert frame.with_opponents or frame.with_all_players, (
                    f"{kind} orders players first but unions no players"
                )


class TestUnionsAreComposed:
    """`14_` §4's specific complaint: unions spelled as single strings.

    A union kind's predicate must be built from the single-type rows, not
    open-coded — otherwise the table reproduces the problem it replaces one
    level down.
    """

    UNION_KINDS = (
        "artifact_or_enchantment", "artifact_or_creature",
        "artifact_creature_or_enchantment", "creature_or_planeswalker",
        "artifact_creature_enchantment_or_planeswalker",
        "creature_planeswalker_or_battle", "creature_or_enchantment",
    )

    @pytest.mark.parametrize("types", UNION_KINDS)
    def test_union_predicate_exists(self, types: str) -> None:
        assert types in targeting._FRAME_TYPE_PREDICATES

    def test_union_predicates_agree_with_their_parts(self) -> None:
        # A union's predicate must accept exactly what the OR of its named
        # single-type predicates accepts. Checked structurally against a set
        # of stub objects rather than a real board — this is a property of
        # the table, not of any game.
        preds = targeting._FRAME_TYPE_PREDICATES

        class _Card:
            def __init__(self, artifact=False, enchantment=False, legendary=False):
                self.is_artifact = artifact
                self.is_enchantment = enchantment
                self.is_legendary = legendary
                self.type_line = ""

        class _Obj:
            def __init__(self, **kw):
                self.is_creature = kw.get("creature", False)
                self.is_land = kw.get("land", False)
                self.is_planeswalker = kw.get("planeswalker", False)
                self.is_battle = kw.get("battle", False)
                self.colors = ()
                self.card = _Card(kw.get("artifact", False), kw.get("enchantment", False))

        samples = [
            _Obj(creature=True), _Obj(land=True), _Obj(artifact=True),
            _Obj(enchantment=True), _Obj(planeswalker=True), _Obj(battle=True),
            _Obj(artifact=True, creature=True), _Obj(),
        ]
        pairs = {
            "artifact_or_enchantment": ("artifact", "enchantment"),
            "artifact_or_creature": ("artifact", "creature"),
            "creature_or_planeswalker": ("creature", "planeswalker"),
            "creature_or_enchantment": ("creature", "enchantment"),
            "artifact_creature_or_enchantment": ("artifact", "creature", "enchantment"),
            "creature_planeswalker_or_battle": ("creature", "planeswalker", "battle"),
            "artifact_creature_enchantment_or_planeswalker": (
                "artifact", "creature", "enchantment", "planeswalker"),
        }
        for union, parts in pairs.items():
            for obj in samples:
                expected = any(preds[p](obj) for p in parts)
                assert bool(preds[union](obj)) == expected, (
                    f"{union} disagrees with OR of {parts} on {vars(obj)}"
                )


class TestDispatchIsStructural:
    """The 58-branch cascade is gone, not merely bypassed."""

    def test_legal_targets_has_few_name_branches_left(self) -> None:
        source = inspect.getsource(targeting._legal_targets_for)
        branches = source.count("if kind ==") + source.count("if kind in")
        # 14_ S0b's exit: `legal_targets` dispatches on structure, not on 58
        # name branches. What remains is the documented irreducible set plus
        # the graveyard family's single composed branch, plus (bumped 14 -> 15)
        # `player_or_planeswalker_or_creature_subtype` (MEC-45's own sibling
        # family): it wants every player, not `with_opponents`' opponents-only
        # union, and its type predicate reads `spec.creature_filter`'s subtype
        # at call time rather than being one of `_FRAME_TYPE_PREDICATES`'
        # fixed lambdas — neither fits `TargetFrame`'s shape. Bumped 15 -> 16 for `player_other_than_event_player`
        # (The Lord of Pain): a plain player list whose exclusion is read off the firing event, so — like
        # `opponent` — it cannot be a battlefield frame.
        # Bumped 16 -> 17 for `spell_nonland_permanent_or_graveyard_card` (Endless Detour): one target spanning the stack, the
        # battlefield and every graveyard, so it can be neither a battlefield frame nor a graveyard-family kind.
        assert branches <= 17, (
            f"{branches} name branches left in legal_targets; the frame "
            f"dispatch was supposed to absorb them"
        )

    def test_frame_dispatch_runs_before_the_remaining_branches(self) -> None:
        source = inspect.getsource(targeting._legal_targets_for)
        dispatch = source.index("TARGET_FRAMES.get(kind)")
        first_branch = source.index("if kind ==")
        assert dispatch < first_branch, (
            "a framed kind must not be shadowed by a leftover branch"
        )
