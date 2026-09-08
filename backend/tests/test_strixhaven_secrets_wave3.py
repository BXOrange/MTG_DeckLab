"""Secrets of Strixhaven — playability batch, wave 3.

Wave 3: the Silverquill **Impetus** Aura cycle.
- `segmenter._ATTACHED_MULTI_EVENT_RE` — "whenever enchanted creature
  attacks or blocks, …" (two-verb attached-subject trigger).
- `LoseLifeEffect.selector="attached_permanent_controller"` — "its
  controller" on an Aura = the enchanted creature's controller.
- Parasitic / Martial / Ghoulish Impetus hand-authored in entries_018.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import is_registered
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_attacks_or_blocks_attached_trigger_now_modeled():
    r = parse_oracle(_db().get_card("Luminous Wake"))
    assert r.coverage != UNMODELED, r.unclaimed
    trig = [s for s in r.specs if s.trigger][0].trigger
    assert set(trig["event"]) == {"ATTACKS", "BLOCKS"}
    assert trig["condition"] == {"subject": "attached_permanent"}


def test_attacks_or_blocks_multi_verb_regex():
    import mtg_analyzer.parser.oracle.segmenter as S
    assert S._ATTACHED_MULTI_EVENT_RE.match("enchanted creature attacks or blocks")
    assert S._ATTACHED_MULTI_EVENT_RE.match("equipped creature attacks or blocks")
    # not a two-verb clause -> no match (single-verb path handles it)
    assert not S._ATTACHED_MULTI_EVENT_RE.match("enchanted creature attacks")


@pytest.mark.parametrize("name", ["Parasitic Impetus", "Martial Impetus", "Ghoulish Impetus"])
def test_impetus_cycle_registered(name):
    assert is_registered(name)


def test_lose_life_attached_permanent_controller_selector():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    # p2's creature, enchanted by p1's Parasitic Impetus.
    victim = GameObject(Card(id="v", name="Ox", type_line="Creature — Ox",
                             is_creature=True, power=3, toughness=3),
                        owner_id=p2.id, zone=Zone.BATTLEFIELD)
    victim.controller_id = p2.id
    eng.state.add_to_battlefield(victim)

    aura = GameObject(_db().get_card("Parasitic Impetus"),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    aura.controller_id = p1.id
    aura.attached_to = victim.instance_id
    eng.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)

    eff = EffectRegistry.create(
        "lose_life", {"amount": 2, "selector": "attached_permanent_controller"}
    )
    eff.source = aura
    eff.apply(eng.rules.context)
    assert p2.life == 18, "the enchanted creature's controller (p2) loses the life"
    assert p1.life == 20


def test_parasitic_impetus_attack_drains_host_controller_and_gains_you():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    attacker = GameObject(Card(id="a", name="Goader", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                          owner_id=p2.id, zone=Zone.BATTLEFIELD)
    attacker.controller_id = p2.id
    attacker.summoning_sick = False
    eng.state.add_to_battlefield(attacker)

    aura = GameObject(_db().get_card("Parasitic Impetus"),
                      owner_id=p1.id, zone=Zone.BATTLEFIELD)
    aura.controller_id = p1.id
    aura.attached_to = attacker.instance_id
    eng.state.add_to_battlefield(aura)
    bind_from_catalogue(aura)

    # Fire the ATTACKS trigger's bound effects directly.
    trig = aura.triggered_abilities[0]
    ctx = eng.rules.context
    for eff in trig.effects:
        eff.source = aura
        eff.apply(ctx)

    assert p2.life == 18
    assert p1.life == 22
