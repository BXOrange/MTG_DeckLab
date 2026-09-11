"""Blight Curse batch C5 wave 9 — Oft-Nabbed Goat
(hand-authored, `ability_catalogue/blight_curse.py`).

* Activated ability — new `ActivationCost.only_opponents_may_activate` (the
  inverse of Mercenaries' `any_player_may_activate`: every player *except*
  this permanent's controller may activate it), sorcery-speed. Effect body:
  activator draws, `gain_control_by_source` (``recipient="activator"`` — new
  branch), self ``add_counters``.
* Dies trigger — new `OwnerDrawOthersLosePerDyingCounterEffect`, gated by the
  trigger-level ``dying_had_counter`` intervening-if.
"""

from __future__ import annotations

from mtg_analyzer.game.ability_catalogue import specs_for
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone


OFT_NABBED_GOAT = Card(
    id="ONG", name="Oft-Nabbed Goat", type_line="Creature — Goat", is_creature=True,
    power=2, toughness=2,
    oracle_text="{1}: Draw a card. Gain control of this creature and put a -1/-1 "
                "counter on it. Only your opponents may activate this ability and only "
                "as a sorcery.\nWhen this creature dies, if it had one or more -1/-1 "
                "counters on it, its owner draws that many cards and each other player "
                "loses that much life.",
)


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    for pl in eng.state.players:
        for i in range(5):
            pl.library.append(GameObject(Card(id=f"L{pl.id}{i}", name=f"L{pl.id}{i}",
                                              type_line="Plains", is_land=True),
                                         owner_id=pl.id, zone=Zone.LIBRARY))
    return eng


def _goat(eng, controller="p1"):
    g = GameObject(OFT_NABBED_GOAT, owner_id="p1", zone=Zone.BATTLEFIELD)
    g.controller_id = controller
    eng.state.add_to_battlefield(g)
    bind_from_catalogue(g)
    return g


def test_oft_nabbed_goat_authored():
    specs = specs_for(OFT_NABBED_GOAT)
    act = [s for s in specs if s.ability_kind == "activated"]
    trg = [s for s in specs if s.ability_kind == "triggered"]
    assert len(act) == 1 and len(trg) == 1
    assert act[0].cost["only_opponents_may_activate"] is True
    assert act[0].cost["sorcery_speed_only"] is True
    assert trg[0].trigger["event"] == "DIES"
    assert trg[0].trigger["dying_had_counter"] == "-1/-1"


def test_controller_may_not_activate_even_at_sorcery_speed():
    eng = _engine()
    g = _goat(eng, controller="p1")
    p1 = eng.state.players[0]
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    p1.mana_pool.add("C", 1)
    assert not eng.can_activate(p1, g, g.activated_abilities[0])


def test_opponent_may_activate_only_at_their_sorcery_speed():
    eng = _engine()
    g = _goat(eng, controller="p1")
    p2 = eng.state.players[1]
    p2.mana_pool.add("C", 1)

    # p1's turn — p2 can't (sorcery speed = the activator's own main phase)
    eng.state.active_player_index = 0
    eng.state.current_step = "main1"
    assert not eng.can_activate(p2, g, g.activated_abilities[0])

    # p2's own main phase, empty stack — now legal
    eng.state.active_player_index = 1
    eng.state.current_step = "main1"
    assert eng.can_activate(p2, g, g.activated_abilities[0])


def test_activation_draws_gains_control_and_adds_a_counter():
    eng = _engine()
    g = _goat(eng, controller="p1")
    p2 = eng.state.players[1]
    eng.state.active_player_index = 1
    eng.state.current_step = "main1"
    p2.mana_pool.add("C", 1)
    hand0 = len(p2.hand)

    eng.activate_ability(p2, g)
    eng.resolve_until_stable()

    assert len(p2.hand) == hand0 + 1     # the activator draws
    assert g.controller_id == "p2"        # …and gains control
    assert g.counters.get("-1/-1", 0) == 1


def test_legal_actions_offers_the_ability_to_the_opponent_not_the_controller():
    eng = _engine()
    g = _goat(eng, controller="p1")
    p1, p2 = eng.state.players
    p2.mana_pool.add("C", 1)
    eng.state.active_player_index = 1
    eng.state.current_step = "main1"

    p2_offers = [a for a in eng.legal_actions(p2)
                 if a.get("type") == "activate_ability" and a.get("instance_id") == g.instance_id]
    assert p2_offers

    eng.state.active_player_index = 0
    p1_offers = [a for a in eng.legal_actions(p1)
                 if a.get("type") == "activate_ability" and a.get("instance_id") == g.instance_id]
    assert not p1_offers


def test_dies_with_counters_owner_draws_each_other_player_loses_life():
    eng = _engine()
    g = _goat(eng, controller="p2")   # control already stolen by p2
    p1, p2 = eng.state.players
    g.counters["-1/-1"] = 2
    eng.begin_turn()
    hand_owner0 = len(p1.hand)

    eng.rules.destroy(g)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand_owner0 + 2   # its owner (p1) draws N
    assert p2.life == 18                      # each other player loses N


def test_dies_without_counters_does_nothing():
    eng = _engine()
    g = _goat(eng, controller="p1")
    p1, p2 = eng.state.players
    eng.begin_turn()
    hand0 = len(p1.hand)

    eng.rules.destroy(g)
    eng.resolve_until_stable()

    assert len(p1.hand) == hand0
    assert p2.life == 20
