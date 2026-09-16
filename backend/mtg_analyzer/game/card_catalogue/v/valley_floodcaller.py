from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _valley_floodcaller() -> list[AbilitySpec]:
    """Flash
    You may cast noncreature spells as though they had flash.
    Whenever you cast a noncreature spell, Birds, Frogs, Otters, and Rats
    you control get +1/+1 until end of turn. Untap them.

    — MEC-41. Flash and the standing flash-permission clause are already
    parser-MODELED (copied verbatim per the hand-author-card skill's own
    guidance — `flash_permission`'s ``noncreature_only``, already built
    with this very card in mind, see its own registry comment); the third
    clause needed `PumpEffect`/`TapEffect`'s own new ``subtypes`` param —
    a ``selector`` group narrowed by a subtype list, the sibling
    `AddCountersEffect.subtypes` already had, that neither previously did.
    **Documented note**: the pump and untap clauses each carry their own
    copy of the four-subtype list rather than a cross-clause pronoun,
    since `GameContext.previous_selector` (MEC-28) only carries the bare
    selector *name*, not any subtype narrowing layered on top of it.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flash"}),
        AbilitySpec(
            "static",
            [EffectSpec("flash_permission", {"noncreature_only": True})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("pump", {
                    "power": 1, "toughness": 1, "selector": "creatures_you_control",
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
                EffectSpec("tap", {
                    "selector": "creatures_you_control", "untap": True,
                    "subtypes": ["bird", "frog", "otter", "rat"],
                }),
            ],
            trigger={
                "event": "SPELL_CAST", "condition": {"subject": "you"},
                "spell_exclude_card_types": ["creature"],
            },
        ),
    ]


register("Valley Floodcaller", _valley_floodcaller)
