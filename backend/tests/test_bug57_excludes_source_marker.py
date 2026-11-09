"""BUG-57, milestone 1: the parser marks a target phrase that says "another"/"other" with `excludes_source`.

RULE 109.5 / 115.1: "another target creature" cannot be the ability's own source, while a plain "target creature"
can. `resolve_target_kind` reads both down to the same kind, so the marker is the only record of the difference. The
engine does not read it yet; these tests pin what the parser records, on the real oracle text of the cards."""

from __future__ import annotations

import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.clause_primitives import EXCLUDES_SOURCE_PARAM
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _specs(name, oracle, types="Creature — Test"):
    card = Card(id=name, name=name, type_line=types, converted_mana_cost=0, oracle_text=oracle,
                is_creature="Creature" in types, power=1 if "Creature" in types else None,
                toughness=1 if "Creature" in types else None, keywords=[])
    result = parse_oracle(card)
    assert result.modeled, name
    return result.specs


def _marked(node) -> bool:
    """Whether any effect in ``node`` (spec, dict or list, nested) carries the marker."""
    if isinstance(node, EffectSpec):
        return EXCLUDES_SOURCE_PARAM in node.params or _marked(node.params)
    if isinstance(node, dict):
        return node.get(EXCLUDES_SOURCE_PARAM) is True or any(_marked(v) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_marked(v) for v in node)
    return False


def _ability_marked(spec) -> bool:
    return _marked(list(spec.effects)) or _marked(spec.modes)


@pytest.mark.parametrize("name, oracle, types", [
    ("Faceless Devourer", "Shadow\nWhen Faceless Devourer enters, exile another target creature with shadow.", "Creature — Nightmare"),
    ("Tideforce Elemental", "{U}, {T}: You may tap or untap another target creature.", "Creature — Elemental"),
    ("Bespoke Bo", "When this Equipment enters, return up to one other target nonland permanent to its owner's hand.", "Artifact — Equipment"),
    ("Phyrexian Vindicator", "Flying\nIf damage would be dealt to Phyrexian Vindicator, prevent that damage. When damage is prevented this way, Phyrexian Vindicator deals that much damage to any other target.", "Creature — Phyrexian Dragon"),
    ("Aegis Angel", "Flying\nWhen this creature enters, another target permanent gains indestructible for as long as you control this creature.", "Creature — Angel"),
    ("Angel of Condemnation", "Vigilance\n{2}{W}, {T}: Exile another target creature. Return that card to the battlefield under its owner's control at the beginning of the next end step.", "Creature — Angel"),
])
def test_another_target_is_marked(name, oracle, types):
    # RULE 109.5: the printed "another"/"other" survives parsing as the marker (the kind alone loses it).
    assert any(_ability_marked(s) for s in _specs(name, oracle, types)), name


@pytest.mark.parametrize("name, oracle", [
    ("Test Tapper", "When this creature enters, tap target creature."),
    ("Test Pinger", "{T}: This creature deals 1 damage to any target."),
    # RULE 115.1: a plain target phrase next to an unrelated "another" (a trigger condition) is not "another target".
    ("Test Pinger Two", "Whenever another creature you control dies, this creature deals 1 damage to any target."),
    # "other than that creature" names the trigger's subject (excluding_trigger_subject), not the source.
    ("Test Counter", "Whenever a creature you control becomes the target of a spell or ability an opponent controls, put a +1/+1 counter on target creature you control other than that creature."),
])
def test_plain_target_is_not_marked(name, oracle):
    assert not any(_ability_marked(s) for s in _specs(name, oracle)), name


def test_only_the_another_requirements_of_an_escalating_clause_are_marked():
    # RULE 109.5: "...on target creature, 2 ... on another target creature, and 3 ... on a third target creature":
    # the first requirement is plain, the other two are "another".
    specs = match_clause("put a -1/-1 counter on target creature, 2 -1/-1 counters on another target creature, "
                         "and 3 -1/-1 counters on a third target creature")
    marks = [EXCLUDES_SOURCE_PARAM in e.params for e in specs]
    assert marks == [False, True, True]
