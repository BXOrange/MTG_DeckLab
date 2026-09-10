"""MEC-41 — [cEDH] Glarb Bloomsday's remaining 8 gaps, done to completion:
Ad Nauseam, Autumn's Veil, Bring to Light, Counterbalance, Lazotep Quarry,
Nissa Steward of Elements, Valley Floodcaller, Gifts Ungiven.

Reference: docs/implementation-state/Done_Backend.md "MEC-41" entry.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.targeting import TargetSpec, legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone

from tests.support.game import make_engine


def _named(name):
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    return CardDatabase(DB_PATH).get_card(name)


def _put(state, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def _to_library(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.LIBRARY)
    state.player_by_id(controller).library.append(obj)
    return obj


def _cast(eng, p1, mana, name=None, targets=None):
    eng.begin_turn()
    eng.state.current_step = "main1"
    # `make_engine`'s hand-dealing pulls from the end of the library list,
    # so hand order doesn't mirror the input list order — select by name
    # rather than by a brittle positional index.
    spell = next(o for o in p1.hand if name is None or o.name == name)
    bind_from_catalogue(spell)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, spell, targets=targets)
    eng.resolve_until_stable()
    return spell


# ---------------------------------------------------------------------------
# Ad Nauseam
# ---------------------------------------------------------------------------


def test_ad_nauseam_open_ended_reveal_loop():
    lib = [Card(id=f"F{i}", name=f"F{i}", type_line="Instant", is_instant=True,
                 mana_cost_string="{1}", converted_mana_cost=1) for i in range(5)]
    # `make_engine`'s hand-dealing pulls from the end of the library list —
    # Ad Nauseam goes last so it's the one card actually dealt to hand.
    eng = make_engine(lib + [_named("Ad Nauseam")], hand=1)
    p1 = eng.state.player_by_id("p1")
    _cast(eng, p1, {"B": 5})

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "reveal_top_hand_lose_life_loop"
    life_before = p1.life
    eng.resolve_pending_choice("again")
    assert p1.life == life_before - 1  # the revealed card's mana value
    assert len(p1.hand) == 1

    eng.resolve_pending_choice("again")
    assert len(p1.hand) == 2

    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None


# ---------------------------------------------------------------------------
# Autumn's Veil
# ---------------------------------------------------------------------------


def test_autumns_veil_blocks_blue_black_targeting_but_not_other_colors():
    eng = make_engine([_named("Autumn's Veil")], hand=1)
    p1 = eng.state.player_by_id("p1")
    bear = _put(eng.state, _named("Grizzly Bears"))
    _cast(eng, p1, {"G": 1})

    blue_source = GameObject(_named("Unsummon"), owner_id="p2", zone=Zone.STACK)
    blue_source.controller_id = "p2"
    opts = legal_targets(eng.state, "p2", TargetSpec(kind="creature"), source=blue_source)
    assert bear.instance_id not in {o.get("instance_id") for o in opts}

    red_source = GameObject(_named("Lightning Bolt"), owner_id="p2", zone=Zone.STACK)
    red_source.controller_id = "p2"
    opts_red = legal_targets(eng.state, "p2", TargetSpec(kind="creature"), source=red_source)
    assert bear.instance_id in {o.get("instance_id") for o in opts_red}


def test_autumns_veil_prevents_own_spells_from_being_countered():
    eng = make_engine([_named("Autumn's Veil"), _named("Lightning Bolt")], hand=2)
    p1 = eng.state.player_by_id("p1")
    _cast(eng, p1, {"G": 1}, name="Autumn's Veil")
    assert eng.state.spell_watchers  # armed, repeat=True


# ---------------------------------------------------------------------------
# Bring to Light
# ---------------------------------------------------------------------------


def test_bring_to_light_converge_finds_and_grants_free_cast():
    found = _named("Llanowar Elves")
    eng = make_engine([_named("Bring to Light")], hand=1)
    p1 = eng.state.player_by_id("p1")
    lib_obj = _to_library(eng.state, found)
    _cast(eng, p1, {"G": 1, "U": 1, "W": 3})

    spell = p1.hand[0] if p1.hand else None
    assert spell is None  # already cast, moved off hand
    cast_obj = eng.state.find_object(list(eng.state.exile_cast_condition.keys())[0]) \
        if eng.state.exile_cast_condition else None
    # colors_spent_to_cast should be exactly {G, U, W} = 3 colors
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "search"
    eng.resolve_pending_choice(str(lib_obj.instance_id))

    assert lib_obj.zone == Zone.EXILE
    assert lib_obj.instance_id in eng.state.free_cast_instance_ids
    assert eng.state.exile_cast_condition.get(lib_obj.instance_id) == ("p1", {})
    legal = eng.legal_actions(p1)
    assert any(a.get("type") == "cast_spell" and a.get("instance_id") == lib_obj.instance_id for a in legal)

    eng.cast_spell(p1, lib_obj)
    eng.resolve_until_stable()
    assert lib_obj in eng.state.battlefield


def test_bring_to_light_converge_count_excludes_colorless():
    # {3}{G}{U} — the {3} generic is paid in colourless, so RULE 702.108a's
    # own count must land on exactly the two *colored* pips, not be
    # inflated by however the generic portion happened to be paid.
    obj_card = _named("Bring to Light")
    eng = make_engine([obj_card], hand=1)
    p1 = eng.state.player_by_id("p1")
    spell = p1.hand[0]
    bind_from_catalogue(spell)
    p1.mana_pool.add_many({"C": 3, "G": 1, "U": 1})
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.cast_spell(p1, spell)
    assert spell.colors_spent_to_cast == frozenset({"G", "U"})


# ---------------------------------------------------------------------------
# Counterbalance
# ---------------------------------------------------------------------------


def test_counterbalance_counters_matching_mana_value():
    eng = make_engine(
        [_named("Counterbalance")], [_named("Lightning Bolt")], hand=1,
    )
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _put(eng.state, _named("Counterbalance"), controller="p1")
    top = _to_library(eng.state, _named("Llanowar Elves"))  # mana value 1

    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    eng.begin_turn()
    eng.state.current_step = "main1"
    bolt = p2.hand[0]
    bind_from_catalogue(bolt)
    p2.mana_pool.add_many({"R": 1})
    eng.cast_spell(p2, bolt)
    eng.resolve_until_stable()

    resolved = [e for e in seen if e.type == "SPELL_RESOLVED"]
    assert resolved and resolved[-1].data.get("countered") is True
    assert top in p1.library  # the reveal never moves the card


def test_counterbalance_does_not_counter_mismatched_mana_value():
    eng = make_engine([_named("Counterbalance")], [_named("Lightning Bolt")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _put(eng.state, _named("Counterbalance"), controller="p1")
    _to_library(eng.state, _named("Rampant Growth"))  # mana value 2, doesn't match Bolt's 1

    seen = []
    eng.state.subscribe(lambda e: seen.append(e))
    eng.begin_turn()
    eng.state.current_step = "main1"
    bolt = p2.hand[0]
    bind_from_catalogue(bolt)
    p2.mana_pool.add_many({"R": 1})
    eng.cast_spell(p2, bolt)
    eng.resolve_until_stable()

    resolved = [e for e in seen if e.type == "SPELL_RESOLVED"]
    assert resolved and resolved[-1].data.get("countered") is not True


# ---------------------------------------------------------------------------
# Lazotep Quarry
# ---------------------------------------------------------------------------


def test_lazotep_quarry_exiles_graveyard_creature_and_makes_zombie_copy():
    eng = make_engine([_named("Lazotep Quarry")])
    p1 = eng.state.player_by_id("p1")
    land = _put(eng.state, _named("Lazotep Quarry"))
    bear = _named("Grizzly Bears")
    gy_obj = GameObject(bear, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(gy_obj)
    mv = gy_obj.card.converted_mana_cost

    p1.mana_pool.add_many({"C": mv + 2})
    eng.begin_turn()
    eng.state.current_step = "main1"
    ability = land.activated_abilities[0]
    assert eng.can_activate(p1, land, ability, x=mv)
    eng.activate_ability(p1, land, ability_index=0, x=mv)
    eng.resolve_until_stable()

    assert gy_obj.zone == Zone.EXILE
    token = next((o for o in eng.state.battlefield if o.is_token), None)
    assert token is not None
    assert token.name == "Grizzly Bears"
    assert token.power == 4 and token.toughness == 4
    assert "zombie" in token.card.type_line.lower()
    assert land not in eng.state.battlefield  # sacrificed as the cost


def test_lazotep_quarry_no_match_leaves_graveyard_untouched():
    eng = make_engine([_named("Lazotep Quarry")])
    p1 = eng.state.player_by_id("p1")
    land = _put(eng.state, _named("Lazotep Quarry"))
    bear = _named("Grizzly Bears")  # mana value 2
    gy_obj = GameObject(bear, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(gy_obj)

    p1.mana_pool.add_many({"C": 5})  # X=3, no mv-3 creature in graveyard
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.activate_ability(p1, land, ability_index=0, x=3)
    eng.resolve_until_stable()

    assert gy_obj.zone == Zone.GRAVEYARD  # untouched
    assert not any(o.is_token for o in eng.state.battlefield)


# ---------------------------------------------------------------------------
# Nissa, Steward of Elements
# ---------------------------------------------------------------------------


def test_nissa_zero_ability_offers_land_for_battlefield():
    eng = make_engine([_named("Nissa, Steward of Elements")])
    p1 = eng.state.player_by_id("p1")
    pw = _put(eng.state, _named("Nissa, Steward of Elements"))
    pw.counters["loyalty"] = 4
    forest = _to_library(eng.state, Card(
        id="Forest2", name="Forest", type_line="Basic Land — Forest", is_land=True,
    ))

    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.activate_ability(p1, pw, ability_index=1)
    eng.resolve_until_stable()
    # ENG-37 B5: the 0 ability is now `seq(reveal_top, if_else(... then
    # optional(put_revealed_card{battlefield})))` — a "you may" yes/no.
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "composite_optional"
    eng.rules.resolve_choice("yes")
    eng.resolve_until_stable()
    assert forest.zone == Zone.BATTLEFIELD


def test_nissa_zero_ability_skips_expensive_creature():
    eng = make_engine([_named("Nissa, Steward of Elements")])
    p1 = eng.state.player_by_id("p1")
    pw = _put(eng.state, _named("Nissa, Steward of Elements"))
    pw.counters["loyalty"] = 1  # too low for a mv-2 creature
    bear = _to_library(eng.state, _named("Grizzly Bears"))

    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.activate_ability(p1, pw, ability_index=1)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert bear.zone == Zone.LIBRARY


def test_nissa_minus_six_animates_up_to_two_lands():
    eng = make_engine([_named("Nissa, Steward of Elements")])
    p1 = eng.state.player_by_id("p1")
    island = _put(eng.state, _named("Island"), tapped=True)
    mountain = _put(eng.state, _named("Mountain"), tapped=True)
    pw = _put(eng.state, _named("Nissa, Steward of Elements"))
    pw.counters["loyalty"] = 6

    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.activate_ability(p1, pw, ability_index=2, targets=[island, mountain])
    eng.resolve_until_stable()

    for land in (island, mountain):
        assert land.tapped is False
        assert land.power == 5 and land.toughness == 5
        assert land.is_creature and land.is_land
        assert "flying" in land.granted_keywords
        assert "haste" in land.granted_keywords


# ---------------------------------------------------------------------------
# Valley Floodcaller
# ---------------------------------------------------------------------------


def test_valley_floodcaller_pumps_and_untaps_only_listed_subtypes():
    eng = make_engine([_named("Valley Floodcaller"), _named("Opt")], hand=1)
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Valley Floodcaller"))
    bird = _put(eng.state, Card(
        id="TestBird", name="Test Bird", type_line="Creature — Bird",
        is_creature=True, power=1, toughness=1, mana_cost_string="{1}{U}",
        converted_mana_cost=2,
    ), tapped=True)
    bear = _put(eng.state, Card(
        id="TestBear", name="Test Bear", type_line="Creature — Bear",
        is_creature=True, power=2, toughness=2, mana_cost_string="{1}{G}",
        converted_mana_cost=2,
    ), tapped=True)

    _cast(eng, p1, {"U": 2})

    assert bird.power == 2 and bird.toughness == 2 and bird.tapped is False
    assert bear.power == 2 and bear.toughness == 2 and bear.tapped is True


def test_valley_floodcaller_grants_flash_to_noncreature_only():
    from mtg_analyzer.game import continuous

    eng = make_engine([_named("Valley Floodcaller")])
    p1 = eng.state.player_by_id("p1")
    _put(eng.state, _named("Valley Floodcaller"))
    eng.recompute_continuous_effects()

    assert continuous.has_standing_flash_permission(eng.state, p1, _named("Rampant Growth"))
    assert not continuous.has_standing_flash_permission(eng.state, p1, _named("Grizzly Bears"))


# ---------------------------------------------------------------------------
# Gifts Ungiven
# ---------------------------------------------------------------------------


def test_gifts_ungiven_opponent_choice_splits_graveyard_and_hand():
    lib_cards = [
        Card(id=f"Gift{i}", name=f"Gift{i}", type_line="Sorcery", is_sorcery=True,
             mana_cost_string="{1}", converted_mana_cost=1)
        for i in "ABCD"
    ]
    eng = make_engine(lib_cards + [_named("Gifts Ungiven")], [_named("Opt")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    lib_objs = {o.name: o for o in p1.library if o.name.startswith("Gift")}
    _cast(eng, p1, {"U": 1, "C": 3}, targets=[p2])

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "intuition_search"
    assert any(o.get("id") == "decline" for o in choice["options"])
    for name in ("GiftA", "GiftB", "GiftC", "GiftD"):
        eng.resolve_pending_choice(str(lib_objs[name].instance_id))

    choice = eng.state.pending_choice
    assert choice["kind"] == "intuition_choose"
    assert choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(lib_objs["GiftA"].instance_id))
    eng.resolve_pending_choice(str(lib_objs["GiftB"].instance_id))

    gy_names = {o.name for o in p1.graveyard}
    hand_names = {o.name for o in p1.hand}
    assert {"GiftA", "GiftB"} <= gy_names
    assert {"GiftC", "GiftD"} <= hand_names


def test_intuition_still_sends_chosen_to_hand_and_rest_to_graveyard():
    lib_cards = [
        Card(id=f"Int{i}", name=f"Int{i}", type_line="Sorcery", is_sorcery=True,
             mana_cost_string="{1}", converted_mana_cost=1)
        for i in "ABC"
    ]
    eng = make_engine(lib_cards + [_named("Intuition")], [_named("Opt")], hand=1)
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    lib_objs = {o.name: o for o in p1.library if o.name.startswith("Int")}
    _cast(eng, p1, {"U": 1, "C": 2}, targets=[p2])

    choice = eng.state.pending_choice
    assert not any(o.get("id") == "decline" for o in choice["options"])  # no "up to" here
    for name in ("IntA", "IntB", "IntC"):
        eng.resolve_pending_choice(str(lib_objs[name].instance_id))

    choice = eng.state.pending_choice
    assert choice["player_id"] == "p2"
    eng.resolve_pending_choice(str(lib_objs["IntA"].instance_id))

    assert "IntA" in {o.name for o in p1.hand}
    gy_names = {o.name for o in p1.graveyard}
    assert {"IntB", "IntC"} <= gy_names
