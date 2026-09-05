"""Basic structural card types: copy (707), DFC transform (712), Saga (714)."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.events import EventType, GameEvent
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import StackItem
from mtg_analyzer.game import combat
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine, _saga_final_chapter


def creature(name="Bear", power=2, toughness=2, **kw):
    return Card(id=name, name=name, type_line=kw.pop("type_line", "Creature — Bear"),
                is_creature=True, power=power, toughness=toughness, **kw)


def make_engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])],
        starting_life=20, starting_hand=0,
    )


def _put(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


# -- Copy (RULE 707) ---------------------------------------------------------


def test_copy_permanent_makes_a_token_clone():
    eng = make_engine()
    original = _put(eng, creature("Serra Angel", power=4, toughness=4, keywords=["Flying"]))
    copies = eng.rules.copy_permanent("p1", original)
    assert len(copies) == 1
    clone = copies[0]
    assert clone.is_token
    assert clone.name == "Serra Angel"
    assert (clone.power, clone.toughness) == (4, 4)
    assert clone in eng.state.battlefield


def test_copy_effect_end_to_end_via_registry():
    from mtg_analyzer.game.effects import EffectRegistry

    eng = make_engine()
    target = _put(eng, creature("Elephant", power=3, toughness=3))
    caster = _put(eng, creature("Wizard"))
    effect = EffectRegistry.create("copy_permanent", {})
    effect.source = caster
    effect.apply(eng.rules.context, targets=[target])
    clones = [o for o in eng.state.battlefield if o.is_token and o.name == "Elephant"]
    assert len(clones) == 1


# -- Copy of a copy (RULE 707.2, ENG-6/ENG-10) -------------------------------
# A copy effect that applies to an object whose copiable values were already
# changed by a *previous* copy effect must see the current values, not the
# pristine printed card underneath — regardless of which of this engine's
# three copy mechanisms (one-shot ETB, conditional/continuous, "until end of
# turn") produced that previous change.


def test_copy_permanent_of_an_already_copied_object_sees_its_current_form():
    eng = make_engine()
    original = _put(eng, creature("Grave Titan", power=6, toughness=6, keywords=["Deathtouch"]))
    shifted = _put(eng, creature("Vesuvan Shapeshifter", power=3, toughness=3))

    from mtg_analyzer.game import copy_mechanics

    copy_mechanics.become_copy(shifted, original)
    assert shifted.card.name == "Grave Titan"

    clones = eng.rules.copy_permanent("p1", shifted)
    clone = clones[0]
    assert clone.name == "Grave Titan"
    assert (clone.power, clone.toughness) == (6, 6)


def test_become_copy_chains_through_a_previous_copy():
    eng = make_engine()
    from mtg_analyzer.game import copy_mechanics

    original = _put(eng, creature("Grave Titan", power=6, toughness=6))
    middle = _put(eng, creature("Vesuvan Shapeshifter", power=3, toughness=3))
    third = _put(eng, creature("Clever Impersonator", power=3, toughness=3))

    copy_mechanics.become_copy(middle, original)
    copy_mechanics.become_copy(third, middle)  # a copy of a copy

    assert third.card.name == "Grave Titan"
    assert (third.power, third.toughness) == (6, 6)


def test_restoring_a_reverted_conditional_copy_also_restores_front_card_tracking():
    # Reverting a conditional/continuous copy (`continuous._apply_copy_layer`)
    # must undo the `_front_card` bookkeeping `become_copy` now keeps in sync
    # too, or the object would misreport its copiable values afterward.
    eng = make_engine()
    from mtg_analyzer.game import copy_mechanics

    original = _put(eng, creature("Grave Titan", power=6, toughness=6))
    src = _put(eng, creature("Vesuvan Shapeshifter", power=3, toughness=3))

    snapshot = copy_mechanics.snapshot_face(src)
    copy_mechanics.become_copy(src, original)
    assert src.card.name == "Grave Titan"

    copy_mechanics.restore_face(src, snapshot)
    assert src.card.name == "Vesuvan Shapeshifter"
    assert src._front_card.name == "Vesuvan Shapeshifter"


# -- DFC transform (RULE 712) ------------------------------------------------


def _werewolf():
    return Card(
        id="delver", name="Delver of Secrets", type_line="Creature — Human Wizard",
        is_creature=True, power=1, toughness=1,
        layout="transform",
        back_name="Insectile Aberration", back_type_line="Creature — Human Insect",
        back_power=3, back_toughness=2,
        back_image_uri_normal="http://x/back.png",
    )


def test_back_face_builds_a_card():
    back = _werewolf().back_face()
    assert back is not None
    assert back.name == "Insectile Aberration"
    assert back.is_creature and (back.power, back.toughness) == (3, 2)


def test_transform_swaps_faces_and_is_reversible():
    eng = make_engine()
    obj = _put(eng, _werewolf())
    assert obj.name == "Delver of Secrets" and (obj.power, obj.toughness) == (1, 1)
    assert obj.transform() is True
    assert obj.transformed
    assert obj.name == "Insectile Aberration" and (obj.power, obj.toughness) == (3, 2)
    # Transform back.
    assert obj.transform() is True
    assert not obj.transformed
    assert obj.name == "Delver of Secrets"


def test_has_back_face_stays_true_in_the_wire_view_across_a_transform():
    # The frontend's "🔄 peek other face" toggle (gameBoardView.js) needs
    # this to decide whether to offer the button at all — it must stay
    # true once transformed too, not just on the untransformed front.
    eng = make_engine()
    obj = _put(eng, _werewolf())
    assert obj.to_dict()["has_back_face"] is True
    obj.transform()
    assert obj.to_dict()["has_back_face"] is True


def test_has_back_face_is_false_for_an_ordinary_creature():
    eng = make_engine()
    obj = _put(eng, creature("Bear"))
    assert obj.to_dict()["has_back_face"] is False


def test_transform_is_noop_without_a_back_face():
    eng = make_engine()
    obj = _put(eng, creature("Vanilla"))
    assert obj.transform() is False
    assert not obj.transformed


# -- Saga (RULE 714) ---------------------------------------------------------


def _saga(name="History of Benalia"):
    return Card(
        id=name, name=name, type_line="Enchantment — Saga",
        oracle_text=("(As this Saga enters and after your draw step, add a lore counter.)\n"
                     "I, II — Create a 2/2 white Knight creature token with vigilance.\n"
                     "III — Creatures you control get +2/+1 until end of turn."),
    )


def test_saga_enters_with_one_lore_counter():
    eng = make_engine()
    saga = _put(eng, _saga())
    assert saga.lore == 1


def test_saga_final_chapter_parses_roman_numerals():
    assert _saga_final_chapter(_saga()) == 3


def test_saga_advances_and_is_sacrificed_at_final_chapter():
    eng = make_engine()
    eng.begin_turn()  # p1 active
    saga = _put(eng, _saga())  # enters at chapter I
    assert saga.lore == 1
    # Each of the controller's draw steps adds a lore counter (RULE 714.2b).
    eng.rules.advance_sagas(eng.state.active_player)
    assert saga.lore == 2
    eng.rules.advance_sagas(eng.state.active_player)
    assert saga.lore == 3
    # SBA (RULE 704.5x): at the final chapter with an empty stack it's sacrificed.
    eng.rules.check_state_based_actions()
    assert saga not in eng.state.battlefield
    assert saga in eng.state.player_by_id("p1").graveyard


def test_saga_not_sacrificed_before_final_chapter():
    eng = make_engine()
    saga = _put(eng, _saga())  # chapter I of III
    eng.rules.check_state_based_actions()
    assert saga in eng.state.battlefield


def test_saga_sacrifice_is_not_blocked_by_an_unrelated_stack_item():
    """RULE 714.4: the sacrifice check must key off *this Saga's own*
    chapter trigger, not "is the stack empty at all" — an opponent's
    unrelated spell/ability sitting on the stack must not delay it."""
    eng = make_engine()
    saga = _put(eng, _saga())
    saga.counters["lore"] = 3  # already at its final chapter, no trigger pending
    eng.state.stack.append(StackItem(kind="spell", controller_id="p2", description="Lightning Bolt"))
    eng.rules.check_state_based_actions()
    assert saga not in eng.state.battlefield
    assert saga in eng.state.player_by_id("p1").graveyard


def test_saga_sacrifice_is_still_blocked_by_its_own_pending_chapter():
    eng = make_engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _saga())
    saga.counters["lore"] = 3  # final chapter reached...
    assert eng.rules.put_triggers_on_stack() == 1  # ...but chapter I's own trigger is still on the stack
    eng.rules.check_state_based_actions()
    assert saga in eng.state.battlefield
    eng.rules.resolve_top_of_stack()
    eng.rules.check_state_based_actions()
    assert saga not in eng.state.battlefield


def test_advance_sagas_runs_at_precombat_main_not_the_draw_step():
    """RULE 714.3c: the lore counter is a turn-based action as the
    controller's precombat main phase begins — not off the draw step."""
    eng = make_engine()
    eng.begin_turn()
    saga = _put(eng, _saga())
    assert saga.lore == 1
    eng._step_draw()
    assert saga.lore == 1  # unchanged — the draw step no longer advances it
    eng._step_main1()
    assert saga.lore == 2


def _saga_in_play(eng, card, controller="p1"):
    """Like `_put`, but binds the card's chapter abilities first (RULE 714.2d)
    — `add_to_battlefield` fires chapter I's `SAGA_CHAPTER` the moment it's
    added, so the ability must already be bound to be collected."""
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_saga_chapter_i_creates_a_token_end_to_end():
    eng = make_engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _saga())  # RULE 714.2d: chapter I fires on ETB
    assert saga.lore == 1
    assert eng.rules.put_triggers_on_stack() == 1
    eng.rules.resolve_top_of_stack()
    knights = [o for o in eng.state.battlefield if o is not saga]
    assert len(knights) == 1
    knight = knights[0]
    assert knight.is_token
    assert (knight.power, knight.toughness) == (2, 2)
    assert combat.has(knight, "vigilance")


def test_saga_chapter_iii_group_pumps_creatures_you_control():
    eng = make_engine()
    eng.begin_turn()
    saga = _saga_in_play(eng, _saga())  # chapter I: a Knight token
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    bear = _put(eng, creature("Bear"))

    eng.rules.advance_sagas(eng.state.active_player)  # chapter II: another Knight
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()
    eng.rules.advance_sagas(eng.state.active_player)  # chapter III: group pump
    assert saga.lore == 3
    eng.rules.put_triggers_on_stack()
    eng.rules.resolve_top_of_stack()

    knights = [o for o in eng.state.battlefield if o.is_token]
    assert len(knights) == 2  # I and II each created one
    assert bear.temp_power == 2 and bear.temp_toughness == 1
    for knight in knights:
        assert knight.temp_power == 2 and knight.temp_toughness == 1


def _saga_read_ahead(name="Rally to Battle"):
    # Chapters I and II are distinguishable tokens on purpose (RULE 702.155a:
    # a skipped chapter never fires at all, so "one token" alone wouldn't
    # prove *which* chapter produced it).
    return Card(
        id=name, name=name, type_line="Enchantment — Saga",
        keywords=["Read Ahead"],
        oracle_text=(
            "Read ahead\n"
            "I — Create a 1/1 white Soldier creature token.\n"
            "II — Create a 2/2 white Knight creature token with vigilance.\n"
            "III — Creatures you control get +2/+1 until end of turn."
        ),
    )


def test_read_ahead_offers_a_choice_of_starting_chapter():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _saga_read_ahead())
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "read_ahead"
    assert obj not in eng.state.battlefield  # paused before entering
    assert [o["id"] for o in pending["options"]] == ["1", "2", "3"]


def test_read_ahead_choosing_two_enters_at_chapter_ii_only_skipping_chapter_i():
    """RULE 702.155a: only the chapter matching the chosen count fires — a
    skipped lower chapter never triggers, not even delayed."""
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _saga_read_ahead())
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    eng.resolve_pending_choice("2")

    assert obj in eng.state.battlefield
    assert obj.lore == 2
    names = sorted(o.name for o in eng.state.battlefield if o.is_token)
    assert names == ["Knight"]  # chapter II fired; chapter I's Soldier never did


def test_read_ahead_choosing_one_behaves_like_an_ordinary_saga():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _saga_read_ahead())
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    eng.resolve_pending_choice("1")

    assert obj.lore == 1
    names = sorted(o.name for o in eng.state.battlefield if o.is_token)
    assert names == ["Soldier"]


def test_read_ahead_choosing_the_final_chapter_skips_every_other_chapter():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _saga_read_ahead())
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()

    eng.resolve_pending_choice("3")

    assert obj.lore == 3
    assert not any(o.is_token for o in eng.state.battlefield)  # neither I nor II fired
    # Final chapter reached with none of its own triggers left on the stack
    # (chapter III's own pump already resolved via resolve_until_stable) —
    # sacrificed by the SBA (RULE 704.5x/714.4).
    assert obj not in eng.state.battlefield
    assert obj in eng.state.player_by_id("p1").graveyard


def test_saga_without_read_ahead_never_opens_that_choice():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _saga())  # no "Read Ahead" keyword
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert obj in eng.state.battlefield
    assert obj.lore == 1


# -- Leveler (RULE 711) ------------------------------------------------------


def _leveler(name="Test Dragon"):
    return Card(
        id=name, name=name, type_line="Creature — Dragon", is_creature=True,
        power=1, toughness=1, keywords=["Level Up", "Flying", "Haste"],
        oracle_text=(
            "Level up {1}{R} (Level up only as a sorcery.)\n"
            "LEVEL 2-6\n2/2\n"
            f"Whenever {name} attacks, {name} gets +1/+0 until end of turn.\n"
            "LEVEL 7+\n6/6\nFlying, haste"
        ),
    )


def _leveler_in_play(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_leveler_base_pt_and_no_tier_keywords_at_level_zero():
    eng = make_engine()
    dragon = _leveler_in_play(eng, _leveler())
    eng.recompute_continuous_effects()
    assert dragon.level == 0
    assert (dragon.power, dragon.toughness) == (1, 1)
    # Regression: Scryfall's `keywords` array lists Flying/Haste even though
    # they're only printed under LEVEL 7+ — parse_keywords's Leveler
    # cross-check must exclude them from the always-on intrinsic set.
    assert not combat.has(dragon, "flying")
    assert not combat.has(dragon, "haste")


def test_leveler_level_up_is_sorcery_speed_only():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "upkeep"  # not a main phase, stack empty
    p1 = eng.state.active_player
    dragon = _leveler_in_play(eng, _leveler())
    ability = dragon.activated_abilities[0]
    p1.mana_pool.add_many({"R": 1, "C": 1})
    assert not eng.can_activate(p1, dragon, ability)

    eng.state.current_step = "main1"
    assert eng.can_activate(p1, dragon, ability)
    eng.activate_ability(p1, dragon)
    eng.resolve_until_stable()
    assert dragon.level == 1


def test_leveler_tier_pt_and_keywords_are_level_gated():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    dragon = _leveler_in_play(eng, _leveler())
    ability = dragon.activated_abilities[0]

    for _ in range(2):  # RULE 711.4b: no per-turn cap on level-up activations
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.activate_ability(p1, dragon)
        eng.resolve_until_stable()
    assert dragon.level == 2
    eng.recompute_continuous_effects()
    assert (dragon.power, dragon.toughness) == (2, 2)
    assert not combat.has(dragon, "flying")

    # The LEVEL 2-6 attack trigger only fires while `level` is in range.
    eng.state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=dragon.name, player_id="p1", instance_id=dragon.instance_id
        )
    )
    assert eng.rules.put_triggers_on_stack() == 1
    eng.resolve_until_stable()
    assert dragon.temp_power == 1 and dragon.temp_toughness == 0
    eng._step_cleanup()  # RULE 514.2: end the "until end of turn" pump

    for _ in range(5):
        p1.mana_pool.add_many({"R": 1, "C": 1})
        eng.activate_ability(p1, dragon)
        eng.resolve_until_stable()
    assert dragon.level == 7
    eng.recompute_continuous_effects()
    assert (dragon.power, dragon.toughness) == (6, 6)
    assert combat.has(dragon, "flying") and combat.has(dragon, "haste")

    # The attack-trigger pump is gone once past LEVEL 2-6.
    eng.state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=dragon.name, player_id="p1", instance_id=dragon.instance_id
        )
    )
    assert eng.rules.put_triggers_on_stack() == 0


def _leveler_with_base_ability(name="Test Anthem Dragon"):
    """RULE 711.4: a non-keyword ability printed *before* the first LEVEL
    tier is "treated normally" — unconditional, not gated by the current
    level at all (unlike a tier's own P/T/keywords/triggers)."""
    return Card(
        id=name, name=name, type_line="Creature — Dragon", is_creature=True,
        power=1, toughness=1, keywords=["Level Up"],
        oracle_text=(
            "Level up {1}{R} (Level up only as a sorcery.)\n"
            "Other creatures you control get +1/+1.\n"
            "LEVEL 2-6\n2/2\n"
            "LEVEL 7+\n6/6\nFlying"
        ),
    )


def test_leveler_base_ability_is_unconditional_at_every_level():
    eng = make_engine()
    dragon = _leveler_in_play(eng, _leveler_with_base_ability())
    bear = _put(eng, creature("Bear"))
    eng.recompute_continuous_effects()
    assert dragon.level == 0
    assert (bear.power, bear.toughness) == (3, 3)  # anthem already active at level 0

    dragon.counters["level"] = 7
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)  # still active well past its own tiers
    assert combat.has(dragon, "flying")  # and the tier grant still applies alongside it


# -- Class (RULE 716) ---------------------------------------------------------


def _class_card(name="Test Class"):
    return Card(
        id=name, name=name, type_line="Enchantment — Class",
        oracle_text=(
            "(Gain the next level as a sorcery to add its ability.)\n"
            "{1}{G}: Level 2\nCreatures you control get +1/+1.\n"
            "{3}{G}: Level 3\nCreatures you control have trample."
        ),
    )


def _class_in_play(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, controller_id=controller, zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def test_class_enters_at_level_one():
    eng = make_engine()
    cls = _class_in_play(eng, _class_card())
    assert cls.class_level == 1


def test_class_level_up_must_go_in_order_and_is_sorcery_speed():
    eng = make_engine()
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    cls = _class_in_play(eng, _class_card())
    level2, level3 = cls.activated_abilities

    # RULE 716.4c: level 3 isn't legal before level 2 is reached.
    p1.mana_pool.add_many({"G": 1, "C": 3})
    assert not eng.can_activate(p1, cls, level3)

    p1.mana_pool.add_many({"G": 1, "C": 1})
    assert eng.can_activate(p1, cls, level2)
    eng.activate_ability(p1, cls, 0)
    eng.resolve_until_stable()
    assert cls.class_level == 2

    bear = _put(eng, creature("Bear"))
    eng.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (3, 3)  # +1/+1 anthem active
    assert not combat.has(bear, "trample")

    p1.mana_pool.add_many({"G": 1, "C": 3})
    eng.activate_ability(p1, cls, 1)
    eng.resolve_until_stable()
    assert cls.class_level == 3
    eng.recompute_continuous_effects()
    # Cumulative: the level-2 anthem is still active alongside level 3's grant.
    assert (bear.power, bear.toughness) == (3, 3)
    assert combat.has(bear, "trample")


def _class_card_with_one_shot_triggers(name="Test Talent"):
    """RULE 716.4c-adjacent: a level whose body is a one-shot "When this
    Class becomes level N, <effect>." trigger rather than an ordinary
    cumulative static/keyword grant — and a preamble "When this Class
    enters, <effect>." ETB trigger (RULE 716's own version of RULE 603.1's
    ordinary self-ETB shape, which excludes "this Class"/"this Saga" from
    the generic ``~``-folding on purpose — see `normalize.py`)."""
    return Card(
        id=name, name=name, type_line="Enchantment — Class",
        oracle_text=(
            "(Gain the next level as a sorcery to add its ability.)\n"
            "When this Class enters, create a 2/2 green Wolf creature token.\n"
            "{1}{G}: Level 2\nWhen this Class becomes level 2, draw two cards."
        ),
    )


def test_class_enters_trigger_fires_on_etb():
    # `_class_in_play` places the object directly (like `_saga_in_play`/
    # `_leveler_in_play`), which skips `ENTERS_BATTLEFIELD` entirely — that
    # event is only fired by the real cast-resolution path
    # (`RulesEngine._resolve_permanent_spell`), so this needs an actual cast.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _class_card_with_one_shot_triggers())
    bind_from_catalogue(obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    wolves = [o for o in eng.state.battlefield if o is not obj]
    assert len(wolves) == 1 and wolves[0].is_token and wolves[0].name == "Wolf"


def test_class_becomes_level_trigger_is_a_one_shot_not_a_cumulative_grant():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    for i in range(2):
        p1.library.append(GameObject(creature(f"Filler {i}"), owner_id="p1", zone=Zone.LIBRARY))
    cls = _in_hand(eng, _class_card_with_one_shot_triggers())
    bind_from_catalogue(cls)
    eng.cast_spell(p1, cls)
    eng.resolve_until_stable()  # drain the ETB Wolf trigger

    p1.mana_pool.add_many({"G": 1, "C": 1})
    before = len(p1.hand)
    eng.activate_ability(p1, cls, 0)
    eng.rules.resolve_top_of_stack()  # resolves the level-up itself
    assert cls.class_level == 2
    assert eng.rules.put_triggers_on_stack() == 1  # the "becomes level 2" trigger, exactly once
    eng.rules.resolve_top_of_stack()
    assert len(p1.hand) == before + 2

    # A one-shot "becomes level N" trigger must not re-fire just because
    # `class_level` still reads >= 2 later (unlike an ordinary cumulative
    # static/keyword grant) — nothing left on the stack, no more cards drawn.
    assert eng.rules.put_triggers_on_stack() == 0


# -- Modal DFC casting (RULE 712.10) -----------------------------------------


def _mdfc_land_back(name="Bala Ged Recovery"):
    """Front: a plain, effect-less sorcery. Back: a land (Zendikar Rising shape)."""
    return Card(
        id=name, name=name, type_line="Sorcery",
        mana_cost_string="{2}{G}", converted_mana_cost=3, is_sorcery=True,
        layout="modal_dfc",
        back_name="Bala Ged Sanctuary", back_type_line="Land",
        back_image_uri_normal="http://x/back.png",
    )


def _mdfc_damage_back(name="Fiery Discharge"):
    """Front: effect-less. Back: an instant with its own targeting effect —
    proves casting the back face rebinds *its* abilities, not the front's
    (the front has none)."""
    return Card(
        id=name, name=name, type_line="Sorcery",
        mana_cost_string="{1}{R}", converted_mana_cost=2, is_sorcery=True,
        layout="modal_dfc",
        back_name="Molten Rebuke", back_type_line="Instant",
        back_mana_cost_string="{R}",
        back_oracle_text="Molten Rebuke deals 3 damage to any target.",
        back_image_uri_normal="http://x/back.png",
    )


def _mdfc_destroy_back(name="Ravaging Blast"):
    """Back requires a *creature* target (not "any target", which a player
    would always satisfy) — for a board with no creatures, has no legal
    target at all."""
    return Card(
        id=name, name=name, type_line="Sorcery",
        mana_cost_string="{1}{B}", converted_mana_cost=2, is_sorcery=True,
        layout="modal_dfc",
        back_name="Grim Undoing", back_type_line="Sorcery",
        back_mana_cost_string="{2}{B}",
        back_oracle_text="Destroy target creature.",
        back_image_uri_normal="http://x/back.png",
    )


def _in_hand(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.HAND)
    return obj


def _ready_main_phase(eng):
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng.state.active_player


def test_modal_dfc_offers_both_faces_in_legal_actions():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _mdfc_land_back())
    p1.mana_pool.add_many({"G": 1, "C": 2})  # front costs {2}{G}
    actions = eng.legal_actions(p1)
    front = [a for a in actions if a.get("instance_id") == obj.instance_id and not a.get("face")]
    back = [a for a in actions if a.get("instance_id") == obj.instance_id and a.get("face") == "back"]
    assert front and front[0]["type"] == "cast_spell" and front[0]["name"] == "Bala Ged Recovery"
    assert back and back[0]["type"] == "play_land" and back[0]["name"] == "Bala Ged Sanctuary"


def test_playing_the_back_face_as_a_land():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _mdfc_land_back())
    assert not eng.can_play_land(p1, obj)  # front is a sorcery, not a land
    assert eng.can_play_land(p1, obj, face="back")
    eng.play_land(p1, obj, face="back")
    assert obj in eng.state.battlefield
    assert obj.name == "Bala Ged Sanctuary"
    assert obj.card.is_land


def test_casting_the_back_face_resolves_with_its_own_effects_and_cost():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, _mdfc_damage_back())
    p1.mana_pool.add_many({"R": 1})
    assert not eng.can_cast(p1, obj)  # front costs {1}{R}, only {R} available
    assert eng.can_cast(p1, obj, face="back")  # back costs just {R}
    eng.cast_spell(p1, obj, targets=[p2], face="back")
    assert obj.name == "Molten Rebuke"
    eng.resolve_until_stable()
    assert p2.life == 17


def test_cast_action_reports_targets_for_the_back_face():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _mdfc_damage_back())
    p1.mana_pool.add_many({"R": 1})
    action = eng._cast_action(p1, obj, face="back")
    assert action["face"] == "back"
    assert action["requires_target"] is True
    # The preview must not leave the object switched.
    assert obj.card.name == "Fiery Discharge"
    assert obj.spell_effects == []


def _mdfc_free_back(name="Testland's Silent Side"):
    """A back face with a genuinely blank `back_mana_cost_string` — the
    common shape for most transform backs (a Battle's Siege side, most
    creature-transform backs), unlike `_mdfc_damage_back`/`_mdfc_destroy_back`
    above, whose backs both carry a real printed cost. Front is priced high
    on purpose so a bug that mistakes the back's cost for the front's is
    unmistakable (it would come out costing {5}, not free)."""
    return Card(
        id=name, name=name, type_line="Sorcery",
        mana_cost_string="{3}{R}{R}", converted_mana_cost=5, is_sorcery=True,
        layout="modal_dfc",
        back_name="Testland's Quiet Reverse", back_type_line="Creature — Phyrexian",
        back_mana_cost_string="",
        back_power=3, back_toughness=3,
        back_oracle_text="",
    )


def test_back_face_with_a_blank_cost_is_actually_free():
    # Regression: `Card.back_face()` used to stamp the *front's*
    # `converted_mana_cost` onto the back `Card` regardless of the back's own
    # (often blank) `back_mana_cost_string`. `ManaCost.from_card` treats a
    # blank `mana_cost_string` as a legacy row predating that field and
    # reconstructs a cost from `converted_mana_cost` instead (the Sol Ring
    # bug fix) — so the mismatch resurrected a fake nonzero generic cost on
    # a back face that should have been free, making it uncastable with an
    # empty mana pool.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _mdfc_free_back())
    assert not eng.can_cast(p1, obj)  # front costs {3}{R}{R}, no mana available
    assert eng.can_cast(p1, obj, face="back")  # back is genuinely free
    cost = eng.effective_cast_cost(p1, obj, face="back")
    assert cost.is_free
    assert cost.converted_mana_cost == 0


def test_rejected_back_face_cast_restores_the_front_face():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_hand(eng, _mdfc_destroy_back())
    p1.mana_pool.add_many({"B": 1, "C": 2})  # back costs {2}{B} — affordable
    front_card = obj.card
    # No creatures anywhere: "destroy target creature" has no legal target,
    # so the cost/timing check passes but `has_legal_targets` still rejects
    # it — exercising the switch-then-rollback path, not the earlier
    # (never-switched) cost-check rejection.
    with pytest.raises(ValueError):
        eng.cast_spell(p1, obj, face="back")
    assert obj.card is front_card
    assert obj.name == "Ravaging Blast"
    assert getattr(obj, "spell_effects", []) == []
    assert obj in p1.hand


# -- Adventure (RULE 715) / Split & Fuse (RULE 709) --------------------------


def _adventure_creature(name="Test Faerie"):
    """Front: a creature. Back: its Adventure instant half with a damage
    effect — proves casting the spell then recasting the creature from
    exile (RULE 715.3d)."""
    return Card(
        id=name, name=name, type_line="Creature — Faerie",
        mana_cost_string="{1}{U}{U}", converted_mana_cost=3,
        is_creature=True, power=3, toughness=1,
        layout="adventure",
        back_name="Test Theft", back_type_line="Instant — Adventure",
        back_mana_cost_string="{1}{U}",
        back_oracle_text="Test Theft deals 2 damage to any target.",
    )


def test_casting_the_adventure_spell_then_recasting_the_creature_from_exile():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, _adventure_creature())
    p1.mana_pool.add_many({"U": 1, "C": 1})  # back costs {1}{U}
    assert not eng.can_cast(p1, obj)  # front costs {1}{U}{U} — one U short
    assert eng.can_cast(p1, obj, face="back")
    eng.cast_spell(p1, obj, targets=[p2], face="back")
    assert obj.name == "Test Theft"
    eng.resolve_until_stable()
    assert p2.life == 18

    # RULE 715.3d: exiled as the creature (not the graveyard), and castable.
    assert obj in p1.exile
    assert obj not in p1.graveyard
    assert obj.card.is_creature
    assert obj.name == "Test Faerie"
    assert obj.adventure_castable is True

    p1.mana_pool.add_many({"U": 2, "C": 1})  # front costs {1}{U}{U}
    assert eng.can_cast(p1, obj)
    eng.cast_spell(p1, obj)
    eng.resolve_until_stable()
    assert obj in eng.state.battlefield
    assert obj not in p1.exile
    assert obj.adventure_castable is False


def _split_card(name="Test Fire // Test Ice"):
    """Front (bare-name-folded self-reference, RULE 709.3): a damage half.
    Back: an independent damage half with its own cost — no Fuse."""
    return Card(
        id=name, name=name, type_line="Instant // Instant",
        mana_cost_string="{1}{R}", converted_mana_cost=2, is_instant=True,
        oracle_text="Test Fire deals 2 damage to any target.",
        layout="split",
        back_name="Test Ice", back_type_line="Instant",
        back_mana_cost_string="{U}",
        back_oracle_text="Test Ice deals 1 damage to any target.",
    )


def test_split_card_offers_and_casts_both_halves_independently():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, _split_card())
    p1.mana_pool.add_many({"R": 1, "C": 1})
    actions = eng.legal_actions(p1)
    front = [a for a in actions if a.get("instance_id") == obj.instance_id and not a.get("face")]
    back = [a for a in actions if a.get("instance_id") == obj.instance_id and a.get("face") == "back"]
    assert front and front[0]["type"] == "cast_spell" and front[0]["name"] == "Test Fire // Test Ice"
    assert not back  # back costs {U} — not affordable yet

    p1.mana_pool.add_many({"U": 1})
    actions = eng.legal_actions(p1)
    back = [a for a in actions if a.get("instance_id") == obj.instance_id and a.get("face") == "back"]
    assert back and back[0]["type"] == "cast_spell" and back[0]["name"] == "Test Ice"

    eng.cast_spell(p1, obj, targets=[p2], face="back")
    assert obj.name == "Test Ice"
    eng.resolve_until_stable()
    assert p2.life == 19
    assert obj in p1.graveyard


def _fuse_split_card(name="Test Turn // Test Burn"):
    """RULE 709.4: both halves' own bare-named effects, castable together
    for the combined cost."""
    return Card(
        id=name, name=name, type_line="Instant // Instant",
        mana_cost_string="{2}{U}", converted_mana_cost=5, is_instant=True,
        oracle_text="Test Turn deals 1 damage to any target.",
        layout="split", has_fuse=True,
        back_name="Test Burn", back_type_line="Instant",
        back_mana_cost_string="{1}{R}",
        back_oracle_text="Test Burn deals 2 damage to any target.",
    )


def test_fuse_face_combines_both_halves_cost_and_text():
    fused = _fuse_split_card().fuse_face()
    assert fused is not None
    assert fused.mana_cost_string == "{2}{U}{1}{R}"
    assert "~ deals 1 damage" in fused.oracle_text
    assert "~ deals 2 damage" in fused.oracle_text


def test_fuse_casts_both_halves_as_one_spell_for_the_combined_cost():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_hand(eng, _fuse_split_card())
    p1.mana_pool.add_many({"U": 1, "R": 1, "C": 3})  # combined {2}{U}{1}{R}
    assert eng.can_cast(p1, obj, face="fuse")
    action = eng._cast_action(p1, obj, face="fuse")
    assert action["face"] == "fuse"
    # Every effect on a spell reads the same flat `targets` list (its own
    # first entry) — one shared target is enough for both halves to hit p2.
    eng.cast_spell(p1, obj, targets=[p2], face="fuse")
    eng.resolve_until_stable()
    assert p2.life == 17  # 20 - 1 (Turn) - 2 (Burn)
    assert obj in p1.graveyard


# -- Prepared (RULE 722, Preparation Cards) -----------------------------------


def _preparation_creature(name="Test Bard"):
    """Front: a creature with a real "whenever ~ attacks, it becomes
    prepared" trigger (RULE 722.3a), parsed through the normal oracle-text
    pipeline (attacks is already a recognized trigger condition — the
    "becomes prepared" clause handler is what's new). Back: the prepare
    spell (RULE 722.3c), its own bare name folded to "~" like any other
    back-face oracle text."""
    return Card(
        id=name, name=name, type_line="Creature — Bard",
        mana_cost_string="{1}{W}", converted_mana_cost=2,
        is_creature=True, power=2, toughness=2,
        oracle_text="Whenever this creature attacks, it becomes prepared.",
        layout="prepare",
        back_name="Test Stanza", back_type_line="Sorcery",
        back_mana_cost_string="{1}{W}",
        back_oracle_text="Test Stanza deals 2 damage to any target.",
    )


def test_attacking_becomes_prepared_and_creates_a_castable_exiled_copy():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bard = _put(eng, _preparation_creature())
    bind_from_catalogue(bard)
    assert not bard.prepared

    eng.state.fire_event(
        GameEvent(
            EventType.ATTACKS, attacker=bard.name, player_id="p1", instance_id=bard.instance_id
        )
    )
    assert eng.rules.put_triggers_on_stack() == 1
    eng.resolve_until_stable()

    assert bard.prepared is True
    copies = [o for o in p1.exile if o.prepared_source_id == bard.instance_id]
    assert len(copies) == 1
    copy = copies[0]
    assert copy.is_token
    assert copy.name == "Test Stanza"
    assert copy.card.mana_cost_string == "{1}{W}"


def test_prepared_copy_is_serialized_for_the_board_but_an_ordinary_object_is_not():
    # The board's "castable from exile" callout (gameBoardView.js) tells a
    # prepared copy apart from an inert exiled card via this flag.
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bard = _put(eng, _preparation_creature())
    bind_from_catalogue(bard)
    eng.rules.make_prepared(bard)
    copy = next(o for o in p1.exile if o.prepared_source_id == bard.instance_id)

    assert copy.to_dict()["prepared_copy"] is True
    assert bard.to_dict()["prepared_copy"] is False


def test_the_exiled_copy_is_castable_and_clears_prepared_on_cast():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    bard = _put(eng, _preparation_creature())
    bind_from_catalogue(bard)
    eng.rules.make_prepared(bard)
    copy = next(o for o in p1.exile if o.prepared_source_id == bard.instance_id)

    p1.mana_pool.add_many({"W": 1, "C": 1})
    actions = eng.legal_actions(p1)
    offer = [a for a in actions if a.get("instance_id") == copy.instance_id]
    assert offer and offer[0]["type"] == "cast_spell"

    eng.cast_spell(p1, copy, targets=[p2])
    assert bard.prepared is False  # RULE 722.3c: cleared the moment it's cast
    eng.resolve_until_stable()
    assert p2.life == 18


def test_prepared_copy_is_reaped_if_the_source_leaves_the_battlefield():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bard = _put(eng, _preparation_creature())
    bind_from_catalogue(bard)
    eng.rules.make_prepared(bard)
    copy = next(o for o in p1.exile if o.prepared_source_id == bard.instance_id)
    assert copy in p1.exile

    eng.rules.destroy(bard)  # the source leaves the battlefield
    eng.rules.check_state_based_actions()
    assert copy not in p1.exile


def test_make_prepared_is_a_no_op_if_already_prepared():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    bard = _put(eng, _preparation_creature())
    bind_from_catalogue(bard)

    eng.rules.make_prepared(bard)
    copies = [o for o in p1.exile if o.prepared_source_id == bard.instance_id]
    assert len(copies) == 1

    eng.rules.make_prepared(bard)  # RULE 722.3a: already prepared — no-op
    copies = [o for o in p1.exile if o.prepared_source_id == bard.instance_id]
    assert len(copies) == 1


# -- transform_permanent / daybound / nightbound (RULE 712.8 / 702.145) ------


def _daybound_werewolf(name="Pack Wolf"):
    """A daybound/nightbound pair (RULE 702.145a): front keyworded daybound,
    back (bigger) keyworded nightbound — the same shape as a real Innistrad
    werewolf, minus the flavour text."""
    return Card(
        id=name, name=name, type_line="Creature — Wolf",
        is_creature=True, power=2, toughness=2,
        oracle_text="Daybound",
        layout="transform",
        back_name="Feral " + name, back_type_line="Creature — Wolf",
        back_power=4, back_toughness=4,
        back_oracle_text="Nightbound",
    )


def test_transform_permanent_rebinds_keywords_for_the_new_face():
    eng = make_engine()
    wolf = _put(eng, _daybound_werewolf())
    bind_from_catalogue(wolf)
    assert combat.has(wolf, "daybound")
    assert not combat.has(wolf, "nightbound")

    assert eng.rules.transform_permanent(wolf) is True

    assert wolf.transformed
    assert (wolf.power, wolf.toughness) == (4, 4)
    # The old face's keyword must be gone, not just the new one added —
    # `GameObject.transform` alone would leave "daybound" stuck forever.
    assert combat.has(wolf, "nightbound")
    assert not combat.has(wolf, "daybound")


def test_transform_permanent_is_noop_without_a_back_face():
    eng = make_engine()
    obj = _put(eng, creature("Vanilla"))
    assert eng.rules.transform_permanent(obj) is False


def test_day_night_established_when_a_daybound_permanent_enters():
    eng = make_engine()
    assert eng.state.day_night is None
    wolf = _put(eng, _daybound_werewolf())
    bind_from_catalogue(wolf)
    eng.rules.check_state_based_actions()
    assert eng.state.day_night == "day"


def test_day_night_transforms_a_mismatched_permanent_immediately():
    eng = make_engine()
    eng.state.day_night = "night"  # already night by the time it enters
    wolf = _put(eng, _daybound_werewolf())
    bind_from_catalogue(wolf)
    assert not wolf.transformed
    eng.rules.check_state_based_actions()  # RULE 702.145c: immediate, not an SBA per se
    assert wolf.transformed
    assert wolf.name == "Feral Pack Wolf"


def test_day_becomes_night_when_last_turns_player_cast_no_spells():
    eng = make_engine()
    eng.state.day_night = "day"
    eng.state._last_turn_player_id = "p1"
    eng.state._last_turn_spell_count = 0
    eng.rules.apply_day_night_turn_check()  # RULE 731.2a
    assert eng.state.day_night == "night"


def test_night_becomes_day_when_last_turns_player_cast_two_spells():
    eng = make_engine()
    eng.state.day_night = "night"
    eng.state._last_turn_player_id = "p1"
    eng.state._last_turn_spell_count = 2
    eng.rules.apply_day_night_turn_check()  # RULE 731.2b
    assert eng.state.day_night == "day"


def test_day_night_flips_across_a_real_turn_via_the_untap_step():
    eng = make_engine()
    eng.start()  # turn 1, p1 active, positioned before its untap step
    eng.state.day_night = "day"
    wolf = _put(eng, _daybound_werewolf())
    bind_from_catalogue(wolf)
    for _ in range(12):  # every step of p1's turn 1 — no spells cast
        eng.advance_step()
    eng.advance_step()  # turn 2's untap step: RULE 731.2a checked here
    assert eng.state.active_player.id == "p2"
    assert eng.state.day_night == "night"
    assert wolf.transformed  # RULE 702.145c applied immediately on the flip


def test_day_night_is_visible_in_the_wire_view():
    # A player can't react to something the frontend never receives.
    eng = make_engine()
    eng.state.day_night = "night"
    assert eng.state.to_dict()["day_night"] == "night"


# -- MDFC commander cast from the command zone (RULE 712.10 + 903.6) --------


def _in_command(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, is_commander=True)
    eng.state.player_by_id(controller).add_to_zone(obj, Zone.COMMAND)
    return obj


def test_mdfc_commander_offers_a_castable_back_face_from_the_command_zone():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_command(eng, _mdfc_damage_back())
    p1.mana_pool.add_many({"C": 1, "R": 1})  # affords either face ({1}{R} or {R})
    actions = eng.legal_actions(p1)
    front = [a for a in actions if a.get("instance_id") == obj.instance_id and not a.get("face")]
    back = [a for a in actions if a.get("instance_id") == obj.instance_id and a.get("face") == "back"]
    assert front and front[0]["type"] == "cast_spell" and front[0]["name"] == "Fiery Discharge"
    assert back and back[0]["type"] == "cast_spell" and back[0]["name"] == "Molten Rebuke"


def test_mdfc_commanders_land_back_face_is_not_offered_from_the_command_zone():
    """RULE 903.6 only lets a commander be *cast* from the command zone —
    a land back face isn't a spell, so it stays unreachable there even
    though the same land is offered as `play_land` once it's in hand
    (`test_playing_the_back_face_as_a_land`)."""
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    obj = _in_command(eng, _mdfc_land_back())
    p1.mana_pool.add_many({"G": 1, "C": 2})  # front costs {2}{G}
    actions = eng.legal_actions(p1)
    front = [a for a in actions if a.get("instance_id") == obj.instance_id and not a.get("face")]
    back = [a for a in actions if a.get("instance_id") == obj.instance_id and a.get("face") == "back"]
    assert front and front[0]["type"] == "cast_spell" and front[0]["name"] == "Bala Ged Recovery"
    assert back == []


def test_casting_an_mdfc_commanders_back_face_still_pays_commander_tax():
    eng = make_engine()
    p1 = _ready_main_phase(eng)
    p2 = eng.state.player_by_id("p2")
    obj = _in_command(eng, _mdfc_damage_back())
    p1.mana_pool.add_many({"R": 1})
    assert eng.can_cast(p1, obj, face="back")  # back costs just {R}
    eng.cast_spell(p1, obj, targets=[p2], face="back")
    assert obj.name == "Molten Rebuke"
    assert p1.commander_casts.get(obj.instance_id) == 1

    # RULE 903.9: recast (still the same commander, same tax bucket) —
    # tax is {2} per previous cast, regardless of which face paid for it,
    # and applies on top of *either* face's own printed cost.
    obj2 = _in_command(eng, _mdfc_damage_back())
    obj2.instance_id = obj.instance_id
    assert eng.commander_tax(p1, obj2) == 2
    # {R} (mv 1) + {2} tax = mv 3.
    assert eng.effective_cast_cost(p1, obj2, face="back").converted_mana_cost == 3
