"""PAR-41 — "As an additional cost to cast this spell, exile N [<type>]
cards from your graveyard." (RULE 601.2b — Cobbled Lancer / Headless Skaab
/ Makeshift Mauler / Abhorrent Oculus).

`ActivationCost` gained `exile_from_graveyard_filter` alongside the
pre-existing `exile_from_graveyard` count (which was Escape-only until
now). `segmenter._ADDITIONAL_COST_EXILE_GRAVEYARD_RE` +
`_additional_cost_dict` recognise the clause; `GameEngine.
_can_pay_additional_cast_cost` gates the cast on the graveyard holding
enough matching cards and `_pay_additional_cast_cost` exiles them (auto-
picked, like Escape's own cost). The "exile **x** cards" variant stays
UNMODELED (no X-scaled additional cost field yet).
"""

from __future__ import annotations

from mtg_analyzer.game.costs import parse_activation_cost
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import _additional_cost_dict

from tests.support.game import creature, make_engine


# --- parse ---------------------------------------------------------------


def test_additional_cost_dict_recognises_typed_and_untyped_forms():
    assert _additional_cost_dict("exile a creature card from your graveyard") == {
        "exile_from_graveyard": {"count": 1, "type": "creature"},
    }
    assert _additional_cost_dict("exile 6 cards from your graveyard") == {
        "exile_from_graveyard": {"count": 6},
    }


def test_additional_cost_dict_rejects_the_x_form():
    # "exile x creature cards …" has no X-scaled additional-cost field yet.
    assert _additional_cost_dict("exile x creature cards from your graveyard") is None


def test_parse_activation_cost_threads_the_filter():
    c = parse_activation_cost({
        "exile_from_graveyard": {"count": 1, "type": "creature"},
    })
    assert c.exile_from_graveyard == 1
    assert c.exile_from_graveyard_filter == "creature"


def test_real_card_modeled():
    lancer = Card(
        id="cl", name="Cobbled Lancer", type_line="Creature — Zombie Knight",
        mana_cost_string="{1}{U}", converted_mana_cost=2, is_creature=True,
        power=3, toughness=1,
        oracle_text=(
            "As an additional cost to cast this spell, exile a creature card "
            "from your graveyard.\nCobbled Lancer can't be blocked."),
    )
    r = parse_oracle(lancer)
    assert r.modeled is True
    assert any(
        s.additional_cost == {"exile_from_graveyard": {"count": 1, "type": "creature"}}
        for s in r.specs
    )


# --- execute -----------------------------------------------------------


def _lancer_card():
    return Card(
        id="cl", name="Cobbled Lancer", type_line="Creature — Zombie Knight",
        mana_cost_string="{1}{U}", converted_mana_cost=2, is_creature=True,
        power=3, toughness=1,
        oracle_text=("As an additional cost to cast this spell, exile a creature "
                     "card from your graveyard.\nCobbled Lancer can't be blocked."),
    )


def _setup(gy_cards):
    eng = make_engine([_lancer_card()], [creature("Bear")], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 3})
    for c in gy_cards:
        p1.graveyard.append(GameObject(c, owner_id="p1", zone=Zone.GRAVEYARD))
    from mtg_analyzer.game.binding.core import bind_from_catalogue
    lancer = p1.hand[0]
    bind_from_catalogue(lancer)
    return eng, p1, lancer


def test_cannot_cast_with_no_creature_card_in_graveyard():
    eng, p1, lancer = _setup([Card(id="isl", name="Island", type_line="Basic Land — Island",
                                   is_land=True)])
    assert eng.can_cast(p1, lancer) is False


def test_casts_and_exiles_a_creature_card_from_graveyard():
    dead_bear = Card(id="db", name="Dead Bear", type_line="Creature — Bear",
                     is_creature=True, power=2, toughness=2)
    eng, p1, lancer = _setup([dead_bear])
    assert eng.can_cast(p1, lancer) is True

    eng.cast_spell(p1, lancer)

    assert all(o.card.id != "db" for o in p1.graveyard)      # left the graveyard
    assert any(o.card.id == "db" for o in p1.exile)          # …to exile, as the cost
