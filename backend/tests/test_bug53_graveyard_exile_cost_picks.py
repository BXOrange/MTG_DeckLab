"""BUG-53 -- "Exile N cards from your graveyard" activation costs are the player's pick (RULE 602.2b / 601.2h).

The engine used to exile the first N eligible cards. The legal action now offers the pool as
``graveyard_exile_cost``; the board answers with ``graveyard_exile_choices`` (wire) / ``hand_card_choices``
(engine), the engine validates the picks, and a call without picks keeps the non-interactive fallback.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.services.game_session import GameSession
from tests.test_eng49_cost_leftovers import battlefield, engine, in_zone, resolve

LAVAMANCER = "Grim Lavamancer"
GRAVEYARD_COST_COUNT = 2  # Grim Lavamancer exiles two cards


def _setup(extra_cards=1):
    eng, p1 = engine()
    lavamancer = battlefield(eng, LAVAMANCER)
    p1.mana_pool.add("R", 1)
    names = ["Grizzly Bears", "Lightning Bolt", "Giant Growth", "Shock"][:GRAVEYARD_COST_COUNT + extra_cards]
    cards = [in_zone(eng, n, Zone.GRAVEYARD) for n in names]
    return eng, p1, lavamancer, cards


def _activate(eng, p1, lavamancer, picks=None):
    opponent = eng.state.player_by_id("p2")
    eng.activate_ability(p1, lavamancer, 0, targets=[opponent], hand_card_choices=picks)


def test_picked_cards_are_exiled_not_the_first_two():
    eng, p1, lava, cards = _setup()
    picks = [cards[1].instance_id, cards[2].instance_id]
    _activate(eng, p1, lava, picks)
    assert cards[0].zone == Zone.GRAVEYARD
    assert cards[1].zone == Zone.EXILE and cards[2].zone == Zone.EXILE


@pytest.mark.parametrize("bad", ["duplicate", "too_few", "too_many", "foreign", "source"])
def test_invalid_picks_are_rejected_and_nothing_is_paid(bad):
    eng, p1, lava, cards = _setup()
    ids = [c.instance_id for c in cards]
    picks = {
        "duplicate": [ids[1], ids[1]], "too_few": [ids[1]], "too_many": ids,
        "foreign": [ids[0], lava.instance_id], "source": [ids[0], lava.instance_id],
    }[bad]
    before = list(p1.graveyard)
    with pytest.raises(ValueError, match="cannot activate"):
        _activate(eng, p1, lava, picks)
    assert p1.graveyard == before and not eng.state.stack
    assert p1.mana_pool.total() == 1


def test_no_picks_falls_back_to_the_first_cards():
    eng, p1, lava, cards = _setup()
    _activate(eng, p1, lava)
    assert [c.zone for c in cards] == [Zone.EXILE, Zone.EXILE, Zone.GRAVEYARD]


def test_unpayable_cost_is_not_offered():
    eng, p1, lava, cards = _setup(extra_cards=-1)
    assert not any(a.get("type") == "activate_ability" and a.get("instance_id") == lava.instance_id
                   for a in eng.legal_actions(p1))


def test_offer_lists_the_pool_and_session_wire_applies_picks():
    eng, p1, lava, cards = _setup()
    action = next(a for a in eng.legal_actions(p1)
                  if a.get("type") == "activate_ability" and a.get("instance_id") == lava.instance_id)
    cost = action["graveyard_exile_cost"]
    assert cost["count"] == GRAVEYARD_COST_COUNT
    assert {o["instance_id"] for o in cost["options"]} == {c.instance_id for c in cards}
    session = GameSession(eng, mode="replay", require_setup=False)
    session.apply_action({
        "type": "activate_ability", "instance_id": lava.instance_id, "ability_index": 0,
        "targets": [{"player_id": "p2"}],
        "graveyard_exile_choices": [cards[2].instance_id, cards[1].instance_id],
    })
    assert cards[0].zone == Zone.GRAVEYARD
    assert cards[1].zone == Zone.EXILE and cards[2].zone == Zone.EXILE


def test_smart_bot_exiles_its_least_valuable_graveyard_cards():
    from mtg_analyzer.services.smart_bot2.choices import fill_costs

    class Ctx:
        @staticmethod
        def effect_text(action):
            return ""

        @staticmethod
        def value(option):
            return option["mana_value"]

    options = [{"instance_id": 1, "mana_value": 5}, {"instance_id": 2, "mana_value": 0},
               {"instance_id": 3, "mana_value": 1}]
    built = fill_costs(Ctx, {"graveyard_exile_cost": {"count": 2, "options": options}})
    assert sorted(built["graveyard_exile_choices"]) == [2, 3]
    assert fill_costs(Ctx, {"graveyard_exile_cost": {"count": 4, "options": options}}) is None


# --- Night Soil: "Exile two creature cards from a single graveyard" (RULE 602.2b) -------------------------------

NIGHT_SOIL_COUNT = 2


def _night_soil():
    eng, p1 = engine()
    soil = battlefield(eng, "Night Soil")
    p1.mana_pool.add("C", 1)
    return eng, p1, soil


def _opp_creature(eng, name="Serra Angel"):
    opp = eng.state.player_by_id("p2")
    card = in_zone(eng, name, Zone.GRAVEYARD, controller="p2")
    return opp, card


def test_night_soil_is_modeled_and_costs_two_cards_from_one_graveyard():
    from mtg_analyzer.game.costs import parse_activation_cost

    cost = parse_activation_cost("{1}, Exile two creature cards from a single graveyard")
    assert (cost.exile_from_graveyard, cost.exile_from_graveyard_filter, cost.exile_from_graveyard_single) == (
        NIGHT_SOIL_COUNT, "creature", True)
    assert cost.unrecognized is None


def test_night_soil_picks_two_cards_from_the_opponents_graveyard():
    eng, p1, soil = _night_soil()
    mine = in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD)
    opp, theirs1 = _opp_creature(eng)
    theirs2 = in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD, controller="p2")
    action = next(a for a in eng.legal_actions(p1) if a.get("instance_id") == soil.instance_id
                  and a.get("type") == "activate_ability")
    # Only the opponent's graveyard holds two creature cards on its own.
    assert {o["instance_id"] for o in action["graveyard_exile_cost"]["options"]} == {
        theirs1.instance_id, theirs2.instance_id}
    eng.activate_ability(p1, soil, 0, hand_card_choices=[theirs1.instance_id, theirs2.instance_id])
    resolve(eng)
    assert theirs1.zone == Zone.EXILE and theirs2.zone == Zone.EXILE and mine.zone == Zone.GRAVEYARD
    assert any(o.name == "Saproling" for o in eng.state.permanents_controlled_by("p1"))


def test_night_soil_rejects_cards_from_two_different_graveyards():
    eng, p1, soil = _night_soil()
    mine = in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD)
    _, theirs = _opp_creature(eng)
    with pytest.raises(ValueError, match="cannot activate"):
        eng.activate_ability(p1, soil, 0, hand_card_choices=[mine.instance_id, theirs.instance_id])
    assert mine.zone == Zone.GRAVEYARD and theirs.zone == Zone.GRAVEYARD


def test_night_soil_is_not_offered_when_no_single_graveyard_has_two_creatures():
    eng, p1, soil = _night_soil()
    in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD)
    _opp_creature(eng)
    in_zone(eng, "Lightning Bolt", Zone.GRAVEYARD)
    assert not any(a.get("instance_id") == soil.instance_id and a.get("type") == "activate_ability"
                   for a in eng.legal_actions(p1))


def test_night_soil_fallback_without_picks_uses_one_graveyard():
    eng, p1, soil = _night_soil()
    mine = in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD)
    _, theirs1 = _opp_creature(eng)
    theirs2 = in_zone(eng, "Grizzly Bears", Zone.GRAVEYARD, controller="p2")
    eng.activate_ability(p1, soil, 0)
    assert theirs1.zone == Zone.EXILE and theirs2.zone == Zone.EXILE and mine.zone == Zone.GRAVEYARD
