"""PAR-17: a triggered ability's own "if it was kicked, `<effect>`." gate
(Heartstabber Mosquito/Citanul Woodreaders/Josu Vess, Lich Knight-shaped) —
the same RULE 702.33b idea `_KICKED_CONDITION_RE`/`ConditionalEffect`
already modeled for a *spell's* own resolve-time effect list (Vastwood
Surge-shaped "if **this spell** was kicked, …"), now also recognizing "if
**it** was kicked, …" for a triggered ability's body, plus two siblings
found/requested in the same pass:

* "if it was kicked **twice**, `<effect>`." (RULE 702.34a Multikicker's own
  count threshold — Archangel of Wrath) — a new `kicked_at_least` condition.
* "if `<this spell|it>` was **bargained**, `<effect>`." (RULE 701.x) — the
  engine (`ConditionalEffect._condition_holds`) has supported this key
  since the cEDH-cube batch, but no oracle-text recognizer ever reached it.

And, since an "X" inside a kicked-wrapper's own rest clause can only mean
Kicker's own announced ``{X}`` (PAR-7's `GameObject.kicker_x_paid`), never
the spell's own `x_paid` — a `"kicker_x"` sentinel `RulesEngine.
_substitute_x` now also resolves, unwrapping through a `ConditionalEffect`
to reach it (Kangee, Aerie Keeper/Verdeloth the Ancient-shaped; both real
cards stay UNMODELED today on an unrelated, pre-existing `add_counters`/
`create_token` gap that doesn't yet accept "X" or a named counter type —
this suite verifies the *rewrite mechanism* itself against a supported
effect body instead).

Reference: mtg_analyzer/parser/oracle/{segmenter,spec}.py,
mtg_analyzer/game/{effects,rules/casting_mixin}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.effects.core import ConditionalEffect, DealDamageEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine():
    cards = [Card(id=f"Bear{i}", name=f"Bear{i}", type_line="Creature", is_creature=True)
             for i in range(6)]
    return GameEngine.new_game([("p1", "Alice", cards), ("p2", "Bob", list(cards))],
                                starting_life=20, starting_hand=0)


# ---------------------------------------------------------------------------
# PARSER: the widened wrapper — "this spell"/"it", plain/"twice"/"bargained"
# ---------------------------------------------------------------------------


def test_this_spell_was_kicked_still_works():
    (spec,) = parse_effect_body("if this spell was kicked, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"kicked": True}


def test_it_was_kicked_is_now_recognized():
    (spec,) = parse_effect_body("if it was kicked, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"kicked": True}


def test_it_was_kicked_twice_maps_to_kicked_at_least_two():
    (spec,) = parse_effect_body("if it was kicked twice, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"kicked_at_least": 2}


def test_this_spell_was_bargained_is_now_recognized():
    (spec,) = parse_effect_body("if this spell was bargained, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"bargained": True}


def test_it_was_bargained_is_recognized_too():
    (spec,) = parse_effect_body("if it was bargained, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"bargained": True}


def test_kicked_wrapper_still_fails_closed_on_an_unrecognized_inner_clause():
    assert parse_effect_body("if it was kicked, it deals 4 damage instead") is None


def test_x_inside_a_kicked_wrapper_is_rewritten_to_the_kicker_x_sentinel():
    (spec,) = parse_effect_body("if it was kicked, draw x cards")
    assert spec.type == "draw"
    assert spec.params == {"count": "kicker_x"}
    assert spec.condition == {"kicked": True}


def test_x_inside_a_bargained_wrapper_is_not_rewritten():
    # Bargain has no "X" of its own to mean — only the kicked family gets
    # the rewrite.
    (spec,) = parse_effect_body("if it was bargained, draw x cards")
    assert spec.params == {"count": "x"}


# ---------------------------------------------------------------------------
# spec.py: the new 'kicked_at_least' condition key
# ---------------------------------------------------------------------------


def test_validate_accepts_kicked_at_least():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"kicked_at_least": 2})],
    )
    ability.validate()  # does not raise


def test_validate_rejects_non_int_kicked_at_least():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"kicked_at_least": "two"})],
    )
    try:
        ability.validate()
        assert False, "expected SpecValidationError"
    except SpecValidationError:
        pass


def test_validate_rejects_zero_kicked_at_least():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"kicked_at_least": 0})],
    )
    try:
        ability.validate()
        assert False, "expected SpecValidationError"
    except SpecValidationError:
        pass


# ---------------------------------------------------------------------------
# game/effects/core.py: ConditionalEffect's kicked_at_least gate
# ---------------------------------------------------------------------------


def _rules_context():
    p1 = Player(id="p1", life=20)
    state = GameState(players=[p1])
    engine = RulesEngine(state)
    return GameContext(state, engine), p1


def test_kicked_at_least_fires_when_kicker_count_meets_the_threshold():
    source = GameObject(Card(id="X", name="X", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK)
    source.kicker_count = 2
    ctx, p1 = _rules_context()
    wrapped = ConditionalEffect({"kicked_at_least": 2}, DealDamageEffect(amount=2, target_kind="player"), source=source)
    wrapped.apply(ctx, targets=[p1])
    assert p1.life == 18


def test_kicked_at_least_does_not_fire_below_the_threshold():
    source = GameObject(Card(id="X", name="X", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK)
    source.kicker_count = 1
    ctx, p1 = _rules_context()
    wrapped = ConditionalEffect({"kicked_at_least": 2}, DealDamageEffect(amount=2, target_kind="player"), source=source)
    wrapped.apply(ctx, targets=[p1])
    assert p1.life == 20


# ---------------------------------------------------------------------------
# END TO END: a real Archangel-of-Wrath-shaped card via GameEngine
# ---------------------------------------------------------------------------


def _multikicker_card():
    # RULE 702.34a Multikicker (a repeatable count, unlike Archangel of
    # Wrath's real "Kicker {B} and/or {R}" — two independently-priced
    # optional components, a different cost shape the plain integer
    # ``kicked=`` cast parameter doesn't model at all) — chosen so
    # ``kicked=2`` is the correct way to pay this cost twice, exercising
    # ``kicked_at_least`` against the mechanism it's actually built for.
    return Card(
        id="Test Multikicker Blast", name="Test Multikicker Blast", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{1}{U}", converted_mana_cost=2,
        oracle_text=(
            "Multikicker {1} (You may pay an additional {1} any number of "
            "times as you cast this spell.)\n"
            "You draw a card. If it was kicked twice, you gain 3 life."
        ),
        keywords=["Multikicker"],
    )


def test_multikicker_shaped_card_is_fully_modeled():
    result = parse_oracle(_multikicker_card())
    assert result.modeled, result.unclaimed


def _cast_multikicker(eng, p1, kicked):
    obj = GameObject(_multikicker_card(), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 1, "C": 1 + kicked})
    eng.cast_spell(p1, obj, kicked=kicked)
    eng.resolve_until_stable()
    return obj


def test_multikicker_unkicked_draws_but_does_not_gain_life():
    eng = _engine()
    p1 = eng.state.players[0]
    _cast_multikicker(eng, p1, kicked=0)
    assert p1.life == 20
    assert len(p1.hand) == 1  # the drawn card


def test_multikicker_kicked_once_still_does_not_meet_the_twice_threshold():
    eng = _engine()
    p1 = eng.state.players[0]
    _cast_multikicker(eng, p1, kicked=1)
    assert p1.life == 20


def test_multikicker_kicked_twice_gains_life():
    eng = _engine()
    p1 = eng.state.players[0]
    _cast_multikicker(eng, p1, kicked=2)
    assert p1.life == 23


# ---------------------------------------------------------------------------
# ENGINE: the kicker_x sentinel end to end (Kangee/Verdeloth-shaped, but
# using a supported effect body so the mechanism itself is isolated from
# the pre-existing, unrelated add_counters/create_token X-support gap)
# ---------------------------------------------------------------------------


def _kicker_x_draw_card():
    return Card(
        id="Test Kicker X Drawer", name="Test Kicker X Drawer", type_line="Creature — Test",
        mana_cost_string="{2}", converted_mana_cost=2, is_creature=True, power=1, toughness=1,
        oracle_text=(
            "Kicker {X} (You may pay an additional {X} as you cast this spell.)\n"
            "When this creature enters, if it was kicked, draw x cards."
        ),
        keywords=["Kicker"],
    )


def test_kicker_x_drawer_is_fully_modeled():
    result = parse_oracle(_kicker_x_draw_card())
    assert result.modeled, result.unclaimed


def test_kicker_x_drawer_draws_exactly_the_announced_x():
    library_cards = [Card(id=f"Lib{i}", name=f"Lib{i}", type_line="Land", is_land=True)
                      for i in range(10)]
    eng = GameEngine.new_game([("p1", "Alice", library_cards), ("p2", "Bob", [])],
                               starting_life=20, starting_hand=0)
    p1 = eng.state.players[0]
    card = _kicker_x_draw_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2, "W": 1, "U": 1, "B": 1})

    eng.cast_spell(p1, obj, kicked=1, kicker_x=3)
    eng.resolve_until_stable()

    # Creature left hand to the stack/battlefield, then 3 cards drawn back.
    assert len(p1.hand) == 3
    assert obj.kicker_x_paid == 3


def test_kicker_x_drawer_unkicked_draws_nothing():
    library_cards = [Card(id=f"Lib{i}", name=f"Lib{i}", type_line="Land", is_land=True)
                      for i in range(10)]
    eng = GameEngine.new_game([("p1", "Alice", library_cards), ("p2", "Bob", [])],
                               starting_life=20, starting_hand=0)
    p1 = eng.state.players[0]
    card = _kicker_x_draw_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 2})

    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    assert len(p1.hand) == 0
