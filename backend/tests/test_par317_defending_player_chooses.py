"""PAR-317: the defending player chooses (RULE 506.2 / 508.1b).

"Defending player chooses / sacrifices / exiles <their own permanents>" opens a `choose_objects` for the player the
source attacks -- never the attacking controller and never the table's other opponent. Every case runs three players
whose two opponents differ (different boards), and the choice must be owned by the defender only.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.bots import create_bot
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
from mtg_analyzer.services.game_session import GameSessionManager

REAL = ("Crashing Boars", "Bane of Bala Ged", "Gisa's Favorite Shovel", "Ogre Marauder", "Witch-king, Bringer of Ruin")


def _real(name):
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _creature(name, oracle="", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Test", oracle_text=oracle, is_creature=True, power=power,
                toughness=toughness)


def _put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _three_player():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", []), ("p3", "C", [])], starting_life=20, starting_hand=0)
    return eng, eng.state


def _attack(eng, attacker, defender_id):
    """Declare ``attacker`` at ``defender_id`` and resolve until the first pending choice (or quiescence)."""
    state = eng.state
    state.current_step = "declare_attackers"
    eng.declare_attackers(state.active_player, [{"attacker": attacker, "defender": {"kind": "player", "id": defender_id}}])
    eng.resolve_until_stable()


def _ids(choice):
    return {o["instance_id"] for o in choice["options"] if "instance_id" in o}


def _answer(eng, instance_id):
    eng.resolve_pending_choice(str(instance_id))
    eng.resolve_until_stable()


# -- parser -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", REAL)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


@pytest.mark.parametrize("text", [
    "Whenever ~ dies, defending player exiles 2 permanents they control.",  # no combat event names a defender
    "Whenever ~ deals combat damage to a player, defending player sacrifices a creature of their choice. If they do, you create a Walker token.",
    "Whenever ~ dies, it gains \"~ can't be blocked\" until end of turn unless defending player sacrifices a creature of their choice.",
])
def test_heads_without_a_defender_stay_unclaimed(text):
    assert parse_oracle(_creature("Zed", text)).modeled is False


def test_least_power_edict_parses_for_each_opponent_too():
    spec = parse_oracle(_creature("Zed", "Whenever ~ attacks, each opponent sacrifices a creature with the least power among creatures they control.")).specs[0]
    assert spec.effects[0].params["least"] == "power"


# -- Crashing Boars: the defender names the blocker -------------------------------------------------------------------


def test_crashing_boars_defender_names_one_of_its_own_untapped_creatures_to_block():
    eng, state = _three_player()
    boars = _put(state, _real("Crashing Boars"))
    a2, b2 = _put(state, _creature("Pawn2"), "p2"), _put(state, _creature("Pawn2b"), "p2")
    a3, b3 = _put(state, _creature("Pawn3"), "p3"), _put(state, _creature("Pawn3b"), "p3")
    tapped = _put(state, _creature("Tapped3"), "p3")
    tapped.tapped = True
    _attack(eng, boars, "p3")
    choice = state.pending_choice
    assert choice["player_id"] == "p3"  # the defender, not the attacker and not the other opponent
    assert _ids(choice) == {a3.instance_id, b3.instance_id}  # untapped and theirs only
    _answer(eng, b3.instance_id)
    assert [r["kind"] for r in b3.temp_combat_restrictions] == ["must_block_target"]
    assert b3.temp_combat_restrictions[0]["filter"] == {"instance_id": boars.instance_id}
    assert not a3.temp_combat_restrictions and not a2.temp_combat_restrictions and not b2.temp_combat_restrictions
    # RULE 509.1c: the chosen creature must block if able.
    state.current_step = "declare_blockers"
    with pytest.raises(ValueError):
        eng.declare_blockers(state.player_by_id("p3"), [])
        eng._enforce_block_requirements()


def test_crashing_boars_with_no_untapped_creature_does_nothing():
    eng, state = _three_player()
    boars = _put(state, _real("Crashing Boars"))
    _put(state, _creature("Pawn2"), "p2")
    gone = _put(state, _creature("Tapped3"), "p3")
    gone.tapped = True
    _attack(eng, boars, "p3")
    assert state.pending_choice is None and not gone.temp_combat_restrictions


# -- Bane of Bala Ged: exile two of their own permanents --------------------------------------------------------------


def test_bane_of_bala_ged_defender_exiles_two_of_their_own_permanents():
    eng, state = _three_player()
    bane = _put(state, _real("Bane of Bala Ged"))
    mine2 = [_put(state, _creature(f"P2-{i}"), "p2") for i in range(3)]
    mine3 = [_put(state, _creature(f"P3-{i}"), "p3") for i in range(3)]
    _attack(eng, bane, "p3")
    choice = state.pending_choice
    assert choice["player_id"] == "p3"
    assert _ids(choice) == {o.instance_id for o in mine3}
    _answer(eng, mine3[2].instance_id)
    assert state.pending_choice["player_id"] == "p3"  # the second pick is still theirs
    _answer(eng, mine3[0].instance_id)
    assert [o.zone for o in mine3] == [Zone.EXILE, Zone.BATTLEFIELD, Zone.EXILE]
    assert all(o.zone is Zone.BATTLEFIELD for o in mine2) and bane.zone is Zone.BATTLEFIELD


def test_bane_of_bala_ged_exiles_everything_when_they_have_two_or_fewer():
    eng, state = _three_player()
    bane = _put(state, _real("Bane of Bala Ged"))
    theirs = [_put(state, _creature(f"P3-{i}"), "p3") for i in range(2)]
    _put(state, _creature("P2"), "p2")
    _attack(eng, bane, "p3")
    assert state.pending_choice is None and all(o.zone is Zone.EXILE for o in theirs)


# -- Gisa's Favorite Shovel: sacrifice, then the controller's Walker ---------------------------------------------------


def _equipped_attack(eng, state, defender_id):
    shovel = _put(state, _real("Gisa's Favorite Shovel"))
    host = _put(state, _creature("Host"))
    shovel.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    _attack(eng, host, defender_id)
    return shovel, host


def test_gisas_shovel_defender_sacrifices_and_the_controller_makes_the_walker():
    eng, state = _three_player()
    mine2 = _put(state, _creature("Pawn2"), "p2")
    keep3, lose3 = _put(state, _creature("Keep3"), "p3"), _put(state, _creature("Lose3"), "p3")
    _equipped_attack(eng, state, "p3")
    choice = state.pending_choice
    assert choice["player_id"] == "p3" and _ids(choice) == {keep3.instance_id, lose3.instance_id}
    _answer(eng, lose3.instance_id)
    assert lose3.zone is Zone.GRAVEYARD and keep3.zone is Zone.BATTLEFIELD and mine2.zone is Zone.BATTLEFIELD
    walkers = [o for o in state.permanents() if o.name == "Walker"]
    assert [w.controller_id for w in walkers] == ["p1"]  # the attacker's controller, not the defender


def test_gisas_shovel_defender_without_creatures_gives_no_walker():
    eng, state = _three_player()
    _put(state, _creature("Pawn2"), "p2")
    _equipped_attack(eng, state, "p3")
    assert state.pending_choice is None
    assert not [o for o in state.permanents() if o.name == "Walker"]


# -- Ogre Marauder: unless the defender sacrifices ---------------------------------------------------------------------


def test_ogre_marauder_defender_may_sacrifice_to_keep_it_blockable():
    eng, state = _three_player()
    ogre = _put(state, _real("Ogre Marauder"))
    _put(state, _creature("Pawn2"), "p2")
    pawn3 = _put(state, _creature("Pawn3"), "p3")
    _attack(eng, ogre, "p3")
    choice = state.pending_choice
    assert choice["player_id"] == "p3" and _ids(choice) == {pawn3.instance_id}
    _answer(eng, pawn3.instance_id)
    assert pawn3.zone is Zone.GRAVEYARD and not ogre.temp_unblockable


def test_ogre_marauder_declining_or_having_no_creature_makes_it_unblockable():
    eng, state = _three_player()
    ogre = _put(state, _real("Ogre Marauder"))
    _put(state, _creature("Pawn3"), "p3")
    _attack(eng, ogre, "p3")
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert ogre.temp_unblockable

    eng, state = _three_player()
    ogre = _put(state, _real("Ogre Marauder"))
    _put(state, _creature("Pawn2"), "p2")
    _attack(eng, ogre, "p3")
    assert state.pending_choice is None and ogre.temp_unblockable


# -- Witch-king, Bringer of Ruin: the least power, ties are the defender's pick -----------------------------------------


def test_witch_king_takes_the_single_least_power_creature_without_asking():
    eng, state = _three_player()
    king = _put(state, _real("Witch-king, Bringer of Ruin"))
    _put(state, _creature("Tiny2", power=0), "p2")
    small, big = _put(state, _creature("Small3", power=1), "p3"), _put(state, _creature("Big3", power=5), "p3")
    _attack(eng, king, "p3")
    assert state.pending_choice is None
    assert small.zone is Zone.GRAVEYARD and big.zone is Zone.BATTLEFIELD


def test_witch_king_tie_for_least_power_is_the_defenders_choice():
    eng, state = _three_player()
    king = _put(state, _real("Witch-king, Bringer of Ruin"))
    other = _put(state, _creature("Other2", power=1), "p2")
    a, b = _put(state, _creature("A3", power=1), "p3"), _put(state, _creature("B3", power=1), "p3")
    big = _put(state, _creature("Big3", power=4), "p3")
    _attack(eng, king, "p3")
    choice = state.pending_choice
    assert choice["player_id"] == "p3" and _ids(choice) == {a.instance_id, b.instance_id}
    _answer(eng, b.instance_id)
    assert b.zone is Zone.GRAVEYARD and a.zone is Zone.BATTLEFIELD and big.zone is Zone.BATTLEFIELD
    assert other.zone is Zone.BATTLEFIELD


def test_witch_king_each_opponent_reading_takes_each_opponents_least():
    eng, state = _three_player()
    edict = _put(state, _creature(
        "Edict", "Whenever ~ attacks, each opponent sacrifices a creature with the least power among creatures they control."))
    lo2, hi2 = _put(state, _creature("Lo2", power=1), "p2"), _put(state, _creature("Hi2", power=3), "p2")
    lo3, hi3 = _put(state, _creature("Lo3", power=0), "p3"), _put(state, _creature("Hi3", power=2), "p3")
    _attack(eng, edict, "p3")
    assert (lo2.zone, hi2.zone, lo3.zone, hi3.zone) == (Zone.GRAVEYARD, Zone.BATTLEFIELD, Zone.GRAVEYARD, Zone.BATTLEFIELD)


# -- a bot defender answers from its own view -------------------------------------------------------------------------


def _bot_session():
    land = Card(id="Forest", name="Forest", type_line="Basic Land — Forest", is_land=True)
    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": [land] * 30} for p in ("p1", "p2", "p3")],
        mulligan_style="none", keep_history=False,
    )
    for p in ("p1", "p2", "p3"):
        session.apply_action({"type": "keep_hand", "bottom_instance_ids": []}, actor_id=p)
    return session


def test_a_bot_defender_answers_its_own_choice_from_its_view_and_legal_actions():
    session = _bot_session()
    eng = session.engine
    state = eng.state
    king = _put(state, _real("Witch-king, Bringer of Ruin"), state.active_player.id)
    defender = "p3" if state.active_player.id != "p3" else "p2"
    other = "p2" if defender == "p3" else "p3"
    a = _put(state, _creature("A", power=1), defender)
    b = _put(state, _creature("B", power=1), defender)
    mine_other = _put(state, _creature("Other", power=1), other)
    _attack(eng, king, defender)
    choice = state.pending_choice
    assert choice["player_id"] == defender
    # The table's other seats are offered nothing; the defender's bot sees only choose actions over its own creatures.
    assert not [act for act in session.legal_actions(perspective=other) if act["type"] == "choose"]
    bot = create_bot("greedy", defender)
    view = session.view(perspective=defender)
    actions = session.legal_actions(perspective=defender)
    assert {act["instance_id"] for act in actions if act["type"] == "choose"} == {a.instance_id, b.instance_id}
    action = bot.decide(view, actions)
    assert action["type"] == "choose"
    session.apply_action(action, actor_id=defender)
    assert sorted(o.zone.value for o in (a, b)) == ["battlefield", "graveyard"]
    assert mine_other.zone is Zone.BATTLEFIELD
