"""Secrets of Strixhaven — playability batch, wave 51 (PAR-60).

Triggered-ability doubling generalized: `TriggerDoublerEffect` gained
``subject_subtype_any`` (Harmonic Prodigy — "a Shaman or another Wizard you
control") and ``cause_spell_type_any`` (Veyran, Voice of Duality — narrows a
``cause_filter`` match to the firing spell's card types).
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone


def _bf(eng, name, tl, ctrl, **kw):
    obj = GameObject(card=Card(id=name[:4] + str(len(name)), name=name, type_line=tl, **kw),
                     owner_id=ctrl, zone=Zone.BATTLEFIELD)
    obj.controller_id = ctrl
    eng.state.add_to_battlefield(obj)
    return obj


def test_registered_and_binds():
    for name, tl in [("Veyran, Voice of Duality", "Legendary Creature — Efreet Wizard"),
                     ("Harmonic Prodigy", "Creature — Human Wizard")]:
        assert is_registered(name)
        specs = _REGISTRY[name.lower()]()
        assert specs
        src = GameObject(card=Card(id="x", name=name, type_line=tl, is_creature=True,
                                  power=2, toughness=2),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
        src.controller_id = "p1"
        for s in specs:
            s.validate()
            bind_ability(s, src)


def test_harmonic_prodigy_doubles_shaman_or_other_wizard():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    hp = _bf(eng, "Harmonic Prodigy", "Creature — Human Wizard", p1.id,
             is_creature=True, power=1, toughness=3)
    bind_from_catalogue(hp)
    wiz = _bf(eng, "Merfolk Wizard", "Creature — Merfolk Wizard", p1.id,
              is_creature=True, power=2, toughness=2)
    sham = _bf(eng, "Goblin Shaman", "Creature — Goblin Shaman", p1.id,
               is_creature=True, power=2, toughness=2)
    bear = _bf(eng, "Grizzly", "Creature — Bear", p1.id,
               is_creature=True, power=2, toughness=2)
    eng.recompute_continuous_effects()
    ev = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=wiz.instance_id)

    assert continuous.trigger_doubler_bonus(eng.state, wiz, ev) == 1
    assert continuous.trigger_doubler_bonus(eng.state, sham, ev) == 1
    assert continuous.trigger_doubler_bonus(eng.state, bear, ev) == 0
    # "another Wizard" — Harmonic Prodigy never doubles its own triggers.
    assert continuous.trigger_doubler_bonus(eng.state, hp, ev) == 0
    # An opponent's Wizard is out of scope ("you control").
    p2 = eng.state.players[1]
    opp_wiz = _bf(eng, "Enemy Wizard", "Creature — Human Wizard", p2.id,
                  is_creature=True, power=2, toughness=2)
    eng.recompute_continuous_effects()
    assert continuous.trigger_doubler_bonus(eng.state, opp_wiz, ev) == 0


def test_veyran_doubles_only_instant_sorcery_cast_causes():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    vey = _bf(eng, "Veyran, Voice of Duality", "Legendary Creature — Efreet Wizard",
              p1.id, is_creature=True, power=2, toughness=2)
    bind_from_catalogue(vey)
    other = _bf(eng, "Storm Chaser", "Creature — Otter Wizard", p1.id,
                is_creature=True, power=1, toughness=1)
    eng.recompute_continuous_effects()

    on_instant = GameEvent(EventType.SPELL_CAST, player_id=p1.id, object_types=["instant"])
    on_sorcery = GameEvent(EventType.SPELL_CAST, player_id=p1.id, object_types=["sorcery"])
    on_creature = GameEvent(EventType.SPELL_CAST, player_id=p1.id, object_types=["creature"])
    etb = GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=other.instance_id)

    assert continuous.trigger_doubler_bonus(eng.state, other, on_instant) == 1
    assert continuous.trigger_doubler_bonus(eng.state, other, on_sorcery) == 1
    assert continuous.trigger_doubler_bonus(eng.state, other, on_creature) == 0
    # A non-cast cause (an ETB trigger) is never doubled by Veyran.
    assert continuous.trigger_doubler_bonus(eng.state, other, etb) == 0
