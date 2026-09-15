"""PAR-70: the Mercadian Masques Rebel/Mercenary recruiter tutor chain —
"`<cost>`: search your library for a rebel/mercenary permanent card with
mana value N or less, put it onto the battlefield, then shuffle."
(Ramosian Sergeant/Captain/Commander/Sky Marshal, Cateran Persuader/Brute/
Kidnappers/Enforcer/Slaver/Overlord, Amrou Scout/Blightspeaker/Defiant
Falcon, Bog Glider, Rathi Fiend/Intimidator).

Pure parser recognition — reuses the existing `"search"` `EffectSpec`
(`game/effects/core.py`'s `SearchLibraryEffect`). "Permanent" isn't a
type-line word (no real card's type line literally reads "Permanent"), so
`_SEARCH_CRITERIA`'s new `subtype` group (`_SEARCH_SUBTYPE_WORD`) maps
"a rebel/mercenary permanent card" straight onto `{"type": "rebel"}` /
`{"type": "mercenary"}` alone — Rebel/Mercenary are exclusively creature
subtypes in paper Magic, so no separate "permanent" key is needed.

Reference: mtg_analyzer/parser/oracle/catalogue/handlers.py
(`_SEARCH_CRITERIA`/`_search_criteria_from_match`).
"""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle

from tests.support.game import creature, make_engine


# ---------------------------------------------------------------------------
# PARSER: the widened _SEARCH_CRITERIA subtype qualifier
# ---------------------------------------------------------------------------


def test_rebel_permanent_search_is_recognized():
    (spec,) = match_clause(
        "search your library for a rebel permanent card with mana value 3 or "
        "less, put it onto the battlefield, then shuffle"
    )
    assert spec.type == "search"
    assert spec.params == {
        "criteria": {"type": "rebel", "max_mana_value": 3},
        "destination": "battlefield",
    }


def test_mercenary_permanent_search_is_recognized():
    (spec,) = match_clause(
        "search your library for a mercenary permanent card with mana value 2 "
        "or less, put it onto the battlefield, then shuffle"
    )
    assert spec.type == "search"
    assert spec.params == {
        "criteria": {"type": "mercenary", "max_mana_value": 2},
        "destination": "battlefield",
    }


def test_x_scaled_rebel_search_keeps_the_x_sentinel():
    # Lin Sivvi, Defiant Hero's own recruiter ability: "…with mana value X or
    # less…" — the shared `_SEARCH_MV_QUALIFIER` already carries the "x"
    # sentinel through for every search shape, unaffected by this widening.
    (spec,) = match_clause(
        "search your library for a rebel permanent card with mana value x or "
        "less, put it onto the battlefield, then shuffle"
    )
    assert spec.params["criteria"] == {"type": "rebel", "max_mana_value": "x"}


def test_unsupported_subtype_permanent_search_is_not_claimed():
    # A near-miss: "permanent" paired with a subtype word outside the fixed
    # Rebel/Mercenary enum must stay unclaimed rather than silently matching
    # nothing (fail-closed, not a guess) or falling through to a bare
    # "card" (over-wide) search.
    assert (
        match_clause(
            "search your library for a soldier permanent card with mana value "
            "3 or less, put it onto the battlefield, then shuffle"
        )
        is None
    )


# ---------------------------------------------------------------------------
# ENGINE: end-to-end, a real Ramosian Sergeant-shaped activated ability
# ---------------------------------------------------------------------------


def _recruiter_card():
    return Card(
        id="Test Recruiter", name="Test Recruiter",
        type_line="Creature — Human Rebel", is_creature=True, power=1, toughness=1,
        oracle_text=(
            "{3}, {T}: Search your library for a Rebel permanent card with "
            "mana value 2 or less, put it onto the battlefield, then shuffle."
        ),
    )


def test_recruiter_ability_is_end_to_end_modeled():
    result = parse_oracle(_recruiter_card())
    assert result.modeled, result.unclaimed


def test_recruiter_activated_ability_fetches_a_rebel_onto_the_battlefield():
    card = _recruiter_card()
    target = creature(
        "Rebel Target", cost="{1}{W}", power=1, toughness=1,
        type_line="Creature — Human Rebel",
    )
    off_type = creature(
        "Off-Type Target", cost="{1}{W}", power=1, toughness=1,
        type_line="Creature — Human Soldier",
    )

    eng = make_engine([target, off_type], hand=0)
    p1 = eng.state.active_player
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)

    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"C": 3})
    ability = obj.activated_abilities[0]
    assert eng.can_activate(p1, obj, ability) is True

    eng.activate_ability(p1, obj, 0)
    eng.resolve_until_stable()

    # The Rebel is the only eligible match ("rebel" type + mana value <= 2);
    # the off-type creature stays out of the offered options entirely.
    assert eng.state.pending_choice is not None
    options = eng.state.pending_choice["options"]
    assert {o["label"] for o in options if o["id"] != "decline"} == {"Rebel Target"}

    found = next(o for o in p1.library if o.name == "Rebel Target")
    eng.rules.resolve_choice(found.instance_id)
    eng.resolve_until_stable()

    battlefield_names = {o.name for o in eng.state.battlefield if o.controller_id == "p1"}
    assert "Rebel Target" in battlefield_names
    assert "Off-Type Target" not in battlefield_names
    assert not any(o.name == "Rebel Target" for o in p1.library)
