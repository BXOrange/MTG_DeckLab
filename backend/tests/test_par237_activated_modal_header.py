"""PAR-237: a modal header behind an activation cost ("{1}, sacrifice ~: choose 1 -").

RULE 700.2 / RULE 602.2b: the mode is chosen on activation, and only the chosen mode's targets are announced
(RULE 601.2c). The engine's activated-mode path already existed (MEC-43); the parser now emits it.
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

CRATERMAKER = (
    "{1}, sacrifice ~: choose one —\n• ~ deals 2 damage to target creature.\n"
    "• Destroy target colorless nonland permanent."
)
BALM = (
    "{1}, {T}, sacrifice ~: Choose one —\n• You gain 2 life.\n"
    "• Prevent the next 2 damage that would be dealt to any target this turn."
)
TAP_MODAL = (
    "{1}{G}, {T}: Choose one —\n• You gain 3 life.\n• Draw a card."
)


def _card(name, type_line, oracle, **kw):
    kw.setdefault("is_creature", "creature" in type_line.lower())
    if kw["is_creature"]:
        kw.setdefault("power", 2)
        kw.setdefault("toughness", 2)
    cost = kw.pop("cost", "{1}")  # colour comes from the mana cost; the default is colourless
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle,
                mana_cost_string=cost, converted_mana_cost=1, **kw)


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


def _parsed(text, type_line="Creature — Goblin"):
    return parse_oracle(_card("X", type_line, text))


@pytest.mark.parametrize("text", [CRATERMAKER, BALM, TAP_MODAL])
def test_header_shapes_parse_as_one_modal_activated_ability(text):
    result = _parsed(text)
    assert result.coverage == "MODELED", result.unclaimed
    (spec,) = result.specs
    assert spec.ability_kind == "activated" and spec.effects == []
    assert len(spec.modes["options"]) == 2 and spec.modes["choose"] == 1
    assert spec.cost["text"].lower().startswith("{1}")


@pytest.mark.parametrize("header", [
    "{1}, sacrifice ~: choose one or both —",
    "{1}, sacrifice ~: choose two —",
    "{1}, sacrifice ~: choose one. activate only as a sorcery —",
])
def test_unsupported_header_variants_stay_unmodeled(header):
    text = f"{header}\n• You gain 2 life.\n• Draw a card."
    assert _parsed(text).coverage != "MODELED"


def test_unclaimed_mode_keeps_the_card_unmodeled():
    text = "{1}, sacrifice ~: Choose one —\n• You gain 2 life.\n• Frobnicate the quux."
    assert _parsed(text).coverage != "MODELED"


def test_sacrifice_cost_card_activates_each_mode():
    # Mode 0: 2 damage to target creature.
    engine, state, p1, p2 = _setup()
    maker = _bf(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER))
    victim = _bf(state, _card("Victim", "Creature — Bear", "", toughness=2), controller="p2")
    p1.mana_pool.add("R", 1)
    engine.activate_ability(p1, maker, 0, mode=0, targets=[victim])
    engine.resolve_until_stable()
    assert maker not in state.battlefield  # sacrifice is a cost (RULE 602.2b)
    assert victim not in state.battlefield

    # Mode 1: destroy target colorless nonland permanent.
    engine, state, p1, p2 = _setup()
    maker = _bf(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER))
    rock = _bf(state, _card("Rock", "Artifact", ""), controller="p2")
    p1.mana_pool.add("R", 1)
    engine.activate_ability(p1, maker, 0, mode=1, targets=[rock])
    engine.resolve_until_stable()
    assert maker not in state.battlefield
    assert rock not in state.battlefield


def test_modal_activation_offers_one_action_per_mode_and_only_chosen_mode_targets():
    engine, state, p1, p2 = _setup()
    maker = _bf(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER, cost="{1}{R}"))
    # Only a coloured creature exists: mode 0 has a legal target, mode 1 (colorless nonland) has none.
    _bf(state, _card("Victim", "Creature — Bear", "", cost="{G}"), controller="p2")
    p1.mana_pool.add("R", 1)
    actions = [a for a in engine.legal_actions(p1)
               if a.get("type") == "activate_ability" and a.get("instance_id") == maker.instance_id]
    by_mode = {a.get("mode"): a for a in actions}
    assert set(by_mode) == {0, 1}
    assert not by_mode[0].get("locked") and by_mode[0]["targets"]
    assert by_mode[1].get("locked")  # RULE 601.2c: only the chosen mode's targets matter


def test_illegal_target_for_chosen_mode_is_rejected_and_costs_stay_unpaid():
    engine, state, p1, p2 = _setup()
    maker = _bf(state, _card("Goblin Cratermaker", "Creature — Goblin Warrior", CRATERMAKER, cost="{1}{R}"))
    colored = _bf(state, _card("Bear", "Creature — Bear", "", cost="{G}"), controller="p2")
    p1.mana_pool.add("R", 1)
    with pytest.raises(ValueError, match="illegal targets"):
        engine.activate_ability(p1, maker, 0, mode=1, targets=[colored])
    assert maker in state.battlefield


def test_tap_cost_card_activates_each_mode():
    engine, state, p1, p2 = _setup()
    fungus = _bf(state, _card("Tapper", "Creature — Fungus", TAP_MODAL))
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    engine.activate_ability(p1, fungus, 0, mode=0)
    engine.resolve_until_stable()
    assert fungus.tapped and p1.life == 23

    engine, state, p1, p2 = _setup()
    fungus = _bf(state, _card("Tapper", "Creature — Fungus", TAP_MODAL))
    p1.mana_pool.add("G", 1)
    p1.mana_pool.add("C", 1)
    engine.activate_ability(p1, fungus, 0, mode=1)
    engine.resolve_until_stable()
    assert fungus.tapped
    assert p1.life == 20
