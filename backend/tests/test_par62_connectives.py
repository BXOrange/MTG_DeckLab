"""PAR-62 (``14_`` S4) — the rest of section 5.2's connectives as nodes/gates.

Each connective is routed to something that already exists rather than to a new
fused effect type: ``if``/``unless`` to a RULE 603.4 gate over the *shared*
condition whitelist (`static_handlers.static_condition`, the same recognizer
the RULE 613.6 "as long as" statics use), ``if …/otherwise`` to ENG-37's
``if_else`` node, and "for each `<group>`" to its ``for_each`` node.

Two placement rules do the safety work, and both are load-bearing enough to be
pinned here:

* the **generic** condition rows run last, after ``match_clause`` *and* the
  connector cascade, so they can only convert an already-unclaimed body — the
  specific rows keep their pre-``match_clause`` position;
* ``if …/otherwise`` is the exception and runs *before* the cascade, because
  the split would otherwise hand "otherwise, `<B>`" to the standing clash row.

Measured across all 34,811 cached cards: +138 covered, **0 regressed**
(41.84% → 42.23%).
"""

from __future__ import annotations

import inspect

import pytest

from mtg_analyzer.game.continuous import group_selector_objects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _FOR_EACH_SELECTORS, parse_effect_body
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


class TestIfGate:
    def test_a_leading_if_gates_the_effect(self) -> None:
        specs = parse_effect_body("if you control a creature, draw a card")
        assert specs is not None
        assert [s.type for s in specs] == ["draw"]
        assert specs[0].condition == {
            "kind": "control_count", "selector": "creatures_you_control", "min": 1,
        }

    def test_a_trailing_if_gates_it_too(self) -> None:
        specs = parse_effect_body("draw a card if you control a creature")
        assert specs is not None
        assert specs[0].condition == {
            "kind": "control_count", "selector": "creatures_you_control", "min": 1,
        }

    def test_an_unrecognised_condition_fails_closed(self) -> None:
        # The whole point of the fail-closed guard in `_peel_condition`:
        # emitting the effect without its gate is a *wrong* card, which is
        # strictly worse than an unmodeled one.
        assert parse_effect_body("if the moon is blue, draw a card") is None

    def test_unless_is_the_same_gate_negated(self) -> None:
        specs = parse_effect_body("draw a card unless you control a creature")
        assert specs is not None
        assert specs[0].condition == {
            "kind": "not",
            "condition": {
                "kind": "control_count", "selector": "creatures_you_control", "min": 1,
            },
        }


class TestIfOtherwise:
    def test_it_becomes_an_if_else_node(self) -> None:
        specs = parse_effect_body(
            "if you control a creature, draw a card. otherwise, you gain 1 life"
        )
        assert specs is not None
        assert [s.type for s in specs] == ["if_else"]
        params = specs[0].params
        assert params["then"] == [{"type": "draw", "params": {"count": 1}}]
        assert params["else"] == [{"type": "gain_life", "params": {"amount": 1}}]

    def test_it_wins_over_the_connector_split(self) -> None:
        # Regression pin for a wrong reading this ticket would otherwise have
        # created. The split hands "otherwise, <B>" over on its own, and a
        # standing `_CONDITION_PREFIXES` row reads a bare leading "otherwise,"
        # as RULE 701.30d's *clash* condition — the only meaning that word had
        # before. Left to the split, this card's else branch would be gated on
        # "you didn't win a clash", which has nothing to do with it.
        specs = parse_effect_body(
            "if you control a creature, draw a card. otherwise, you gain 1 life"
        )
        assert specs is not None and len(specs) == 1
        assert specs[0].type == "if_else"

    def test_a_real_clash_body_keeps_its_own_grammar(self) -> None:
        # The rule is anchored on a leading "if", so a clash card never
        # reaches it.
        specs = parse_effect_body("clash with an opponent. if you win, draw a card")
        assert specs is not None
        assert [s.type for s in specs] == ["clash", "draw"]

    def test_an_unrecognised_condition_fails_closed(self) -> None:
        assert parse_effect_body(
            "if the moon is blue, draw a card. otherwise, you gain 1 life"
        ) is None


class TestForEach:
    def test_it_becomes_a_for_each_node(self) -> None:
        specs = parse_effect_body("you gain 1 life for each creature you control")
        assert specs is not None
        assert [s.type for s in specs] == ["for_each"]
        assert specs[0].params["over"] == {"selector": "creatures_you_control"}
        assert specs[0].params["effects"] == [
            {"type": "gain_life", "params": {"amount": 1}}
        ]

    def test_a_targeted_body_fails_closed(self) -> None:
        # `ForEachEffect` hands each selected object to the body *as its
        # targets*, which would override the announced RULE 115 target with
        # the iteration item — a wrong reading, so it is refused.
        assert parse_effect_body(
            "deal 1 damage to target creature for each creature you control"
        ) is None

    def test_a_count_operand_is_not_an_iteration(self) -> None:
        # "for each card in your hand" is an *amount*
        # (`game/effect_amounts.py`), not a battlefield group — iterating over
        # a non-group would resolve to nothing at all while the card still
        # counted as MODELED. It routes to `bind` instead; the point pinned
        # here is that it must never become a `for_each`.
        specs = parse_effect_body("you gain 1 life for each card in your hand")
        assert specs is not None
        assert [s.type for s in specs] == ["bind"]

    @pytest.mark.parametrize("selector", sorted(set(_FOR_EACH_SELECTORS.values())))
    def test_every_emitted_selector_is_real(self, selector: str) -> None:
        """The parser may not import ``game/`` (docs/09), so nothing in it can
        check these names against the engine's vocabulary — and an unknown one
        fails closed *inside* the node, i.e. a MODELED card that does nothing.
        This test is the boundary crossing, done once, here.

        Asserted by *finding something*, not merely by not raising: an unknown
        selector also returns an empty list, so an emptiness check would pass
        for a typo and prove nothing.
        """
        eng = GameEngine.new_game(
            [("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=0
        )
        for card in (
            Card(id="c", name="Bear", type_line="Legendary Creature - Bear",
                 is_creature=True, power=2, toughness=2, is_legendary=True),
            Card(id="a", name="Rock", type_line="Artifact"),
            Card(id="l", name="Waste", type_line="Land", is_land=True),
        ):
            obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
            obj.summoning_sick = False
            eng.state.add_to_battlefield(obj)

        found = group_selector_objects(eng.state, "p1", selector)
        if selector == "attacking_creatures":
            # Nothing is attacking outside combat; the name itself is still
            # proven real by the vocabulary check below.
            assert found == []
            assert f'"{selector}"' in inspect.getsource(group_selector_objects)
        else:
            assert found, f"{selector!r} matched nothing on a board that has one"


@pytest.mark.full_cache
class TestRealCards:
    @staticmethod
    def _card(name: str) -> Card:
        card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
        if card is None:
            pytest.skip(f"{name!r} not in the local card cache")
        return card

    def test_beastbond_outcaster_keeps_its_intervening_if(self) -> None:
        # "When this creature enters, if you control a creature with power 4
        # or greater, draw a card." — the gate must reach the effect, or the
        # card draws unconditionally.
        result = parse_oracle(self._card("Beastbond Outcaster"))
        assert result.modeled, result.unclaimed
        draws = [e for spec in result.specs for e in spec.effects if e.type == "draw"]
        assert draws and draws[0].condition == {
            "kind": "control_count", "selector": "creatures_you_control",
            "min": 1, "min_power": 4,
        }

    def test_bloodhall_priest_keeps_its_intervening_if(self) -> None:
        result = parse_oracle(self._card("Bloodhall Priest"))
        assert result.modeled, result.unclaimed
        damage = [e for spec in result.specs for e in spec.effects if e.type == "damage"]
        assert damage and damage[0].condition == {
            "kind": "cards_in_hand_at_most", "amount": 0,
        }


class TestConditionWhitelistWidening:
    """PAR-62 added four rows to `static_handlers.static_condition`.

    They are asserted here rather than only in the static-ability tests
    because this is the shared whitelist: the same row now answers a RULE
    603.4 effect gate *and* a RULE 613.6 "as long as" static, which is the
    reason widening it was worth doing at all.
    """

    @pytest.mark.parametrize("phrase,expected", [
        ("a creature died this turn", {"kind": "creatures_died_this_turn", "min": 1}),
        ("you gained life this turn", {"kind": "gained_life_this_turn"}),
        ("an opponent lost life this turn",
         {"kind": "opponent_lost_life_this_turn", "min": 1}),
        ("~ is an enchantment",
         {"kind": "is_card_type", "card_type": "enchantment"}),
    ])
    def test_the_new_rows_resolve(self, phrase: str, expected: dict) -> None:
        from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition

        assert static_condition(phrase) == expected

    def test_they_did_not_shadow_the_existing_rows(self) -> None:
        # The new rows are prepended, so the ones they sit in front of are the
        # ones at risk — "~ is untapped" must not be eaten by the new
        # "~ is a/an <type>" row.
        from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition

        assert static_condition("~ is untapped") == {"kind": "source_untapped"}
        assert static_condition("~ is tapped") == {"kind": "source_tapped"}

    def test_the_gate_now_reaches_them(self) -> None:
        specs = parse_effect_body("if a creature died this turn, draw a card")
        assert specs is not None
        assert specs[0].condition == {"kind": "creatures_died_this_turn", "min": 1}


class TestForEachQuantity:
    def test_a_quantity_operand_becomes_a_bind_node(self) -> None:
        # "for each card in your hand" is measured once and handed to the
        # body (ENG-37's `bind`), not iterated over.
        specs = parse_effect_body("you gain 1 life for each card in your hand")
        assert specs is not None
        assert [s.type for s in specs] == ["bind"]
        params = specs[0].params
        assert params["amount"] == {"kind": "resource", "resource": "hand_size"}
        assert params["effects"] == [
            {"type": "gain_life", "params": {"amount": "$n"}}
        ]

    def test_an_unmeasurable_quantity_fails_closed(self) -> None:
        # No `effect_amounts` kind reads counters on a permanent yet, so this
        # must stay unclaimed rather than bind to something wrong.
        assert parse_effect_body(
            "you gain 1 life for each +1/+1 counter on it"
        ) is None


class TestInsteadReplacementRider:
    """RULE 614 "…instead" detected in an effect body and tied to the engine's
    existing replacement primitive (`grant_die_to_exile_this_turn`) — not to a
    composition node, which would be a wrong reading."""

    def test_the_or_planeswalker_spelling_is_claimed(self) -> None:
        specs = parse_effect_body(
            "~ deals 4 damage to target creature or planeswalker. "
            "if that creature or planeswalker would die this turn, exile it instead"
        )
        assert specs is not None
        assert [s.type for s in specs] == ["damage", "grant_die_to_exile_this_turn"]

    def test_mass_damage_fails_closed(self) -> None:
        # "deals 3 damage to each creature" announces no target, so
        # `previous_subject` would arm the replacement on nobody. Refusing is
        # correct until a group-scoped arm exists.
        assert parse_effect_body(
            "~ deals 3 damage to each creature. "
            "if a creature dealt damage this way would die this turn, exile it instead"
        ) is None
