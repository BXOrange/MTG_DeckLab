"""cEDH staples cube — batch A2: static/continuous-effect parser+engine coverage.

Reference: CLAUDE.md's oracle-text-parser pipeline; docs/concepts/
09_ORACLE_EFFECT_PARSER.md; docs/Reference/11_CARD_CATALOGUE_AUTHORING_GUIDE.md
§6 (static-layer EffectSpec whitelist). This batch extended
`parser/oracle/catalogue/static_handlers.py` with six new *generic,
type-filter-parameterized* static-clause families (not hardcoded to any one
card name) and `game/continuous.py`/`game/game_engine.py`/
`game/rules_engine.py` with the matching consult points RULE 613's ordinary
layer engine doesn't cover on its own:

1. "Activated abilities of <type> can't be activated." — a global
   prohibition consulted by `GameEngine.can_activate`
   (`continuous.activation_prohibited`).
2. "<Type> spells cost {N} more/less to cast." — extends the existing
   `cost_reduction` static with an `affects="all_spells"` (unscoped by
   ownership) shape and a `spell_type` filter
   (`continuous.cost_reduction_for`'s new ``obj`` parameter).
3. "Each player can't cast more than N spells each turn." — a flat,
   per-turn cap read off `GameState.spells_cast_this_turn`
   (`continuous.max_spells_per_turn`, `GameEngine.can_cast`).
4. "This <type> doesn't untap during your untap step." — a self-scoped
   restriction consulted by `GameEngine._step_untap`
   (`continuous.has_no_untap_static`).
5. "Creatures entering don't cause abilities to trigger." — a global
   trigger-collection gate (`continuous.trigger_suppressed`,
   `RulesEngine._collect_triggers`).
6. "[Nonbasic] <type> your opponents control enter tapped." — a board-wide
   RULE 614.1 effect, distinct from `ability_catalogue.enters_tapped`
   (`continuous.enters_tapped_from_static`, consulted by both
   `RulesEngine._resolve_permanent_spell`/token creation *and*
   `enter_land_tapped`, since a land normally enters via the separate
   `play_land` special-action path, not spell resolution).

Plus one RULE 613.5 layer-4 *full type overwrite* ("Nonbasic lands are
Mountains.", item 7 — `type_change`'s new `set_subtypes` param,
`GameObject._derived_subtypes`, `continuous._has_subtype`) and one no-op
deck-legality claim (item 8 — "~ can be your commander.", RULE 903.3,
claimed at `gate._process_line` with no `EffectSpec` at all, the same split
RULE 614.1 tapped-entry/entry-counter clauses already get).

Every test uses the real cached card (not a hand-built fixture) for the
`parse_oracle` assertion; a hand-built fixture is used only for the *other*
side of a static effect (an artifact with a plain activated ability, a
creature with a plain ETB trigger, …) since the point is to prove the new
*generic* mechanism, not re-test an unrelated card's own parsing.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import ActivatedAbility
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.mana_abilities import mana_options_for
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH

pytestmark = pytest.mark.skipif(
    not DEFAULT_DB_PATH.exists(), reason="card cache not present in this environment"
)


def _card(name: str) -> Card:
    db = CardDatabase(DEFAULT_DB_PATH)
    card = db.get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not present in the local card cache")
    return card


def _battlefield(state, card: Card, controller: str = "p1") -> GameObject:
    """A card bound + added to ``state.battlefield`` (bind-on-load, mirroring
    `services.game_session.build_goldfish_engine`)."""
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _engine(p1_cards=(), p2_cards=()) -> GameEngine:
    eng = GameEngine.new_game(
        [("p1", "Alice", list(p1_cards)), ("p2", "Bob", list(p2_cards))],
        starting_life=40,
        starting_hand=len(p1_cards) or 0,
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


# ---------------------------------------------------------------------------
# Item 1: "Activated abilities of <type> can't be activated." (RULE 602)
# ---------------------------------------------------------------------------


def test_null_rod_family_modeled():
    for name in ("Collector Ouphe", "Stony Silence", "Null Rod"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_null_rod_prohibits_a_different_artifacts_activated_ability():
    """Null Rod carries no self-exemption in its printed text — the
    prohibition is global (`affects="all_permanents"`, `card_type=
    "artifact"`), so it silences *any* qualifying permanent's activated
    abilities, including one its own controller controls, not just an
    opponent's."""
    rock = Card(
        id="Test Rock", name="Test Rock", type_line="Artifact",
        oracle_text="{T}: Draw a card.",
    )
    eng = _engine()
    state = eng.state
    p1 = state.active_player
    rock_obj = _battlefield(state, rock, controller="p1")
    assert len(rock_obj.activated_abilities) == 1
    ability = rock_obj.activated_abilities[0]
    assert isinstance(ability, ActivatedAbility)
    assert eng.can_activate(p1, rock_obj, ability)

    null_rod = _battlefield(state, _card("Null Rod"), controller="p2")
    assert not eng.can_activate(p1, rock_obj, ability)

    state.remove_from_battlefield(null_rod)
    assert eng.can_activate(p1, rock_obj, ability)


# ---------------------------------------------------------------------------
# Item 2: "<Type> spells cost {N} more/less to cast." (RULE 601.2f)
# ---------------------------------------------------------------------------


def test_thalia_family_modeled():
    for name in ("Thalia, Guardian of Thraben", "Thorn of Amethyst", "Vryn Wingmare"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_thalia_taxes_noncreature_spells_for_every_player_including_her_own():
    shock = Card(
        id="Shock", name="Shock", type_line="Instant", mana_cost_string="{R}",
        converted_mana_cost=1, is_instant=True, oracle_text="Shock deals 2 damage to any target.",
    )
    bear = Card(
        id="Bear", name="Bear", type_line="Creature — Bear", mana_cost_string="{1}{G}",
        converted_mana_cost=2, is_creature=True, power=2, toughness=2,
    )
    eng = _engine(p1_cards=[shock, bear], p2_cards=[shock])
    state = eng.state
    p1 = state.active_player
    p2 = state.players[1]
    _battlefield(state, _card("Thalia, Guardian of Thraben"), controller="p1")

    shock_obj = next(o for o in p1.hand if o.name == "Shock")
    bear_obj = next(o for o in p1.hand if o.name == "Bear")
    # Thalia's own controller's noncreature spell is taxed too (no self-exemption).
    assert eng.effective_cast_cost(p1, shock_obj).raw == "{1}{R}"
    # A creature spell is untouched.
    assert eng.effective_cast_cost(p1, bear_obj).raw == "{1}{G}"
    # An opponent's noncreature spell is taxed the same way.
    p2_shock = p2.hand[0]
    assert eng.effective_cast_cost(p2, p2_shock).raw == "{1}{R}"


# ---------------------------------------------------------------------------
# Item 3: "Each player can't cast more than N spells each turn." (RULE 601-area)
# ---------------------------------------------------------------------------


def test_rule_of_law_family_modeled():
    for name in ("Eidolon of Rhetoric", "Rule of Law"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_archon_of_emeria_cast_limit_line_claimed_enters_tapped_line_claimed():
    """Archon of Emeria's own two lines (the cast limit + the opponent-scoped
    "Nonbasic lands … enter tapped.") are both claimed by this batch's new
    handlers; the card is fully `MODELED` (unlike Rule of Law's siblings
    above, it has no *third*, unrelated unmodeled clause)."""
    result = parse_oracle(_card("Archon of Emeria"))
    assert result.modeled, result.unclaimed


def test_eidolon_of_rhetoric_limits_each_player_to_one_spell_per_turn():
    bolt1 = Card(
        id="Bolt1", name="Bolt1", type_line="Instant", mana_cost_string="{R}",
        converted_mana_cost=1, is_instant=True, oracle_text="Bolt1 deals 3 damage to any target.",
    )
    bolt2 = Card(
        id="Bolt2", name="Bolt2", type_line="Instant", mana_cost_string="{R}",
        converted_mana_cost=1, is_instant=True, oracle_text="Bolt2 deals 3 damage to any target.",
    )
    eng = _engine(p1_cards=[bolt1, bolt2])
    state = eng.state
    p1 = state.active_player
    _battlefield(state, _card("Eidolon of Rhetoric"), controller="p1")
    p1.mana_pool.add("R", 5)

    b1 = next(o for o in p1.hand if o.name == "Bolt1")
    b2 = next(o for o in p1.hand if o.name == "Bolt2")
    assert eng.can_cast(p1, b1)
    eng.cast_spell(p1, b1)
    assert not eng.can_cast(p1, b2)
    with pytest.raises(ValueError):
        eng.cast_spell(p1, b2)


# ---------------------------------------------------------------------------
# Item 4: "This <type> doesn't untap during your untap step." (RULE 502.3-adjacent)
# ---------------------------------------------------------------------------


def test_monolith_family_modeled_and_own_other_lines_unaffected():
    """Basalt/Grim Monolith flip to fully `MODELED`: the "doesn't untap"
    line is new coverage, and their own mana ability + "{N}: Untap this
    artifact." activated ability were already independently claimed. Mana
    Vault stays `UNMODELED` for one unrelated, out-of-scope trigger clause
    (its "deals 1 damage to you" draw-step trigger) — pinned by its text
    rather than by a count, so a future fix reads as the clause it closed.

    ENG-38: this pinned *two* clauses until the optional pay-{4}-to-untap
    upkeep trigger became claimable (`pay_cost_then`). The count assertion
    could only ever report "2 != 1"; naming the clause says which one
    went."""
    for name in ("Basalt Monolith", "Grim Monolith"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)

    mana_vault = parse_oracle(_card("Mana Vault"))
    assert not mana_vault.modeled
    assert not any("doesn't untap" in u for u in mana_vault.unclaimed)
    assert not any("pay {4}" in u for u in mana_vault.unclaimed)
    assert mana_vault.unclaimed == [
        "at the beginning of your draw step, if ~ is tapped, "
        "it deals 1 damage to you."
    ]


def test_basalt_monolith_stays_tapped_through_its_controllers_untap_step():
    card = _card("Basalt Monolith")
    eng = _engine()
    state = eng.state
    obj = _battlefield(state, card, controller="p1")
    obj.tapped = True
    # Its own mana ability and "{3}: Untap this artifact." cost are both
    # still live — this restriction only touches the automatic untap step.
    assert len(obj.activated_abilities) == 1
    assert mana_options_for(obj, state) == [{"C": 3}]

    eng._step_untap()
    assert obj.tapped is True


def test_ordinary_artifact_untaps_normally_for_comparison():
    rock = Card(id="Plain Rock", name="Plain Rock", type_line="Artifact")
    eng = _engine()
    state = eng.state
    obj = _battlefield(state, rock, controller="p1")
    obj.tapped = True
    eng._step_untap()
    assert obj.tapped is False


# ---------------------------------------------------------------------------
# Item 5: "Creatures entering don't cause abilities to trigger." (RULE 603)
# ---------------------------------------------------------------------------


def test_torpor_orb_family_modeled():
    for name in ("Tocatli Honor Guard", "Hushwing Gryff", "Torpor Orb"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_torpor_orb_silences_a_creatures_own_etb_trigger():
    etb_bear = Card(
        id="ETB Bear", name="ETB Bear", type_line="Creature — Bear",
        mana_cost_string="{1}{G}", converted_mana_cost=2, is_creature=True,
        power=2, toughness=2, oracle_text="When ~ enters the battlefield, draw a card.",
    )
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Torpor Orb"), controller="p1")
    bear = _battlefield(state, etb_bear, controller="p1")
    assert len(bear.triggered_abilities) == 1

    eng.rules._collect_triggers(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            controller_id="p1",
            instance_id=bear.instance_id,
            object_types=sorted(bear.type_words),
        )
    )
    assert eng.rules.pending_triggers == []


def test_without_torpor_orb_the_same_trigger_fires_for_comparison():
    etb_bear = Card(
        id="ETB Bear2", name="ETB Bear2", type_line="Creature — Bear",
        mana_cost_string="{1}{G}", converted_mana_cost=2, is_creature=True,
        power=2, toughness=2, oracle_text="When ~ enters the battlefield, draw a card.",
    )
    eng = _engine()
    state = eng.state
    bear = _battlefield(state, etb_bear, controller="p1")

    eng.rules._collect_triggers(
        GameEvent(
            EventType.ENTERS_BATTLEFIELD,
            controller_id="p1",
            instance_id=bear.instance_id,
            object_types=sorted(bear.type_words),
        )
    )
    assert len(eng.rules.pending_triggers) == 1


# ---------------------------------------------------------------------------
# Item 6: "[Nonbasic] <type> your opponents control enter tapped." (RULE 614.1)
# ---------------------------------------------------------------------------


def test_manglehorn_family_modeled_or_pinned_unclaimed():
    manglehorn = parse_oracle(_card("Manglehorn"))
    assert manglehorn.modeled, manglehorn.unclaimed

    dismantler = parse_oracle(_card("Dauntless Dismantler"))
    assert not dismantler.modeled
    assert not any("enter tapped" in u for u in dismantler.unclaimed)
    assert len(dismantler.unclaimed) == 1  # only its own {X}{X}{W} sac ability


def test_manglehorn_makes_an_opponents_artifact_enter_tapped():
    rock = Card(id="Rock", name="Rock", type_line="Artifact", mana_cost_string="{2}",
                converted_mana_cost=2)
    eng = _engine(p1_cards=[rock])
    state = eng.state
    p1 = state.active_player
    _battlefield(state, _card("Manglehorn"), controller="p2")
    p1.mana_pool.add("C", 2)

    rock_obj = p1.hand[0]
    eng.cast_spell(p1, rock_obj)
    eng.rules.resolve_top_of_stack()
    resolved = next(o for o in state.battlefield if o.name == "Rock")
    assert resolved.tapped is True


def test_archon_of_emeria_makes_opponents_nonbasic_land_enter_tapped_but_not_basics():
    dual = Card(id="Dual", name="Dual", type_line="Land — Island Swamp", is_land=True)
    forest = Card(id="Forest2", name="Forest2", type_line="Basic Land — Forest", is_land=True)
    eng = _engine(p1_cards=[dual, forest])
    state = eng.state
    p1 = state.active_player
    _battlefield(state, _card("Archon of Emeria"), controller="p2")

    dual_obj = next(o for o in p1.hand if o.name == "Dual")
    eng.play_land(p1, dual_obj)
    assert next(o for o in state.battlefield if o.name == "Dual").tapped is True

    p1.lands_played_this_turn = 0  # a test-only reset; RULE 305.1 aside
    forest_obj = next(o for o in p1.hand if o.name == "Forest2")
    eng.play_land(p1, forest_obj)
    assert next(o for o in state.battlefield if o.name == "Forest2").tapped is False


# ---------------------------------------------------------------------------
# Item 7: "Nonbasic lands are Mountains." (RULE 613.5 full layer-4 overwrite)
# ---------------------------------------------------------------------------


def test_blood_moon_family_modeled():
    for name in ("Magus of the Moon", "Blood Moon"):
        result = parse_oracle(_card(name))
        assert result.modeled, (name, result.unclaimed)


def test_blood_moon_overwrites_a_nonbasic_lands_subtype_and_grants_red_mana():
    """RULE 613.5: the dual loses its Island/Swamp subtypes outright (not
    just gains Mountain alongside them) and gains the matching basic land's
    mana ability. Known, documented scope limit (see BACKLOG.md): the
    dual's own *printed* mana ability isn't stripped, so it can still also
    tap for its original colours — only the subtype/new-mana-ability half of
    Blood Moon's real-world effect is modeled."""
    dual = _card("Underground Sea")
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Blood Moon"), controller="p1")
    dual_obj = _battlefield(state, dual, controller="p2")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(dual_obj, "Mountain") is True
    assert continuous.has_subtype(dual_obj, "Island") is False
    assert continuous.has_subtype(dual_obj, "Swamp") is False
    assert {"R": 1} in mana_options_for(dual_obj, state)


def test_blood_moon_does_not_affect_basic_lands():
    forest = Card(id="Forest3", name="Forest3", type_line="Basic Land — Forest", is_land=True)
    eng = _engine()
    state = eng.state
    _battlefield(state, _card("Blood Moon"), controller="p1")
    forest_obj = _battlefield(state, forest, controller="p2")

    eng.recompute_continuous_effects()
    assert continuous.has_subtype(forest_obj, "Forest") is True
    assert continuous.has_subtype(forest_obj, "Mountain") is False


# ---------------------------------------------------------------------------
# Item 8: "~ can be your commander." (RULE 903.3, no-op deck-legality claim)
# ---------------------------------------------------------------------------


def test_commander_eligibility_line_claimed_though_other_lines_stay_unmodeled():
    """Both real cube cards carry unrelated, genuinely complex loyalty
    abilities (a delayed "until your next turn, triple damage" replacement,
    a conditional card-draw payoff, mass commander reanimation, …) that stay
    out of this batch's scope — but the "~ can be your commander." sentence
    itself is now claimed and contributes no unclaimed span, on both cards,
    proving the claim is name-generic rather than hardcoded."""
    for name in ("Jeska, Thrice Reborn", "Tevesh Szat, Doom of Fools"):
        result = parse_oracle(_card(name))
        assert not result.modeled  # unrelated complex loyalty abilities remain
        assert not any("can be your commander" in u for u in result.unclaimed), (
            name, result.unclaimed
        )
