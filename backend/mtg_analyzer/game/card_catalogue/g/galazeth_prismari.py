from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _galazeth_prismari() -> list[AbilitySpec]:
    """Flying
    When Galazeth Prismari enters, create a Treasure token.
    Artifacts you control have "{T}: Add one mana of any color. Spend this
    mana only to cast an instant or sorcery spell."

    Documented simplification: the granted mana ability's "spend only to
    cast an instant or sorcery spell" restriction is not modeled — the mana
    is unrestricted."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_mana_ability", {
                "affects": "artifacts_you_control",
                "mana": [{"W": 1}, {"U": 1}, {"B": 1}, {"R": 1}, {"G": 1}],
            })],
        ),
    ]


register("Galazeth Prismari", _galazeth_prismari)
