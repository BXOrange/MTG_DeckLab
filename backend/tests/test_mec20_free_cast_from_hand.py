"""Tests for MEC-20 — RULE 601.2f's "Expertise" cycle: "You may cast a
spell with mana value N or less from your hand without paying its mana
cost."

The missing piece was never the payment mechanism (`GameState.
free_cast_instance_ids` already zeroed a cast's mana cost — RULE 702.88b
Rebound/Beseech the Mirror already used it from *exile*) but the interactive
"which hand card, if any, meets the mana-value cap" choice. Since a hand
card is already a legal cast zone (`can_cast`'s ``in_castable_zone``), the
new ``"grant_free_cast"`` `request_choose_objects` action only *arms* the
picked card's free-cast flag — deliberately not `RulesEngine.
cast_without_paying`, which would cast it immediately with no further
interaction. The caster then casts it (or doesn't) through the ordinary
`legal_actions` cast option, keeping its full targeting/modal choices.

`FreeCastFromHandEffect` covers three real shapes: a literal cap (the five
Expertise sorceries), the caster's own announced {X} (Electrodominance, via
`criteria={"max_mana_value": "x"}` — the same ``"x"`` sentinel
`RulesEngine._substitute_x` already walks for `SearchLibraryEffect`'s
``criteria``), and a board-read cap (Epistolary Librarian's "where X is the
number of attacking creatures", ``max_mana_value_selector``).

Reference: mtg_analyzer/game/effects.py (`FreeCastFromHandEffect`),
mtg_analyzer/game/rules/misc_mixin.py (`CHOOSE_OBJECT_ACTIONS`,
`_apply_chosen_object`'s ``"grant_free_cast"`` branch),
mtg_analyzer/parser/oracle/catalogue/handlers.py (`_free_cast_from_hand`),
mtg_analyzer/game/ability_catalogue.py (Kari Zev's Expertise,
Electrodominance), RULE 601.2f/601.3b.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.spec import EffectSpec


def make_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0,
    )
    eng.begin_turn()
    return eng


def to_hand(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def battlefield(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    bind_from_catalogue(obj)
    return obj


def source_permanent(state, controller="p1"):
    card = Card(id="Some Source", name="Some Source", type_line="Artifact")
    return battlefield(state, card, controller)


def shock():
    return Card(id="Shock", name="Shock", type_line="Instant", mana_cost_string="{R}",
                is_instant=True, converted_mana_cost=1,
                oracle_text="Shock deals 2 damage to any target.")


def counterspell():
    return Card(id="Counterspell", name="Counterspell", type_line="Instant",
                mana_cost_string="{U}{U}", is_instant=True, converted_mana_cost=2,
                oracle_text="Counter target spell.")


def basic_land():
    return Card(id="Island", name="Island", type_line="Basic Land — Island", is_land=True)


# ---------------------------------------------------------------------------
# Parser recognition
# ---------------------------------------------------------------------------


def test_parses_a_literal_cap():
    specs = match_clause("cast a spell with mana value 3 or less from your hand without paying its mana cost")
    assert specs == [EffectSpec("free_cast_from_hand", {"max_mana_value": 3})]


def test_parses_the_you_may_prefixed_form_too():
    specs = match_clause(
        "you may cast a spell with mana value 3 or less from your hand without paying its mana cost"
    )
    assert specs == [EffectSpec("free_cast_from_hand", {"max_mana_value": 3})]


def test_parses_the_x_sentinel():
    specs = match_clause(
        "you may cast a spell with mana value x or less from your hand without paying its mana cost"
    )
    assert specs == [EffectSpec("free_cast_from_hand", {"max_mana_value": "x"})]


def test_parses_the_attacking_creatures_selector():
    specs = match_clause(
        "you may cast a spell with mana value x or less from your hand without paying its mana cost, "
        "where x is the number of attacking creatures"
    )
    assert specs == [
        EffectSpec("free_cast_from_hand", {"max_mana_value_selector": "attacking_creatures"})
    ]


def test_does_not_overmatch_an_unrelated_cast_clause():
    assert match_clause("you may cast target spell without paying its mana cost") is None


def test_sram_and_yahenni_expertise_are_modeled():
    from mtg_analyzer.parser.oracle.gate import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

    if not DEFAULT_DB_PATH.exists():
        import pytest

        pytest.skip("card cache not present in this environment")
    db = CardDatabase(DEFAULT_DB_PATH)
    for name in ("Sram's Expertise", "Yahenni's Expertise", "Epistolary Librarian"):
        card = db.get_card(name)
        if card is None:
            import pytest

            pytest.skip(f"{name!r} not present in the local card cache")
        assert parse_oracle(card).modeled is True, name


# ---------------------------------------------------------------------------
# The engine primitive — literal cap
# ---------------------------------------------------------------------------


def test_offers_only_hand_cards_at_or_under_the_cap():
    eng = make_engine()
    source = source_permanent(eng.state)
    to_hand(eng.state, shock())  # mana value 1
    to_hand(eng.state, counterspell())  # mana value 2
    to_hand(eng.state, basic_land())  # not a spell at all

    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    ctx = GameContext(eng.state, eng.rules)
    FreeCastFromHandEffect(criteria={"max_mana_value": 1}, source=source).apply(ctx)

    choice = eng.state.pending_choice
    assert choice is not None
    assert choice["kind"] == "choose_objects"
    assert choice["action"] == "grant_free_cast"
    offered = {o["label"] for o in choice["options"] if "instance_id" in o}
    assert offered == {"Shock"}


def test_declining_arms_nothing():
    eng = make_engine()
    source = source_permanent(eng.state)
    to_hand(eng.state, shock())
    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    FreeCastFromHandEffect(criteria={"max_mana_value": 1}, source=source).apply(GameContext(eng.state, eng.rules))
    eng.rules.resolve_choose_objects_choice(None)
    assert eng.state.free_cast_instance_ids == set()


def test_picking_a_card_arms_it_for_a_genuinely_free_cast():
    eng = make_engine()
    source = source_permanent(eng.state)
    bolt = to_hand(eng.state, shock())
    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    FreeCastFromHandEffect(criteria={"max_mana_value": 1}, source=source).apply(GameContext(eng.state, eng.rules))
    eng.rules.resolve_choose_objects_choice(bolt.instance_id)

    p1 = eng.state.player_by_id("p1")
    assert eng.can_cast(p1, bolt)  # legal with an empty mana pool
    assert p1.mana_pool.total() == 0

    p2 = eng.state.player_by_id("p2")
    life_before = p2.life
    eng.cast_spell(p1, bolt, targets=[p2])
    eng.resolve_until_stable()
    assert p2.life == life_before - 2
    assert p1.mana_pool.total() == 0  # nothing was ever spent


def test_no_eligible_hand_card_opens_no_choice():
    eng = make_engine()
    source = source_permanent(eng.state)
    to_hand(eng.state, counterspell())  # mana value 2, over the cap
    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    FreeCastFromHandEffect(criteria={"max_mana_value": 1}, source=source).apply(GameContext(eng.state, eng.rules))
    assert eng.state.pending_choice is None


# ---------------------------------------------------------------------------
# The X-scaled and count-selector shapes
# ---------------------------------------------------------------------------


def test_x_sentinel_resolves_against_the_spells_own_announced_x():
    eng = make_engine()
    p1 = eng.state.player_by_id("p1")
    elec = to_hand(
        eng.state,
        Card(id="Electrodominance", name="Electrodominance", type_line="Instant",
             mana_cost_string="{X}{R}{R}", is_instant=True,
             oracle_text=(
                 "Electrodominance deals X damage to any target. You may cast a "
                 "spell with mana value X or less from your hand without paying "
                 "its mana cost."
             )),
    )
    bolt = to_hand(eng.state, shock())
    p1.mana_pool.add("R", 3)

    p2 = eng.state.player_by_id("p2")
    eng.cast_spell(p1, elec, x=1, targets=[p2])
    eng.resolve_until_stable()

    choice = eng.state.pending_choice
    assert choice is not None
    offered = {o["label"] for o in choice["options"] if "instance_id" in o}
    assert offered == {"Shock"}  # mana value 1 <= announced X (1)


def test_attacking_creatures_selector_reads_the_live_board():
    eng = make_engine()
    source = source_permanent(eng.state)
    to_hand(eng.state, shock())
    attacker = battlefield(
        eng.state,
        Card(id="Attacker", name="Attacker", type_line="Creature — Bear",
             is_creature=True, power=2, toughness=2),
    )
    attacker.attacking = True

    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    FreeCastFromHandEffect(
        max_mana_value_selector="attacking_creatures", source=source
    ).apply(GameContext(eng.state, eng.rules))

    choice = eng.state.pending_choice
    assert choice is not None
    offered = {o["label"] for o in choice["options"] if "instance_id" in o}
    assert offered == {"Shock"}  # mana value 1 <= 1 attacking creature


def test_no_attackers_means_no_cap_and_no_choice():
    eng = make_engine()
    source = source_permanent(eng.state)
    to_hand(eng.state, shock())

    from mtg_analyzer.game.effects import FreeCastFromHandEffect, GameContext

    FreeCastFromHandEffect(
        max_mana_value_selector="attacking_creatures", source=source
    ).apply(GameContext(eng.state, eng.rules))
    assert eng.state.pending_choice is None


# ---------------------------------------------------------------------------
# Real card end-to-end
# ---------------------------------------------------------------------------


def test_kari_zevs_expertise_and_electrodominance_are_registered():
    from mtg_analyzer.game.ability_catalogue import is_registered, specs_for

    assert is_registered("Kari Zev's Expertise")
    assert is_registered("Electrodominance")
    kari_specs = specs_for(
        Card(id="Kari Zev's Expertise", name="Kari Zev's Expertise", type_line="Sorcery")
    )
    types = [s.effects[0].type for s in kari_specs]
    assert "gain_control_until_eot" in types
    assert "free_cast_from_hand" in types
