from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _natures_claim() -> list[AbilitySpec]:
    """Destroy target artifact or enchantment. Its controller gains 4 life.

    — Nature's Claim. Shipped as a welded `destroy_gain_life_to_controller`
    effect, for the same reason Swords to Plowshares did: the life goes to
    the *target's own* controller, and an operand could not name a referent.
    ENG-37 retired both — the recipient is now
    ``{"of": "previous_target", "as": "controller"}`` on an ordinary
    `gain_life`, with no `bind` needed here because 4 is printed rather than
    measured. ``target_kind="permanent"`` (broader than "artifact or
    enchantment") mirrors Feed the Swarm's composition (`destroy` + `bind`, ENG-37)'s own
    documented simplification.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("destroy", {"target_kind": "permanent"}),
                EffectSpec("gain_life", {
                    "amount": 4,
                    "player": {"of": "previous_target", "as": "controller"},
                }),
            ],
        )
    ]


register("Nature's Claim", _natures_claim)
