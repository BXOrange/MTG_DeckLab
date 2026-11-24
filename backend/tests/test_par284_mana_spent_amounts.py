"""PAR-284 milestone 11: amounts measured from the mana spent to cast a spell (RULE 601.2h, 702.108a, 106.4).

The engine already records, on the cast object, the total mana paid, the colors, the snow share and the Treasure share
(`GameObject.mana_spent_to_cast*`, stamped by `RulesEngine.cast_spell`; they survive the move onto the battlefield and
reset on the next zone change, RULE 400.7), and the cast event carries the total and the color list (RULE 601.2i).
Pinned here: the wordings that read those records, the antecedent guards, and real casts through the engine.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading, STANDALONE
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter.overrides_and_amounts import spent_to_cast_amount

SELF = ClauseReading(self_subject=True)


def _card(name, type_line, oracle, cost="{3}", mv=3, **kw):
    kw.setdefault("is_instant", type_line.startswith("Instant"))
    kw.setdefault("is_sorcery", type_line.startswith("Sorcery"))
    kw.setdefault("is_creature", "Creature" in type_line)
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=mv,
                oracle_text=oracle, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _hand(eng, card):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    eng.state.players[0].hand.append(obj)
    return obj


def _cast(eng, obj, mana, *, source_kind=None):
    p1 = eng.state.players[0]
    for color, amount in mana.items():
        p1.mana_pool.add(color, amount, source_kind=source_kind)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()


def _tokens(eng, name):
    return [o for o in eng.state.battlefield if o.name == name]


# -- parse ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, reading, expected", [
    ("the amount of mana spent to cast it", SELF, {"kind": "count_selector", "selector": "mana_spent_to_cast"}),
    ("the number of colors of mana spent to cast this spell", STANDALONE,
     {"kind": "count_selector", "selector": "converge"}),
    ("color of mana spent to cast it", SELF, {"kind": "count_selector", "selector": "converge"}),
    ("mana from a treasure that was spent to cast this spell", STANDALONE,
     {"kind": "count_selector", "selector": "treasure_mana_spent_to_cast"}),
    ("the amount of {s} spent to cast this spell", STANDALONE,
     {"kind": "count_selector", "selector": "snow_mana_spent_to_cast"}),
    ("the amount of mana spent to cast that spell", STANDALONE, {"kind": "trigger_event", "field": "mana_spent"}),
    ("color of mana spent to cast that spell", STANDALONE, {"kind": "trigger_event", "field": "colors_spent"}),
])
def test_spent_phrases_read_the_recorded_amount(phrase, reading, expected):
    assert spent_to_cast_amount(phrase, reading=reading) == expected


@pytest.mark.parametrize("phrase, reading", [
    ("the amount of mana spent to cast it", STANDALONE),  # "it" has no antecedent
    ("mana from a treasure spent to cast that spell", STANDALONE),  # the cast event does not carry the source split
    ("mana from a cave spent to cast that spell", STANDALONE),
    ("mana from a forest spent to cast this spell", STANDALONE),
])
def test_unrecorded_or_unanchored_phrases_stay_unread(phrase, reading):
    assert spent_to_cast_amount(phrase, reading=reading) is None


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Sweep Probe", "Sorcery", "Create a 1/1 colorless Thopter artifact creature token with flying for each color of mana spent to cast this spell."),
    ("Prossh Probe", "Creature — Kobold", "When you cast this spell, create X 0/1 red Kobold creature tokens named Kobolds of Kher Keep, where X is the amount of mana spent to cast it."),
    ("Marut Probe", "Artifact Creature — Golem", "When this creature enters, if mana from a Treasure was spent to cast it, create a Treasure token for each mana from a Treasure spent to cast it."),
    ("Wurm Probe", "Creature — Wurm", "Whenever you cast an instant or sorcery spell, this creature gets +X/+0 until end of turn, where X is the amount of mana spent to cast that spell."),
    ("Archaic Probe", "Creature — Dragon", "Whenever you cast an instant or sorcery spell, creatures you control get +1/+0 until end of turn for each color of mana spent to cast that spell."),
    ("Lore Probe", "Sorcery", "Scry X, where X is the amount of {S} spent to cast this spell, then draw three cards."),
    ("Fumarole Probe", "Instant", "Fumarole Probe deals 4 damage to target creature or planeswalker. Add {C} for each {S} spent to cast this spell. Until end of turn, you don't lose this mana as steps and phases end."),
    ("Note Probe", "Sorcery", "Note Probe deals damage to target creature equal to the amount of mana spent to cast this spell. Untap all creatures you control."),
    ("Deluge Probe", "Sorcery", "Look at the top X cards of your library, where X is the amount of mana spent to cast this spell. Put two of them into your hand and the rest on the bottom of your library in a random order."),
    ("Shantotto Probe", "Creature — Wizard", "Whenever you cast a noncreature spell, this creature gets +X/+0 until end of turn, where X is the amount of mana spent to cast that spell. If X is 4 or more, draw a card."),
])
def test_spent_amount_cards_are_modeled(name, type_line, oracle):
    assert parse_oracle(_card(name, type_line, oracle)).modeled


def test_that_spell_is_only_read_under_a_cast_trigger():
    # an activated ability's "that spell" has no cast event to read
    assert not parse_oracle(_card(
        "Activated Probe", "Artifact",
        "{T}: This artifact deals X damage to each opponent, where X is the amount of mana spent to cast that spell.",
    )).modeled


# -- engine --------------------------------------------------------------------------------------------------------


def test_converge_tokens_count_the_colors_actually_spent():
    eng = _engine()
    spell = _hand(eng, _card("Unified Probe", "Sorcery",
                             "Create a 1/1 white Kor Ally creature token for each color of mana spent to cast this spell."))
    _cast(eng, spell, {"W": 1, "U": 1, "G": 1})
    assert len(_tokens(eng, "Kor Ally")) == 3


def test_a_one_color_payment_makes_one_token():
    eng = _engine()
    spell = _hand(eng, _card("Unified Probe", "Sorcery",
                             "Create a 1/1 white Kor Ally creature token for each color of mana spent to cast this spell."))
    _cast(eng, spell, {"W": 3})
    assert len(_tokens(eng, "Kor Ally")) == 1


def test_cast_trigger_reads_the_total_mana_paid_for_its_own_spell():
    """Prossh: the trigger resolves above the spell, which is still on the stack with its payment recorded."""
    eng = _engine()
    creature = _hand(eng, _card(
        "Prossh Probe", "Creature — Kobold",
        "When you cast this spell, create X 0/1 red Kobold creature tokens named Kobolds of Kher Keep, where X is the "
        "amount of mana spent to cast it.", cost="{4}", mv=4, power=5, toughness=5))
    _cast(eng, creature, {"R": 2, "C": 2})
    assert len(_tokens(eng, "Kobolds Of Kher Keep")) == 4


def test_treasure_mana_tokens_count_only_the_treasure_share():
    eng = _engine()
    p1 = eng.state.players[0]
    golem = _hand(eng, _card(
        "Marut Probe", "Artifact Creature — Golem",
        "When this creature enters, if mana from a Treasure was spent to cast it, create a Treasure token for each mana "
        "from a Treasure spent to cast it.", cost="{3}", mv=3, power=3, toughness=3))
    p1.mana_pool.add("B", 2, source_kind="treasure")
    p1.mana_pool.add("B", 1)
    eng.cast_spell(p1, golem)
    eng.resolve_until_stable()
    assert len(_tokens(eng, "Treasure")) == 2


def test_cast_event_amount_pumps_the_wurm_by_the_spell_cast():
    eng = _engine()
    p1 = eng.state.players[0]
    wurm = GameObject(_card("Wurm Probe", "Creature — Wurm",
                            "Whenever you cast an instant or sorcery spell, this creature gets +X/+0 until end of turn, "
                            "where X is the amount of mana spent to cast that spell.", power=2, toughness=2),
                      owner_id="p1", zone=Zone.BATTLEFIELD)
    wurm.controller_id = "p1"
    wurm.summoning_sick = False
    attach_to_object(wurm, parse_oracle(wurm.card).specs)
    eng.state.add_to_battlefield(wurm)
    spell = _hand(eng, _card("Bolt Probe", "Instant", "You gain 1 life.", cost="{2}{R}", mv=3))
    _cast(eng, spell, {"R": 1, "C": 2})
    eng.recompute_continuous_effects()
    assert wurm.power == 2 + 3


def test_cast_event_colors_scale_a_team_pump():
    eng = _engine()
    p1 = eng.state.players[0]
    archaic = GameObject(_card("Archaic Probe", "Creature — Dragon",
                               "Whenever you cast an instant or sorcery spell, creatures you control get +1/+0 until end "
                               "of turn for each color of mana spent to cast that spell.", power=1, toughness=1),
                         owner_id="p1", zone=Zone.BATTLEFIELD)
    archaic.controller_id = "p1"
    archaic.summoning_sick = False
    attach_to_object(archaic, parse_oracle(archaic.card).specs)
    eng.state.add_to_battlefield(archaic)
    spell = _hand(eng, _card("Bolt Probe", "Instant", "You gain 1 life.", cost="{2}{R}", mv=3))
    _cast(eng, spell, {"R": 1, "G": 1, "W": 1})
    eng.recompute_continuous_effects()
    assert archaic.power == 1 + 3


def test_snow_mana_adds_that_much_mana_that_is_kept():
    eng = _engine()
    p1 = eng.state.players[0]
    spell = _hand(eng, _card("Fumarole Probe", "Instant",
                             "Fumarole Probe deals 4 damage to target creature or planeswalker. Add {C} for each {S} spent to "
                             "cast this spell. Until end of turn, you don't lose this mana as steps and phases end.",
                             cost="{3}", mv=3))
    victim = GameObject(_card("Victim", "Creature — Bear", "", is_creature=True, power=2, toughness=2),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.add_to_battlefield(victim)
    p1.mana_pool.add("C", 3, is_snow=True)
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert spell.mana_spent_to_cast_snow == 3
    # RULE 106.4: the three {C} added stay in the pool through the end of turn, past the end of the main phase
    assert p1.mana_pool.pool["C"] == 3
    assert p1.mana_pool.kept.get("end_of_turn", {}).get("C") == 3
    assert victim not in eng.state.battlefield


def test_damage_equal_to_the_mana_spent_on_the_spell():
    eng = _engine()
    p1 = eng.state.players[0]
    spell = _hand(eng, _card("Note Probe", "Sorcery",
                             "Note Probe deals damage to target creature equal to the amount of mana spent to cast this "
                             "spell.", cost="{R}{R}{R}{R}", mv=4))
    victim = GameObject(_card("Victim", "Creature — Bear", "", is_creature=True, power=9, toughness=4),
                        owner_id="p2", zone=Zone.BATTLEFIELD)
    victim.controller_id = "p2"
    eng.state.add_to_battlefield(victim)
    p1.mana_pool.add("R", 4)
    eng.cast_spell(p1, spell, targets=[victim])
    eng.resolve_until_stable()
    assert victim not in eng.state.battlefield


def _land_mana(eng, type_line, color):
    player = eng.state.players[0]
    card = _card(type_line, type_line, f"{{T}}: Add {{{color}}}.", cost="", mv=0, is_land=True)
    land = GameObject(card, owner_id=player.id, zone=Zone.BATTLEFIELD)
    eng.state.battlefield.append(land)
    eng.tap_for_mana(player, land)
    return land


@pytest.mark.parametrize("use_caves", [True, False])
def test_bat_colony_reads_its_payment_after_entering(use_caves):
    eng = _engine()
    spell = _hand(eng, _card(
        "Bat Colony", "Enchantment",
        "When this enchantment enters, create a 1/1 black Bat creature token with flying for each mana from a Cave spent to cast it.\n"
        "Whenever a Cave you control enters, put a +1/+1 counter on target creature you control.",
        cost="{2}{W}",
    ))
    player = eng.state.players[0]
    land_type = "Land — Cave" if use_caves else "Land — Desert"
    _land_mana(eng, land_type, "W")
    _land_mana(eng, land_type, "C")
    player.mana_pool.add("C")
    _cast(eng, spell, {})
    assert len(_tokens(eng, "Bat")) == (2 if use_caves else 0)
    assert spell.mana_spent_to_cast_by_source_subtype == ({"cave": 2} if use_caves else {"desert": 2})
    eng.rules.destroy(spell)
    eng.rules.return_from_graveyard(spell)
    eng.resolve_until_stable()
    assert spell.mana_spent_to_cast_by_source_subtype == {}
    assert len(_tokens(eng, "Bat")) == (2 if use_caves else 0)


def test_cataclysmic_prospecting_counts_desert_mana_from_the_total_cost():
    eng = _engine()
    spell = _hand(eng, _card(
        "Cataclysmic Prospecting", "Sorcery",
        "Cataclysmic Prospecting deals X damage to each creature. "
        "For each mana from a Desert spent to cast this spell, create a tapped Treasure token.",
        cost="{X}{R}{R}", mv=2,
    ))
    player = eng.state.players[0]
    _land_mana(eng, "Land — Desert", "R")
    _land_mana(eng, "Land — Cave Desert", "C")
    _land_mana(eng, "Land — Cave", "R")
    _land_mana(eng, "Land — Desert", "G")  # Floated but not spent.
    eng.cast_spell(player, spell, x=1)
    assert spell.mana_spent_to_cast_by_source_subtype == {"desert": 2, "cave": 2}
    eng.resolve_until_stable()
    treasures = _tokens(eng, "Treasure")
    assert len(treasures) == 2
    assert all(token.tapped for token in treasures)
    assert player.mana_pool.pool["G"] == 1


def test_restricted_land_mana_keeps_its_provenance_when_cloned_and_paid():
    from mtg_analyzer.models.mana.mana_cost import ManaCost
    from mtg_analyzer.models.mana.mana_pool import ManaPool

    original = ManaPool()
    original.add("C", source_subtypes=("cave",), restriction={"kind": "creature_spell"})
    original.add("C", source_subtypes=("desert",))
    trial = original.clone()
    cost = ManaCost.parse("{1}")
    trial.pay(cost, allows_restriction=lambda restriction: True)
    assert trial.last_payment_by_source_subtype == {"cave": 1}
    trial.pay(cost)
    assert trial.last_payment_by_source_subtype == {"desert": 1}
    assert original.total() == 2
