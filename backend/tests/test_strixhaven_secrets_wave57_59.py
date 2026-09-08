"""Secrets of Strixhaven — playability batch, waves 57-59 (PAR-60).

wave 57: Chaos Warp — new ``shuffle_target_into_library_reveal_top`` effect.
wave 58: Thunderclap Drake — ``CopySpellEffect.count_selector`` (copy count
         from a `continuous.count_selector`) + the existing
         ``arm_spell_watcher`` delayed "when you next cast" hook.
wave 59: Priest of Forgotten Gods — pure composition (lose_life /
         sacrifice ``selector="each_opponent"`` + add_mana + draw), cost
         ``sacrifice_count``.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered
from mtg_analyzer.game.binding.core import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone


def _apply(eng, spec, src, **kw):
    ability = bind_ability(spec, src)
    for e in (ability if isinstance(ability, list) else [ability]):
        e.source = src
        e.apply(eng.rules.context, **kw)
    return ability


def test_chaos_warp_shuffles_target_and_reveals_top_permanent():
    assert is_registered("Chaos Warp")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, p2 = eng.state.players
    victim = GameObject(card=Card(id="v", name="Big Threat", type_line="Creature — Dragon",
                                 is_creature=True, power=6, toughness=6),
                        owner_id=p2.id, zone=Zone.BATTLEFIELD)
    victim.controller_id = p2.id
    eng.state.add_to_battlefield(victim)
    for j in range(6):
        p2.library.append(GameObject(card=Card(id=f"c{j}", name=f"Bear{j}",
                                              type_line="Creature — Bear", is_creature=True,
                                              power=2, toughness=2),
                                     owner_id=p2.id, zone=Zone.LIBRARY))
    src = GameObject(card=Card(id="cw", name="Chaos Warp", type_line="Instant"),
                     owner_id=p1.id, zone=Zone.STACK)
    src.controller_id = p1.id
    _apply(eng, _REGISTRY["chaos warp"]()[0], src, targets=[victim])
    eng.resolve_until_stable()

    # The whole library is permanents, so exactly one card is revealed and
    # enters (RULE 701.20 shuffle + reveal-top). It may, with small odds, be
    # the just-shuffled victim itself — Chaos Warp genuinely allows that —
    # so assert the conserved invariant, not which card.
    p2_perms = [o for o in eng.state.battlefield if o.controller_id == p2.id]
    assert len(p2_perms) == 1
    assert len(p2.library) == 6
    assert len(p2_perms) + len(p2.library) == 7  # victim + 6 library cards, conserved


def test_thunderclap_drake_copies_next_spell_per_commander_cast():
    assert is_registered("Thunderclap Drake")
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1, _ = eng.state.players
    p1.commander_casts = {"cmd1": 2}
    td = GameObject(card=Card(id="td", name="Thunderclap Drake", type_line="Creature — Drake",
                             is_creature=True, power=2, toughness=1),
                    owner_id=p1.id, zone=Zone.BATTLEFIELD)
    td.controller_id = p1.id
    eng.state.add_to_battlefield(td)
    bind_from_catalogue(td)
    for e in td.activated_abilities[0].effects:
        e.source = td
        e.apply(eng.rules.context)
    assert len(eng.state.spell_watchers) == 1

    spell = GameObject(card=Card(id="sp", name="Shock", type_line="Instant"),
                       owner_id=p1.id, zone=Zone.STACK)
    spell.controller_id = p1.id
    eng.state.stack.append(type("SI", (), {"kind": "spell", "obj": spell,
                                          "controller_id": p1.id, "targets": [],
                                          "effects": [], "description": "Shock",
                                          "x": 0, "target_groups": None})())
    eng.state.fire_event(GameEvent(EventType.SPELL_CAST, player_id=p1.id,
                                   object_types=["instant"],
                                   instance_id=spell.instance_id, mana_value=1))
    assert len(eng.state.stack) == 3  # original + 2 copies


def test_priest_of_forgotten_gods_composition():
    assert is_registered("Priest of Forgotten Gods")
    src = GameObject(card=Card(id="p", name="Priest of Forgotten Gods",
                             type_line="Creature — Human Cleric", is_creature=True,
                             power=1, toughness=2),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    spec = _REGISTRY["priest of forgotten gods"]()[0]
    spec.validate()
    ability = bind_ability(spec, src)
    assert ability.cost.taps_self is True
    assert ability.cost.sacrifice_count == (2, "creature")
    assert [type(e).__name__ for e in ability.effects] == [
        "LoseLifeEffect", "SacrificeEffect", "AddManaEffect", "DrawCardEffect"]
