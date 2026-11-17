"""PAR-284 milestone 12: colors of a referent (RULE 105.1) and player-scoped counts (RULE 102.2, 506.2, 903.3).

Pinned: the phrase readers and their antecedent guards, the commander cost reduction and the Cornucopia head, and real
resolutions through the engine (a pump sized by a target's colors, life from a destroyed permanent's colors, a cast
trigger reading the spell's colors, tokens per opponent, draws per attacked player).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading, STANDALONE
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter.overrides_and_amounts import count_amount, referent_colors_amount

SELF = ClauseReading(self_subject=True)


def _card(name, type_line, oracle, cost="{3}", mv=3, colors=None, **kw):
    kw.setdefault("is_instant", type_line.startswith("Instant"))
    kw.setdefault("is_sorcery", type_line.startswith("Sorcery"))
    kw.setdefault("is_creature", "Creature" in type_line)
    if colors is not None:
        kw["colors"] = colors
    return Card(id=name, name=name, type_line=type_line, mana_cost_string=cost, converted_mana_cost=mv,
                oracle_text=oracle, **kw)


def _engine(players=2):
    eng = GameEngine.new_game([(f"p{i + 1}", f"P{i + 1}", []) for i in range(players)], starting_life=20, starting_hand=0)
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


def _battlefield(eng, card, owner="p1"):
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    attach_to_object(obj, result.specs)
    eng.state.battlefield.append(obj)
    return obj


# -- parse ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, expected", [
    ("the number of colors that spell is", {"kind": "color_count", "of": "trigger_spell"}),
    ("of that spell's colors", {"kind": "color_count", "of": "trigger_spell"}),
    ("the number of colors of that commander", {"kind": "color_count", "of": "trigger_spell"}),
])
def test_cast_spell_colors_read_the_event_spell(phrase, expected):
    assert referent_colors_amount(phrase, reading=SELF) == expected


@pytest.mark.parametrize("phrase, reading", [
    ("of its colors", STANDALONE),  # no antecedent
    ("of that spell's colors", STANDALONE),  # no cast head
    ("the number of colors among creatures you control", SELF),  # a distinct-value pool, not a referent
])
def test_unanchored_colors_stay_unread(phrase, reading):
    assert referent_colors_amount(phrase, reading=reading) is None


@pytest.mark.parametrize("phrase, expected", [
    ("opponent you have", {"kind": "player_count", "scope": "each_opponent"}),
    ("the number of opponents you have", {"kind": "player_count", "scope": "each_opponent"}),
    ("player being attacked", {"kind": "count_selector", "selector": "players_being_attacked"}),
    ("the number of players being attacked", {"kind": "count_selector", "selector": "players_being_attacked"}),
])
def test_player_scoped_counts(phrase, expected):
    assert count_amount(phrase) == expected


@pytest.mark.parametrize("name, type_line, oracle", [
    ("Breathe Probe", "Instant", "Destroy target creature or planeswalker. You gain 1 life for each of its colors."),
    ("Might Probe", "Instant", "Target creature gets +2/+2 until end of turn for each of its colors."),
    ("Crystal Probe", "Creature — Human", "Whenever you cast a noncreature spell, ~ deals X damage to each opponent, where X is the number of colors that spell is."),
    ("Familiar Probe", "Creature — Construct", "Commander spells you cast cost {1} less to cast.\nWhenever you cast a commander spell, create X 1/1 Stained Glass artifact creature tokens that are all colors, where X is the number of colors of that commander."),
    ("Cornucopia Probe", "Artifact", "Whenever you cast a spell that's one or more colors, you may gain 1 life for each of that spell's colors. Do this only once each turn."),
    ("Company Probe", "Creature — Human", "When this creature enters, create a number of 1/1 white Soldier creature tokens equal to the number of opponents you have."),
    ("White Probe", "Creature — Human", "Whenever you attack, you create a Food token for each player being attacked."),
])
def test_cards_are_modeled(name, type_line, oracle):
    assert parse_oracle(_card(name, type_line, oracle)).modeled


def test_its_colors_without_a_referent_is_unclaimed():
    # a spell with no earlier clause: "its" names nothing the colors could be read from
    assert not parse_oracle(_card("Loose Probe", "Sorcery", "You gain 1 life for each of its colors.")).modeled


def test_commander_cost_reduction_spec():
    result = parse_oracle(_card("Familiar Probe", "Creature — Construct", "Commander spells you cast cost {1} less to cast."))
    assert [s.effects[0].params for s in result.specs] == [{"generic": 1, "increase": False, "spell_is_commander": True}]


# -- engine --------------------------------------------------------------------------------------------------------


def _cast(eng, obj, mana, targets=None):
    p1 = eng.state.players[0]
    for color, amount in mana.items():
        p1.mana_pool.add(color, amount)
    eng.cast_spell(p1, obj, targets=targets)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()


def test_pump_is_sized_by_the_targets_colors():
    eng = _engine()
    target = _battlefield(eng, _card("Bear", "Creature — Bear", "", cost="{W}{U}", mv=2, power=2, toughness=2))
    spell = _hand(eng, _card("Might Probe", "Instant", "Target creature gets +2/+2 until end of turn for each of its colors.",
                             cost="{G}", mv=1))
    _cast(eng, spell, {"G": 1}, targets=[target])
    assert (target.power, target.toughness) == (6, 6)


def test_colorless_target_gets_nothing():
    eng = _engine()
    target = _battlefield(eng, _card("Golem", "Artifact Creature — Golem", "", cost="{3}", mv=3, power=2, toughness=2))
    spell = _hand(eng, _card("Might Probe", "Instant", "Target creature gets +2/+2 until end of turn for each of its colors.",
                             cost="{G}", mv=1))
    _cast(eng, spell, {"G": 1}, targets=[target])
    assert (target.power, target.toughness) == (2, 2)


def test_destroyed_permanents_colors_gain_life():
    eng = _engine()
    target = _battlefield(eng, _card("Bear", "Creature — Bear", "", cost="{R}{G}", mv=2, power=2, toughness=2), owner="p2")
    spell = _hand(eng, _card("Breathe Probe", "Instant",
                             "Destroy target creature or planeswalker. You gain 1 life for each of its colors.",
                             cost="{B}", mv=1))
    _cast(eng, spell, {"B": 1}, targets=[target])
    assert target not in eng.state.battlefield
    assert eng.state.players[0].life == 22


def test_cast_trigger_reads_the_spells_colors():
    eng = _engine()
    _battlefield(eng, _card("Crystal Probe", "Creature — Human",
                            "Whenever you cast a noncreature spell, ~ deals X damage to each opponent, where X is the "
                            "number of colors that spell is.", cost="{1}", mv=1, power=1, toughness=1))
    spell = _hand(eng, _card("Gold Spell", "Sorcery", "You gain 1 life.", cost="{W}{U}", mv=2))
    _cast(eng, spell, {"W": 1, "U": 1})
    assert eng.state.players[1].life == 18


def test_a_colorless_spell_deals_nothing():
    eng = _engine()
    _battlefield(eng, _card("Crystal Probe", "Creature — Human",
                            "Whenever you cast a noncreature spell, ~ deals X damage to each opponent, where X is the "
                            "number of colors that spell is.", cost="{1}", mv=1, power=1, toughness=1))
    spell = _hand(eng, _card("Plain Spell", "Sorcery", "You gain 1 life.", cost="{2}", mv=2))
    _cast(eng, spell, {"C": 2})
    assert eng.state.players[1].life == 20


def test_commander_spells_cost_one_less():
    eng = _engine()
    _battlefield(eng, _card("Familiar Probe", "Creature — Construct", "Commander spells you cast cost {1} less to cast.",
                            cost="{3}", mv=3, power=1, toughness=1))
    commander = _hand(eng, _card("Cmdr", "Creature — Bear", "", cost="{1}{G}", mv=2, power=2, toughness=2))
    commander.is_commander = True
    ordinary = _hand(eng, _card("Plain Bear", "Creature — Bear", "", cost="{1}{G}", mv=2, power=2, toughness=2))
    p1 = eng.state.players[0]
    p1.mana_pool.add("G", 1)
    eng.cast_spell(p1, commander)
    eng.resolve_until_stable()
    assert commander.zone == Zone.BATTLEFIELD
    p1.mana_pool.add("G", 1)
    with pytest.raises(Exception):
        eng.cast_spell(p1, ordinary)


def test_tokens_per_opponent_in_a_multiplayer_game():
    eng = _engine(players=3)
    creature = _hand(eng, _card(
        "Company Probe", "Creature — Human",
        "When this creature enters, create a number of 1/1 white Soldier creature tokens equal to the number of opponents you have.",
        cost="{2}", mv=2, power=1, toughness=1))
    _cast(eng, creature, {"C": 2})
    assert len([o for o in eng.state.battlefield if o.name == "Soldier"]) == 2


def test_players_being_attacked_counts_distinct_defenders():
    from mtg_analyzer.game.continuous import count_selector

    eng = _engine(players=3)
    a = _battlefield(eng, _card("A", "Creature — Bear", "", power=1, toughness=1))
    b = _battlefield(eng, _card("B", "Creature — Bear", "", power=1, toughness=1))
    c = _battlefield(eng, _card("C", "Creature — Bear", "", power=1, toughness=1))
    for obj, defender in ((a, "p2"), (b, "p2"), (c, "p3")):
        obj.attacking = True
        obj.combat_defender = {"kind": "player", "id": defender}
    assert count_selector(eng.state, "p1", "players_being_attacked") == 2
    c.attacking = False
    assert count_selector(eng.state, "p1", "players_being_attacked") == 1
