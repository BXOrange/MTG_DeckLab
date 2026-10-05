"""Batch 4 — "create a token that's a copy of …" (PLAY-ALL Step 1).

New axes (each measured over the whole card cache, 0 regressed):

* the head takes a count and flags — "create 2 tokens that are copies of …", "create X tokens …", "create a
  tapped token that's a copy of ~" (`handlers._COPY_HEAD`);
* "target token [you control]" and the "you control" scope over artifact / enchantment / artifact-or-enchantment
  (`subgrammars.YOU_TARGET_KINDS`, `targeting.TARGET_FRAMES`);
* the pronoun row takes "that creature/permanent/artifact/enchantment/land" after a clause that chose it;
* the bare "It gains haste." tail of a copy / reanimation clause — an indefinite grant, as printed.

Reference: parser/oracle/catalogue/handlers.py, subgrammars.py, game/targeting.py, game/effects/counters_tokens.py.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.subgrammars import (
    SCOPED_TARGET_BASE, YOU_TARGET_KINDS, resolve_target_kind,
)
from mtg_analyzer.parser.oracle.normalize import normalize
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
                is_instant="Instant" in type_line, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card, controller="p1", token=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.is_token = token
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _cast(eng, text, targets=None, x=0):
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_card("Copier", "Instant", text, converted_mana_cost=0), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(p1, spell, targets=targets or [], x=x)
    eng.resolve_until_stable()


def _parse(text):
    return parse_effect_body(normalize(text))


# --- the target vocabulary ----------------------------------------------------------------------------


@pytest.mark.parametrize("phrase, kind", [
    ("target token", "token"),
    ("target token you control", "token_you_control"),
    ("target artifact you control", "artifact_you_control"),
    ("target enchantment you control", "enchantment_you_control"),
    ("target artifact or enchantment you control", "artifact_or_enchantment_you_control"),
    # the rows that already named their own scope are unchanged
    ("another target red creature you control", "other_creature_you_control"),
    ("target creature you control", "creature_you_control"),
    ("target land you control", "land_you_control"),
])
def test_target_phrases_resolve(phrase, kind):
    assert resolve_target_kind(phrase) == kind


def test_a_pool_without_a_you_control_frame_stays_unclaimed():
    assert resolve_target_kind("target planeswalker you control") is None


@pytest.mark.parametrize("base, scoped", sorted(YOU_TARGET_KINDS.items()))
def test_you_kinds_are_real_engine_frames_over_the_same_pool(base, scoped):
    assert scoped in targeting.ALLOWED_TARGET_KINDS and base in targeting.ALLOWED_TARGET_KINDS
    frame = targeting.TARGET_FRAMES[scoped]
    assert frame.scope == targeting.SCOPE_YOU
    base_frame = targeting.TARGET_FRAMES.get(base)
    assert frame.types == (base_frame.types if base_frame is not None else base)
    assert SCOPED_TARGET_BASE[scoped] == base


# --- parse -------------------------------------------------------------------------------------------


def test_the_head_carries_a_count_and_flags():
    [spec] = _parse("Create 2 tokens that are copies of target token you control.")
    assert spec.type == "copy_permanent" and spec.params["count"] == 2
    assert spec.params["target_kind"] == "token_you_control"
    [spec] = _parse("Create X tokens that are copies of target creature you control.")
    assert spec.params["count"] == "x"
    [spec] = _parse("At the beginning of your end step, create a tapped token that's a copy of ~.") or [None]
    # a bare clause (no trigger shell) is the unit under test
    [spec] = _parse("Create a tapped token that's a copy of ~.")
    assert spec.params["tapped"] is True and spec.params["referent"] == "source"


def test_the_pronoun_row_takes_that_creature_after_a_chosen_one():
    specs = _parse("Choose target creature you control. Create a token that's a copy of that creature.")
    assert [s.type for s in specs] == ["choose_targets", "copy_permanent"]
    assert specs[1].params["referent"] == "previous"
    # "that creature" with nothing before it names nobody
    assert not _parse("Create a token that's a copy of that creature.")


def test_bare_haste_after_a_copy_is_an_indefinite_grant():
    specs = _parse("Create a token that's a copy of target creature you control. It gains haste. "
                   "Sacrifice it at the beginning of the next end step.")
    assert [s.type for s in specs] == ["copy_permanent", "grant_until", "create_delayed_trigger"]
    grant = specs[1].params
    assert grant["duration"] == "rest_of_game" and grant["previous_subject"] is True
    # …but only haste: another bare grant would be a different card
    assert not _parse("Create a token that's a copy of target creature you control. It gains flying.")


# --- execute -----------------------------------------------------------------------------------------


def _names(eng, controller="p1"):
    return sorted(o.card.name for o in eng.state.battlefield if o.controller_id == controller)


def test_a_token_you_control_is_the_only_legal_target_and_x_copies_are_made():
    eng = _engine()
    mine = _bf(eng, _card("Soldier Token"), token=True)
    _bf(eng, _card("Real Bear"))                       # a nontoken of mine
    _bf(eng, _card("Their Token"), controller="p2", token=True)
    p1 = eng.state.player_by_id("p1")
    legal = targeting.legal_targets(
        eng.state, "p1", targeting.TargetSpec(kind="token_you_control"), source=None,
    )
    assert {o["instance_id"] for o in legal} == {mine.instance_id}
    p1.mana_pool.add_many({"C": 2})
    _cast(eng, "Create X tokens that are copies of target token you control.", [mine], x=2)
    assert _names(eng).count("Soldier Token") == 3
    assert all(o.is_token for o in eng.state.battlefield if o.card.name == "Soldier Token")


def test_artifact_you_control_excludes_the_opponents_artifacts():
    eng = _engine()
    mine = _bf(eng, _card("My Rock", "Artifact"))
    theirs = _bf(eng, _card("Their Rock", "Artifact"), controller="p2")
    legal = targeting.legal_targets(
        eng.state, "p1", targeting.TargetSpec(kind="artifact_you_control"), source=None,
    )
    ids = {o["instance_id"] for o in legal}
    assert mine.instance_id in ids and theirs.instance_id not in ids


def test_a_copy_that_gains_haste_keeps_it():
    eng = _engine()
    bear = _bf(eng, _card("Bear"))
    _cast(eng, "Create a token that's a copy of target creature you control. It gains haste. "
               "Sacrifice it at the beginning of the next end step.", [bear])
    [copy] = [o for o in eng.state.battlefield if o.is_token and o.card.name == "Bear"]
    eng.recompute_continuous_effects()
    assert "haste" in copy.granted_keywords and "haste" not in bear.granted_keywords
