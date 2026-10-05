"""Batch 6 — "As ~ enters, choose A or B" blocks (Siege cycle) and the Enduring cycle's dies-return.

* `modal.split_named_choice_block` reads the header and its two labelled bullets; `gate._process_named_choice_block`
  emits an as-enters `choose_named_mode` plus each option's ability gated on `GameObject.chosen_mode`
  (`named_mode` on a trigger, a `chosen_mode` `active_if` on a static).
* "When ~ dies, if it was a creature, return it … It's an enchantment." is `dies_return_as_enchantment`.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import graveyard_cast
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle

FROSTCLIFF = (
    "As this enchantment enters, choose Jeskai or Temur.\n"
    "• Jeskai — Whenever one or more creatures you control deal combat damage to a player, draw a card.\n"
    "• Temur — Creatures you control get +1/+0 and have trample and haste."
)
GLACIERWOOD = (
    "As this enchantment enters, choose Temur or Sultai.\n"
    "• Temur — Whenever you cast an instant or sorcery spell, target player mills four cards.\n"
    "• Sultai — You may play lands from your graveyard."
)
ENDURING = (
    "Whenever you gain life, target opponent loses that much life.\n"
    "When Enduring Tenacity dies, if it was a creature, return it to the battlefield under its owner's control. "
    "It's an enchantment. (It's not a creature.)"
)


def _card(name, type_line, oracle="", power=None, toughness=None):
    creature = "Creature" in type_line
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle, is_creature=creature,
                is_land="Land" in type_line,
                power=power if creature else None, toughness=toughness if creature else None,
                converted_mana_cost=0)


def _engine():
    return GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)


def _put(eng, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    return obj


def test_header_and_bullets_become_a_choice_and_two_gated_abilities():
    result = parse_oracle(_card("Frostcliff Siege", "Enchantment", FROSTCLIFF))
    assert result.modeled, result.unclaimed
    choice, drawn, anthem = result.specs
    assert choice.ability_kind == "enter_replacement"
    assert choice.effects[0].params == {"options": ["Jeskai", "Temur"]}
    assert drawn.trigger["named_mode"] == "jeskai"
    assert {e.params["active_if"]["mode"] for e in anthem.effects} == {"temur"}


@pytest.mark.parametrize("text", [
    # an option with no bullet of its own
    "As this enchantment enters, choose Khans or Dragons.\n• Khans — At the beginning of your upkeep, draw a card.",
    # a bullet the grammar cannot claim keeps the whole block unclaimed
    "As this enchantment enters, choose Khans or Dragons.\n• Khans — Frobnicate the widget.\n"
    "• Dragons — At the beginning of your upkeep, draw a card.",
    # no bullets at all ("choose odd or even" is a different mechanic)
    "As this creature enters, choose odd or even.",
])
def test_a_block_that_is_not_fully_claimed_stays_unmodeled(text):
    assert not parse_oracle(_card("Odd One", "Enchantment", text)).modeled


def test_static_option_applies_only_under_its_own_label():
    for chosen, expect_boost in (("temur", True), ("jeskai", False)):
        eng = _engine()
        siege = _put(eng, _card("Frostcliff Siege", "Enchantment", FROSTCLIFF))
        siege.chosen_mode = chosen
        bear = _put(eng, _card("Bear", "Creature — Bear", power=2, toughness=2))
        eng.recompute_continuous_effects()
        assert (bear.power == 3) is expect_boost
        assert ("Trample" in bear.granted_keywords or "trample" in bear.granted_keywords) is expect_boost


def test_land_from_graveyard_permission_follows_the_choice():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    siege = _put(eng, _card("Glacierwood Siege", "Enchantment", GLACIERWOOD))
    forest = _card("Forest", "Basic Land — Forest")
    siege.chosen_mode = "temur"
    assert graveyard_cast.graveyard_land_play_grant_for(p1, eng.state, forest) is None
    siege.chosen_mode = "sultai"
    assert graveyard_cast.graveyard_land_play_grant_for(p1, eng.state, forest) is not None


def test_enduring_cycle_is_modeled_and_returns_as_a_noncreature_enchantment():
    result = parse_oracle(_card("Enduring Tenacity", "Enchantment Creature — Glimmer", ENDURING, 5, 5))
    assert result.modeled, result.unclaimed
    assert "dies_return_as_enchantment" in {e.type for s in result.specs for e in s.effects}


def test_a_dies_return_that_names_another_clause_is_not_claimed():
    text = ("When Enduring Tenacity dies, if it was a creature, return it to the battlefield under its owner's "
            "control. It's an artifact.")
    assert not parse_oracle(_card("Enduring Tenacity", "Enchantment Creature — Glimmer", text, 5, 5)).modeled


# --- "twice X" (Heliod's Intervention, Drown in Dreams, ...) and the draw-step / main-phase heads -----------

HELIODS = (
    "Choose one —\n• Destroy X target artifacts and/or enchantments.\n• Target player gains twice X life."
)
DROWN = (
    "Choose one. If you control a commander as you cast this spell, you may choose both instead.\n"
    "• Target player draws X cards.\n• Target player mills twice X cards."
)


def _spell(name, oracle):
    return Card(id=name, name=name, type_line="Instant", is_instant=True, mana_cost_string="{X}{W}",
                converted_mana_cost=1, oracle_text=oracle)


def _cast(eng, card, x, mode, targets=None):
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(card, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"W": 1 + x, "U": x})
    eng.cast_spell(p1, obj, targets=targets, x=x, mode=mode)
    eng.resolve_until_stable()
    return p1


def test_twice_x_gain_life_uses_the_announced_x():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    assert parse_oracle(_spell("Heliod's Intervention", HELIODS)).modeled
    p1 = _cast(eng, _spell("Heliod's Intervention", HELIODS), x=3, mode=1, targets=[eng.state.player_by_id("p1")])
    assert p1.life == 26


def test_twice_x_mill_and_x_draw_in_one_modal_spell():
    lib = [_card(f"Card{i}", "Basic Land — Forest") for i in range(10)]
    eng = GameEngine.new_game([("p1", "Alice", lib), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    assert parse_oracle(_spell("Drown in Dreams", DROWN)).modeled
    p1 = eng.state.player_by_id("p1")
    _cast(eng, _spell("Drown in Dreams", DROWN), x=2, mode=1, targets=[p1])
    assert len(p1.graveyard) == 4 + 1   # twice X milled, plus the spell itself


def test_a_clause_that_names_twice_x_in_an_unmodeled_slot_stays_unclaimed():
    # "twice X" is read only where the effect substitutes the sentinel (life, damage, mill, stun counters)
    card = _spell("Odd Spell", "Target player scries twice X.")
    assert not parse_oracle(card).modeled


def test_draw_step_additional_card_and_both_main_phases_are_triggers():
    draw = parse_oracle(_card("Overbeing", "Creature — Bear",
                              "At the beginning of your draw step, draw an additional card.", 3, 3))
    assert draw.modeled and draw.specs[0].effects[0].params == {"count": 1}
    mains = parse_oracle(_card("Mana Maker", "Enchantment", "At the beginning of each of your main phases, add {G}{G}."))
    assert mains.modeled
    assert [s.trigger["filter"]["step"] for s in mains.specs] == ["main1", "main2"]
    # the singular "your main phase" is not a printed template: not claimed
    assert not parse_oracle(_card("Odd", "Enchantment", "At the beginning of your main phase, add {G}{G}.")).modeled


EREBOS = (
    "Choose one —\n• Target creature gets -X/-X until end of turn. You gain X life.\n"
    "• Exile up to twice X target cards from graveyards."
)


def test_erebos_graveyard_exile_is_sized_by_twice_x():
    result = parse_oracle(_spell("Erebos's Intervention", EREBOS))
    assert result.modeled, result.unclaimed
    exile = result.specs[0].modes["options"][1][0]
    assert exile.params["target_kind"] == "any_graveyard_card"
    assert exile.params["count_selector"] == "source_twice_x_paid" and exile.params["optional"] is True
    # a numeric count below 2 is the single-card row's business, not this one
    assert not parse_oracle(_spell("One", "Exile 1 target cards from graveyards.")).modeled


def test_erebos_exiles_up_to_twice_x_cards():
    from mtg_analyzer.game import targeting

    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    cards = []
    for i in range(6):
        owner = p1 if i % 2 else p2
        o = GameObject(_card(f"Dead{i}", "Creature — Bear", power=1, toughness=1), owner_id=owner.id,
                       zone=Zone.GRAVEYARD)
        owner.graveyard.append(o)
        cards.append(o)
    spec = targeting.TargetSpec(kind="any_graveyard_card", count=10, count_selector="source_twice_x_paid",
                                optional=True)
    source = GameObject(_spell("Erebos's Intervention", EREBOS), owner_id="p1")
    source.x_paid = 2
    assert targeting.resolved_count(spec, eng.state, "p1", source) == 4
    source.x_paid = 0
    assert targeting.resolved_count(spec, eng.state, "p1", source) == 0
    p1_before = len(p1.graveyard) + len(p2.graveyard)
    _cast(eng, _spell("Erebos's Intervention", EREBOS), x=2, mode=1, targets=cards[:4])
    assert len(p1.graveyard) + len(p2.graveyard) == p1_before - 4 + 1   # four exiled, the spell lands


PIT = (
    "This land enters tapped.\n"
    "When this land enters, exile up to three target cards from graveyards.\n"
    "{T}: Add {C}.\n"
    "{T}: Add one mana of any of the exiled cards' colors."
)


def test_pit_of_offerings_taps_for_the_colors_of_every_exiled_card():
    from mtg_analyzer.game import mana_abilities

    result = parse_oracle(_card("Pit of Offerings", "Land — Cave", PIT))
    assert result.modeled, result.unclaimed
    exile = next(e for s in result.specs for e in s.effects if e.type == "exile")
    assert exile.params["remember"] is True and exile.params["count"] == 3

    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    red = GameObject(Card(id="R", name="Red Dead", type_line="Creature — Bear", is_creature=True, power=1,
                          toughness=1, color_identity={"R"}), owner_id="p1", zone=Zone.GRAVEYARD)
    blue = GameObject(Card(id="U", name="Blue Dead", type_line="Creature — Bear", is_creature=True, power=1,
                           toughness=1, color_identity={"U"}), owner_id="p1", zone=Zone.GRAVEYARD)
    land = _put(eng, _card("Pit of Offerings", "Land — Cave", PIT))
    land.linked_exile_ids = [red.instance_id, blue.instance_id]
    for card in (red, blue):
        p1.add_to_zone(card, Zone.EXILE)
    menus = [
        ability for ability in mana_abilities.mana_abilities_for(land, eng.state)
        if ability.color_selector == "imprinted_card_colors"
    ]
    assert menus
    options = mana_abilities.resolve_options(menus[0], land, eng.state)
    assert sorted(next(iter(o)) for o in options) == ["R", "U"]


THASSA = (
    "Choose one —\n• Look at the top X cards of your library. Put up to two of them into your hand and the "
    "rest on the bottom of your library in a random order.\n"
    "• Counter target spell unless its controller pays twice {X}."
)


def test_thassas_intervention_is_modeled_with_a_double_x_tax_and_an_x_dig():
    result = parse_oracle(_spell("Thassa's Intervention", THASSA))
    assert result.modeled, result.unclaimed
    dig, counter = result.specs[0].modes["options"]
    assert dig[0].params["count"] == "x" and dig[0].params["max_picks"] == 2 and dig[0].params["optional"] is True
    assert counter[0].params["unless_pays"] == "{x}{x}"


def test_an_x_dig_is_refused_under_a_trigger_and_a_tap_x_cost_is_refused():
    trig = "When this creature enters, look at the top X cards of your library. Put one of them into your hand and the rest on the bottom of your library in any order."
    assert not parse_oracle(_card("Trigger Dig", "Creature — Bear", trig, 2, 2)).modeled
    tap_x = "{T}, Tap X untapped artifacts you control: Look at the top X cards of your library. Put one of them into your hand and the rest on the bottom of your library in any order."
    assert not parse_oracle(_card("Tap X", "Artifact Creature — Construct", tap_x, 1, 2)).modeled


def test_a_double_x_unless_cost_needs_twice_the_announced_x():
    from mtg_analyzer.models.mana.mana_cost import ManaCost
    from mtg_analyzer.models.mana.mana_pool import ManaPool

    cost = ManaCost.parse("{x}{x}").with_x(3)
    short, enough = ManaPool(), ManaPool()
    short.add_many({"U": 5})
    enough.add_many({"U": 6})
    assert not short.can_pay(cost) and enough.can_pay(cost)


# --- "deals damage to target X equal to the number of ..." and "... equal to the greatest <stat> among ..." ---


def test_damage_to_target_equal_to_a_count_binds_the_count():
    result = parse_oracle(_spell("Earth Tremor", "Earth Tremor deals damage to target creature equal to the number of lands you control."))
    assert result.modeled, result.unclaimed
    bind = result.specs[0].effects[0]
    assert bind.type == "bind"
    inner = bind.params["effects"][0]
    assert inner["type"] == "damage" and inner["params"]["amount"] == "$n"
    assert bind.params["amount"]["selector"]["filter"] == {"card_type": "land"}


def test_equal_to_the_greatest_power_draws_that_many_cards():
    text = "Draw cards equal to the greatest power among creatures you control."
    assert parse_oracle(_spell("Rishkar's Expertise", text)).modeled
    lib = [_card(f"Card{i}", "Basic Land — Forest") for i in range(8)]
    eng = GameEngine.new_game([("p1", "Alice", lib), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    _put(eng, _card("Big", "Creature — Giant", power=4, toughness=4))
    _put(eng, _card("Small", "Creature — Bear", power=1, toughness=1))
    p1 = eng.state.player_by_id("p1")
    p1.hand.clear()
    spell = _spell("Rishkar's Expertise", text)
    spell.mana_cost_string = "{W}"
    obj = GameObject(spell, owner_id="p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"W": 1})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert len(p1.hand) == 4


def test_greatest_power_among_other_creatures_excludes_the_source():
    text = "When this creature enters, you gain life equal to the greatest toughness among other creatures you control."
    assert parse_oracle(_card("Flourishing Hunter", "Creature — Giant", text, 6, 6)).modeled
    assert not parse_oracle(_card("Odd", "Creature — Giant", "When this creature enters, you gain life equal to the greatest rarity among other creatures you control.", 6, 6)).modeled


def test_a_mana_ability_scaled_by_the_greatest_power():
    from mtg_analyzer.game import mana_abilities

    text = "{T}: Add an amount of {G} equal to the greatest power among creatures you control."
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    rancher = _put(eng, _card("Rancher", "Creature — Elk", text, 1, 1))
    _put(eng, _card("Big", "Creature — Giant", power=5, toughness=5))
    [ability] = mana_abilities.mana_abilities_for(rancher, eng.state)
    assert mana_abilities.resolve_options(ability, rancher, eng.state) == [{"G": 5}]


# --- the wheel family ---------------------------------------------------------------------------------------


def _wheel_table(lib_size=12, hand_size=3):
    libs = {pid: [_card(f"{pid}-L{i}", "Basic Land — Forest") for i in range(lib_size)] for pid in ("p1", "p2")}
    eng = GameEngine.new_game([("p1", "Alice", libs["p1"]), ("p2", "Bob", libs["p2"])], starting_life=20,
                              starting_hand=0)
    for pid in ("p1", "p2"):
        player = eng.state.player_by_id(pid)
        player.hand.clear()
        for i in range(hand_size):
            player.add_to_zone(GameObject(_card(f"{pid}-H{i}", "Basic Land — Forest"), owner_id=pid), Zone.HAND)
    return eng


def _cast_free(eng, card):
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(card, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 3})
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    return p1


def test_the_mandatory_wheel_discards_and_redraws_every_hand():
    text = "Each player discards their hand, then draws 7 cards."
    assert parse_oracle(_spell("Reforge the Soul", text)).modeled
    eng = _wheel_table()
    spell = _spell("Reforge the Soul", text)
    spell.mana_cost_string = "{R}"
    _cast_free(eng, spell)
    for pid in ("p1", "p2"):
        assert len(eng.state.player_by_id(pid).hand) == 7


def test_the_optional_wheel_asks_each_player_and_only_acts_on_a_yes():
    text = "Each player may discard their hand and draw 7 cards."
    assert parse_oracle(_spell("Raphael's Technique", text)).modeled
    eng = _wheel_table()
    spell = _spell("Raphael's Technique", text)
    spell.mana_cost_string = "{R}"
    _cast_free(eng, spell)
    answers = {"p1": "yes", "p2": "decline"}
    asked = []
    while eng.state.pending_choice:
        choice = eng.state.pending_choice
        asked.append(choice["player_id"])
        eng.resolve_pending_choice(answers[choice["player_id"]])
    assert sorted(asked) == ["p1", "p2"]
    assert len(eng.state.player_by_id("p1").hand) == 7
    assert len(eng.state.player_by_id("p2").hand) == 3


def test_greatest_power_edict_takes_the_strongest_creature_of_each_opponent():
    text = ("Crackling Doom deals 2 damage to each opponent. Each opponent sacrifices a creature with the "
            "greatest power among creatures that player controls.")
    assert parse_oracle(_spell("Crackling Doom", text)).modeled
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    weak = _put(eng, _card("Weak", "Creature — Bear", power=1, toughness=1), controller="p2")
    strong = _put(eng, _card("Strong", "Creature — Giant", power=5, toughness=5), controller="p2")
    mine = _put(eng, _card("Mine", "Creature — Giant", power=9, toughness=9), controller="p1")
    spell = _spell("Crackling Doom", text)
    spell.mana_cost_string = "{R}"
    _cast_free(eng, spell)
    assert strong.zone == Zone.GRAVEYARD and weak.zone == Zone.BATTLEFIELD and mine.zone == Zone.BATTLEFIELD
    assert eng.state.player_by_id("p2").life == 18


def test_distribute_counters_over_a_range_then_double_them():
    text = ("Distribute three +1/+1 counters among one, two, or three target creatures, then double the number of "
            "+1/+1 counters on each of those creatures.")
    assert parse_oracle(_spell("Biogenic Upgrade", text)).modeled
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    a = _put(eng, _card("A", "Creature — Bear", power=1, toughness=1))
    b = _put(eng, _card("B", "Creature — Bear", power=1, toughness=1))
    spell = _spell("Biogenic Upgrade", text)
    spell.mana_cost_string = "{R}"
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 2})
    eng.cast_spell(p1, obj, targets=[a, b])
    eng.resolve_until_stable()
    counters = sorted([a.counters.get("+1/+1", 0), b.counters.get("+1/+1", 0)])
    assert counters == [2, 4]   # 3 split 2 + 1, each then doubled


def test_court_of_garenbrig_distributes_up_to_two_targets_and_doubles_only_for_the_monarch():
    text = ("When this enchantment enters, you become the monarch.\n"
            "At the beginning of your upkeep, distribute two +1/+1 counters among up to two target creatures. "
            "Then if you're the monarch, double the number of +1/+1 counters on each creature you control.")
    result = parse_oracle(_card("Court of Garenbrig", "Enchantment", text))
    assert result.modeled, result.unclaimed
    upkeep = next(s for s in result.specs if s.trigger and s.trigger.get("filter") == {"step": "upkeep"})
    assert upkeep.effects[0].params["target_count"] == 2 and upkeep.effects[0].params["divided"] is True
    assert upkeep.effects[1].condition == {"kind": "is_monarch"}


DISORDER = (
    "Exile X target creatures, then investigate X times. Return the exiled cards to the battlefield tapped under "
    "their owners' control at the beginning of the next end step."
)


def test_disorder_in_the_court_exiles_x_investigates_x_and_returns_them_tapped():
    spell = Card(id="Disorder", name="Disorder in the Court", type_line="Instant", is_instant=True,
                 mana_cost_string="{X}{W}{U}", converted_mana_cost=2, oracle_text=DISORDER)
    result = parse_oracle(spell)
    assert result.modeled, result.unclaimed
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    a = _put(eng, _card("A", "Creature — Bear", power=2, toughness=2))
    b = _put(eng, _card("B", "Creature — Bear", power=2, toughness=2), controller="p2")
    stay = _put(eng, _card("Stay", "Creature — Bear", power=2, toughness=2))
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"W": 1, "U": 1, "R": 2})
    eng.cast_spell(p1, obj, targets=[a, b], x=2)
    eng.resolve_until_stable()
    assert a.zone == Zone.EXILE and b.zone == Zone.EXILE and stay.zone == Zone.BATTLEFIELD
    clues = [o for o in eng.state.permanents() if o.card.name == "Clue"]
    assert len(clues) == 2
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert a in eng.state.battlefield and b in eng.state.battlefield
    assert a.tapped and b.tapped and b.controller_id == "p2"


ABZAN = (
    "Choose one. If you control a commander as you cast this spell, you may choose both instead.\n"
    "• Any number of target opponents each sacrifice a creature with the greatest power among creatures that "
    "player controls and lose 3 life.\n"
    "• Return target creature card from your graveyard to the battlefield."
)


def test_will_of_the_abzan_hits_each_chosen_opponent_and_only_those():
    spell = Card(id="Abzan", name="Will of the Abzan", type_line="Instant", is_instant=True,
                 mana_cost_string="{2}{W}{B}{G}", converted_mana_cost=5, oracle_text=ABZAN)
    assert parse_oracle(spell).modeled
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", []), ("p3", "Cy", [])], starting_life=20,
                              starting_hand=0)
    small2 = _put(eng, _card("Small2", "Creature — Bear", power=1, toughness=1), controller="p2")
    big2 = _put(eng, _card("Big2", "Creature — Giant", power=6, toughness=6), controller="p2")
    big3 = _put(eng, _card("Big3", "Creature — Giant", power=4, toughness=4), controller="p3")
    p1, p2, p3 = (eng.state.player_by_id(pid) for pid in ("p1", "p2", "p3"))
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"W": 1, "B": 1, "G": 1, "R": 2})
    eng.cast_spell(p1, obj, targets=[p2], mode=0)   # only Bob is chosen
    eng.resolve_until_stable()
    assert big2.zone == Zone.GRAVEYARD and small2.zone == Zone.BATTLEFIELD
    assert p2.life == 17 and p3.life == 20 and big3.zone == Zone.BATTLEFIELD


MARDU = (
    "Choose one. If you control a commander as you cast this spell, you may choose both instead.\n"
    "• Create a number of 1/1 red Warrior creature tokens equal to the number of creatures target player controls.\n"
    "• Will of the Mardu deals damage to target creature equal to the number of creatures you control."
)


def _mardu_cast(mode, targets_for):
    spell = Card(id="Mardu", name="Will of the Mardu", type_line="Instant", is_instant=True,
                 mana_cost_string="{2}{R}{W}{B}", converted_mana_cost=5, oracle_text=MARDU)
    assert parse_oracle(spell).modeled
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    mine = [_put(eng, _card(f"Mine{i}", "Creature — Bear", power=1, toughness=3)) for i in range(2)]
    theirs = [_put(eng, _card(f"Theirs{i}", "Creature — Bear", power=1, toughness=1), controller="p2") for i in range(3)]
    p1 = eng.state.player_by_id("p1")
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"R": 1, "W": 1, "B": 1, "G": 2})
    eng.cast_spell(p1, obj, targets=targets_for(eng, mine, theirs), mode=mode)
    eng.resolve_until_stable()
    return eng, mine, theirs


def test_will_of_the_mardu_makes_one_warrior_per_creature_the_chosen_player_controls():
    eng, mine, theirs = _mardu_cast(0, lambda eng, mine, theirs: [eng.state.player_by_id("p2")])
    warriors = [o for o in eng.state.permanents() if o.card.name == "Warrior"]
    assert len(warriors) == 3 and all(o.controller_id == "p1" for o in warriors)


def test_will_of_the_mardu_damage_mode_counts_the_casters_creatures():
    eng, mine, theirs = _mardu_cast(1, lambda eng, mine, theirs: [theirs[0]])
    assert theirs[0].zone == Zone.GRAVEYARD   # 2 damage (two creatures you control) kills the 1/1


JESKAI = (
    "Choose one. If you control a commander as you cast this spell, you may choose both instead.\n"
    "• Each player may discard their hand and draw 5 cards.\n"
    "• Each instant and sorcery card in your graveyard gains flashback until end of turn. The flashback cost is "
    "equal to its mana cost."
)


def test_will_of_the_jeskai_grants_flashback_to_the_graveyard_even_though_the_spell_is_not_a_permanent():
    from mtg_analyzer.game import graveyard_cast

    spell = Card(id="Jeskai", name="Will of the Jeskai", type_line="Instant", is_instant=True,
                 mana_cost_string="{2}{U}{R}{W}", converted_mana_cost=5, oracle_text=JESKAI)
    assert parse_oracle(spell).modeled
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    p1 = eng.state.player_by_id("p1")
    bolt = Card(id="Bolt", name="Bolt", type_line="Instant", is_instant=True, mana_cost_string="{R}",
                converted_mana_cost=1)
    bolt_obj = GameObject(bolt, owner_id="p1", zone=Zone.GRAVEYARD)
    p1.graveyard.append(bolt_obj)
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, bolt) is None
    eng.begin_turn()
    eng.state.current_step = "main1"
    obj = GameObject(spell, owner_id="p1")
    p1.add_to_zone(obj, Zone.HAND)
    bind_from_catalogue(obj)
    p1.mana_pool.add_many({"U": 1, "R": 1, "W": 1, "G": 2})
    eng.cast_spell(p1, obj, mode=1)
    eng.resolve_until_stable()
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, bolt) is not None
    # ...and only until end of turn
    eng.state.internal_turn.number += 1
    assert graveyard_cast.graveyard_cast_grant_for(p1, eng.state, bolt) is None
