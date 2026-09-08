"""MEC-12 (cEDH staples 2) — Protean Hulk's "when this creature dies,
search your library for any number of creature cards with total mana
value 6 or less, put them onto the battlefield, then shuffle."

New primitive: `SearchLibraryEffect.total_mana_value_budget` — a running
mana-value total shared across a whole open-ended multi-pick search,
distinct from `criteria`'s own fixed per-card `max_mana_value` cap.

Reference: docs/implementation-state/Done_Backend.md "MEC-12" entries.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone

from tests.support.game import make_engine, obj_on_battlefield


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _creature_card(name, cmc):
    return Card(
        id=name, name=name, type_line="Creature — Beast", is_creature=True,
        power=cmc, toughness=cmc, converted_mana_cost=cmc,
    )


def test_protean_hulk_finds_multiple_creatures_within_total_budget():
    from mtg_analyzer.models.game.game_object import GameObject

    eng = make_engine([], [], hand=0)
    hulk = obj_on_battlefield(eng.state, eng, _named("Protean Hulk"), controller="p1")
    bind_from_catalogue(hulk)
    p1 = eng.state.player_by_id("p1")
    five = GameObject(_creature_card("Five", 5), owner_id="p1", zone=Zone.LIBRARY)
    one = GameObject(_creature_card("One", 1), owner_id="p1", zone=Zone.LIBRARY)
    six = GameObject(_creature_card("Six", 6), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.extend([five, one, six])

    eng.rules.destroy(hulk)
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    eligible_names = {e["name"] for e in choice["eligible"]}
    assert eligible_names == {"Five", "One", "Six"}

    eng.rules.resolve_search_choice(five.instance_id)
    # Budget now 6 - 5 = 1 remaining: "Six" no longer fits, "One" still does.
    choice = eng.state.pending_choice
    eligible_names = {e["name"] for e in choice["eligible"]}
    assert eligible_names == {"One"}

    eng.rules.resolve_search_choice(one.instance_id)
    # Budget exhausted (0 remaining) — search auto-finishes with no more choice.
    assert eng.state.pending_choice is None
    assert five in eng.state.battlefield
    assert one in eng.state.battlefield
    assert six not in eng.state.battlefield
    assert six in p1.library


def test_protean_hulk_declining_early_still_keeps_earlier_picks():
    from mtg_analyzer.models.game.game_object import GameObject

    eng = make_engine([], [], hand=0)
    hulk = obj_on_battlefield(eng.state, eng, _named("Protean Hulk"), controller="p1")
    bind_from_catalogue(hulk)
    p1 = eng.state.player_by_id("p1")
    two = GameObject(_creature_card("Two", 2), owner_id="p1", zone=Zone.LIBRARY)
    p1.library.append(two)

    eng.rules.destroy(hulk)
    eng.resolve_until_stable()

    eng.rules.resolve_search_choice(two.instance_id)
    # Still eligible (budget 6-2=4 > 0) but only "Two" existed and it's now
    # picked, so the search should have auto-finished already.
    assert eng.state.pending_choice is None
    assert two in eng.state.battlefield
