"""BUG-15: effects in one layer apply in dependency order (RULE 613.8).

Blood Moon vs. Urborg (a nonbasic land whose own grant ceases once Blood Moon
makes it a Mountain), a non-land same-layer dependency (an effect that changes
what another applies to), and a dependency loop falling back to timestamps."""

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


def _put(eng, name, type_line, **kw):
    card = Card(id=name, name=name, type_line=type_line, **kw)
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _land(eng, name):
    return _put(eng, name, "Land", is_land=True)


def _static(source, layer, affects, params):
    source.static_effects.append(StaticAbility(layer, affects=affects, params=params, source=source))


def _recompute(eng):
    continuous.recompute(eng.state)


@pytest.mark.parametrize("moon_first", [True, False])
def test_blood_moon_suppresses_urborg_in_either_order(moon_first):
    eng = _engine()

    def moon():
        m = _put(eng, "Moon", "Enchantment")
        _static(m, "type", "all_lands", {"set_subtypes": ["Mountain"], "nonbasic": True})

    def urborg():
        u = _land(eng, "Urborg")
        _static(u, "type", "all_lands", {"add_subtypes": ["Swamp"]})
        return u

    if moon_first:
        moon()
        u = urborg()
    else:
        u = urborg()
        moon()
    other = _land(eng, "Other Land")
    _recompute(eng)
    assert continuous.has_subtype(other, "Mountain")
    assert not continuous.has_subtype(other, "Swamp")
    assert continuous.has_subtype(u, "Mountain")
    assert not continuous.has_subtype(u, "Swamp")


def test_urborg_still_applies_without_blood_moon():
    eng = _engine()
    u = _land(eng, "Urborg")
    _static(u, "type", "all_lands", {"add_subtypes": ["Swamp"]})
    other = _land(eng, "Other Land")
    _recompute(eng)
    assert continuous.has_subtype(other, "Swamp")


@pytest.mark.parametrize("animator_newer", [True, False])
def test_effect_changing_what_another_applies_to_goes_first(animator_newer):
    # Non-land dependency: "creatures are Zombies in addition" depends on an
    # effect that makes the Gizmo a creature (RULE 613.8a: changes what it applies to).
    eng = _engine()
    gizmo = None

    def zombie_lord():
        z = _put(eng, "Necro", "Enchantment")
        _static(z, "type", "all_creatures", {"add_subtypes": ["Zombie"]})

    def animate():
        nonlocal gizmo
        gizmo = _put(eng, "Gizmo", "Artifact")
        _static(gizmo, "type", "self", {"add_types": ["creature"]})

    if animator_newer:
        zombie_lord()
        animate()
    else:
        animate()
        zombie_lord()
    _recompute(eng)
    assert gizmo.is_creature
    assert continuous.has_subtype(gizmo, "Zombie")


@pytest.mark.parametrize("plains_first", [True, False])
def test_dependency_loop_falls_back_to_timestamp_order(plains_first):
    # Each land's overwrite strips the other land's ability: a loop (RULE 613.8b),
    # so timestamp order decides -- the older effect applies, the newer one ceased.
    eng = _engine()
    first = _land(eng, "First")
    second = _land(eng, "Second")
    _static(first, "type", "all_lands", {"set_subtypes": ["Plains" if plains_first else "Island"]})
    _static(second, "type", "all_lands", {"set_subtypes": ["Island" if plains_first else "Plains"]})
    third = _land(eng, "Third")
    _recompute(eng)
    winner, loser = ("Plains", "Island") if plains_first else ("Island", "Plains")
    assert continuous.has_subtype(third, winner)
    assert not continuous.has_subtype(third, loser)


def test_probe_leaves_no_animation_pt_behind(monkeypatch):
    # An animating manland (layer 4, base P/T 3/3) is stripped by Blood Moon.
    # Probing "does Blood Moon depend on the manland?" tentatively applies the
    # animation; that scratch write must not survive into layer 7.
    eng = _engine()
    seen = {}
    real = continuous._apply_layer_7_pt

    def spy(state, abilities, animation_pt):
        seen.update(animation_pt)
        return real(state, abilities, animation_pt)

    monkeypatch.setattr(continuous, "_apply_layer_7_pt", spy)
    manland = _land(eng, "Manland")
    _static(manland, "type", "self", {"add_types": ["creature"], "power": 3, "toughness": 3})
    moon = _put(eng, "Moon", "Enchantment")
    _static(moon, "type", "all_lands", {"set_subtypes": ["Mountain"], "nonbasic": True})
    _recompute(eng)
    assert manland.instance_id not in seen
    assert not manland.is_creature


def _creature(eng, name, flying=False):
    obj = _put(eng, name, "Creature — Bear", is_creature=True, power=2, toughness=2)
    return obj


def _humility(eng):
    h = _put(eng, "Humility", "Enchantment")
    _static(h, "ability", "all_creatures", {"lose_all_abilities": True})


def _flying_grant(source):
    _static(source, "ability", "all_creatures", {"keywords": ["flying"]})


@pytest.mark.parametrize("humility_first", [True, False])
def test_creature_lord_grant_ceases_under_humility_in_either_order(humility_first):
    from mtg_analyzer.game import combat
    eng = _engine()
    if humility_first:
        _humility(eng)
    lord = _creature(eng, "Lord")
    _flying_grant(lord)
    other = _creature(eng, "Other")
    if not humility_first:
        _humility(eng)
    _recompute(eng)
    assert not combat.has(other, "flying")
    assert not combat.has(lord, "flying")


def test_enchantment_grant_newer_than_humility_survives():
    from mtg_analyzer.game import combat
    eng = _engine()
    _humility(eng)
    ench = _put(eng, "Wings", "Enchantment")
    _flying_grant(ench)
    other = _creature(eng, "Other")
    _recompute(eng)
    assert combat.has(other, "flying")


@pytest.mark.parametrize("filtered_first", [True, False])
def test_power_filtered_anthem_depends_on_a_same_sublayer_pump(filtered_first):
    # 7d: "creatures with power 2 or less get +1/+1" depends on "creatures get
    # +2/+2" (the pump changes which creatures qualify), so the pump goes first
    # in either timestamp order: a 2/2 Bear ends as 4/4, not 5/5.
    eng = _engine()
    bear = _creature(eng, "Bear")

    def filtered():
        f = _put(eng, "Small Boost", "Enchantment")
        _static(f, "pt_mod", "all_creatures", {"power": 1, "toughness": 1, "object_filter": {"max_power": 2}})

    def pump():
        g = _put(eng, "Big Boost", "Enchantment")
        _static(g, "pt_mod", "all_creatures", {"power": 2, "toughness": 2})

    if filtered_first:
        filtered(); pump()
    else:
        pump(); filtered()
    _recompute(eng)
    assert (bear.power, bear.toughness) == (4, 4)
