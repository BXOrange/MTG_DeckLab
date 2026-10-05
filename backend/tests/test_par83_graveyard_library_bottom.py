"""PAR-83 — put a targeted graveyard card on its owner's library bottom.

The move is intentionally not a shuffle: ``ReturnToLibraryEffect`` already
implements the from-any-zone, owner's-library, chosen-position primitive.
This ticket makes its ``any_graveyard_card`` target form parser-reachable.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from mtg_analyzer.parser.oracle.spec import EffectSpec


_CLAUSE = "put target card from a graveyard on the bottom of its owner's library."


def _engine() -> GameEngine:
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )


def test_graveyard_card_to_library_bottom_parses():
    assert parse_effect_body(_CLAUSE) == [EffectSpec("return_to_library", {
        "target_kind": "any_graveyard_card", "position": "bottom",
    })]


def test_does_not_overmatch_other_library_destinations():
    assert parse_effect_body(
        "put target card from a graveyard on top of its owner's library."
    ) is None


def test_junktroller_is_modeled():
    card = Card(
        id="Junktroller", name="Junktroller", type_line="Artifact Creature — Golem",
        mana_cost_string="{4}", converted_mana_cost=4, is_creature=True, power=0, toughness=6,
        oracle_text="{T}: Put target card from a graveyard on the bottom of its owner's library.",
    )
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed


def test_junktroller_moves_an_opponents_graveyard_card_to_its_owners_library_bottom():
    eng = _engine()
    state = eng.state
    p1, p2 = state.players

    junktroller = GameObject(
        Card(
            id="Junktroller", name="Junktroller", type_line="Artifact Creature — Golem",
            is_creature=True, power=0, toughness=6,
            oracle_text="{T}: Put target card from a graveyard on the bottom of its owner's library.",
        ),
        owner_id=p1.id, zone=Zone.BATTLEFIELD,
    )
    junktroller.summoning_sick = False
    bind_from_catalogue(junktroller)
    state.add_to_battlefield(junktroller)

    existing_bottom = GameObject(
        Card(id="Existing Bottom", name="Existing Bottom", type_line="Land", is_land=True),
        owner_id=p2.id, zone=Zone.LIBRARY,
    )
    dead_card = GameObject(
        Card(id="Dead Card", name="Dead Card", type_line="Instant", is_instant=True),
        owner_id=p2.id, zone=Zone.GRAVEYARD,
    )
    p2.library.append(existing_bottom)
    p2.graveyard.append(dead_card)

    eng.activate_ability(p1, junktroller, ability_index=0, targets=[dead_card])
    eng.resolve_until_stable()

    assert dead_card not in p2.graveyard
    assert p2.library == [dead_card, existing_bottom]
    assert dead_card.zone is Zone.LIBRARY
