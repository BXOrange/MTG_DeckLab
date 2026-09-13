"""PAR-45 — RULE 601.2b opponent choice as a permanent enters."""

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def test_choose_opponent_on_enter_parses_as_an_entry_replacement():
    card = Card(
        id="chooser", name="Chooser", type_line="Artifact Creature — Construct",
        is_creature=True, power=1, toughness=1,
        mana_cost_string="{0}",
        oracle_text="As Chooser enters, choose an opponent.",
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    [spec] = result.effect_specs
    assert spec.ability_kind == "enter_replacement"
    assert spec.effects[0].type == "choose_opponent_on_enter"


def test_choose_opponent_happens_before_battlefield_entry():
    card = Card(
        id="chooser", name="Chooser", type_line="Artifact Creature — Construct",
        is_creature=True, power=1, toughness=1,
        mana_cost_string="{0}",
        oracle_text="As Chooser enters, choose an opponent.",
    )
    engine = GameEngine.new_game([("p1", "Alice", [card]), ("p2", "Bob", [])], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    caster = engine.state.active_player
    obj = caster.hand[0]
    bind_from_catalogue(obj)
    engine.cast_spell(caster, obj)
    engine.resolve_until_stable()
    pending = engine.state.pending_choice
    assert pending and pending["kind"] == "choose_opponent_on_enter"
    assert obj not in engine.state.battlefield
    assert [option["id"] for option in pending["options"]] == ["p2"]
    engine.resolve_pending_choice("p2")
    assert obj in engine.state.battlefield
    assert obj.chosen_player_id == "p2"
