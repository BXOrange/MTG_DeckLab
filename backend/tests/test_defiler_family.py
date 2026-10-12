"""The Defiler cycle: "As an additional cost to cast <colour> permanent spells, you may pay 2 life…" (parser-claimed)."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.spell_phrase import parse_spell_phrase
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.catalogue import battlefield_object

_CLAUSE = (
    "as an additional cost to cast {c} permanent spells, you may pay 2 life. those spells cost {{{l}}} less to "
    "cast if you paid life this way. this effect reduces only the amount of {c} mana you pay."
)
_DEFILERS = [("Defiler of Faith", "white", "W"), ("Defiler of Flesh", "black", "B"), ("Defiler of Instinct", "red", "R")]


@pytest.mark.parametrize("name,colour,letter", _DEFILERS)
def test_each_defiler_parses_fully_to_a_pip_life_option(name, colour, letter):
    card = CardDatabase(DB_PATH).get_card(name)
    result = parse_oracle(card)
    assert result.coverage == "MODELED" and not result.unclaimed
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "pip_life_option"
    assert static.effects[0].params["spell_color"] == letter and static.effects[0].params["color"] == letter
    trigger = next(s for s in result.specs if s.ability_kind == "triggered")
    # "permanent spell" is a spell of a permanent type, not just a coloured one — no instants or sorceries.
    assert set(trigger.trigger["spell_filter"]["card_type_any"]) >= {"creature", "land", "battle"}
    assert "instant" not in trigger.trigger["spell_filter"]["card_type_any"]


def test_the_clause_rejects_a_mismatched_colour_pip_or_life_amount():
    assert static_effect_specs(_CLAUSE.format(c="white", l="w")) is not None
    assert static_effect_specs(_CLAUSE.format(c="white", l="u")) is None
    assert static_effect_specs(_CLAUSE.format(c="white", l="w").replace("2 life", "3 life")) is None
    mixed = _CLAUSE.format(c="white", l="w").replace("amount of white mana", "amount of blue mana")
    assert static_effect_specs(mixed) is None


def test_a_bare_permanent_spell_phrase_excludes_instants_and_sorceries():
    keys = parse_spell_phrase("a permanent spell")
    assert keys is not None and "instant" not in keys["spell_filter"]["card_type_any"]
    assert parse_spell_phrase("a creature permanent spell") is None  # contradictory: not claimed


@pytest.mark.parametrize("name,colour,letter", _DEFILERS)
def test_a_defiler_lets_you_pay_two_life_for_the_coloured_pip_of_permanent_spells_only(name, colour, letter):
    cards = [CardDatabase(DB_PATH).get_card(name)]
    engine = GameEngine.new_game([("p1", "A", cards), ("p2", "B", [])], starting_hand=1, starting_life=20)
    p1 = engine.state.player_by_id("p1")
    engine.begin_turn()
    engine.state.current_step = "main1"
    defiler = p1.hand[0]
    bind_from_catalogue(defiler)
    p1.hand.remove(defiler)
    defiler.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(defiler)
    defiler.summoning_sick = False
    engine.recompute_continuous_effects()

    def hand_card(card_name, type_line, **kw):
        obj = GameObject(
            Card(id=card_name, name=card_name, type_line=type_line, mana_cost_string="{1}{%s}" % letter,
                 converted_mana_cost=2, color_identity={letter}, **kw),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.hand.append(obj)
        return obj

    trick = hand_card("Coloured Trick", "Instant", is_instant=True)
    cub = hand_card("Coloured Cub", "Creature — Bear", is_creature=True, power=1, toughness=1)
    p1.mana_pool.add_many({"C": 1})  # the generic part only — none of the coloured mana
    assert not engine.can_cast(p1, trick)  # instants get no life option
    life = p1.life
    engine.cast_spell(p1, cub)
    engine.resolve_pending_choice("1")  # pay the 2 life
    for _ in range(4):  # the Defiler's own cast trigger may ask for its target (Flesh, Instinct)
        engine.rules.put_triggers_on_stack()
        choice = engine.state.pending_choice
        if choice:
            # aim any "target" at the opponent (Instinct's ping would otherwise hit its own controller first)
            pick = next((o for o in choice["options"] if "p2" in str(o)), choice["options"][0])
            engine.resolve_pending_choice(pick["id"])
        engine.resolve_until_stable()
    assert cub.zone == Zone.BATTLEFIELD and p1.life == life - 2
