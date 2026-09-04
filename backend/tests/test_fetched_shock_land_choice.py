"""Bug report, 2026-09-04: a shock land found by a search effect (a
fetchland, a tutor, Sakura-Tribe Elder-shaped ramp, …) got no RULE 614.1
"pay 2 life to enter untapped" choice at all — `RulesEngine._put_searched_
card` set ``obj.tapped`` straight from the search's own ``destination``
string (``"battlefield"`` → always untapped, ``"battlefield_tapped"`` →
always tapped), completely bypassing `enter_land_tapped` (the RULE 614.1
dispatcher `GameEngine.play_land` already routes an ordinary land play
through). A fetched shock land therefore always entered untapped *for
free* — worse than merely "no choice offered": it silently skipped the
land's own cost entirely.

Fixed by routing a landed ``destination="battlefield"`` search hit through
`enter_land_tapped` too, same as a played land — `"battlefield_tapped"`
(Evolving Wilds' own explicit "put it onto the battlefield tapped") stays
a plain unconditional tap with no choice offered, matching the accepted
real-card ruling that an explicit "tapped" destination already decides it.

See `test_ability_catalogue.py`'s `test_played_shock_land_defaults_tapped_
and_opens_pay_life_choice`/`test_shock_land_pay_life_choice_keeps_it_
untapped`/`test_shock_land_decline_leaves_it_tapped_and_keeps_life` for the
pre-existing coverage of `play_land`'s own (already-correct) side of this;
this file covers the search/fetch side.
"""

from __future__ import annotations

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.services.game_session import build_goldfish_engine


def _shock_land():
    return Card(
        id="SV", name="Steam Vents", type_line="Land — Island Mountain", is_land=True,
        oracle_text="As Steam Vents enters the battlefield, you may pay 2 life. "
                    "If you don't, it enters tapped.",
    )


def _basic(name="Forest"):
    return Card(id=name, name=name, type_line=f"Basic Land — {name}", is_land=True)


def _engine_with_library(*cards, starting_life=20):
    engine = build_goldfish_engine([], starting_hand=0, starting_life=starting_life)
    engine.begin_turn()
    p1 = engine.state.active_player
    for card in cards:
        p1.library.append(GameObject(card, owner_id=p1.id, zone=Zone.LIBRARY))
    return engine, p1


def test_fetched_shock_land_defaults_tapped_and_opens_the_pay_life_choice():
    engine, p1 = _engine_with_library(_shock_land())
    engine.rules.request_search(p1, {"type": "Land"}, "battlefield", count=1)
    [land] = [o for o in p1.library if o.name == "Steam Vents"]

    engine.rules.resolve_search_choice(land.instance_id)
    assert land in engine.state.battlefield
    assert land.tapped is True  # defaults tapped, same as a played shock land
    choice = engine.state.pending_choice
    assert choice is not None and choice["kind"] == "land_tapped"


def test_paying_the_life_leaves_it_untapped():
    engine, p1 = _engine_with_library(_shock_land())
    engine.rules.request_search(p1, {"type": "Land"}, "battlefield", count=1)
    [land] = [o for o in p1.library if o.name == "Steam Vents"]
    engine.rules.resolve_search_choice(land.instance_id)

    engine.resolve_pending_choice("pay")
    assert land.tapped is False
    assert p1.life == 18
    assert engine.state.pending_choice is None


def test_declining_leaves_it_tapped_and_keeps_the_life():
    engine, p1 = _engine_with_library(_shock_land())
    engine.rules.request_search(p1, {"type": "Land"}, "battlefield", count=1)
    [land] = [o for o in p1.library if o.name == "Steam Vents"]
    engine.rules.resolve_search_choice(land.instance_id)

    engine.resolve_pending_choice("decline")
    assert land.tapped is True
    assert p1.life == 20
    assert engine.state.pending_choice is None


def test_explicit_battlefield_tapped_destination_offers_no_choice():
    # Evolving Wilds-shaped: the fetch effect's own explicit "tapped"
    # already decides it (the accepted real-card ruling) — no pay-life
    # choice opens, the land just enters tapped, no life spent.
    engine, p1 = _engine_with_library(_shock_land())
    engine.rules.request_search(p1, {"type": "Land"}, "battlefield_tapped", count=1)
    [land] = [o for o in p1.library if o.name == "Steam Vents"]

    engine.rules.resolve_search_choice(land.instance_id)
    assert land in engine.state.battlefield
    assert land.tapped is True
    assert engine.state.pending_choice is None
    assert p1.life == 20


def test_a_plain_fetched_basic_land_still_enters_untapped_with_no_choice():
    # No regression for the overwhelming common case: an ordinary land
    # (`land_tap_condition` kind "never") fetched to "battlefield" stays
    # untapped, no pending choice opened.
    engine, p1 = _engine_with_library(_basic("Forest"))
    engine.rules.request_search(p1, {"type": "Land"}, "battlefield", count=1)
    [land] = [o for o in p1.library if o.name == "Forest"]

    engine.rules.resolve_search_choice(land.instance_id)
    assert land in engine.state.battlefield
    assert land.tapped is False
    assert engine.state.pending_choice is None


def test_a_fetched_check_land_still_resolves_its_deterministic_condition():
    # A check/fast/slow land's board-state condition (no interactive
    # choice) must keep resolving immediately through the search path too.
    check_land = Card(
        id="RC", name="Rootbound Crag", type_line="Land", is_land=True,
        oracle_text="Rootbound Crag enters the battlefield tapped unless you "
                    "control a Mountain or a Forest.\n{T}: Add {R} or {G}.",
    )
    engine, p1 = _engine_with_library(check_land)
    mountain = GameObject(_basic("Mountain"), owner_id=p1.id, zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(mountain)

    engine.rules.request_search(p1, {"type": "Land"}, "battlefield", count=1)
    [land] = [o for o in p1.library if o.name == "Rootbound Crag"]
    engine.rules.resolve_search_choice(land.instance_id)
    assert land.tapped is False  # already controls a Mountain
    assert engine.state.pending_choice is None
