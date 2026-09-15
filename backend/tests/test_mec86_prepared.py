"""MEC-86 — Prepared (RULE 722.3a). The engine primitive
(`GameObject.prepared`, `RulesEngine.make_prepared`, `BecomePreparedEffect`)
and the parser handler for a card's own "~ becomes prepared" trigger body
already existed; the whole gap was one missing dispatch — "~ enters
prepared." (no "when …", RULE 722.3a's *other*, bare phrasing) fell
through unclaimed. `gate.py`'s per-line loop now synthesizes the
equivalent "when ~ enters, it becomes prepared" trigger for that shape.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _prepare_card():
    return Card(
        id="Adventurous Eater", name="Adventurous Eater",
        type_line="Creature — Human Warlock", is_creature=True,
        power=3, toughness=2, mana_cost_string="{2}{B}", converted_mana_cost=3,
        layout="prepare",
        oracle_text=(
            "This creature enters prepared. (While it's prepared, you may "
            "cast a copy of its spell. Doing so unprepares it.)"
        ),
        back_name="Have a Bite", back_type_line="Sorcery",
        back_mana_cost_string="{1}{B}",
        back_oracle_text="You gain 1 life.",
    )


def test_enters_prepared_parses_as_an_etb_trigger():
    card = _prepare_card()
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    spec = result.specs[0]
    assert spec.ability_kind == "triggered"
    assert spec.trigger["event"] == "ENTERS_BATTLEFIELD"
    assert spec.trigger["condition"] == {"subject": "self"}
    assert spec.effects[0].type == "become_prepared"


def test_casting_it_sets_prepared_and_exiles_a_copy_of_the_prepare_spell():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )
    state = eng.state
    card = _prepare_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id("p1").hand.append(obj)

    eng.start()
    while state.current_phase != "precombat_main":
        eng.advance_step()
    eng.recompute_continuous_effects()
    player = state.player_by_id("p1")
    for colour in "WUBRGC":
        player.mana_pool.add(colour, 30)

    eng.cast_spell(player, obj, targets=None)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    battlefield = [o for o in state.battlefield if o.controller_id == "p1"]
    assert len(battlefield) == 1
    source = battlefield[0]
    assert source.prepared is True

    copies = [o for o in player.exile if o.prepared_source_id == source.instance_id]
    assert len(copies) == 1
    assert copies[0].card.name == "Have a Bite"

    # Casting the exiled copy unprepares the source (RULE 722.3c).
    eng.cast_spell(player, copies[0], targets=None)
    eng.resolve_until_stable()
    source = state.find_object(source.instance_id)
    assert source.prepared is False
