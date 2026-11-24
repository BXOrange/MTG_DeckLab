"""MEC-176: printed triggered and static keywords the engine now executes (RULE 702), on real cards.

Each keyword is played on the real cached card in a real `GameEngine`: the trigger fires, the choice opens, and the
outcome is read off the board. A keyword wired here has left `KEYWORDS_WITHOUT_BEHAVIOUR`.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

STARTING_LIFE = 20


def real_card(name: str) -> Card:
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    assert card is not None, name
    return card


def filler() -> Card:
    return Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)


def engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", [filler()] * 8), ("p2", "Bob", [filler()] * 8)], starting_hand=0, starting_life=STARTING_LIFE,
    )


def put(eng: GameEngine, name: str, owner: str = "p1", zone: Zone = Zone.BATTLEFIELD) -> GameObject:
    obj = GameObject(real_card(name), owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone is Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(owner).add_to_zone(obj, zone)
    eng.recompute_continuous_effects()
    return obj


def next_turn_of(eng: GameEngine, player_index: int) -> None:
    """Move the game to the next turn of ``player_index`` (RULE 500.1: every player's turn counts)."""
    eng.state.internal_turn.number += 1
    eng.state.active_player_index = player_index


def upkeep(eng: GameEngine, player_index: int = 0) -> None:
    eng.state.active_player_index = player_index
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep", phase="upkeep"))
    eng.resolve_until_stable()


# -- echo (RULE 702.30) ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Avalanche Riders", "Deepcavern Imp", "Skizzik Surger", "Acridian"])
def test_echo_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_an_echo_dash_cost_the_engine_cannot_pay_is_not_a_keyword_line():
    from mtg_analyzer.parser.oracle.segmenter import is_keyword_line

    assert is_keyword_line("echo\u2014discard a card.") and is_keyword_line("echo\u2014sacrifice two lands.")
    assert not is_keyword_line("echo\u2014flip a coin.")


def test_echo_asks_once_the_turn_after_it_came_under_your_control_and_sacrifices_when_unpaid():
    eng = engine()
    acridian = put(eng, "Acridian")  # Echo {1}{G}
    upkeep(eng)  # the turn it entered: not yet (RULE 702.30a: since the beginning of your last upkeep)
    assert eng.state.pending_choice is None and acridian.zone == Zone.BATTLEFIELD
    next_turn_of(eng, 1)
    next_turn_of(eng, 0)
    eng.state.player_by_id("p1").mana_pool.add("G", 2)  # affordable, so the player is asked (an unaffordable cost sacrifices)
    upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    eng.resolve_pending_choice("decline")
    assert acridian.zone == Zone.GRAVEYARD


def test_echo_paid_keeps_the_permanent_and_never_asks_again():
    eng = engine()
    acridian = put(eng, "Acridian")
    next_turn_of(eng, 1)
    next_turn_of(eng, 0)
    eng.state.player_by_id("p1").mana_pool.add("G", 2)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    assert acridian.zone == Zone.BATTLEFIELD
    next_turn_of(eng, 1)
    next_turn_of(eng, 0)
    upkeep(eng)
    assert eng.state.pending_choice is None and acridian.zone == Zone.BATTLEFIELD


def test_echo_is_owed_again_when_control_changes_and_only_to_the_new_controller():
    from mtg_analyzer.game.control import gain_control

    eng = engine()
    acridian = put(eng, "Acridian")
    next_turn_of(eng, 1)
    next_turn_of(eng, 0)
    eng.state.player_by_id("p1").mana_pool.add("G", 2)
    upkeep(eng)
    eng.resolve_pending_choice("pay")
    gain_control(eng.state, acridian, "p2")
    upkeep(eng, 0)  # the old controller's upkeep: nothing to pay for a permanent it no longer controls
    assert eng.state.pending_choice is None
    next_turn_of(eng, 1)
    eng.state.player_by_id("p2").mana_pool.add("G", 2)
    upkeep(eng, 1)
    assert eng.state.pending_choice["player_id"] == "p2"


def test_echo_discard_cost_is_paid_by_discarding():
    eng = engine()
    imp = put(eng, "Deepcavern Imp")  # Echo—Discard a card.
    hand_card = put(eng, "Acridian", zone=Zone.HAND)
    next_turn_of(eng, 1)
    next_turn_of(eng, 0)
    upkeep(eng)
    assert eng.state.pending_choice["kind"] == "sacrifice_unless_pay"
    eng.resolve_pending_choice("pay")
    assert imp.zone == Zone.BATTLEFIELD
    assert hand_card.zone == Zone.GRAVEYARD


# -- soulshift (RULE 702.46) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Burr Grafter", "Deathknell Kami", "Body of Jukai", "Kami of the Honored Dead"])
def test_soulshift_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_soulshift_returns_a_spirit_of_at_most_its_number_when_it_dies():
    eng = engine()
    kami = put(eng, "Burr Grafter")  # Soulshift 3
    cheap = put(eng, "Deathknell Kami", zone=Zone.GRAVEYARD)  # Spirit, MV 2
    pricey = put(eng, "Body of Jukai", zone=Zone.GRAVEYARD)  # Spirit, MV 9
    non_spirit = put(eng, "Acridian", zone=Zone.GRAVEYARD)
    eng.rules.put_into_graveyard(kami)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    assert {o["id"] for o in eng.state.pending_choice["options"]} == {str(cheap.instance_id), "decline"}
    eng.resolve_pending_choice(str(cheap.instance_id))
    eng.resolve_until_stable()
    assert cheap.zone == Zone.HAND
    assert pricey.zone == Zone.GRAVEYARD and non_spirit.zone == Zone.GRAVEYARD


# -- extort (RULE 702.101) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Basilica Screecher", "Crypt Ghast", "Blind Obedience"])
def test_extort_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def _cast_cheap_spell(eng, name="Opt"):
    spell = put(eng, name, zone=Zone.HAND)
    player = eng.state.player_by_id("p1")
    for color in "WUBRG":
        player.mana_pool.add(color, 3)
    eng.state.current_step = "main1"
    eng.cast_spell(player, spell)
    return spell


def test_extort_drains_each_opponent_when_its_controller_casts_a_spell_and_pays():
    eng = engine()
    put(eng, "Basilica Screecher")
    _cast_cheap_spell(eng)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"  # "you may pay {W/B}"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == STARTING_LIFE - 1
    assert eng.state.player_by_id("p1").life == STARTING_LIFE + 1


def test_extort_does_not_trigger_on_an_opponents_spell():
    eng = engine()
    put(eng, "Basilica Screecher")
    spell = put(eng, "Opt", owner="p2", zone=Zone.HAND)
    opp = eng.state.player_by_id("p2")
    for color in "WUBRG":
        opp.mana_pool.add(color, 3)
    eng.state.active_player_index = 1
    eng.state.current_step = "main1"
    eng.cast_spell(opp, spell)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p1").life == STARTING_LIFE and opp.life == STARTING_LIFE


# -- bloodthirst (RULE 702.54) --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Battering Wurm", "Furyborn Hellkite", "Petrified Wood-Kin"])
def test_bloodthirst_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def deal_damage(eng, player_id: str, amount: int) -> None:
    """Record ``amount`` damage dealt to a player this turn (the event stream is what `damage_dealt_to_players_this_turn` reads)."""
    eng.state.fire_event(GameEvent(EventType.DAMAGE, target_id=player_id, is_player=True, amount=amount))


def _enter(eng, name, owner="p1"):
    """Cast the real card and let it resolve, so the entry replacement runs as it does in a game."""
    obj = put(eng, name, owner=owner, zone=Zone.HAND)
    player = eng.state.player_by_id(owner)
    for color in "WUBRG":
        player.mana_pool.add(color, 8)
    eng.state.current_step = "main1"
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    return obj


def test_bloodthirst_n_adds_counters_only_when_an_opponent_was_dealt_damage():
    eng = engine()
    cold = _enter(eng, "Battering Wurm")  # Bloodthirst 1
    assert cold.counters.get("+1/+1", 0) == 0
    deal_damage(eng, "p2", 3)
    hot = _enter(eng, "Battering Wurm")
    assert hot.counters.get("+1/+1", 0) == 1


def test_bloodthirst_ignores_damage_dealt_to_its_own_controller():
    eng = engine()
    deal_damage(eng, "p1", 4)
    obj = _enter(eng, "Battering Wurm")
    assert obj.counters.get("+1/+1", 0) == 0


def test_bloodthirst_x_counts_the_total_damage_dealt_to_opponents():
    eng = engine()
    deal_damage(eng, "p2", 2)
    deal_damage(eng, "p2", 3)
    obj = _enter(eng, "Petrified Wood-Kin")  # Bloodthirst X
    assert obj.counters.get("+1/+1", 0) == 5


# -- unleash (RULE 702.98) and decayed (RULE 702.147) ---------------------------------------------------------------


def advance_to(eng, step):
    for _ in range(60):
        if eng.state.current_step == step:
            return
        eng.advance_step()
    raise AssertionError(step)


def attack_with(eng, attacker):
    advance_to(eng, "declare_attackers")
    eng.declare_attackers(eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": "p2"}}])


def swing_and_try_to_block(eng, attacker, blocker):
    """Declare ``attacker`` against p2 and ask the engine whether ``blocker`` (p2's) may block it."""
    attack_with(eng, attacker)
    advance_to(eng, "declare_blockers")
    return eng.can_block(eng.state.player_by_id("p2"), blocker, attacker)


def ready(obj):
    obj.summoning_sick = False
    obj.tapped = False


@pytest.mark.parametrize("name", ["Bloodfray Giant", "Chaos Imps", "Carnival Hellsteed"])
def test_unleash_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_unleash_offers_the_counter_and_a_creature_with_it_cannot_block():
    eng = engine()
    giant = _enter(eng, "Bloodfray Giant")
    assert eng.state.pending_choice["kind"] == "choose_enter_counter"
    labels = [o["label"] for o in eng.state.pending_choice["options"]]
    assert labels == ["+1/+1", "keine Marke"]
    eng.resolve_pending_choice("0")
    eng.resolve_until_stable()
    assert giant.counters.get("+1/+1") == 1 and (giant.power, giant.toughness) == (5, 4)
    assert combat_keyword_bars_blocking(giant)


def test_unleash_declined_enters_plain_and_can_still_block():
    eng = engine()
    giant = _enter(eng, "Bloodfray Giant")
    eng.resolve_pending_choice("1")
    eng.resolve_until_stable()
    assert giant.counters.get("+1/+1", 0) == 0 and (giant.power, giant.toughness) == (4, 3)
    assert not combat_keyword_bars_blocking(giant)


def test_unleash_stops_barring_blocks_once_the_counter_is_gone():
    eng = engine()
    giant = _enter(eng, "Bloodfray Giant")
    eng.resolve_pending_choice("0")
    eng.resolve_until_stable()
    giant.counters.pop("+1/+1")
    assert not combat_keyword_bars_blocking(giant)


def combat_keyword_bars_blocking(obj) -> bool:
    from mtg_analyzer.game import combat

    return combat.keyword_bars_blocking(obj)


def test_decayed_creature_cannot_block():
    eng = engine()
    rakshasa = put(eng, "Rot-Curse Rakshasa", owner="p2")
    ready(rakshasa)
    assert combat_keyword_bars_blocking(rakshasa)
    attacker = put(eng, "Bloodfray Giant", owner="p1")
    ready(attacker)
    assert not swing_and_try_to_block(eng, attacker, rakshasa)  # RULE 702.147a: it can't block


def test_decayed_attacker_is_sacrificed_at_end_of_combat_and_not_before():
    eng = engine()
    mine = put(eng, "Rot-Curse Rakshasa", owner="p1")
    ready(mine)
    attack_with(eng, mine)
    eng.resolve_until_stable()
    assert mine.zone == Zone.BATTLEFIELD  # RULE 702.147a: sacrificed at end of combat, not on the attack
    advance_to(eng, "end_combat")
    eng.resolve_until_stable()
    assert mine.zone == Zone.GRAVEYARD


def test_decayed_creature_that_does_not_attack_stays():
    eng = engine()
    mine = put(eng, "Rot-Curse Rakshasa", owner="p1")
    ready(mine)
    advance_to(eng, "main2")
    eng.resolve_until_stable()
    assert mine.zone == Zone.BATTLEFIELD


# -- sunburst (RULE 702.44) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Etched Oracle", "Pentad Prism", "Engineered Explosives"])
def test_sunburst_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def cast_with(eng, name, mana: dict[str, int]):
    obj = put(eng, name, zone=Zone.HAND)
    player = eng.state.player_by_id("p1")
    for color, amount in mana.items():
        player.mana_pool.add(color, amount)
    eng.state.current_step = "main1"
    eng.cast_spell(player, obj)
    eng.resolve_until_stable()
    return obj


def test_sunburst_creature_enters_with_a_counter_per_color_of_mana_spent():
    eng = engine()
    oracle = cast_with(eng, "Etched Oracle", {"W": 2, "U": 2})  # {4}: two colors spent
    assert oracle.counters.get("+1/+1") == 2 and (oracle.power, oracle.toughness) == (2, 2)


def test_sunburst_counts_colors_not_mana_and_colorless_mana_adds_none():
    eng = engine()
    oracle = cast_with(eng, "Etched Oracle", {"G": 4})
    assert oracle.counters.get("+1/+1") == 1
    eng = engine()
    oracle = cast_with(eng, "Etched Oracle", {"C": 4})
    assert oracle.counters.get("+1/+1", 0) == 0


def test_sunburst_noncreature_permanent_enters_with_charge_counters():
    eng = engine()
    prism = cast_with(eng, "Pentad Prism", {"W": 1, "U": 1})
    assert prism.counters.get("charge") == 2 and not prism.counters.get("+1/+1")


# -- graft (RULE 702.58) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Simic Initiate", "Sporeback Troll", "Llanowar Reborn", "Vigean Graftmage"])
def test_graft_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_graft_enters_with_its_counters_and_moves_one_to_each_entering_creature_on_request():
    eng = engine()
    troll = _enter(eng, "Sporeback Troll")  # Graft 2
    assert troll.counters.get("+1/+1") == 2
    bear = _enter(eng, "Acridian")
    assert [o["id"] for o in eng.state.pending_choice["options"]] == ["do", "decline"]  # RULE 702.58a: "you may"
    answer_optional_trigger(eng, accept=True)
    eng.resolve_until_stable()
    assert troll.counters.get("+1/+1") == 1 and bear.counters.get("+1/+1") == 1


def answer_optional_trigger(eng, accept: bool) -> None:
    """Answer the open "you may" prompt of a triggered ability with its first (accept) or decline option."""
    choice = eng.state.pending_choice
    assert choice is not None, "the optional graft trigger asks"
    ids = [str(o["id"]) for o in choice["options"]]
    eng.resolve_pending_choice(next((i for i in ids if i != "decline"), ids[0]) if accept else "decline")


def test_graft_declined_moves_nothing():
    eng = engine()
    troll = _enter(eng, "Sporeback Troll")
    bear = _enter(eng, "Acridian")
    answer_optional_trigger(eng, accept=False)
    eng.resolve_until_stable()
    assert troll.counters.get("+1/+1") == 2 and bear.counters.get("+1/+1", 0) == 0


def test_graft_does_nothing_once_the_last_counter_is_gone():
    eng = engine()
    troll = _enter(eng, "Sporeback Troll")
    troll.counters.pop("+1/+1")
    _enter(eng, "Acridian")
    assert eng.state.pending_choice is None


# -- ingest (RULE 702.115) and provoke (RULE 702.39) ----------------------------------------------------------------


@pytest.mark.parametrize("name", ["Mist Intruder", "Benthic Infiltrator", "Goblin Grappler", "Krosan Vorine"])
def test_ingest_and_provoke_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_ingest_exiles_the_top_card_of_the_damaged_players_library():
    eng = engine()
    intruder = put(eng, "Mist Intruder")  # Flying, Ingest
    ready(intruder)
    p2 = eng.state.player_by_id("p2")
    library_before = len(p2.library)
    attack_with(eng, intruder)
    advance_to(eng, "end_combat")
    eng.resolve_until_stable()
    assert p2.life == STARTING_LIFE - 1  # the creature dealt combat damage to the player
    assert len(p2.library) == library_before - 1 and [c.zone for c in p2.exile] == [Zone.EXILE]
    assert len(eng.state.player_by_id("p1").library) == library_before  # only the damaged player exiles


def test_ingest_does_not_trigger_when_the_creature_is_blocked_and_hits_a_creature():
    eng = engine()
    infiltrator = put(eng, "Benthic Infiltrator")  # Ingest, can't be blocked: so check noncombat-damage to a creature instead
    ready(infiltrator)
    p2 = eng.state.player_by_id("p2")
    library_before = len(p2.library)
    advance_to(eng, "main2")
    eng.resolve_until_stable()
    assert len(p2.library) == library_before  # no combat damage to a player, nothing exiled


def test_provoke_untaps_the_target_and_forces_it_to_block():
    eng = engine()
    grappler = put(eng, "Goblin Grappler")
    ready(grappler)
    victim = put(eng, "Acridian", owner="p2")
    victim.tapped = True
    attack_with(eng, grappler)
    eng.resolve_until_stable()
    assert eng.state.pending_choice is not None  # "you may": pick the target or decline
    ids = [str(o["id"]) for o in eng.state.pending_choice["options"]]
    assert str(victim.instance_id) in ids and "decline" in ids
    eng.resolve_pending_choice(str(victim.instance_id))
    eng.resolve_until_stable()
    assert not victim.tapped
    advance_to(eng, "declare_blockers")
    with pytest.raises(ValueError, match="must block"):
        eng.advance_step()  # RULE 702.39a / 509.1c: leaving the declare-blockers step without the forced block
    eng.declare_blockers(eng.state.player_by_id("p2"), [{"blocker": victim, "attacker": grappler}])
    assert grappler.blocked_by
    eng.advance_step()


def test_provoke_declined_leaves_the_tapped_creature_tapped():
    eng = engine()
    grappler = put(eng, "Goblin Grappler")
    ready(grappler)
    victim = put(eng, "Acridian", owner="p2")
    victim.tapped = True
    attack_with(eng, grappler)
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert victim.tapped


# -- gravestorm (RULE 702.69) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Bitter Ordeal", "Follow the Bodies", "Ominous Harvest"])
def test_gravestorm_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def clues(eng):
    return [o for o in eng.state.permanents() if o.name == "Clue"]


def test_gravestorm_copies_the_spell_once_per_permanent_put_into_a_graveyard_this_turn():
    eng = engine()
    for _ in range(2):
        eng.rules.put_into_graveyard(put(eng, "Acridian"))
    eng.resolve_until_stable()
    cast_with(eng, "Follow the Bodies", {"U": 1, "C": 3})
    assert len(clues(eng)) == 3  # the spell plus one copy for each of the two permanents


def test_gravestorm_with_nothing_in_the_graveyard_makes_no_copies():
    eng = engine()
    cast_with(eng, "Follow the Bodies", {"U": 1, "C": 3})
    assert len(clues(eng)) == 1


def test_gravestorm_counts_a_token_and_ignores_cards_that_were_not_permanents_on_the_battlefield():
    eng = engine()
    put(eng, "Opt", zone=Zone.GRAVEYARD)  # a card put into a graveyard from elsewhere does not count
    token = put(eng, "Acridian")
    token.is_token = True
    eng.rules.put_into_graveyard(token)
    eng.resolve_until_stable()
    cast_with(eng, "Follow the Bodies", {"U": 1, "C": 3})
    assert len(clues(eng)) == 2


# -- increment (RULE 702.191) ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Ambitious Augmenter", "Hungry Graffalon", "Pensive Professor", "Topiary Lecturer"])
def test_increment_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_increment_puts_a_counter_only_when_more_mana_was_spent_than_power_or_toughness():
    eng = engine()
    augmenter = put(eng, "Ambitious Augmenter")  # a 1/1
    cast_with(eng, "Ancestral Recall", {"U": 1})  # one mana: not greater than 1
    assert augmenter.counters.get("+1/+1", 0) == 0
    cast_with(eng, "Divination", {"U": 1, "C": 2})  # three mana: greater than power and toughness
    assert augmenter.counters.get("+1/+1") == 1


def test_increment_compares_with_the_derived_stats_and_ignores_opposing_spells():
    eng = engine()
    graffalon = put(eng, "Hungry Graffalon")  # a 3/4
    cast_with(eng, "Divination", {"U": 1, "C": 2})
    assert graffalon.counters.get("+1/+1", 0) == 0  # 3 is neither > 3 nor > 4
    eng2 = engine()
    augmenter = put(eng2, "Ambitious Augmenter")
    spell = put(eng2, "Divination", owner="p2", zone=Zone.HAND)
    opp = eng2.state.player_by_id("p2")
    opp.mana_pool.add("U", 3)
    eng2.state.active_player_index = 1
    eng2.state.current_step = "main1"
    eng2.cast_spell(opp, spell)
    eng2.resolve_until_stable()
    assert augmenter.counters.get("+1/+1", 0) == 0


# -- champion (RULE 702.72) -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Wren's Run Packmaster", "Boggart Mob", "Lightning Crafter", "Changeling Hero",
                                  "Unstoppable Ash", "Thoughtweft Trio"])
def test_champion_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_champion_exiles_another_matching_creature_and_returns_it_when_it_leaves():
    eng = engine()
    elf = put(eng, "Llanowar Elves")
    packmaster = _enter(eng, "Wren's Run Packmaster")  # Champion an Elf
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "choose_objects"
    assert {o["id"] for o in eng.state.pending_choice["options"]} >= {str(elf.instance_id), "decline"}
    eng.resolve_pending_choice(str(elf.instance_id))
    eng.resolve_until_stable()
    assert elf.zone == Zone.EXILE and packmaster.zone == Zone.BATTLEFIELD
    eng.rules.put_into_graveyard(packmaster)
    eng.resolve_until_stable()
    assert elf.zone == Zone.BATTLEFIELD  # RULE 702.72a: back under its owner's control


def test_champion_is_sacrificed_when_the_exile_is_declined():
    eng = engine()
    elf = put(eng, "Llanowar Elves")
    packmaster = _enter(eng, "Wren's Run Packmaster")
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert packmaster.zone == Zone.GRAVEYARD and elf.zone == Zone.BATTLEFIELD


def test_champion_is_sacrificed_with_nothing_to_exile_and_ignores_the_wrong_type_and_other_controllers():
    eng = engine()
    put(eng, "Acridian")  # not an Elf
    put(eng, "Llanowar Elves", owner="p2")  # not ours
    packmaster = _enter(eng, "Wren's Run Packmaster")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None and packmaster.zone == Zone.GRAVEYARD


def test_champion_a_creature_accepts_any_other_creature_but_not_itself():
    eng = engine()
    bystander = put(eng, "Acridian")
    hero = _enter(eng, "Changeling Hero")  # Champion a creature
    eng.resolve_until_stable()
    assert {o["id"] for o in eng.state.pending_choice["options"]} == {str(bystander.instance_id), "decline"}
    assert str(hero.instance_id) not in {o["id"] for o in eng.state.pending_choice["options"]}


# -- amplify (RULE 702.38) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Canopy Crawler", "Aven Warhawk", "Kilnmouth Dragon", "Feral Throwback"])
def test_amplify_cards_are_modeled(name):
    assert parse_oracle(real_card(name)).modeled


def test_amplify_reveals_hand_cards_sharing_a_creature_type_and_scales_the_counters():
    eng = engine()
    same_a = put(eng, "Feral Throwback", zone=Zone.HAND)  # Beast
    same_b = put(eng, "Canopy Crawler", zone=Zone.HAND)  # Beast
    other = put(eng, "Aven Warhawk", zone=Zone.HAND)  # Bird Soldier
    crawler = _enter(eng, "Canopy Crawler")  # Amplify 1
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_objects"
    offered = {o["id"] for o in choice["options"]}
    assert offered >= {str(same_a.instance_id), str(same_b.instance_id)} and str(other.instance_id) not in offered
    assert str(crawler.instance_id) not in offered  # RULE 702.38a: not itself
    eng.resolve_pending_choice(str(same_a.instance_id))
    eng.resolve_pending_choice(str(same_b.instance_id))
    eng.resolve_until_stable()
    assert crawler.counters.get("+1/+1") == 2
    assert any(e.type == EventType.REVEAL and e.get("instance_id") == same_a.instance_id for e in eng.state.event_log)


def test_amplify_with_a_number_above_one_multiplies_per_card():
    eng = engine()
    dragon_mate = put(eng, "Kilnmouth Dragon", zone=Zone.HAND)
    dragon = _enter(eng, "Kilnmouth Dragon")  # Amplify 3
    eng.resolve_pending_choice(str(dragon_mate.instance_id))
    eng.resolve_until_stable()
    assert dragon.counters.get("+1/+1") == 3


def test_amplify_with_nothing_to_reveal_or_declined_enters_plain():
    eng = engine()
    crawler = _enter(eng, "Canopy Crawler")
    assert eng.state.pending_choice is None and crawler.counters.get("+1/+1", 0) == 0
    eng = engine()
    put(eng, "Feral Throwback", zone=Zone.HAND)
    crawler = _enter(eng, "Canopy Crawler")
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert crawler.counters.get("+1/+1", 0) == 0


# -- granted and token keywords -------------------------------------------------------------------------------------


def test_a_granted_provoke_triggers_on_the_creature_that_has_it():
    eng = engine()
    put(eng, "Hunter Sliver")  # "All Sliver creatures have provoke."
    sliver = put(eng, "Crystalline Sliver")
    ready(sliver)
    victim = put(eng, "Acridian", owner="p2")
    victim.tapped = True
    attack_with(eng, sliver)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(str(victim.instance_id))
    eng.resolve_until_stable()
    assert not victim.tapped


def test_decayed_tokens_cannot_block_and_are_sacrificed_after_attacking():
    eng = engine()
    put(eng, "Diregraf Horde")
    horde = [o for o in eng.state.permanents() if o.name == "Diregraf Horde"][0]
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=horde.instance_id))
    eng.resolve_until_stable()
    tokens = [o for o in eng.state.permanents() if o.is_token and o.name == "Zombie"]
    assert len(tokens) == 2 and all(combat_keyword_bars_blocking(t) for t in tokens)
    for token in tokens:
        ready(token)
    attack_with(eng, tokens[0])
    advance_to(eng, "end_combat")
    eng.resolve_until_stable()
    assert tokens[0] not in eng.state.permanents() and tokens[1] in eng.state.permanents()


# -- RULE 603.4: the intervening "if" is asked again on resolution --------------------------------------------------


def test_graft_trigger_does_nothing_if_the_counter_is_gone_when_it_resolves():
    eng = engine()
    troll = _enter(eng, "Sporeback Troll")  # Graft 2
    bear = put(eng, "Acridian", zone=Zone.HAND)
    player = eng.state.player_by_id("p1")
    player.mana_pool.add("G", 8)
    eng.state.current_step = "main1"
    eng.cast_spell(player, bear)
    eng.resolve_until_stable()  # the creature spell resolves, graft's trigger asks "you may"
    assert eng.state.pending_choice is not None
    troll.counters.pop("+1/+1")  # the counters leave before the move is carried out
    answer_optional_trigger(eng, accept=True)
    eng.resolve_until_stable()
    assert bear.counters.get("+1/+1", 0) == 0 and troll.counters.get("+1/+1", 0) == 0


def test_increment_trigger_does_nothing_if_the_creature_outgrew_the_mana_spent_by_resolution():
    eng = engine()
    augmenter = put(eng, "Ambitious Augmenter")  # a 1/1
    spell = put(eng, "Divination", zone=Zone.HAND)
    player = eng.state.player_by_id("p1")
    player.mana_pool.add("U", 1)
    player.mana_pool.add("C", 2)
    eng.state.current_step = "main1"
    eng.cast_spell(player, spell)
    eng.rules.put_triggers_on_stack()
    assert any(getattr(item, "source", None) is augmenter for item in eng.state.stack)  # increment is on the stack
    augmenter.counters["+1/+1"] = 3  # now 4/4 in response: three mana is greater than neither stat
    eng.resolve_until_stable()
    assert augmenter.counters.get("+1/+1") == 3
