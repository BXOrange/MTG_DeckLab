"""PAR-285: "another target X" after an earlier target of the same ability (RULE 115.3 / 109.5).

Three shapes that used to stay unclaimed: "you may tap or untap another target permanent" (the tap-or-untap row did
not take "another"), "destroy target A and up to 1 other target B" (one verb over two requirements) and "target player
draws a card. Another target player creates ..." (the later sentence names a second, different player). Each now
parses to the plain effects, the later one stamped `distinct_from_others` (ENG-52); `build_effects` copies the flag
onto its `TargetSpec`, `targeting.requirements_with_targets` offers it to the caster (the client and bots drop what
the earlier requirement picked) and the spell or ability resolves end to end. Tests run parser -> binder -> engine on
the real cards' text."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.services.game_session import GameSession

RELIC_CRUSH = "Destroy target artifact or enchantment and up to 1 other target artifact or enchantment."
HIDDEN_STRINGS = "You may tap or untap target permanent, then you may tap or untap another target permanent."
DATASMITH = (
    'Protection from Robots\n{U}, {T}: Target player draws a card. Another target player creates a 4/4 colorless '
    'Robot artifact creature token with "This token can\'t block."'
)


def _card(name: str, type_line: str, oracle: str = "", power: int = 2, toughness: int = 2) -> Card:
    creature = "creature" in type_line.lower()
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, mana_cost_string="{1}",
                converted_mana_cost=1, is_creature=creature, power=power if creature else None,
                toughness=toughness if creature else None, is_instant=type_line == "Instant")


def _session():
    engine = GameEngine.new_game([("p1", "A", []), ("p2", "B", [])], starting_life=20, starting_hand=5)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return GameSession(engine, starting_hand=0), engine, engine.state


def _put(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _hand(state, card, owner="p1"):
    obj = GameObject(card, owner_id=owner, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(owner).hand.append(obj)
    return obj


def _flags(state, obj):
    return [entry["distinct_from_others"] for entry in targeting.requirements_with_targets(state, "p1", obj)]


def _modeled(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    assert parse_oracle(card).modeled is True, name


@pytest.mark.parametrize("name", ["Relic Crush", "Toils of Night and Day", "Cybernetica Datasmith"])
def test_real_cards_are_modeled(name):
    _modeled(name)


def test_relic_crush_second_requirement_is_distinct_and_optional():
    _, engine, state = _session()
    spell = _hand(state, _card("Relic Crush", "Instant", RELIC_CRUSH))
    rock = _put(state, _card("Rock", "Artifact"))
    aura = _put(state, _card("Pacifism", "Enchantment"), "p2")
    first, second = targeting.requirements_with_targets(state, "p1", spell)
    assert first["distinct_from_others"] is False and second["distinct_from_others"] is True
    assert second["optional"] is True
    assert {o["instance_id"] for o in second["options"]} == {rock.instance_id, aura.instance_id}


def test_relic_crush_destroys_both_picks_and_works_with_one():
    _, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _card("Relic Crush", "Instant", RELIC_CRUSH))
    rock = _put(state, _card("Rock", "Artifact"))
    aura = _put(state, _card("Pacifism", "Enchantment"), "p2")
    p1.mana_pool.add("C", 1)
    engine.cast_spell(p1, spell, targets=[rock, aura])
    engine.rules.resolve_top_of_stack()
    assert rock.zone == Zone.GRAVEYARD and aura.zone == Zone.GRAVEYARD


def test_hidden_strings_second_tap_choice_is_distinct_and_never_the_source():
    _, engine, state = _session()
    spell = _hand(state, _card("Hidden Strings", "Instant", HIDDEN_STRINGS))
    a = _put(state, _card("Bear A", "Creature — Bear"))
    b = _put(state, _card("Bear B", "Creature — Bear"), "p2")
    first, second = targeting.requirements_with_targets(state, "p1", spell)
    assert first["distinct_from_others"] is False and second["distinct_from_others"] is True
    assert {o["instance_id"] for o in second["options"]} == {a.instance_id, b.instance_id}
    specs = [spec for effect in build_effects(parse_oracle(spell.card).specs[0].effects, spell)
             for spec in effect.target_specs]
    assert [spec.exclude_source for spec in specs] == [False, True]


def test_hidden_strings_resolves_and_asks_each_tap_or_untap():
    session, engine, state = _session()
    p1 = state.player_by_id("p1")
    spell = _hand(state, _card("Hidden Strings", "Instant", HIDDEN_STRINGS))
    a = _put(state, _card("Bear A", "Creature — Bear"))
    b = _put(state, _card("Bear B", "Creature — Bear"), "p2")
    b.tapped = True
    p1.mana_pool.add("C", 1)
    engine.cast_spell(p1, spell, targets=[a, b])
    engine.rules.resolve_top_of_stack()
    assert state.pending_choice["kind"] == "tap_or_untap"
    session.apply_action({"type": "choose", "option_id": "tap"}, "p1")
    engine.resolve_until_stable()
    assert a.tapped is True
    assert state.pending_choice is not None and state.pending_choice["kind"] == "tap_or_untap"
    session.apply_action({"type": "choose", "option_id": "untap"}, "p1")
    engine.resolve_until_stable()
    assert b.tapped is False


def test_datasmith_gives_each_player_a_different_effect():
    session, engine, state = _session()
    smith = _put(state, _card("Cybernetica Datasmith", "Creature — Artificer", DATASMITH))
    p1 = state.player_by_id("p1")
    for n in range(2):
        filler = GameObject(_card(f"Filler {n}", "Instant"), owner_id="p1", zone=Zone.LIBRARY)
        p1.library.append(filler)
    specs = [spec for effect in build_effects(parse_oracle(smith.card).specs[-1].effects, smith)
             for spec in effect.target_specs]
    assert [spec.distinct_from_others for spec in specs] == [False, True]
    before_hand = len(p1.hand)
    p1.mana_pool.add("U", 1)
    session.apply_action({"type": "activate_ability", "instance_id": smith.instance_id, "ability_index": 0,
                          "targets": [{"player_id": "p1"}, {"player_id": "p2"}]}, "p1")
    engine.resolve_until_stable()
    assert len(p1.hand) == before_hand + 1
    robots = [o for o in state.battlefield if o.name == "Robot"]
    assert [o.controller_id for o in robots] == ["p2"]
