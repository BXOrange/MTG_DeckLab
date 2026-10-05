"""PAR-143: graveyard → battlefield returns that enter tapped [and attacking], plus the untargeted
pick ("return a land card …") and the typed mass ("return all land cards …") they ride with."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _card(name: str, text: str = "", type_line: str = "Creature — Bear", power: int = 2) -> Card:
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=creature,
        is_land="Land" in type_line, is_sorcery=type_line.startswith("Sorcery"),
        power=power if creature else None, toughness=2 if creature else None, oracle_text=text,
    )


def _in_graveyard(eng: GameEngine, card: Card, owner: str = "p1") -> GameObject:
    obj = GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD)
    eng.state.player_by_id(owner).graveyard.append(obj)
    return obj


def _cast_sorcery(eng: GameEngine, text: str, targets=None) -> GameObject:
    p1 = eng.state.players[0]
    spell = GameObject(_card("Spell", text, "Sorcery"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 6})
    eng.cast_spell(p1, spell, targets=targets)
    eng.resolve_until_stable()
    return spell


# --- parse -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("clause, params", [
    ("return target creature card with mana value 3 or less from your graveyard to the battlefield tapped",
     {"target_kind": "graveyard_creature", "destination": "battlefield", "max_mana_value": 3, "tapped": True}),
    ("return target creature card with power 2 or less from your graveyard to the battlefield tapped and attacking",
     {"target_kind": "graveyard_creature", "destination": "battlefield",
      "creature_filter": {"max_power": 2}, "tapped": True, "attacking": True}),
    ("return all land cards from your graveyard to the battlefield tapped",
     {"target_kind": "graveyard_land", "destination": "battlefield", "players": "you", "tapped": True}),
    ("return a land card from your graveyard to the battlefield tapped",
     {"target_kind": "graveyard_land", "destination": "battlefield", "pick": True, "tapped": True}),
    ("you may return a creature card from your graveyard to your hand",
     {"target_kind": "graveyard_creature", "destination": "hand", "pick": True, "optional": True}),
    ("put a land card from a graveyard onto the battlefield tapped under your control",
     {"target_kind": "any_graveyard_land", "destination": "battlefield", "pick": True, "tapped": True,
      "under_your_control": True}),
])
def test_graveyard_return_forms_parse(clause, params):
    [spec] = match_clause(clause)
    assert spec.type == "return_from_graveyard" and spec.params == params


def test_self_return_with_counters_parses_and_places_them():
    from mtg_analyzer.game.effects.registry import EffectRegistry

    [spec] = match_clause("return this card from your graveyard to the battlefield tapped with 2 +1/+1 counters on it")
    assert spec.params == {"tapped": True, "extra_counters": {"kind": "+1/+1", "count": 2}}
    eng = _engine()
    card = _in_graveyard(eng, _card("Transmogrant"))
    effect = EffectRegistry.create("return_self_from_graveyard", spec.params)
    effect.source = card
    effect.apply(_ctx(eng))
    assert card in eng.state.battlefield and card.tapped and card.plus_one_counters == 2


def test_self_return_forms_parse():
    [spec] = match_clause("return ~ from your graveyard to the battlefield tapped")
    assert spec.type == "return_self_from_graveyard" and spec.params == {"tapped": True}
    [spec] = match_clause("return this card from your graveyard to the battlefield tapped and attacking")
    assert spec.params == {"tapped": True, "attacking": True}


@pytest.mark.parametrize("clause", [
    "return target creature card from your graveyard to your hand tapped",   # a hand entry isn't tapped
    "return target creature card from your graveyard to the battlefield and attacking",  # never printed alone
    "return all land cards from your graveyard to your hand tapped",
    "return ~ from your graveyard to the battlefield and attacking",
    "return a blorp card from your graveyard to the battlefield",
])
def test_graveyard_return_fails_closed(clause):
    assert match_clause(clause) is None


# --- execute ---------------------------------------------------------------------------------------


def test_targeted_return_enters_tapped_and_respects_the_mana_value_cap():
    eng = _engine()
    cheap = _in_graveyard(eng, _card("Cheap"))
    _cast_sorcery(
        eng, "Return target creature card with mana value 3 or less from your graveyard to the battlefield tapped.",
        targets=[cheap],
    )
    assert cheap in eng.state.battlefield and cheap.tapped


def test_mass_return_takes_only_the_named_type():
    eng = _engine()
    forest = _in_graveyard(eng, _card("Forest", type_line="Basic Land — Forest"))
    island = _in_graveyard(eng, _card("Island", type_line="Basic Land — Island"))
    bear = _in_graveyard(eng, _card("Bear"))
    _cast_sorcery(eng, "Return all land cards from your graveyard to the battlefield tapped.")
    assert forest in eng.state.battlefield and island in eng.state.battlefield
    assert forest.tapped and island.tapped
    assert bear in eng.state.players[0].graveyard  # a creature card is not a land card


def test_pick_asks_and_places_the_choice_tapped():
    eng = _engine()
    forest = _in_graveyard(eng, _card("Forest", type_line="Basic Land — Forest"))
    island = _in_graveyard(eng, _card("Island", type_line="Basic Land — Island"))
    bear = _in_graveyard(eng, _card("Bear"))
    _cast_sorcery(eng, "Return a land card from your graveyard to the battlefield tapped.")
    pending = eng.state.pending_choice
    assert pending is not None and pending["kind"] == "choose_objects"
    assert {o["instance_id"] for o in pending["options"]} == {forest.instance_id, island.instance_id}
    eng.resolve_pending_choice(island.instance_id)
    eng.resolve_until_stable()
    assert island in eng.state.battlefield and island.tapped
    assert forest in eng.state.players[0].graveyard and bear in eng.state.players[0].graveyard


def test_pick_with_one_candidate_is_taken_and_with_none_does_nothing():
    eng = _engine()
    only = _in_graveyard(eng, _card("Forest", type_line="Basic Land — Forest"))
    _cast_sorcery(eng, "Return a land card from your graveyard to the battlefield tapped.")
    assert eng.state.pending_choice is None and only in eng.state.battlefield and only.tapped
    eng2 = _engine()
    _in_graveyard(eng2, _card("Bear"))
    _cast_sorcery(eng2, "Return a land card from your graveyard to the battlefield tapped.")
    assert eng2.state.pending_choice is None


def test_pick_to_hand_and_an_opponents_graveyard_is_not_offered():
    eng = _engine()
    mine = _in_graveyard(eng, _card("Mine"))
    _in_graveyard(eng, _card("Theirs"), owner="p2")
    _cast_sorcery(eng, "Return a creature card from your graveyard to your hand.")
    assert mine in eng.state.players[0].hand and eng.state.pending_choice is None


def _ctx(eng: GameEngine):
    from mtg_analyzer.game.effects.core import GameContext

    return GameContext(eng.state, eng.rules)


def test_self_return_tapped_and_attacking():
    from mtg_analyzer.game.effects.registry import EffectRegistry

    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.state.current_phase = "combat"
    card = _in_graveyard(eng, _card("Interceptor"))
    effect = EffectRegistry.create("return_self_from_graveyard", {"tapped": True, "attacking": True})
    effect.source = card
    effect.apply(_ctx(eng))
    assert card in eng.state.battlefield and card.tapped and card.attacking


def test_attacking_return_joins_combat():
    eng = _engine()
    eng.begin_turn()
    eng.state.current_step = "declare_attackers"
    eng.state.current_phase = "combat"
    bear = _in_graveyard(eng, _card("Bear", power=1))
    spell = GameObject(
        _card("Spell", "Return target creature card with power 2 or less from your graveyard to the "
              "battlefield tapped and attacking.", "Sorcery"), owner_id="p1", zone=Zone.STACK,
    )
    bind_from_catalogue(spell)
    effect = spell.spell_effects[0]
    effect.source = spell
    effect.apply(_ctx(eng), [bear])
    assert bear in eng.state.battlefield and bear.tapped and bear.attacking


# --- real cards ------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, text, type_line", [
    ("Helping Hand", "Return target creature card with mana value 3 or less from your graveyard to the "
     "battlefield tapped.", "Sorcery"),
    ("Aftermath Analyst", "When Aftermath Analyst enters, mill three cards.\n{3}{G}, Sacrifice Aftermath "
     "Analyst: Return all land cards from your graveyard to the battlefield tapped.", "Creature — Elf Druid"),
])
def test_real_cards_are_modeled(name, text, type_line):
    assert parse_oracle(_card(name, text, type_line)).modeled is True
