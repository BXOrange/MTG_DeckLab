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
