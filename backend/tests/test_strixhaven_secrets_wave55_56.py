"""Secrets of Strixhaven — playability batch, waves 55-56 (PAR-60).

wave 55: Quandrix Apprentice — magecraft trigger + the existing
         ``impulsive_look`` ("look at top N, take one matching, rest to Y").
wave 56: Furygale Flocking — the existing ``CreateTokenEffect.per_opponent``
         ("for each opponent, create a … token") with ``count=2``.
"""

from __future__ import annotations

from mtg_analyzer.game import combat
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def test_quandrix_apprentice_magecraft_impulsive_look():
    assert is_registered("Quandrix Apprentice")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    qa = GameObject(card=Card(id="qa", name="Quandrix Apprentice",
                             type_line="Creature — Human Wizard", is_creature=True,
                             power=2, toughness=2),
                    owner_id=p1.id, zone=Zone.BATTLEFIELD)
    qa.controller_id = p1.id
    eng.state.add_to_battlefield(qa)
    bind_from_catalogue(qa)
    assert len(qa.triggered_abilities) == 1

    for nm, tl in [("Forest", "Basic Land — Forest"), ("Bolt", "Instant"),
                   ("Wrath", "Sorcery")]:
        p1.library.append(GameObject(card=Card(id=nm, name=nm, type_line=tl),
                                     owner_id=p1.id, zone=Zone.LIBRARY))
    p1.library.reverse()  # Forest on top

    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=p1.id,
                                   object_types=["instant"]))
    eng.resolve_until_stable()
    pc = eng.state.pending_choice
    assert pc and pc["kind"] == "impulsive_look"
    opts = [o for o in pc["options"] if o.get("id") != "decline"]
    assert [o["label"] for o in opts] == ["Forest"]
    eng.rules.resolve_impulsive_look_choice(opts[0]["instance_id"])
    eng.resolve_until_stable()
    assert [o.name for o in p1.hand] == ["Forest"]
    assert len(p1.library) == 2


def test_furygale_flocking_two_tokens_per_opponent():
    assert is_registered("Furygale Flocking")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.players[0]
    src = GameObject(card=Card(id="ff", name="Furygale Flocking", type_line="Sorcery"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    ability = bind_ability(_REGISTRY["furygale flocking"]()[0], src)
    for e in (ability if isinstance(ability, list) else [ability]):
        e.source = src
        e.apply(eng.rules.context)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 4  # 2 per opponent × 2 opponents
    assert all(t.controller_id == p1.id for t in tokens)
    assert all(t.power == 3 and t.toughness == 3 for t in tokens)
    assert all(combat.has(t, "flying") and combat.has(t, "haste") for t in tokens)
