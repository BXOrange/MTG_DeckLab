from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tenth_district_hero() -> list[AbilitySpec]:
    """{1}{W}, Collect evidence 2: This creature becomes a Human Detective
    with base power and toughness 4/4 and gains vigilance.
    {2}{W}, Collect evidence 4: If this creature is a Detective, it becomes
    a legendary creature named Mileva, the Stalwart, it has base power and
    toughness 5/5, and it gains "Other creatures you control have
    indestructible."

    — PAR-30 (Collect Evidence / Forage / Blight residue). Both bodies are
    permanent (RAW: no "until") self-transformations, `grant_until` at
    ``duration="rest_of_game"`` scoped to the source (the Incubator-token
    idiom). Level 1: a layer-4 `type_change` (`set_subtypes=["Human",
    "Detective"]`, base 4/4) + a layer-6 vigilance grant. Level 2 is an
    intervening-if on the source's own now-derived Detective subtype
    (``condition={"source_has_subtype": "Detective"}`` — the binder wraps
    the grant in a `ConditionalEffect`): a layer-4 `type_change`
    (``legendary=True`` → `GameObject._granted_legendary`, base 5/5) + a
    layer-6 grant of an *anthem* static onto the Hero itself
    (`grant_keyword` `affects="other_creatures_you_control"`,
    indestructible).

    **Documented simplification:** the literal rename to "Mileva, the
    Stalwart" isn't modeled — `GameObject.name` has no override mechanism,
    building one (layer 1, copy semantics, `to_dict`) is disproportionate to
    one card, and no card in the pool references the name "Mileva". The
    legend rule still applies (``legendary=True``); the Hero simply keeps
    showing its printed name.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "set_subtypes": ["Human", "Detective"],
                    "power": 4, "toughness": 4,
                }},
                "extra_statics": [{"type": "grant_keyword", "params": {
                    "affects": "self", "keywords": ["vigilance"],
                }}],
            })],
            cost={"text": "{1}{W}, Collect evidence 2",
                  "mana": "{1}{W}", "collect_evidence": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "legendary": True, "power": 5, "toughness": 5,
                }},
                "extra_statics": [{"type": "grant_keyword", "params": {
                    "affects": "other_creatures_you_control",
                    "keywords": ["indestructible"],
                }}],
            }, condition={"source_has_subtype": "Detective"})],
            cost={"text": "{2}{W}, Collect evidence 4",
                  "mana": "{2}{W}", "collect_evidence": 4},
        ),
    ]


register("Tenth District Hero", _tenth_district_hero)
