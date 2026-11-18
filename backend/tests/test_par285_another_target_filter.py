"""PAR-285: "another target <subtype / quality> [you control]" announces the plain kind plus the source exclusion.

The operand grammar used to refuse every "another target X" whose X is not a bare creature (no source-excluding frame
exists for a subtype or a snow permanent). The parser now emits the plain kind with the RULE 109.5 `excludes_source`
marker on the `choose_targets` announcement; `EffectRegistry.create` -> `targeting.mark_source_exclusion` turns it into
`TargetSpec.exclude_source`. Tests run parser -> binder -> `targeting.legal_targets` on the real cards."""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import build_effects
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.game import creature, make_engine, obj_on_battlefield


def _announced(name: str):
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    result = parse_oracle(card)
    assert result.modeled is True, name
    seqs = [e for ab in result.specs for e in ab.effects if e.type == "seq"]
    specs = [spec for e in seqs for spec in build_effects([e], None)[0].target_specs]
    assert len(specs) == 1, name
    return specs[0]


def _legal_ids(state, spec, source):
    return {t["instance_id"] for t in targeting.legal_targets(state, "p1", spec, source=source)}


def test_announcement_carries_the_exclusion_marker():
    specs = match_clause("put a +1/+1 counter on another target vampire you control")
    assert specs is not None
    announce = specs[0].params["effects"][0]["params"]
    assert announce["kinds"] == ["permanent_you_control"]
    assert announce["creature_filter"] == {"subtype": "vampire"}
    assert announce["excludes_source"] is True


def test_plain_subtype_target_is_not_marked():
    specs = match_clause("put a +1/+1 counter on target vampire you control")
    assert "excludes_source" not in specs[0].params["effects"][0]["params"]


def test_subtype_you_control_never_offers_the_source():
    spec = _announced("Sanguine Glorifier")
    assert spec.exclude_source is True
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Glorifier", type_line="Creature — Vampire Cleric"), "p1")
    other_vampire = obj_on_battlefield(state, engine, creature("Bat", type_line="Creature — Vampire"), "p1")
    elf = obj_on_battlefield(state, engine, creature("Elf", type_line="Creature — Elf"), "p1")
    enemy_vampire = obj_on_battlefield(state, engine, creature("Foe", type_line="Creature — Vampire"), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, spec, source)
    assert legal == {other_vampire.instance_id}, (legal, elf.instance_id, enemy_vampire.instance_id)


def test_subtype_without_scope_offers_every_other_member():
    spec = _announced("Attended Healer")
    assert spec.exclude_source is True
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Healer", type_line="Creature — Kor Cleric"), "p1")
    mine = obj_on_battlefield(state, engine, creature("Mine", type_line="Creature — Cleric"), "p1")
    theirs = obj_on_battlefield(state, engine, creature("Theirs", type_line="Creature — Cleric"), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, spec, source)
    assert legal == {mine.instance_id, theirs.instance_id}


def test_quality_permanent_target_never_offers_the_source():
    spec = _announced("Rime Tender")
    assert spec.exclude_source is True
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Tender", type_line="Snow Creature — Elf Druid"), "p1")
    snow = obj_on_battlefield(state, engine, creature("Snow Wolf", type_line="Snow Creature — Wolf"), "p2")
    plain = obj_on_battlefield(state, engine, creature("Wolf", type_line="Creature — Wolf"), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, spec, source)
    assert snow.instance_id in legal and source.instance_id not in legal and plain.instance_id not in legal


def test_unmarked_announcement_would_offer_the_source():
    """The marker is the only thing excluding the source: the same announcement without it offers ~ itself."""
    from dataclasses import replace

    spec = replace(_announced("Sanguine Glorifier"), exclude_source=False)
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Glorifier", type_line="Creature — Vampire Cleric"), "p1")
    engine.recompute_continuous_effects()
    assert source.instance_id in _legal_ids(state, spec, source)


def test_attacking_subtype_pool_excludes_the_source_and_non_attackers():
    spec = _announced("Ogre Errant")
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, creature("Ogre", type_line="Creature — Ogre Knight"), "p1")
    ally = obj_on_battlefield(state, engine, creature("Knight A", type_line="Creature — Human Knight"), "p1")
    idle = obj_on_battlefield(state, engine, creature("Knight B", type_line="Creature — Human Knight"), "p1")
    source.attacking = ally.attacking = True
    engine.recompute_continuous_effects()
    assert _legal_ids(state, spec, source) == {ally.instance_id}
    assert idle.instance_id not in _legal_ids(state, spec, source)


def _artifact(name: str):
    card = creature(name, type_line="Artifact")
    card.is_creature = False
    return card


def test_nontoken_artifact_scope_excludes_the_source():
    spec = _announced("The Blackstaff of Waterdeep")
    engine = make_engine([creature()], [creature()])
    state = engine.state
    source = obj_on_battlefield(state, engine, _artifact("Blackstaff"), "p1")
    mine = obj_on_battlefield(state, engine, _artifact("Rock"), "p1")
    theirs = obj_on_battlefield(state, engine, _artifact("Foe Rock"), "p2")
    engine.recompute_continuous_effects()
    legal = _legal_ids(state, spec, source)
    assert legal == {mine.instance_id}, (legal, theirs.instance_id)


@pytest.mark.parametrize("name", ["Tandem Takedown"])
def test_another_after_an_earlier_target_stays_unclaimed(name):
    """"another target" after a target of the same ability also means "different from it" (RULE 115.3): not modelled
    for a verb that carries two requirements of its own (Hidden Strings & co. are `test_par285_sequential_another_target`)."""
    card = CardDatabase(DB_PATH).get_card(name)
    if card is None:
        pytest.skip("card cache not available")
    assert parse_oracle(card).modeled is False
