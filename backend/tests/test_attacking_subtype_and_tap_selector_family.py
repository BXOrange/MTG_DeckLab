"""Tests for two small targeting/selector widenings:

* `TapEffect.selector`'s new ``"other_creatures_you_control"`` entry
  (Copperhorn Scout's "Whenever ~ attacks, untap each other creature you
  control.") — and the latent bug it surfaced: the selector branch never
  passed ``src=self.source`` to `continuous.group_selector_objects`, so
  "other" was silently a no-op exclusion for any selector needing it.
* `combat.matches_object_filter`'s new ``"attacking"`` key (Gnarlroot
  Trapper's "Target attacking Elf you control gains deathtouch until end
  of turn."), composing with the existing subtype filter.
"""

from __future__ import annotations

from mtg_analyzer.game import targeting
from mtg_analyzer.game.effects import GameContext, PumpEffect, TapEffect
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.player import Player
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bear(name="Bear"):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=2, toughness=2)


def _bf(state, card, controller="p1", tapped=True):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# TapEffect.selector == "other_creatures_you_control"
# ---------------------------------------------------------------------------


def test_untap_other_creatures_you_control_excludes_the_source():
    engine, state, p1, p2 = _rules()
    source = _bf(state, _bear("Attacker"))
    other_a = _bf(state, _bear("Other A"))
    other_b = _bf(state, _bear("Other B"))
    opp = _bf(state, _bear("Opp"), controller="p2")
    ctx = GameContext(state, engine)

    TapEffect(selector="other_creatures_you_control", untap=True, source=source).apply(ctx)

    assert source.tapped is True  # excluded — the "other" is load-bearing
    assert other_a.tapped is False
    assert other_b.tapped is False
    assert opp.tapped is True  # not yours — untouched


def test_copperhorn_scout_is_fully_modeled():
    card = Card(
        id="Copperhorn Scout", name="Copperhorn Scout", type_line="Creature — Elf Scout",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever this creature attacks, untap each other creature you control.",
    )
    assert parse_oracle(card).coverage == MODELED


# ---------------------------------------------------------------------------
# combat.matches_object_filter's "attacking" key
# ---------------------------------------------------------------------------


def test_attacking_filter_key_excludes_non_attacking_creatures():
    engine, state, p1, p2 = _rules()
    attacker = _bf(state, _bear("Attacker"), tapped=False)
    attacker.attacking = True
    bystander = _bf(state, _bear("Bystander"), tapped=False)

    spec = targeting.TargetSpec(kind="creature", creature_filter={"attacking": True})
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {attacker.instance_id}


def test_gnarlroot_trapper_is_fully_modeled():
    card = Card(
        id="Gnarlroot Trapper", name="Gnarlroot Trapper", type_line="Creature — Elf Scout",
        is_creature=True, power=1, toughness=1,
        oracle_text="{T}, Pay 1 life: Add {G}. Spend this mana only to cast an Elf creature spell.\n"
                     "{T}: Target attacking Elf you control gains deathtouch until end of turn.",
    )
    assert parse_oracle(card).coverage == MODELED


def test_gnarlroot_trapper_pump_only_targets_attacking_elves_you_control():
    engine, state, p1, p2 = _rules()
    attacking_elf = GameObject(
        Card(id="Elf1", name="Elf1", type_line="Creature — Elf", is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    attacking_elf.attacking = True
    state.add_to_battlefield(attacking_elf)
    nonattacking_elf = GameObject(
        Card(id="Elf2", name="Elf2", type_line="Creature — Elf", is_creature=True, power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    state.add_to_battlefield(nonattacking_elf)
    attacking_bear = GameObject(_bear("Attacking Bear"), owner_id="p1", zone=Zone.BATTLEFIELD)
    attacking_bear.attacking = True
    state.add_to_battlefield(attacking_bear)

    spec = targeting.TargetSpec(
        kind="creature_you_control", creature_filter={"attacking": True, "subtype": "Elf"},
    )
    legal = targeting.legal_targets(state, "p1", spec)
    assert {t["instance_id"] for t in legal} == {attacking_elf.instance_id}
