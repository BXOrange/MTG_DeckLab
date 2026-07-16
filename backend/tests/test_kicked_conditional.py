"""Tests for RULE 702.33b's "If this spell was kicked, <effect>." (Batch
11's A.7 item) — a second, additional effect gated on `obj.kicker_count`,
via the new `EffectSpec.condition` field (parallel to `AbilitySpec.modes`)
and `game.effects.ConditionalEffect` (`game/effect_binder.py`'s
`build_effects` wraps any effect whose spec carries a `condition`).

Only the "additional effect when kicked" shape is modeled (Vastwood
Surge-shaped: a base effect, then a second sentence gated on kicked) — "if
kicked, it deals N damage *instead*" (overriding an *existing* effect's own
amount — Burst Lightning/Rite of Replication-shaped) is a different,
unmodeled grammar; see `parser/oracle/segmenter.py`'s `_KICKED_CONDITION_RE`
docstring.
"""

import pytest

from mtg_analyzer.game.effect_binder import attach_to_object
from mtg_analyzer.game.effects import ConditionalEffect, DrawCardEffect, GainLifeEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec, SpecValidationError


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True, oracle_text=oracle_text,
    )


def sorcery(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Sorcery", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_sorcery=True, oracle_text=oracle_text,
    )


# ---------------------------------------------------------------------------
# spec.py: EffectSpec.condition validation
# ---------------------------------------------------------------------------


def test_condition_dict_round_trips_through_to_dict_from_dict():
    spec = EffectSpec("draw", {"count": 1}, condition={"kicked": True})
    data = spec.to_dict()
    assert data["condition"] == {"kicked": True}
    restored = EffectSpec.from_dict(data)
    assert restored.condition == {"kicked": True}


def test_condition_omitted_when_none():
    assert "condition" not in EffectSpec("draw", {"count": 1}).to_dict()


def test_validate_rejects_unknown_condition_key():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"bogus": True})],
    )
    with pytest.raises(SpecValidationError):
        ability.validate()


def test_validate_rejects_non_bool_kicked_value():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"kicked": "yes"})],
    )
    with pytest.raises(SpecValidationError):
        ability.validate()


def test_validate_accepts_well_formed_kicked_condition():
    ability = AbilitySpec(
        "spell_effect",
        effects=[EffectSpec("draw", {"count": 1}, condition={"kicked": True})],
    )
    ability.validate()  # does not raise


# ---------------------------------------------------------------------------
# game/effects.py: ConditionalEffect
# ---------------------------------------------------------------------------


def test_conditional_effect_fires_when_kicked():
    source = GameObject(sorcery("X"), owner_id="p1", zone=Zone.STACK)
    source.kicker_count = 1
    inner = GainLifeEffect(amount=3)
    wrapped = ConditionalEffect({"kicked": True}, inner, source=source)

    from mtg_analyzer.game.effects import GameContext
    from mtg_analyzer.game.rules_engine import RulesEngine
    from mtg_analyzer.models.game_state import GameState
    from mtg_analyzer.models.player import Player

    p1 = Player(id="p1", life=20)
    state = GameState(players=[p1])
    engine = RulesEngine(state)
    ctx = GameContext(state, engine)

    wrapped.apply(ctx)
    assert p1.life == 23


def test_conditional_effect_does_not_fire_when_not_kicked():
    source = GameObject(sorcery("X"), owner_id="p1", zone=Zone.STACK)
    source.kicker_count = 0
    inner = GainLifeEffect(amount=3)
    wrapped = ConditionalEffect({"kicked": True}, inner, source=source)

    from mtg_analyzer.game.effects import GameContext
    from mtg_analyzer.game.rules_engine import RulesEngine
    from mtg_analyzer.models.game_state import GameState
    from mtg_analyzer.models.player import Player

    p1 = Player(id="p1", life=20)
    state = GameState(players=[p1])
    engine = RulesEngine(state)
    ctx = GameContext(state, engine)

    wrapped.apply(ctx)
    assert p1.life == 20  # untouched


def test_conditional_effect_target_spec_passes_through():
    from mtg_analyzer.game.effects import DestroyEffect

    inner = DestroyEffect()
    wrapped = ConditionalEffect({"kicked": True}, inner)
    assert wrapped.target_spec is inner.target_spec


# ---------------------------------------------------------------------------
# PARSER: "if this spell was kicked, <effect>." wrapper
# ---------------------------------------------------------------------------


def test_kicked_wrapper_tags_the_inner_effect_with_condition():
    (spec,) = parse_effect_body("if this spell was kicked, you gain 3 life")
    assert spec.type == "gain_life" and spec.condition == {"kicked": True}


def test_kicked_wrapper_fails_closed_on_an_unrecognized_inner_clause():
    # "it deals 4 damage instead" (Burst Lightning-shaped "instead" override)
    # has no target of its own and isn't a recognized standalone clause.
    assert parse_effect_body("if this spell was kicked, it deals 4 damage instead") is None


def test_kicked_wrapper_combines_with_a_base_effect_via_period_connector():
    specs = parse_effect_body(
        "you draw a card. if this spell was kicked, you gain 3 life"
    )
    assert specs is not None
    assert len(specs) == 2
    draw, gain = specs
    assert draw.type == "draw" and draw.condition is None
    assert gain.type == "gain_life" and gain.condition == {"kicked": True}


def test_add_counters_each_creature_you_control_selector_is_recognized():
    (spec,) = parse_effect_body("put 2 +1/+1 counters on each creature you control")
    assert spec.type == "add_counters"
    assert spec.params["selector"] == "each_creature_you_control"


# ---------------------------------------------------------------------------
# END TO END: a real Vastwood Surge-shaped card, via GameEngine
# ---------------------------------------------------------------------------


_VASTWOOD_TEXT = (
    "Kicker {4} (You may pay an additional {4} as you cast this spell.)\n"
    "Search your library for up to two basic land cards, put them onto the "
    "battlefield tapped, then shuffle. If this spell was kicked, put two "
    "+1/+1 counters on each creature you control."
)


def _vastwood_card():
    card = sorcery("Vastwood Surge", cost="{2}{G}", oracle_text=_VASTWOOD_TEXT)
    card.keywords = ["Kicker"]
    return card


def test_vastwood_surge_shaped_card_is_fully_modeled():
    r = parse_oracle(_vastwood_card())
    assert r.modeled
    (spell_effect,) = [s for s in r.specs if s.ability_kind == "spell_effect"]
    kinds = [(s.type, s.condition) for s in spell_effect.effects]
    assert kinds == [
        ("search", None),
        ("add_counters", {"kicked": True}),
    ]


def _make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2)


def test_unkicked_vastwood_surge_skips_the_counters():
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 1, "C": 2})
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    card = _vastwood_card()
    result = parse_oracle(card)
    assert result.modeled
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)

    # Bypass the interactive library-search choice: no basics in the deck,
    # so `request_search` resolves with nothing to find — only the kicked
    # gate matters here, not the search itself.
    eng.cast_spell(p1, obj, kicked=0)
    eng.resolve_until_stable()

    assert bear.counters.get("+1/+1", 0) == 0


def test_kicked_vastwood_surge_adds_the_counters():
    eng = _make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"G": 5, "C": 4})
    bear = GameObject(_bear(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.summoning_sick = False
    eng.state.add_to_battlefield(bear)

    card = _vastwood_card()
    result = parse_oracle(card)
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)

    eng.cast_spell(p1, obj, kicked=1)
    eng.resolve_until_stable()

    assert bear.counters.get("+1/+1", 0) == 2
