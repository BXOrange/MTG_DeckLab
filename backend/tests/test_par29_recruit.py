"""PAR-29 — RULE 701.70 "Recruit" (Tales of Middle-earth).

"Draw a card, then discard a card. If you discarded a nonland card, create
a 1/1 white Human Soldier creature token." Connive's sibling —
`RulesEngine.recruit` owns it as its own small primitive (token payoff, not
a +1/+1 counter on a source) with a `recruit` "which card to discard"
`pending_choice`. `effects.RecruitEffect` is a bare "you"-subject effect.

Reference: game/rules/misc_mixin.py (`recruit` / `_recruit_discard` /
`resolve_recruit_choice`), game/effects.py (`RecruitEffect`),
parser/oracle/catalogue/handlers.py.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# --- parse ---------------------------------------------------------------


def test_recruit_parses():
    assert match_clause("recruit") == [EffectSpec("recruit", {})]


def test_real_recruit_card_modeled_end_to_end():
    boat = Card(id="GGB", name="Great Gilded Boat", type_line="Artifact — Vehicle",
                oracle_text="Whenever you attack, recruit. (Draw a card, then discard "
                            "a card. If you discarded a nonland card, create a 1/1 white "
                            "Human Soldier creature token.)\nCrew 2")
    assert parse_oracle(boat).modeled


# --- execute -----------------------------------------------------------------


def _engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    return eng, eng.state, eng.state.player_by_id("p1")


def _spell_card(name):
    return Card(id=name, name=name, type_line="Instant", is_instant=True,
                oracle_text="Deal 1 damage to any target.")


def _land_card(name="Forest"):
    return Card(id=name, name=name, type_line="Basic Land — Forest", is_land=True)


def _put_hand(player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    player.hand.append(obj)
    return obj


def _put_library(player, card):
    player.library.append(GameObject(card, owner_id=player.id, zone=Zone.LIBRARY))


def test_recruit_discard_nonland_makes_soldier_token():
    eng, state, p1 = _engine()
    _put_library(p1, _spell_card("Drawn"))          # will be drawn
    _put_hand(p1, _spell_card("InHand"))            # then two cards to choose from

    eng.rules.recruit(p1)
    choice = state.pending_choice
    assert choice is not None and choice["kind"] == "recruit"
    # discard the nonland "InHand"
    inhand = next(o for o in p1.hand if o.name == "InHand")
    eng.resolve_pending_choice(str(inhand.instance_id))

    assert state.pending_choice is None
    soldiers = [o for o in state.battlefield if o.name == "Soldier"]
    assert len(soldiers) == 1
    s = soldiers[0]
    assert (s.power, s.toughness) == (1, 1)
    assert s.colors == {"W"} and s.is_token
    assert "human soldier" in s.card.type_line.lower()


def test_recruit_discard_land_makes_no_token():
    eng, state, p1 = _engine()
    _put_library(p1, _spell_card("Drawn"))
    _put_hand(p1, _land_card("Forest"))

    eng.rules.recruit(p1)
    forest = next(o for o in p1.hand if o.name == "Forest")
    eng.resolve_pending_choice(str(forest.instance_id))

    assert not any(o.name == "Soldier" for o in state.battlefield)
    assert any(o.name == "Forest" for o in p1.graveyard)


def test_recruit_single_card_no_choice():
    eng, state, p1 = _engine()
    _put_library(p1, _spell_card("Drawn"))  # after draw, hand has exactly this one

    eng.rules.recruit(p1)

    assert state.pending_choice is None
    assert any(o.name == "Drawn" for o in p1.graveyard)
    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 1


def test_recruit_empty_library_still_discards_from_hand():
    eng, state, p1 = _engine()
    _put_hand(p1, _spell_card("A"))
    _put_hand(p1, _spell_card("B"))
    # empty library → draw does nothing, hand still has 2 → a choice

    eng.rules.recruit(p1)
    assert state.pending_choice["kind"] == "recruit"
    eng.resolve_pending_choice(None)  # default: first card

    assert len(p1.graveyard) == 1
    assert len([o for o in state.battlefield if o.name == "Soldier"]) == 1


def test_recruit_via_binder_on_etb():
    eng, state, p1 = _engine()
    _put_library(p1, _spell_card("Drawn"))
    _put_hand(p1, _spell_card("Held"))

    card = Card(id="EG", name="Esgaroth Garrison", type_line="Creature — Human Soldier",
                is_creature=True, power=1, toughness=3,
                oracle_text="When this creature enters, recruit.")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.controller_id = "p1"
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id,
        controller_id="p1", object_types=sorted(obj.type_words),
    ))
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()

    assert state.pending_choice is not None
    assert state.pending_choice["kind"] == "recruit"
