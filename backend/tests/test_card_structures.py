"""Basic structural card types: copy (707), DFC transform (712), Saga (714)."""

import pytest

from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
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
