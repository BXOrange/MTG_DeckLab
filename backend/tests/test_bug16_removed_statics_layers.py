"""BUG-16: a static removed in layer 6 never starts applying in layers 7+ (RULE 613.6).

Humility + a Goblin lord: the lord loses its anthem before layer 7c begins, so
the other Goblin is 1/1, not 2/2. An effect that already began applying in an
earlier layer (a layer-4 animation carrying base P/T) keeps applying."""

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effects.core import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(eng, name, creature=True, power=2, toughness=2):
    card = Card(id=name, name=name,
                type_line="Creature — Goblin" if creature else "Enchantment",
                is_creature=creature, power=power if creature else None,
                toughness=toughness if creature else None)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _static(source, layer, affects, params):
    source.static_effects.append(StaticAbility(layer, affects=affects, params=params, source=source))


def _humility(eng):
    h = _put(eng, "Humility", creature=False)
    _static(h, "ability", "all_creatures", {"lose_all_abilities": True})
    _static(h, "pt_set", "all_creatures", {"power": 1, "toughness": 1})
    return h


def _lord(eng):
    lord = _put(eng, "Lord")
    _static(lord, "pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1})
    return lord


def _pt(eng, obj):
    continuous.recompute(eng.state)
    return obj.power, obj.toughness


def test_lord_anthem_without_humility():
    eng = _engine()
    _lord(eng)
    other = _put(eng, "Other")
    assert _pt(eng, other) == (3, 3)


@pytest.mark.parametrize("humility_first", [True, False])
def test_humility_removes_lord_anthem_in_either_timestamp_order(humility_first):
    eng = _engine()
    if humility_first:
        _humility(eng)
    lord = _lord(eng)
    other = _put(eng, "Other")
    if not humility_first:
        _humility(eng)
    assert _pt(eng, other) == (1, 1)
    assert _pt(eng, lord) == (1, 1)


def test_removal_is_not_stale_across_recomputes():
    eng = _engine()
    h = _humility(eng)
    _lord(eng)
    other = _put(eng, "Other")
    assert _pt(eng, other) == (1, 1)
    eng.state.battlefield.remove(h)
    assert _pt(eng, other) == (3, 3)


def test_effect_begun_in_layer_4_survives_ability_loss():
    # Opalescence-shaped: one ability animates (layer 4, base P/T 3/3); Humility's
    # layer-6 strip must not undo that, though it drops the source's layer-7 statics.
    eng = _engine()
    opal = _put(eng, "Opal", creature=False)
    _static(opal, "type", "self", {"add_types": ["creature"], "power": 3, "toughness": 3})
    _static(opal, "pt_mod", "self", {"power": 5, "toughness": 5})
    strip = _put(eng, "Strip", creature=False)
    _static(strip, "ability", "all_creatures", {"lose_all_abilities": True})
    continuous.recompute(eng.state)
    assert opal.is_creature and opal.loses_all_abilities
    assert (opal.power, opal.toughness) == (3, 3)  # base from layer 4; own 7d pump gone
