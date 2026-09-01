"""PAR-30 (Vote residue) — Living Death mass graveyard recursion.

"[each player returns / you return] all/each creature card[s] from
[their/your] graveyard to the battlefield / hand" — a mass, untargeted
recursion over every matching graveyard card
(`ReturnFromGraveyardEffect.players` = "you" / "each_player"). Magister of
Worth's grace vote branch, Empty the Catacombs, Storm of Souls, Finale of
Eternity.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import build_effects
from mtg_analyzer.game.effects import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state


def _gy(state, name, pid, *, creature=True):
    if creature:
        card = Card(id=name[:6], name=name, type_line="Creature — Zombie",
                    is_creature=True, power=2, toughness=2)
    else:
        card = Card(id=name[:6], name=name, type_line="Instant", is_instant=True)
    o = GameObject(card, owner_id=pid, zone=Zone.GRAVEYARD)
    state.player_by_id(pid).graveyard.append(o)
    return o


# --- parse --------------------------------------------------------------


def test_each_player_to_battlefield():
    assert match_clause(
        "each player returns each creature card from their graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield",
        "players": "each_player"})]


def test_each_player_to_hand():
    assert match_clause(
        "each player returns all creature cards from their graveyard to their hand"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "hand",
        "players": "each_player"})]


def test_you_scope():
    assert match_clause(
        "return all creature cards from your graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield",
        "players": "you"})]


def test_targeted_single_return_unaffected():
    assert match_clause(
        "return target creature card from your graveyard to the battlefield"
    ) == [EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield"})]


def test_real_cards_modeled():
    for name, tl, text in [
        ("Empty the Catacombs", "Sorcery",
         "Each player returns all creature cards from their graveyard to their hand."),
        ("Magister of Worth", "Creature — Angel",
         "Flying\nWhen Magister of Worth enters, "
         "starting with you, each player votes for grace or condemnation. If grace "
         "gets more votes, each player returns each creature card from their "
         "graveyard to the battlefield. If condemnation gets more votes or the vote "
         "is tied, destroy all creatures other than Magister of Worth."),
    ]:
        c = Card(id=name[:6], name=name, type_line=tl, oracle_text=text,
                 is_creature="Creature" in tl, is_sorcery="Sorcery" in tl,
                 power=4 if "Creature" in tl else None,
                 toughness=4 if "Creature" in tl else None)
        assert parse_oracle(c).coverage != UNMODELED, (name, parse_oracle(c).unclaimed)


# --- execute -----------------------------------------------------------


def test_each_player_return_reanimates_every_graveyard_creature():
    eng, state = _engine()
    a1 = _gy(state, "AZombie1", "p1")
    a2 = _gy(state, "AZombie2", "p1")
    _gy(state, "ABolt", "p1", creature=False)   # non-creature: stays
    b1 = _gy(state, "BZombie", "p2")

    src = GameObject(Card(id="MOW", name="Magister of Worth", type_line="Creature — Angel",
                          is_creature=True, power=4, toughness=4),
                     owner_id="p1", zone=Zone.BATTLEFIELD)
    src.controller_id = "p1"
    state.add_to_battlefield(src)

    build_effects([EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield",
        "players": "each_player"})], src)[0].apply(GameContext(state, eng.rules), None)

    bf = set(state.battlefield)
    assert {a1, a2, b1} <= bf
    assert a1.controller_id == "p1" and b1.controller_id == "p2"   # owner control
    assert len(state.player_by_id("p1").graveyard) == 1            # the Bolt


def test_you_scope_only_touches_your_graveyard():
    eng, state = _engine()
    mine = _gy(state, "Mine", "p1")
    theirs = _gy(state, "Theirs", "p2")
    src = GameObject(Card(id="SOS", name="Storm of Souls", type_line="Sorcery",
                          is_sorcery=True),
                     owner_id="p1", zone=Zone.STACK)
    src.controller_id = "p1"

    build_effects([EffectSpec("return_from_graveyard", {
        "target_kind": "graveyard_creature", "destination": "battlefield",
        "players": "you"})], src)[0].apply(GameContext(state, eng.rules), None)

    assert mine in state.battlefield
    assert theirs in state.player_by_id("p2").graveyard
