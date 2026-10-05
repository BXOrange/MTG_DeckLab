from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _treasure_vault() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {X}{X}, {T}, Sacrifice this land: Create X Treasure tokens.

    — MEC-12 (cEDH Kinnan). The plain "{T}: Add {C}." mana ability needs no
    entry at all here — `game/mana_abilities.py`'s `mana_abilities_for`
    reads it straight off `Card.oracle_text` via its own regex, completely
    independent of catalogue registration (unlike `parse_oracle`'s
    AbilitySpec pipeline, which *does* turn off once a name is registered).
    Only the X-cost second ability needs hand-authoring. ``"count": "x"``
    on `create_token` rides the same ``"x"`` sentinel the ``{X}{X}`` cost
    itself does (`RulesEngine._substitute_x` walks a plain effect ``count``
    attribute).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {"count": "x", "token_name": "Treasure"})],
            cost={"text": "{X}{X}", "tap": True, "sacrifice": "self"},
        ),
    ]


register("Treasure Vault", _treasure_vault)
