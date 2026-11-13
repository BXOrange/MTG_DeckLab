"""PAR-255: ``<cost>: choose one that hasn't been chosen [this turn] —`` on an activated ability.

RULE 700.2 + RULE 602.2b: the mode counts as chosen on activation, whether or not the ability resolves. Kargan
Intimidator tracks per turn; Survivor's Med Kit and Three Bowls of Porridge track while the permanent stays on
the battlefield (RULE 400.7: a blinked permanent is a new object). Rulings: each copy is tracked separately.
All card text below is the real oracle text.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.gate import parse_oracle

KARGAN = (
    "Cowards can't block Warriors.\n{1}: Choose one that hasn't been chosen this turn —\n"
    "• This creature gets +1/+1 until end of turn.\n"
    "• Target creature becomes a Coward until end of turn.\n"
    "• Target Warrior gains trample until end of turn."
)
MED_KIT = (
    "{1}, {T}: Choose one that hasn't been chosen —\n• Stimpak — Draw a card.\n"
    "• Fancy Lads Snack Cakes — Create a Food token. (It's an artifact with "
    "\"{2}, {T}, Sacrifice this token: You gain 3 life.\")\n"
    "• RadAway — Target player loses all rad counters. Sacrifice this artifact."
)
BOWLS = (
    "{2}, {T}: Choose one that hasn't been chosen —\n• This artifact deals 2 damage to target creature.\n"
    "• Tap target creature.\n• Sacrifice this artifact. You gain 3 life."
)


def _card(name, type_line, oracle, **kw):
    kw.setdefault("is_creature", "creature" in type_line.lower())
    if kw["is_creature"]:
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                mana_cost_string="{1}", converted_mana_cost=1, **kw)


def _setup():
    p1, p2 = Player(id="p1", life=20), Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = GameEngine(state)
    state.current_step = "main1"
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _kargan(state, controller="p1"):
    return _bf(state, _card("Kargan Intimidator", "Creature — Human Warrior", KARGAN), controller)


def _kit(state):
    return _bf(state, _card("Survivor's Med Kit", "Artifact", MED_KIT))


def _bowls(state):
    return _bf(state, _card("Three Bowls of Porridge", "Artifact", BOWLS))


def _modes(engine, p, src):
    return sorted(a["mode"] for a in engine.legal_actions(p)
                  if a.get("type") == "activate_ability" and a.get("instance_id") == src.instance_id
                  and not a.get("locked"))


def _fund(p, n):
    for _ in range(n):
        p.mana_pool.add("C", 1)


@pytest.mark.parametrize("text, kind, tp", [(KARGAN, "Creature — Human Warrior", "turn"),
                                           (MED_KIT, "Artifact", "permanence"), (BOWLS, "Artifact", "permanence")])
def test_real_text_is_modeled(text, kind, tp):
    result = parse_oracle(_card("X", kind, text))
    assert result.coverage == "MODELED", result.unclaimed
    modal = [s for s in result.specs if s.modes]
    assert len(modal) == 1 and modal[0].modes["exhaust"] == tp and len(modal[0].modes["options"]) == 3


def test_kargan_modes_each_work_and_are_refused_twice():
    engine, state, p1, p2 = _setup()
    k = _kargan(state)
    ally = _bf(state, _card("Ally Warrior", "Creature — Human Warrior", ""))
    foe = _bf(state, _card("Foe", "Creature — Bear", ""), "p2")
    _fund(p1, 3)
    assert _modes(engine, p1, k) == [0, 1, 2]
    engine.activate_ability(p1, k, 0, mode=0)
    engine.resolve_until_stable()
    assert (k.power, k.toughness) == (3, 3)
    assert _modes(engine, p1, k) == [1, 2]  # no tap in the cost: still activatable
    with pytest.raises(ValueError, match="already been chosen"):
        engine.activate_ability(p1, k, 0, mode=0)
    assert p1.mana_pool.total() == 2  # rejected before any cost was paid

    engine.activate_ability(p1, k, 0, mode=1, targets=[foe])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert foe.has_subtype("Coward")
    engine.activate_ability(p1, k, 0, mode=2, targets=[ally])
    engine.resolve_until_stable()
    assert "trample" in {kw.lower() for kw in ally.granted_keywords}
    assert _modes(engine, p1, k) == []  # every mode spent: not activatable at all
    _fund(p1, 1)
    with pytest.raises(ValueError):
        engine.activate_ability(p1, k, 0, mode=0)


def test_kargan_coward_cannot_block_a_warrior():
    engine, state, p1, p2 = _setup()
    k = _kargan(state)
    warrior = _bf(state, _card("Warrior", "Creature — Human Warrior", ""), "p2")
    blocker = _bf(state, _card("Blocker", "Creature — Bear", ""), "p1")
    warrior.attacking = True
    warrior.combat_defender = {"kind": "player", "id": p1.id}
    engine.recompute_continuous_effects()
    assert engine.can_block(p1, blocker, warrior)
    _fund(p1, 1)
    engine.activate_ability(p1, k, 0, mode=1, targets=[blocker])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert not engine.can_block(p1, blocker, warrior)  # "Cowards can't block Warriors"


def test_kargan_modes_return_next_turn_and_copies_track_separately():
    engine, state, p1, p2 = _setup()
    a, b = _kargan(state), _kargan(state)
    _fund(p1, 4)
    engine.activate_ability(p1, a, 0, mode=0)
    engine.resolve_until_stable()
    assert _modes(engine, p1, a) == [1, 2] and _modes(engine, p1, b) == [0, 1, 2]
    state.internal_turn.number += 1
    assert _modes(engine, p1, a) == [0, 1, 2]


def test_med_kit_modes_do_not_reset_each_turn_and_radaway_sacrifices_on_resolution():
    engine, state, p1, p2 = _setup()
    kit = _kit(state)
    p2.counters["rad"] = 3
    p1.library.append(GameObject(_card("Filler", "Land", ""), owner_id="p1", zone=Zone.LIBRARY))
    _fund(p1, 3)
    engine.activate_ability(p1, kit, 0, mode=0)
    engine.resolve_until_stable()
    assert _modes(engine, p1, kit) == []  # tapped; check the exhaust set directly
    state.internal_turn.number += 1
    kit.tapped = False
    _fund(p1, 3)
    assert _modes(engine, p1, kit) == [1, 2]  # Stimpak stays spent on a later turn
    engine.activate_ability(p1, kit, 0, mode=2, targets=[p2])
    assert kit in state.battlefield  # sacrifice is part of resolution, not a cost
    engine.resolve_until_stable()
    assert kit not in state.battlefield and p2.counters.get("rad", 0) == 0


def test_med_kit_food_mode():
    engine, state, p1, p2 = _setup()
    kit = _kit(state)
    _fund(p1, 1)
    engine.activate_ability(p1, kit, 0, mode=1)
    engine.resolve_until_stable()
    assert any(o.name == "Food" for o in state.battlefield)


def test_bowls_modes_and_sacrifice_mode_resolves_not_pays():
    engine, state, p1, p2 = _setup()
    bowls = _bowls(state)
    foe = _bf(state, _card("Foe", "Creature — Bear", "", toughness=3), "p2")
    _fund(p1, 6)
    engine.activate_ability(p1, bowls, 0, mode=0, targets=[foe])
    engine.resolve_until_stable()
    assert foe.damage_marked == 2
    state.internal_turn.number += 1
    bowls.tapped = False
    assert _modes(engine, p1, bowls) == [1, 2]  # not restored by a new turn
    engine.activate_ability(p1, bowls, 0, mode=2)
    assert bowls in state.battlefield
    engine.resolve_until_stable()
    assert bowls not in state.battlefield and p1.life == 23


def test_countered_activation_still_consumes_the_mode():
    engine, state, p1, p2 = _setup()
    bowls = _bowls(state)
    foe = _bf(state, _card("Foe", "Creature — Bear", "", toughness=3), "p2")
    _fund(p1, 4)
    engine.activate_ability(p1, bowls, 0, mode=0, targets=[foe])
    state.stack.pop()  # countered (RULE 701.5): never resolves
    bowls.tapped = False
    _fund(p1, 4)
    assert _modes(engine, p1, bowls) == [1, 2]


def test_fizzled_activation_still_consumes_the_mode():
    engine, state, p1, p2 = _setup()
    bowls = _bowls(state)
    foe = _bf(state, _card("Foe", "Creature — Bear", "", toughness=3), "p2")
    _fund(p1, 4)
    engine.activate_ability(p1, bowls, 0, mode=0, targets=[foe])
    engine.rules.exile(foe)  # target gone: RULE 608.2b, the ability does nothing
    engine.resolve_until_stable()
    bowls.tapped = False
    _fund(p1, 4)
    assert _modes(engine, p1, bowls) == [2]  # mode 0 spent; mode 1 has no creature left to tap


def test_blink_resets_the_lifetime_form():
    engine, state, p1, p2 = _setup()
    bowls = _bowls(state)
    _fund(p1, 4)
    engine.activate_ability(p1, bowls, 0, mode=1, targets=[_bf(state, _card("Foe", "Creature — Bear", ""), "p2")])
    engine.resolve_until_stable()
    bowls.tapped = False
    _fund(p1, 4)
    assert _modes(engine, p1, bowls) == [0, 2]
    new = engine.rules.blink(bowls)
    new.summoning_sick = False
    _fund(p1, 4)
    assert _modes(engine, p1, new) == [0, 1, 2]


def test_clone_and_undo_restore_exhausted_mode():
    engine, state, p1, p2 = _setup()
    bowls = _bowls(state)
    _fund(p1, 4)
    before = state.clone()
    engine.activate_ability(p1, bowls, 0, mode=2)
    clone = state.clone()
    cb = next(o for o in clone.battlefield if o.name == "Three Bowls of Porridge")
    assert cb.activated_abilities[0].exhausted_modes(0) == {2}
    pb = next(o for o in before.battlefield if o.name == "Three Bowls of Porridge")
    assert pb.activated_abilities[0].exhausted_modes(0) == set()
