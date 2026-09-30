"""PAR-141/142 residue: the pronoun-comma connector, host-pronoun conditions, conjoined intervening-ifs,
"for as long as it has a <counter> counter on it" durations, "it's a …" riders and "that's attacking you"."""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition, static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle as _parse
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter
from tests.test_par120_count_phrase import _creature, _put
from tests.test_par123_referent import _pay


def _modeled(oracle: str, types: str = "Creature — Bear", name: str = "Source") -> bool:
    return _parse(Card(id=name, name=name, type_line=types, oracle_text=oracle)).modeled


# --- Olivia: a comma before a pronoun-led clause, inside the "if you do" gate ------------------------

OLIVIA = (
    "Whenever another creature you control enters, you may discard a card. If you do, put a +1/+1 counter "
    "on that creature, it gains haste until end of turn, and it becomes a Vampire in addition to its other types."
)


def test_olivia_gates_every_clause_on_the_payment():
    assert _modeled(OLIVIA, "Legendary Creature — Vampire", "Olivia")
    [spec] = [s for s in _parse(Card(id="O", name="O", type_line="Creature — Vampire", oracle_text=OLIVIA)).specs
              if s.ability_kind == "triggered"]
    [pay] = spec.effects
    assert pay.type == "pay_cost_then" and pay.params["cost"] == "discard a card"
    inner = [e["type"] for e in pay.params["effects"]]
    assert inner.count("grant_until") == 1 and "pump" in repr(pay.params["effects"])  # nothing escapes the gate


def test_olivia_pays_and_the_entering_creature_gets_all_three():
    engine, state = _engine()
    _put(state, OLIVIA, name="Olivia", types="Legendary Creature — Vampire")
    state.player_by_id("p1").hand.append(GameObject(Card(id="F", name="Fodder", type_line="Sorcery"),
                                                    owner_id="p1", zone=Zone.HAND))
    late = _creature(state, "Late")
    _fire_enter(engine, state, late)
    _pay(engine, state)
    engine.recompute_continuous_effects()
    assert late.counters.get("+1/+1") == 1 and "Vampire" in late._added_subtypes
    assert "haste" in late.temp_keywords


def test_olivia_declined_changes_nothing():
    engine, state = _engine()
    _put(state, OLIVIA, name="Olivia", types="Legendary Creature — Vampire")
    state.player_by_id("p1").hand.append(GameObject(Card(id="F", name="Fodder", type_line="Sorcery"),
                                                    owner_id="p1", zone=Zone.HAND))
    late = _creature(state, "Late")
    _fire_enter(engine, state, late)
    _pay(engine, state, "decline")
    engine.recompute_continuous_effects()
    assert not late.counters.get("+1/+1") and "Vampire" not in late._added_subtypes
    assert "haste" not in late.temp_keywords


def test_the_pronoun_comma_never_splits_inside_a_gated_body():
    # Split across the gate, "it gains …" would fall outside "if you do".
    specs = parse_effect_body(
        "you may discard a card. if you do, put a +1/+1 counter on ~, it gains haste until end of turn",
        self_subject=True,
    )
    assert specs is None or [s.type for s in specs] == ["pay_cost_then"]


# --- conditions ------------------------------------------------------------------------------------


def test_conjoined_conditions_compose_with_all():
    cond = static_condition("you haven't cast a spell from your hand this turn and ~ doesn't have a flying counter on it")
    assert cond["kind"] == "all" and len(cond["conditions"]) == 2
    assert static_condition("you control a blorp and ~ is wobbly") is None  # one unknown half fails closed


def test_not_a_creature_is_the_negated_card_type_read():
    assert static_condition("~ isn't a creature") == {
        "kind": "not", "condition": {"kind": "is_card_type", "card_type": "creature"},
    }


def test_a_host_pronoun_state_reads_the_enchanted_creature_not_the_aura():
    [spec, *_] = static_effect_specs(
        "enchanted creature has first strike as long as it's blocking and you control a snow land"
    )
    gate = spec.params["active_if"]
    assert gate["kind"] == "all"
    assert {"kind": "source_blocking", "of": "attached"} in gate["conditions"]


def test_emergent_haunting_becomes_a_creature_only_while_it_is_not_one():
    oracle = (
        "At the beginning of your end step, if you haven't cast a spell from your hand this turn and this "
        "creature isn't a creature, it becomes a 3/3 Spirit creature with flying in addition to its other types."
    )
    assert _modeled(oracle, "Enchantment", "Emergent Haunting")


# --- "for as long as it has a <counter> counter on it" ---------------------------------------------


def test_a_counter_duration_retimes_the_type_addition():
    specs = parse_effect_body(
        "put a flood counter on target land. that land is an island in addition to its other types for as long "
        "as it has a flood counter on it"
    )
    assert [s.type for s in specs] == ["add_counters", "grant_until"]
    grant = specs[1].params
    assert grant["duration"] == "for_as_long_as" and grant["previous_subject"] is True
    assert grant["condition"] == {"kind": "source_counters", "counter": "flood", "min": 1, "of": "affected"}


def test_a_counter_duration_needs_a_pick_and_a_retimable_body():
    assert parse_effect_body("it is an island in addition to its other types for as long as it has a flood counter on it") is None
    assert parse_effect_body("draw a card for as long as it has a flood counter on it", previous_subject=True) is None


def test_aquitects_will_makes_the_land_an_island_only_while_the_counter_stays():
    oracle = (
        "Put a flood counter on target land. That land is an Island in addition to its other types for as long "
        "as it has a flood counter on it. If you control a Merfolk, draw a card."
    )
    engine, state = _engine()
    land = _put(state, "", name="Plains", types="Basic Land — Plains", is_land=True)
    spell = GameObject(Card(id="A", name="Aquitect's Will", type_line="Tribal Sorcery — Merfolk",
                            oracle_text=oracle, is_sorcery=True), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    state.player_by_id("p1").hand.append(spell)
    engine.begin_turn()
    state.current_step = "main1"
    state.player_by_id("p1").mana_pool.add_many({"U": 2})
    engine.cast_spell(state.player_by_id("p1"), spell, targets=[land])
    engine.resolve_until_stable()
    engine.recompute_continuous_effects()
    assert land.counters.get("flood") == 1 and "Island" in land._added_subtypes
    engine.rules.add_counters(land, -1, "flood")
    engine.recompute_continuous_effects()
    assert "Island" not in land._added_subtypes


# --- "it's a … in addition" after a counter on a named land/creature ------------------------------


def test_minas_morgul_shape_is_modeled():
    assert _modeled(
        "{3}{B}, {T}: Put a shadow counter on target creature. For as long as that creature has a shadow "
        "counter on it, it's a Wraith in addition to its other types.",
        "Legendary Land", "Minas Morgul",
    )


# --- a dies-trigger gate on "it" must not be claimed while it cannot hold ---------------------------


def test_a_dies_trigger_gate_on_it_fails_closed_until_last_known_information_exists():
    # Both cards read `previous_target`, which no clause made: they would silently never act.
    assert not _modeled(
        "When this creature dies, if it wasn't a Demon, return it to the battlefield under its owner's control "
        "with two +1/+1 counters on it. It's a Demon in addition to its other types.", "Creature — Human", "Vessel",
    )
    assert not _modeled(
        "When this creature dies, if it was a creature, return this card to its owner's hand.", "Artifact", "Totem",
    )


def test_a_self_return_with_counters_makes_the_returned_permanent_the_next_it():
    specs = parse_effect_body(
        "return it to the battlefield under its owner's control with 2 +1/+1 counters on it. "
        "it's a demon in addition to its other types",
        self_subject=True,
    )
    assert [s.type for s in specs] == ["return_self_to_battlefield", "grant_until"]
    assert specs[0].params["extra_counters"] == {"kind": "+1/+1", "count": 2}
    assert specs[1].params["previous_subject"] is True


def test_a_self_return_hands_the_returned_permanent_to_the_next_clause():
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.registry import EffectRegistry

    engine, state = _engine()
    card = GameObject(Card(id="V", name="V", type_line="Creature — Human", is_creature=True, power=1, toughness=1),
                      owner_id="p1", zone=Zone.GRAVEYARD)
    state.player_by_id("p1").graveyard.append(card)
    effect = EffectRegistry.create("return_self_to_battlefield", {"extra_counters": {"kind": "+1/+1", "count": 2}})
    effect.source = card
    context = GameContext(state, engine.rules)
    effect.apply(context)
    assert card in state.battlefield and card.counters.get("+1/+1") == 2
    assert context.previous_targets == [card]


# --- token copies: adjective target, more "except" modifiers, the granted end-step clause ----------------


def test_copy_tail_modifiers():
    from mtg_analyzer.parser.oracle.catalogue.handlers import _parse_copy_except_tail as tail

    assert tail("it's an enchantment in addition to its other types") == {"add_types": ["Enchantment"]}
    assert tail("it's legendary") == {"legendary": True}
    assert tail("it isn't legendary and is a mutant in addition to its other types") == {
        "not_legendary": True, "add_subtypes": ["Mutant"],
    }
    assert tail("it's a blorp in addition to its other types") is None  # an unknown word fails the tail closed


def test_the_end_step_grant_becomes_a_delayed_trigger_on_the_copy():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    specs = match_clause(
        'create a token that\'s a copy of target creature you control, except it has haste and "at the beginning '
        'of the end step, sacrifice ~."'
    )
    assert [s.type for s in specs] == ["copy_permanent", "create_delayed_trigger"]
    assert specs[0].params["haste"] is True
    assert specs[1].params["effects"] == [{"type": "sacrifice_specific", "params": {}}]
    assert specs[1].params["step"] == "end"


def test_kiki_jiki_only_copies_nonlegendary_creatures():
    from mtg_analyzer.game.targeting import TargetSpec, legal_targets

    engine, state = _engine()
    plain = _put(state, "", name="Plain", types="Creature — Goblin")
    legend = _put(state, "", name="Legend", types="Legendary Creature — Goblin")
    legend.card.is_legendary = True
    [spec] = parse_effect_body("create a token that's a copy of target nonlegendary creature you control, except it has haste")[:1]
    assert spec.params["creature_filter"] == {"nonlegendary": True}
    pool = TargetSpec(kind=spec.params["target_kind"], creature_filter=spec.params["creature_filter"])
    assert {t["name"] for t in legal_targets(state, "p1", pool)} == {"Plain"}


def test_a_copy_can_be_made_legendary_and_an_enchantment():
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.registry import EffectRegistry

    engine, state = _engine()
    original = _put(state, "", name="Plain", types="Artifact")
    effect = EffectRegistry.create("copy_permanent", {
        "target_kind": "artifact", "legendary": True, "add_types": ["Enchantment"],
    })
    effect.source = original
    context = GameContext(state, engine.rules)
    effect.apply(context, [original])
    [token] = [o for o in state.battlefield if o is not original and o.name == "Plain"]
    assert token.card.is_legendary and "Legendary" in token.card.type_line and "Enchantment" in token.card.type_line


# --- "you may have ~ enter as a copy of …" ---------------------------------------------------------------

CLONE = "You may have this creature enter as a copy of any creature on the battlefield."


def _enter_copy_effect(oracle: str, type_line: str = "Creature — Shapeshifter"):
    result = _parse(Card(id="C", name="Clone", type_line=type_line, oracle_text=oracle, is_creature="Creature" in type_line,
                         power=0 if "Creature" in type_line else None, toughness=0 if "Creature" in type_line else None))
    assert result.modeled, oracle
    [spec] = [s for s in result.specs if s.ability_kind == "enter_replacement"]
    [effect] = spec.effects
    return effect


def test_enter_as_copy_forms_parse():
    assert _enter_copy_effect(CLONE).params == {"target_kind": "creature"}
    artifact = _enter_copy_effect(
        "You may have this enchantment enter as a copy of any artifact on the battlefield, except it's an "
        "enchantment in addition to its other types.", "Enchantment",
    )
    assert artifact.params == {"target_kind": "artifact", "add_types": ["Enchantment"]}
    soldier = _enter_copy_effect(
        "You may have this creature enter as a copy of any creature on the battlefield, except it isn't legendary, "
        "is an artifact in addition to its other types, and has flying.",
    )
    assert soldier.params == {
        "target_kind": "creature", "not_legendary": True, "add_types": ["Artifact"], "add_keywords": ["Flying"],
    }


@pytest.mark.parametrize("oracle", [
    "You may have this creature enter as a copy of any creature card in a graveyard.",      # not a battlefield pool
    "You may have this creature enter as a copy of any creature on the battlefield, except it's a blorp in addition to its other types.",
    'You may have this creature enter as a copy of any creature on the battlefield, except it has "{T}: Draw a card."',
])
def test_enter_as_copy_fails_closed(oracle):
    assert not _modeled(oracle, "Creature — Shapeshifter", "Clone")


def test_clone_copies_the_chosen_creature():
    from tests.support.game import creature, make_engine, obj_on_battlefield

    clone_card = Card(id="clone", name="Clone", type_line="Creature — Shapeshifter", oracle_text=CLONE,
                      is_creature=True, power=0, toughness=0, mana_cost_string="{3}{U}")
    eng = make_engine([clone_card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 6})
    clone = p1.hand[0]
    bind_from_catalogue(clone)
    target = obj_on_battlefield(eng.state, eng, creature(name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6))
    bind_from_catalogue(target)
    eng.cast_spell(p1, clone)
    eng.resolve_until_stable()
    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "enter_as_copy"
    option = next(o for o in pending["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(option["id"])
    assert clone.card.name == "Grave Titan" and (clone.power, clone.toughness) == (6, 6)
    assert clone in eng.state.battlefield


def test_a_not_legendary_copy_drops_the_legendary_supertype():
    from tests.support.game import creature, make_engine, obj_on_battlefield

    card = Card(id="as", name="Auton Soldier", type_line="Artifact Creature — Soldier", is_creature=True,
                power=0, toughness=0, mana_cost_string="{3}{U}",
                oracle_text="You may have this creature enter as a copy of any creature on the battlefield, except "
                            "it isn't legendary.")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"U": 2, "C": 6})
    clone = p1.hand[0]
    bind_from_catalogue(clone)
    target = obj_on_battlefield(eng.state, eng, creature(
        name="Grave Titan", cost="{4}{B}{B}", power=6, toughness=6, is_legendary=True,
        type_line="Legendary Creature — Giant Zombie"))
    bind_from_catalogue(target)
    eng.cast_spell(p1, clone)
    eng.resolve_until_stable()
    option = next(o for o in eng.state.pending_choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(option["id"])
    assert clone.card.name == "Grave Titan" and not clone.card.is_legendary
    assert "Legendary" not in clone.card.type_line


# --- attached colours / base P/T and literal group type additions ------------------------------------------


def test_attached_color_and_base_pt_parse():
    specs = static_effect_specs(
        "equipped creature has base power and toughness 5/5, has menace, and is a black Demon in addition to "
        "its other colors and types"
    )
    assert [s.type for s in specs] == ["color", "grant_keyword", "type_change"]
    assert specs[0].params == {"affects": "attached_permanent", "colors": ["B"], "set": False}
    assert specs[2].params == {"affects": "attached_permanent", "add_subtypes": ["Demon"], "power": 5, "toughness": 5}
    # A colour with no "other colors and types" would mean "exactly that colour": not modelled.
    assert static_effect_specs("enchanted creature is a black Demon in addition to its other types") is None


def test_angelic_armaments_adds_a_colour_a_type_and_the_pump():
    from tests.test_par141_target_quality import _attach  # same Aura/Equipment harness as the type-addition tests

    engine, state = _engine()
    bear = _put(state, "", name="Bear", types="Creature — Bear")
    _attach(engine, Card(
        id="AA", name="Angelic Armaments", type_line="Artifact — Equipment",
        oracle_text="Equipped creature gets +2/+2, has flying, and is a white Angel in addition to its other colors "
                    "and types.\nEquip {3}",
    ), bear)
    assert (bear.power, bear.toughness) == (4, 4)
    assert "Angel" in bear._added_subtypes and "W" in {str(c).upper() for c in bear.colors}


def test_group_type_addition_respects_its_token_scope():
    specs = static_effect_specs("creature tokens you control are squirrels in addition to their other creature types")
    assert specs[0].params == {"affects": "creatures_you_control", "tokens": True, "add_subtypes": ["Squirrel"]}
    [forest] = static_effect_specs("nontoken creatures you control are forest lands in addition to their other types")
    assert forest.params["add_types"] == ["land"] and forest.params["add_subtypes"] == ["Forest"]
    assert static_effect_specs("attacking creatures you control are zombies in addition to their other types") is None
    assert static_effect_specs("creatures you control are blorps in addition to their other types") is None


def test_earl_of_squirrel_only_adds_the_type_to_tokens():
    engine, state = _engine()
    _put(state, "Creature tokens you control are Squirrels in addition to their other creature types.",
         name="Earl", types="Creature — Squirrel Noble")
    plain = _creature(state, "Plain")
    token = _creature(state, "Token")
    token.is_token = True
    engine.recompute_continuous_effects()
    assert "Squirrel" in token._added_subtypes and "Squirrel" not in plain._added_subtypes


# --- "~ becomes a copy of …, except it has this ability" --------------------------------------------------


def test_become_copy_tail_forms():
    specs = parse_effect_body("~ becomes a copy of another target creature, except it has this ability")
    assert specs[0].type == "become_copy_permanent" and specs[0].params["keep_own_abilities"] is True
    specs = parse_effect_body("~ becomes a copy of target creature until end of turn, except it has haste")
    assert specs[0].type == "become_copy_until_eot" and specs[0].params["add_keywords"] == ["Haste"]
    assert parse_effect_body("~ becomes a copy of target creature, except it has \"{T}: Draw a card.\"") is None


def test_the_copying_ability_survives_the_copy():
    from mtg_analyzer.game.effects.core import GameContext
    from mtg_analyzer.game.effects.registry import EffectRegistry

    engine, state = _engine()
    shifter = _put(
        state, "{2}{U}: This creature becomes a copy of another target creature, except it has this ability.",
        name="Shifter", types="Creature — Shapeshifter",
    )
    titan = _creature(state, "Titan", owner="p2")
    titan.card.power, titan.card.toughness = 6, 6
    before = len(shifter.activated_abilities)
    assert before == 1
    effect = EffectRegistry.create("become_copy_permanent", {"target_kind": "creature", "keep_own_abilities": True})
    effect.source = shifter
    effect.apply(GameContext(state, engine.rules), [titan])
    assert shifter.card.name == "Titan"
    assert len(shifter.activated_abilities) == before  # the ability that did the copying is still there
    plain = EffectRegistry.create("become_copy_permanent", {"target_kind": "creature"})
    other = _put(state, "{2}{U}: This creature becomes a copy of another target creature.", name="Other",
                 types="Creature — Shapeshifter")
    plain.source = other
    plain.apply(GameContext(state, engine.rules), [titan])
    assert other.activated_abilities == []  # RULE 707.2: without the exception, its own ability is gone
