"""Secrets of Strixhaven — playability batch, wave 102 (PAR-60).

Laelia, the Blade Reforged — attack trigger reuses `impulsive_draw`
(same_turn_only). The counter trigger is a new binder key
``exiled_from_your_library_or_graveyard`` on `EventType.EXILE` (which now
carries ``from_zone``). Documented simplification: fires once per card
exiled from those zones (per-card, not per "one or more" batch).
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _laelia_card():
    return Card(id="lae", name="Laelia, the Blade Reforged",
                type_line="Legendary Creature — Spirit Warrior", is_creature=True,
                power=2, toughness=2,
                oracle_text=("Haste\nWhenever Laelia attacks, exile the top card of your "
                             "library. You may play that card this turn.\nWhenever one or "
                             "more cards are put into exile from your library and/or your "
                             "graveyard, put a +1/+1 counter on Laelia."))


def test_registered_and_binds():
    assert is_registered("Laelia, the Blade Reforged")
    specs = _REGISTRY["laelia, the blade reforged"]()
    assert [s.effects[0].type for s in specs] == ["impulsive_draw", "add_counters"]
    src = GameObject(_laelia_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_specs_for_real_card():
    assert specs_for(_laelia_card())


def _laelia_on_battlefield(eng):
    src = GameObject(_laelia_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    eng.state.add_to_battlefield(src)
    for s in _REGISTRY["laelia, the blade reforged"]():
        bound = bind_ability(s, src)
        for ab in (bound if isinstance(bound, list) else [bound]):
            src.triggered_abilities.append(ab)
    return src


def test_library_exile_grows_laelia_but_battlefield_exile_does_not():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    laelia = _laelia_on_battlefield(eng)

    lib_card = GameObject(Card(id="x", name="Spell", type_line="Sorcery", is_sorcery=True),
                          owner_id="p1", zone=Zone.LIBRARY)
    p1.add_to_zone(lib_card, Zone.LIBRARY)
    eng.rules.exile(lib_card)
    eng.resolve_until_stable()
    assert laelia.counters.get("+1/+1", 0) == 1

    other = GameObject(Card(id="b", name="Bear", type_line="Creature — Bear",
                            is_creature=True, power=2, toughness=2),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    other.controller_id = "p1"
    eng.state.add_to_battlefield(other)
    eng.rules.exile(other)
    eng.resolve_until_stable()
    assert laelia.counters.get("+1/+1", 0) == 1  # unchanged — not a library/graveyard exile


def test_opponent_library_exile_does_not_grow_laelia():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_life=20, starting_hand=0)
    p2 = eng.state.player_by_id("p2")
    laelia = _laelia_on_battlefield(eng)
    theirs = GameObject(Card(id="y", name="Spell2", type_line="Sorcery", is_sorcery=True),
                        owner_id="p2", zone=Zone.LIBRARY)
    p2.add_to_zone(theirs, Zone.LIBRARY)
    eng.rules.exile(theirs)
    eng.resolve_until_stable()
    assert laelia.counters.get("+1/+1", 0) == 0
