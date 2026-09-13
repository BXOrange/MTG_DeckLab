"""PAR-49 — activated Mistform creature-type overwrite."""

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle


def _mistform() -> Card:
    return Card(
        id="Mistform Dreamer", name="Mistform Dreamer",
        type_line="Creature — Illusion", is_creature=True, power=1, toughness=1,
        mana_cost_string="{0}",
        oracle_text="{1}: Mistform Dreamer becomes the creature type of your choice until end of turn.",
    )


def test_mistform_activation_is_fully_parsed():
    result = parse_oracle(_mistform())
    assert result.coverage == MODELED
    [ability] = result.effect_specs
    assert ability.effects[0].type == "_request_choose_creature_type_grant"


def test_mistform_choice_overwrites_subtype_until_cleanup():
    card = _mistform()
    engine = GameEngine.new_game([("p1", "Alice", [card]), ("p2", "Bob", [])], starting_hand=1)
    engine.begin_turn()
    engine.state.current_step = "main1"
    player = engine.state.active_player
    player.library.append(GameObject(
        Card(id="Goblin", name="Goblin", type_line="Creature — Goblin", is_creature=True),
        owner_id="p1", zone=Zone.LIBRARY,
    ))
    obj = player.hand[0]
    bind_from_catalogue(obj)
    player.hand.remove(obj)
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    player.mana_pool.add_many({"C": 1})

    engine.activate_ability(player, obj, 0)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "choose_type_for_source"
    engine.resolve_pending_choice("Goblin")
    assert continuous.has_subtype(obj, "Goblin")
    assert not continuous.has_subtype(obj, "Illusion")

    engine._step_cleanup()
    assert continuous.has_subtype(obj, "Illusion")
    assert not continuous.has_subtype(obj, "Goblin")
