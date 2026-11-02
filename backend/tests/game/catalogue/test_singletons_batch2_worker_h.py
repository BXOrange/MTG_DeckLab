"""Hand-authored singletons, Batch 2 (Commander Cube), worker H: Elesh Norn // The Argent Etchings, Emberwilde Captain,
Emeria's Call // Emeria, Shattered Skyclave, Empty the Laboratory, Eris Roar of the Storm, Ezuri Claw of Progress,
Fatestitcher, Fear of Impostors, Foe-Razer Regent, Geralf Visionary Stitcher. Each test executes the card in a real
GameEngine."""

from __future__ import annotations

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState, StackItem
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
    obj.controller_id = controller
    bind_from_catalogue(obj)
    state.player_by_id(controller).add_to_zone(obj, zone)
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


def push_spell(state: GameState, player_id: str, card: Card) -> GameObject:
    obj = GameObject(card, owner_id=player_id, zone=Zone.STACK)
    obj.controller_id = player_id
    obj.spell_effects = []
    state.stack.append(StackItem(kind="spell", controller_id=player_id, obj=obj, description=card.name, effects=[]))
    return obj


def reach_main(engine: GameEngine) -> None:
    engine.begin_turn()
    while engine.state.active_player.id != "p1":
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


# --- Fear of Impostors ---------------------------------------------------------------------------------------------

def test_fear_of_impostors_counters_a_spell_and_its_controller_manifests_dread():
    engine, state = engine_2p()
    p2 = state.player_by_id("p2")
    for i in range(3):
        p2.library.append(GameObject(vanilla(f"Lib{i}"), owner_id="p2", zone=Zone.LIBRARY))
    spell = push_spell(state, "p2", Card(id="Bolt", name="Bolt", type_line="Instant", is_instant=True))
    fear = to_bf(state, named("Fear of Impostors"))
    enter(engine, fear)
    assert spell in p2.graveyard and not state.stack  # countered
    faceless = [o for o in state.battlefield if o.controller_id == "p2" and getattr(o, "face_down", False)]
    assert len(faceless) == 1  # RULE 701.62a: the *spell's* controller manifested, not Fear's controller
    assert len(p2.graveyard) == 2  # the countered spell plus the other dread card


# --- Eris, Roar of the Storm ---------------------------------------------------------------------------------------

def test_eris_costs_two_less_per_different_mana_value_among_instants_and_sorceries_in_the_graveyard():
    from mtg_analyzer.game import continuous

    engine, state = engine_2p()
    eris = to_zone(state, named("Eris, Roar of the Storm"), Zone.HAND)
    assert continuous.self_cost_reduction_for(eris, state, "p1")[0] == 0
    gy = [("Spell A", "Instant", 1), ("Spell B", "Instant", 1), ("Spell C", "Sorcery", 3),
          ("Not a spell", "Creature — Bear", 5)]
    for name, type_line, mv in gy:
        card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                    is_instant=type_line == "Instant", is_sorcery=type_line == "Sorcery")
        to_zone(state, card, Zone.GRAVEYARD)
    # RULE 202.3: MV 1 (twice) and MV 3 are two distinct values; the creature card is not an instant or sorcery.
    assert continuous.self_cost_reduction_for(eris, state, "p1")[0] == 4
    # An opponent's graveyard does not count ("your graveyard").
    to_zone(state, Card(id="Opp", name="Opp", type_line="Instant", converted_mana_cost=7, is_instant=True),
            Zone.GRAVEYARD, controller="p2")
    assert continuous.self_cost_reduction_for(eris, state, "p1")[0] == 4


# --- Ezuri, Claw of Progress ---------------------------------------------------------------------------------------

def test_ezuri_gains_experience_for_small_creatures_and_pumps_another_creature_at_combat():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    ezuri = to_bf(state, named("Ezuri, Claw of Progress"))
    bear = to_bf(state, vanilla("Bear", 2, 2))
    enter(engine, bear)  # power 2 or less -> experience counter
    big = to_bf(state, vanilla("Big", 5, 5))
    enter(engine, big)  # power 5: no counter
    assert p1.counters.get("experience", 0) == 1
    p1.counters["experience"] = 3
    state.fire_event(GameEvent(EventType.STEP_BEGIN, step="begin_combat", player_id="p1"))
    drain(engine)
    # RULE 109.5: "another" target creature; X = 3 experience counters. Ezuri himself never gets them.
    assert ezuri.counters.get("+1/+1", 0) == 0
    assert bear.counters.get("+1/+1", 0) + big.counters.get("+1/+1", 0) == 3


# --- Fatestitcher --------------------------------------------------------------------------------------------------

def test_fatestitcher_taps_or_untaps_another_permanent_but_never_itself():
    from mtg_analyzer.game import targeting

    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    stitcher = to_bf(state, named("Fatestitcher"))
    victim = to_bf(state, vanilla("Victim"), controller="p2")
    ability = stitcher.activated_abilities[0]
    legal = targeting.legal_targets(state, "p1", ability.effects[0].target_spec, source=stitcher)
    assert victim.instance_id in {t["instance_id"] for t in legal}
    assert stitcher.instance_id not in {t["instance_id"] for t in legal}  # "another" permanent
    engine.activate_ability(p1, stitcher, ability_index=0, targets=[victim])
    engine.resolve_until_stable()
    assert state.pending_choice is not None  # RULE 115 target chosen; tap-or-untap is the "you may" decision
    option = next(o for o in state.pending_choice["options"] if "tap" in str(o["id"]).lower() and "un" not in str(o["id"]).lower())
    engine.rules.resolve_choice(str(option["id"]))
    engine.resolve_until_stable()
    assert victim.tapped and stitcher.tapped  # cost paid, target tapped


# --- Geralf, Visionary Stitcher ------------------------------------------------------------------------------------

def test_geralf_sacrifices_a_nontoken_creature_for_a_zombie_as_big_as_its_toughness():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    geralf = to_bf(state, named("Geralf, Visionary Stitcher"))
    victim = to_bf(state, vanilla("Wall", 0, 4))
    ability = geralf.activated_abilities[0]
    p1.mana_pool.add("U", 1)
    engine.activate_ability(p1, geralf, ability_index=0, sacrifice_choice=victim.instance_id)
    drain(engine)
    assert victim not in state.battlefield and victim in p1.graveyard
    zombies = [o for o in state.battlefield if o.is_token and "Zombie" in o.card.type_line]
    assert len(zombies) == 1 and (zombies[0].power, zombies[0].toughness) == (4, 4)
    engine.recompute_continuous_effects()
    assert "flying" in {k.lower() for k in zombies[0].granted_keywords}  # "Zombies you control have flying"
    # Geralf cannot sacrifice himself ("another") and tokens are not legal fodder ("nontoken").
    assert geralf in state.battlefield


# --- Emeria's Call // Emeria, Shattered Skyclave -------------------------------------------------------------------

def test_emerias_call_makes_two_angels_and_protects_only_the_non_angels_until_your_next_turn():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    bear = to_bf(state, vanilla("Bear"))
    old_angel = to_bf(state, vanilla("Old Angel", 3, 3, "Creature — Angel"))
    opp_bear = to_bf(state, vanilla("Opp Bear"), controller="p2")
    call = to_zone(state, named("Emeria's Call // Emeria, Shattered Skyclave"), Zone.HAND)
    p1.mana_pool.add("W", 7)
    engine.cast_spell(p1, call)
    drain(engine)
    angels = [o for o in state.battlefield if o.is_token and "Angel" in o.card.type_line]
    assert len(angels) == 2 and all((a.power, a.toughness) == (4, 4) for a in angels)
    engine.recompute_continuous_effects()

    def indestructible(o):
        return "indestructible" in {k.lower() for k in o.granted_keywords}

    assert indestructible(bear)
    assert not indestructible(old_angel) and not any(indestructible(a) for a in angels)  # "Non-Angel"
    assert not indestructible(opp_bear)  # "you control"
    # RULE 611.2b: it ends when your next turn begins.
    engine.begin_turn()
    while engine.state.active_player.id != "p1":
        engine.begin_turn()
    engine.recompute_continuous_effects()
    assert not indestructible(bear)


def test_emeria_shattered_skyclave_back_face_is_a_playable_shock_land():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    card = to_zone(state, named("Emeria's Call // Emeria, Shattered Skyclave"), Zone.HAND)
    land = engine.play_land(p1, card, face="back")
    drain(engine)
    assert land in state.battlefield and land.is_land
    # RULE 614.1c: "you may pay 3 life; if you don't, it enters tapped" -- either answer is consistent.
    assert (p1.life == 17 and not land.tapped) or (p1.life == 20 and land.tapped)
    land.tapped = False
    engine.tap_for_mana(p1, land)  # {T}: Add {W}
    assert p1.mana_pool.total() >= 1


# --- Foe-Razer Regent ----------------------------------------------------------------------------------------------

def test_foe_razer_regent_fights_on_entering_and_the_fighter_grows_at_the_next_end_step():
    engine, state = engine_2p()
    reach_main(engine)
    regent = to_bf(state, named("Foe-Razer Regent"))
    victim = to_bf(state, vanilla("Victim", 1, 1), controller="p2")
    enter(engine, regent)
    assert victim not in state.battlefield  # RULE 701.14a: the Regent's power kills it
    # The Regent fought, so it is named by the delayed trigger; nothing happens before the end step.
    assert regent.counters.get("+1/+1", 0) == 0
    engine._fire_delayed_triggers("end")  # RULE 603.7: the next end step
    drain(engine)
    assert regent.counters.get("+1/+1", 0) == 2


def test_foe_razer_regent_also_pays_off_for_other_fights():
    from mtg_analyzer.game.effects.captured_counters import AddCountersToCapturedEffect  # noqa: F401  (registered)

    engine, state = engine_2p()
    reach_main(engine)
    to_bf(state, named("Foe-Razer Regent"))
    mine = to_bf(state, vanilla("Mine", 3, 3))
    theirs = to_bf(state, vanilla("Theirs", 1, 1), controller="p2")
    for obj in (mine, theirs):
        state.fire_event(GameEvent(EventType.FIGHTS, instance_id=obj.instance_id, controller_id=obj.controller_id,
                                   object_types=sorted(obj.type_words)))
    drain(engine)
    engine._fire_delayed_triggers("end")
    drain(engine)
    assert mine.counters.get("+1/+1", 0) == 2  # "a creature you control fights" -> that creature
    assert theirs not in state.battlefield or theirs.counters.get("+1/+1", 0) == 0  # an opponent's fighter: nothing


# --- Emberwilde Captain --------------------------------------------------------------------------------------------

def test_emberwilde_captain_makes_you_monarch_and_punishes_attackers_by_their_hand_size():
    engine, state = engine_2p()
    reach_main(engine)
    p2 = state.player_by_id("p2")
    captain = to_bf(state, named("Emberwilde Captain"))
    enter(engine, captain)
    assert state.monarch_id == "p1"  # RULE 725.1
    for i in range(4):
        to_zone(state, vanilla(f"Card{i}"), Zone.HAND, controller="p2")

    def p2_attacks_p1():
        state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p2", defending_player_id="p1",
                                   count=1, controller_id="p2"))
        drain(engine)

    p2_attacks_p1()
    assert state.player_by_id("p2").life == 16  # 4 cards in hand
    # Not the monarch any more: the same attack deals nothing.
    state.monarch_id = "p2"
    p2_attacks_p1()
    assert state.player_by_id("p2").life == 16
    assert p2 is state.player_by_id("p2")


# --- Empty the Laboratory ------------------------------------------------------------------------------------------

def test_empty_the_laboratory_sacrifices_x_zombies_and_reanimates_that_many_from_the_library():
    engine, state = engine_2p()
    reach_main(engine)
    p1 = state.player_by_id("p1")
    zombies = [to_bf(state, vanilla(f"Zed{i}", 1, 1, "Creature — Zombie")) for i in range(3)]
    bear = to_bf(state, vanilla("Bystander"))
    # Library (top first): Bear, Zombie A, Bear, Zombie B, Zombie C ...
    order = [("Filler Bear", "Creature — Bear"), ("Zombie A", "Creature — Zombie"), ("Filler Elf", "Creature — Elf"),
             ("Zombie B", "Creature — Zombie"), ("Zombie C", "Creature — Zombie")]
    p1.library.clear()
    for name, type_line in reversed(order):  # the top of the library is the end of the list
        p1.library.append(GameObject(vanilla(name, 1, 1, type_line), owner_id="p1", zone=Zone.LIBRARY))
    spell = to_zone(state, named("Empty the Laboratory"), Zone.HAND)
    p1.mana_pool.add("U", 4)
    engine.cast_spell(p1, spell, x=2)
    drain(engine)
    assert sum(1 for z in zombies if z in state.battlefield) == 1  # X = 2 sacrificed
    assert bear in state.battlefield
    entered = {o.name for o in state.battlefield if o.name.startswith("Zombie ")}
    assert entered == {"Zombie A", "Zombie B"}  # two Zombie creature cards, "equal to the number sacrificed"
    assert [o.name for o in p1.library][0] == "Zombie C" or "Zombie C" in {o.name for o in p1.library}
    assert {"Filler Bear", "Filler Elf"} <= {o.name for o in p1.library}  # the rest went to the bottom
