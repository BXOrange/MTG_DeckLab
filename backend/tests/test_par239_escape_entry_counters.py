"""PAR-239 -- counter-bearing ETB variants run through the real engine.

RULE 702.138a: "~ escapes with N counters" applies only to a permanent whose spell was cast for its Escape cost.
RULE 614.1c: "enters with a +1/+1 counter on it for each creature card in your graveyard" is counted as it enters.
"""

from __future__ import annotations

from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.counters import entry_counters_condition
from tests.test_cedh_cube_keyword_mechanics import _card, _catalogue_obj, _engine

ESCAPE_EXILE_COUNT = 3  # Underworld Rage-Hound / Underworld Charger: "exile three other cards from your graveyard"
RAGE_HOUND_ESCAPE_MANA = 4  # {3}{R}
CHARGER_ESCAPE_MANA = 5  # {4}{B}
CHARGER_ESCAPE_COUNTERS = 2


def _fuel(p1, n):
    for i in range(n):
        o = GameObject(_card(f"Fuel{i}", "Instant", "{R}", 1), owner_id="p1", zone=Zone.GRAVEYARD)
        p1.add_to_zone(o, Zone.GRAVEYARD)


def _resolve(eng):
    eng.resolve_until_stable()


def test_clauses_are_recognised_and_riders_stay_unclaimed():
    assert entry_counters_condition("~ escapes with 2 +1/+1 counters on it.")["escape_gate"] is True
    assert entry_counters_condition(
        "~ enters with a +1/+1 counter on it for each creature card in your graveyard."
    )["creature_cards_in_graveyard_scale"] is True
    for unclaimed in (
        "~ escapes with 12 +1/+1 counters on it instead.",
        "~ escapes with your choice of a +1/+1 counter or a flying counter on it.",
        "~ escapes with 2 +1/+1 counters on it. when it enters this way, each opponent sacrifices a creature.",
    ):
        assert entry_counters_condition(unclaimed) is None


def test_escaped_permanent_gets_counters():
    eng, state, p1, _ = _engine()
    hound = _catalogue_obj("Underworld Rage-Hound", zone=Zone.GRAVEYARD)
    p1.add_to_zone(hound, Zone.GRAVEYARD)
    _fuel(p1, ESCAPE_EXILE_COUNT)
    p1.mana_pool.add("R", RAGE_HOUND_ESCAPE_MANA)
    eng.cast_spell(p1, hound)
    assert hound.cast_via_escape
    _resolve(eng)
    assert hound.zone == Zone.BATTLEFIELD
    assert hound.counters.get("+1/+1", 0) == 1


def test_hardcast_and_reanimated_get_no_counters():
    eng, state, p1, _ = _engine()
    hound = _catalogue_obj("Underworld Rage-Hound", zone=Zone.HAND)
    p1.add_to_zone(hound, Zone.HAND)
    p1.mana_pool.add("R", 2)
    eng.cast_spell(p1, hound)
    _resolve(eng)
    assert hound.zone == Zone.BATTLEFIELD and hound.counters.get("+1/+1", 0) == 0
    # Escaped once, died, then put onto the battlefield without being cast: the stale cast flag must not apply.
    other = _catalogue_obj("Underworld Charger", zone=Zone.GRAVEYARD)
    p1.add_to_zone(other, Zone.GRAVEYARD)
    _fuel(p1, ESCAPE_EXILE_COUNT)
    p1.mana_pool.add("B", CHARGER_ESCAPE_MANA)
    eng.cast_spell(p1, other)
    _resolve(eng)
    assert other.counters.get("+1/+1", 0) == CHARGER_ESCAPE_COUNTERS
    eng.rules.put_into_graveyard(other)
    eng.rules.return_from_graveyard(other)
    assert other.zone == Zone.BATTLEFIELD
    assert other.counters.get("+1/+1", 0) == 0  # a reanimated copy is a new object: no counters, no stale Escape flag


def test_graveyard_creature_count_scales_counters_at_entry():
    eng, state, p1, _ = _engine()
    for i in range(3):
        d = GameObject(_card(f"Dead{i}"), owner_id="p1", zone=Zone.GRAVEYARD)
        p1.add_to_zone(d, Zone.GRAVEYARD)
    land = GameObject(_card("Isle", "Basic Land — Island", "", 0), owner_id="p1", zone=Zone.GRAVEYARD)
    p1.add_to_zone(land, Zone.GRAVEYARD)
    troll = _catalogue_obj("Golgari Grave-Troll", zone=Zone.HAND)
    p1.add_to_zone(troll, Zone.HAND)
    p1.mana_pool.add("G", 6)
    eng.cast_spell(p1, troll)
    _resolve(eng)
    assert troll.zone == Zone.BATTLEFIELD
    assert troll.counters.get("+1/+1", 0) == 3


ESCAPE_FUEL_MAX = 8  # Ox of Agonas exiles eight other cards, the largest Escape cost among these cards
ESCAPE_MANA_EACH = 8  # enough of every colour for any of these Escape costs
ESCAPED_COUNTERS = {
    "Chainweb Aracnir": 3, "Loathsome Chimera": 1, "Ox of Agonas": 1, "Phoenix of Ash": 1,
    "Underworld Charger": 2, "Underworld Rage-Hound": 1, "Voracious Typhon": 3,
}


def test_every_newly_claimed_escape_card_escapes_with_its_counters():
    for name, expected in ESCAPED_COUNTERS.items():
        eng, state, p1, _ = _engine()
        obj = _catalogue_obj(name, zone=Zone.GRAVEYARD)
        p1.add_to_zone(obj, Zone.GRAVEYARD)
        _fuel(p1, ESCAPE_FUEL_MAX)
        for color in "WUBRG":
            p1.mana_pool.add(color, ESCAPE_MANA_EACH)
        eng.cast_spell(p1, obj)
        _resolve(eng)
        assert obj.zone == Zone.BATTLEFIELD, name
        assert obj.counters.get("+1/+1", 0) == expected, name
