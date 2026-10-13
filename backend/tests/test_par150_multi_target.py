"""PAR-150: RULE 115.1a "up to N / up to X target ..." for gain control, goad, counter and keyword grants.

Each family opts into the shared `_MULTI_TARGET_QUANTIFIER`/`_multi_target_params` machinery destroy/tap/return
already use. Parse tests pin the spec shape; the engine tests resolve the *real* effects with 0, 1 and N chosen
targets and check that every chosen target (and only those) is affected.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue, build_effects
from mtg_analyzer.game.effects.core import _apply_effects_partitioned
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_state import GameState
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.player import Player
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


# -- fixtures -----------------------------------------------------------------------------------------------------


def _engine(players: int = 2):
    seats = [Player(id=f"p{i}", name=f"P{i}", life=20) for i in range(1, players + 1)]
    state = GameState(players=seats)
    return GameEngine(state), state


def _source(state, name="Src", types="Sorcery", owner="p1", **kw):
    card = Card(id=name, name=name, type_line=types, is_creature="Creature" in types, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD if "Creature" in types else Zone.HAND)
    obj.controller_id = owner
    if obj.zone == Zone.BATTLEFIELD:
        state.add_to_battlefield(obj)
    return obj


def _creature(state, name, owner="p2", cost=""):
    card = Card(id=name, name=name, type_line="Creature — Bear", is_creature=True, power=2, toughness=2,
                mana_cost_string=cost)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    state.add_to_battlefield(obj)
    return obj


def _resolve(engine, state, clause, targets, source=None):
    """Parse one effect clause, build the real effects and resolve them against ``targets``."""
    specs = parse_effect_body(clause)
    assert specs, clause
    src = source or _source(state)
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, targets, None, source=src)
    return specs, src


# -- parse shapes -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("clause, effect, params", [
    ("gain control of up to 3 target creatures", "gain_control_until_eot", {
        "target_kind": "creature", "optional": True, "target_count": 3,
        "duration": "permanent", "haste": False, "untap": False}),
    ("goad up to 2 target creatures", "goad", {"target_kind": "creature", "count": 2, "optional": True}),
    ("counter up to 2 target spells", "counter", {"target_kind": "spell", "target_count": 2, "optional": True}),
    ("counter up to 4 target spells and/or abilities", "counter",
     {"target_kind": "spell_or_ability", "target_count": 4, "optional": True}),
    ("up to 4 target permanents you control gain indestructible until end of turn", "pump",
     {"target_kind": "permanent_you_control", "target_count": 4, "optional": True, "keywords": ["indestructible"]}),
    ("up to 2 target creatures you control each get +2/+1 until end of turn", "pump",
     {"target_kind": "creature_you_control", "target_count": 2, "optional": True, "power": 2, "toughness": 1}),
    ("up to x target creatures each gain intimidate and haste until end of turn, where x is your devotion to black",
     "pump", {"target_kind": "creature", "count_selector": "devotion_to_black", "target_count": 10,
              "optional": True, "keywords": ["intimidate", "haste"]}),
    ("up to x target creatures gain flying until end of turn, where x is the number of times ~ was kicked",
     "pump", {"target_kind": "creature", "count_selector": "source_kicker_count", "target_count": 10,
              "optional": True, "keywords": ["flying"]}),
    ("x target creatures gain islandwalk until end of turn", "pump",
     {"target_kind": "creature", "count_selector": "source_x_paid", "target_count": 10, "optional": True,
      "keywords": ["islandwalk"]}),
])
def test_plural_forms_parse(clause, effect, params):
    [spec] = parse_effect_body(clause)
    assert spec.type == effect
    assert spec.params == params


def test_single_counter_and_unknown_x_definitions_stay_unclaimed():
    assert parse_effect_body("counter up to 1 target spell") is None  # N=1 is the singular row's job
    assert parse_effect_body(
        "up to x target creatures gain flying until end of turn, where x is the number of lands you control"
    ) is None


def test_goad_range_is_refused_because_goad_has_no_count_max():
    assert parse_effect_body("goad 1 or 2 target creatures") is None


# -- gain control -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("picked", [0, 1, 3])
def test_gain_control_takes_every_chosen_target(picked):
    engine, state = _engine()
    pool = [_creature(state, f"C{i}") for i in range(4)]
    _resolve(engine, state, "gain control of up to 3 target creatures", pool[:picked])
    assert [c.controller_id for c in pool] == ["p1" if i < picked else "p2" for i in range(4)]


def test_gain_control_slices_a_longer_shared_list_to_its_own_count():
    engine, state = _engine()
    pool = [_creature(state, f"C{i}") for i in range(4)]
    _resolve(engine, state, "gain control of up to 3 target creatures", pool)
    assert [c.controller_id for c in pool] == ["p1", "p1", "p1", "p2"]


def test_jace_ingenious_mind_mage_minus_nine_is_modeled_with_three_optional_targets():
    card = Card(id="Jace", name="Jace", type_line="Legendary Planeswalker — Jace",
                oracle_text="−9: Gain control of up to three target creatures.")
    assert parse_oracle(card).coverage == MODELED
    [effect] = build_effects(parse_effect_body("gain control of up to 3 target creatures"), _source(_engine()[1]))
    assert (effect.target_spec.count, effect.target_spec.optional) == (3, True)


def test_up_to_one_gain_control_is_now_optional_in_the_engine():
    # The parser always emitted ``optional`` for "up to one"; the factory used to drop it.
    [effect] = build_effects(parse_effect_body("gain control of up to 1 target creature until end of turn"),
                             _source(_engine()[1]))
    assert effect.target_spec.optional is True


def test_hideous_taskmaster_takes_one_creature_per_opponent_and_grants_the_rider_keywords():
    engine, state = _engine(players=3)
    taken = [_creature(state, "A", owner="p2"), _creature(state, "B", owner="p3")]
    spare = _creature(state, "C", owner="p2")
    specs = parse_effect_body(
        "for each opponent, gain control of up to 1 target creature that player controls until end of turn. "
        "untap those creatures. they gain trample, haste, and annihilator 1 until end of turn"
    )
    assert [s.type for s in specs] == ["gain_control_until_eot", "pump"]
    src = _source(state, "Taskmaster", "Creature — Eldrazi")
    effects = build_effects(specs, src)
    spec = effects[0].target_spec
    assert spec.count_selector == "opponents" and spec.distinct_controllers is True
    assert targeting.resolved_count(spec, state, "p1", src) == 2  # one pick per opponent
    _apply_effects_partitioned(effects, engine.rules.context, taken, None, source=src)
    engine.recompute_continuous_effects()
    assert [c.controller_id for c in taken] == ["p1", "p1"] and spare.controller_id == "p2"
    for creature in taken:
        assert {"haste", "trample"} <= set(creature.temp_keywords)
        assert creature.temp_parametric_keywords == {"annihilator": 1}
    assert not spare.temp_keywords and not spare.temp_parametric_keywords


# -- goad ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("picked", [0, 1, 2])
def test_goad_up_to_two_goads_every_chosen_creature(picked):
    engine, state = _engine()
    pool = [_creature(state, f"C{i}") for i in range(3)]
    _resolve(engine, state, "goad up to 2 target creatures", pool[:picked])
    assert [bool(c.goaded_by) for c in pool] == [i < picked for i in range(3)]
    assert all(c.goaded_by == {"p1"} for c in pool[:picked])


def test_goad_up_to_two_target_spec_is_a_two_pick_optional_requirement():
    [effect] = build_effects(parse_effect_body("goad up to 2 target creatures"), _source(_engine()[1]))
    assert (effect.target_spec.count, effect.target_spec.optional) == (2, True)


def test_sontaran_general_goads_one_creature_per_opponent_and_stops_exactly_those_from_blocking():
    card = Card(id="Sontaran", name="Sontaran General", type_line="Creature — Alien Soldier", is_creature=True,
                oracle_text="Trample, haste\nBattalion — Whenever this creature and at least two other creatures "
                            "attack, for each opponent, goad up to one target creature that player controls. "
                            "Those creatures can't block this turn.")
    assert parse_oracle(card).coverage == MODELED
    engine, state = _engine(players=3)
    goaded = [_creature(state, "A", owner="p2"), _creature(state, "B", owner="p3")]
    bystander = _creature(state, "C", owner="p2")
    specs = parse_effect_body(
        "for each opponent, goad up to 1 target creature that player controls. "
        "those creatures can't block this turn"
    )
    assert [s.type for s in specs] == ["goad", "cant_block_this_turn"]
    src = _source(state, "Sontaran General", "Creature — Alien Soldier")
    effects = build_effects(specs, src)
    assert effects[0].target_spec.distinct_controllers is True  # one creature per opponent
    assert targeting.resolved_count(effects[0].target_spec, state, "p1", src) == 2
    _apply_effects_partitioned(effects, engine.rules.context, goaded, None, source=src)
    assert all(c.goaded_by == {"p1"} and c.temp_cant_block for c in goaded)
    assert not bystander.goaded_by and not bystander.temp_cant_block


# -- keyword grants and pumps -------------------------------------------------------------------------------------


@pytest.mark.parametrize("picked", [0, 1, 4])
def test_invisible_force_field_grants_indestructible_to_each_chosen_permanent(picked):
    engine, state = _engine()
    pool = [_creature(state, f"C{i}", owner="p1") for i in range(5)]
    _resolve(engine, state, "up to 4 target permanents you control gain indestructible until end of turn",
             pool[:picked])
    assert [("indestructible" in c.temp_keywords) for c in pool] == [i < picked for i in range(5)]


def test_pump_multi_target_pumps_only_its_own_count_of_a_longer_list():
    engine, state = _engine()
    pool = [_creature(state, f"C{i}", owner="p1") for i in range(3)]
    _resolve(engine, state, "up to 2 target creatures you control each get +2/+1 until end of turn", pool)
    engine.recompute_continuous_effects()
    assert [(c.power, c.toughness) for c in pool] == [(4, 3), (4, 3), (2, 2)]


def test_voyager_drake_x_is_the_number_of_times_it_was_kicked():
    engine, state = _engine()
    drake = _source(state, "Voyager Drake", "Creature — Drake")
    [effect] = build_effects(parse_effect_body(
        "up to x target creatures gain flying until end of turn, where x is the number of times ~ was kicked"
    ), drake)
    spec = effect.target_spec
    for kicks in (0, 1, 3):
        drake.kicker_count = kicks
        assert targeting.resolved_count(spec, state, "p1", drake) == kicks
    pool = [_creature(state, f"C{i}", owner="p1") for i in range(3)]
    drake.kicker_count = 2
    _apply_effects_partitioned([effect], engine.rules.context, pool[:2], None, source=drake)
    assert [("flying" in c.temp_keywords) for c in pool] == [True, True, False]


def test_mogis_marauder_x_is_the_controllers_devotion_to_black():
    engine, state = _engine()
    marauder = _source(state, "Mogis's Marauder", "Creature — Human", mana_cost_string="{4}{B}{B}")
    state.add_to_battlefield(marauder) if marauder.zone != Zone.BATTLEFIELD else None
    marauder.zone = Zone.BATTLEFIELD
    [effect] = build_effects(parse_effect_body(
        "up to x target creatures each gain intimidate and haste until end of turn, where x is your devotion to black"
    ), marauder)
    spec = effect.target_spec
    assert targeting.resolved_count(spec, state, "p1", marauder) == 2  # {B}{B}
    _creature(state, "Extra", owner="p1", cost="{1}{B}")
    assert targeting.resolved_count(spec, state, "p1", marauder) == 3
    _creature(state, "Opponent's", owner="p2", cost="{B}{B}{B}")  # never counts toward p1's devotion
    assert targeting.resolved_count(spec, state, "p1", marauder) == 3
    pool = [_creature(state, f"T{i}", owner="p1") for i in range(2)]
    _apply_effects_partitioned([effect], engine.rules.context, pool, None, source=marauder)
    assert all({"intimidate", "haste"} <= set(c.temp_keywords) for c in pool)


def test_x_spell_reads_the_announced_x_as_the_target_count():
    engine, state = _engine()
    spell = _source(state, "Part Water")
    spell.x_paid = 2
    pool = [_creature(state, f"C{i}", owner="p2") for i in range(3)]
    specs, _ = _resolve(engine, state, "x target creatures gain islandwalk until end of turn", pool[:2], source=spell)
    [effect] = build_effects(specs, spell)
    assert targeting.resolved_count(effect.target_spec, state, "p1", spell) == 2
    assert [("islandwalk" in c.temp_keywords) for c in pool] == [True, True, False]


# -- counter ------------------------------------------------------------------------------------------------------


def _filler(name):
    return Card(id=name, name=name, type_line="Instant", mana_cost_string="{0}", converted_mana_cost=0,
                is_instant=True, oracle_text="")


def _stack_two_spells():
    engine = GameEngine.new_game(
        [("p1", "Alice", [_filler("f")] * 5), ("p2", "Bob", [_filler("g")] * 5)], starting_hand=0,
    )
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    spells = []
    for n in range(3):
        obj = GameObject(_filler(f"Bolt{n}"), owner_id="p2", zone=Zone.HAND)
        p2.hand.append(obj)
        engine.cast_spell(p2, obj)
        spells.append(obj)
    return engine, p1, spells


def _double_negative(engine, p1):
    card = Card(id="DN", name="Double Negative", type_line="Instant", mana_cost_string="{0}",
                converted_mana_cost=0, is_instant=True, oracle_text="Counter up to two target spells.")
    assert parse_oracle(card).coverage == MODELED
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    p1.hand.append(obj)
    return obj


@pytest.mark.parametrize("picked", [0, 1, 2])
def test_double_negative_counters_each_chosen_spell(picked):
    engine, p1, spells = _stack_two_spells()
    dn = _double_negative(engine, p1)
    reqs = targeting.requirements_with_targets(engine.state, "p1", dn)
    assert reqs[0]["count"] == 2 and targeting.all_requirements_satisfiable(reqs)
    engine.cast_spell(p1, dn, targets=spells[:picked])
    engine.rules.resolve_top_of_stack()  # Double Negative itself
    countered = [s.zone == Zone.GRAVEYARD for s in spells]
    assert countered == [i < picked for i in range(3)]
    assert all(s.zone == Zone.STACK for s in spells[picked:])


def test_double_negative_ignores_a_third_target_in_a_shared_list():
    engine, p1, spells = _stack_two_spells()
    dn = _double_negative(engine, p1)
    engine.cast_spell(p1, dn, targets=spells[:2])
    engine.rules.resolve_top_of_stack()
    assert [s.zone for s in spells] == [Zone.GRAVEYARD, Zone.GRAVEYARD, Zone.STACK]


def test_katara_reversal_offers_the_spell_or_ability_pool():
    # RULE 701.5b: abilities on the stack are legal counter targets (`spell_or_ability`, Disallow's pool).
    [effect] = build_effects(parse_effect_body("counter up to 4 target spells and/or abilities"), _source(_engine()[1]))
    assert (effect.target_spec.kind, effect.target_spec.count, effect.target_spec.optional) == ("spell_or_ability", 4, True)


# -- announce-time X: a dynamic count that resolves to N asks for exactly N picks ------------------------------------


_DRAKE_TEXT = (
    "Multikicker {U}\nFlying\nWhen this creature enters, up to X target creatures gain flying until end of turn, "
    "where X is the number of times this creature was kicked."
)


def _drake_game(kicks: int):
    bear = Card(id="b", name="Bear", type_line="Creature — Bear", is_creature=True, power=2, toughness=2)
    engine = GameEngine.new_game([("p1", "A", [bear] * 5), ("p2", "B", [bear] * 5)], starting_hand=0)
    p1 = engine.state.player_by_id("p1")
    drake_card = Card(id="d", name="Voyager Drake", type_line="Creature — Drake", is_creature=True, power=2,
                      toughness=2, mana_cost_string="{3}{U}", converted_mana_cost=4, oracle_text=_DRAKE_TEXT,
                      keywords=["Multikicker", "Flying"])
    drake = GameObject(drake_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(drake)
    p1.hand.append(drake)
    bears = []
    for _ in range(4):
        b = GameObject(bear, owner_id="p1", zone=Zone.BATTLEFIELD)
        b.controller_id = "p1"
        engine.state.add_to_battlefield(b)
        bears.append(b)
    engine.state.current_step = "main1"
    p1.mana_pool.add_many({"U": 14, "C": 4})
    engine.cast_spell(p1, drake, None, 0, kicked=kicks)
    engine.resolve_until_stable()
    return engine, bears


def test_unkicked_voyager_drake_asks_for_no_target_at_all():
    engine, bears = _drake_game(kicks=0)
    assert engine.state.pending_choice is None
    assert not any("flying" in b.temp_keywords for b in bears)


@pytest.mark.parametrize("kicks, stop_after, expected", [(2, None, 2), (2, 1, 1), (3, 0, 0), (9, None, 4)])
def test_kicked_voyager_drake_offers_one_round_per_kick_and_flies_exactly_the_picks(kicks, stop_after, expected):
    engine, bears = _drake_game(kicks=kicks)
    picks = 0
    while engine.state.pending_choice is not None:
        options = [o for o in engine.state.pending_choice["options"] if o.get("id") != "stop"]
        if stop_after is not None and picks >= stop_after:
            engine.rules.resolve_choice("stop")
        else:
            engine.rules.resolve_choice(str(options[0]["id"]))
            picks += 1
    engine.resolve_until_stable()
    assert picks == expected  # capped by the kicks, then by the four creatures on the table
    assert sum("flying" in b.temp_keywords for b in bears) == expected


def _stack_spell_and_ability():
    """p2 has a spell *and* an activated ability on the stack (RULE 701.5b: abilities are legal counter targets)."""
    from mtg_analyzer.models.game.game_state import StackItem

    engine = GameEngine.new_game(
        [("p1", "Alice", [_filler("f")] * 5), ("p2", "Bob", [_filler("g")] * 5)], starting_hand=0,
    )
    p1, p2 = engine.state.player_by_id("p1"), engine.state.player_by_id("p2")
    spell = GameObject(_filler("Bolt"), owner_id="p2", zone=Zone.HAND)
    p2.hand.append(spell)
    engine.cast_spell(p2, spell)
    gizmo = GameObject(Card(id="g", name="Gizmo", type_line="Artifact"), owner_id="p2", zone=Zone.BATTLEFIELD)
    engine.state.add_to_battlefield(gizmo)
    ability = StackItem(kind="ability", controller_id="p2", source=gizmo, description="Gizmo's ability", effects=[],
                        targets=[])
    engine.state.stack.append(ability)
    return engine, p1, spell, ability


@pytest.mark.parametrize("picks", ["none", "spell", "both"])
def test_katara_reversal_counters_the_chosen_spells_and_abilities(picks):
    engine, p1, spell, ability = _stack_spell_and_ability()
    card = Card(id="K", name="Katara's Reversal", type_line="Instant", mana_cost_string="{0}", converted_mana_cost=0,
                is_instant=True, oracle_text="Counter up to four target spells and/or abilities.")
    assert parse_oracle(card).coverage == MODELED
    katara = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(katara)
    p1.hand.append(katara)
    options = targeting.legal_targets(engine.state, "p1", targeting.TargetSpec(kind="spell_or_ability"))
    assert {"instance_id", "stack_id"} <= {k for o in options for k in o}  # the pool offers both kinds
    chosen = {"none": [], "spell": [spell], "both": [spell, ability]}[picks]
    engine.cast_spell(p1, katara, targets=chosen)
    engine.rules.resolve_top_of_stack()
    assert (spell.zone == Zone.GRAVEYARD) == (picks != "none")
    assert (ability in engine.state.stack) == (picks != "both")


# -- the plural pronouns and spellings the multi-target clauses pull along ---------------------------------------


def test_return_up_to_two_accepts_the_singular_owners_hand_wording():
    [spec] = parse_effect_body("return up to 2 target creatures to their owner's hand")
    assert (spec.type, spec.params) == ("return_to_hand", {"target_kind": "creature", "count": 2, "optional": True})


@pytest.mark.parametrize("picked", [0, 1, 2])
def test_coronation_of_chaos_stops_the_blockers_and_goads_them(picked):
    engine, state = _engine()
    pool = [_creature(state, f"C{i}") for i in range(3)]
    specs = parse_effect_body("up to 3 target creatures can't block this turn. goad them")
    assert [s.type for s in specs] == ["cant_block_this_turn", "goad"]
    src = _source(state)
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, pool[:picked], None, source=src)
    assert [c.temp_cant_block for c in pool] == [i < picked for i in range(3)]
    assert [bool(c.goaded_by) for c in pool] == [i < picked for i in range(3)]


def test_sudden_storm_taps_both_targets_and_keeps_both_from_untapping():
    engine, state = _engine()
    pool = [_creature(state, f"C{i}") for i in range(3)]
    specs = parse_effect_body(
        "tap up to 2 target creatures. those creatures don't untap during their controllers' next untap steps"
    )
    assert [s.type for s in specs] == ["tap", "skip_next_untap"]
    src = _source(state)
    _apply_effects_partitioned(build_effects(specs, src), engine.rules.context, pool[:2], None, source=src)
    assert [c.tapped for c in pool] == [True, True, False]
    assert [c.skip_next_untap for c in pool] == [True, True, False]


# -- RULE 611.2b: "gain control of ... for as long as you control ~" -------------------------------------------------

_RANGERS = "gain control of up to 1 target creature with lesser power for as long as you control ~"


def _rangers_steal():
    engine, state = _engine()
    rangers = _source(state, "Rangers of Ithilien", "Creature — Human Soldier")
    rangers.card.power, rangers.card.toughness = 3, 3
    weak = _creature(state, "Weak")  # power 2 < 3
    strong = _creature(state, "Strong")
    strong.card.power = 4
    specs = parse_effect_body(_RANGERS)
    effects = build_effects(specs, rangers)
    engine.recompute_continuous_effects()
    options = targeting.legal_targets(state, "p1", effects[0].target_spec, source=rangers)
    assert {o["instance_id"] for o in options} == {weak.instance_id}  # "lesser power" is vs. Rangers
    _apply_effects_partitioned(effects, engine.rules.context, [weak], None, source=rangers)
    assert weak.controller_id == "p1" and weak.control_change_while_source
    return engine, state, rangers, weak


def test_rangers_of_ithilien_is_modeled():
    card = Card(id="R", name="Rangers of Ithilien", type_line="Creature — Human Soldier", is_creature=True,
                power=3, toughness=3, keywords=["Vigilance"],
                oracle_text="Vigilance\nWhen this creature enters, " + _RANGERS.replace("~", "this creature")
                + ". Then the Ring tempts you.")
    assert parse_oracle(card).coverage == MODELED


def test_stolen_creature_stays_while_you_keep_controlling_the_source():
    engine, state, rangers, weak = _rangers_steal()
    engine.rules.check_state_based_actions()
    assert weak.controller_id == "p1"


def test_stolen_creature_goes_back_when_the_source_leaves():
    engine, state, rangers, weak = _rangers_steal()
    state.remove_from_battlefield(rangers)
    engine.rules.check_state_based_actions()
    assert weak.controller_id == "p2" and weak.control_change_while_source is None


def test_stolen_creature_goes_back_when_the_source_is_stolen():
    engine, state, rangers, weak = _rangers_steal()
    rangers.controller_id = "p2"
    engine.rules.check_state_based_actions()
    assert weak.controller_id == "p2"


def test_stolen_creature_does_not_come_back_to_you_when_the_source_returns_as_a_new_object():
    engine, state, rangers, weak = _rangers_steal()
    state.remove_from_battlefield(rangers)
    engine.rules.check_state_based_actions()
    rangers.reset_as_new_object() if hasattr(rangers, "reset_as_new_object") else None
    state.add_to_battlefield(rangers)
    rangers.controller_id = "p1"
    engine.rules.check_state_based_actions()
    assert weak.controller_id == "p2"  # RULE 611.2b: the effect ended for good


def test_sower_of_temptation_takes_its_target_only_while_it_remains_on_the_battlefield():
    engine, state = _engine()
    sower = _source(state, "Sower of Temptation", "Creature — Faerie Wizard", power=2, toughness=2)
    victim = _creature(state, "Victim")
    _resolve(engine, state, "gain control of target creature for as long as ~ remains on the battlefield",
             [victim], source=sower)
    assert victim.controller_id == "p1"
    engine.rules.check_state_based_actions()
    assert victim.controller_id == "p1"
    state.remove_from_battlefield(sower)
    engine.rules.check_state_based_actions()
    assert victim.controller_id == "p2"


def test_willbreaker_style_group_trigger_steals_the_firing_creature_while_the_source_is_controlled():
    from mtg_analyzer.game.effects.composition import TriggerSubjectReferentEffect

    engine, state = _engine()
    willbreaker = _source(state, "Willbreaker", "Creature — Human Wizard", power=2, toughness=2)
    victim = _creature(state, "Victim")
    [spec] = parse_effect_body("gain control of target creature for as long as you control ~")
    body = TriggerSubjectReferentEffect(effects=[spec.to_dict()], event_key="target_id", source=willbreaker)
    ctx = engine.rules.context
    ctx.trigger_event = {"target_id": victim.instance_id}
    body.apply(ctx, None)
    assert victim.controller_id == "p1" and victim.control_change_while_source
