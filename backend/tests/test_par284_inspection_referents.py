"""PAR-284 milestone 3: amounts that measure a card an earlier clause revealed or milled.

"Reveal the top card of your library. ~ gets +X/+0 until end of turn, where X is that card's mana value" (RULE 701.20),
"reveal cards ... until you reveal a nonland card. ..., where X is that card's mana value", "target opponent reveals a
card at random from their hand. ... where X is the revealed card's mana value" and "target player mills a card. ...,
where X is the milled card's mana value" (RULE 701.17). Parse tests pin the claimed cards and what stays unclaimed;
engine tests resolve spell-shaped bodies against a real library so the measured value is checked.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line, oracle, cost="{1}", mv=1, **kw):
    kw.setdefault("is_instant", type_line.startswith("Instant"))
    kw.setdefault("is_sorcery", type_line.startswith("Sorcery"))
    kw.setdefault("is_creature", "Creature" in type_line)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=mv,
                oracle_text=oracle, **kw)


def _modeled(card):
    return parse_oracle(card).modeled


# -- parse ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, oracle", [
    ("Putrid Cyclops", "When this creature enters, scry 1, then reveal the top card of your library. This creature gets -X/-X until end of turn, where X is that card's mana value."),
    ("Stormchaser Chimera", "{2}{U}{R}: Scry 1, then reveal the top card of your library. This creature gets +X/+0 until end of turn, where X is that card's mana value."),
    ("Goblin Machinist", "{2}{R}: Reveal cards from the top of your library until you reveal a nonland card. This creature gets +X/+0 until end of turn, where X is that card's mana value. Put the revealed cards on the bottom of your library in any order."),
    ("Planeswalker's Scorn", "{3}{B}: Target opponent reveals a card at random from their hand. Target creature gets -X/-X until end of turn, where X is the revealed card's mana value. Activate only as a sorcery."),
    ("Mindshrieker", "{2}: Target player mills a card. This creature gets +X/+X until end of turn, where X is the milled card's mana value."),
])
def test_inspection_referent_cards_are_modeled(name, oracle):
    assert _modeled(_card(name, "Creature — Bear", oracle, power=1, toughness=1))


@pytest.mark.parametrize("oracle", [
    # the milled noun needs a one-card mill right before it
    "Draw a card. ~ gets +X/+X until end of turn, where X is the milled card's mana value.",
    # a reveal that is not a lone library lead keeps the whole-block grammar's verdict
    "Reveal the top two cards of your library. ~ gets +X/+0 until end of turn, where X is that card's mana value.",
])
def test_referent_without_its_producer_stays_unclaimed(oracle):
    assert not _modeled(_card("Probe", "Creature — Bear", f"{{T}}: {oracle}", power=1, toughness=1))


# -- engine --------------------------------------------------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _stack_library(eng, owner, cards):
    """Put ``cards`` (name, type_line, mv) on ``owner``'s library, the first being the top card."""
    player = eng.state.player_by_id(owner)
    player.library.clear()
    for name, type_line, mv in reversed(cards):
        obj = GameObject(_card(name, type_line, "", cost="{1}", mv=mv), owner_id=owner, zone=Zone.LIBRARY)
        player.library.append(obj)
    return player


def _cast(eng, oracle, *, mana, targets=None, type_line="Instant"):
    card = _card("Probe Spell", type_line, oracle, cost="{1}", mv=1)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, obj, targets=targets)
    eng.resolve_until_stable()
    return p1


def _answer_pending(eng):
    """Acknowledge every pending 'ack' prompt (a reveal the player only has to look at)."""
    for _ in range(8):
        pending = eng.state.pending_choice
        if not pending:
            return
        eng.resolve_pending_choice("done")
        eng.resolve_until_stable()


def test_revealed_card_mana_value_drives_the_gain():
    eng = _engine()
    p1 = _stack_library(eng, "p1", [("Top Card", "Creature — Bear", 3), ("Next", "Land", 0)])
    p1 = _cast(eng, "Reveal the top card of your library. You gain life equal to that card's mana value.", mana={"C": 1})
    _answer_pending(eng)
    assert p1.life == 23


def test_reveal_until_nonland_measures_the_first_nonland_and_buries_all():
    eng = _engine()
    p1 = _stack_library(eng, "p1", [("Forest", "Basic Land — Forest", 0), ("Big Spell", "Sorcery", 5), ("Deep", "Land", 0)])
    _cast(eng, "Reveal cards from the top of your library until you reveal a nonland card. You gain life equal to that card's mana value. Put the revealed cards on the bottom of your library in any order.", mana={"C": 1})
    _answer_pending(eng)
    assert p1.life == 25
    assert sorted(o.name for o in p1.library) == ["Big Spell", "Deep", "Forest"]  # RULE 701.20: nothing leaves the library


def test_milled_card_mana_value_makes_that_many_tokens():
    eng = _engine()
    p2 = _stack_library(eng, "p2", [("Milled Four", "Sorcery", 4), ("Below", "Land", 0)])
    _cast(eng, "Target player mills a card. Create X 1/1 black Minion creature tokens, where X is the milled card's mana value.",
          mana={"C": 1}, targets=[p2])
    _answer_pending(eng)
    assert [o.name for o in p2.graveyard] == ["Milled Four"]
    assert len([o for o in eng.state.battlefield if o.is_token and o.controller_id == "p1"]) == 4


def test_random_hand_reveal_measures_the_revealed_card():
    eng = _engine()
    p2 = eng.state.players[1]
    p2.hand.append(GameObject(_card("Lone Card", "Sorcery", "", cost="{4}", mv=4), owner_id="p2", zone=Zone.HAND))
    p1 = _cast(eng, "Target opponent reveals a card at random from their hand. You gain life equal to the revealed card's mana value.",
               mana={"C": 1}, targets=[p2])
    _answer_pending(eng)
    assert p1.life == 24


def test_putrid_cyclops_shrinks_by_the_revealed_cards_mana_value():
    """The real card: scry (keep on top), reveal the top card, -X/-X with X its mana value."""
    eng = _engine()
    _stack_library(eng, "p1", [("Top Card", "Creature — Bear", 2), ("Next", "Land", 0)])
    oracle = ("When this creature enters, scry 1, then reveal the top card of your library. This creature gets -X/-X "
              "until end of turn, where X is that card's mana value.")
    card = _card("Putrid Cyclops", "Creature — Zombie Cyclops", oracle, cost="{2}{B}", mv=3, power=3, toughness=3)
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1 = eng.state.players[0]
    p1.hand.append(obj)
    p1.mana_pool.add_many({"B": 1, "C": 2})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "scry"
    eng.resolve_pending_choice("decline")  # keep the card on top
    eng.resolve_until_stable()
    _answer_pending(eng)
    eng.recompute_continuous_effects()
    assert (obj.power, obj.toughness) == (1, 1)
