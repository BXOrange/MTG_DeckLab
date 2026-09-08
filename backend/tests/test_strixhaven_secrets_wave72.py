"""Secrets of Strixhaven — playability batch, wave 72 (PAR-60).

Augusta, Order Returned — new
`each_player_exile_from_graveyard_then_counters` effect: one atomic effect
over a shared "target attacking creature" that auto-exiles each player's
oldest graveyard card and puts one +1/+1 counter per nonland exiled onto
the target.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import _REGISTRY, is_registered, specs_for
from mtg_analyzer.game.effect_binder import bind_ability, bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _augusta_card():
    return Card(id="ag", name="Augusta, Order Returned",
                type_line="Legendary Creature — Spirit Advisor", is_creature=True,
                power=1, toughness=3,
                oracle_text=("Flying, vigilance\nWhenever Augusta attacks, each player "
                             "exiles a card from their graveyard. When one or more "
                             "nonland cards are exiled this way, put that many +1/+1 "
                             "counters on target attacking creature."))


def test_registered_and_binds():
    assert is_registered("Augusta, Order Returned")
    spec = _REGISTRY["augusta, order returned"]()[0]
    spec.validate()
    assert spec.trigger["event"] == "ATTACKS"
    assert spec.effects[0].type == "each_player_exile_from_graveyard_then_counters"
    src = GameObject(_augusta_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    bind_ability(spec, src)


def test_specs_for_real_card():
    assert specs_for(_augusta_card())


def _gy(player, name, is_land=False):
    c = Card(id=name, name=name,
             type_line="Basic Land — Forest" if is_land else "Sorcery",
             is_land=is_land, is_sorcery=not is_land)
    o = GameObject(c, owner_id=player.id, zone=Zone.GRAVEYARD)
    player.add_to_zone(o, Zone.GRAVEYARD)
    return o


def test_attack_exiles_each_graveyard_and_scales_counters_by_nonland():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")

    aug = GameObject(_augusta_card(), owner_id="p1", zone=Zone.BATTLEFIELD)
    aug.controller_id = "p1"
    aug.summoning_sick = False
    eng.state.add_to_battlefield(aug)
    bind_from_catalogue(aug)

    attacker = GameObject(Card(id="bear", name="Bear", type_line="Creature — Bear",
                               is_creature=True, power=2, toughness=2),
                          owner_id="p1", zone=Zone.BATTLEFIELD)
    attacker.controller_id = "p1"
    attacker.summoning_sick = False
    attacker.attacking = True
    eng.state.add_to_battlefield(attacker)

    p1_spell = _gy(p1, "P1Spell", is_land=False)
    p2_land = _gy(p2, "P2Land", is_land=True)
    p2_spell = _gy(p2, "P2Spell", is_land=False)

    eng.recompute_continuous_effects()
    spec = _REGISTRY["augusta, order returned"]()[0]
    from mtg_analyzer.game.effect_binder import bind_ability as _ba
    trig = _ba(spec, aug)
    # resolve the triggered ability's effect directly against the attacker
    eng.rules._apply_effect_specs(
        [{"type": "each_player_exile_from_graveyard_then_counters", "params": {}}],
        aug, targets=[attacker],
    )
    eng.resolve_until_stable()

    assert p1_spell.zone == Zone.EXILE
    assert p2_land.zone == Zone.EXILE  # oldest in p2's graveyard
    assert p2_spell in p2.graveyard    # only one card per player
    # nonland exiled: p1's spell only (p2's oldest was the land) -> 1 counter
    assert attacker.counters.get("+1/+1") == 1
