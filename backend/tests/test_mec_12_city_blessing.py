"""Tests for BACKLOG MEC-12 and its Ascend/city's blessing companion mechanic.

MEC-12 (Monarch/Initiative-conditioned statics, RULE 613.6): `game/
static_conditions.py` gains ``is_monarch``/``has_initiative`` — plain reads
of `GameState.monarch_id`/`initiative_id` against the static's own
controller, the same shape `your_turn` already has. `parser/oracle/
catalogue/static_handlers.py`'s `_STATIC_CONDITION_RES` gains the matching
phrases, so both printed orders ("as long as you're the monarch, …" / "…
as long as you're the monarch.") ride the existing `_conditional_static_
specs` wrapper with no new engine mechanism.

Ascend (RULE 702.131, "the city's blessing") shipped alongside it in the same
batch — the ticket's own condition vocabulary is the natural place for
``has_city_blessing`` too, and Ascend was previously recognized only as a
bare `keyword` spec (`parser/oracle/catalogue/keywords.py`) with no engine
behaviour bound to it at all, a silent no-op exactly like `create_emblem`'s
dropped `ActivatedAbility` was before MEC-8. Unlike Monarch/Initiative
(`GameState.monarch_id`/`initiative_id`, a single shared holder), the city's
blessing is a plain idempotent per-player flag (`Player.has_city_blessing`,
RULE 702.131c: "any number of players may have the city's blessing at the
same time") that, once granted, is never cleared (702.131d: "for the rest of
the game") — `RulesEngine.get_city_blessing` is the one idempotent setter
both forms share:

* **Ascend on a permanent** (702.131b) is a continuous "any time you control
  ten or more permanents…" check with no event to hang off, swept at SBA
  cadence exactly like the day/night and Ring-bearer checks
  (`RulesEngine._sba_check_ascend`, reading the keyword straight off
  `combat.has(obj, "ascend")` — no extra binding needed beyond what
  `attach_keyword` already does for every flag keyword).
* **Ascend on an instant/sorcery** (702.131a) is a one-shot resolution
  effect instead (`GetCityBlessingEffect`, wired in `effect_binder.
  attach_to_object`'s keyword branch onto `spell_effects` when the object's
  card is an instant/sorcery).
"""

from __future__ import annotations

from mtg_analyzer.game import combat, continuous, static_conditions
from mtg_analyzer.game.binding.core import attach_to_object, bind_from_catalogue
from mtg_analyzer.game.effects.core import GetCityBlessingEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle


# ---------------------------------------------------------------------------
# Shared fixtures (mirrors test_mec_batch_4_6_7_8_9.py's style)
# ---------------------------------------------------------------------------


def _engine(*player_ids):
    players = [Player(id=pid, life=20) for pid in player_ids]
    state = GameState(players=players)
    engine = GameEngine(state)
    engine.state.current_step = "main1"
    return engine, state


def _permanent(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _fill_permanents(state, controller, count, existing=0):
    """Add plain vanilla lands until ``controller`` controls ``count``
    permanents total (``existing`` already placed by the caller)."""
    for i in range(count - existing):
        land = Card(
            id=f"Filler Land {controller} {i}", name=f"Filler Land {controller} {i}",
            type_line="Land", is_land=True,
        )
        _permanent(state, land, controller=controller)


# ---------------------------------------------------------------------------
# RulesEngine.get_city_blessing — the shared idempotent primitive
# ---------------------------------------------------------------------------


def test_get_city_blessing_is_idempotent():
    engine, state = _engine("p1")
    p1 = state.players[0]
    assert p1.has_city_blessing is False
    engine.rules.get_city_blessing(p1)
    assert p1.has_city_blessing is True
    # A second grant is a no-op, not an error (RULE 702.131c/d).
    engine.rules.get_city_blessing(p1)
    assert p1.has_city_blessing is True


# ---------------------------------------------------------------------------
# Ascend on a permanent (RULE 702.131b) — SBA-cadence board check
# ---------------------------------------------------------------------------


def test_sba_check_ascend_grants_blessing_at_ten_permanents():
    engine, state = _engine("p1", "p2")
    p1, p2 = state.players
    ascend_permanent = _permanent(
        state,
        Card(
            id="Bench Ascend Permanent", name="Bench Ascend Permanent", type_line="Enchantment",
            mana_cost_string="{1}", converted_mana_cost=1,
            oracle_text="Ascend (If you control ten or more permanents, you get the city's blessing for the rest of the game.)",
            keywords=["Ascend"],
        ),
    )
    assert combat.has(ascend_permanent, "ascend")
    _fill_permanents(state, "p1", 10, existing=1)  # 1 (Ascend permanent) + 9 lands = 10
    assert continuous.count_selector(state, "p1", "permanents_you_control") == 10
    assert p1.has_city_blessing is False
    engine.rules.check_state_based_actions()
    assert p1.has_city_blessing is True
    # An opponent's permanent count must not grant it to them.
    assert p2.has_city_blessing is False


def test_sba_check_ascend_does_not_grant_below_ten():
    engine, state = _engine("p1")
    p1 = state.players[0]
    _permanent(
        state,
        Card(
            id="Bench Ascend Permanent 2", name="Bench Ascend Permanent 2", type_line="Enchantment",
            mana_cost_string="{1}", converted_mana_cost=1,
            oracle_text="Ascend (If you control ten or more permanents, you get the city's blessing for the rest of the game.)",
            keywords=["Ascend"],
        ),
    )
    _fill_permanents(state, "p1", 5, existing=1)
    engine.rules.check_state_based_actions()
    assert p1.has_city_blessing is False


def test_sba_check_ascend_is_a_one_time_flip():
    """RULE 702.131d: once granted, the SBA sweep has nothing further to do
    even though the controller keeps controlling 10+ permanents forever —
    exercised by running the SBA loop again after the grant."""
    engine, state = _engine("p1")
    p1 = state.players[0]
    _permanent(
        state,
        Card(
            id="Bench Ascend Permanent 3", name="Bench Ascend Permanent 3", type_line="Enchantment",
            mana_cost_string="{1}", converted_mana_cost=1,
            oracle_text="Ascend (If you control ten or more permanents, you get the city's blessing for the rest of the game.)",
            keywords=["Ascend"],
        ),
    )
    _fill_permanents(state, "p1", 10, existing=1)
    engine.rules.check_state_based_actions()
    assert p1.has_city_blessing is True
    # Doesn't loop forever, and a second sweep leaves it alone.
    assert engine.rules.check_state_based_actions() is False
    assert p1.has_city_blessing is True


# ---------------------------------------------------------------------------
# Ascend on an instant/sorcery (RULE 702.131a) — one-shot resolution effect
# ---------------------------------------------------------------------------


def _ascend_sorcery():
    return Card(
        id="Bench Ascend Sorcery", name="Bench Ascend Sorcery", type_line="Sorcery",
        mana_cost_string="{1}{W}", converted_mana_cost=2, is_sorcery=True,
        oracle_text="Ascend (If you control ten or more permanents, you get the city's blessing for the rest of the game.)",
        keywords=["Ascend"],
    )


def test_ascend_spell_binds_get_city_blessing_effect():
    obj = GameObject(_ascend_sorcery(), owner_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    assert any(isinstance(e, GetCityBlessingEffect) for e in obj.spell_effects)


def test_ascend_spell_grants_blessing_on_resolution_at_ten_permanents():
    engine, state = _engine("p1")
    p1 = state.players[0]
    _fill_permanents(state, "p1", 10)
    obj = GameObject(_ascend_sorcery(), owner_id="p1", controller_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    # Resolve the spell's one-shot effects directly, against the RulesEngine's
    # own context (`RulesEngine.__init__` builds `self.context = GameContext
    # (state, self)`) — a `GameContext.engine` is always the `RulesEngine`,
    # never the outer `GameEngine`.
    for effect in obj.spell_effects:
        effect.apply(engine.rules.context)
    assert p1.has_city_blessing is True


def test_ascend_spell_no_blessing_below_ten_permanents():
    engine, state = _engine("p1")
    p1 = state.players[0]
    _fill_permanents(state, "p1", 3)
    obj = GameObject(_ascend_sorcery(), owner_id="p1", controller_id="p1", zone=Zone.STACK)
    bind_from_catalogue(obj)
    for effect in obj.spell_effects:
        effect.apply(engine.rules.context)
    assert p1.has_city_blessing is False


# ---------------------------------------------------------------------------
# static_conditions.py: is_monarch / has_initiative / has_city_blessing
# ---------------------------------------------------------------------------


def test_condition_is_monarch():
    engine, state = _engine("p1", "p2")
    state.monarch_id = "p1"
    assert static_conditions.condition_holds({"kind": "is_monarch"}, state, controller_id="p1") is True
    assert static_conditions.condition_holds({"kind": "is_monarch"}, state, controller_id="p2") is False


def test_condition_has_initiative():
    engine, state = _engine("p1", "p2")
    state.initiative_id = "p2"
    assert static_conditions.condition_holds({"kind": "has_initiative"}, state, controller_id="p2") is True
    assert static_conditions.condition_holds({"kind": "has_initiative"}, state, controller_id="p1") is False


def test_condition_has_city_blessing():
    engine, state = _engine("p1", "p2")
    state.players[0].has_city_blessing = True
    assert static_conditions.condition_holds({"kind": "has_city_blessing"}, state, controller_id="p1") is True
    assert static_conditions.condition_holds({"kind": "has_city_blessing"}, state, controller_id="p2") is False


def test_unrecognized_designation_kind_fails_closed():
    engine, state = _engine("p1")
    state.monarch_id = "p1"
    # A malformed/unknown kind must never accidentally read as true.
    assert static_conditions.condition_holds({"kind": "is_emperor"}, state, controller_id="p1") is False


# ---------------------------------------------------------------------------
# Parser recognition — both printed orders, over the shared "as long as" wrapper
# ---------------------------------------------------------------------------


def test_static_condition_recognizes_designation_phrases():
    assert static_condition("you're the monarch") == {"kind": "is_monarch"}
    assert static_condition("you have the initiative") == {"kind": "has_initiative"}
    assert static_condition("you have the city's blessing") == {"kind": "has_city_blessing"}


def test_leading_and_trailing_as_long_as_monarch():
    leading = static_effect_specs("As long as you're the monarch, ~ has hexproof.")
    trailing = static_effect_specs("~ has hexproof as long as you're the monarch.")
    for specs in (leading, trailing):
        assert specs is not None
        assert len(specs) == 1
        assert specs[0].params["active_if"] == {"kind": "is_monarch"}


def test_trailing_as_long_as_city_blessing_self_anthem():
    specs = static_effect_specs("~ gets +2/+2 as long as you have the city's blessing.")
    assert specs is not None
    assert specs[0].type == "anthem"
    assert specs[0].params["power"] == 2
    assert specs[0].params["toughness"] == 2
    assert specs[0].params["active_if"] == {"kind": "has_city_blessing"}


# ---------------------------------------------------------------------------
# End-to-end: a real cached card (Dusk Charger, Ixalan)
# ---------------------------------------------------------------------------


def _dusk_charger():
    return Card(
        id="Dusk Charger", name="Dusk Charger", type_line="Creature — Horse",
        mana_cost_string="{3}{B}", converted_mana_cost=4,
        is_creature=True, power=3, toughness=3,
        keywords=["Ascend"],
        oracle_text=(
            "Ascend (If you control ten or more permanents, you get the city's "
            "blessing for the rest of the game.)\n"
            "This creature gets +2/+2 as long as you have the city's blessing."
        ),
    )


def test_dusk_charger_parses_fully_modeled():
    result = parse_oracle(_dusk_charger())
    assert result.modeled is True


def test_dusk_charger_anthem_is_live_and_gated():
    engine, state = _engine("p1")
    p1 = state.players[0]
    dusk_charger = _permanent(state, _dusk_charger())
    continuous.recompute(state)
    assert dusk_charger.power == 3 and dusk_charger.toughness == 3

    p1.has_city_blessing = True
    continuous.recompute(state)
    assert dusk_charger.power == 5 and dusk_charger.toughness == 5

    # RULE 613: a live re-derivation, not a one-time bake — losing the
    # designation (impossible in real rules, but the condition must still
    # answer honestly either way) turns the anthem back off.
    p1.has_city_blessing = False
    continuous.recompute(state)
    assert dusk_charger.power == 3 and dusk_charger.toughness == 3
