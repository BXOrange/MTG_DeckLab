"""Shared card factories and board setup for engine integration tests."""
from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.game.effects.core import ActivatedAbility

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.game.effects.core import DealDamageEffect
from mtg_analyzer.game.game_engine import GameEngine

def land(name="Forest", produces="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {produces}", is_land=True)

def creature(name="Grizzly Bears", cost="{1}{G}", power=2, toughness=2, **kw):
    if kw.get("color_identity") and cost == "{1}{G}":
        # RULE 202.2: colour comes from the cost, so a recoloured test creature needs matching pips.
        cost = "{1}" + "".join("{%s}" % c for c in sorted(kw["color_identity"]))
    return Card(
        id=name,
        name=name,
        type_line=kw.pop("type_line", "Creature — Bear"),
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True,
        power=power,
        toughness=toughness,
        **kw,
    )

def instant(name="Shock", cost="{R}"):
    return Card(
        id=name,
        name=name,
        type_line="Instant",
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_instant=True,
    )

def make_engine(p1_cards, p2_cards=None, life=20, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=life, starting_hand=hand)

def obj_on_battlefield(state: GameState, engine: GameEngine, card: Card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj

def _dual_land():
    return Card(
        id="Tundra",
        name="Tundra",
        type_line="Land — Plains Island",
        is_land=True,
        oracle_text="{T}: Add {W} or {U}.",
    )

def _sick(state, engine, card, controller="p1", haste=False):
    """Put a *summoning-sick* permanent on the battlefield (no obj_on_battlefield
    here, which clears sickness)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = True
    if haste:
        obj.intrinsic_keywords.add("haste")
    state.add_to_battlefield(obj)
    return obj

def _mana_dork(name="Llanowar Elves"):
    return creature(name=name, cost="{G}", power=1, toughness=1,
                    type_line="Creature — Elf Druid", oracle_text="{T}: Add {G}.")

def _mana_offered(engine, player, obj):
    return any(
        a.get("type") == "tap_for_mana" and a.get("instance_id") == obj.instance_id
        for a in engine.legal_actions(player)
    )

def _life_lost_events(eng):
    events = []
    eng.state.subscribe(lambda e: events.append(e) if e.type == EventType.LIFE_LOST else None)
    return events

def planeswalker(name="Test Walker", controller="p2", loyalty=5):
    return Card(id=name, name=name, type_line="Legendary Planeswalker — Test", loyalty=loyalty)

def _search_one(eng, player, criteria, destination):
    eng.rules._request_search(player, criteria, destination)
    chosen = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_choice(chosen)
    return chosen

def _combat_creature(name="Fighter", power=2, toughness=2, controller="p1", **kw):
    """A non-summoning-sick creature already in play, for combat tests."""
    return name, power, toughness, controller, kw

def _to_declare_attackers(eng):
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"

def _attack_then_blockers_step(eng, attacker):
    eng.declare_attackers(eng.state.active_player, [attacker])
    eng.state.current_step = "declare_blockers"
    return eng.state.player_by_id("p2")

def _goblin_guide_card():
    return Card(
        id="Goblin Guide", name="Goblin Guide", type_line="Creature — Goblin Scout",
        is_creature=True, power=2, toughness=2, mana_cost_string="{R}",
        converted_mana_cost=1, keywords=["Haste"],
        oracle_text="Haste\nWhenever this creature attacks, defending player "
                     "reveals the top card of their library. If it's a land "
                     "card, that player puts it into their hand.",
    )

def _rampage_attacker(eng, n=2):
    return obj_on_battlefield(
        eng.state,
        eng,
        creature(
            power=2,
            toughness=2,
            keywords=["Rampage"],
            oracle_text=f"Rampage {n} (Whenever this creature becomes blocked, it gets "
            f"+{n}/+{n} until end of turn for each creature blocking it beyond the first.)",
        ),
    )

def _shock_spell(p1):
    """A hand `GameObject` for a bare "deal 3 damage to target creature" instant."""
    from mtg_analyzer.game.effects.core import DealDamageEffect

    card = Card(
        id="Shock",
        name="Shock",
        type_line="Instant",
        mana_cost_string="{R}",
        converted_mana_cost=1,
        is_instant=True,
    )
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(spell, Zone.HAND)
    spell.spell_effects = [DealDamageEffect(amount=3, target_kind="creature")]
    return spell

def _with_ability(eng, card, cost_text, effects, controller="p1"):
    """Put a permanent with one activated ability on the battlefield."""
    obj = obj_on_battlefield(eng.state, eng, card, controller=controller)
    ability = ActivatedAbility(
        effects=effects, cost=parse_activation_cost(cost_text), source=obj
    )
    obj.activated_abilities.append(ability)
    return obj, ability

def _in_graveyard(player, card):
    """A `GameObject` for ``card`` sitting directly in ``player``'s graveyard,
    as if it had already been cast and resolved there some previous turn."""
    obj = GameObject(card, owner_id=player.id, zone=Zone.GRAVEYARD)
    player.add_to_zone(obj, Zone.GRAVEYARD)
    return obj
