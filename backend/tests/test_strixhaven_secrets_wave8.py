"""Secrets of Strixhaven — playability batch, wave 8.

Wave 8: "a creature **token** you control deals combat damage to a player"
— a `(?P<token>)` slot on `segmenter._DAMAGE_TRIGGER_RE` →
`condition["is_token"]`, bound by a new positive `want_token` filter in
`effect_binder._build_group_ok` (mirror of `want_nontoken`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH


def _db():
    return CardDatabase(DEFAULT_DB_PATH)


def test_curiosity_crafter_modeled_with_token_filter():
    r = parse_oracle(_db().get_card("Curiosity Crafter"))
    assert r.coverage != UNMODELED, r.unclaimed
    trig = [s for s in r.specs if s.trigger and s.trigger["event"] == "DAMAGE"][0].trigger
    assert trig["condition"]["is_token"] is True
    assert trig["condition"]["controller"] == "you"
    assert trig["filter"] == {"is_player": True, "combat": True}


def _crafter_engine():
    eng = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])],
                              starting_hand=0, starting_life=20)
    p1 = eng.state.active_player
    for i in range(4):
        p1.library.append(GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Forest",
                                          is_land=True), owner_id=p1.id, zone=Zone.LIBRARY))
    cc = GameObject(_db().get_card("Curiosity Crafter"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    cc.controller_id = p1.id
    cc.summoning_sick = False
    eng.state.add_to_battlefield(cc)
    bind_from_catalogue(cc)
    return eng, p1


def _creature(eng, pid, token):
    o = GameObject(Card(id="k" + str(token), name="K", type_line="Creature — Elemental",
                        is_creature=True, power=2, toughness=2), owner_id=pid, zone=Zone.BATTLEFIELD)
    o.controller_id = pid
    o.is_token = token
    eng.state.add_to_battlefield(o)
    return o


def test_token_combat_damage_draws():
    eng, p1 = _crafter_engine()
    tok = _creature(eng, p1.id, token=True)
    before = len(p1.hand)
    eng.rules.deal_damage(eng.state.players[1], 2, source=tok, combat=True)
    eng.resolve_until_stable()
    assert len(p1.hand) - before == 1


def test_nontoken_combat_damage_does_not_draw():
    eng, p1 = _crafter_engine()
    nontok = _creature(eng, p1.id, token=False)
    before = len(p1.hand)
    eng.rules.deal_damage(eng.state.players[1], 2, source=nontok, combat=True)
    eng.resolve_until_stable()
    assert len(p1.hand) == before


def test_token_noncombat_damage_does_not_draw():
    eng, p1 = _crafter_engine()
    tok = _creature(eng, p1.id, token=True)
    before = len(p1.hand)
    eng.rules.deal_damage(eng.state.players[1], 2, source=tok, combat=False)
    eng.resolve_until_stable()
    assert len(p1.hand) == before
