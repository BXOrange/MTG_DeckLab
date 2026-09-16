from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _honorable_passage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to any
    target this turn, prevent that damage. If damage from a red source is
    prevented this way, Honorable Passage deals that much damage to the
    source's controller.

    — ``target_kind="any"`` (already shipped, Circle of Despair's own
    shape). ``rider={"if_source_color": "R", ...}`` (MEC-30) — same
    source-colour-gated rider as Shadowbane, different kind.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller", "if_source_color": "R"},
            })],
        ),
    ]


register("Honorable Passage", _honorable_passage)
