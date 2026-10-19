"""MEC-127 — "each player chooses N <permanents> they control, then sacrifices/destroys the rest".

A counted keep on `ChoosePlayerObjectsEffect` (the per-type keeper path's sibling): every player picks in APNAP
order while nothing moves (RULE 608.2e), then the rest leave together (RULE 603.10a). Each real card is cast
through `cast_spell` from its printed oracle text, with picks answered for several players.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from test_mec106_gift import _bf, _creature, _engine, _hand

RAZIA = "Each player chooses three permanents they control, then sacrifices the rest."
RECKONING = "Each player chooses a creature they control. Destroy the rest."
ELEGY = ("Each player chooses up to two creatures they control, then sacrifices the rest. "
         "Then you create a tapped Treasure token for each creature your opponents control.")
COMBAT = ("Each player chooses a creature or planeswalker they control, then sacrifices the rest. "
          "Players can't cast creature or planeswalker spells until the end of your next turn.")
TIDE = ("Each player chooses a nonland permanent they control. Return all nonland permanents not chosen this way "
        "to their owners' hands. Then you draw a card for each opponent who has more cards in their hand than you.")
OVERLAY = ("Each player chooses a land they control of each basic land type. "
           "Return those lands to their owners' hands.")
SYLEX_ABILITY = ("{2}{W}{W}, {T}, Exile Urza's Sylex: Each player chooses six lands they control. "
                 "Destroy all other permanents. Activate only as a sorcery.")
FALL_III = ("(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)\n"
            "I — You and target opponent each draw two cards.\n"
            "II — Exile target artifact an opponent controls.\n"
            "III — Each player chooses three nonland permanents they control. Destroy all other nonland permanents.")


def _sorcery(name, oracle):
    return Card(id=name, name=name, type_line="Sorcery", oracle_text=oracle, mana_cost_string="{0}",
                converted_mana_cost=0, is_sorcery=True)


def _put(eng, name, type_line, player="p1", **kw):
    return _bf(eng, Card(id=name, name=name, type_line=type_line, **kw), player)


def _creat(eng, name, player="p1"):
    return _put(eng, name, "Creature — Bear", player, is_creature=True, power=2, toughness=2)


def _cast(eng, name, oracle, player="p1"):
    card = _sorcery(name, oracle)
    assert parse_oracle(card).modeled, name
    obj = _hand(eng, card, player)
    eng.cast_spell(eng.state.player_by_id(player), obj)
    eng.resolve_until_stable()
    return obj


def _pick(eng, obj, who=None):
    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "choose_objects"
    if who:
        assert pc["player_id"] == who
    assert str(obj.instance_id) in {o["id"] for o in pc["options"]}
    eng.resolve_pending_choice(str(obj.instance_id))


def _where(*objs):
    return [o.zone for o in objs]


def test_razia_every_player_keeps_three_in_apnap_order_then_the_rest_go_together():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    eng.state.active_player_index = 1
    perms = {pid: [_creat(eng, f"{pid}-{i}", pid) for i in range(4)] for pid in ("p1", "p2", "p3")}
    # p3 only controls two permanents here: both are kept without a prompt.
    for obj in perms["p3"][2:]:
        eng.rules.exile(obj)
    perms["p3"] = perms["p3"][:2]
    obj = _cast_as(eng, "Razia's Purification", RAZIA, "p2")
    order = []
    while eng.state.pending_choice:
        pid = eng.state.pending_choice["player_id"]
        order.append(pid)
        assert all(o.zone == Zone.BATTLEFIELD for pairs in perms.values() for o in pairs)  # nothing moves yet
        for _ in range(3):
            _pick(eng, perms[pid][_], pid)
    eng.resolve_until_stable()
    assert order == ["p2", "p1"]  # APNAP from the active player; p3 had nothing to decide
    for pid in ("p1", "p2"):
        assert _where(*perms[pid]) == [Zone.BATTLEFIELD] * 3 + [Zone.GRAVEYARD]
    assert _where(*perms["p3"]) == [Zone.BATTLEFIELD] * 2
    batches = [e for e in eng.state.event_log
               if e.type == EventType.EVENT_BATCH and e.get("batch_of") == EventType.SACRIFICE]
    assert len(batches[-1].get("members")) == 2
    assert obj.zone == Zone.GRAVEYARD


def _cast_as(eng, name, oracle, player):
    eng.state.active_player_index = [p.id for p in eng.state.players].index(player)
    return _cast(eng, name, oracle, player)


def test_fewer_permanents_than_the_count_keeps_them_all_without_a_prompt():
    eng = _engine()
    mine = [_creat(eng, "a"), _creat(eng, "b")]
    theirs = [_creat(eng, f"t{i}", "p2") for i in range(5)]
    _cast(eng, "Razia's Purification", RAZIA)
    for i in range(3):
        _pick(eng, theirs[i], "p2")
    eng.resolve_until_stable()
    assert _where(*mine) == [Zone.BATTLEFIELD] * 2
    assert _where(*theirs) == [Zone.BATTLEFIELD] * 3 + [Zone.GRAVEYARD] * 2


def test_divine_reckoning_destroys_the_rest_and_an_indestructible_creature_survives():
    eng = _engine()
    keep1, lose1 = _creat(eng, "k1"), _creat(eng, "l1")
    god = _put(eng, "Indestructible", "Creature — God", is_creature=True, power=1, toughness=1,
               keywords=["Indestructible"])
    keep2, lose2 = _creat(eng, "k2", "p2"), _creat(eng, "l2", "p2")
    land = _put(eng, "Island", "Basic Land — Island", is_land=True)
    _cast(eng, "Divine Reckoning", RECKONING)
    _pick(eng, keep1, "p1")
    _pick(eng, keep2, "p2")
    eng.resolve_until_stable()
    assert _where(keep1, keep2, land, god) == [Zone.BATTLEFIELD] * 4
    assert _where(lose1, lose2) == [Zone.GRAVEYARD] * 2


def test_covetous_elegy_up_to_two_declining_and_the_treasure_tail_counts_afterwards():
    eng = _engine()
    mine = [_creat(eng, f"m{i}") for i in range(3)]
    theirs = [_creat(eng, f"t{i}", "p2") for i in range(3)]
    _cast(eng, "Covetous Elegy", ELEGY)
    _pick(eng, mine[0], "p1")
    _pick(eng, mine[1], "p1")
    assert eng.state.pending_choice["player_id"] == "p2"
    assert any(o["id"] == "decline" for o in eng.state.pending_choice["options"])
    eng.resolve_pending_choice("decline")  # a player choosing nothing extra: all of p2's creatures go
    eng.resolve_until_stable()
    assert _where(*mine) == [Zone.BATTLEFIELD] * 2 + [Zone.GRAVEYARD]
    assert _where(*theirs) == [Zone.GRAVEYARD] * 3
    treasures = [o for o in eng.state.battlefield if o.is_token and o.name == "Treasure"]
    assert len(treasures) == 0  # the tail counts creatures opponents control AFTER the edict (none are left)


def test_covetous_elegy_tail_counts_the_survivors():
    eng = _engine()
    mine = [_creat(eng, f"m{i}") for i in range(2)]
    theirs = [_creat(eng, f"t{i}", "p2") for i in range(3)]
    _cast(eng, "Covetous Elegy", ELEGY)
    _pick(eng, mine[0], "p1")
    eng.resolve_pending_choice("decline")
    _pick(eng, theirs[0], "p2")
    _pick(eng, theirs[1], "p2")
    eng.resolve_until_stable()
    treasures = [o for o in eng.state.battlefield if o.name == "Treasure"]
    assert len(treasures) == 2 and all(t.tapped for t in treasures)
    assert theirs[2].zone == Zone.GRAVEYARD and mine[1].zone == Zone.GRAVEYARD


def test_single_combat_keeps_one_and_bars_creature_and_planeswalker_spells_until_next_turn_ends():
    eng = _engine()
    walker = _put(eng, "Walker", "Planeswalker — Example", loyalty=3)
    bear = _creat(eng, "bear")
    theirs = _creat(eng, "theirs", "p2")
    _cast(eng, "Single Combat", COMBAT)
    _pick(eng, walker, "p1")
    eng.resolve_until_stable()
    assert walker.zone == Zone.BATTLEFIELD and bear.zone == Zone.GRAVEYARD and theirs.zone == Zone.BATTLEFIELD
    creature_spell = Card(id="cs", name="cs", type_line="Creature — Bear", is_creature=True, mana_cost_string="{0}",
                          converted_mana_cost=0, power=1, toughness=1)
    instant = Card(id="ci", name="ci", type_line="Instant", is_instant=True, mana_cost_string="{0}",
                   converted_mana_cost=0)
    (floating,) = eng.state.floating_statics
    assert floating.duration == "end_of_your_next_turn"  # RULE 611.2: outlasts the turn it was cast in
    from mtg_analyzer.game import durations
    eng.state.internal_turn.number += 1  # the opponent's turn: the window is still open
    eng.state.active_player_index = 1
    assert not durations.sweep(eng.state, "cleanup") and eng.state.floating_statics
    eng.state.internal_turn.number += 1  # the caster's next turn reaches its cleanup step
    eng.state.active_player_index = 0
    assert durations.sweep(eng.state, "cleanup") and not eng.state.floating_statics
    eng.state.internal_turn.number -= 2
    eng.state.floating_statics.append(floating)
    for pid in ("p1", "p2"):
        obj = _hand(eng, creature_spell, pid)
        assert not eng.can_cast(eng.state.player_by_id(pid), obj)
        assert eng.can_cast(eng.state.player_by_id(pid), _hand(eng, instant, pid))


def test_consuming_tide_returns_the_rest_keeps_lands_and_draws_for_richer_opponents():
    eng = _engine()
    keep, bounce = _creat(eng, "keep"), _creat(eng, "bounce")
    land = _put(eng, "Island", "Basic Land — Island", is_land=True)
    token = _put(eng, "Token", "Creature — Bear", is_creature=True, power=1, toughness=1)
    token.is_token = True
    theirs_keep, theirs_bounce = _creat(eng, "tk", "p2"), _creat(eng, "tb", "p2")
    for i in range(4):  # the opponent holds more cards than the caster will have after casting
        _hand(eng, Card(id=f"h{i}", name=f"h{i}", type_line="Land", is_land=True), "p2")
    _cast(eng, "Consuming Tide", TIDE)
    _pick(eng, keep, "p1")
    _pick(eng, theirs_keep, "p2")
    eng.resolve_until_stable()
    assert _where(keep, land, theirs_keep) == [Zone.BATTLEFIELD] * 3
    assert bounce.zone == theirs_bounce.zone == Zone.HAND and token.zone != Zone.BATTLEFIELD
    # caster: bounced creature + token vanished; draw 1 for the one opponent holding more cards
    assert len(eng.state.player_by_id("p1").hand) >= 2


def test_planar_overlay_returns_one_land_of_each_basic_type_per_player():
    eng = _engine()
    plains = _put(eng, "Plains", "Basic Land — Plains", is_land=True)
    plains2 = _put(eng, "Plains2", "Basic Land — Plains", is_land=True)
    dual = _put(eng, "Dual", "Land — Island Swamp", is_land=True)
    other = _put(eng, "Mountain", "Basic Land — Mountain", is_land=True, player="p1") if False else None
    theirs = _put(eng, "TheirsForest", "Basic Land — Forest", "p2", is_land=True)
    _cast(eng, "Planar Overlay", OVERLAY)
    # APNAP: p1 chooses first. Plains has two candidates; Island/Swamp are the dual alone (auto).
    _pick(eng, plains, "p1")
    eng.resolve_until_stable()
    assert plains.zone == Zone.HAND and dual.zone == Zone.HAND and theirs.zone == Zone.HAND
    assert plains2.zone == Zone.BATTLEFIELD


def test_urza_sylex_keeps_six_lands_and_destroys_every_other_permanent():
    eng = _engine()
    lands = [_put(eng, f"L{i}", "Basic Land — Forest", is_land=True) for i in range(7)]
    bear = _creat(eng, "bear")
    theirs_lands = [_put(eng, f"T{i}", "Basic Land — Forest", "p2", is_land=True) for i in range(3)]
    theirs_bear = _creat(eng, "tbear", "p2")
    card = Card(id="Urza's Sylex", name="Urza's Sylex", type_line="Legendary Artifact", oracle_text=SYLEX_ABILITY,
                mana_cost_string="{3}", converted_mana_cost=3)
    assert parse_oracle(card).modeled
    sylex = _bf(eng, card)
    eng.state.player_by_id("p1").mana_pool.add_many({"W": 2, "C": 2})
    eng.activate_ability(eng.state.player_by_id("p1"), sylex, 0)
    eng.resolve_until_stable()
    for i in range(6):
        _pick(eng, lands[i], "p1")
    eng.resolve_until_stable()
    assert _where(*lands[:6], *theirs_lands) == [Zone.BATTLEFIELD] * 9
    assert lands[6].zone == bear.zone == theirs_bear.zone == Zone.GRAVEYARD


def test_fall_of_the_first_civilization_chapter_three_destroys_other_nonland_permanents():
    card = Card(id="Fall", name="Fall of the First Civilization", type_line="Enchantment — Saga",
                oracle_text=FALL_III, mana_cost_string="{2}{W}", converted_mana_cost=3)
    result = parse_oracle(card)
    assert result.modeled
    eng = _engine()
    land = _put(eng, "Plains", "Basic Land — Plains", is_land=True)
    bears = [_creat(eng, f"b{i}") for i in range(4)]
    spec = parse_effect_body("each player chooses 3 nonland permanents they control. destroy all other nonland permanents.")
    from mtg_analyzer.game.binding.core import build_effects
    source = _bf(eng, _creature("Source"))
    bears.append(source)  # the source is a nonland permanent too
    for effect in build_effects(spec, source):
        effect.apply(eng.rules.context)
    for b in bears[:2] + [bears[2]]:
        _pick(eng, b, "p1")
    eng.resolve_until_stable()
    assert land.zone == Zone.BATTLEFIELD
    assert [b.zone for b in bears[:3]] == [Zone.BATTLEFIELD] * 3
    assert bears[3].zone == source.zone == Zone.GRAVEYARD


def test_clone_retains_a_pending_counted_pick_without_mutating_the_original():
    eng = _engine()
    mine = [_creat(eng, f"m{i}") for i in range(5)]
    theirs = [_creat(eng, f"t{i}", "p2") for i in range(2)]
    _cast(eng, "Razia's Purification", RAZIA)
    _pick(eng, mine[0], "p1")
    clone = GameEngine(eng.state.clone())
    _pick(clone, clone.state.find_object(mine[1].instance_id), "p1")
    _pick(clone, clone.state.find_object(mine[2].instance_id), "p1")
    assert clone.state.pending_choice is None
    assert all(clone.state.find_object(o.instance_id).zone == Zone.BATTLEFIELD
               for o in mine[:3] + theirs)
    assert all(clone.state.find_object(o.instance_id).zone == Zone.GRAVEYARD for o in mine[3:])
    assert all(o.zone == Zone.BATTLEFIELD for o in mine)  # the original is untouched and still mid-choice
    _pick(eng, mine[3], "p1")
    _pick(eng, mine[4], "p1")
    eng.resolve_until_stable()
    assert [o.zone for o in mine] == [Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.BATTLEFIELD, Zone.BATTLEFIELD]


def test_a_leaves_trigger_sees_every_other_permanent_destroyed_with_it():
    eng = _engine()
    survivor = _creat(eng, "survivor", "p2")
    artist_card = Card(
        id="Artist", name="Artist", type_line="Creature — Vampire", is_creature=True, power=0, toughness=1,
        oracle_text="Whenever Artist or another creature dies, target opponent loses 1 life and you gain 1 life.")
    artist = _bf(eng, artist_card, "p2")
    victim = _creat(eng, "victim", "p2")
    keeper, spare = _creat(eng, "keeper"), _creat(eng, "spare")
    _cast(eng, "Divine Reckoning", RECKONING)
    _pick(eng, keeper, "p1")
    _pick(eng, survivor, "p2")
    while eng.state.pending_choice:
        eng.resolve_pending_choice("p1")
    eng.resolve_until_stable()
    assert artist.zone == victim.zone == Zone.GRAVEYARD
    # Artist, the victim and p1's spare all die together: one trigger each (RULE 603.10a).
    assert eng.state.player_by_id("p1").life == 17 and eng.state.player_by_id("p2").life == 23


@pytest.mark.parametrize("params", [
    {"keep_count": 0}, {"keep_count": 2, "rest_action": "exile"}, {"keep_count": 1, "keep_types": ["creature"]},
    {"keep_count": True},
])
def test_malformed_keep_params_fail_closed_and_move_nothing(params):
    eng = _engine()
    bears = [_creat(eng, f"b{i}") for i in range(3)]
    source = _bf(eng, _creature("Source"))
    from mtg_analyzer.game.effects.choices_actions import ChoosePlayerObjectsEffect
    effect = ChoosePlayerObjectsEffect(action="sacrifice_rest", player_scope="each_player", source=source, **params)
    effect.apply(eng.rules.context)
    assert not eng.state.pending_choice
    assert all(b.zone == Zone.BATTLEFIELD for b in bears)


@pytest.mark.parametrize("text", [
    "each player chooses up to 1 creatures they control, then sacrifices the rest.",
    "each player chooses 0 creatures they control, then sacrifices the rest.",
    "each player chooses 2 creatures they control, then exiles the rest.",
])
def test_unsupported_keep_count_templates_stay_unclaimed(text):
    assert not parse_effect_body(text)


@pytest.mark.full_cache
@pytest.mark.parametrize("name", [
    "Razia's Purification", "Divine Reckoning", "Covetous Elegy", "Single Combat", "Fall of the First Civilization",
    "Urza's Sylex", "Planar Overlay", "Consuming Tide",
])
def test_every_real_card_of_the_family_is_modeled(name):
    from test_par157_back_selections import _cached
    assert parse_oracle(_cached(name)).modeled


def test_each_opponent_keep_scope_destroy_all_other_permanents_reaches_the_casters_board():
    # BUG-5: a victim_filter wipe covers every player's permanents, not just the choosing players'. No printed card
    # pairs "each opponent" with "destroy all other", so the Sylex ability text is re-scoped.
    eng = _engine()
    mine = _put(eng, "mine", "Basic Land — Forest", is_land=True)
    my_bear = _creat(eng, "bear")
    theirs = [_put(eng, f"T{i}", "Basic Land — Forest", "p2", is_land=True) for i in range(3)]
    their_bear = _creat(eng, "tbear", "p2")
    text = SYLEX_ABILITY.replace("Each player chooses six", "Each opponent chooses two")
    card = Card(id="Urza's Sylex", name="Urza's Sylex", type_line="Legendary Artifact", oracle_text=text,
                mana_cost_string="{3}", converted_mana_cost=3)
    assert parse_oracle(card).modeled
    wipe = _bf(eng, card)
    eng.state.player_by_id("p1").mana_pool.add_many({"W": 2, "C": 2})
    eng.activate_ability(eng.state.player_by_id("p1"), wipe, 0)
    eng.resolve_until_stable()
    for land in theirs[:2]:
        _pick(eng, land, "p2")
    eng.resolve_until_stable()
    assert _where(*theirs[:2]) == [Zone.BATTLEFIELD] * 2
    assert mine.zone == my_bear.zone == theirs[2].zone == their_bear.zone == Zone.GRAVEYARD
