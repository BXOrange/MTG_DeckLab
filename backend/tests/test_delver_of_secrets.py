"""Delver of Secrets — the last open item in RULE 712's ToDo entry
(`docs/implementation-state/BACKLOG.md`): a *conditional* transform gated on a library
peek ("look at the top card of your library. If it's an instant or sorcery
card, transform ~"), distinct from RULE 731's day/night spells-cast-count
flip. `RevealTopThenTransformEffect` (`game/effects/core.py`) is the new
general-purpose primitive, parameterized on a `models.card_query` criteria
dict rather than hardcoded to instant/sorcery, so any future card sharing
this exact template reuses it.

Reference: mtg_analyzer/game/{effects,ability_catalogue,rules_engine}.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def _delver_card():
    return Card(
        id="Delver of Secrets", name="Delver of Secrets",
        type_line="Creature — Human Wizard", is_creature=True,
        power=1, toughness=1,
        oracle_text=(
            "At the beginning of each upkeep, look at the top card of your "
            "library. You may reveal that card. If an instant or sorcery "
            "card is revealed this way, transform Delver of Secrets."
        ),
        layout="transform",
        back_name="Insectile Aberration", back_type_line="Creature — Human Insect",
        back_power=3, back_toughness=2,
    )


def _instant(name="Bolt"):
    return Card(id=name, name=name, type_line="Instant", is_instant=True)


def _sorcery(name="Twister"):
    return Card(id=name, name=name, type_line="Sorcery", is_sorcery=True)


def _creature(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2)


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _put_delver(eng, controller="p1"):
    obj = GameObject(_delver_card(), owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _fire_upkeep(eng):
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="beginning"))
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()


def test_delver_binds_a_triggered_reveal_and_conditional_transform_ability():
    eng = _engine()
    obj = _put_delver(eng)
    assert len(obj.triggered_abilities) == 1


def test_transforms_when_top_card_is_instant():
    eng = _engine()
    obj = _put_delver(eng)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_instant(), owner_id="p1", zone=Zone.LIBRARY))

    _fire_upkeep(eng)

    assert obj.transformed is True
    assert obj.card.name == "Insectile Aberration"
    assert obj.power == 3 and obj.toughness == 2
    # library untouched — the card was only looked at, never moved
    assert len(p1.library) == 1


def test_transforms_when_top_card_is_sorcery():
    eng = _engine()
    obj = _put_delver(eng)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_sorcery(), owner_id="p1", zone=Zone.LIBRARY))

    _fire_upkeep(eng)

    assert obj.transformed is True
    assert obj.card.name == "Insectile Aberration"


def test_does_not_transform_when_top_card_is_a_creature():
    eng = _engine()
    obj = _put_delver(eng)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_creature(), owner_id="p1", zone=Zone.LIBRARY))

    _fire_upkeep(eng)

    assert obj.transformed is False
    assert obj.card.name == "Delver of Secrets"


def test_does_not_transform_with_empty_library():
    eng = _engine()
    obj = _put_delver(eng)

    _fire_upkeep(eng)

    assert obj.transformed is False


def test_fires_on_opponents_upkeep_too_but_reads_its_own_controllers_library():
    """"Each upkeep", not just its controller's — but "your library" is
    always Delver's own controller's, regardless of whose upkeep fired it.
    """
    eng = _engine()
    obj = _put_delver(eng, controller="p1")
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    p1.library.append(GameObject(_instant(), owner_id="p1", zone=Zone.LIBRARY))
    p2.library.append(GameObject(_creature(), owner_id="p2", zone=Zone.LIBRARY))

    # Bob's upkeep begins, not Alice's — the trigger has no `phase_relation`
    # filter, so it still fires, and must still consult Alice's library.
    eng.state.active_player_index = 1
    _fire_upkeep(eng)

    assert obj.transformed is True


def test_already_transformed_creature_flips_back_on_a_second_matching_upkeep():
    eng = _engine()
    obj = _put_delver(eng)
    p1 = eng.state.player_by_id("p1")
    p1.library.append(GameObject(_instant(), owner_id="p1", zone=Zone.LIBRARY))
    _fire_upkeep(eng)
    assert obj.transformed is True

    # Its back face has no ability at all, so nothing fires (and nothing
    # flips it back) on a later upkeep — Delver only ever transforms once.
    p1.library.append(GameObject(_instant("Bolt 2"), owner_id="p1", zone=Zone.LIBRARY))
    _fire_upkeep(eng)
    assert obj.transformed is True
    assert obj.card.name == "Insectile Aberration"
