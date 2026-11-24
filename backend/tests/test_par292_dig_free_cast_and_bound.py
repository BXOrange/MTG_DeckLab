"""PAR-292 M19: the dig that casts a spell from among the looked-at cards for free, and the dig whose criteria are
bounded by a measured amount ("mana value X or less").

Parsed from real oracle wording, then run on a real engine with bystanders: the mana-value bound is respected, the card
that is not cast goes to the bottom with the rest, a land cannot be "cast", the cast ignores timing (RULE 608.2g), and the
measured bound / count changes with the board.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle

from tests.support.deck_batch import activate, attack, card, cast, filler, game, stack_library
from tests.test_par157_back_selections import _cached

CAST_CARDS = ["Cosmic Cube", "Kiora, Sovereign of the Deep", "Perception Bobblehead"]
BOUND_CARDS = ["Hatchery Spider", "Vivien's Arkbow", "Emergent Woodwurm", "Genesis Wave", "Saheeli's Directive",
               "Keldon Flamesage"]


@pytest.mark.parametrize("name", CAST_CARDS + BOUND_CARDS)
def test_claimed_cards_are_modeled(name):
    assert parse_oracle(_cached(name)).modeled


def _probe(text, **kw):
    return parse_oracle(Card(id="t", name="Probe", type_line="Artifact", oracle_text=text, **kw))


@pytest.mark.parametrize("text", [
    # the rest must be the random bottom (no ordering decision, nothing else to do with the rest)
    "{T}: Look at the top three cards of your library. You may cast a spell from among them without paying its mana cost. "
    "Put the rest into your graveyard.",
    # a cap the amount grammar cannot read
    "{T}: Look at the top three cards of your library. You may cast a spell with mana value less than the moon's phase "
    "from among them without paying its mana cost. Put the rest on the bottom of your library in a random order.",
    # a bound X with no X count to be the same X as
    "{T}: Look at the top three cards of your library. You may cast a spell with mana value X or less from among them "
    "without paying its mana cost. Put the rest on the bottom of your library in a random order.",
    # an announced X is not supported by the free-cast dig
    "{X}, {T}: Look at the top X cards of your library. You may cast a spell from among them without paying its mana cost. "
    "Put the rest on the bottom of your library in a random order.",
    # an unbound X under a trigger
    "Whenever you cast a spell, look at the top X cards of your library. You may put a creature card with mana value X or "
    "less from among them onto the battlefield. Put the rest on the bottom of your library in a random order.",
    # a bound X with a count that is not that X
    "{T}: Look at the top three cards of your library. You may put a creature card with mana value X or less from among "
    "them onto the battlefield. Put the rest on the bottom of your library in a random order.",
    # a power bound is not a mana-value bound
    "{X}, {T}: Look at the top X cards of your library. You may put a creature card with power X or less from among "
    "them onto the battlefield. Put the rest on the bottom of your library in a random order.",
])
def test_near_misses_stay_unclaimed(text):
    assert not _probe(text).modeled


def _stack(eng, *entries):
    """Library, bottom to top as listed: ``(name, type_line, mana value)``."""
    made = [filler(eng, n, zone=Zone.LIBRARY, type_line=t, mv=mv,
                   **({"power": 2, "toughness": 2} if "Creature" in t else {})) for n, t, mv in entries]
    stack_library(eng, "p1", *made)
    return made


def _offered_ids(eng):
    choice = eng.state.pending_choice or eng.state.resolution_play_choice
    return list(choice["instance_ids"]) if choice else []


def _ids(made, *names):
    return sorted(o.instance_id for o in made if o.name in names)


def _bobblehead_game(extra_bobbleheads=0):
    eng = game(library=20)
    bobble = card(eng, "Perception Bobblehead")
    for i in range(extra_bobbleheads):
        filler(eng, f"Other Bobblehead {i}", type_line="Artifact — Bobblehead")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 3})
    return eng, bobble


def test_bobblehead_offers_only_cheap_spells_among_the_looked_at_cards_and_bottoms_the_rest():
    eng, bobble = _bobblehead_game(extra_bobbleheads=2)  # three Bobbleheads: look at three cards
    p1 = eng.state.player_by_id("p1")
    made = _stack(
        eng, ("Deep Cheap", "Sorcery", 1), ("Big Sorcery", "Sorcery", 5), ("Top Land", "Land", 0),
        ("Cheap Creature", "Creature", 3), ("Pricey", "Creature", 4))
    # top down: Pricey, Cheap Creature, Top Land are looked at; Big Sorcery and Deep Cheap lie below them
    activate(eng, bobble, 0)
    assert _offered_ids(eng) == _ids(made, "Cheap Creature")  # Pricey (MV 4 > 3) and the land are never offered
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    names = [o.name for o in p1.library]  # index 0 is the bottom
    assert set(names[:3]) == {"Pricey", "Cheap Creature", "Top Land"}  # the three looked-at cards went under
    assert names[-2:] == ["Deep Cheap", "Big Sorcery"]  # the unlooked cards keep their order on top of the rest


def test_the_cast_card_resolves_and_the_other_cards_go_to_the_bottom():
    eng, bobble = _bobblehead_game(extra_bobbleheads=2)
    p1 = eng.state.player_by_id("p1")
    made = _stack(eng, ("Keep", "Sorcery", 7), ("Cheap Creature", "Creature", 2), ("Pricey", "Sorcery", 6))
    activate(eng, bobble, 0)
    assert _offered_ids(eng) == _ids(made, "Cheap Creature")
    cheap = next(o for o in made if o.name == "Cheap Creature")
    eng.play_resolution_card(p1, cheap)
    eng.resolve_until_stable()
    assert cheap in eng.state.battlefield and cheap not in p1.library  # cast without paying: it resolved
    assert {o.name for o in p1.library[:2]} == {"Keep", "Pricey"}  # the two not cast are the new bottom


def test_a_card_that_is_not_cast_stays_with_the_rest():
    eng, bobble = _bobblehead_game()  # one Bobblehead: look at one card
    p1 = eng.state.player_by_id("p1")
    only, = _stack(eng, ("Only Spell", "Sorcery", 2))
    activate(eng, bobble, 0)
    assert _offered_ids(eng) == [only.instance_id]
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert p1.library[0] is only and only.zone == Zone.LIBRARY  # declined: it went to the bottom, never to exile


def test_a_land_among_the_looked_at_cards_is_never_offered():
    eng, bobble = _bobblehead_game()
    p1 = eng.state.player_by_id("p1")
    _stack(eng, ("Top Land", "Land", 0))
    activate(eng, bobble, 0)
    assert eng.state.pending_choice is None and eng.state.resolution_play_choice is None
    assert p1.library[0].name == "Top Land"  # nothing castable: the looked-at card simply goes to the bottom


def test_the_looked_at_count_is_the_number_of_bobbleheads():
    one, bobble = _bobblehead_game()
    three, bobble3 = _bobblehead_game(extra_bobbleheads=2)
    for eng, b in ((one, bobble), (three, bobble3)):
        _stack(eng, ("Third", "Sorcery", 1), ("Second", "Sorcery", 1), ("First", "Sorcery", 1))
        activate(eng, b, 0)
    assert len(_offered_ids(one)) == 1
    assert len(_offered_ids(three)) == 3


def test_the_free_cast_ignores_timing_a_sorcery_offered_outside_a_main_phase():
    eng, bobble = _bobblehead_game()
    p1 = eng.state.player_by_id("p1")
    sorcery, = _stack(eng, ("Sorcery Spell", "Sorcery", 1))
    eng.state.current_phase, eng.state.current_step = "combat", "declare_blockers"
    eng.activate_ability(p1, bobble, 0)
    eng.resolve_until_stable()
    assert _offered_ids(eng) == [sorcery.instance_id]  # a sorcery at combat: castable only through this permission
    eng.play_resolution_card(p1, sorcery)
    eng.resolve_until_stable()
    assert sorcery in p1.graveyard


def _kiora_game(spell_mv):
    eng = game(library=20)
    card(eng, "Kiora, Sovereign of the Deep")
    kraken = filler(eng, "Big Kraken", type_line="Creature — Kraken", mv=spell_mv, zone=Zone.HAND,
                    power=1, toughness=1)
    return eng, kraken


def test_kiora_looks_at_the_spells_mana_value_and_offers_only_strictly_lesser_spells():
    eng, kraken = _kiora_game(3)
    made = _stack(eng, ("Deep", "Sorcery", 1), ("Equal", "Sorcery", 3), ("Lesser", "Sorcery", 2),
                  ("Cheapest", "Sorcery", 1))
    cast(eng, kraken)
    # three cards looked at (Cheapest, Lesser, Equal); Equal (MV 3, not less than 3) and Deep (below them) are out
    assert sorted(_offered_ids(eng)) == _ids(made, "Lesser", "Cheapest")


def test_kiora_with_a_cheaper_spell_looks_at_fewer_cards():
    eng, kraken = _kiora_game(2)
    made = _stack(eng, ("Deep", "Sorcery", 1), ("Lesser", "Sorcery", 1), ("Cheapest", "Sorcery", 1))
    cast(eng, kraken)
    assert sorted(_offered_ids(eng)) == _ids(made, "Lesser", "Cheapest")  # two cards looked at: Deep is not


def test_kiora_does_not_trigger_on_a_non_matching_spell():
    eng = game(library=20)
    card(eng, "Kiora, Sovereign of the Deep")
    bear = filler(eng, "Bear", type_line="Creature — Bear", mv=3, zone=Zone.HAND, power=2, toughness=2)
    _stack(eng, ("Cheap", "Sorcery", 1), ("Cheaper", "Sorcery", 1))
    cast(eng, bear)
    assert not _offered_ids(eng)


def _cube_game(*attackers):
    eng = game(library=20)
    card(eng, "Cosmic Cube")
    bodies = [filler(eng, f"Attacker {p}", power=p, toughness=3) for p in attackers]
    made = _stack(eng, ("Four", "Sorcery", 4), ("Three", "Sorcery", 3), ("One", "Instant", 1), ("Two", "Creature", 2))
    attack(eng, bodies)
    return eng, made


def test_cosmic_cube_bound_is_the_greatest_power_among_attacking_creatures():
    eng, made = _cube_game(1, 3)
    assert sorted(_offered_ids(eng)) == _ids(made, "One", "Two", "Three")  # power 3: Four (MV 4) is out


def test_cosmic_cube_with_only_a_weak_attacker_offers_less():
    eng, made = _cube_game(1)
    assert _offered_ids(eng) == _ids(made, "One")


# --- the measured mana-value bound on a put-onto-the-battlefield dig -------------------------------------------------


def test_arkbow_bound_and_count_are_the_announced_x():
    eng = game(library=20)
    arkbow = card(eng, "Vivien's Arkbow")
    p1 = eng.state.player_by_id("p1")
    filler(eng, "Discard Fodder", type_line="Creature", zone=Zone.HAND)
    made = _stack(eng, ("Far Big", "Creature", 1), ("Cost 3", "Creature", 3), ("Cost 1", "Creature", 1),
                  ("Land", "Land", 0), ("Cost 2", "Creature", 2))
    p1.mana_pool.add_many({"C": 2})
    activate(eng, arkbow, 0, x=2)
    # X = 2 cards looked at (Cost 2, Land): only the creature among them within mana value 2
    assert sorted(o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o) == ["Cost 2"]


def test_arkbow_mana_value_bound_excludes_a_costlier_creature_inside_the_count():
    eng = game(library=20)
    arkbow = card(eng, "Vivien's Arkbow")
    p1 = eng.state.player_by_id("p1")
    filler(eng, "Discard Fodder", type_line="Creature", zone=Zone.HAND)
    _stack(eng, ("Cost 1", "Creature", 1), ("Cost 3", "Creature", 3), ("Cost 2", "Creature", 2))
    p1.mana_pool.add_many({"C": 2})
    activate(eng, arkbow, 0, x=2)
    # looked at Cost 2 and Cost 3: Cost 3 is above X = 2 and is never offered; Cost 1 lies beyond the count
    assert sorted(o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o) == ["Cost 2"]


def _spider_game(graveyard_creatures):
    eng = game(library=20)
    p1 = eng.state.player_by_id("p1")
    for i in range(graveyard_creatures):
        filler(eng, f"Dead {i}", type_line="Creature", zone=Zone.GRAVEYARD, power=1, toughness=1)
    spider = card(eng, "Hatchery Spider", zone=Zone.HAND)
    made = [
        filler(eng, n, zone=Zone.LIBRARY, type_line=t, mv=mv, mana_cost_string="{%d}{%s}" % (max(mv - 1, 0), c[0]), **kw)
        for n, t, mv, c, kw in [
            ("Beyond", "Creature", 1, ["G"], {"power": 2, "toughness": 2}),
            ("Green Three", "Creature", 3, ["G"], {"power": 2, "toughness": 2}),
            ("Red One", "Creature", 1, ["R"], {"power": 2, "toughness": 2}),
            ("Green One", "Creature", 1, ["G"], {"power": 2, "toughness": 2}),
            ("Green Land", "Land", 0, ["G"], {}),
            ("Green Two", "Creature", 2, ["G"], {"power": 2, "toughness": 2}),
        ]
    ]
    stack_library(eng, "p1", *made)
    return eng, spider, made


def test_hatchery_spider_looks_at_and_bounds_by_the_creature_cards_in_the_graveyard():
    eng, spider, made = _spider_game(3)  # X = 3: look at Green Two, Green Land, Green One; cost bound 3
    cast(eng, spider)
    labels = sorted(o["label"] for o in eng.state.pending_choice["options"] if "instance_id" in o)
    # green permanent cards within the top three with mana value 3 or less; Red One is not green, Beyond is below
    assert labels == ["Green Land", "Green One", "Green Two"]


def test_hatchery_spider_with_a_smaller_graveyard_looks_at_less_and_bounds_tighter():
    eng, spider, made = _spider_game(1)  # X = 1: only Green Two is looked at, and its mana value 2 exceeds X
    cast(eng, spider)
    assert not (eng.state.pending_choice and any("instance_id" in o for o in eng.state.pending_choice["options"]))
