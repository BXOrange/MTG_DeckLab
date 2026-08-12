"""Tests for RULE 115.1a "up to one target" (Batch 11's A.2 item, the
"up to N" targets backlog entry, scoped to N=1 for the families covered
here). A real N>=2 multi-target choice (an interactive multi-select and
per-effect application over a list) has since shipped for `destroy`/
`exile`/`damage` — see `tests/test_multi_target.py` — and for
`return_from_graveyard`/`return_to_hand`/`tap`/`add_counters` too — see
`tests/test_multi_target_extended.py`. This file keeps the N=1 coverage for
all of them.

Mirrors `test_targeting.py`'s fixture pattern (locked/unlocked cast offers,
server-side `has_legal_targets` enforcement) plus
`test_effect_families_wave3.py`'s parser-recognition-then-engine-drive
split.
"""

from mtg_analyzer.game.effects import (
    AddCountersEffect,
    DealDamageEffect,
    DestroyEffect,
    ExileEffect,
    ReturnFromGraveyardEffect,
    ReturnToHandEffect,
    TapEffect,
)
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def instant(name, cost="{0}"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        is_instant=True,
    )


def creature(name="Grizzly Bears"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True,
                power=2, toughness=2)


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [instant("filler")] * 5), ("p2", "Bob", [instant("f")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def give_spell(eng, player, card, effects):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    obj.spell_effects = effects
    for e in effects:
        e.source = obj
    player.hand.append(obj)
    return obj


def cast_action_for(eng, player, obj):
    for a in eng.legal_actions(player):
        if a.get("type") == "cast_spell" and a["instance_id"] == obj.instance_id:
            return a
    return None


# ---------------------------------------------------------------------------
# PARSER RECOGNITION
# ---------------------------------------------------------------------------


def test_up_to_one_target_is_recognized_for_destroy_exile_tap_damage():
    cases = {
        "destroy up to one target creature": ("destroy", "creature"),
        "exile up to one target artifact": ("exile", "artifact"),
        "tap up to one target creature": ("tap", "creature"),
        "deals 3 damage to up to one target creature": ("damage", "creature"),
    }
    for clause, (effect_type, kind) in cases.items():
        specs = parse_effect_body(clause)
        assert specs is not None, clause
        (spec,) = specs
        assert spec.type == effect_type
        assert spec.params["target_kind"] == kind
        assert spec.params["optional"] is True


def test_bare_target_still_required_not_optional():
    (spec,) = parse_effect_body("destroy target creature")
    assert "optional" not in spec.params


def test_up_to_one_target_recognized_for_add_counters():
    (spec,) = parse_effect_body("put a +1/+1 counter on up to one target creature")
    assert spec.type == "add_counters" and spec.params["optional"] is True


def test_up_to_one_target_recognized_for_return_to_hand():
    (spec,) = parse_effect_body("return up to one target creature to its owner's hand")
    assert spec.type == "return_to_hand" and spec.params["optional"] is True


def test_up_to_one_target_recognized_for_return_from_graveyard():
    specs = parse_effect_body(
        "return up to one target creature card from your graveyard to the battlefield"
    )
    assert specs is not None
    (spec,) = specs
    assert spec.type == "return_from_graveyard" and spec.params["optional"] is True


def test_up_to_2_targets_for_destroy_now_recognized():
    # N>=2 has since shipped for destroy/exile/damage — see
    # tests/test_multi_target.py for the full coverage of this family.
    (spec,) = parse_effect_body("destroy up to 2 target creatures")
    assert spec.type == "destroy"
    assert spec.params == {"target_kind": "creature", "count": 2, "optional": True}


def test_up_to_2_targets_now_recognized_for_return_to_hand():
    # N>=2 has since shipped for return_to_hand too — see
    # tests/test_multi_target_extended.py for the full coverage. Note the
    # plural possessive ("their owners' hands") — the singular "its owner's
    # hand" phrasing above stays N=1-only, as it should.
    (spec,) = parse_effect_body("return up to 2 target creatures to their owners' hands")
    assert spec.type == "return_to_hand"
    assert spec.params == {"target_kind": "creature", "count": 2, "optional": True}


# ---------------------------------------------------------------------------
# EFFECT CLASSES: optional propagates to TargetSpec
# ---------------------------------------------------------------------------


def test_optional_flag_reaches_target_spec_on_every_threaded_effect():
    assert DestroyEffect(optional=True).target_spec.optional is True
    assert ExileEffect(optional=True).target_spec.optional is True
    assert TapEffect(optional=True).target_spec.optional is True
    assert ReturnToHandEffect(optional=True).target_spec.optional is True
    assert DealDamageEffect(3, optional=True).target_spec.optional is True
    assert AddCountersEffect(target_kind="creature", optional=True).target_spec.optional is True
    assert (
        ReturnFromGraveyardEffect(target_kind="graveyard_creature", optional=True)
        .target_spec.optional is True
    )
    # Default stays required, unaffected.
    assert DestroyEffect().target_spec.optional is False


# ---------------------------------------------------------------------------
# ENGINE: an optional target never locks casting, and declining is a legal no-op
# ---------------------------------------------------------------------------


def test_optional_destroy_is_never_locked_even_with_an_empty_board():
    eng, p1, _ = two_player_engine()
    obj = give_spell(eng, p1, instant("Maybe Murder"), [DestroyEffect(optional=True)])
    action = cast_action_for(eng, p1, obj)
    assert action.get("requires_target") is True
    assert action.get("locked") is None
    assert eng.has_legal_targets(p1, obj)


def test_declining_the_optional_target_resolves_as_a_no_op():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Maybe Murder"), [DestroyEffect(optional=True)])
    eng.cast_spell(p1, obj, targets=None)  # no target chosen — legal
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.BATTLEFIELD  # untouched


def test_choosing_the_optional_target_still_applies():
    eng, p1, p2 = two_player_engine()
    bear = GameObject(creature("Bear"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(bear)
    obj = give_spell(eng, p1, instant("Maybe Murder"), [DestroyEffect(optional=True)])
    eng.cast_spell(p1, obj, targets=[bear])
    eng.rules.resolve_top_of_stack()
    assert bear.zone == Zone.GRAVEYARD
