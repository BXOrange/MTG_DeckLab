"""PAR-150: "up to N target ..." for counter, gain control, goad and keyword grants (RULE 115.1a).

Each family: the parser claims the plural/up-to shape with a `count`/`optional` param, and the engine applies the
effect to every chosen target (RULE 608.2b: a target that became illegal is skipped, the rest still apply).
"""

from mtg_analyzer.game import targeting
from mtg_analyzer.game.effects.core import CounterSpellEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.models.mana.mana_cost import ManaCost
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def instant(name, cost="{0}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Instant", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_instant=True, oracle_text=oracle_text,
    )


def creature(name="Grizzly Bears", cost="{1}{G}"):
    return Card(
        id=name, name=name, type_line="Creature — Bear", mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_creature=True, power=2, toughness=2,
    )


def two_player_engine():
    eng = GameEngine.new_game(
        [("p1", "Alice", [instant("f")] * 5), ("p2", "Bob", [instant("f")] * 5)], starting_hand=0,
    )
    return eng, eng.state.player_by_id("p1"), eng.state.player_by_id("p2")


def push_spell(eng, player, card):
    obj = GameObject(card, owner_id=player.id, zone=Zone.STACK)
    obj.spell_effects = []
    eng.state.stack.append(StackItem(
        kind="spell", controller_id=player.id, obj=obj, description=card.name, effects=obj.spell_effects,
    ))
    return obj


def give_spell(player, card, effects):
    obj = GameObject(card, owner_id=player.id, zone=Zone.HAND)
    obj.spell_effects = effects
    for e in effects:
        e.source = obj
    player.hand.append(obj)
    return obj


def only_spec(text):
    (spec,) = parse_effect_body(text)
    return spec


# --- counter -------------------------------------------------------------------------------------------------------


def test_counter_up_to_two_spells_parses():
    spec = only_spec("counter up to 2 target spells")
    assert (spec.type, spec.params) == ("counter", {"count": 2, "optional": True})


def test_counter_spells_and_or_abilities_uses_the_union_pool():
    spec = only_spec("counter up to 4 target spells and/or abilities")
    assert spec.params == {"count": 4, "optional": True, "target_kind": "spell_or_ability"}


def test_counter_up_to_one_typed_spell_and_ability():
    assert only_spec("counter up to 1 target creature spell").params == {
        "count": 1, "optional": True, "card_types": ["creature"],
    }
    spec = only_spec("counter up to 1 target activated or triggered ability")
    assert (spec.type, spec.params) == ("counter_ability", {"count": 1, "optional": True})


def test_counter_up_to_rejects_a_number_noun_mismatch():
    assert parse_effect_body("counter up to 2 target spell") is None


def test_double_negative_and_katara_are_modeled():
    for name, text in (
        ("Double Negative", "Counter up to two target spells."),
        ("Katara Reversal", "Counter up to four target spells and/or abilities.\nUntap up to four target artifacts and/or creatures."),
    ):
        card = Card(id=name, name=name, type_line="Instant", is_instant=True, oracle_text=text)
        assert parse_oracle(card).coverage == MODELED


def test_counter_up_to_two_counters_both_chosen_spells():
    eng, p1, p2 = two_player_engine()
    a = push_spell(eng, p2, creature("A"))
    b = push_spell(eng, p2, creature("B"))
    c = push_spell(eng, p2, creature("C"))
    obj = give_spell(p1, instant("Double Negative"), [CounterSpellEffect(count=2, optional=True)])
    eng.cast_spell(p1, obj, targets=[a, b])
    eng.rules.resolve_top_of_stack()
    assert a.zone == Zone.GRAVEYARD and b.zone == Zone.GRAVEYARD
    assert c.zone == Zone.STACK


def test_counter_up_to_two_with_one_target_counters_it_and_zero_is_legal():
    eng, p1, p2 = two_player_engine()
    a = push_spell(eng, p2, creature("A"))
    obj = give_spell(p1, instant("Double Negative"), [CounterSpellEffect(count=2, optional=True)])
    eng.cast_spell(p1, obj, targets=[a])
    eng.rules.resolve_top_of_stack()
    assert a.zone == Zone.GRAVEYARD
    eng2, q1, q2 = two_player_engine()
    obj2 = give_spell(q1, instant("Double Negative"), [CounterSpellEffect(count=2, optional=True)])
    assert eng2.cast_spell(q1, obj2, targets=[]) is not False


def test_counter_spell_effect_target_spec_carries_count():
    spec = CounterSpellEffect(count=4, optional=True, target_kind="spell_or_ability").target_spec
    assert (spec.count, spec.optional, spec.kind) == (4, True, "spell_or_ability")
    assert CounterSpellEffect().target_spec.count == 1


def test_counter_spells_and_abilities_counters_a_spell_and_an_ability_together():
    eng, p1, p2 = two_player_engine()
    spell = push_spell(eng, p2, creature("A"))
    src = GameObject(creature("Source"), owner_id="p2", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(src)
    ability = StackItem(kind="ability", controller_id="p2", obj=None, source=src, description="ping", effects=[])
    eng.state.stack.append(ability)
    effect = CounterSpellEffect(count=4, optional=True, target_kind="spell_or_ability")
    obj = give_spell(p1, instant("Katara Reversal"), [effect])
    eng.cast_spell(p1, obj, targets=[spell, ability])
    eng.rules.resolve_top_of_stack()
    assert spell.zone == Zone.GRAVEYARD
    assert ability not in eng.state.stack


# --- shared harness: parse an effect body, bind it, apply it to chosen targets -------------------------------------


def run_body(text, targets, *, x=None, source_type="Sorcery"):
    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    eng, p1, p2 = two_player_engine()
    src = GameObject(Card(id="Src", name="Src", type_line=source_type), owner_id="p1", zone=Zone.STACK)
    if x is not None:
        src.x_paid = x
    return eng, src, build_effects(parse_effect_body(text), src), p1, p2


def board_creature(eng, name, owner):
    obj = GameObject(creature(name), owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    eng.state.add_to_battlefield(obj)
    return obj


def apply(eng, src, effects, targets, groups=None):
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    _apply_effects_partitioned(effects, eng.rules.context, targets, groups, source=src)


# --- gain control --------------------------------------------------------------------------------------------------


def test_gain_control_up_to_three_parses_as_a_permanent_steal():
    spec = only_spec("gain control of up to 3 target creatures")
    assert spec.type == "gain_control_until_eot"
    assert spec.params == {
        "target_kind": "creature", "count": 3, "optional": True, "duration": "permanent", "haste": False, "untap": False,
    }


def test_gain_control_x_creatures_and_planeswalkers_never_offers_players():
    spec = only_spec("gain control of x target creatures and/or planeswalkers")
    assert spec.params["target_kind"] == "creature_or_planeswalker"
    assert spec.params["count_selector"] == "source_x_paid"


def test_gain_control_up_to_three_steals_every_chosen_creature_for_good():
    eng, src, effects, p1, p2 = run_body("gain control of up to 3 target creatures", None)
    a, b, c = (board_creature(eng, n, "p2") for n in "ABC")
    apply(eng, src, effects, [a, b])
    assert a.controller_id == "p1" and b.controller_id == "p1" and c.controller_id == "p2"
    assert a.control_change_until_eot is None  # RULE 611.2: no duration, never reverts at cleanup


def test_gain_control_up_to_three_ignores_extra_entries_in_a_shared_target_list():
    eng, src, effects, p1, p2 = run_body("gain control of up to 2 target creatures", None)
    a, b, c = (board_creature(eng, n, "p2") for n in "ABC")
    apply(eng, src, effects, [a, b, c])
    assert c.controller_id == "p2"


def test_harness_by_force_threatens_any_number_with_untap_and_haste():
    eng, src, effects, p1, p2 = run_body(
        "gain control of any number of target creatures until end of turn. untap those creatures. "
        "they gain haste until end of turn", None,
    )
    a, b = board_creature(eng, "A", "p2"), board_creature(eng, "B", "p2")
    a.tapped = b.tapped = True
    apply(eng, src, effects, [a, b])
    for obj in (a, b):
        assert obj.controller_id == "p1" and not obj.tapped
        assert "haste" in obj.temp_keywords
        assert obj.control_change_until_eot == "p2"  # reverts at cleanup


def test_mass_manipulation_takes_exactly_x_targets():
    eng, src, effects, p1, p2 = run_body("gain control of x target creatures and/or planeswalkers", None, x=2)
    a, b, c = (board_creature(eng, n, "p2") for n in "ABC")
    apply(eng, src, effects, [a, b])
    assert a.controller_id == "p1" and b.controller_id == "p1" and c.controller_id == "p2"
    [effect] = effects
    assert targeting.resolved_count(effect.target_spec, eng.state, "p1", src) == 2


# --- goad ----------------------------------------------------------------------------------------------------------


def test_goad_up_to_two_parses():
    assert only_spec("goad up to 2 target creatures").params == {"target_kind": "creature", "count": 2, "optional": True}
    assert only_spec("goad 2 target creatures your opponents control").params == {
        "target_kind": "creature_you_dont_control", "count": 2,
    }


def test_goad_refuses_a_non_creature_plural_pool():
    assert parse_effect_body("goad up to 2 target permanents") is None


def test_goad_up_to_two_goads_each_chosen_creature():
    eng, src, effects, p1, p2 = run_body("goad up to 2 target creatures", None)
    a, b, c = (board_creature(eng, n, "p2") for n in "ABC")
    apply(eng, src, effects, [a, b])
    assert a.goaded_by == {"p1"} and b.goaded_by == {"p1"} and not c.goaded_by


def test_goad_up_to_two_can_choose_just_one_or_none():
    eng, src, effects, p1, p2 = run_body("goad up to 2 target creatures", None)
    a = board_creature(eng, "A", "p2")
    apply(eng, src, effects, [a])
    assert a.goaded_by == {"p1"}
    apply(eng, src, effects, [])  # zero targets is legal for "up to" (RULE 115.1a)


def test_sontaran_general_goaded_creatures_cannot_block():
    eng, src, effects, p1, p2 = run_body(
        "for each opponent, goad up to 1 target creature that player controls. those creatures can't block this turn", None,
    )
    a, b = board_creature(eng, "A", "p2"), board_creature(eng, "B", "p2")
    apply(eng, src, effects, [a])
    assert a.goaded_by == {"p1"} and a.temp_cant_block and not b.temp_cant_block


# --- keyword grants ------------------------------------------------------------------------------------------------


def test_keyword_grant_up_to_n_parses_with_the_permanent_pool():
    spec = only_spec("up to 4 target permanents you control gain indestructible until end of turn")
    assert (spec.type, spec.params) == (
        "pump", {"keywords": ["indestructible"], "target_kind": "permanent_you_control", "target_count": 4, "optional": True},
    )


def test_keyword_grant_unmodeled_keyword_fails_closed():
    assert parse_effect_body("up to 2 target creatures gain flying and bogus until end of turn") is None


def test_keyword_grant_x_where_clauses_pick_their_count_selectors():
    dev = only_spec(
        "up to x target creatures each gain intimidate and haste until end of turn, where x is your devotion to black"
    )
    assert dev.params["count_selector"] == "counted:devotion_to_black"
    kicked = only_spec("up to x target creatures gain flying until end of turn, where x is the number of times ~ was kicked")
    assert kicked.params["count_selector"] == "source_kicker_count"
    assert parse_effect_body("up to 2 target creatures gain flying until end of turn, where x is your devotion to black") is None


def test_counted_selector_prefix_matches_the_parsers_copy():
    from mtg_analyzer.parser.oracle.catalogue import handlers

    assert handlers._COUNTED_SELECTOR_PREFIX == targeting.COUNTED_SELECTOR_PREFIX


def test_invisible_force_field_grants_every_chosen_permanent():
    eng, src, effects, p1, p2 = run_body("up to 4 target permanents you control gain indestructible until end of turn", None)
    a, b, c = (board_creature(eng, n, "p1") for n in "ABC")
    rock = GameObject(Card(id="Rock", name="Rock", type_line="Artifact"), owner_id="p1", zone=Zone.BATTLEFIELD)
    rock.controller_id = "p1"
    eng.state.add_to_battlefield(rock)
    apply(eng, src, effects, [a, b, rock])
    for obj in (a, b, rock):
        assert "indestructible" in obj.temp_keywords
    assert "indestructible" not in c.temp_keywords


def test_mogis_marauder_target_count_is_devotion_to_black():
    eng, src, effects, p1, p2 = run_body(
        "up to x target creatures each gain intimidate and haste until end of turn, where x is your devotion to black", None,
    )
    for n in ("A", "B"):
        pip = GameObject(
            Card(id=n, name=n, type_line="Creature — Bear", mana_cost_string="{1}{B}{B}", is_creature=True, power=1, toughness=1),
            owner_id="p1", zone=Zone.BATTLEFIELD,
        )
        pip.controller_id = "p1"
        eng.state.add_to_battlefield(pip)
    [effect] = effects
    assert targeting.resolved_count(effect.target_spec, eng.state, "p1", src) == 4
    victims = [board_creature(eng, f"V{i}", "p2") for i in range(3)]
    apply(eng, src, effects, victims)
    assert all({"intimidate", "haste"} <= v.temp_keywords for v in victims)


def test_voyager_drake_target_count_is_the_kick_count():
    eng, src, effects, p1, p2 = run_body(
        "up to x target creatures gain flying until end of turn, where x is the number of times ~ was kicked", None,
    )
    src.kicker_count = 2
    [effect] = effects
    assert targeting.resolved_count(effect.target_spec, eng.state, "p1", src) == 2
    src.kicker_count = 0
    assert targeting.resolved_count(effect.target_spec, eng.state, "p1", src) == 0


def _etb_game(oracle, name="Mogis Test", cost="{B}", extra_types="Creature — Human Berserker"):
    from mtg_analyzer.game.binding.core import bind_from_catalogue

    card = Card(
        id=name, name=name, type_line=extra_types, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost, is_creature=True, power=2, toughness=2,
        oracle_text=oracle,
    )
    eng = GameEngine.new_game([("p1", "A", [card]), ("p2", "B", [])], starting_hand=1, starting_life=20)
    for obj in eng.state.players[0].hand:
        bind_from_catalogue(obj)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng, eng.state.player_by_id("p1")


def test_mogis_marauder_end_to_end_grants_to_each_chosen_creature():
    eng, p1 = _etb_game(
        "When ~ enters, up to X target creatures each gain intimidate and haste until end of turn, "
        "where X is your devotion to black.",
        cost="{B}{B}",
    )
    a = board_creature(eng, "A", "p2")
    b = board_creature(eng, "B", "p2")
    c = board_creature(eng, "C", "p2")
    p1.mana_pool.add_many({"B": 2})
    eng.cast_spell(p1, p1.hand[0])
    eng.resolve_until_stable()
    eng.rules.put_triggers_on_stack()
    # devotion to black is 2 ({B}{B} on the battlefield): exactly two rounds are offered.
    picked = []
    while eng.state.pending_choice and eng.state.pending_choice["kind"].startswith("trigger_target"):
        target = str([o for o in (a, b, c) if o not in picked][0].instance_id)
        picked.append(next(o for o in (a, b, c) if str(o.instance_id) == target))
        eng.resolve_pending_choice(target)
    eng.resolve_until_stable()
    assert len(picked) == 2
    for obj in picked:
        assert {"intimidate", "haste"} <= obj.temp_keywords
    assert not ({"intimidate", "haste"} & ({*c.temp_keywords} if c not in picked else set()))


def test_repulsive_mutation_taxes_by_the_greatest_power_after_the_counters_land():
    spec = only_spec("counter up to 1 target spell unless its controller pays mana equal to the greatest power among creatures you control")
    assert spec.params == {
        "count": 1, "optional": True, "unless_pays": "{0}",
        "unless_pays_extra_selector": "greatest_power_among_creatures_you_control",
    }
    eng, src, effects, p1, p2 = run_body(
        "put 3 +1/+1 counters on target creature you control. then counter up to 1 target spell unless its controller "
        "pays mana equal to the greatest power among creatures you control", None,
    )
    mine = board_creature(eng, "Mine", "p1")  # 2/2: the counters make it 5/5, so the tax is {5}
    victim = push_spell(eng, p2, creature("Their Spell"))
    apply(eng, src, effects, [mine, victim], groups=[[mine], [victim]])
    assert mine.counters.get("+1/+1") == 3
    assert victim.zone == Zone.GRAVEYARD  # Bob has no mana to pay {5}: countered (RULE 118.12a)
