"""PAR-258: "differently named lands you control" as one shared count, in every slot a card reads it.

RULE 201.2: two objects have the same name only if they share an English name, so two Plains count once.
The count is the existing ``distinct: name`` selector (`count_phrase`), reached from "where X is the number of",
"equal to the number of", threshold conditions and the activated-ability cost reduction; these tests pin the
parse and run each slot on a real engine with duplicate and distinct land names.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_amount_phrase, parse_count_phrase
from mtg_analyzer.parser.oracle.segmenter import static_condition

from tests.support.deck_batch import activate, cast, enter, filler, game, main_phase, _place
from mtg_analyzer.models.game.game_object import GameObject

#: The selector every slot must reach.
DIFFERENT_LANDS = {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}, "distinct": "name"}


def _card(name: str, text: str, type_line: str = "Creature — Human", **kw) -> Card:
    return Card(id=name, name=name, type_line=type_line, oracle_text=text,
                is_creature="Creature" in type_line, is_sorcery="Sorcery" in type_line,
                toughness=2 if "Creature" in type_line else None, **kw)


def _lands(engine, *names: str):
    for i, name in enumerate(names):
        filler(engine, name=name, type_line="Basic Land" if name in ("Plains", "Island") else "Land", mv=0)
        # filler ids collide by name on purpose: only the *name* decides distinctness


def _count(engine) -> int:
    return continuous.count_selector(engine.state, "p1", DIFFERENT_LANDS)


def test_phrase_reads_distinct_name_for_every_wording():
    assert parse_count_phrase("differently named lands you control") == DIFFERENT_LANDS
    assert parse_amount_phrase("the number of differently named lands you control") == DIFFERENT_LANDS
    assert parse_count_phrase("lands you control with different names") == DIFFERENT_LANDS
    # fail closed: a second distinctness axis is not one count
    assert parse_count_phrase("differently named creatures with different powers") is None


def test_threshold_condition_reads_the_same_selector():
    assert static_condition("you control 7 or more differently named lands") == {
        "kind": "control_count", "selector": DIFFERENT_LANDS, "min": 7,
    }


def test_count_counts_names_not_lands():
    engine = game()
    assert _count(engine) == 0
    _lands(engine, "Plains", "Plains", "Island", "Command Tower", "Command Tower")
    assert _count(engine) == 3  # two Plains once, two Command Towers once, Island once
    filler(engine, name="Plains", type_line="Basic Land")
    assert _count(engine) == 3  # a third Plains changes nothing
    filler(engine, name="Bear")  # a nonland with a new name is not a land
    assert _count(engine) == 3
    _lands(engine, "Urza's Tower")
    assert _count(engine) == 4


def test_gain_life_etb_scales_with_distinct_names():
    engine = game()
    _lands(engine, "Plains", "Plains", "Island")
    before = engine.state.player_by_id("p1").life
    obj = _place(engine, GameObject(_card("Medic", "When Medic enters, you gain life equal to the number of differently named lands you control."),
                                    owner_id="p1", zone=Zone.BATTLEFIELD), "p1", Zone.BATTLEFIELD)
    enter(engine, obj)
    assert engine.state.player_by_id("p1").life == before + 2


def test_tokens_and_draw_use_the_count():
    engine = game()
    _lands(engine, "Plains", "Plains", "Island", "Command Tower")
    obj = _place(engine, GameObject(_card("Gamemaster", "When Gamemaster enters, create X 1/1 red Officer creature tokens, where X is the number of differently named lands you control."),
                                    owner_id="p1", zone=Zone.BATTLEFIELD), "p1", Zone.BATTLEFIELD)
    enter(engine, obj)
    assert len([o for o in engine.state.battlefield if o.name == "Officer"]) == 3


def test_deep_space_scan_draws_and_lifts_hand_size():
    engine = game(library=10)
    _lands(engine, "Plains", "Island", "Island")
    scan = _place(engine, GameObject(
        _card("Scan", "Draw X cards, where X is the number of differently named lands you control. You have no maximum hand size until your next turn.",
              "Sorcery", mana_cost_string="{5}{U}"),
        owner_id="p1", zone=Zone.HAND), "p1", Zone.HAND)
    hand = len(engine.state.player_by_id("p1").hand)
    cast(engine, scan)
    player = engine.state.player_by_id("p1")
    assert len(player.hand) == hand - 1 + 2
    assert continuous.has_no_maximum_hand_size(engine.state, player)


def _praxis(engine):
    return _place(engine, GameObject(
        _card("Praxis", "All creatures get -X/-X until end of turn, where X is the number of differently named lands you control. If X is 6 or more, create 2 2/1 red Klingon Warrior creature tokens with haste.",
              "Sorcery", mana_cost_string="{5}{R}"),
        owner_id="p1", zone=Zone.HAND), "p1", Zone.HAND)


def test_praxis_threshold_below_and_at_six():
    engine = game()
    bear = filler(engine, name="Bear", power=3, toughness=3)
    _lands(engine, "Plains", "Plains", "Island", "Swamp", "Mountain")  # 4 names
    cast(engine, _praxis(engine))
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (-1, -1) or bear.zone != Zone.BATTLEFIELD
    assert not [o for o in engine.state.battlefield if o.name == "Klingon Warrior"]

    engine = game()
    _lands(engine, "Plains", "Island", "Swamp", "Mountain", "Forest", "Command Tower")  # 6 names
    cast(engine, _praxis(engine))
    assert len([o for o in engine.state.battlefield if o.name == "Klingon Warrior"]) == 2


def test_praxis_rider_not_claimed_when_the_head_can_change_the_count():
    card = _card("Odd", "All creatures get -X/-X until end of turn, where X is the number of creatures you control. If X is 6 or more, create 2 2/1 red Klingon Warrior creature tokens with haste.", "Sorcery")
    assert parse_oracle(card).modeled is False


@pytest.mark.parametrize("names, cost", [
    (("Plains", "Plains"), 5),        # one name: {6} -> {5}
    (("Plains", "Island", "Swamp"), 3),
    (("Plains", "Island", "Swamp", "Mountain", "Forest", "Command Tower", "A", "B"), 0),  # never below zero generic
])
def test_activated_cost_reduction_counts_names_and_floors_at_zero(names, cost):
    engine = game()
    _lands(engine, *names)
    obj = _place(engine, GameObject(_card(
        "Terraformer",
        "{6}: Terraformer gets +2/+2 until end of turn. This ability costs {X} less to activate, where X is the number of differently named lands you control. Activate only once each turn."),
        owner_id="p1", zone=Zone.BATTLEFIELD), "p1", Zone.BATTLEFIELD)
    player = engine.state.player_by_id("p1")
    main_phase(engine)
    player.mana_pool.add_many({"C": 6})
    engine.activate_ability(player, obj, 0)
    # RULE 601.2f / 602.2b: the generic part shrinks by one per name; it never goes below zero
    assert player.mana_pool.total() == 6 - cost


def test_cost_reduction_parse_is_the_shared_selector():
    result = parse_oracle(_card("Practitioner", "{4}{U}, {T}: Tap target creature. This ability costs {X} less to activate, where X is the number of differently named lands you control."))
    assert result.modeled is True
    assert result.specs[0].cost["dynamic_reduction"] == {"count_selector": DIFFERENT_LANDS, "generic_per": 1}


def test_reveal_top_x_puts_permanents_in_and_the_rest_on_the_bottom():
    from tests.support.deck_batch import answer, stack_library

    engine = game()
    _lands(engine, "Plains", "Plains", "Island")  # two names: the top two cards
    lib = [filler(engine, name=f"Perm{i}", type_line="Creature", zone=Zone.LIBRARY, power=1, toughness=1) for i in range(2)]
    lib.append(filler(engine, name="Sorc", type_line="Sorcery", zone=Zone.LIBRARY))
    stack_library(engine, "p1", *lib)  # the sorcery is on top
    spell = _place(engine, GameObject(_card(
        "Timeline", "Reveal the top X cards of your library, where X is the number of differently named lands you control. Put all permanent cards revealed this way onto the battlefield tapped and the rest on the bottom of your library in a random order.",
        "Sorcery"), owner_id="p1", zone=Zone.HAND), "p1", Zone.HAND)
    cast(engine, spell)
    answer(engine)
    assert [(o.name, o.tapped) for o in engine.state.battlefield if o.name.startswith("Perm")] == [("Perm1", True)]
    library = engine.state.player_by_id("p1").library  # the last entry is the top
    assert library[-1].name == "Perm0"  # the third card was never revealed
    assert library[0].name == "Sorc"  # the revealed nonpermanent went to the bottom
