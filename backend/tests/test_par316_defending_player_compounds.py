"""PAR-316: defending-player pay-or-sacrifice compounds (RULE 506.2 / 508.1b, 118.3, 510.1e).

"you may pay {R} / sacrifice ~ / exile ... . If you do, <effect on the defending player's stuff> and ~ assigns no
combat damage this turn", plus the wheel and random-discard payoffs of the same unblocked-attacker family. Every
engine case seats three players so the two opponents differ for each gained card.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

GOBLIN_VANDAL = (
    "Whenever ~ attacks and isn't blocked, you may pay {R}. If you do, destroy target artifact defending player controls "
    "and ~ assigns no combat damage this turn."
)
NECRITE = (
    "Whenever ~ attacks and isn't blocked, you may sacrifice it. If you do, destroy target creature defending player "
    "controls. It can't be regenerated."
)
BADGER = (
    "Whenever ~ attacks and isn't blocked, you may exile up to two target creature cards from defending player's graveyard. "
    "If you do, you gain 1 life for each card exiled this way and ~ assigns no combat damage this turn."
)
CLOAK = (
    "Enchant creature you control\nWhenever enchanted creature attacks and isn't blocked, you may have it assign no combat "
    "damage this turn. If you do, defending player discards a card at random."
)
ROBBER_FLY = "Flying\nWhenever ~ becomes blocked, defending player discards all the cards in their hand, then draws that many cards."
MTENDA = "Whenever ~ attacks, defending player may pay {U}. If that player does, prevent all combat damage that would be dealt by ~ this turn."


def _three_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _card(name, oracle="", power=2, toughness=2, type_line="Creature — Test", **kw):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                power=power if creature else None, toughness=toughness if creature else None, **kw)


def _in_zone(state, pid, name, zone):
    obj = GameObject(_card(name), owner_id=pid, zone=zone)
    getattr(state.player_by_id(pid), zone.value).append(obj)
    return obj


def _settle(eng, take=("pay", "yes")):
    """Resolve the stack; a pending choice is answered with the first of ``take`` it offers, else its first option."""
    eng.resolve_until_stable()
    while eng.state.pending_choice is not None:
        choice = eng.state.pending_choice
        ids = [o["id"] for o in choice["options"]]
        eng.resolve_pending_choice(next((t for t in take if t in ids), ids[0]))
        eng.resolve_until_stable()


def _attack(eng, attackers, defender_id, *, blocker=None, take=("pay", "yes")):
    state = eng.state
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [
        {"attacker": a, "defender": {"kind": "player", "id": defender_id}} for a in attackers
    ])
    _settle(eng, take)
    state.current_step = "declare_blockers"
    if blocker is not None:
        eng.declare_blockers(state.player_by_id(blocker.controller_id), [{"blocker": blocker, "attacker": attackers[0]}])
    else:
        eng._fire_unblocked_events()
    _settle(eng, take)


# -- parser -----------------------------------------------------------------------------------------------------------


def _coverage(text, **kw):
    return parse_oracle(_card("Zed", text, **kw)).coverage


@pytest.mark.parametrize("text", [GOBLIN_VANDAL, NECRITE, BADGER, CLOAK, ROBBER_FLY, MTENDA])
def test_printed_cards_are_modeled(text):
    assert _coverage(text, keywords=["Flying"] if "Flying" in text else []) == "MODELED"


def test_vandal_payoff_and_rider_ride_the_payment():
    spec = parse_oracle(_card("Zed", GOBLIN_VANDAL)).specs[0]
    assert [e.type for e in spec.effects] == ["pay_cost_then"]  # the rider is not split out as an unconditional effect
    assert [e["type"] for e in spec.effects[0].params["effects"]] == ["destroy", "assign_no_combat_damage"]


def test_necrite_denies_regeneration_to_the_destroy_only():
    spec = parse_oracle(_card("Zed", NECRITE)).specs[0]
    assert [e.type for e in spec.effects] == ["sacrifice_self", "destroy"]
    assert spec.effects[1].params["can_be_regenerated"] is False


@pytest.mark.parametrize("text", [
    # the rider belongs to the source only: another creature's combat damage is a different effect
    "Whenever ~ attacks and isn't blocked, you may pay {R}. If you do, destroy target artifact defending player controls "
    "and target creature assigns no combat damage this turn.",
    # the pay-or-sacrifice antecedent must be a cost the payer can really be asked for
    "Whenever ~ attacks and isn't blocked, you may frobnicate. If you do, destroy target artifact defending player controls "
    "and ~ assigns no combat damage this turn.",
    # a defending player who pays for an effect that is not modeled leaves the card unclaimed
    "Whenever ~ attacks, defending player may pay {U}. If that player does, frobnicate ~.",
])
def test_near_misses_stay_unclaimed(text):
    assert _coverage(text) != "MODELED"


def test_attached_head_side_gain_keeps_both_events_on_the_host():
    # Kaya's Ghostform's "enchanted permanent" head rides the same attached-host subject (it was unclaimed before).
    specs = parse_oracle(_card(
        "Zed", "Enchant creature or planeswalker you control\n"
        "When enchanted permanent dies or is put into exile, return that card to the battlefield under your control.",
        type_line="Enchantment — Aura",
    )).specs
    triggers = [s.trigger for s in specs if s.ability_kind == "triggered"]
    assert [t["event"] for t in triggers] == ["DIES", "LEAVES_BATTLEFIELD"]
    assert all(t["condition"] == {"subject": "attached_permanent"} for t in triggers)


# -- engine: three players, the two opponents differ ------------------------------------------------------------------


def _float(state, pid, mana):
    player = state.player_by_id(pid)
    player.mana_pool.add_many(mana)
    return player


def _silenced(obj):
    return bool(getattr(obj, "temp_assign_no_combat_damage", False))


def test_vandal_paying_destroys_the_defenders_artifact_and_deals_no_combat_damage():
    eng, state = _three_player()
    atk = _put(state, _card("Vandal", GOBLIN_VANDAL))
    rock2 = _put(state, _card("Rock2", type_line="Artifact"), "p2")
    rock3 = _put(state, _card("Rock3", type_line="Artifact"), "p3")
    me = _float(state, "p1", {"R": 1})
    _attack(eng, [atk], "p3")
    assert rock3.zone is Zone.GRAVEYARD and rock2.zone is Zone.BATTLEFIELD  # the attacked player's, not the other's
    assert me.mana_pool.total() == 0  # the {R} was really spent
    assert _silenced(atk)


def test_vandal_unable_to_pay_changes_nothing():
    eng, state = _three_player()
    atk = _put(state, _card("Vandal", GOBLIN_VANDAL))
    rock3 = _put(state, _card("Rock3", type_line="Artifact"), "p3")
    _attack(eng, [atk], "p3")
    assert rock3.zone is Zone.BATTLEFIELD
    assert not _silenced(atk)  # no payment, no rider


def test_vandal_declined_payment_keeps_the_mana_and_the_rider():
    eng, state = _three_player()
    atk = _put(state, _card("Vandal", GOBLIN_VANDAL))
    rock3 = _put(state, _card("Rock3", type_line="Artifact"), "p3")
    me = _float(state, "p1", {"R": 1})
    _attack(eng, [atk], "p3", take=("decline", "no"))
    assert rock3.zone is Zone.BATTLEFIELD and me.mana_pool.total() == 1
    assert not _silenced(atk)


def test_necrite_sacrifices_itself_to_destroy_the_defenders_creature():
    eng, state = _three_player()
    atk = _put(state, _card("Necrite", NECRITE))
    bear2 = _put(state, _card("Bear2"), "p2")
    bear3 = _put(state, _card("Bear3"), "p3")
    _attack(eng, [atk], "p3")
    assert atk.zone is Zone.GRAVEYARD  # the sacrifice really happened
    assert bear3.zone is Zone.GRAVEYARD and bear2.zone is Zone.BATTLEFIELD


def test_necrite_declined_sacrifice_destroys_nothing():
    eng, state = _three_player()
    atk = _put(state, _card("Necrite", NECRITE))
    bear3 = _put(state, _card("Bear3"), "p3")
    _attack(eng, [atk], "p3", take=("decline", "no"))
    assert atk.zone is Zone.BATTLEFIELD and bear3.zone is Zone.BATTLEFIELD


def test_necrite_destroy_ignores_a_regeneration_shield():
    eng, state = _three_player()
    atk = _put(state, _card("Necrite", NECRITE))
    bear3 = _put(state, _card("Bear3"), "p3")
    bear3.regeneration_shields = 1
    _attack(eng, [atk], "p3")
    assert bear3.zone is Zone.GRAVEYARD  # RULE 701.19c: it can't be regenerated


def test_badger_exiles_from_the_defenders_graveyard_and_gains_per_card():
    eng, state = _three_player()
    atk = _put(state, _card("Badger", BADGER))
    mine = [_in_zone(state, "p2", f"Two{i}", Zone.GRAVEYARD) for i in range(2)]
    theirs = [_in_zone(state, "p3", f"Three{i}", Zone.GRAVEYARD) for i in range(3)]
    _attack(eng, [atk], "p3")
    assert all(c.zone is Zone.EXILE for c in theirs[:2]) and theirs[2].zone is Zone.GRAVEYARD
    assert all(c.zone is Zone.GRAVEYARD for c in mine)  # the other opponent's graveyard is untouched
    assert state.player_by_id("p1").life == 22  # 1 life for each of the two cards exiled this way
    assert _silenced(atk)


def test_badger_with_an_empty_defender_graveyard_gains_nothing():
    eng, state = _three_player()
    atk = _put(state, _card("Badger", BADGER))
    _in_zone(state, "p2", "Two", Zone.GRAVEYARD)
    _attack(eng, [atk], "p3")
    assert state.player_by_id("p1").life == 20


def test_cloak_discards_from_the_defenders_hand_only_when_it_silences_the_host():
    eng, state = _three_player()
    host = _put(state, _card("Host"))
    _put(state, _card("Cloak", CLOAK, type_line="Enchantment — Aura")).attached_to = host.instance_id
    h2 = [_in_zone(state, "p2", f"H2{i}", Zone.HAND) for i in range(2)]
    h3 = [_in_zone(state, "p3", f"H3{i}", Zone.HAND) for i in range(2)]
    _attack(eng, [host], "p3")
    assert len(state.player_by_id("p3").hand) == 1 and len(state.player_by_id("p2").hand) == 2
    assert _silenced(host)


def test_cloak_declined_discards_nothing_and_the_host_still_deals_damage():
    eng, state = _three_player()
    host = _put(state, _card("Host"))
    _put(state, _card("Cloak", CLOAK, type_line="Enchantment — Aura")).attached_to = host.instance_id
    for i in range(2):
        _in_zone(state, "p3", f"H3{i}", Zone.HAND)
    _attack(eng, [host], "p3", take=("decline", "no"))
    assert len(state.player_by_id("p3").hand) == 2 and not _silenced(host)


def test_robber_fly_wheels_the_blockers_controller_hand():
    eng, state = _three_player()
    fly = _put(state, _card("Fly", ROBBER_FLY, keywords=["Flying"]))
    wall = _put(state, _card("Wall", "Reach", keywords=["Reach"]), "p3")
    for pid, n in (("p2", 2), ("p3", 3)):
        for i in range(n):
            _in_zone(state, pid, f"H{pid}{i}", Zone.HAND)
            state.player_by_id(pid).library.append(GameObject(_card(f"L{pid}{i}"), owner_id=pid, zone=Zone.LIBRARY))
            state.player_by_id(pid).library.append(GameObject(_card(f"M{pid}{i}"), owner_id=pid, zone=Zone.LIBRARY))
    old = {c.name for c in state.player_by_id("p3").hand}
    _attack(eng, [fly], "p3", blocker=wall)
    p3, p2 = state.player_by_id("p3"), state.player_by_id("p2")
    assert len(p3.hand) == 3 and not ({c.name for c in p3.hand} & old)  # a fresh hand of as many cards
    assert len(p2.hand) == 2 and all(c.name.startswith("Hp2") for c in p2.hand)
    assert len(p3.graveyard) == 3


def test_mtenda_lion_prevents_combat_damage_only_if_the_defender_pays():
    for pays, expected_life in ((True, 20), (False, 18)):
        eng, state = _three_player()
        lion = _put(state, _card("Lion", MTENDA))
        _float(state, "p3", {"U": 1})
        _attack(eng, [lion], "p3", take=("pay",) if pays else ("decline", "no"))
        assert state.player_by_id("p3").mana_pool.total() == (0 if pays else 1)  # the {U} is the defender's own
        assert state.player_by_id("p2").mana_pool.total() == 0
