"""RULE 118.9 alternative costs on a creature spell (the Bringer cycle:
"You may pay {W}{U}{B}{R}{G} rather than pay this spell's mana cost.") —
the engine side (`GameEngine.can_cast`/`cast_spell`'s ``alt_cost=True``
branch, MEC-15) was already built and tested against instants/sorceries;
only the oracle-text recognition was scoped to `gate.py`'s `_is_spell`
(instant/sorcery only), so a creature printing this exact RULE 118.9
sentence stayed UNMODELED and never reached `_offer_cast`'s alt-cost
action at all.

Widening `_is_spell` itself to include creatures was tried and reverted —
`allow_spell_effect` also gates unrelated bare-imperative rows (Strive,
free-cast conditions, …) that broke real creature static/replacement-clause
parsing once creature cards started reaching them. The RULE 118.9 alt_cost
family (`segmenter.py`'s ``pitch``/``sac_filter``/``sac_type``/``ret_two``/
``pay_if``/``pay_mana`` checks) was pulled out of that gate instead and made
unconditional — a spell's mana cost doesn't care what it becomes once it
resolves, so these checks are safe on any card type.
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def bringer_card():
    return Card(
        id="Bringer of the White Dawn", name="Bringer of the White Dawn",
        type_line="Creature — Bringer", is_creature=True,
        power=7, toughness=7, mana_cost_string="{7}{W}{W}", converted_mana_cost=9,
        oracle_text="You may pay {W}{U}{B}{R}{G} rather than pay this "
                    "spell's mana cost.\nTrample",
        keywords=["Trample"],
    )


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def test_bringer_alt_cost_line_is_modeled():
    result = parse_oracle(bringer_card())
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_bringer_alt_cost_is_offered_and_castable_from_hand():
    eng = make_engine("p1", "p2")
    card = bringer_card()
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.active_player.hand.append(obj)

    for color in "WUBRG":
        eng.rules.add_mana(eng.state.active_player, color, 1)
    eng.state.current_step = "main1"  # Bringer is a creature — sorcery-speed timing

    assert eng.can_cast(eng.state.active_player, obj, alt_cost=True)
    eng.cast_spell(eng.state.active_player, obj, alt_cost=True)

    assert any(item.obj is obj for item in eng.state.stack)
    assert eng.state.active_player.mana_pool.total() == 0
