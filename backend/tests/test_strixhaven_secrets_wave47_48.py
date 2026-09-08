"""Secrets of Strixhaven — playability batch, waves 47-48 (PAR-60).

wave 47: Feral Appetite (exile-a-graveyard-card, token if it was a creature),
         Teshar, Ancestor's Apostle (historic-cast -> reanimate small creature).
wave 48: Killian, Decisive Mentor — ``enchanted_by_your_aura`` group-condition
         filter in ``effect_binder._build_group_ok``.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone

WAVE = ["Feral Appetite", "Teshar, Ancestor's Apostle", "Killian, Decisive Mentor"]


@pytest.mark.parametrize("name", WAVE)
def test_registered_and_binds(name):
    assert is_registered(name)
    specs = _REGISTRY[name.lower()]()
    assert specs
    src = GameObject(
        card=Card(id="x", name=name, type_line="Legendary Creature — Human Warlock",
                  is_creature=True, power=2, toughness=3),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)


def test_killian_reads_the_parser_claimed_enchantment_etb():
    """The registered factory must re-add the parser-claimed
    enchantment-enters trigger (registration turns ``parse_oracle`` off for
    the card), plus the hand-authored Aura-attack draw trigger."""
    specs = _REGISTRY["killian, decisive mentor"]()
    assert len(specs) == 2
    etb, attack = specs
    assert etb.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert etb.trigger["condition"]["type"] == "enchantment"
    assert {e.type for e in etb.effects} == {"tap", "goad"}
    assert attack.trigger["event"] == "ATTACKS"
    assert attack.trigger["condition"]["enchanted_by_your_aura"] is True
    assert attack.effects[0].type == "draw"


def test_group_ok_enchanted_by_your_aura_filter():
    """``_build_group_ok`` honours ``enchanted_by_your_aura``: an ATTACKS
    event only passes when the acting creature has an Aura the ability's
    controller controls attached to it."""
    from mtg_analyzer.game.binding.core import _build_group_ok
    from mtg_analyzer.models.events import EventType

    src = GameObject(card=Card(id="k", name="Killian, Decisive Mentor",
                               type_line="Legendary Creature", is_creature=True),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    cond = {"subject": "group", "controller": "you", "enchanted_by_your_aura": True}
    group_ok = _build_group_ok(cond, src, {"event": EventType.ATTACKS}, "k")

    bear = GameObject(card=Card(id="b", name="Grizzly Bears", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    bear.controller_id = "p1"
    aura = GameObject(card=Card(id="a", name="Sentinel's Eyes",
                               type_line="Enchantment — Aura"),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"

    class _State:
        battlefield = [bear, aura]

    class _Ctx:
        state = _State()

    event = {"instance_id": "b", "player_id": "p1", "controller_id": "p1"}
    # No aura attached yet -> fails.
    assert group_ok(event, _Ctx()) is False
    # Attach the Aura -> passes.
    aura.attached_to = "b"
    assert group_ok(event, _Ctx()) is True
    # Aura controlled by an opponent -> fails.
    aura.controller_id = "p2"
    assert group_ok(event, _Ctx()) is False
