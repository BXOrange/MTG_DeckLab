"""Tests for MEC-17 — RULE 702.45-adjacent Imprint (Chrome Mox).

Two new primitives, both general rather than Chrome-Mox-specific:

* `RulesEngine.request_choose_objects`'s new ``remember=True`` param
  (`game/rules/misc_mixin.py`) — stamps whichever object gets
  ``action="exile"``ed onto the calling permanent's own
  `GameObject.linked_exile_id`, the same field `ExileEffect(remember=True)`
  already uses for the unrelated O-Ring return-when-leaves shape.
* `ManaAbility.color_selector`'s new ``"imprinted_card_colors"`` kind
  (`game/mana_abilities.py`) — "Add one mana of any of the exiled card's
  colors," a menu built fresh every tap off whatever `linked_exile_id`
  currently points at.

`ImprintEffect` (`game/effects/core.py`) is the ETB half — "you may exile a
`<filter>` card from your hand" — riding `request_choose_objects` exactly
like Gemstone Caverns' own pregame "exile a card from your hand" tail
already does, just with `remember=True` added.

Reference: mtg_analyzer/game/effects/core.py (`ImprintEffect`),
game/mana_abilities.py (`_IMPRINTED_COLOR_ADD_RE`, `resolve_options`),
game/rules/misc_mixin.py (`request_choose_objects`), game/ability_catalogue.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import ability_catalogue, mana_abilities
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str):
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def filler(name="Filler"):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string="{0}",
        converted_mana_cost=0, is_instant=True,
    )


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [filler("F1")] * 5), ("p2", "Bob", [filler("F2")] * 5)],
        starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def battlefield_bound(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def to_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    eng.state.player_by_id(controller).hand.append(obj)
    return obj


def enter_mox(eng, mox):
    eng.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, instance_id=mox.instance_id))
    eng.resolve_until_stable()


def test_chrome_mox_is_registered_on_imprint():
    assert ability_catalogue.is_registered("Chrome Mox")
    specs = ability_catalogue.specs_for(_card("Chrome Mox"))
    assert len(specs) == 1
    effect = specs[0].effects[0]
    assert effect.type == "imprint"
    assert set(effect.params.get("exclude_card_types", [])) == {"artifact", "land"}


def test_etb_offers_only_nonartifact_nonland_hand_cards():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    bolt = to_hand(eng, _card("Lightning Bolt"))  # instant, qualifies
    to_hand(eng, _card("Sol Ring"))  # artifact, excluded
    to_hand(eng, _card("Island"))  # land, excluded
    enter_mox(eng, mox)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "choose_objects"
    offered_ids = {o.get("instance_id") for o in choice["options"] if "instance_id" in o}
    assert offered_ids == {bolt.instance_id}
    assert any(o["id"] == "decline" for o in choice["options"])


def test_exiling_the_chosen_card_remembers_it():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    bolt = to_hand(eng, _card("Lightning Bolt"))
    enter_mox(eng, mox)
    eng.resolve_pending_choice(str(bolt.instance_id))
    assert eng.state.pending_choice is None
    assert bolt in p1.exile
    assert bolt not in p1.hand
    assert mox.linked_exile_id == bolt.instance_id


def test_declining_remembers_nothing():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    to_hand(eng, _card("Lightning Bolt"))
    enter_mox(eng, mox)
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert mox.linked_exile_id is None


def test_no_qualifying_card_never_opens_a_choice():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    to_hand(eng, _card("Sol Ring"))  # artifact only — nothing qualifies
    enter_mox(eng, mox)
    assert eng.state.pending_choice is None
    assert mox.linked_exile_id is None


def test_mana_ability_produces_the_imprinted_cards_own_color():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    bolt = to_hand(eng, _card("Lightning Bolt"))  # mono-red
    enter_mox(eng, mox)
    eng.resolve_pending_choice(str(bolt.instance_id))
    abilities = mana_abilities.mana_abilities_for(mox, state=eng.state)
    assert len(abilities) == 1
    options = mana_abilities.resolve_options(abilities[0], mox, eng.state)
    assert options == [{"R": 1}]
    produced = eng.tap_for_mana(p1, mox)
    assert produced == {"R": 1}


def test_mana_ability_offers_a_menu_for_a_multicolor_imprint():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    helix = to_hand(eng, _card("Lightning Helix"))  # R/W
    enter_mox(eng, mox)
    eng.resolve_pending_choice(str(helix.instance_id))
    abilities = mana_abilities.mana_abilities_for(mox, state=eng.state)
    options = mana_abilities.resolve_options(abilities[0], mox, eng.state)
    assert {frozenset(o.items()) for o in options} == {
        frozenset({("R", 1)}), frozenset({("W", 1)}),
    }
    produced = eng.tap_for_mana(p1, mox, option_index=0)
    assert produced in ({"R": 1}, {"W": 1})


def test_with_no_imprinted_card_the_mana_ability_produces_nothing():
    eng, p1, p2 = two_player_engine()
    mox = battlefield_bound(eng, _card("Chrome Mox"))
    abilities = mana_abilities.mana_abilities_for(mox, state=eng.state)
    options = mana_abilities.resolve_options(abilities[0], mox, eng.state)
    assert options == []
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, mox)
