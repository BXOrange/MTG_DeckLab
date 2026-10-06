from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _circle_of_power() -> list[AbilitySpec]:
    """You draw two cards and you lose 2 life. Create a 0/1 black Wizard creature token with "Whenever you cast a noncreature spell, this token deals 1 damage to each opponent."
    Wizards you control get +1/+0 and gain lifelink until end of turn.

    — PLAY-ALL (Scions & Spellcraft). `draw`, `lose_life`, then `create_token` with the token's own printed trigger as
    ``oracle_text`` (parsed when the token binds), then the parser's Wizard-group `pump` (the new token is in the group).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("draw", {"count": 2}),
                EffectSpec("lose_life", {"amount": 2}),
                EffectSpec("create_token", {
                    "count": 1, "power": 0, "toughness": 1, "colors": ["B"], "subtypes": ["Wizard"], "keywords": [],
                    "token_name": "Wizard",
                    "oracle_text": "Whenever you cast a noncreature spell, this token deals 1 damage to each opponent.",
                }),
                EffectSpec("pump", {
                    "power": 1, "toughness": 0, "keywords": ["lifelink"],
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "wizard"}},
                }),
            ],
        ),
    ]


register("Circle of Power", _circle_of_power)
