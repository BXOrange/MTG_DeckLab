"""Hand-authored singletons, Batch 2 (Commander Cube), worker E: Aerial Extortionist, Agadeem's Awakening,
Archfiend of Spite, Aven Interrupter, Azra Oddsmaker, Azure Fleet Admiral, Barad-dûr, Barrin Tolarian Archmage,
Battle for Bretagard, Benevolent Offering. Each test executes the card in a real GameEngine."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.services.card_database import CardDatabase


def named(name: str) -> Card:
    return CardDatabase(DB_PATH).get_card(name)


def engine_2p() -> tuple[GameEngine, GameState]:
    state = GameState(players=[Player(id="p1", name="Alice", life=20), Player(id="p2", name="Bob", life=20)])
    return GameEngine(state), state


def to_bf(state: GameState, card: Card, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    obj.controller_id = controller
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def to_zone(state: GameState, card: Card, zone: Zone, controller: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=controller, zone=zone)
    bind_from_catalogue(obj)
    player = state.player_by_id(controller)
    {Zone.HAND: player.hand, Zone.GRAVEYARD: player.graveyard}[zone].append(obj)
    return obj


def vanilla(name: str, power: int = 2, toughness: int = 2, type_line: str = "Creature — Bear", cmc: int = 0) -> Card:
    return Card(id=name, name=name, type_line=type_line, is_creature=True, power=power, toughness=toughness,
                converted_mana_cost=cmc)


def drain(engine: GameEngine) -> None:
    """Resolve the stack, answering every pending choice with its first option."""
    engine.resolve_until_stable()
    while engine.state.pending_choice is not None:
        options = engine.state.pending_choice.get("options") or []
        if not options:
            break
        engine.rules.resolve_choice(str(options[0]["id"]))
        engine.resolve_until_stable()


def enter(engine: GameEngine, obj: GameObject) -> None:
    engine.state.fire_event(
        GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id)
    )
    drain(engine)


def reach_main(engine: GameEngine) -> None:
    engine.begin_turn()
    while engine.state.active_player.id != "p1":
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


# --- Barad-dûr -----------------------------------------------------------------------------------------------------

def test_barad_dur_amass_x_needs_a_death_this_turn():
    engine, state = engine_2p()
    reach_main(engine)
    land = to_bf(state, named("Barad-dûr"))
    p1 = state.player_by_id("p1")
    ability = land.activated_abilities[0]
    p1.mana_pool.add("B", 5)
    assert not engine.can_activate(p1, land, ability)  # RULE 602.5b: no creature died yet

    # A creature dies -> the gate opens; X=2 costs {X}{X}{B} = 5 mana and makes a 0/0 Army with two counters.
    victim = to_bf(state, vanilla("Victim", 1, 1))
    engine.rules.destroy(victim)
    drain(engine)
    assert sum(state.creatures_died_this_turn.values()) >= 1
    assert engine.can_activate(p1, land, ability)
    engine.activate_ability(p1, land, ability_index=0, x=2)
    drain(engine)
    armies = [o for o in state.battlefield if "Army" in o.card.type_line]
    assert len(armies) == 1 and armies[0].counters.get("+1/+1", 0) == 2


# --- Azure Fleet Admiral ---------------------------------------------------------------------------------------------

def test_azure_fleet_admiral_becomes_monarch_and_evades_the_monarchs_creatures():
    from mtg_analyzer.game import combat

    engine, state = engine_2p()
    admiral = to_bf(state, named("Azure Fleet Admiral"))
    enter(engine, admiral)
    assert state.monarch_id == "p1"  # RULE 725.1: ETB makes its controller the monarch

    blocker = to_bf(state, vanilla("Opp Bear"), controller="p2")
    engine.recompute_continuous_effects()
    # The monarch is p1, so p2's creature may still block...
    assert combat.blocker_allowed(admiral, blocker, state=state)
    # ...until p2 takes the monarchy (RULE 725.2): now the restriction bites.
    state.monarch_id = "p2"
    assert not combat.blocker_allowed(admiral, blocker, state=state)
    other = to_bf(state, vanilla("My Bear"), controller="p1")
    assert combat.blocker_allowed(admiral, other, state=state)


# --- Barrin, Tolarian Archmage ---------------------------------------------------------------------------------------

def to_end_step(engine: GameEngine) -> None:
    """Fire the active player's end-step STEP_BEGIN (what the turn loop does) and resolve what it triggers."""
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end", player_id=engine.state.active_player.id))
    drain(engine)


def test_barrin_draws_at_end_step_only_if_a_permanent_went_to_your_hand():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    for _ in range(3):
        p1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))

    # Control: nothing bounced -> no draw at the end step.
    barrin = to_bf(state, named("Barrin, Tolarian Archmage"))
    hand_before = len(p1.hand)
    to_end_step(engine)
    assert len(p1.hand) == hand_before

    # A permanent of ours returns to our hand during the turn -> the end-step trigger draws (RULE 603.4 intervening if).
    engine2, state2 = engine_2p()
    reach_main(engine2)
    q1 = state2.player_by_id("p1")
    for _ in range(3):
        q1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))
    to_bf(state2, named("Barrin, Tolarian Archmage"))
    mine = to_bf(state2, vanilla("My Bear"))
    engine2.rules.return_to_hand(mine)
    hand_before = len(q1.hand)
    to_end_step(engine2)
    assert len(q1.hand) == hand_before + 1


def test_barrin_ignores_a_permanent_returned_to_an_opponents_hand():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))
    to_bf(state, named("Barrin, Tolarian Archmage"))
    theirs = to_bf(state, vanilla("Their Bear"), controller="p2")
    engine.rules.return_to_hand(theirs)
    hand_before = len(p1.hand)
    to_end_step(engine)
    assert len(p1.hand) == hand_before  # it went to p2's hand, not "your hand"


def cast(engine: GameEngine, card_obj: GameObject, pool: dict[str, int], targets=None) -> None:
    p = engine.state.player_by_id(card_obj.controller_id)
    engine.state.current_step = "main1"
    for color, n in pool.items():
        p.mana_pool.add(color, n)
    engine.cast_spell(p, card_obj, targets=targets, target_groups=None)
    drain(engine)


# --- Azra Oddsmaker ------------------------------------------------------------------------------------------------

def begin_combat(engine: GameEngine) -> None:
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id=engine.state.active_player.id))
    engine.resolve_until_stable()


def test_azra_oddsmaker_discard_picks_a_creature_whose_combat_hit_draws_two():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    to_bf(state, named("Azra Oddsmaker"))
    hitter = to_bf(state, vanilla("Hitter", 3, 3))
    bystander = to_bf(state, vanilla("Bystander", 3, 3))
    fodder = to_zone(state, vanilla("Fodder"), Zone.HAND)
    for _ in range(4):
        p1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))
    begin_combat(engine)
    pc = state.pending_choice
    assert pc is not None, "the optional discard must be offered"
    # Answer the "you may discard" prompt with yes / the fodder, then choose `hitter` for the creature pick.
    for _ in range(6):
        pc = state.pending_choice
        if pc is None:
            break
        options = pc.get("options") or pc.get("eligible") or []
        pick = next((o for o in options if o.get("label") == "Hitter"), None) \
            or next((o for o in options if o.get("label") == "Fodder"), None) or (options[0] if options else None)
        engine.rules.resolve_choice(str(pick.get("id", pick.get("instance_id"))) if pick else "yes")
        engine.resolve_until_stable()
    assert fodder.zone == Zone.GRAVEYARD  # RULE 118.3: the discard was paid
    hand_before = len(p1.hand)
    # The unchosen creature's combat hit draws nothing...
    engine.rules.deal_damage(p2, 3, source=bystander, combat=True)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before
    # ...the chosen one's draws two (RULE 603.7a: delayed trigger for the turn).
    engine.rules.deal_damage(p2, 3, source=hitter, combat=True)
    engine.resolve_until_stable()
    assert len(p1.hand) == hand_before + _CARDS_DRAWN_AZRA


_CARDS_DRAWN_AZRA = 2


# --- Battle for Bretagard ------------------------------------------------------------------------------------------

def make_token(state: GameState, name: str, type_line: str = "Creature — Warrior", controller: str = "p1") -> GameObject:
    creature = "Creature" in type_line
    card = Card(id=name, name=name, type_line=type_line, is_creature=creature,
                power=1 if creature else None, toughness=1 if creature else None)
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD, is_token=True)
    obj.controller_id = controller
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def chapter(engine: GameEngine, saga: GameObject, number: int) -> None:
    engine.state.fire_event(
        GameEvent(EventType.SAGA_CHAPTER, chapter=number, controller_id=saga.controller_id, instance_id=saga.instance_id)
    )
    engine.resolve_until_stable()


def test_battle_for_bretagard_chapters_make_warriors_then_copy_one_token_per_name():
    engine, state = engine_2p()
    reach_main(engine)
    saga = to_bf(state, named("Battle for Bretagard"))  # enters with a lore counter: chapter I triggers by itself
    engine.resolve_until_stable()
    chapter(engine, saga, 2)
    names = sorted(o.name for o in state.battlefield if o.is_token)
    assert names == ["Elf Warrior", "Human Warrior"]  # chapters I and II

    make_token(state, "Human Warrior")  # a second token with the first one's name
    make_token(state, "Treasure", "Artifact — Treasure")
    make_token(state, "Opp Token", controller="p2")  # not ours: never copyable
    before = sorted(o.name for o in state.battlefield if o.is_token and o.controller_id == "p1")
    assert before == ["Elf Warrior", "Human Warrior", "Human Warrior", "Treasure"]

    chapter(engine, saga, 3)
    # Offered: one representative per name (3 names) -- pick all of them through the one-at-a-time chooser.
    for _ in range(6):
        pc = state.pending_choice
        if pc is None:
            break
        engine.rules.resolve_choice(str(pc["options"][0]["id"]))
        engine.resolve_until_stable()
    after = sorted(o.name for o in state.battlefield if o.is_token and o.controller_id == "p1")
    # Each distinct name is copied exactly once: the doubled "Human Warrior" gains one copy, not two.
    assert after == ["Elf Warrior", "Elf Warrior", "Human Warrior", "Human Warrior", "Human Warrior",
                     "Treasure", "Treasure"]
    assert sum(o.name == "Opp Token" for o in state.battlefield) == 1


# --- Agadeem's Awakening //Agadeem, the Undercrypt -----------------------------------------------------------------

def test_agadeems_awakening_returns_creatures_of_pairwise_distinct_mana_values_up_to_x():
    import pytest

    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    yard = {name: to_zone(state, vanilla(name, cmc=mv), Zone.GRAVEYARD)
            for name, mv in (("Dead1", 1), ("Dead2a", 2), ("Dead2b", 2), ("Dead3", 3), ("Dead5", 5))}
    spell = to_zone(state, named("Agadeem's Awakening // Agadeem, the Undercrypt"), Zone.HAND)
    p1.mana_pool.add("B", 3)
    p1.mana_pool.add("C", 3)
    # Two cards of one mana value, or one above X, are illegal target lists (RULE 601.2c).
    with pytest.raises(ValueError):
        engine.cast_spell(p1, spell, targets=[yard["Dead2a"], yard["Dead2b"]], target_groups=None, x=3)
    with pytest.raises(ValueError):
        engine.cast_spell(p1, spell, targets=[yard["Dead5"]], target_groups=None, x=3)
    engine.cast_spell(p1, spell, targets=[yard["Dead1"], yard["Dead2a"], yard["Dead3"]], target_groups=None, x=3)
    drain(engine)
    assert {o.name for o in state.battlefield} == {"Dead1", "Dead2a", "Dead3"}
    assert yard["Dead2b"].zone == Zone.GRAVEYARD and yard["Dead5"].zone == Zone.GRAVEYARD


# --- Aerial Extortionist -------------------------------------------------------------------------------------------

def test_aerial_extortionist_exiles_a_permanent_its_owner_may_cast_and_draws_off_non_hand_casts():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    for _ in range(3):
        p1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))
    victim = to_bf(state, vanilla("Opp Ogre", 3, 3, cmc=3), controller="p2")
    land = to_bf(state, Card(id="Plains", name="Plains", type_line="Basic Land — Plains", is_land=True), controller="p2")
    extortionist = to_bf(state, named("Aerial Extortionist"))
    enter(engine, extortionist)
    # The pending target is chosen by `drain` (first option); a land is never a legal target.
    assert land.zone == Zone.BATTLEFIELD
    assert victim.zone == Zone.EXILE  # RULE 406: exiled
    # The standing "its owner may cast it" permission belongs to p2 (the card's owner), not to the exiler.
    assert state.exile_cast_condition.get(victim.instance_id, (None,))[0] == "p2"

    # Another player casting from exile (not from their hand) draws us a card; a hand cast does not.
    hand_before = len(p1.hand)
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", instance_id=victim.instance_id,
                               from_hand=False, from_zone="exile"))
    drain(engine)
    assert len(p1.hand) == hand_before + 1
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p2", instance_id=999,
                               from_hand=True, from_zone="hand"))
    drain(engine)
    assert len(p1.hand) == hand_before + 1
    # ...and our own non-hand casts never trigger it ("another player").
    state.fire_event(GameEvent(EventType.SPELL_CAST, player_id="p1", instance_id=998,
                               from_hand=False, from_zone="graveyard"))
    drain(engine)
    assert len(p1.hand) == hand_before + 1


def test_aerial_extortionist_combat_damage_trigger_exiles_too():
    engine, state = engine_2p()
    reach_main(engine)
    p2 = state.player_by_id("p2")
    victim = to_bf(state, vanilla("Opp Ogre", 3, 3, cmc=3), controller="p2")
    extortionist = to_bf(state, named("Aerial Extortionist"))
    engine.rules.deal_damage(p2, 3, source=extortionist, combat=True)
    drain(engine)
    assert victim.zone == Zone.EXILE


# --- Aven Interrupter ----------------------------------------------------------------------------------------------

def test_aven_interrupter_exiles_a_spell_which_its_owner_casts_free_as_a_sorcery_on_a_later_turn():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    for _ in range(3):
        p1.library.append(GameObject(vanilla("Lib"), owner_id="p1", zone=Zone.LIBRARY))
    cantrip = Card(id="Test Cantrip", name="Test Cantrip", type_line="Instant", is_instant=True,
                   mana_cost_string="{1}{U}", converted_mana_cost=2, oracle_text="Draw a card.")
    spell = to_zone(state, cantrip, Zone.HAND)
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    assert any(item.obj is spell for item in state.stack)  # it is a spell on the stack, unresolved

    aven = to_bf(state, named("Aven Interrupter"), controller="p2")
    enter(engine, aven)
    assert spell.zone == Zone.EXILE and spell.plotted_card  # RULE 702.170: exiled and plotted, not countered
    assert not any(item.obj is spell for item in state.stack)
    assert not engine.can_cast(p1, spell)  # not on the turn it became plotted

    # Later turn (p1's next one): free, sorcery speed, owner only.
    hand_before = len(p1.hand)
    engine.begin_turn()
    while state.active_player.id != "p1":
        engine.begin_turn()
    state.current_step = "main1"
    assert not engine.can_cast(p2, spell)
    # Free of its mana cost, but Aven's own tax still applies to opponents' exile casts: {2} (RULE 601.2f / 118.9d).
    assert not engine.can_cast(p1, spell)
    p1.mana_pool.add("C", 2)
    assert engine.can_cast(p1, spell)
    engine.cast_spell(p1, spell, targets=None, target_groups=None)
    drain(engine)
    assert len(p1.hand) == hand_before + 1  # the plotted cantrip resolved and drew a card


def test_aven_interrupter_taxes_only_opponents_spells_cast_from_graveyard_or_exile():
    from mtg_analyzer.game import continuous

    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    to_bf(state, named("Aven Interrupter"), controller="p1")
    engine.recompute_continuous_effects()
    card = Card(id="Tax Probe", name="Tax Probe", type_line="Sorcery", is_sorcery=True,
                mana_cost_string="{2}", converted_mana_cost=2)
    from_hand = to_zone(state, card, Zone.HAND, controller="p2")
    from_gy = to_zone(state, card, Zone.GRAVEYARD, controller="p2")
    mine_gy = to_zone(state, card, Zone.GRAVEYARD, controller="p1")
    assert continuous.cost_reduction_for(state, p2, from_hand)[0] == 0
    assert continuous.cost_reduction_for(state, p2, from_gy)[0] == -2  # RULE 601.2f: {2} more
    assert continuous.cost_reduction_for(state, p1, mine_gy)[0] == 0  # Aven's own controller is not taxed


# --- Archfiend of Spite --------------------------------------------------------------------------------------------

def test_archfiend_of_spite_punishes_only_opponent_sources_and_lets_them_sacrifice_instead():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    archfiend = to_bf(state, named("Archfiend of Spite"))
    own = to_bf(state, vanilla("Own Pinger"))
    theirs = to_bf(state, vanilla("Their Pinger"), controller="p2")
    fodder = [to_bf(state, vanilla(f"Fodder{i}", 1, 1), controller="p2") for i in range(2)]

    # Damage from our own source: no trigger (the filter is "an opponent controls").
    engine.rules.deal_damage(archfiend, 1, source=own)
    drain(engine)
    assert state.pending_choice is None and p1.life == 20

    # Damage from p2's source: p2 may pay 2 permanents or lose 2 life. Declining loses the life.
    engine.rules.deal_damage(archfiend, 2, source=theirs)
    engine.resolve_until_stable()
    pc = state.pending_choice
    assert pc is not None and pc.get("kind") == "pay_cost_then"
    engine.rules.resolve_choice("decline")
    engine.resolve_until_stable()
    assert p2.life == 18 and p1.life == 20  # RULE 118.12: the *source's* controller loses it

    # Paying: sacrifice that many permanents of their choice instead of losing life.
    engine.rules.deal_damage(archfiend, 1, source=theirs)
    engine.resolve_until_stable()
    engine.rules.resolve_choice("pay")
    drain(engine)
    assert p2.life == 18
    assert sum(1 for o in state.battlefield if o.controller_id == "p2") == 2


# --- Benevolent Offering -------------------------------------------------------------------------------------------

def test_benevolent_offering_tokens_for_both_then_life_for_each_creature():
    engine, state = engine_2p()
    reach_main(engine)
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    to_bf(state, vanilla("Opp Bear"), controller="p2")
    spell = to_zone(state, named("Benevolent Offering"), Zone.HAND)
    cast(engine, spell, {"W": 1, "C": 3})
    spirits = [o for o in state.battlefield if "Spirit" in o.card.type_line]
    assert sum(o.controller_id == "p1" for o in spirits) == 3  # three 1/1 flyers each
    assert sum(o.controller_id == "p2" for o in spirits) == 3
    # Second clause counts the freshly made tokens: p1 has 3 creatures, p2 has 3 + the Bear.
    assert p1.life == 20 + 2 * 3
    assert p2.life == 20 + 2 * 4
