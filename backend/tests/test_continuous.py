"""Tests for the continuous-effects layer engine (game/continuous.py, RULE 613)."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.effects import StaticAbility
from mtg_analyzer.game.game_engine import GameEngine


def creature(name="Bear", power=2, toughness=2, controller="p1", **kw):
    return Card(
        id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
        is_creature=True, power=power, toughness=toughness, **kw,
    )


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", [creature()]), ("p2", "Bob", [creature()])],
        starting_life=20, starting_hand=0,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.add_to_battlefield(obj)
    return obj


def static(layer, affects, params, source):
    ab = StaticAbility(layer, affects=affects, params=params, source=source)
    source.static_effects.append(ab)
    return ab


# -- Layer 7: power/toughness ------------------------------------------------


def test_anthem_pumps_other_creatures_you_control():
    eng = make_engine()
    lord = put(eng.state, creature("Lord", power=2, toughness=2))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    enemy = put(eng.state, creature("Enemy", power=2, toughness=2), controller="p2")
    static("pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1}, lord)
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (3, 3)   # pumped
    assert (lord.power, lord.toughness) == (2, 2)   # "other" excludes itself
    assert (enemy.power, enemy.toughness) == (2, 2)  # not yours


def test_anthem_stacks_with_counters_in_layer_order():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 2)
    static("pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1}, lord)
    continuous.recompute(eng.state)
    # base 2/2 + 2 counters (7c) + 1/1 anthem (7d) = 5/5.
    assert (bear.power, bear.toughness) == (5, 5)


def test_pt_set_applies_before_counters():
    eng = make_engine()
    src = put(eng.state, creature("Humility"))
    bear = put(eng.state, creature("Bear", power=5, toughness=5))
    bear.add_counters("+1/+1", 1)
    static("pt_set", "all_creatures", {"power": 1, "toughness": 1}, src)
    continuous.recompute(eng.state)
    # 7b set to 1/1, then 7c +1 counter → 2/2 (set wipes the printed 5/5).
    assert (bear.power, bear.toughness) == (2, 2)


# -- Layer 7a: characteristic-defining P/T -----------------------------------


def test_cda_defines_pt_from_a_count():
    eng = make_engine()
    src = put(eng.state, creature("Nightmare", power=0, toughness=0))
    put(eng.state, creature("A"))
    put(eng.state, creature("B"))
    # */* equal to the number of creatures you control (3: Nightmare + A + B).
    static("pt_cda", "self",
           {"power_count": "creatures_you_control", "toughness_count": "creatures_you_control"},
           src)
    continuous.recompute(eng.state)
    assert (src.power, src.toughness) == (3, 3)


# -- Layer 7e: power/toughness switch ----------------------------------------


def test_pt_switch_swaps_power_and_toughness_last():
    eng = make_engine()
    src = put(eng.state, creature("Switcher", power=4, toughness=1))
    static("pt_switch", "self", {}, src)
    continuous.recompute(eng.state)
    assert (src.power, src.toughness) == (1, 4)


def test_pt_switch_applies_after_anthem():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=3, toughness=1))
    static("pt_mod", "creatures_you_control", {"power": 1, "toughness": 0}, lord)
    static("pt_switch", "self", {}, bear)
    continuous.recompute(eng.state)
    # 3/1 +1/0 anthem = 4/1, then 7e switch → 1/4.
    assert (bear.power, bear.toughness) == (1, 4)


# -- "Until end of turn" pump / keyword grant (RULE 613.4d, 514.2) -----------


def test_temp_pt_bonus_folds_in_at_layer_7d():
    eng = make_engine()
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.temp_power, bear.temp_toughness = 3, 3  # a resolved Giant Growth
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (5, 5)


def test_temp_pt_stacks_on_counters_and_anthem():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 1)                                   # 7c
    static("pt_mod", "other_creatures_you_control", {"power": 1, "toughness": 1}, lord)  # 7d
    bear.temp_power, bear.temp_toughness = 2, 0                     # 7d (until EOT)
    continuous.recompute(eng.state)
    # base 2/2 + counter 1/1 + anthem 1/1 + pump 2/0 = 6/4.
    assert (bear.power, bear.toughness) == (6, 4)


def test_temp_negative_pt_can_be_lethal():
    eng = make_engine()
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.temp_toughness = -2  # -0/-2 until end of turn
    continuous.recompute(eng.state)
    assert bear.toughness == 0  # a 0-toughness SBA would then destroy it


def test_temp_keyword_grant_folds_in_at_layer_6():
    eng = make_engine()
    bear = put(eng.state, creature("Bear"))
    bear.temp_keywords.add("flying")
    continuous.recompute(eng.state)
    assert "flying" in bear.granted_keywords


# -- Layer 5: colour change --------------------------------------------------


def test_color_change_makes_a_creature_a_new_colour():
    eng = make_engine()
    bear = put(eng.state, creature("Bear", color_identity={"G"}))
    static("color", "self", {"colors": ["B"], "set": True}, bear)
    continuous.recompute(eng.state)
    assert bear.colors == {"B"}


def test_color_change_feeds_protection():
    eng = make_engine()
    attacker = put(eng.state, creature("Knight", oracle_text="Protection from black"))
    victim = put(eng.state, creature("Beast", color_identity={"G"}), controller="p2")
    static("color", "self", {"colors": ["B"], "set": True}, victim)
    continuous.recompute(eng.state)
    # The green beast is now black, so protection-from-black applies to it.
    assert combat.is_protected_from(attacker, victim)


# -- Layer 2: control change -------------------------------------------------


def test_control_change_reassigns_and_is_idempotent():
    eng = make_engine()
    # A Control-Magic-style static: "you control this permanent" set on an
    # object owned by p2 but naming p1 as controller (as an aura's grant would).
    stolen = put(eng.state, creature("Beast"), controller="p2")
    static("control", "self", {"controller": "p1"}, stolen)
    continuous.recompute(eng.state)
    assert stolen.controller_id == "p1"
    # Idempotent across repeated recomputes (base restored each pass).
    continuous.recompute(eng.state)
    assert stolen.controller_id == "p1"
    # Removing the effect restores the original controller.
    stolen.static_effects.clear()
    continuous.recompute(eng.state)
    assert stolen.controller_id == "p2"


# -- Timestamp ordering within a layer ---------------------------------------


def test_pt_set_uses_timestamp_order_within_layer():
    eng = make_engine()
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    first = put(eng.state, creature("First"))
    second = put(eng.state, creature("Second"))
    # Two "set P/T" effects; the later-timestamped one wins (RULE 613.7b).
    static("pt_set", "all_creatures", {"power": 1, "toughness": 1}, first)
    static("pt_set", "all_creatures", {"power": 6, "toughness": 6}, second)
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (6, 6)


# -- Layer 6: ability granting flows into combat -----------------------------


def test_granted_flying_flows_into_combat():
    eng = make_engine()
    lord = put(eng.state, creature("Wind Lord"))
    bear = put(eng.state, creature("Bear"))
    assert not combat.has_flying(bear)
    static("ability", "creatures_you_control", {"keywords": ["flying"]}, lord)
    continuous.recompute(eng.state)
    assert combat.has_flying(bear)  # anthem-granted flying is real in combat
    assert "Flying" in bear.to_dict()["keywords"]


# -- Layer 4: type change ----------------------------------------------------


def test_type_change_animates_a_land_into_a_creature():
    eng = make_engine()
    land = put(eng.state, Card(id="Mishra", name="Mishra's Factory",
                               type_line="Land", is_land=True))
    assert not land.is_creature
    static("type", "self", {"add_types": ["creature"], "power": 2, "toughness": 2}, land)
    continuous.recompute(eng.state)
    assert land.is_creature
    assert (land.power, land.toughness) == (2, 2)
    assert land.to_dict()["is_creature"] is True


# -- Trace -------------------------------------------------------------------


def test_static_trace_records_each_layer():
    eng = make_engine()
    lord = put(eng.state, creature("Lord"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 1)
    static("ability", "creatures_you_control", {"keywords": ["flying"]}, lord)
    static("pt_mod", "other_creatures_you_control", {"power": 2, "toughness": 0}, lord)
    continuous.recompute(eng.state)
    layers = [entry["layer"] for entry in bear.static_trace]
    assert 6 in layers and 7 in layers          # keyword grant + P/T changes
    # Final P/T reflects the whole trace: 2/2 +1 counter +2/+0 = 5/3.
    assert (bear.power, bear.toughness) == (5, 3)


# -- Cost reduction (RULE 601.2f) --------------------------------------------


def test_cost_reduction_lowers_generic_only():
    eng = make_engine()
    p1 = eng.state.active_player
    reducer = put(eng.state, creature("Rock"))
    static("cost", "your_spells", {"generic": 2}, reducer)
    spell = Card(id="Big", name="Big Spell", type_line="Sorcery",
                 mana_cost_string="{3}{G}", converted_mana_cost=4, is_sorcery=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    cost = eng.effective_cast_cost(p1, obj)
    assert cost.converted_mana_cost == 2          # {3}{G} → {1}{G}
    assert cost.color_identity == {"G"}           # colour pip untouched


def test_cost_increase_raises_generic():
    eng = make_engine()
    p1 = eng.state.active_player
    tax = put(eng.state, creature("Tax"))
    static("cost", "your_spells", {"generic": 1, "increase": True}, tax)
    spell = Card(id="S", name="S", type_line="Sorcery", mana_cost_string="{1}{R}",
                 converted_mana_cost=2, is_sorcery=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    assert eng.effective_cast_cost(p1, obj).converted_mana_cost == 3  # {1}{R} → {2}{R}


# -- Binding a static ability from a spec ------------------------------------


def test_bind_and_attach_static_ability():
    from mtg_analyzer.game.effect_binder import attach_to_object
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    eng = make_engine()
    lord = put(eng.state, Card(id="Lord", name="Anthem", type_line="Enchantment"))
    bear = put(eng.state, creature("Bear", power=1, toughness=1))
    attach_to_object(
        lord,
        [AbilitySpec("static", [EffectSpec("anthem", {"power": 2, "toughness": 2,
                     "affects": "creatures_you_control"})], raw_text="+2/+2")],
    )
    assert lord.static_effects  # bound and attached, not refused
    continuous.recompute(eng.state)
    assert (bear.power, bear.toughness) == (3, 3)


# -- Tribal lords / token anthems from oracle text (end-to-end) --------------


def _bind(state, card, controller="p1"):
    """Put a permanent on the battlefield with its abilities bound from text."""
    from mtg_analyzer.game.effect_binder import bind_from_catalogue

    obj = put(state, card, controller)
    bind_from_catalogue(obj)
    return obj


def test_tribal_lord_buffs_only_its_creature_type():
    eng = make_engine()
    lord = _bind(eng.state, Card(id="GK", name="Goblin King", type_line="Creature — Goblin",
                                 is_creature=True, power=2, toughness=2, keywords=[],
                                 oracle_text="Other Goblins you control get +1/+1."))
    goblin = put(eng.state, creature("Goblin Piker", power=2, toughness=1,
                                     type_line="Creature — Goblin Warrior"))
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    enemy_goblin = put(eng.state, creature("Enemy Goblin", power=1, toughness=1,
                                           type_line="Creature — Goblin"), controller="p2")
    continuous.recompute(eng.state)
    assert (goblin.power, goblin.toughness) == (3, 2)   # your other Goblin
    assert (lord.power, lord.toughness) == (2, 2)       # "other" excludes the lord
    assert (bear.power, bear.toughness) == (2, 2)       # not a Goblin
    assert (enemy_goblin.power, enemy_goblin.toughness) == (1, 1)  # not yours


def test_token_anthem_buffs_only_tokens():
    from mtg_analyzer.services.token_database import synthesize_token_card

    eng = make_engine()
    _bind(eng.state, Card(id="IV", name="Intangible Virtue", type_line="Enchantment",
                          oracle_text="Creature tokens you control get +1/+1."))
    token = eng.rules.create_token("p1", synthesize_token_card("Soldier", power=1, toughness=1))[0]
    real = put(eng.state, creature("Real Creature", power=2, toughness=2))
    continuous.recompute(eng.state)
    assert (token.power, token.toughness) == (2, 2)   # a token → buffed
    assert (real.power, real.toughness) == (2, 2)     # a real creature → not buffed


def test_compound_lord_grants_keyword_and_pt():
    eng = make_engine()
    _bind(eng.state, Card(id="EL", name="Elf Lord", type_line="Creature — Elf",
                          is_creature=True, power=2, toughness=2, keywords=[],
                          oracle_text="Other Elves you control get +1/+1 and have haste."))
    elf = put(eng.state, creature("Llanowar Elf", power=1, toughness=1,
                                  type_line="Creature — Elf Druid"))
    elf.summoning_sick = True
    continuous.recompute(eng.state)
    assert (elf.power, elf.toughness) == (2, 2)          # anthem
    assert combat.has_haste(elf)                          # granted keyword


def test_subtype_filter_matches_changeling():
    eng = make_engine()
    lord = _bind(eng.state, Card(id="GK", name="Goblin King", type_line="Creature — Goblin",
                                 is_creature=True, power=2, toughness=2, keywords=[],
                                 oracle_text="Other Goblins you control get +1/+1."))
    # A Changeling is every creature type (RULE 702.73) → counts as a Goblin.
    # Bound so its Changeling keyword docks onto intrinsic_keywords.
    shifter = _bind(eng.state, creature("Shifter", power=1, toughness=1,
                                        type_line="Creature — Shapeshifter", keywords=["Changeling"]))
    continuous.recompute(eng.state)
    assert (shifter.power, shifter.toughness) == (2, 2)


def test_global_color_anthem_buffs_all_matching_colors():
    # Bad Moon is global ("Black creatures get +1/+1", no "you control"), so it
    # buffs every black creature in play — including the opponent's.
    eng = make_engine()
    _bind(eng.state, Card(id="BM", name="Bad Moon", type_line="Enchantment",
                          keywords=[], oracle_text="Black creatures get +1/+1."))
    my_black = put(eng.state, Card(id="Z", name="Zombie", type_line="Creature — Zombie",
                                   is_creature=True, power=2, toughness=2, color_identity={"B"}))
    my_white = put(eng.state, Card(id="A", name="Angel", type_line="Creature — Angel",
                                   is_creature=True, power=3, toughness=3, color_identity={"W"}))
    enemy_black = put(eng.state, Card(id="EB", name="Enemy Zombie", type_line="Creature — Zombie",
                                      is_creature=True, power=1, toughness=1, color_identity={"B"}),
                      controller="p2")
    continuous.recompute(eng.state)
    assert (my_black.power, my_black.toughness) == (3, 3)     # black, buffed
    assert (my_white.power, my_white.toughness) == (3, 3)     # white, untouched
    assert (enemy_black.power, enemy_black.toughness) == (2, 2)  # global → enemy black too
