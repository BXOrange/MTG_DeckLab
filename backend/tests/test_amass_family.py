"""RULE 701.47/48 Amass "<Type> N" — a first parser handler reaching the
already-shipped `game/effects/core.py` `AmassEffect` (proven only via the
hand-authored Orcish Bowmasters entry, `test_mec42_family.py`, until now)
from real oracle text for the first time.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def test_amass_typed_parses():
    assert match_clause("amass orcs 1") == [
        EffectSpec("amass", {"subtype": "Orc", "count": 1})
    ]


def test_amass_typed_plural_count_parses():
    assert match_clause("amass zombies 2") == [
        EffectSpec("amass", {"subtype": "Zombie", "count": 2})
    ]


def test_amass_untyped_defaults_to_zombie():
    # RULE 701.47d's pre-errata bare "amass N" — no card in the cache prints
    # this any more (see the handler's own docstring), but the row exists
    # for a differently-worded future import.
    assert match_clause("amass 3") == [
        EffectSpec("amass", {"subtype": "Zombie", "count": 3})
    ]


def test_amass_x_sentinel_stays_unclaimed():
    # `EffectRegistry.register("amass", ...)` forces `int(count)` at bind
    # time — a literal "x" sentinel (Assault on Osgiliath/Barad-dûr) isn't
    # safe to emit yet, so this must fail closed rather than crash at bind.
    assert match_clause("amass orcs x") is None


def test_dreadhorde_invasion_amass_clause_is_claimed():
    # A real, previously-unregistered card (not the hand-authored Orcish
    # Bowmasters) — confirms the handler reaches real cache text end to end.
    card = Card(
        id="Dreadhorde Invasion", name="Dreadhorde Invasion",
        type_line="Enchantment",
        oracle_text=(
            "At the beginning of your upkeep, you lose 1 life and amass "
            "Zombies 1."
        ),
    )
    result = parse_oracle(card)
    spec = result.effect_specs[0]
    amass_effects = [e for e in spec.effects if e.type == "amass"]
    assert amass_effects == [EffectSpec("amass", {"subtype": "Zombie", "count": 1})]


def test_amass_executes_and_creates_an_army_token():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    p1 = state.player_by_id("p1")
    card = Card(
        id="Test Amasser", name="Test Amasser", type_line="Creature — Human Soldier",
        is_creature=True, power=1, toughness=1,
        oracle_text="When this creature enters, amass Orcs 2.",
    )
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)

    state.add_to_battlefield(obj)
    state.fire_event(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
            controller_id="p1", object_types=sorted(obj.type_words),
        )
    )
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    armies = [
        o for o in state.battlefield
        if o.controller_id == "p1" and "Army" in o.card.type_line and "Orc" in o.card.type_line
    ]
    assert len(armies) == 1
    assert armies[0].counters.get("+1/+1", 0) == 2
