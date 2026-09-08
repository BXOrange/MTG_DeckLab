"""Coverage proof: the parameterized library-search feature expresses the
most popular real "search your library" cards (tutors / ramp / fetch).

This is the "überprüfe ob diese Funktionen umgesetzt werden können" check for
the search feature. Each entry below is a real, high-play-rate card (EDHREC
staples + Legacy/Modern tutors) reduced to the two axes the feature exposes:
``criteria`` (what to look for — `models.card_query`) and ``destination``
(where the found card goes). The test drives each spec through the real
engine and asserts the card lands in the right zone — so if the feature
regresses, the affected cards are named.

Known limitations are asserted explicitly at the bottom so the coverage
boundary is documented rather than implied.
"""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.effects.core import EffectRegistry


# --- A representative library covering every criterion the specs use -------


def _card(name, type_line, cost="", colors=None, **flags):
    return Card(
        id=name,
        name=name,
        type_line=type_line,
        mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost if cost else 0,
        color_identity=set(colors or []),
        **flags,
    )


def popular_library():
    return [
        _card("Forest", "Basic Land — Forest", is_land=True, colors=["G"]),
        _card("Island", "Basic Land — Island", is_land=True, colors=["U"]),
        _card("Command Tower", "Land", is_land=True),  # nonbasic
        _card("Llanowar Elves", "Creature — Elf Druid", "{G}", ["G"],
              is_creature=True, power=1, toughness=1),
        _card("Craterhoof Behemoth", "Creature — Beast", "{5}{G}{G}{G}", ["G"],
              is_creature=True, power=5, toughness=5),
        _card("Counterspell", "Instant", "{U}{U}", ["U"], is_instant=True),
        _card("Rite of Replication", "Sorcery", "{4}{U}", ["U"], is_sorcery=True),
        _card("Sol Ring", "Artifact", "{1}"),
        _card("Rhystic Study", "Enchantment", "{2}{U}", ["U"]),
    ]


def new_engine():
    eng = GameEngine.new_game([("p1", "Alice", popular_library())], starting_hand=0)
    return eng, eng.state.active_player


# --- The popular-card coverage table ---------------------------------------
# (label, criteria, destination, count, expected eligible names or None)

POPULAR_CARDS = [
    ("Demonic Tutor — any card to hand", "", "hand", 1, None),
    ("Diabolic Tutor — any card to hand", "", "hand", 1, None),
    ("Gamble — any card to hand", "", "hand", 1, None),
    ("Vampiric Tutor — any card on top", "", "library_top", 1, None),
    ("Mystical Tutor — instant/sorcery on top",
        {"type": ["Instant", "Sorcery"]}, "library_top", 1,
        {"Counterspell", "Rite of Replication"}),
    ("Enlightened Tutor — artifact/enchantment on top",
        {"type": ["Artifact", "Enchantment"]}, "library_top", 1,
        {"Sol Ring", "Rhystic Study"}),
    ("Worldly Tutor — creature on top", "Creature", "library_top", 1,
        {"Llanowar Elves", "Craterhoof Behemoth"}),
    ("Rampant Growth — basic land to battlefield tapped",
        {"basic": True}, "battlefield_tapped", 1, {"Forest", "Island"}),
    ("Farseek — Plains/Island/Swamp/Mountain to battlefield tapped",
        {"type": ["Plains", "Island", "Swamp", "Mountain"]}, "battlefield_tapped", 1,
        {"Island"}),
    ("Nature's Lore — Forest to battlefield (untapped)",
        "Forest", "battlefield", 1, {"Forest"}),
    ("Sylvan Scrying — any land to hand", "Land", "hand", 1,
        {"Forest", "Island", "Command Tower"}),
    ("Crop Rotation — a land to battlefield", "Land", "battlefield", 1,
        {"Forest", "Island", "Command Tower"}),
    ("Green Sun's Zenith (X=3) — green creature MV<=3 to battlefield",
        {"type": "Creature", "color": "G", "max_mana_value": 3}, "battlefield", 1,
        {"Llanowar Elves"}),
    ("Chord of Calling — a creature to battlefield", "Creature", "battlefield", 1,
        {"Llanowar Elves", "Craterhoof Behemoth"}),
    ("Entomb — any card to graveyard", "", "graveyard", 1, None),
    ("Fabled Passage / Evolving Wilds — basic land to battlefield tapped",
        {"basic": True}, "battlefield_tapped", 1, {"Forest", "Island"}),
]


def _zone_has(player, state, instance_id, destination):
    if destination in ("battlefield", "battlefield_tapped"):
        obj = state.find_object(instance_id)
        if obj not in state.battlefield:
            return False
        return obj.tapped == (destination == "battlefield_tapped")
    if destination == "library_top":
        return player.library[-1].instance_id == instance_id
    if destination == "library_bottom":
        return player.library[0].instance_id == instance_id
    zone = {"hand": player.hand, "graveyard": player.graveyard, "exile": player.exile}[destination]
    return any(o.instance_id == instance_id for o in zone)


@pytest.mark.parametrize(
    "label,criteria,destination,count,expected",
    POPULAR_CARDS,
    ids=[c[0].split(" —")[0] for c in POPULAR_CARDS],
)
def test_popular_card_is_expressible(label, criteria, destination, count, expected):
    eng, p1 = new_engine()

    # The whole card is realized as a registry-built effect + resolve, i.e.
    # exactly the path an oracle handler would take — not a bespoke call.
    effect = EffectRegistry.create(
        "search", {"criteria": criteria, "destination": destination, "count": count}
    )
    effect.apply(eng.rules.context)

    choice = eng.state.pending_choice
    assert choice is not None, f"{label}: expected a search choice to open"
    names = {e["name"] for e in choice["eligible"]}
    if expected is not None:
        assert names == expected, f"{label}: eligible {names} != {expected}"

    chosen = choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(chosen)
    assert eng.state.pending_choice is None
    assert _zone_has(p1, eng.state, chosen, destination), (
        f"{label}: card did not reach {destination}"
    )


def test_buried_alive_puts_three_creatures_in_graveyard():
    """Buried Alive — search for up to three creature cards to the graveyard."""
    eng, p1 = new_engine()
    eng.rules.request_search(p1, "Creature", "graveyard", count=3)
    picked = []
    for _ in range(3):
        choice = eng.state.pending_choice
        if choice is None:
            break
        cid = choice["eligible"][0]["instance_id"]
        picked.append(cid)
        eng.rules.resolve_search_choice(cid)
    # Only two creatures exist, so it finishes after two picks.
    assert eng.state.pending_choice is None
    assert len(picked) == 2
    assert all(any(o.instance_id == c for o in p1.graveyard) for c in picked)


# --- Documented coverage boundary ------------------------------------------


def test_cultivate_split_destination_single_search():
    """Cultivate/Kodama's Reach fetch two basics to *different* zones (one to
    the battlefield tapped, one to hand) as a single search — `destinations`
    overrides `destination` positionally per pick (`RulesEngine.
    _finish_search`), so this no longer needs the two-chained-searches
    workaround a prior version of this test documented.
    """
    eng, p1 = new_engine()
    eng.rules.request_search(
        p1, {"basic": True}, "battlefield_tapped", count=2,
        destinations=["battlefield_tapped", "hand"],
    )
    first = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(first)
    second = eng.state.pending_choice["eligible"][0]["instance_id"]
    eng.rules.resolve_search_choice(second)
    assert eng.state.pending_choice is None
    assert eng.state.find_object(first).tapped
    assert any(o.instance_id == second for o in p1.hand)
