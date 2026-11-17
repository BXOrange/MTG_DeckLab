"""ENG-62: per-cost Kicker announcement (RULE 702.33b, 702.33d, 702.33f, 707.10).

"Kicker {2}{U} and/or {1}{B}" is two kicker costs, each payable once in any combination. The
spell records *which* were paid (`GameObject.kicker_costs_paid`, indices, beside `kicker_count`),
the announcement is a list of indices (an int N still means "the first N costs"), and a linked
"if it was kicked with its {A} kicker" reads that record through the `kicked` condition's `cost`.
Everything below runs the real parser, binder and engine on the printed Oracle text.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import attach_to_object
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.kicker_costs import (
    kicked_count, normalize_cost_text, paid_indices, was_kicked_with,
)
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.services.game_session import GameSession

STORMSCAPE = Card(
    id="Stormscape Battlemage", name="Stormscape Battlemage", type_line="Creature — Human Wizard",
    mana_cost_string="{1}{U}", converted_mana_cost=2, is_creature=True, power=2, toughness=2,
    oracle_text=(
        "Kicker {W} and/or {2}{B} (You may pay an additional {W} and/or {2}{B} as you cast this spell.)\n"
        "When this creature enters, if it was kicked with its {W} kicker, you gain 3 life.\n"
        "When this creature enters, if it was kicked with its {2}{B} kicker, destroy target nonblack creature. "
        "That creature can't be regenerated."
    ),
    keywords=["Kicker"],
)
SUNSCAPE = Card(
    id="Sunscape Battlemage", name="Sunscape Battlemage", type_line="Creature — Human Wizard",
    mana_cost_string="{3}{U}", converted_mana_cost=4, is_creature=True, power=2, toughness=2,
    oracle_text=(
        "Kicker {1}{G} and/or {2}{U} (You may pay an additional {1}{G} and/or {2}{U} as you cast this spell.)\n"
        "When this creature enters, if it was kicked with its {1}{G} kicker, destroy target creature with flying.\n"
        "When this creature enters, if it was kicked with its {2}{U} kicker, draw two cards."
    ),
    keywords=["Kicker"],
)
ANAVOLVER = Card(
    id="Anavolver", name="Anavolver", type_line="Creature — Volver",
    mana_cost_string="{3}{G}", converted_mana_cost=4, is_creature=True, power=3, toughness=3,
    oracle_text=(
        "Kicker {1}{U} and/or {B} (You may pay an additional {1}{U} and/or {B} as you cast this spell.)\n"
        "If this creature was kicked with its {1}{U} kicker, it enters with two +1/+1 counters on it and with flying.\n"
        "If this creature was kicked with its {B} kicker, it enters with a +1/+1 counter on it and with "
        "\"Pay 3 life: Regenerate this creature.\""
    ),
    keywords=["Kicker"],
)
ARCHANGEL = Card(
    id="Archangel of Wrath", name="Archangel of Wrath", type_line="Creature — Angel",
    mana_cost_string="{2}{W}{W}", converted_mana_cost=4, is_creature=True, power=3, toughness=4,
    oracle_text=(
        "Kicker {B} and/or {R} (You may pay an additional {B} and/or {R} as you cast this spell.)\n"
        "Flying, lifelink\n"
        "When this creature enters, if it was kicked, it deals 2 damage to any target.\n"
        "When this creature enters, if it was kicked twice, it deals 2 damage to any target."
    ),
    keywords=["Flying", "Lifelink", "Kicker"],
)
SINGLE_KICKER = Card(
    id="Sengir Nemesis", name="Sengir Nemesis", type_line="Creature", mana_cost_string="{2}{B}",
    converted_mana_cost=3, is_creature=True, power=2, toughness=2,
    oracle_text="Kicker {1}{B} (You may pay an additional {1}{B} as you cast this spell.)", keywords=["Kicker"],
)


def _library():
    return [Card(id=f"Lib{i}", name=f"Lib{i}", type_line="Land", is_land=True) for i in range(12)]


def _setup(card, mana):
    eng = GameEngine.new_game([("p1", "Alice", _library()), ("p2", "Bob", _library())],
                              starting_life=20, starting_hand=0)
    p1 = eng.state.players[0]
    result = parse_oracle(card)
    assert result.modeled, result.unclaimed
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, result.specs)
    p1.hand.append(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.mana_pool.add_many(mana)
    return eng, p1, obj


def _drain(eng, spell):
    """Resolve the stack, answering any trigger target with the opponent's creature (never the spell itself)."""
    for _ in range(6):
        eng.resolve_until_stable()
        choice = eng.state.pending_choice
        if choice is None:
            return
        options = [o for o in choice["options"] if o.get("instance_id") != spell.instance_id] or choice["options"]
        eng.resolve_pending_choice(options[0]["id"])
    raise AssertionError("choices did not settle")


def _cast(card, mana, kicked):
    eng, p1, obj = _setup(card, mana)
    victim = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                             toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.battlefield.append(victim)
    assert eng.cast_spell(p1, obj, kicked=kicked)
    _drain(eng, obj)
    return eng, p1, obj


# --- parser -------------------------------------------------------------------------------------


def test_two_kicker_costs_parse_in_printed_order():
    result = parse_oracle(STORMSCAPE)
    (kw,) = [s.keyword for s in result.specs if s.keyword and s.keyword["name"] == "kicker"]
    assert kw["costs"] == ["{W}", "{2}{B}"] and kw["cost"] == "{W}"


def test_single_kicker_has_no_costs_list():
    (kw,) = [s.keyword for s in parse_oracle(SINGLE_KICKER).specs if s.keyword and s.keyword["name"] == "kicker"]
    assert "costs" not in kw


def test_kicked_with_its_cost_condition_names_the_cost():
    result = parse_oracle(STORMSCAPE)
    conditions = [e.condition for s in result.specs for e in s.effects if e.condition]
    assert {"kind": "kicked", "min": 1, "cost": "{W}"} in conditions
    assert {"kind": "kicked", "min": 1, "cost": "{2}{B}"} in conditions


# --- announcement / cost ------------------------------------------------------------------------


def test_cost_adds_exactly_the_chosen_costs():
    eng, p1, obj = _setup(STORMSCAPE, {"C": 9})
    base = eng.effective_cast_cost(p1, obj).raw
    assert eng.effective_cast_cost(p1, obj, kicked=[]).raw == base
    assert eng.effective_cast_cost(p1, obj, kicked=[0]).converted_mana_cost == 3
    assert eng.effective_cast_cost(p1, obj, kicked=[1]).converted_mana_cost == 5
    assert eng.effective_cast_cost(p1, obj, kicked=[0, 1]).converted_mana_cost == 6


def test_illegal_announcements_are_rejected():
    eng, p1, obj = _setup(STORMSCAPE, {"U": 1, "C": 20, "W": 5, "B": 5})
    assert eng.can_cast(p1, obj, kicked=[0, 1])
    assert not eng.can_cast(p1, obj, kicked=[0, 0])   # RULE 702.33d: each cost at most once
    assert not eng.can_cast(p1, obj, kicked=[2])      # no such cost
    assert not eng.can_cast(p1, obj, kicked=3)        # old integer path: more than the printed costs


def test_affordability_is_checked_per_combination():
    # {1}{U} + {W} + {2}{B} = 6 mana of which exactly one W and one B: kicking only {W} fits 3 mana.
    eng, p1, obj = _setup(STORMSCAPE, {"U": 1, "W": 2})
    assert eng.can_cast(p1, obj, kicked=[0])
    assert not eng.can_cast(p1, obj, kicked=[1])
    assert eng.affordable_kicker_combinations(p1, obj) == [[0]]


def test_legal_actions_expose_the_per_cost_options():
    eng, p1, obj = _setup(STORMSCAPE, {"U": 1, "C": 1, "W": 1, "B": 1})
    session = GameSession.__new__(GameSession)
    session.engine = eng
    action = next(a for a in eng.legal_actions(p1) if a["type"] == "cast_spell" and a["instance_id"] == obj.instance_id)
    assert action["has_kicker"] and action["kicker_costs"] == ["{W}", "{2}{B}"]
    assert action["kicker_options"] == [[0]]


def test_session_announced_kicked_accepts_a_list_and_an_int():
    assert GameSession._announced_kicked({"kicked": [1, 0]}) == (1, 0)
    assert GameSession._announced_kicked({"kicked": 1}) == 1
    assert GameSession._announced_kicked({}) == 0


# --- Battlemage: neither, each, both ------------------------------------------------------------


def test_battlemage_unkicked_neither_cost_effect_fires():
    _, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 1}, kicked=[])
    assert p1.life == 20 and obj.kicker_count == 0 and obj.kicker_costs_paid == ()


def test_battlemage_first_cost_only():
    _, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 1, "W": 1}, kicked=[0])
    assert p1.life == 23
    assert obj.kicker_count == 1 and obj.kicker_costs_paid == (0,)
    assert was_kicked_with(obj, "{W}") and not was_kicked_with(obj, "{2}{B}")


def test_battlemage_second_cost_only_does_not_satisfy_the_first_gate():
    eng, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 1, "B": 1, "R": 2}, kicked=[1])
    assert p1.life == 20  # {W} gate unmet
    assert obj.kicker_count == 1 and obj.kicker_costs_paid == (1,)
    assert was_kicked_with(obj, "{2}{B}") and not was_kicked_with(obj, "{W}")


def test_battlemage_both_costs():
    _, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 4, "W": 1, "B": 1}, kicked=[0, 1])
    assert p1.life == 23 and obj.kicker_count == 2 and obj.kicker_costs_paid == (0, 1)


def test_sunscape_draws_only_for_its_blue_kicker():
    mana = {"C": 10, "G": 1, "U": 2}
    eng, p1, _ = _cast(SUNSCAPE, mana, kicked=[0])
    assert len(p1.hand) == 0
    eng, p1, _ = _cast(SUNSCAPE, mana, kicked=[1])
    assert len(p1.hand) == 2
    eng, p1, _ = _cast(SUNSCAPE, mana, kicked=[0, 1])
    assert len(p1.hand) == 2


def test_cost_param_fails_closed_on_an_unknown_cost():
    _, _, obj = _cast(STORMSCAPE, {"U": 1, "C": 4, "W": 1, "B": 1}, kicked=[0, 1])
    assert not was_kicked_with(obj, "{R}")
    assert not was_kicked_with(obj, "")


# --- Anavolver: entering with counters / keyword / quoted ability -------------------------------


def test_anavolver_first_kicker_gives_two_counters_and_flying():
    _, _, obj = _cast(ANAVOLVER, {"G": 1, "C": 3, "U": 1, "R": 1}, kicked=[0])
    assert obj.counters.get("+1/+1") == 2
    assert "flying" in obj.intrinsic_keywords
    assert not obj.activated_abilities


def test_anavolver_second_kicker_gives_one_counter_and_regenerate():
    _, _, obj = _cast(ANAVOLVER, {"G": 1, "C": 3, "B": 1}, kicked=[1])
    assert obj.counters.get("+1/+1") == 1
    assert "flying" not in obj.intrinsic_keywords
    assert any("egenerate" in (getattr(a, "description", "") or "") for a in obj.activated_abilities)


def test_anavolver_both_and_neither():
    _, _, both = _cast(ANAVOLVER, {"G": 1, "C": 3, "U": 1, "R": 1, "B": 1}, kicked=[0, 1])
    assert both.counters.get("+1/+1") == 3 and "flying" in both.intrinsic_keywords
    _, _, none = _cast(ANAVOLVER, {"G": 1, "C": 3}, kicked=[])
    assert not none.counters.get("+1/+1") and "flying" not in none.intrinsic_keywords


# --- the old integer path -----------------------------------------------------------------------


def test_integer_announcement_pays_the_first_n_costs():
    # Documented choice: an int N on a two-cost card pays the first N printed costs, so a count-only
    # caller still casts it; callers that care which cost use the list.
    _, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 1, "W": 1}, kicked=1)
    assert p1.life == 23 and obj.kicker_costs_paid == (0,) and obj.kicker_count == 1
    _, p1, obj = _cast(STORMSCAPE, {"U": 1, "C": 4, "W": 1, "B": 1}, kicked=2)
    assert obj.kicker_costs_paid == (0, 1)


def test_single_cost_kicker_keeps_its_integer_semantics():
    eng, p1, obj = _setup(SINGLE_KICKER, {"C": 4, "B": 2})
    assert not eng.can_cast(p1, obj, kicked=2)  # plain Kicker is payable once
    assert eng.can_cast(p1, obj, kicked=1)
    assert eng.cast_spell(p1, obj, kicked=1)
    assert obj.kicker_count == 1 and obj.kicker_costs_paid == ()
    assert was_kicked_with(obj, "{1}{B}")


def test_archangel_of_wrath_kicked_twice_means_both_costs():
    eng, p1, obj = _setup(ARCHANGEL, {"W": 2, "C": 2, "B": 1, "R": 1})
    assert eng.can_cast(p1, obj, kicked=[0, 1])
    assert eng.cast_spell(p1, obj, kicked=[0, 1])
    assert obj.kicker_count == 2


def test_kicker_helpers():
    assert normalize_cost_text("{1}{u}") == "{1}{U}"
    assert kicked_count([0, 1]) == 2 and kicked_count(1) == 1 and kicked_count(None) == 0
    assert paid_indices(SINGLE_KICKER_OBJ(), [0]) is None  # a list needs two printed costs


def SINGLE_KICKER_OBJ():
    obj = GameObject(SINGLE_KICKER, owner_id="p1", zone=Zone.HAND)
    attach_to_object(obj, parse_oracle(SINGLE_KICKER).specs)
    return obj


# --- RULE 707.10: a copy keeps the record --------------------------------------------------------


def test_spell_copy_keeps_the_per_cost_record():
    eng, p1, obj = _setup(STORMSCAPE, {"U": 1, "C": 4, "W": 1, "B": 1})
    assert eng.cast_spell(p1, obj, kicked=[0, 1])
    item = eng.state.stack[-1]
    copies = eng.rules.copy_spell(item, p1.id)
    assert copies, "copy_spell produced no copy"
    copy_obj = copies[0].obj
    assert copy_obj is not obj
    assert copy_obj.kicker_costs_paid == (0, 1) and copy_obj.kicker_count == 2
    assert was_kicked_with(copy_obj, "{W}") and was_kicked_with(copy_obj, "{2}{B}")


# --- GameSession: the list announcement round-trips from legal_actions ---------------------------


@pytest.mark.parametrize("option", [[0], [1], [0, 1]])
def test_session_casts_each_offered_combination(option):
    eng, p1, obj = _setup(ANAVOLVER, {"C": 8, "G": 1, "U": 1, "B": 1})
    session = GameSession(eng, mode="replay", require_setup=False)
    offered = next(a for a in eng.legal_actions(p1)
                   if a["type"] == "cast_spell" and a["instance_id"] == obj.instance_id)
    assert option in offered["kicker_options"]
    session.apply_action({"type": "cast_spell", "instance_id": obj.instance_id, "kicked": option}, actor_id="p1")
    assert list(obj.kicker_costs_paid) == option and obj.kicker_count == len(option)


def test_smart_bot_offers_one_variant_per_affordable_combination():
    from mtg_analyzer.services.bot_policies.smart2 import SmartBot2

    bot = SmartBot2.__new__(SmartBot2)
    action = {"type": "cast_spell", "has_kicker": True, "kicker_costs": ["{W}", "{2}{B}"],
              "kicker_options": [[0], [1], [0, 1]], "max_kicker": 2}
    variants = bot._variants(None, action, [action])
    assert [v.get("kicked") for v in variants] == [None, [0], [1], [0, 1]]


def test_wastescape_cast_trigger_reads_the_announced_cost():
    wastescape = Card(
        id="Wastescape Battlemage", name="Wastescape Battlemage", type_line="Creature — Human Wizard",
        mana_cost_string="{2}{G}", converted_mana_cost=3, is_creature=True, power=2, toughness=2,
        oracle_text=(
            "Kicker {G} and/or {1}{U} (You may pay an additional {G} and/or {1}{U} as you cast this spell.)\n"
            "When you cast this spell, if it was kicked with its {G} kicker, exile target artifact or enchantment "
            "an opponent controls.\n"
            "When you cast this spell, if it was kicked with its {1}{U} kicker, return target creature an opponent "
            "controls to its owner's hand."),
        keywords=["Kicker"],
    )
    results = {}
    for label, kicked in (("green", [0]), ("blue", [1]), ("none", [])):
        eng, p1, obj = _setup(wastescape, {"C": 6, "G": 2, "U": 1})
        rock = GameObject(Card(id="Rock", name="Rock", type_line="Artifact"),
                          owner_id="p2", zone=Zone.BATTLEFIELD)
        bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                               toughness=2), owner_id="p2", zone=Zone.BATTLEFIELD)
        eng.state.battlefield.extend([rock, bear])
        assert eng.cast_spell(p1, obj, kicked=kicked)
        _drain(eng, obj)
        results[label] = (rock.zone, bear.zone)
    assert results["green"] == (Zone.EXILE, Zone.BATTLEFIELD)
    assert results["blue"] == (Zone.BATTLEFIELD, Zone.HAND)
    assert results["none"] == (Zone.BATTLEFIELD, Zone.BATTLEFIELD)


def test_illuminate_riders_follow_their_own_kicker_cost():
    illuminate = Card(
        id="Illuminate", name="Illuminate", type_line="Sorcery", is_sorcery=True, mana_cost_string="{X}{R}",
        converted_mana_cost=1,
        oracle_text=(
            "Kicker {2}{R} and/or {3}{U} (You may pay an additional {2}{R} and/or {3}{U} as you cast this spell.)\n"
            "Illuminate deals X damage to target creature. If this spell was kicked with its {2}{R} kicker, it deals "
            "X damage to that creature's controller. If this spell was kicked with its {3}{U} kicker, you draw X "
            "cards."),
        keywords=["Kicker"],
    )
    outcomes = {}
    for label, kicked in (("red", [0]), ("blue", [1]), ("both", [0, 1]), ("none", [])):
        eng, p1, obj = _setup(illuminate, {"C": 12, "R": 3, "U": 1})
        bear = GameObject(Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True, power=2,
                               toughness=5), owner_id="p2", zone=Zone.BATTLEFIELD)
        eng.state.battlefield.append(bear)
        p2 = eng.state.players[1]
        assert eng.cast_spell(p1, obj, [bear], 2, kicked=kicked)
        eng.resolve_until_stable()
        outcomes[label] = (p2.life, len(p1.hand))
    assert outcomes == {"red": (18, 0), "blue": (20, 2), "both": (18, 2), "none": (20, 0)}
