"""MEC-43 round 3 "SearchLibraryEffect widenings" batch (2026-08-24) — closes
the four cards BACKLOG.md's round-2 diagnosis had flagged as near-free
`SearchLibraryEffect` widenings. Each turned out to need a genuinely new (if
small) primitive once actually checked against the effect's real code, not
just its constructor signature — the fail-closed "verify, don't assume" rule
`Done_Backend.md` already documents for this ticket:

* Beseech the Queen — `SearchLibraryEffect.mana_value_from`'s new
  ``"count_selector"`` source (`continuous.count_selector`'s existing
  ``"lands_you_control"`` entry, previously only reachable from
  ``"sacrificed_cost"``).
* Final Parting — a genuinely free reuse of the existing ``destinations``
  split (Cultivate/Kodama's Reach-shaped), just needing a parser handler for
  its own bare "N cards" / three-sentence phrasing
  (`_SEARCH_TWO_CARDS_SPLIT_RE`).
* Search for Glory — its ``"or"`` criteria combinator was already free
  (`models.card_query`), but "gain 1 life for each {S} spent to cast this
  spell" needed a wholly new tracking primitive: `ManaPool.snow_pool` (a
  `pool_by_source`-shaped but orthogonal "was this snow-sourced" subset
  count, since a lot can be both ``source_kind="basic_land"`` *and* snow),
  `GameObject.mana_spent_to_cast_snow` (a `colors_spent_to_cast`-shaped
  before/after diff at cast time), and `continuous.count_selector`'s new
  ``"snow_mana_spent_to_cast"`` self-referential entry.
* Myriad Landscape — "...basic land cards **that share a land type**." is a
  cross-pick constraint no existing criteria shape could express (`models.
  card_query` only ever judges one candidate in isolation);
  `SearchLibraryEffect.share_land_type`/`RulesEngine.request_search`'s new
  param threads a "shares a basic land type with an already-found card"
  filter through both `request_search`'s first round and
  `resolve_search_choice`'s later rounds.

Reference: docs/implementation-state/Done_Backend.md "MEC-43" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

from tests.test_game_engine import creature, make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _basic(name, produces):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)


def _snow_basic(name, produces):
    return Card(id=name, name=name, type_line=f"Basic Snow Land — {produces}", is_land=True)


def _eligible_names(pending_choice):
    return {o["label"] for o in pending_choice["options"] if o["id"] != "decline"}


# ---------------------------------------------------------------------------
# Beseech the Queen — mana_value_from's new "count_selector" source
# ---------------------------------------------------------------------------


def test_beseech_the_queen_bounds_the_search_by_lands_controlled():
    eng = make_engine([_named("Beseech the Queen")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 6})
    for _ in range(3):
        obj = GameObject(_basic("Swamp", "Swamp"), owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        eng.state.add_to_battlefield(obj)

    cheap = creature("Cheap", cost="{G}")  # mana value 1
    pricey = creature("Pricey", cost="{4}{G}{G}")  # mana value 6
    p1.library.append(GameObject(cheap, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(pricey, owner_id="p1", zone=Zone.LIBRARY))

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=None)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    # 3 lands controlled -> mana value <= 3: Cheap qualifies, Pricey doesn't.
    assert _eligible_names(eng.state.pending_choice) == {"Cheap"}


def test_beseech_the_queen_finds_nothing_with_no_lands_controlled():
    eng = make_engine([_named("Beseech the Queen")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 6})
    p1.library.append(
        GameObject(creature("OneDrop", cost="{G}"), owner_id="p1", zone=Zone.LIBRARY)
    )

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=None)
    eng.resolve_until_stable()

    # mana value <= 0 (no lands controlled) matches nothing -> auto-shuffle,
    # no prompt at all.
    assert eng.state.pending_choice is None


# ---------------------------------------------------------------------------
# Final Parting — the existing "destinations" split, bare-"N cards" phrasing
# ---------------------------------------------------------------------------


def test_final_parting_puts_the_first_pick_in_hand_and_the_second_in_the_graveyard():
    eng = make_engine([_named("Final Parting")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"B": 5})
    p1.library.append(GameObject(creature("PickA"), owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(creature("PickB"), owner_id="p1", zone=Zone.LIBRARY))

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=None)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    a_obj = next(o for o in p1.library if o.name == "PickA")
    eng.rules.resolve_search_choice(a_obj.instance_id)
    assert eng.state.pending_choice is not None  # second pick still open

    b_obj = next(o for o in p1.library if o.name == "PickB")
    eng.rules.resolve_search_choice(b_obj.instance_id)

    assert eng.state.pending_choice is None
    assert any(o.name == "PickA" for o in p1.hand)
    assert any(o.name == "PickB" for o in p1.graveyard)


# ---------------------------------------------------------------------------
# Search for Glory — free "or" criteria + the new snow-mana-spent tracker
# ---------------------------------------------------------------------------


def test_search_for_glory_end_to_end_finds_a_legendary_and_gains_life_for_snow_spent():
    eng = make_engine([_named("Search for Glory")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.life = 20

    snow_plains = _snow_basic("Snow-Covered Plains", "Plains")
    plains = _basic("Plains", "Plains")
    for card in (snow_plains, snow_plains, plains):
        obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        eng.state.add_to_battlefield(obj)
    # Cost is {2}{W} (mana value 3): 2 of the 3 W spent come from the two
    # snow Plains (`ManaPool.snow_pool`'s "snow-first" drain order), the
    # third from the plain one.
    for source in [o for o in eng.state.battlefield if o.controller_id == "p1"]:
        eng.tap_for_mana(p1, source)

    legendary = creature("LegendBear", type_line="Legendary Creature — Bear")
    plain_creature = creature("PlainBear")
    p1.library.append(GameObject(legendary, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(plain_creature, owner_id="p1", zone=Zone.LIBRARY))

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=None)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    # The "or" criteria (snow permanent / legendary / Saga) excludes the
    # plain creature.
    assert _eligible_names(eng.state.pending_choice) == {"LegendBear"}
    found = next(o for o in p1.library if o.name == "LegendBear")
    eng.rules.resolve_search_choice(found.instance_id)
    eng.resolve_until_stable()  # drains the deferred gain_life (RULE 608.2)

    assert eng.state.pending_choice is None
    assert any(o.name == "LegendBear" for o in p1.hand)
    assert p1.life == 22


def test_search_for_glory_gains_no_life_when_no_snow_mana_was_spent():
    eng = make_engine([_named("Search for Glory")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.life = 20
    p1.mana_pool.add_many({"W": 3})  # ordinary, non-snow mana
    p1.library.append(GameObject(creature("Filler"), owner_id="p1", zone=Zone.LIBRARY))

    spell = p1.hand[0]
    bind_from_catalogue(spell)
    eng.cast_spell(p1, spell, targets=None)
    eng.resolve_until_stable()

    # No eligible card in the library (a plain creature matches none of the
    # three "or" alternatives) -> search closes with no prompt, but the
    # life-gain clause still resolves independently.
    assert eng.state.pending_choice is None
    assert p1.life == 20


# ---------------------------------------------------------------------------
# Myriad Landscape — the new cross-pick "share a land type" constraint
# ---------------------------------------------------------------------------


def test_myriad_landscape_second_pick_must_share_a_land_type_with_the_first():
    eng = make_engine([creature("Filler")], hand=0)
    p1 = eng.state.player_by_id("p1")
    land_obj = GameObject(_named("Myriad Landscape"), owner_id="p1", zone=Zone.BATTLEFIELD)
    land_obj.summoning_sick = False
    land_obj.tapped = False
    bind_from_catalogue(land_obj)
    eng.state.add_to_battlefield(land_obj)
    p1.mana_pool.add_many({"C": 2})

    forest = _basic("Forest", "Forest")
    island = _basic("Island", "Island")
    forest2 = _basic("Forest2", "Forest")
    p1.library.append(GameObject(forest, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(island, owner_id="p1", zone=Zone.LIBRARY))
    p1.library.append(GameObject(forest2, owner_id="p1", zone=Zone.LIBRARY))

    eng.activate_ability(p1, land_obj)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is not None
    # The first pick is unconstrained -- nothing found yet to share with.
    assert _eligible_names(eng.state.pending_choice) == {"Forest", "Island", "Forest2"}

    forest_obj = next(o for o in p1.library if o.name == "Forest")
    eng.rules.resolve_search_choice(forest_obj.instance_id)

    assert eng.state.pending_choice is not None
    # Island doesn't share a basic land type with Forest -- excluded.
    assert _eligible_names(eng.state.pending_choice) == {"Forest2"}

    forest2_obj = next(o for o in p1.library if o.name == "Forest2")
    eng.rules.resolve_search_choice(forest2_obj.instance_id)

    assert eng.state.pending_choice is None
    battlefield = {o.name: o for o in eng.state.battlefield if o.controller_id == "p1"}
    assert "Forest" in battlefield and "Forest2" in battlefield
    assert battlefield["Forest"].tapped and battlefield["Forest2"].tapped
    assert "Myriad Landscape" not in battlefield  # sacrificed to pay the cost
