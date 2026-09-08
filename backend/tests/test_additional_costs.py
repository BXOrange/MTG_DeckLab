"""Tests for RULE 601.2b/604's "as an additional cost to cast this spell, …".

Covers all three layers: the IR (`parser/oracle/spec.py`'s `additional_cost`
field), the parser (`parser/oracle/segmenter.py` claiming the closed
vocabulary of cost shapes), and the engine (`game/game_engine.py` gating
legality and paying the cost as part of casting, RULE 601.2h).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md, mtg_analyzer/game/costs.py.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.costs import PAY_LIFE_X, parse_activation_cost
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import AbilitySpec, SpecValidationError


# ---------------------------------------------------------------------------
# Card factories (mirrors tests/test_game_engine.py's conventions)
# ---------------------------------------------------------------------------


def creature(name="Fodder", cost="{1}{G}", power=1, toughness=1, **kw):
    return Card(
        id=name,
        name=name,
        type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        **kw,
    )


def sorcery(name, cost, oracle_text):
    return Card(
        id=name,
        name=name,
        type_line="Sorcery",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_sorcery=True,
        oracle_text=oracle_text,
    )


def instant(name, cost, oracle_text):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
        oracle_text=oracle_text,
    )


def make_engine(p1_cards, p2_cards=None, life=20, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=life, starting_hand=hand)


def obj_on_battlefield(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Parser: the closed vocabulary of additional-cost shapes
# ---------------------------------------------------------------------------


class TestParserClaims:
    def _parse(self, oracle_text, is_instant=False):
        card = sorcery("Test", "{1}{B}", oracle_text) if not is_instant \
            else instant("Test", "{1}{B}", oracle_text)
        return parse_oracle(card)

    def test_sacrifice_a_creature_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, sacrifice a creature.\n"
            "Destroy target creature."
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"sacrifice": "creature"}

    def test_sacrifice_an_artifact_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, sacrifice an artifact.\n"
            "Draw a card."
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"sacrifice": "artifact"}

    def test_sacrifice_a_land_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, sacrifice a land.\n"
            "Draw a card."
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"sacrifice": "land"}

    def test_discard_a_card_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, discard a card.\n"
            "Draw two cards."
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"discard": 1}

    def test_pay_n_life_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, pay 2 life.\n"
            "Draw a card."
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"pay_life": 2}

    def test_pay_x_life_claimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, pay X life.\n"
            "Draw a card.",
            is_instant=True,
        )
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"pay_life": "x"}

    def test_unknown_sacrifice_count_unclaimed(self):
        # Outside the closed vocabulary (a count, not "a"/"an") — fail-closed.
        result = self._parse(
            "As an additional cost to cast this spell, sacrifice two creatures.\n"
            "Destroy target creature."
        )
        assert not result.modeled
        assert any("additional cost" in line for line in result.unclaimed)

    def test_discard_your_hand_unclaimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, discard your hand.\n"
            "Draw seven cards."
        )
        assert not result.modeled

    def test_sacrifice_a_permanent_unclaimed(self):
        # "permanent"/"enchantment" aren't in the closed vocabulary the
        # actual card pool needs — fail-closed rather than guessed.
        result = self._parse(
            "As an additional cost to cast this spell, sacrifice a permanent.\n"
            "Draw a card."
        )
        assert not result.modeled

    def test_pay_mana_unclaimed(self):
        result = self._parse(
            "As an additional cost to cast this spell, pay 3 mana.\n"
            "Draw a card."
        )
        assert not result.modeled

    def test_permanent_claims_recognized_additional_cost_line(self):
        # RULE 601.2b additional costs apply to *any* spell, creature spells
        # included — real cards print this (Demon of Catastrophes, Kinsbaile
        # Aspirant, Lys Alana Dignitary). The "as an additional cost to cast
        # this spell," wrapper is unambiguous, so it's recognized regardless
        # of card type (PAR-29 Behold ungated it).
        card = Card(
            id="Permanent Test",
            name="Permanent Test",
            type_line="Creature — Bear",
            mana_cost_string="{1}{G}",
            converted_mana_cost=2,
            is_creature=True,
            power=1,
            toughness=1,
            oracle_text="As an additional cost to cast this spell, sacrifice a creature.",
        )
        result = parse_oracle(card)
        assert result.modeled, result.unclaimed
        cost_spec = next(s for s in result.specs if s.additional_cost)
        assert cost_spec.additional_cost == {"sacrifice": "creature"}

    def test_permanent_still_fails_closed_on_unrecognized_additional_cost(self):
        # Ungating the wrapper doesn't widen the closed cost vocabulary: a
        # permanent with an out-of-vocabulary additional cost is still
        # UNMODELED, exactly as a sorcery would be.
        card = Card(
            id="Permanent Test 2",
            name="Permanent Test 2",
            type_line="Creature — Bear",
            mana_cost_string="{1}{G}",
            converted_mana_cost=2,
            is_creature=True,
            power=1,
            toughness=1,
            oracle_text="As an additional cost to cast this spell, sacrifice two creatures.",
        )
        result = parse_oracle(card)
        assert not result.modeled


# ---------------------------------------------------------------------------
# Spec IR: validation + round-trip
# ---------------------------------------------------------------------------


class TestAbilitySpecAdditionalCost:
    def test_round_trip(self):
        spec = AbilitySpec(
            "spell_effect", effects=[], additional_cost={"sacrifice": "creature"},
            raw_text="as an additional cost to cast this spell, sacrifice a creature.",
        )
        spec.validate()
        data = spec.to_dict()
        restored = AbilitySpec.from_dict(data)
        assert restored.additional_cost == {"sacrifice": "creature"}
        restored.validate()

    def test_rejects_non_spell_effect_kind(self):
        spec = AbilitySpec(
            "triggered",
            effects=[],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            additional_cost={"sacrifice": "creature"},
        )
        with pytest.raises(SpecValidationError):
            spec.validate()

    def test_rejects_unknown_cost_key(self):
        spec = AbilitySpec("spell_effect", effects=[], additional_cost={"exile": 1})
        with pytest.raises(SpecValidationError):
            spec.validate()

    def test_rejects_unknown_sacrifice_type(self):
        spec = AbilitySpec("spell_effect", effects=[], additional_cost={"sacrifice": "permanent"})
        with pytest.raises(SpecValidationError):
            spec.validate()

    def test_empty_effects_allowed_when_additional_cost_set(self):
        # A standalone additional-cost-only spec (no effects, no modes) must
        # not trip the "effect-bearing kind needs an effect" check.
        spec = AbilitySpec("spell_effect", effects=[], additional_cost={"discard": 1})
        spec.validate()  # must not raise


class TestActivationCostReuse:
    """`additional_cost` dicts feed `costs.parse_activation_cost` directly —
    the same charging model an activated ability's cost uses."""

    def test_sacrifice_dict(self):
        cost = parse_activation_cost({"sacrifice": "creature"})
        assert cost.sacrifice == "creature"
        assert not cost.is_free

    def test_discard_dict(self):
        cost = parse_activation_cost({"discard": 1})
        assert cost.discard == 1

    def test_pay_life_dict(self):
        cost = parse_activation_cost({"pay_life": 2})
        assert cost.pay_life == 2

    def test_pay_life_x_dict(self):
        cost = parse_activation_cost({"pay_life": "x"})
        assert cost.pay_life == PAY_LIFE_X
        assert "Pay X life" in cost.label()


# ---------------------------------------------------------------------------
# Engine: legality + payment (RULE 601.2b/601.2h)
# ---------------------------------------------------------------------------


class TestSacrificeAdditionalCost:
    CARD_TEXT = (
        "As an additional cost to cast this spell, sacrifice a creature.\n"
        "Destroy target creature."
    )

    def _setup(self, with_fodder=True):
        card = sorcery("Bone Splinters Test", "{1}{B}", self.CARD_TEXT)
        eng = make_engine([card], [creature(name="Victim")], hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p2 = eng.state.players[1]
        p1.mana_pool.add_many({"B": 1, "C": 1})
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        target = obj_on_battlefield(eng.state, creature(name="Victim"), controller="p2")
        fodder = None
        if with_fodder:
            fodder = obj_on_battlefield(eng.state, creature(name="Fodder"), controller="p1")
        return eng, p1, spell, target, fodder

    def test_cast_illegal_without_a_creature_to_sacrifice(self):
        eng, p1, spell, target, _ = self._setup(with_fodder=False)
        assert not eng.can_cast(p1, spell)
        with pytest.raises(ValueError):
            eng.cast_spell(p1, spell, targets=[target])

    def test_cast_pays_sacrifice_immediately(self):
        eng, p1, spell, target, fodder = self._setup()
        assert eng.can_cast(p1, spell)
        eng.cast_spell(p1, spell, targets=[target])
        # Paid as part of casting (RULE 601.2h) — already gone before the
        # spell has even resolved.
        assert fodder not in eng.state.battlefield
        assert fodder in p1.graveyard
        assert eng.state.stack and eng.state.stack[-1].obj is spell

    def test_sacrifice_stays_paid_if_spell_is_countered(self):
        eng, p1, spell, target, fodder = self._setup()
        eng.cast_spell(p1, spell, targets=[target])
        assert fodder in p1.graveyard
        eng.rules.counter_spell(spell)
        # RULE 601.2h: the cost is never refunded, whatever happens to the spell.
        assert fodder in p1.graveyard
        assert target in eng.state.battlefield  # the destroy effect never resolved

    def test_resolving_destroys_the_target_and_sacrifices_the_fodder(self):
        eng, p1, spell, target, fodder = self._setup()
        eng.cast_spell(p1, spell, targets=[target])
        eng.resolve_until_stable()
        assert fodder in p1.graveyard
        p2 = eng.state.players[1]
        assert target in p2.graveyard
        assert target not in eng.state.battlefield


class TestDiscardAdditionalCost:
    CARD_TEXT = (
        "As an additional cost to cast this spell, discard a card.\n"
        "Draw two cards."
    )

    def _setup(self, extra_cards=1):
        card = sorcery("Altar's Reap Test", "{1}{U}", self.CARD_TEXT)
        # Extra library cards so "Draw two cards." has something to draw
        # from after the opening hand is dealt. `draw()` takes from the end
        # of the list (top of library), so the spell itself goes last.
        library = [creature(name=f"Library {i}") for i in range(3)] + [card]
        eng = make_engine(library, hand=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p1.mana_pool.add_many({"U": 1, "C": 1})
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        extras = []
        for i in range(extra_cards):
            filler = GameObject(creature(name=f"Filler {i}"), owner_id="p1", zone=Zone.HAND)
            p1.hand.append(filler)
            extras.append(filler)
        return eng, p1, spell, extras

    def test_cast_illegal_with_no_other_card_to_discard(self):
        eng, p1, spell, _ = self._setup(extra_cards=0)
        assert not eng.can_cast(p1, spell)
        with pytest.raises(ValueError):
            eng.cast_spell(p1, spell)

    def test_cast_consumes_a_chosen_card_and_draws_two(self):
        eng, p1, spell, extras = self._setup(extra_cards=1)
        before_library = len(p1.library)
        assert eng.can_cast(p1, spell)
        eng.cast_spell(p1, spell)
        # The filler card is gone from hand, discarded as the cost — before
        # the spell has even resolved (RULE 601.2h).
        assert extras[0] not in p1.hand
        assert extras[0] in p1.graveyard
        eng.resolve_until_stable()
        assert len(p1.library) == before_library - 2  # drew two cards
        assert len(p1.hand) == 2  # filler discarded, spell resolved, drew 2


class TestPayLifeAdditionalCost:
    FIXED_TEXT = (
        "As an additional cost to cast this spell, pay 2 life.\n"
        "Draw a card."
    )
    X_TEXT = (
        "As an additional cost to cast this spell, pay X life.\n"
        "Draw a card."
    )

    def test_cast_illegal_without_enough_life(self):
        card = sorcery("Fixed Life Test", "{1}{B}", self.FIXED_TEXT)
        eng = make_engine([card], hand=1, life=1)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p1.mana_pool.add_many({"B": 1, "C": 1})
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        assert not eng.can_cast(p1, spell)
        with pytest.raises(ValueError):
            eng.cast_spell(p1, spell)

    def test_cast_deducts_fixed_life(self):
        card = sorcery("Fixed Life Test", "{1}{B}", self.FIXED_TEXT)
        eng = make_engine([card], hand=1, life=20)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p1.mana_pool.add_many({"B": 1, "C": 1})
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        eng.cast_spell(p1, spell)
        assert p1.life == 18  # paid immediately, before resolution

    def test_cast_deducts_announced_x_life(self):
        card = instant("Pay X Life Test", "{X}{U}", self.X_TEXT)
        eng = make_engine([card], hand=1, life=20)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p1.mana_pool.add_many({"U": 1, "C": 3})
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        assert eng.can_cast(p1, spell, x=3)
        eng.cast_spell(p1, spell, x=3)
        assert p1.life == 17  # 20 - 3 announced X, mana paid separately
        assert eng.state.stack[-1].x == 3

    def test_x_life_not_charged_when_x_is_zero(self):
        card = instant("Pay X Life Test", "{X}{U}", self.X_TEXT)
        eng = make_engine([card], hand=1, life=20)
        eng.begin_turn()
        eng.state.current_step = "main1"
        p1 = eng.state.active_player
        p1.mana_pool.add("U", 1)
        spell = p1.hand[0]
        bind_from_catalogue(spell)
        eng.cast_spell(p1, spell)  # defaults to x=0
        assert p1.life == 20
