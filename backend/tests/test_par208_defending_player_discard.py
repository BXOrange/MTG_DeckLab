"""PAR-208 slice 2: "defending player discards N cards" under an attacks / isn't-blocked / becomes-blocked head
(RULE 508.1b), including the "you may sacrifice it. If you do, defending player discards 3 cards" chain."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine

_DB = CardDatabase(DB_PATH)


def _named(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _setup(attacker_name: str, hand_size: int = 4):
    eng = make_engine([creature(f"Lib {i}") for i in range(6)], [creature(f"Opp {i}") for i in range(6)], hand=0)
    state = eng.state
    eng.begin_turn()
    me = state.active_player.id
    p2 = next(p for p in state.players if p.id != me)  # the defending player
    for i in range(hand_size):
        p2.hand.append(GameObject(creature(f"Held {i}"), owner_id=p2.id, zone=Zone.HAND))
    attacker = GameObject(_named(attacker_name), owner_id=me, zone=Zone.BATTLEFIELD)
    attacker.controller_id = me
    attacker.summoning_sick = False
    bind_from_catalogue(attacker)
    state.add_to_battlefield(attacker)
    attacker.summoning_sick = False  # entered before this turn began
    return eng, attacker, p2


def _advance_to(eng, step):
    for _ in range(60):
        if eng.state.current_step == step:
            return
        eng.advance_step()
    raise AssertionError(step)


def _other(eng) -> str:
    return next(p.id for p in eng.state.players if p.id != eng.state.active_player.id)


def _attack(eng, attacker, blocker=None):
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(
        eng.state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": _other(eng)}}]
    )
    eng.resolve_until_stable()
    eng.state.current_step = "declare_blockers"
    if blocker is not None:
        eng.declare_blockers(eng.state.player_by_id(_other(eng)), [{"blocker": blocker, "attacker": attacker}])
    else:
        eng._fire_unblocked_events()  # RULE 509.1h: nobody blocked it
    eng.resolve_until_stable()


@pytest.mark.parametrize("name", [
    "Abyssal Nightstalker", "Alley Grifters", "Corrupt Official", "Dauthi Mindripper", "Mindstab Thrull",
    "Shrieking Specter", "Slate Street Ruffian", "The Haunt of Hightower",
])
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_named(name)).coverage == MODELED


def test_shrieking_specter_makes_the_defending_player_discard_on_attack():
    eng, specter, p2 = _setup("Shrieking Specter")
    _attack(eng, specter)
    choice = eng.state.pending_choice
    while choice is not None:
        eng.resolve_pending_choice(choice["options"][0]["id"])
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
    assert len(p2.hand) == 3 and len(p2.graveyard) == 1


def test_abyssal_nightstalker_discards_only_when_unblocked():
    eng, stalker, p2 = _setup("Abyssal Nightstalker")
    _attack(eng, stalker)
    choice = eng.state.pending_choice
    while choice is not None:
        eng.resolve_pending_choice(choice["options"][0]["id"])
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
    assert len(p2.hand) == 3


def test_dauthi_mindripper_sacrificed_discards_three():
    eng, ripper, p2 = _setup("Dauthi Mindripper", hand_size=5)
    _attack(eng, ripper)
    choice = eng.state.pending_choice
    assert choice is not None and {"do", "decline"} <= {o["id"] for o in choice["options"]}
    eng.resolve_pending_choice("do")
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    while choice is not None:
        eng.resolve_pending_choice(choice["options"][0]["id"])
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
    assert ripper.zone is Zone.GRAVEYARD and len(p2.hand) == 2


def test_dauthi_mindripper_declined_keeps_everything():
    eng, ripper, p2 = _setup("Dauthi Mindripper", hand_size=5)
    _attack(eng, ripper)
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert ripper.zone is Zone.BATTLEFIELD and len(p2.hand) == 5


def test_alley_grifters_makes_the_defending_player_discard_when_blocked():
    eng, grifters, p2 = _setup("Alley Grifters")
    blocker = GameObject(creature("Wall"), owner_id=p2.id, zone=Zone.BATTLEFIELD)
    blocker.controller_id = p2.id
    eng.state.add_to_battlefield(blocker)
    blocker.summoning_sick = False
    _attack(eng, grifters, blocker)
    choice = eng.state.pending_choice
    while choice is not None:
        eng.resolve_pending_choice(choice["options"][0]["id"])
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
    assert len(p2.hand) == 3  # RULE 508.1b: the blocked attacker's defending player (p2) discarded one of four
