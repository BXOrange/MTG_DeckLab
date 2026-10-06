"""Shared helpers for the PLAY-ALL deck batches' gameplay regressions (real engine, real cached cards)."""
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase

#: A pool that pays for any spell — the tests care what resolves, not how it was paid for.
RICH = {"W": 5, "U": 5, "B": 5, "R": 5, "G": 5, "C": 15}


def game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _place(engine, obj, player, zone):
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    """A real cached card, bound from the catalogue, placed in ``zone``."""
    return _place(engine, GameObject(CardDatabase(DB_PATH).get_card(name), owner_id=player, zone=zone), player, zone)


def filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
           zone=Zone.BATTLEFIELD, **kw):
    """A synthetic vanilla card (no abilities) — use for bodies, library fodder, hand cards."""
    c = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
             is_creature="Creature" in type_line, is_land="Land" in type_line,
             is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
             power=power, toughness=toughness, mana_cost_string=kw.pop("mana_cost_string", "{%d}" % mv if mv else ""),
             mana_cost={"generic": mv} if mv else {}, **kw)
    return _place(engine, GameObject(c, owner_id=player, zone=zone), player, zone)


def main_phase(engine):
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"


def cast(engine, obj, pool=None, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(obj.controller_id)
    main_phase(engine)
    p.mana_pool.add_many(pool if pool is not None else RICH)
    engine.cast_spell(p, obj, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    main_phase(engine)
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        chosen = pick(choice) if pick is not None else None
        if chosen is None:
            chosen = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(chosen)


def pick_label(*labels):
    """An `answer` picker choosing the first option whose label contains one of ``labels``."""
    def _pick(choice):
        for o in choice.get("options") or []:
            if any(label in str(o.get("label")) for label in labels):
                return str(o["id"])
        return None
    return _pick


def enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def step(engine, step_name, player="p1"):
    engine.state.current_step = step_name
    engine._fire_delayed_triggers(step_name)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step_name, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    enter(engine, obj)
    return obj


def stack_library(engine, player, *cards):
    """Put ``cards`` on top of ``player``'s library; the last listed ends up on top."""
    p = engine.state.player_by_id(player)
    for obj in cards:
        p.library[:] = [o for o in p.library if o is not obj]
        obj.zone = Zone.LIBRARY
        p.library.append(obj)


def attack(engine, attackers, defender=None):
    """Declare ``attackers`` (the active player's) against the first legal defender, then resolve triggers."""
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    first = defender or engine.legal_defenders_for(state.active_player)[0]
    engine.declare_attackers(state.active_player, [{"attacker": a, "defender": first} for a in attackers])
    engine._fire_player_attacked_events()  # combat "locks in": the aggregate attack events (RULE 508.1)
    engine.resolve_until_stable()
