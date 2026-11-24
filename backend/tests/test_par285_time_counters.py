"""PAR-285 class C: time counters on permanents and suspended cards (RULE 122.1, 702.62a-b).

Shivan Sand-Mage, Timebender, Timecrafting and Dust of Moments remove or put time counters on "target permanent or
suspended card" / "target permanent with a time counter on it or suspended card" / "each permanent and each suspended
card". Tests run parser -> binder -> `legal_targets` -> effect on the real cards, with matching and non-matching
candidates; removing the last counter from a suspended card must fire Suspend's own last-counter trigger."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.suspended_cards import is_suspended
from mtg_analyzer.game.targeting import legal_targets
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

CARDS = ["Shivan Sand-Mage", "Timebender", "Timecrafting", "Dust of Moments", "Fury Charm"]
REMOVE_KIND = "permanent_or_suspended_card"
ADD_KIND = "permanent_with_time_counter_or_suspended_card"


def _real(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    return card


def _modes(name: str):
    result = parse_oracle(_real(name))
    assert result.modeled is True, name
    (modal,) = [ab for ab in result.specs if ab.modes]
    remove, add = modal.modes["options"]
    return remove, add


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.state.current_step = "main1"
    return eng


def _card(name, type_line="Creature — Human"):
    return Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line, power=1, toughness=1)


def _put(eng, card, owner="p1", zone=Zone.BATTLEFIELD, time=0, suspend=False):
    obj = GameObject(card, owner_id=owner, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        getattr(eng.state.player_by_id(owner), zone.value).append(obj)
    if time:
        obj.add_counters("time", time)
    obj.granted_suspend = suspend
    return obj


def _offered(eng, effect, source):
    return {o["instance_id"] for o in legal_targets(eng.state, "p1", effect.target_spec, source=source)}


@pytest.mark.parametrize("name", CARDS)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_real(name)).modeled is True


def test_parse_shapes():
    (rm,) = match_clause("remove 2 time counters from target permanent or suspended card")
    assert rm.params == {"mode": "remove", "count": 2, "target_kind": REMOVE_KIND}
    (add,) = match_clause("put x time counters on target permanent with a time counter on it or suspended card")
    assert add.params == {"mode": "add", "count": "x", "target_kind": ADD_KIND}
    (mass,) = match_clause("remove 2 time counters from each permanent and each suspended card")
    assert mass.params == {"mode": "remove", "count": 2, "mass": True}
    # adversarial: the pairing is exact, other nouns and a wrong counter kind fail closed
    assert match_clause("put 2 time counters on target permanent or suspended card") is None
    assert match_clause("remove 2 time counters from target creature or suspended card") is None
    assert match_clause("remove 2 fade counters from target permanent or suspended card") is None


def test_target_pools_split_permanents_by_time_counter_and_keep_only_suspended_exile_cards():
    eng = _engine()
    mage = _put(eng, _real("Shivan Sand-Mage"))
    plain = _put(eng, _card("Plain"))
    ticking = _put(eng, _card("Ticking"), time=2)
    suspended = _put(eng, _card("Suspended"), "p2", Zone.EXILE, time=3, suspend=True)
    no_suspend = _put(eng, _card("Exiled With Counters"), "p1", Zone.EXILE, time=3, suspend=False)
    spent = _put(eng, _card("No Counters"), "p1", Zone.EXILE, time=0, suspend=True)
    assert is_suspended(suspended) and not is_suspended(no_suspend) and not is_suspended(spent)
    remove, add = (build_effects(spec_list, mage)[0] for spec_list in _modes("Shivan Sand-Mage"))
    assert _offered(eng, remove, mage) == {mage.instance_id, plain.instance_id, ticking.instance_id, suspended.instance_id}
    assert _offered(eng, add, mage) == {ticking.instance_id, suspended.instance_id}


def test_remove_two_from_a_permanent_and_from_a_suspended_card():
    eng = _engine()
    mage = _put(eng, _real("Shivan Sand-Mage"))
    ticking = _put(eng, _card("Ticking"), time=3)
    suspended = _put(eng, _card("Suspended"), "p2", Zone.EXILE, time=3, suspend=True)
    remove = build_effects(_modes("Shivan Sand-Mage")[0], mage)[0]
    remove.apply(GameContext(eng.state, eng.rules), [ticking])
    assert ticking.counters["time"] == 1
    remove.apply(GameContext(eng.state, eng.rules), [suspended])
    assert suspended.counters["time"] == 1


def test_removing_the_last_time_counter_from_a_suspended_card_offers_the_free_cast():
    eng = _engine()
    mage = _put(eng, _real("Shivan Sand-Mage"))
    suspended = _put(eng, _card("Suspended"), "p2", Zone.EXILE, time=2, suspend=True)
    remove = build_effects(_modes("Shivan Sand-Mage")[0], mage)[0]
    remove.apply(GameContext(eng.state, eng.rules), [suspended])
    assert suspended.counters.get("time", 0) == 0
    eng.resolve_until_stable()  # Suspend's last-counter trigger resolves: the owner may cast it (RULE 702.62a)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "play_during_resolution" and choice["player_id"] == "p2"
    assert choice["free"] is True and choice["instance_ids"] == [suspended.instance_id]


def test_put_adds_only_where_a_time_counter_already_stands_or_a_card_is_suspended():
    eng = _engine()
    mage = _put(eng, _real("Shivan Sand-Mage"))
    ticking = _put(eng, _card("Ticking"), time=1)
    suspended = _put(eng, _card("Suspended"), "p2", Zone.EXILE, time=1, suspend=True)
    add = build_effects(_modes("Shivan Sand-Mage")[1], mage)[0]
    add.apply(GameContext(eng.state, eng.rules), [ticking])
    add.apply(GameContext(eng.state, eng.rules), [suspended])
    assert ticking.counters["time"] == 3 and suspended.counters["time"] == 3


def test_timecrafting_reads_the_announced_x():
    eng = _engine()
    spell = _put(eng, _real("Timecrafting"), zone=Zone.HAND)
    spell.x_paid = 3
    ticking = _put(eng, _card("Ticking"), time=5)
    remove = build_effects(_modes("Timecrafting")[0], spell)[0]
    remove.apply(GameContext(eng.state, eng.rules), [ticking])
    assert ticking.counters["time"] == 2


def test_dust_of_moments_mass_forms():
    eng = _engine()
    dust = _put(eng, _real("Dust of Moments"), zone=Zone.HAND)
    ticking = _put(eng, _card("Ticking"), time=3)
    plain = _put(eng, _card("Plain"))
    suspended = _put(eng, _card("Suspended"), "p2", Zone.EXILE, time=4, suspend=True)
    remove, add = (build_effects(spec_list, dust)[0] for spec_list in _modes("Dust of Moments"))
    add.apply(GameContext(eng.state, eng.rules), [])
    assert ticking.counters["time"] == 5 and suspended.counters["time"] == 6
    assert plain.counters.get("time", 0) == 0  # no counter yet: "each permanent with a time counter on it"
    remove.apply(GameContext(eng.state, eng.rules), [])
    assert ticking.counters["time"] == 3 and suspended.counters["time"] == 4 and plain.counters.get("time", 0) == 0


def test_timebender_and_sand_mage_share_the_same_two_modes():
    """Timebender's face-up trigger offers exactly Shivan Sand-Mage's modes; run its remove mode on a real target."""
    assert [[(e.type, e.params) for e in mode] for mode in _modes("Timebender")] == [
        [(e.type, e.params) for e in mode] for mode in _modes("Shivan Sand-Mage")]
    eng = _engine()
    bender = _put(eng, _real("Timebender"))
    ticking = _put(eng, _card("Ticking"), time=2)
    build_effects(_modes("Timebender")[0], bender)[0].apply(GameContext(eng.state, eng.rules), [ticking])
    assert ticking.counters.get("time", 0) == 0
