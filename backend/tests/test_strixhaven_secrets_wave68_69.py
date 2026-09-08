"""Secrets of Strixhaven — playability batch, waves 68-69 (PAR-60).

wave 68: Spirit of Resilience — pure reuse of the batched
         ``CARDS_LEFT_GRAVEYARD`` trigger (+1/+1; the become-a-copy rider
         is a documented simplification).
wave 69: Stensian Sanguinist — pure reuse: ``PLAYER_ATTACKED`` +
         ``grant_until`` (deathtouch) + a DAMAGE trigger firing
         ``become_prepared``.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


def test_spirit_of_resilience_registered_and_binds():
    assert is_registered("Spirit of Resilience")
    spec = _REGISTRY["spirit of resilience"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "CARDS_LEFT_GRAVEYARD"
    assert spec.trigger["graveyard_owner"] == "you"
    assert spec.effects[0].type == "add_counters"
    src = GameObject(card=Card(id="s", name="Spirit of Resilience",
                             type_line="Creature — Spirit Warrior", is_creature=True,
                             power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_stensian_sanguinist_registered_and_binds():
    for name in ("Stensian Sanguinist", "Stensian Sanguinist // Exsanguinate"):
        assert is_registered(name)
    specs = _REGISTRY["stensian sanguinist"]()
    assert len(specs) == 2
    grant, prepared = specs
    assert grant.trigger["event"] == "PLAYER_ATTACKED"
    assert grant.effects[0].type == "grant_until"
    assert grant.effects[0].params["static"]["params"]["keywords"] == ["deathtouch"]
    assert prepared.trigger["event"] == "DAMAGE"
    assert prepared.trigger["filter"] == {"combat": True, "is_player": True}
    assert prepared.effects[0].type == "become_prepared"
    src = GameObject(card=Card(id="ss", name="Stensian Sanguinist",
                             type_line="Creature — Vampire Cleric", is_creature=True,
                             power=2, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    for s in specs:
        s.validate()
        bind_ability(s, src)
