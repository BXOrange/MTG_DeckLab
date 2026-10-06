from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "deals 7 damage to each creature".
_METEOR_DAMAGE = 7


def _ultimate_magic_meteor() -> list[AbilitySpec]:
    """Ultimate Magic: Meteor deals 7 damage to each creature. If this spell was cast from exile, for each opponent, choose an artifact or land that player controls. Destroy the chosen permanents.
    Foretell {5}{R} (During your turn, you may pay {2} and exile this card from your hand face down. Cast it on a later turn for its foretell cost.)

    — PLAY-ALL (Limit Break). Foretell is the keyword. `damage` with the ``each_creature`` selector, then the new `destroy_artifact_or_land_per_opponent` behind the ``foretold``
    flag (**simplification:** "cast from exile" is "was foretold"; the controller's pick per opponent is the permanent with the greatest mana value).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "foretell", "cost": "{5}{R}"}),
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": _METEOR_DAMAGE, "selector": "each_creature"}),
                EffectSpec("destroy_artifact_or_land_per_opponent", {}, condition={"kind": "flag", "flag": "foretold", "of": "source"}),
            ],
        ),
    ]


register("Ultimate Magic: Meteor", _ultimate_magic_meteor)
