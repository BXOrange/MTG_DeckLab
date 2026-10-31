"""PAR-176 -- "Activate only ..." restriction sentences (RULE 602.5, 602.5b, 602.5d).

One grammar (`costs_mana_limits._activate_only_compound`) turns a printed restriction sentence into the timing
flags / `ActivationCost.activation_condition` the engine already enforces, plus two new step conditions
(`during_phase`, `before_step`).  Every family is parsed *and* executed against the real engine; any atom the engine
cannot enforce keeps the card UNMODELED.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle

LIBRARY_FILLER = 40
MAX_STEP_ADVANCES = 200


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "P1", []), ("p2", "P2", [])], starting_life=20, starting_hand=0)
    for player in eng.state.players:
        for n in range(LIBRARY_FILLER):
            player.add_to_zone(
                GameObject(Card(id=f"f{player.id}{n}", name="Filler", type_line="Land", is_land=True),
                           owner_id=player.id, zone=Zone.LIBRARY),
                Zone.LIBRARY,
            )
    eng.start()
    return eng


def _perm(eng, oracle, name="Gadget", type_line="Artifact Creature -- Construct", power=2, toughness=2, owner="p1"):
    obj = GameObject(
        Card(id=name, name=name, type_line=type_line, is_creature="Creature" in type_line,
             is_land="Land" in type_line,
             power=power, toughness=toughness, oracle_text=oracle),
        owner_id=owner, zone=Zone.BATTLEFIELD,
    )
    obj.controller_id = owner
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _run_to(eng, step, active="p1"):
    guard = 0
    while eng.state.current_step != step or eng.state.active_player.id != active:
        eng.advance_step()
        guard += 1
        assert guard < MAX_STEP_ADVANCES, f"never reached {step!r} on {active}'s turn"


def _can(eng, obj, player="p1"):
    [ability] = obj.activated_abilities
    obj.tapped = False
    return eng.can_activate(eng.state.player_by_id(player), obj, ability)


def _legal_steps(eng, obj, steps, active="p1"):
    """The subset of ``steps`` (in turn order) at which ``obj``'s ability is activatable."""
    legal = set()
    for step in steps:
        try:
            _run_to(eng, step, active)
        except AssertionError:
            continue  # the step was skipped (no attackers) -- not an activation window at all
        if _can(eng, obj):
            legal.add(step)
    return legal


TURN_STEPS = ["upkeep", "draw", "main1", "begin_combat", "declare_attackers", "declare_blockers",
              "combat_damage", "end_combat", "main2", "end"]


# ---------------------------------------------------------------------------
# Parse verdicts: the whole family is MODELED, and an unenforceable atom is not
# ---------------------------------------------------------------------------

def _modeled(oracle, **kw):
    card = Card(id="t", name="Test Card", type_line="Artifact Creature -- Construct", is_creature=True,
                power=2, toughness=2, oracle_text=oracle, **kw)
    return parse_oracle(card).modeled


@pytest.mark.parametrize("sentence", [
    "Activate only during your upkeep.",
    "Activate only during any upkeep step.",
    "Activate only during combat.",
    "Activate only during the end of combat step.",
    "Activate only during the declare blockers step.",
    "Activate only before the combat damage step.",
    "Activate only before attackers are declared.",
    "Activate only as a sorcery and only once each turn.",
    "Activate only as a sorcery and only once.",
    "Activate only as an instant.",
    "Activate only during your upkeep and only if you control a Swamp.",
    "Activate only if you have exactly seven cards in hand.",
    "Activate only if you have seven or more cards in your hand.",
    "Activate only if this creature's power is 4 or greater.",
    "Activate only if an opponent controls four or more lands.",
    "Activate only if an opponent controls at least two more lands than you.",
    "Activate only if an opponent was dealt damage this turn.",
    "Activate only if this creature entered this turn.",
    "Activate only if you had a creature enter the battlefield under your control this turn.",
    "Activate only if this creature is attacking or blocking and only once each turn.",
    "Activate only during the declare blockers step, only if at least one creature is blocking this creature, "
    "and only once each turn.",
    "Activate only if you control no creatures and only during your turn.",
])
def test_restriction_sentence_is_claimed(sentence):
    assert _modeled("{1}: Draw a card. " + sentence)


@pytest.mark.parametrize("sentence", [
    "Activate only if the moon is full.",
    "Activate only during your upkeep and only if the moon is full.",
    "Activate only on a full moon.",
    "Activate only during the sideways step.",
    "Activate only during combat or only during your upkeep.",
])
def test_unenforceable_restriction_stays_unmodeled(sentence):
    assert not _modeled("{1}: Draw a card. " + sentence)


def test_real_cards_become_modeled():
    cards = {
        "Augur il-Vec": "Shadow (This creature can block or be blocked by only creatures with shadow.)\n"
                        "Sacrifice this creature: You gain 4 life. Activate only during your upkeep.",
        "Library of Alexandria": "{T}: Draw a card. Activate only if you have exactly seven cards in hand.",
        "Heart Wolf": "{R}, {T}: Target Dwarf creature gains first strike until end of turn. Activate only during combat.",
    }
    for name, text in cards.items():
        creature = "Library" not in name
        card = Card(id=name, name=name, type_line="Creature -- Wolf" if creature else "Artifact",
                    is_creature=creature, oracle_text=text,
                    power=1 if creature else None, toughness=1 if creature else None)
        assert parse_oracle(card).modeled, name


# ---------------------------------------------------------------------------
# Engine enforcement: timing windows
# ---------------------------------------------------------------------------

def test_during_your_upkeep_only_in_own_upkeep():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during your upkeep.")
    assert _legal_steps(eng, obj, TURN_STEPS) == {"upkeep"}


def test_during_your_upkeep_is_illegal_in_opponents_upkeep():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during your upkeep.")
    _run_to(eng, "upkeep", "p2")
    assert not _can(eng, obj)


def test_during_any_upkeep_step_includes_the_opponents():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during any upkeep step.")
    _run_to(eng, "upkeep", "p2")
    assert _can(eng, obj)
    _run_to(eng, "main1", "p2")
    assert not _can(eng, obj)


def test_during_combat_is_the_whole_combat_phase_on_any_turn():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during combat.")
    legal = _legal_steps(eng, obj, TURN_STEPS)
    assert legal <= {"begin_combat", "declare_attackers", "declare_blockers", "combat_damage", "end_combat"}
    assert "begin_combat" in legal
    assert not (legal & {"upkeep", "main1", "main2", "end"})
    _run_to(eng, "begin_combat", "p2")
    assert _can(eng, obj)


def test_during_a_named_step():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during the end of combat step.")
    legal = _legal_steps(eng, obj, TURN_STEPS)
    assert legal <= {"end_combat"}


def test_before_the_combat_damage_step_covers_earlier_phases_too():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only before the combat damage step.")
    legal = _legal_steps(eng, obj, TURN_STEPS)
    assert {"upkeep", "draw", "main1", "begin_combat"} <= legal
    assert not (legal & {"combat_damage", "end_combat", "main2", "end"})


def test_before_attackers_are_declared_is_not_limited_to_the_controllers_turn():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only before attackers are declared.")
    _run_to(eng, "main1", "p2")
    assert _can(eng, obj)
    legal = _legal_steps(eng, obj, ["declare_attackers", "declare_blockers", "main2"], active="p2")
    assert not legal


def test_sorcery_and_once_each_turn_folds_both_flags():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only as a sorcery and only once each turn.")
    [ability] = obj.activated_abilities
    assert ability.cost.sorcery_speed_only and ability.once_per_turn


def test_sorcery_and_once_per_game_folds_both_flags():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only as a sorcery and only once.")
    [ability] = obj.activated_abilities
    assert ability.cost.sorcery_speed_only and ability.once_per_game


def test_as_an_instant_restricts_nothing():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only as an instant.")
    _run_to(eng, "main2", "p2")
    assert _can(eng, obj)


# ---------------------------------------------------------------------------
# Engine enforcement: "and only ..." conjunctions
# ---------------------------------------------------------------------------

def test_timing_window_and_condition_must_both_hold():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during your upkeep and only if you control a Swamp.")
    _run_to(eng, "upkeep", "p1")
    assert not _can(eng, obj)  # right window, condition fails
    swamp = _perm(eng, "", name="Swamp", type_line="Basic Land — Swamp", power=None, toughness=None)
    assert _can(eng, obj)
    _run_to(eng, "main1", "p1")
    assert not _can(eng, obj)  # condition holds, wrong window


def test_condition_then_own_turn_in_either_order():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if you control no creatures and only during your turn.",
                type_line="Artifact", power=None, toughness=None)
    _run_to(eng, "main1", "p1")
    assert _can(eng, obj)
    _perm(eng, "", name="Bear", type_line="Creature -- Bear")
    assert not _can(eng, obj)


def test_blockers_conjunction_needs_step_blocker_and_is_once_a_turn():
    eng = _engine()
    wolverine = _perm(eng,
                      "{T}: ~ gets +2/+0 until end of turn. Activate only during the declare blockers step, "
                      "only if at least one creature is blocking this creature, and only once each turn.")
    [ability] = wolverine.activated_abilities
    assert ability.once_per_turn
    _run_to(eng, "declare_blockers", "p1")
    assert not _can(eng, wolverine)  # nobody blocks it
    wolverine.blocked_by = [999]
    assert _can(eng, wolverine)
    _run_to(eng, "main2", "p1")
    assert not _can(eng, wolverine)


def test_several_restriction_sentences_are_all_enforced():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only during your upkeep. Activate only if you have exactly 7 cards in hand.")
    [ability] = obj.activated_abilities
    assert ability.cost.activation_condition["kind"] == "all"
    _run_to(eng, "upkeep", "p1")
    player = eng.state.player_by_id("p1")
    seven = len(player.hand) == 7
    assert _can(eng, obj) == seven


# ---------------------------------------------------------------------------
# Engine enforcement: condition gates over the static_conditions vocabulary
# ---------------------------------------------------------------------------

def _hand_filler(eng, n):
    player = eng.state.player_by_id("p1")
    player.hand[:] = []
    for i in range(n):
        player.add_to_zone(GameObject(Card(id=f"h{i}", name="Card", type_line="Land", is_land=True),
                                      owner_id="p1", zone=Zone.HAND), Zone.HAND)


@pytest.mark.parametrize("cards,legal", [(6, False), (7, True), (8, False)])
def test_exactly_seven_cards_in_hand(cards, legal):
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if you have exactly seven cards in hand.",
                type_line="Artifact", power=None, toughness=None)
    _run_to(eng, "main1", "p1")
    _hand_filler(eng, cards)
    assert _can(eng, obj) is legal


def test_power_threshold_reads_the_derived_power():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if this creature's power is 4 or greater.", power=2)
    _run_to(eng, "main1", "p1")
    eng.recompute_continuous_effects()
    assert not _can(eng, obj)
    obj.add_counters("+1/+1", 2)
    eng.recompute_continuous_effects()
    assert _can(eng, obj)


def test_opponent_land_count_gate():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if an opponent controls four or more lands.",
                type_line="Artifact", power=None, toughness=None)
    _run_to(eng, "main1", "p1")
    assert not _can(eng, obj)
    for i in range(4):
        _perm(eng, "", name=f"Land{i}", type_line="Land", power=None, toughness=None, owner="p2")
    eng.recompute_continuous_effects()
    assert _can(eng, obj)


def test_opponent_two_more_lands_needs_the_margin():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if an opponent controls at least two more lands than you.",
                type_line="Artifact", power=None, toughness=None)
    _run_to(eng, "main1", "p1")
    _perm(eng, "", name="Mine", type_line="Land", power=None, toughness=None, owner="p1")
    for i in range(2):
        _perm(eng, "", name=f"Theirs{i}", type_line="Land", power=None, toughness=None, owner="p2")
    assert not _can(eng, obj)  # only one more
    _perm(eng, "", name="Theirs2", type_line="Land", power=None, toughness=None, owner="p2")
    assert _can(eng, obj)


def test_entered_this_turn_gate():
    eng = _engine()
    _run_to(eng, "main1", "p1")
    obj = _perm(eng, "{T}: Draw a card. Activate only if this creature entered this turn.")
    obj.turn_entered = eng.state.internal_turn.number
    assert _can(eng, obj)
    obj.turn_entered = eng.state.internal_turn.number - 1
    assert not _can(eng, obj)


def test_attacking_or_blocking_gate():
    eng = _engine()
    obj = _perm(eng, "{T}: Draw a card. Activate only if this creature is attacking or blocking and only once each turn.")
    _run_to(eng, "main1", "p1")
    assert not _can(eng, obj)
    obj.attacking = True
    assert _can(eng, obj)


def test_enchanted_creature_gate_reads_the_host():
    eng = _engine()
    host = _perm(eng, "", name="Host")
    aura = _perm(eng, "Enchant creature\n{T}: Draw a card. Activate only if enchanted creature is white and untapped.",
                 name="Aura", type_line="Enchantment -- Aura", power=None, toughness=None)
    aura.attached_to = host.instance_id
    host.card.color_identity = ["W"]
    host.tapped = False
    _run_to(eng, "main1", "p1")
    ability = aura.activated_abilities[0]
    cond = ability.cost.activation_condition
    assert cond["kind"] == "all" and all(c.get("of") == "attached" for c in cond["conditions"])


# ---------------------------------------------------------------------------
# New condition kinds
# ---------------------------------------------------------------------------

def test_during_phase_and_before_step_conditions():
    from mtg_analyzer.game import static_conditions as sc

    eng = _engine()
    _run_to(eng, "declare_attackers", "p1")
    assert sc.condition_holds({"kind": "during_phase", "phase": "combat"}, eng.state, controller_id="p1")
    assert not sc.condition_holds({"kind": "during_phase", "phase": "precombat_main"}, eng.state, controller_id="p1")
    assert sc.condition_holds({"kind": "before_step", "step": "combat_damage"}, eng.state, controller_id="p1")
    assert not sc.condition_holds({"kind": "before_step", "step": "declare_attackers"}, eng.state, controller_id="p1")
    assert not sc.condition_holds({"kind": "before_step", "step": "nonsense"}, eng.state, controller_id="p1")
