"""MEC-37 — Doomsday's real printed shape ("Search your library and
graveyard for five cards and exile the rest. Put the chosen cards on top
of your library in any order. You lose half your life, rounded up.")
turned out to need no new search primitive at all: `SearchLibraryEffect`
already supports a combined library+graveyard search, `exile_rest`
(built with this exact card in mind, per its own docstring), and
`destination="library_top"`, whose one-card-at-a-time picks already stack
in a player-controlled order for free. The only new piece is
`LoseLifeEffect.amount_from_half_own_life`.

Reference: docs/implementation-state/Done_Backend.md "MEC-37" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def test_doomsday_stacks_five_chosen_cards_exiles_the_rest_and_halves_life():
    lib = [creature(f"Lib{i}") for i in range(6)]
    eng = make_engine([_named("Doomsday")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    p1.life = 13  # loses half rounded up (7) -> 6 remaining

    for card in lib:
        p1.library.append(GameObject(card, owner_id="p1", zone=Zone.LIBRARY))
    grave_obj = GameObject(creature("GraveGuy"), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(grave_obj)

    doomsday = p1.hand[0]
    bind_from_catalogue(doomsday)
    eng.cast_spell(p1, doomsday, targets=None)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    lib_by_name = {o.card.name: o.instance_id for o in list(p1.library)}
    # Pick the graveyard card first (ends up buried under the other four,
    # drawn last of the five), then four library cards in a fixed order —
    # exercising both "search zone" and the player's free choice of order.
    order = [grave_obj.instance_id] + [
        lib_by_name[name] for name in ("Lib0", "Lib1", "Lib2", "Lib3")
    ]
    for instance_id in order:
        eng.rules.resolve_choice(instance_id)
    eng.resolve_until_stable()  # drains the deferred lose_life (RULE 608.2m)

    assert eng.state.pending_choice is None
    assert p1.life == 6
    assert grave_obj not in p1.graveyard

    top5 = [p1.library[-(i + 1)].instance_id for i in range(5)]
    assert top5 == list(reversed(order))  # last-named pick ends up on top

    remaining_names = {o.card.name for o in p1.library}
    assert "Lib4" not in remaining_names and "Lib5" not in remaining_names
    exiled_names = {o.card.name for o in p1.exile}
    assert {"Lib4", "Lib5"} <= exiled_names


def test_doomsday_leaves_no_pending_choice_when_fewer_than_five_cards_exist():
    eng = make_engine([_named("Doomsday")], [], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 3})
    p1.life = 10

    only = GameObject(creature("Solo"), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(only)

    doomsday = p1.hand[0]
    bind_from_catalogue(doomsday)
    eng.cast_spell(p1, doomsday, targets=None)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    eng.rules.resolve_choice(only.instance_id)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None  # nothing left to search for
    assert p1.life == 5
    assert only in p1.library
