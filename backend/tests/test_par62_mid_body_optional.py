"""PAR-62 (``14_`` S4) — the first section-5.2 connective routed to a node.

RULE 601.2b's "you may <effect>" appearing **mid-body**. ``_peel_optional``
only ever stripped a *leading* "you may" at the whole-ability level, so
"..., then you may <effect>" — where the connector split hands
``parse_effect_body`` the "you may ..." part on its own — had no reading at
all. A standing gap named in ``09_`` and in the ticket.

What makes this S4 rather than another handler row: the connective becomes an
ENG-37 **``optional`` node** wrapping a recursively-parsed body, not a new
fused effect type and not another per-effect ``optional`` boolean. The rule
sits *after* the connector cascade, which returns on the first separator
yielding a complete parse — so it can only fire where the pipeline already
returned ``None``, and no card that parsed before parses differently. That is
what lets S4 land in increments instead of as one re-derivation of every
MODELED card (measured: +7 cards, 0 regressed, across all 34,811).

Two engine defects fell out of routing a real card through the node — see
`TestOptionalAnnouncesTargets`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.game.effects.core import GameContext, _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


class TestParse:
    def test_a_standalone_you_may_becomes_an_optional_node(self) -> None:
        specs = parse_effect_body("you may draw a card")
        assert specs is not None
        assert [s.type for s in specs] == ["optional"]
        assert specs[0].params["effects"] == [{"type": "draw", "params": {"count": 1}}]

    def test_it_reaches_a_you_may_that_is_not_the_first_clause(self) -> None:
        # The actual gap: the connector split hands the second part over on
        # its own, and nothing used to claim it.
        specs = parse_effect_body("draw a card, then you may discard a card")
        assert specs is not None
        assert [s.type for s in specs] == ["draw", "optional"]
        assert specs[1].params["effects"] == [{"type": "discard", "params": {"count": 1}}]

    def test_an_unparseable_body_is_still_unclaimed(self) -> None:
        # Fail-closed: the node must not claim a "you may" whose body has no
        # reading, or the card models a choice that then does nothing.
        assert parse_effect_body("you may quibble with the umpire") is None


class TestAdversarial:
    def test_a_reflexive_trigger_is_not_collapsed(self) -> None:
        # RULE 603.3: "you may A. **when you do**, B." — B is a separate
        # triggered ability that fires because A happened and uses the stack,
        # not the second half of one choice. Wrapping both in one node is a
        # *wrong* reading rather than a missing one, so this fails closed and
        # leaves the shape to its own grammar.
        assert parse_effect_body("you may earthbend 2. when you do, draw a card.") is None

    def test_the_if_you_do_sibling_keeps_its_own_grammar(self) -> None:
        specs = parse_effect_body("you may pay {2}. if you do, draw a card.")
        assert specs is not None
        assert [s.type for s in specs] == ["pay_cost_then"]

    def test_two_independent_choices_stay_independent(self) -> None:
        # "you may A. you may B" is two questions, not one — merging them
        # would make declining the first silently skip the second. The
        # connector split reaches this first and gives each its own node,
        # which is the right reading; the rule's own one-per-node guard only
        # has to stop it wrapping a body that still leads with "you may".
        specs = parse_effect_body("you may draw a card. you may draw a card")
        assert specs is not None
        assert [s.type for s in specs] == ["optional", "optional"]
        assert all(
            s.params["effects"] == [{"type": "draw", "params": {"count": 1}}]
            for s in specs
        )


class TestOptionalAnnouncesTargets:
    """Both halves of a real defect this increment exposed.

    `OptionalEffect` had been grouped with ``if_else``/``for_each``/``bind`` as
    a node that announces no targets. It belongs with ``seq``: its body is
    fixed and singular, so RULE 601.2c fixes the targets on announcement and
    RULE 601.2b merely decides, at resolution, whether the body runs.
    """

    @staticmethod
    def _board():
        eng = GameEngine.new_game(
            [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
        )
        bear = GameObject(
            Card(id="B", name="Bear", type_line="Creature - Bear",
                 is_creature=True, power=2, toughness=2),
            owner_id="p2", zone=Zone.BATTLEFIELD,
        )
        bear.summoning_sick = False
        eng.state.add_to_battlefield(bear)
        source = GameObject(
            Card(id="S", name="Src", type_line="Instant", is_instant=True),
            owner_id="p1", zone=Zone.STACK,
        )
        return eng, bear, source

    def _optional_tap(self, source):
        return build_effects([EffectSpec("optional", {"effects": [
            {"type": "tap", "params": {"target_kind": "creature"}},
        ]})], source)[0]

    def test_it_announces_its_bodys_targets(self) -> None:
        _eng, _bear, source = self._board()
        assert [spec.kind for spec in self._optional_tap(source).target_specs] == ["creature"]

    def test_the_announced_target_survives_the_pause(self) -> None:
        # RULE 608.2h: the body does not run until the question is answered,
        # so the targets have to be carried across the pause by id. Without
        # this the card parsed as MODELED and then resolved to nothing.
        eng, bear, source = self._board()
        _apply_effects_partitioned(
            [self._optional_tap(source)], GameContext(eng.state, eng.rules),
            [bear], None, source=source,
        )
        choice = eng.state.pending_choice
        assert choice is not None and choice["kind"] == "composite_optional"
        assert bear.tapped is False
        eng.rules.resolve_choice("yes")
        eng.resolve_until_stable()
        assert bear.tapped is True

    def test_declining_does_nothing(self) -> None:
        eng, bear, source = self._board()
        _apply_effects_partitioned(
            [self._optional_tap(source)], GameContext(eng.state, eng.rules),
            [bear], None, source=source,
        )
        eng.rules.resolve_choice("decline")
        eng.resolve_until_stable()
        assert bear.tapped is False


@pytest.mark.full_cache
class TestRealCards:
    @staticmethod
    def _card(name: str) -> Card:
        card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
        if card is None:
            pytest.skip(f"{name!r} not in the local card cache")
        return card

    def test_choking_tethers_is_modeled_and_targets(self) -> None:
        # "When you cycle this card, you may tap target creature." — the card
        # that exposed the target-announcement half of the bug.
        result = parse_oracle(self._card("Choking Tethers"))
        assert result.modeled, result.unclaimed
        optionals = [e for spec in result.specs for e in spec.effects
                     if e.type == "optional"]
        assert optionals and optionals[0].params["effects"] == [
            {"type": "tap", "params": {"target_kind": "creature", "untap": False}}
        ]

    def test_krosan_tusker_is_modeled(self) -> None:
        # "When you cycle this card, you may search your library for a basic
        # land card, ... then shuffle." — a multi-effect optional body.
        result = parse_oracle(self._card("Krosan Tusker"))
        assert result.modeled, result.unclaimed
