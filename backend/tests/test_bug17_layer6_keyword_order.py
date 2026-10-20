"""BUG-17: layer-6 ability grants/removals apply in timestamp order (RULE 613.7).

A "loses all abilities" effect (Humility) removes only what was printed or
granted *before* it; a later-timestamp grant adds back (RULE 613.7f)."""

from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effects.core import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _put(eng, name, creature=True, keywords=None, controller="p1"):
    card = Card(id=name, name=name,
                type_line="Creature — Bear" if creature else "Enchantment",
                is_creature=creature, power=2 if creature else None,
                toughness=2 if creature else None, keywords=keywords or [])
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if keywords:
        obj.intrinsic_keywords = {k.lower() for k in keywords}
    eng.state.add_to_battlefield(obj)  # assigns the timestamp (entry order)
    return obj


def _static(source, params):
    ab = StaticAbility("ability", affects="all_creatures", params=params, source=source)
    source.static_effects.append(ab)


def _flying(obj):
    continuous.recompute(_STATE[0])
    return combat.has(obj, "flying")


_STATE: list = []


def _setup():
    eng = _engine()
    _STATE[:] = [eng.state]
    return eng


def test_humility_then_newer_flying_grant_keeps_flying():
    eng = _setup()
    bear = _put(eng, "Bear")
    _static(_put(eng, "Humility", creature=False), {"lose_all_abilities": True})
    _static(_put(eng, "Grant", creature=False), {"keywords": ["flying"]})
    assert _flying(bear)
    assert "flying" in combat._obj_keywords(bear)
    assert bear.loses_all_abilities  # printed/triggered abilities stay suppressed


def test_flying_grant_then_newer_humility_removes_it():
    eng = _setup()
    bear = _put(eng, "Bear")
    _static(_put(eng, "Grant", creature=False), {"keywords": ["flying"]})
    _static(_put(eng, "Humility", creature=False), {"lose_all_abilities": True})
    assert not _flying(bear)


def test_printed_flying_dies_to_humility_even_with_later_other_grant():
    eng = _setup()
    angel = _put(eng, "Angel", keywords=["Flying"])
    _static(_put(eng, "Humility", creature=False), {"lose_all_abilities": True})
    assert not _flying(angel)
    _static(_put(eng, "Grant", creature=False), {"keywords": ["haste"]})
    continuous.recompute(eng.state)
    assert combat.has(angel, "haste") and not combat.has(angel, "flying")


def test_specific_loses_flying_after_grant():
    eng = _setup()
    bear = _put(eng, "Bear")
    _static(_put(eng, "Grant", creature=False), {"keywords": ["flying"]})
    _static(_put(eng, "Frost", creature=False), {"remove_keywords": ["flying"]})
    assert not _flying(bear)


def test_until_eot_grant_after_humility_survives():
    eng = _setup()
    bear = _put(eng, "Bear")
    _static(_put(eng, "Humility", creature=False), {"lose_all_abilities": True})
    bear.temp_keywords.add("flying")
    assert _flying(bear)
