"""PAR-129: a "Keyword — <ability>" line (Exhaust / Power-up / Boast / Max
speed / Solved) whose body the parser can't model must leave the card
UNMODELED, not be claimed as an inert keyword line.

`segmenter._segment_keyword_labeled_ability` used to fall back, for a
comma-free ``<keyword> — <body>`` line, to `is_keyword_line`'s greedy
`_KEYWORD_TOKEN_RE` — the card went MODELED with the whole labelled ability
silently missing (23 cards; Mai, Liliana the Repentant, Captain Marvel, …).

Also covers the mana-ability sibling: "Exhaust — {G}, {T}: Add three mana of
any one color." (Loot, the Pathfinder) kept no once-per-game cap
(RULE 702.177a) — `ActivationCost.once_per_game`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_abilities_for, parse_mana_abilities
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import segment_line
from mtg_analyzer.parser.oracle.spec import ParserProvenance

PROVENANCE = ParserProvenance(version="test", source="test")


def _creature(name, text, keywords=()):
    return Card(
        id=name, name=name, type_line="Creature — Human", is_creature=True,
        power=2, toughness=2, oracle_text=text, keywords=list(keywords),
    )


# A body no handler models (an age counter is read by name — cumulative upkeep — so it has no
# generic `add_counters` row; PAR-135 opened the named-counter kinds that stun/feather etc. now use).
UNMODELED_BODIES = [
    ("Exhaust", "Exhaust — {3}: Put an age counter on Mai."),
    ("Power-up", "Power-up — {5}{W}{W}: Put a +1/+1 counter and an age counter on Mai."),
    ("Boast", "Boast — {1}: Put an age counter on another target creature."),
    ("Max speed", "Max speed — Mai has deathtouch. Put an age counter on each creature you control."),
]


@pytest.mark.parametrize("keyword,line", UNMODELED_BODIES)
def test_unparseable_labelled_body_is_not_claimed_as_an_inert_keyword_line(keyword, line):
    seg = segment_line(normalize(line, "Mai"), allow_spell_effect=False, provenance=PROVENANCE)
    assert not seg.claimed
    assert not seg.keyword_line


@pytest.mark.parametrize("keyword,line", UNMODELED_BODIES)
def test_card_with_an_unparseable_labelled_ability_is_unmodeled(keyword, line):
    result = parse_oracle(_creature("Mai", f"Prowess\n{line}", keywords=[keyword]))
    assert result.coverage is not MODELED
    assert any(keyword.lower() in clause.lower() for clause in result.unclaimed)


def test_a_parseable_exhaust_body_is_still_modeled_with_its_ability_and_cap():
    result = parse_oracle(_creature(
        "Test Exhauster", "Exhaust — {2}{G}: Put two +1/+1 counters on this creature.",
        keywords=["Exhaust"]))
    assert result.coverage is MODELED
    (spec,) = [s for s in result.effect_specs if s.ability_kind == "activated"]
    assert "activate_only_once_marker" in {e.type for e in spec.effects}


def test_one_unparseable_exhaust_line_does_not_hide_behind_its_parseable_siblings():
    # Audacious Knuckleblade's shape: three Exhaust lines, one unmodeled.
    result = parse_oracle(_creature(
        "Triple", "Exhaust — {R}: Creatures you control gain haste until end of turn.\n"
        "Exhaust — {G}: Put an age counter on this creature.",
        keywords=["Exhaust"]))
    assert result.coverage is not MODELED


# ---------------------------------------------------------------------------
# Exhaust mana ability: once per game (RULE 702.177a)
# ---------------------------------------------------------------------------

LOOT = Card(
    id="Loot", name="Loot, the Pathfinder", type_line="Legendary Creature — Dinosaur",
    is_creature=True, power=3, toughness=3, is_legendary=True,
    oracle_text=(
        "Double strike, vigilance, haste\n"
        "Exhaust — {G}, {T}: Add three mana of any one color. (Activate each exhaust ability only once.)"
    ),
)


def _loot_on_battlefield(eng):
    obj = GameObject(LOOT, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def test_exhaust_mana_ability_is_flagged_once_per_game():
    [ability] = parse_mana_abilities(LOOT)
    assert ability.cost.once_per_game is True
    assert ability.cost.once_per_turn is False
    assert ability.options == [{c: 3} for c in "WUBRG"]


def test_unlabelled_mana_ability_has_no_game_cap():
    card = Card(id="Elf", name="Llanowar Elves", type_line="Creature — Elf Druid",
                is_creature=True, power=1, toughness=1, oracle_text="{T}: Add {G}.")
    [ability] = parse_mana_abilities(card)
    assert ability.cost.once_per_game is False


def test_exhaust_mana_ability_can_be_used_once_then_never_again():
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    loot = _loot_on_battlefield(eng)
    p1.mana_pool.add("G", 1)
    assert mana_abilities_for(loot, state=eng.state)[0].options

    eng.tap_for_mana(p1, loot, option_index=0, ability_index=0)
    assert p1.mana_pool.total() >= 3

    # Spent: nothing offers it again, this turn or any later one.
    assert mana_abilities_for(loot, state=eng.state)[0].options == []
    loot.tapped = False
    p1.mana_pool.add("G", 1)
    with pytest.raises(ValueError):
        eng.tap_for_mana(p1, loot, option_index=0, ability_index=0)
    eng.begin_turn()
    loot.tapped = False
    assert mana_abilities_for(loot, state=eng.state)[0].options == []


def test_a_new_object_gets_a_fresh_exhaust_cap():
    # RULE 400.7: a permanent that left and came back is a new object.
    eng = GameEngine.new_game([("p1", "p1", []), ("p2", "p2", [])], starting_life=20, starting_hand=0)
    loot = _loot_on_battlefield(eng)
    loot.mana_abilities_used_this_game.add(0)
    loot.used_once_per_game_abilities.add("exhaust")
    loot.reset_as_new_object()
    assert mana_abilities_for(loot, state=eng.state)[0].options
    assert not loot.used_once_per_game_abilities
