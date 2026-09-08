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

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import CopyPermanentEffect, GameContext
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


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


# -- PAR-18: the add_types/add_subtypes sibling now has a parser route too --


def test_saheelis_artistry_is_modeled():
    card = Card(
        id="Saheeli's Artistry", name="Saheeli's Artistry", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{3}{U}{U}", converted_mana_cost=5,
        oracle_text=(
            "Choose one or both —\n"
            "• Create a token that's a copy of target artifact.\n"
            "• Create a token that's a copy of target creature, except "
            "it's an artifact in addition to its other types."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_copy_add_types_clause_parses_as_artifact():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    effects = match_clause(
        "create a token that's a copy of target creature, except it's an "
        "artifact in addition to its other types"
    )
    assert effects is not None
    assert effects[0].type == "copy_permanent"
    assert effects[0].params.get("add_types") == ["Artifact"]


def test_copy_add_subtypes_clause_parses_as_subtype_words():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    effects = match_clause(
        "create a token that's a copy of target creature, except it's a "
        "shapeshifter rogue in addition to its other types"
    )
    assert effects is not None
    assert effects[0].type == "copy_permanent"
    assert effects[0].params.get("add_subtypes") == ["Shapeshifter", "Rogue"]


def test_copy_permanent_effect_add_types_from_parsed_spec_makes_a_real_artifact_token():
    eng = make_engine("p1", "p2")
    original = put(eng.state, legendary_creature())

    effect = CopyPermanentEffect(target=original, add_types=["Artifact"])
    context = GameContext(eng.state, eng.rules)
    effect.apply(context, targets=[original])

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert "Artifact" in tokens[0].card.type_line
    assert tokens[0].card.is_artifact is True


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


def test_copy_permanent_effect_set_colors_pt_and_subtype():
    # "except it's a 4/4 black zombie" (God-Pharaoh's Gift / Hour of
    # Eternity reanimator-token shape) — P/T override + colour replacement
    # + an added subtype.
    eng = make_engine("p1", "p2")
    c = Card(id="wg", name="White Griffin", type_line="Creature — Griffin",
             is_creature=True, power=2, toughness=2, color_identity={"W"})
    original = put(eng.state, c)

    effect = CopyPermanentEffect(
        target=original, set_power=4, set_toughness=4,
        set_colors=["B"], add_subtypes=["Zombie"],
    )
    effect.apply(GameContext(eng.state, eng.rules), targets=[original])

    tok = next(o for o in eng.state.battlefield if o.is_token)
    assert (tok.card.power, tok.card.toughness) == (4, 4)
    assert tok.card.color_identity == {"B"}
    assert "Zombie" in tok.card.type_line


# -- PAR-18: the "copy of it/that card" pronoun antecedent -------------------
# ("exile up to 1 target creature card from a graveyard. create a token
# that's a copy of that card" — Ardyn, the Usurper/Anikthea, Hand of
# Erebos-shaped) and the compound "except <mod> and <mod>" tail
# (Dedicated Dollmaker-shaped).


def test_copy_permanent_previous_clause_parses_with_referent_previous():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    effects = match_clause(
        "create a token that's a copy of that card", previous_subject=True
    )
    assert effects is not None
    assert effects[0].type == "copy_permanent"
    assert effects[0].params.get("target_kind") is None
    assert effects[0].params.get("referent") == "previous"


def test_copy_permanent_previous_not_offered_without_previous_subject():
    # The pronoun row is `previous_subject_only` — not offered at all unless
    # the caller states an earlier clause really did choose something
    # (`EffectHandler.previous_subject_only`'s own fail-closed gate).
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    assert match_clause("create a token that's a copy of that card") is None


def test_copy_permanent_previous_clause_with_compound_except_tail():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    effects = match_clause(
        "create a token that's a copy of it, except it's not legendary and "
        "it's an artifact in addition to its other types",
        previous_subject=True,
    )
    assert effects is not None
    params = effects[0].params
    assert params.get("referent") == "previous"
    assert params.get("not_legendary") is True
    assert params.get("add_types") == ["Artifact"]


def test_copy_permanent_except_tail_fails_closed_on_an_unrecognised_modifier():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    # "it's a 4/4 black zombie" (P/T + colour + creature subtype) is
    # `_copy_except_modifier`'s `_COPY_EXCEPT_PT_RE` branch now
    # (`set_power`/`set_toughness`/`set_colors`/`add_subtypes`).
    assert match_clause(
        "create a token that's a copy of target creature, except it's a "
        "4/4 black zombie"
    ) == [EffectSpec("copy_permanent", {
        "target_kind": "creature", "set_power": 4, "set_toughness": 4,
        "set_colors": ["B"], "add_subtypes": ["Zombie"],
    })]

    # "it's an enchantment creature" still fails closed — a card-type add
    # this shape can't safely represent.
    assert match_clause(
        "create a token that's a copy of target creature, except it's an "
        "enchantment creature"
    ) is None


def test_exile_up_to_one_from_graveyard_then_copy_that_card_is_modeled():
    card = Card(
        id="Test Grave Coppy", name="Test Grave Coppy", type_line="Sorcery",
        is_sorcery=True, mana_cost_string="{2}{U}", converted_mana_cost=3,
        oracle_text=(
            "Exile up to one target creature card from a graveyard. "
            "Create a token that's a copy of that card, except it isn't "
            "legendary and it's an artifact in addition to its other types."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []
    effects = result.specs[0].effects
    types = [spec.type for spec in effects]
    assert types == ["exile", "copy_permanent"]
    copy_spec = effects[1]
    assert copy_spec.params.get("referent") == "previous"
    assert copy_spec.params.get("not_legendary") is True
    assert copy_spec.params.get("add_types") == ["Artifact"]


def test_copy_permanent_effect_referent_previous_copies_previous_target():
    eng = make_engine("p1", "p2")
    original = put(eng.state, legendary_creature(name="Grave Legend"))
    original.zone = Zone.GRAVEYARD

    effect = CopyPermanentEffect(target_kind=None, referent="previous", not_legendary=True)
    context = GameContext(eng.state, eng.rules)
    context.previous_targets = [original]
    effect.apply(context, targets=None)

    tokens = [o for o in eng.state.battlefield if o.is_token]
    assert len(tokens) == 1
    assert tokens[0].card.name == "Grave Legend"
    assert tokens[0].card.is_legendary is False


def test_copy_permanent_effect_referent_previous_with_no_previous_target_noops():
    eng = make_engine("p1", "p2")
    effect = CopyPermanentEffect(target_kind=None, referent="previous")
    context = GameContext(eng.state, eng.rules)
    context.previous_targets = []
    effect.apply(context, targets=None)

    assert [o for o in eng.state.battlefield if o.is_token] == []
