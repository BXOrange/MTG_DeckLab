"""Tests for ENG-27 — the two real cards behind "an interactive any-one-
color mana ability with a per-object usage gate" turned out to need two
genuinely different primitives, not one:

* **Bloom Tender** — its real cached Oracle text ("Vivid — {T}: For each
  color among permanents you control, add one mana of that color.") isn't
  an interactive choice at all: it's a deterministic *aggregate*
  production (one mana of *every* colour currently present among the
  controller's permanents, together). `ManaAbility.color_selector`'s new
  ``"colors_among_permanents_you_control"`` kind (`game/mana_abilities.py`).
* **Carpet of Flowers** — a genuinely targeted, once-per-turn, "you may add
  X mana of any one color" triggered ability (RULE 605.5a disqualifies it
  from ever being a mana ability at all, so it's an ordinary stack-using
  triggered ability instead). `AddManaEffect.
  amount_from_target_count_selector`/`once_per_turn_ability`
  (`game/effects/core.py`) plus `RulesEngine.add_mana_any_color`'s new
  ``amount`` param (`game/rules/mana_counters_mixin.py`) and
  `GameObject.added_mana_with_ability_this_turn` (reset each untap step).

Reference: mtg_analyzer/game/{effects,mana_abilities,card_registry}.py,
mtg_analyzer/game/rules/mana_counters_mixin.py,
mtg_analyzer/game/engine/turn_loop_mixin.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import mana_abilities
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.mana.mana_cost import ManaCost
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


def battlefield(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def multicolor_creature(name, colors, cost="{W}{U}"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=True, power=1, toughness=1, color_identity=set(colors),
    )


def island(controller_name="Island"):
    return Card(id=controller_name, name="Island", type_line="Basic Land — Island", is_land=True)


def advance_to_main(eng):
    while eng.state.current_phase != "precombat_main":
        eng.advance_step()
    eng.recompute_continuous_effects()


# ---------------------------------------------------------------------------
# Bloom Tender — deterministic aggregate production, no choice at all
# ---------------------------------------------------------------------------


def test_bloom_tender_produces_one_mana_of_its_own_color_alone():
    eng, p1, p2 = two_player_engine()
    bt = battlefield(eng, _card("Bloom Tender"), "p1")  # itself mono-green
    abilities = mana_abilities.mana_abilities_for(bt, state=eng.state)
    assert len(abilities) == 1
    assert abilities[0].color_selector == "colors_among_permanents_you_control"
    options = mana_abilities.resolve_options(abilities[0], bt, eng.state)
    assert options == [{"G": 1}]


def test_bloom_tender_aggregates_every_color_on_the_board_at_once():
    eng, p1, p2 = two_player_engine()
    bt = battlefield(eng, _card("Bloom Tender"), "p1")
    battlefield(eng, multicolor_creature("Azorius Bird", {"W", "U"}), "p1")
    # An opponent's colours don't count — "permanents **you** control".
    battlefield(eng, multicolor_creature("Rival Bird", {"B"}), "p2")
    abilities = mana_abilities.mana_abilities_for(bt, state=eng.state)
    options = mana_abilities.resolve_options(abilities[0], bt, eng.state)
    assert options == [{"G": 1, "W": 1, "U": 1}]


def test_bloom_tender_tap_for_mana_produces_the_aggregate_no_choice_needed():
    eng, p1, p2 = two_player_engine()
    bt = battlefield(eng, _card("Bloom Tender"), "p1")
    battlefield(eng, multicolor_creature("Azorius Bird", {"W", "U"}), "p1")
    produced = eng.tap_for_mana(p1, bt)
    assert produced == {"G": 1, "W": 1, "U": 1}
    assert eng.state.pending_choice is None  # no menu — it's not a choice


def test_bloom_tender_with_no_state_produces_nothing_rather_than_guessing():
    bt_card = _card("Bloom Tender")
    obj = GameObject(bt_card, owner_id="p1", zone=Zone.BATTLEFIELD)
    ability = mana_abilities.parse_mana_abilities(bt_card)[0]
    assert mana_abilities.resolve_options(ability, obj, state=None) == []


# ---------------------------------------------------------------------------
# Carpet of Flowers — targeted, gated, interactive "any one color" trigger
# ---------------------------------------------------------------------------


def test_carpet_of_flowers_offers_a_target_and_declining_produces_nothing():
    eng, p1, p2 = two_player_engine()
    carpet = battlefield(eng, _card("Carpet of Flowers"), "p1")
    battlefield(eng, island(), "p2")
    advance_to_main(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    assert any(o["id"] == "decline" for o in choice["options"])
    eng.resolve_pending_choice("decline")
    assert eng.state.pending_choice is None
    assert eng.state.stack == []
    assert p1.mana_pool.pool.get("U", 0) == 0
    assert carpet.added_mana_with_ability_this_turn is False


def test_carpet_of_flowers_produces_x_mana_of_the_chosen_color_where_x_is_the_targets_islands():
    eng, p1, p2 = two_player_engine()
    carpet = battlefield(eng, _card("Carpet of Flowers"), "p1")
    for i in range(3):
        battlefield(eng, island(f"Island{i}"), "p2")
    advance_to_main(eng)
    choice = eng.state.pending_choice
    assert {o["id"] for o in choice["options"]} == {"p2", "decline"}
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    color_choice = eng.state.pending_choice
    assert color_choice is not None and color_choice["kind"] == "add_mana_any_color"
    assert color_choice["amount"] == 3
    eng.resolve_pending_choice("U")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert eng.state.stack == []
    assert p1.mana_pool.pool.get("U", 0) == 3
    assert carpet.added_mana_with_ability_this_turn is True


def test_carpet_of_flowers_once_per_turn_gate_blocks_a_second_use():
    eng, p1, p2 = two_player_engine()
    carpet = battlefield(eng, _card("Carpet of Flowers"), "p1")
    battlefield(eng, island(), "p2")
    carpet.added_mana_with_ability_this_turn = True  # already used this turn
    eng.state.active_player_index = 0
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="main2", phase="postcombat_main"))
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # still offered ("you may")…
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None  # …but produces nothing once accepted
    assert p1.mana_pool.pool.get("U", 0) == 0


def test_carpet_of_flowers_gate_resets_after_untap():
    eng, p1, p2 = two_player_engine()
    carpet = battlefield(eng, _card("Carpet of Flowers"), "p1")
    carpet.added_mana_with_ability_this_turn = True
    eng.state.active_player_index = 0
    eng._step_untap()
    assert carpet.added_mana_with_ability_this_turn is False


def test_carpet_of_flowers_never_touches_its_own_controllers_islands():
    # "the number of Islands **target opponent** controls" — the ability's
    # own controller's own Islands don't count, only the chosen target's.
    eng, p1, p2 = two_player_engine()
    carpet = battlefield(eng, _card("Carpet of Flowers"), "p1")
    for i in range(5):
        battlefield(eng, island(f"MyIsland{i}"), "p1")
    battlefield(eng, island("TheirIsland"), "p2")
    advance_to_main(eng)
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    color_choice = eng.state.pending_choice
    assert color_choice["amount"] == 1  # p2's one Island, not p1's five


def test_carpet_of_flowers_is_registered_as_two_optional_targeted_triggers():
    from mtg_analyzer.game import card_registry

    assert card_registry.is_registered("Carpet of Flowers")
    specs = card_registry.specs_for(_card("Carpet of Flowers"))
    assert len(specs) == 2
    steps = {spec.trigger["filter"]["step"] for spec in specs}
    assert steps == {"main1", "main2"}
    for spec in specs:
        assert spec.optional is True
        assert spec.trigger["phase_relation"] == "you"
        effect = spec.effects[0]
        assert effect.type == "add_mana"
        assert effect.params.get("target_kind") == "opponent"
        assert effect.params.get("once_per_turn_ability") is True
        assert effect.params.get("amount_from_target_count_selector") == (
            "lands_you_control_of_type_island"
        )
