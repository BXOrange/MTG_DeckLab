"""MEC-49 — per-turn damage-source attribution.

"Whenever a creature dealt damage by ~ this turn dies, <effect>." (Baron
Sengir, Abattoir Ghoul, Blood Cultist, the Sengir Vampire family).

`GameState.creatures_damaged_by_source_this_turn` — `{damaged_obj_id:
{source_id, …}}` — recorded by `RulesEngine.deal_damage` for any damage to a
creature (combat or not), reset game-wide each `begin_turn`. Read by
`effect_binder._build_group_ok`'s `damaged_by_source_this_turn` filter off
the DIES event.
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _engine(life=20):
    eng = GameEngine.new_game(
        [("p1", "A", []), ("p2", "B", [])], starting_life=life, starting_hand=0
    )
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state


def _creature(st, pid, name, power=3, toughness=3):
    o = GameObject(
        Card(id=name[:6], name=name, type_line="Creature — Bear",
             is_creature=True, power=power, toughness=toughness),
        owner_id=pid, zone=Zone.BATTLEFIELD,
    )
    o.controller_id = pid
    st.add_to_battlefield(o)
    return o


# --- the tracker --------------------------------------------------------


def test_deal_damage_to_a_creature_records_the_source():
    eng, st = _engine()
    a = _creature(st, "p1", "Attacker")
    victim = _creature(st, "p2", "Victim", toughness=5)
    eng.rules.deal_damage(victim, 2, source=a)
    assert a.instance_id in st.creatures_damaged_by_source_this_turn[victim.instance_id]
    # unrelated creature is untouched
    other = _creature(st, "p2", "Bystander")
    assert other.instance_id not in st.creatures_damaged_by_source_this_turn


def test_damage_to_a_player_is_not_recorded_here():
    eng, st = _engine()
    a = _creature(st, "p1", "Burner")
    eng.rules.deal_damage(st.player_by_id("p2"), 3, source=a)
    assert st.creatures_damaged_by_source_this_turn == {}


def test_begin_turn_clears_the_map():
    eng, st = _engine()
    a = _creature(st, "p1", "A")
    v = _creature(st, "p2", "V", toughness=9)
    eng.rules.deal_damage(v, 1, source=a)
    assert st.creatures_damaged_by_source_this_turn
    eng.begin_turn()
    assert st.creatures_damaged_by_source_this_turn == {}


# --- parser ----------------------------------------------------------


def test_trigger_condition_parses_to_the_group_history_shape():
    card = Card(
        id="bc", name="Testcultist", type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        oracle_text=("Whenever a creature dealt damage by Testcultist this turn "
                     "dies, put a +1/+1 counter on Testcultist."),
    )
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed
    trig = next(s for s in res.specs if s.ability_kind == "triggered")
    cond = trig.trigger["condition"]
    assert cond["subject"] == "group"
    assert cond["damaged_by_source_this_turn"] is True
    assert cond.get("controller") == "any"


def test_real_card_blood_cultist_is_modeled():
    card = Card(
        id="BC", name="Blood Cultist", type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        oracle_text=(
            "{T}: Blood Cultist deals 1 damage to any target.\n"
            "Whenever a creature dealt damage by Blood Cultist this turn dies, "
            "put a +1/+1 counter on Blood Cultist."
        ),
    )
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed


# --- execute --------------------------------------------------------


def test_trigger_fires_only_for_a_creature_this_source_damaged():
    eng, st = _engine()
    src = GameObject(
        Card(id="Cult", name="Blood Cultist", type_line="Creature — Human Wizard",
             is_creature=True, power=1, toughness=1,
             oracle_text=("Whenever a creature dealt damage by Blood Cultist "
                          "this turn dies, put a +1/+1 counter on Blood Cultist.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    bind_from_catalogue(src)

    hit = _creature(st, "p2", "Hit", toughness=1)
    missed = _creature(st, "p2", "Missed", toughness=1)

    eng.rules.deal_damage(hit, 1, source=src)
    eng.rules.deal_damage(missed, 1, source=None)  # damaged by something else

    eng.rules.destroy(hit)
    eng.rules.destroy(missed)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()

    # exactly one +1/+1 counter — from `hit` dying, not `missed`
    assert src.counters.get("+1/+1", 0) == 1


# --- MEC-49 body gaps ------------------------------------------------


def test_abattoir_ghoul_gains_life_equal_to_that_creatures_toughness():
    eng, st = _engine()
    src = GameObject(
        Card(id="AG", name="Abattoir Ghoul", type_line="Creature — Zombie",
             is_creature=True, power=3, toughness=2,
             oracle_text=("Whenever a creature dealt damage by Abattoir Ghoul "
                          "this turn dies, you gain life equal to that "
                          "creature's toughness.")),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    src.controller_id = "p1"
    st.add_to_battlefield(src)
    bind_from_catalogue(src)

    victim = _creature(st, "p2", "BigVictim", power=1, toughness=5)
    eng.rules.deal_damage(victim, 1, source=src)
    eng.rules.destroy(victim, can_be_regenerated=False)
    eng.resolve_until_stable()
    # RULE 400.7 last-known toughness of the dead creature = 5
    assert st.player_by_id("p1").life == 25


def test_abattoir_ghoul_parses():
    card = Card(
        id="AG", name="Abattoir Ghoul", type_line="Creature — Zombie",
        is_creature=True, power=3, toughness=2,
        oracle_text=("First strike\nWhenever a creature dealt damage by "
                     "Abattoir Ghoul this turn dies, you gain life equal to "
                     "that creature's toughness."),
    )
    res = parse_oracle(card)
    assert res.modeled, res.unclaimed
    trig = next(s for s in res.specs if s.ability_kind == "triggered")
    assert trig.effects[0].type == "gain_life"
    assert trig.effects[0].params["amount_from_subject"] == "trigger_subject_toughness"


def test_baron_sengir_plus_two_counter_is_two_plus_one_counters():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
    specs = match_clause("put a +2/+2 counter on ~")
    assert specs and specs[0].type == "add_counters"
    assert specs[0].params["kind"] == "+1/+1"
    assert specs[0].params["count"] == 2

    card = Card(
        id="BS", name="Baron Sengir", type_line="Legendary Creature — Vampire",
        is_creature=True, power=5, toughness=5,
        oracle_text=("Flying\nWhenever a creature dealt damage by Baron Sengir "
                     "this turn dies, put a +2/+2 counter on Baron Sengir."),
    )
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
