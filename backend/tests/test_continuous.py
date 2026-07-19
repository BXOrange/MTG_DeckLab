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


# -- RULE 613.8 same-layer dependency ordering (layer 2 only) ----------------


def test_control_change_ordering_unaffected_when_all_same_bucket():
    # Regression guard: every existing control_change use is self/attached_
    # permanent-scoped, so `_order_control_effects` must be a no-op (plain
    # timestamp order) whenever nothing is controller-scoped.
    eng = make_engine()
    bear = put(eng.state, creature("Bear", power=2, toughness=2), controller="p2")
    first = put(eng.state, creature("First"), controller="p1")
    second = put(eng.state, creature("Second"), controller="p1")
    static("control", "self", {"controller": "p1"}, first)  # unrelated source
    static("control", "self", {"controller": "p2"}, bear)
    static("control", "self", {"controller": "p1"}, second)
    continuous.recompute(eng.state)
    assert bear.controller_id == "p2"  # only the ability sourced on `bear` applies to it


def test_control_change_dependency_overrides_timestamp_order():
    # The textbook CR 613.8 example: a direct control-change ("gain control
    # of target creature") and a controller-scoped one ("you control
    # creatures you control" — i.e. everything the ability's controller now
    # controls gets reassigned again) where the scoped one's *result*
    # depends on whether the direct one already ran. Direct-scoped abilities
    # must always apply first regardless of timestamp (here the scoped
    # ability is given the earlier timestamp, to prove it's not coincidental
    # ordering).
    eng = make_engine()
    stolen = put(eng.state, creature("Beast"), controller="p2")  # p2's creature
    stolen.timestamp = 2  # later — the direct ability's sort key

    scoped_source = put(eng.state, creature("Scoped Source"), controller="p1")
    scoped_source.timestamp = 1  # earlier — the scoped ability's sort key

    # "You control creatures you control" (a no-op on its own, just re-stamps
    # p1's own creatures) reassigns to p2 — but only what's already p1's *at
    # the time it applies*.
    static("control", "creatures_you_control", {"controller": "p2"}, scoped_source)
    # "Gain control of target creature" — steals `stolen` from p2 to p1.
    static("control", "self", {"controller": "p1"}, stolen)

    continuous.recompute(eng.state)
    # If the scoped ability incorrectly ran first (pure timestamp order), it
    # would see `stolen` still under p2 and leave it alone, and `stolen`
    # would end up under p1 (the direct ability applying after). Correct
    # RULE 613.8 order (direct first) instead lets the scoped ability see
    # `stolen` already under p1 and hand it straight to p2.
    assert stolen.controller_id == "p2"


# -- Layer 1: conditional/continuous copy effects (RULE 707) ----------------
#
# `become_copy` wipes and rebinds an object's whole ability set from the
# copied card (RULE 706.2), so a plain copy target (e.g. a bare "Grave
# Titan") *consumes* the very "copy" ability that caused the copy — the real
# Vesuvan Shapeshifter ruling ("won't be able to change again unless
# something else allows it"). Testing revert/re-target/no-op behavior across
# more than one recompute therefore needs a copy target whose *own* card
# grants an equivalent `conditional_copy` ability, so it survives the wipe —
# a "Test Vesuvan Clone" registered here, mirroring `test_tokens.py`'s
# register-then-pop pattern for a test-only catalogue entry.


@pytest.fixture
def vesuvan_clone_target(request):
    from mtg_analyzer.game import ability_catalogue
    from mtg_analyzer.parser.oracle.spec import AbilitySpec, EffectSpec

    ability_catalogue.register(
        "Test Vesuvan Clone",
        lambda: [AbilitySpec(
            "static",
            [EffectSpec("conditional_copy", {"requires_untapped": True})],
        )],
    )
    request.addfinalizer(lambda: ability_catalogue._REGISTRY.pop("test vesuvan clone", None))
    return creature("Test Vesuvan Clone", power=6, toughness=6, oracle_text="")


def test_conditional_copy_applies_while_condition_holds(vesuvan_clone_target):
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, vesuvan_clone_target)
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Test Vesuvan Clone"
    assert (src.power, src.toughness) == (6, 6)


def test_conditional_copy_reverts_when_condition_stops_holding(vesuvan_clone_target):
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, vesuvan_clone_target)
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Test Vesuvan Clone"

    src.tapped = True  # condition ("as long as untapped") stops holding
    continuous.recompute(eng.state)
    assert src.card.name == "Shifter"
    assert (src.power, src.toughness) == (1, 1)


def test_conditional_copy_reapplies_when_condition_holds_again(vesuvan_clone_target):
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, vesuvan_clone_target)
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    src.tapped = True
    continuous.recompute(eng.state)
    assert src.card.name == "Shifter"

    src.tapped = False
    continuous.recompute(eng.state)
    assert src.card.name == "Test Vesuvan Clone"


def test_conditional_copy_switches_to_a_new_target(vesuvan_clone_target):
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target_a = put(eng.state, vesuvan_clone_target)
    target_b = put(eng.state, creature("Bear", power=2, toughness=2))
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target_a.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Test Vesuvan Clone"

    src.copy_target_id = target_b.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Bear"
    assert (src.power, src.toughness) == (2, 2)


def test_conditional_copy_is_transition_only_and_preserves_bookkeeping(vesuvan_clone_target):
    # Once already applied to the same target, a second recompute must NOT
    # re-run the mutate/rebind — otherwise per-turn bookkeeping on the
    # copy's own abilities (e.g. a granted TriggeredAbility's "once per
    # turn" state) would be silently destroyed every single pass.
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, vesuvan_clone_target)
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Test Vesuvan Clone"
    # The copied card grants an equivalent "copy" ability, so it survives
    # the wipe-and-rebind — the transition-only guard is what's actually
    # under test on the next pass, not "the ability disappeared".
    assert any(isinstance(ab, StaticAbility) and ab.layer == "copy" for ab in src.static_effects)

    sentinel = object()
    src.activated_abilities = [sentinel]
    continuous.recompute(eng.state)  # same target, condition still holds
    assert src.activated_abilities == [sentinel]  # untouched: no re-copy


def test_conditional_copy_locks_in_once_the_copied_card_grants_no_similar_ability():
    # Real Vesuvan Shapeshifter ruling: copying a creature without a similar
    # ability consumes the very ability that caused it — it won't change (or
    # revert) again on its own.
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, creature("Grave Titan", power=6, toughness=6))
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Grave Titan"
    assert not any(isinstance(ab, StaticAbility) and ab.layer == "copy" for ab in src.static_effects)

    src.tapped = True
    continuous.recompute(eng.state)
    assert src.card.name == "Grave Titan"  # no revert: the "copy" ability is gone
    src.tapped = False
    continuous.recompute(eng.state)
    assert src.card.name == "Grave Titan"  # and no needless re-copy either


def test_conditional_copy_survives_target_leaving_the_battlefield():
    eng = make_engine()
    src = put(eng.state, creature("Shifter", power=1, toughness=1))
    target = put(eng.state, creature("Grave Titan", power=6, toughness=6))
    static("copy", "self", {"requires_untapped": True}, src)
    src.copy_target_id = target.instance_id
    continuous.recompute(eng.state)
    assert src.card.name == "Grave Titan"

    eng.state.remove_from_battlefield(target)
    continuous.recompute(eng.state)
    assert src.card.name == "Grave Titan"  # only the condition reverts a copy, not target liveness


# -- Layer 3: text-changing effects (RULE 612), scoped -----------------------
# The canonical Artificial-Evolution case: "protection from red" -> "protection
# from blue" — the one real, already-live-re-derived consumer this engine has
# (`combat.protections_of_text`, via `GameObject.effective_oracle_text`).


def test_text_change_rewrites_a_colour_word_and_flips_protection():
    eng = make_engine()
    src = put(eng.state, creature("Wall", oracle_text="Protection from red."))
    attacker = put(eng.state, creature("Red Ogre", oracle_text=""), controller="p2")
    attacker.card.color_identity = {"R"}
    assert combat.is_protected_from(src, attacker)  # baseline: protected from red

    static("text", "self", {"replace": {"red": "blue"}}, src)
    continuous.recompute(eng.state)
    assert src.effective_oracle_text == "Protection from blue."
    assert not combat.is_protected_from(src, attacker)  # no longer protected from red…
    attacker.card.color_identity = {"U"}
    assert combat.is_protected_from(src, attacker)  # …but now protected from blue


def test_text_change_does_not_affect_bound_abilities():
    # Scoped deliberately: layer 3 here only feeds `effective_oracle_text`
    # (consulted by `protections_of_text`); it does not re-derive
    # abilities/keywords, which stay bound once from the printed text.
    eng = make_engine()
    src = put(eng.state, creature("Wall", oracle_text="Protection from red.",
                                  keywords=["Flying"]))
    static("text", "self", {"replace": {"red": "blue"}}, src)
    continuous.recompute(eng.state)
    assert combat.has_flying(src)  # unaffected — bound once at bind time


def test_text_change_absent_leaves_effective_text_as_printed():
    eng = make_engine()
    src = put(eng.state, creature("Wall", oracle_text="Protection from red."))
    continuous.recompute(eng.state)
    assert src.effective_oracle_text == "Protection from red."


# -- "attached_permanent": Aura/Equipment/Fortify/Reconfigure buffs ----------


def test_attached_permanent_selector_buffs_the_enchanted_creature():
    # A Rancor-style Aura: "Enchanted creature gets +2/+0 and has trample."
    eng = make_engine()
    host = put(eng.state, creature("Bear", power=2, toughness=2))
    aura = GameObject(Card(id="Aura", name="Rancor-alike", type_line="Enchantment"),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(aura)
    aura.attached_to = host.instance_id
    static("pt_mod", "attached_permanent", {"power": 2, "toughness": 0}, aura)
    static("ability", "attached_permanent", {"keywords": ["trample"]}, aura)
    continuous.recompute(eng.state)
    assert (host.power, host.toughness) == (4, 2)
    assert combat.has_trample(host)


def test_attached_permanent_selector_matches_nothing_while_unattached():
    eng = make_engine()
    host = put(eng.state, creature("Bear", power=2, toughness=2))
    aura = GameObject(Card(id="Aura", name="Rancor-alike", type_line="Enchantment"),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    eng.state.add_to_battlefield(aura)
    static("pt_mod", "attached_permanent", {"power": 2, "toughness": 0}, aura)
    continuous.recompute(eng.state)
    assert (host.power, host.toughness) == (2, 2)  # aura.attached_to is None


def test_control_change_via_attached_permanent_steals_the_host():
    # A Mind-Control-style Aura: "You control enchanted creature."
    eng = make_engine()
    stolen = put(eng.state, creature("Beast"), controller="p2")
    aura = GameObject(Card(id="Aura", name="Mind-Control-alike", type_line="Enchantment"),
                       owner_id="p1", zone=Zone.BATTLEFIELD)
    aura.controller_id = "p1"
    eng.state.add_to_battlefield(aura)
    aura.attached_to = stolen.instance_id
    static("control", "attached_permanent", {}, aura)
    continuous.recompute(eng.state)
    assert stolen.controller_id == "p1"


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


def test_static_trace_tags_duration_and_source():
    """The per-card effect summary (board info popover) needs every trace
    entry tagged with its source and how long it lasts."""
    eng = make_engine()
    bear = put(eng.state, creature("Bear", power=2, toughness=2))
    bear.add_counters("+1/+1", 2)
    # A resolved "until end of turn" pump (Monstrous Rage-shaped): records the
    # aggregate ints *and* a per-source breakdown, exactly like PumpEffect.
    bear.temp_power += 3
    bear.temp_toughness += 1
    bear.temp_keywords.add("trample")
    bear.temp_effects.append(
        {"source": "Monstrous Rage", "power": 3, "toughness": 1, "keywords": ["trample"]}
    )
    continuous.recompute(eng.state)
    # 2/2 + two +1/+1 counters + Monstrous Rage's +3/+1 = 7/5.
    assert (bear.power, bear.toughness) == (7, 5)
    by_duration = {(e["source"], e["duration"]) for e in bear.static_trace}
    assert ("+1/+1-Marken", "permanent") in by_duration
    assert ("Monstrous Rage", "end_of_turn") in by_duration
    # Its keyword grant is attributed to the same source and duration.
    kw = next(e for e in bear.static_trace if e["layer"] == 6)
    assert kw["source"] == "Monstrous Rage" and kw["duration"] == "end_of_turn"


def test_temp_effects_cleared_at_cleanup():
    eng = make_engine()
    bear = put(eng.state, creature("Bear"))
    bear.temp_power += 2
    bear.temp_effects.append({"source": "Giant Growth", "power": 2, "toughness": 2, "keywords": []})
    eng._step_cleanup()
    assert bear.temp_effects == [] and bear.temp_power == 0


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


# -- Self cost reduction (Delve/Affinity-shaped, printed on the spell itself) -


def test_self_cost_reduction_scales_with_a_graveyard_count_selector():
    # Delve-shaped: "This spell costs {1} less to cast for each card in
    # your graveyard." — printed on the card itself, so it must apply while
    # the card is still in hand, not off a battlefield scan.
    eng = make_engine()
    p1 = eng.state.active_player
    for i in range(3):
        p1.graveyard.append(Card(id=f"G{i}", name=f"G{i}", type_line="Instant", is_instant=True))
    spell = Card(id="Cruise", name="Treasure Cruise", type_line="Sorcery",
                 mana_cost_string="{7}{U}", converted_mana_cost=8, is_sorcery=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    static("cost", "self", {"generic": 1, "per": "cards_in_your_graveyard"}, obj)
    cost = eng.effective_cast_cost(p1, obj)
    assert cost.converted_mana_cost == 5  # {7}{U} - {3} → {4}{U}
    assert cost.color_identity == {"U"}


def test_self_cost_reduction_scales_with_an_artifact_count_selector():
    # Affinity-shaped: "This spell costs {1} less to cast for each artifact
    # you control."
    eng = make_engine()
    p1 = eng.state.active_player
    for i in range(4):
        put(eng.state, Card(id=f"Art{i}", name=f"Art{i}", type_line="Artifact"))
    spell = Card(id="Myr", name="Myr Enforcer", type_line="Artifact Creature — Myr",
                 mana_cost_string="{7}", converted_mana_cost=7, is_creature=True)
    obj = GameObject(spell, owner_id="p1", zone=Zone.HAND)
    p1.hand.append(obj)
    static("cost", "self", {"generic": 1, "per": "artifacts_you_control"}, obj)
    cost = eng.effective_cast_cost(p1, obj)
    assert cost.converted_mana_cost == 3  # {7} - {4} → {3}


def test_self_cost_reduction_does_not_apply_to_other_players_spells():
    eng = make_engine()
    p1 = eng.state.active_player
    p2 = next(p for p in eng.state.players if p is not p1)
    for i in range(3):
        p2.graveyard.append(Card(id=f"G{i}", name=f"G{i}", type_line="Instant", is_instant=True))
    spell = Card(id="Cruise", name="Treasure Cruise", type_line="Sorcery",
                 mana_cost_string="{7}{U}", converted_mana_cost=8, is_sorcery=True)
    obj = GameObject(spell, owner_id="p2", zone=Zone.HAND)
    p2.hand.append(obj)
    static("cost", "self", {"generic": 1, "per": "cards_in_your_graveyard"}, obj)
    # p1's own (empty) graveyard is irrelevant — the reduction is scoped to
    # the spell's own controller (p2), read straight off the object.
    cost = eng.effective_cast_cost(p2, obj)
    assert cost.converted_mana_cost == 5  # {7}{U} - {3} → {4}{U}


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
