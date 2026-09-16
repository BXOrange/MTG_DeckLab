from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ===========================================================================
# Prismari cast-triggered copy effects
# ===========================================================================


def _muddle_the_ever_changing() -> list[AbilitySpec]:
    """Whenever you cast an instant or sorcery spell, Muddle becomes a copy
    of up to one target nonlegendary creature you control until end of turn,
    except it has myriad.

    Documented simplifications: "up to one target" is modeled as a required
    target; the "except it has myriad" grant is not modeled."""
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("become_copy_until_eot", {"target_kind": "creature_you_control"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Muddle, the Ever-Changing", _muddle_the_ever_changing)
