"""PAR-120 (e): "spells you cast this turn … cost {N} less" / "the next spell
you cast this turn costs {N} less" — a player-owned RULE 601.2f discount in
`GameState.turn_cost_reductions` (Rowan, Scion of War; Hardened Berserker)."""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import EffectRegistry
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle


def _engine():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                                 starting_life=20, starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, engine.state


def _spell(player, name, cost, colors):
    card = Card(id=name, name=name, type_line="Sorcery", is_sorcery=True,
                mana_cost_string=cost, color_identity=set(colors))
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


def _resolve_single_effect(engine, card, source):
    parsed = parse_oracle(card)
    assert parsed.modeled, parsed.unclaimed
    [ability] = [a for a in parsed.specs if a.ability_kind in ("activated", "triggered")]
    # "Activate only as a sorcery" rides along as a marker effect.
    [spec] = [e for e in ability.effects if e.type != "sorcery_speed_marker"]
    effect = EffectRegistry.create(spec.type, spec.params)
    effect.source = source
    effect.apply(engine.rules.context, None)


ROWAN = Card(id="rowan", name="Rowan, Scion of War", type_line="Legendary Creature — Human",
             is_creature=True, power=4, toughness=2,
             oracle_text=("Menace\n{T}: Spells you cast this turn that are black and/or red cost "
                          "{X} less to cast, where X is the amount of life you lost this turn. "
                          "Activate only as a sorcery."))


def test_rowan_discounts_red_spells_by_life_lost_this_turn():
    engine, state = _engine()
    player = state.player_by_id("p1")
    engine.rules.lose_life(player, 3)
    rowan = GameObject(ROWAN, owner_id="p1", zone=Zone.BATTLEFIELD)
    rowan.controller_id = "p1"
    state.add_to_battlefield(rowan)
    _resolve_single_effect(engine, ROWAN, rowan)
    red = _spell(player, "Red", "{4}{R}", ["R"])
    green = _spell(player, "Green", "{4}{G}", ["G"])
    assert continuous.cost_reduction_for(state, player, red)[0] == 3
    assert continuous.cost_reduction_for(state, player, green)[0] == 0
    player.mana_pool.add("R", 1)
    player.mana_pool.add("C", 1)
    engine.cast_spell(player, red)
    assert red.zone == Zone.STACK
    # Not a "next spell" discount: still there for the rest of the turn.
    assert continuous.cost_reduction_for(state, player, _spell(player, "Red2", "{2}{R}", ["R"]))[0] == 3
    engine._step_cleanup()  # RULE 514.2: "this turn" ends here
    assert state.turn_cost_reductions == []


def test_the_next_spell_discount_is_used_up_by_one_cast():
    engine, state = _engine()
    player = state.player_by_id("p1")
    card = Card(id="berserker", name="Hardened Berserker", type_line="Creature — Human Berserker",
                is_creature=True, power=3, toughness=2,
                oracle_text=("Whenever Hardened Berserker attacks, the next spell you cast this "
                             "turn costs {1} less to cast."))
    berserker = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    berserker.controller_id = "p1"
    state.add_to_battlefield(berserker)
    _resolve_single_effect(engine, card, berserker)
    first = _spell(player, "First", "{1}{R}", ["R"])
    assert continuous.cost_reduction_for(state, player, first)[0] == 1
    player.mana_pool.add("R", 1)
    engine.cast_spell(player, first)
    assert first.zone == Zone.STACK
    assert state.turn_cost_reductions == []


@pytest.mark.parametrize("power", [2, 5])
def test_maelstrom_muse_measures_power_as_the_ability_resolves(power):
    engine, state = _engine()
    player = state.player_by_id("p1")
    card = Card(id="muse", name="Maelstrom Muse", type_line="Creature — Djinn Wizard",
                is_creature=True, power=power, toughness=4,
                oracle_text=("Flying\nWhenever Maelstrom Muse attacks, the next instant or sorcery "
                             "spell you cast this turn costs {X} less to cast, where X is Maelstrom "
                             "Muse's power as this ability resolves."))
    muse = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    muse.controller_id = "p1"
    state.add_to_battlefield(muse)
    _resolve_single_effect(engine, card, muse)
    assert continuous.cost_reduction_for(state, player, _spell(player, "S", "{6}{U}", ["U"]))[0] == power
    creature = GameObject(Card(id="c", name="C", type_line="Creature — Elf", is_creature=True,
                               power=1, toughness=1, mana_cost_string="{3}{G}"),
                          owner_id="p1", zone=Zone.HAND)
    assert continuous.cost_reduction_for(state, player, creature)[0] == 0
