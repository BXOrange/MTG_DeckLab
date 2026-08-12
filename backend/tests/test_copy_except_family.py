"""RULE 706/707's "copy `<X>`, except `<modification>`" family, beyond the
couple of hand-authored shapes that already existed (`EnterAsCopyReplacement.
add_types`/`add_subtypes`). `Card.as_copy` is the one root primitive all
three copy mechanisms (`copy_mechanics.become_copy`, `RulesEngine.
copy_permanent`, the enters-as-a-copy replacement) funnel through, so a new
modifier there reaches all of them for free — this batch adds
``not_legendary`` (RULE 205.4a, "except it isn't legendary" — the single
biggest real template in the family: Multiversal Recruitment/Impostor
Syndrome/Hall of Mirrors-shaped) and threads `add_types`/`add_subtypes`/
``not_legendary`` through `CopyPermanentEffect`, which previously had none
of them at all (only `EnterAsCopyReplacement` did).
"""

from __future__ import annotations

from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.game.effects import CopyPermanentEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def make_engine(*player_ids):
    return GameEngine.new_game(
        [(pid, pid, []) for pid in player_ids], starting_life=20, starting_hand=0
    )


def legendary_creature(name="Legend", power=3, toughness=3):
    return Card(
        id=name, name=name, type_line="Legendary Creature — Human", is_creature=True,
        is_legendary=True, power=power, toughness=toughness,
    )


def put(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# -- Card.as_copy's own new modifier -----------------------------------------


def test_as_copy_not_legendary_strips_the_supertype_and_the_word():
    card = legendary_creature()
    copy = card.as_copy(not_legendary=True)
    assert copy.is_legendary is False
    assert "legendary" not in copy.type_line.lower()
    assert "Creature" in copy.type_line


def test_as_copy_without_not_legendary_keeps_it_legendary():
    card = legendary_creature()
    copy = card.as_copy()
    assert copy.is_legendary is True
    assert "Legendary" in copy.type_line


def test_as_copy_not_legendary_combines_with_add_types():
    card = legendary_creature()
    copy = card.as_copy(add_types=["Artifact"], not_legendary=True)
    assert copy.is_legendary is False
    assert "Artifact" in copy.type_line
    assert "Legendary" not in copy.type_line


# -- CopyPermanentEffect's new not_legendary/add_types/add_subtypes ---------


def test_multiversal_recruitment_is_modeled():
    card = Card(
        id="Multiversal Recruitment", name="Multiversal Recruitment", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{3}{U}", converted_mana_cost=4,
        oracle_text="Create a token that's a copy of target creature you "
                    "control, except it isn't legendary.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_copy_permanent_effect_strips_legendary_from_the_token():
    eng = make_engine("p1", "p2")
    original = put(eng.state, legendary_creature())

    effect = CopyPermanentEffect(target=original, not_legendary=True)
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[original])

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].card.is_legendary is False
    assert tokens[0].is_legendary is False


def test_copy_permanent_effect_without_not_legendary_keeps_legendary():
    eng = make_engine("p1", "p2")
    original = put(eng.state, legendary_creature())

    effect = CopyPermanentEffect(target=original)
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[original])

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].card.is_legendary is True


def test_copy_permanent_effect_add_types_still_works():
    eng = make_engine("p1", "p2")
    original = put(eng.state, legendary_creature())

    effect = CopyPermanentEffect(target=original, add_types=["Artifact"])
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[original])

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert "Artifact" in tokens[0].card.type_line
