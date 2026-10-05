"""Bug report, 2026-09-04: a bot cast Betrayal ("Enchant creature an
opponent controls") on its own creature. RULE 303.4c makes a printed
controller qualifier on an "Enchant" line ("... you control" / "... you
don't control" / "... an opponent controls") a real targeting restriction,
but `parser/oracle/catalogue/keywords.py`'s ``enchant`` regex only ever
captured the bare type ("creature"), discarding the qualifier — so nothing
downstream ever filtered by it, at either target-selection time
(`targeting.legal_targets`) or resolve-time re-validation
(`RulesEngine._attachment_legal`, RULE 704.5m). A bot's "first legal
target" default (`services/bots.py`) had no way to avoid an illegal target
that was never actually excluded from "legal".
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.keywords import parse_keywords
from mtg_analyzer.game.targeting import legal_targets, spell_target_specs


def _card(name, oracle_text, type_line="Enchantment — Aura", **kw):
    return Card(id=name, name=name, type_line=type_line, keywords=["Enchant"],
                oracle_text=oracle_text, **kw)


def _betrayal():
    return _card(
        "Betrayal",
        "Enchant creature an opponent controls\nWhenever enchanted creature "
        "becomes tapped, you draw a card.",
    )


def _rancor():
    return _card(
        "Rancor",
        "Enchant creature you control\nEnchanted creature gets +2/+0 and has trample.",
    )


def _pacifism():
    return _card("Pacifism", "Enchant creature\nEnchanted creature can't attack or block.")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_an_opponent_controls_normalizes_to_not_you():
    [spec] = parse_keywords(_betrayal())
    assert spec.keyword == {"name": "enchant", "quality": "creature", "controller": "not_you"}


def test_you_control_normalizes_to_you():
    [spec] = parse_keywords(_rancor())
    assert spec.keyword == {"name": "enchant", "quality": "creature", "controller": "you"}


def test_you_dont_control_normalizes_to_not_you():
    card = _card("Test Aura", "Enchant creature you don't control\nFoo.")
    [spec] = parse_keywords(card)
    assert spec.keyword == {"name": "enchant", "quality": "creature", "controller": "not_you"}


def test_compound_quality_with_controller_qualifier():
    card = _card("Test Aura", "Enchant creature or planeswalker you don't control\nFoo.")
    [spec] = parse_keywords(card)
    assert spec.keyword == {
        "name": "enchant", "quality": "creature or planeswalker", "controller": "not_you",
    }


def test_plain_enchant_has_no_controller_qualifier():
    [spec] = parse_keywords(_pacifism())
    assert spec.keyword == {"name": "enchant", "quality": "creature"}


# ---------------------------------------------------------------------------
# Target-selection (targeting.legal_targets)
# ---------------------------------------------------------------------------


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def _hand_aura(state, player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    bind_from_catalogue(obj)
    return obj


def test_betrayal_only_offers_the_opponents_creature():
    eng = _engine()
    p1 = eng.state.active_player
    my_bear = _bf(eng.state, Card(id="Mine", name="Mine", type_line="Creature — Bear",
                                   is_creature=True, power=2, toughness=2))
    their_bear = _bf(eng.state, Card(id="Theirs", name="Theirs", type_line="Creature — Bear",
                                      is_creature=True, power=2, toughness=2), controller="p2")
    aura = _hand_aura(eng.state, p1, _betrayal())

    [spec] = spell_target_specs(aura)
    options = legal_targets(eng.state, "p1", spec, source=aura)
    assert {o["instance_id"] for o in options} == {their_bear.instance_id}
    assert my_bear.instance_id not in {o["instance_id"] for o in options}


def test_rancor_only_offers_the_casters_own_creature():
    eng = _engine()
    p1 = eng.state.active_player
    my_bear = _bf(eng.state, Card(id="Mine", name="Mine", type_line="Creature — Bear",
                                   is_creature=True, power=2, toughness=2))
    their_bear = _bf(eng.state, Card(id="Theirs", name="Theirs", type_line="Creature — Bear",
                                      is_creature=True, power=2, toughness=2), controller="p2")
    aura = _hand_aura(eng.state, p1, _rancor())

    [spec] = spell_target_specs(aura)
    options = legal_targets(eng.state, "p1", spec, source=aura)
    assert {o["instance_id"] for o in options} == {my_bear.instance_id}
    assert their_bear.instance_id not in {o["instance_id"] for o in options}


def test_unrestricted_enchant_still_offers_both():
    eng = _engine()
    p1 = eng.state.active_player
    my_bear = _bf(eng.state, Card(id="Mine", name="Mine", type_line="Creature — Bear",
                                   is_creature=True, power=2, toughness=2))
    their_bear = _bf(eng.state, Card(id="Theirs", name="Theirs", type_line="Creature — Bear",
                                      is_creature=True, power=2, toughness=2), controller="p2")
    aura = _hand_aura(eng.state, p1, _pacifism())

    [spec] = spell_target_specs(aura)
    options = legal_targets(eng.state, "p1", spec, source=aura)
    assert {o["instance_id"] for o in options} == {my_bear.instance_id, their_bear.instance_id}


# ---------------------------------------------------------------------------
# Resolve-time re-validation (RulesEngine._attachment_legal, RULE 704.5m)
# ---------------------------------------------------------------------------


def test_attachment_legal_rejects_the_casters_own_creature_for_betrayal():
    eng = _engine()
    my_bear = _bf(eng.state, Card(id="Mine", name="Mine", type_line="Creature — Bear",
                                   is_creature=True, power=2, toughness=2))
    aura = GameObject(_betrayal(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura)
    assert eng.rules._attachment_legal(aura, my_bear) is False


def test_attachment_legal_accepts_the_opponents_creature_for_betrayal():
    eng = _engine()
    their_bear = _bf(eng.state, Card(id="Theirs", name="Theirs", type_line="Creature — Bear",
                                      is_creature=True, power=2, toughness=2), controller="p2")
    aura = GameObject(_betrayal(), owner_id="p1", zone=Zone.BATTLEFIELD)
    bind_from_catalogue(aura)
    assert eng.rules._attachment_legal(aura, their_bear) is True
