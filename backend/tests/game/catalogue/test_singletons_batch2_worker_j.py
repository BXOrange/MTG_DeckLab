"""Hand-authored singletons, Batch 2 (Commander Cube), worker J: Increasing Devotion, Juvenile Mist Dragon,
Meteor Blast, Moria Scavenger. Each test executes the card in a real GameEngine."""

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


def drain(engine: GameEngine, pick: int = 0) -> None:
    """Resolve the stack, answering every pending choice with its ``pick``-th option."""
    engine.resolve_until_stable()
    while engine.state.pending_choice is not None:
        options = engine.state.pending_choice.get("options") or []
        if not options:
            break
        engine.rules.resolve_choice(str(options[min(pick, len(options) - 1)]["id"]))
        engine.resolve_until_stable()


def reach_main(engine: GameEngine) -> None:
    engine.begin_turn()
    while engine.state.active_player.id != "p1":
        engine.begin_turn()
    engine.state.current_step = "main1"
    engine.recompute_continuous_effects()


def enter(engine: GameEngine, obj: GameObject) -> None:
    engine.state.fire_event(
        GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id)
    )
    drain(engine)


def cast(engine: GameEngine, card_obj: GameObject, pool: dict[str, int], targets=None, x: int = 0) -> None:
    p = engine.state.player_by_id(card_obj.controller_id)
    engine.state.current_step = "main1"
    for color, n in pool.items():
        p.mana_pool.add(color, n)
    engine.cast_spell(p, card_obj, targets=targets, target_groups=None, x=x)
    drain(engine)


def tokens_named(state: GameState, name: str, controller: str = "p1") -> list[GameObject]:
    return [o for o in state.battlefield if o.controller_id == controller and o.is_token and o.name == name]


# --- Meteor Blast --------------------------------------------------------------------------------------------------

def test_meteor_blast_deals_four_to_each_of_x_targets():
    engine, state = engine_2p()
    reach_main(engine)
    creatures = [to_bf(state, vanilla(f"Wall {i}", toughness=9), controller="p2") for i in range(3)]
    spell = to_zone(state, named("Meteor Blast"), Zone.HAND)
    cast(engine, spell, {"R": 5}, targets=creatures[:2], x=2)
    assert [o.damage_marked for o in creatures] == [4, 4, 0]


def test_meteor_blast_x_zero_takes_no_targets_and_does_nothing():
    engine, state = engine_2p()
    reach_main(engine)
    wall = to_bf(state, vanilla("Wall", toughness=9), controller="p2")
    spell = to_zone(state, named("Meteor Blast"), Zone.HAND)
    cast(engine, spell, {"R": 3}, targets=[], x=0)
    assert wall.damage_marked == 0


# --- Juvenile Mist Dragon ------------------------------------------------------------------------------------------

def test_juvenile_mist_dragon_taps_each_opponents_creature_and_it_skips_next_untap():
    engine, state = engine_2p()
    reach_main(engine)
    theirs = to_bf(state, vanilla("Their Bear"), controller="p2")
    dragon = to_bf(state, named("Juvenile Mist Dragon"))
    enter(engine, dragon)
    assert theirs.tapped
    assert theirs.skip_next_untap


# --- Moria Scavenger -----------------------------------------------------------------------------------------------

def _activate_discarding(engine, state, scavenger, discard: GameObject) -> None:
    p1 = state.player_by_id("p1")
    engine.activate_ability(p1, scavenger, ability_index=0, discard_choices=[discard.instance_id])
    drain(engine)


def test_moria_scavenger_discarding_a_creature_draws_and_amasses_an_orc():
    engine, state = engine_2p()
    reach_main(engine)
    scavenger = to_bf(state, named("Moria Scavenger"))
    creature = to_zone(state, vanilla("Dead Bear"), Zone.HAND)
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(vanilla("Drawn"), owner_id="p1", zone=Zone.LIBRARY))
    _activate_discarding(engine, state, scavenger, creature)
    assert scavenger.tapped
    assert creature in p1.graveyard
    assert len(p1.hand) == 1  # discarded one, drew one
    assert any(o.is_token and "Orc" in o.card.type_line for o in state.battlefield if o.controller_id == "p1")


def test_moria_scavenger_discarding_a_land_draws_but_does_not_amass():
    engine, state = engine_2p()
    reach_main(engine)
    scavenger = to_bf(state, named("Moria Scavenger"))
    land = to_zone(state, Card(id="Forest", name="Forest", type_line="Basic Land — Forest"), Zone.HAND)
    p1 = state.player_by_id("p1")
    p1.library.append(GameObject(vanilla("Drawn"), owner_id="p1", zone=Zone.LIBRARY))
    _activate_discarding(engine, state, scavenger, land)
    assert land in p1.graveyard
    assert len(p1.hand) == 1  # discarded the land, drew one
    assert not any(o.is_token for o in state.battlefield if o.controller_id == "p1")


# --- Increasing Devotion -------------------------------------------------------------------------------------------

def _human_tokens(state: GameState) -> int:
    return len([o for o in state.battlefield if o.controller_id == "p1" and o.is_token])


def test_increasing_devotion_from_hand_makes_five_tokens():
    engine, state = engine_2p()
    reach_main(engine)
    spell = to_zone(state, named("Increasing Devotion"), Zone.HAND)
    cast(engine, spell, {"W": 5})
    assert _human_tokens(state) == 5


def test_increasing_devotion_cast_from_graveyard_makes_ten_tokens():
    engine, state = engine_2p()
    reach_main(engine)
    spell = to_zone(state, named("Increasing Devotion"), Zone.GRAVEYARD)
    cast(engine, spell, {"W": 2, "C": 7})
    assert _human_tokens(state) == 10


# --- Ironsoul Enforcer ---------------------------------------------------------------------------------------------

def _attack_alone(engine, state, attacker: GameObject) -> None:
    attacker.attacking = True
    engine._fire_attacks_alone_event()
    drain(engine)
    attacker.attacking = False


def test_ironsoul_enforcer_attacking_alone_returns_an_artifact_from_graveyard():
    engine, state = engine_2p()
    reach_main(engine)
    enforcer = to_bf(state, named("Ironsoul Enforcer"))
    relic = to_zone(state, Card(id="Relic", name="Relic", type_line="Artifact"), Zone.GRAVEYARD)
    _attack_alone(engine, state, enforcer)
    assert relic in state.battlefield


def test_ironsoul_enforcer_commander_attacking_alone_also_returns_an_artifact():
    engine, state = engine_2p()
    reach_main(engine)
    enforcer = to_bf(state, named("Ironsoul Enforcer"))
    general = to_bf(state, vanilla("General"))
    general.is_commander = True
    relic = to_zone(state, Card(id="Relic", name="Relic", type_line="Artifact"), Zone.GRAVEYARD)
    _attack_alone(engine, state, general)
    assert relic in state.battlefield


def test_ironsoul_enforcer_does_not_trigger_for_a_non_commander_attacking_alone():
    engine, state = engine_2p()
    reach_main(engine)
    enforcer = to_bf(state, named("Ironsoul Enforcer"))
    bear = to_bf(state, vanilla("Bear"))
    relic = to_zone(state, Card(id="Relic", name="Relic", type_line="Artifact"), Zone.GRAVEYARD)
    _attack_alone(engine, state, bear)
    assert relic in state.player_by_id("p1").graveyard
