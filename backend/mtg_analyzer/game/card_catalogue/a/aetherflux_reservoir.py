from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-43 "near-free reuses" batch (2026-08-21) — cEDH staples 2's remaining
# gaps that only needed an existing primitive recoloured/param-widened, per
# BACKLOG.md's own clustering. See Done_Backend.md's "MEC-43" entry for the
# primitives each of these closed along the way (sacrificed_cost_power,
# graveyard_redirect, cast_prohibition's color/creature_only/zones knobs,
# dig_until's graveyard rest destination, grant_borrowed_activated_ability's
# top_of_library source mode, the each_player_pay_or scope/effect_targets
# widening, the Uba Mask draw replacement, and several small trigger-
# condition/target-kind additions).
# ---------------------------------------------------------------------------


def _aetherflux_reservoir() -> list[AbilitySpec]:
    """Whenever you cast a spell, you gain 1 life for each spell you've
    cast this turn.
    Pay 50 life: This artifact deals 50 damage to any target.

    — MEC-43. The life-gain trigger reuses `continuous.count_selector`'s
    existing ``"spells_cast_this_turn"`` entry — incremented synchronously
    at cast time, so it already includes the just-cast spell by the time
    this ability resolves off the stack; the activated ability is a plain
    RULE 118.4 ``{"pay_life": 50}`` cost into an ordinary any-target damage
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("gain_life", {"count_selector": "spells_cast_this_turn"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 50, "target_kind": "any"})],
            cost={"pay_life": 50},
        ),
    ]


register("Aetherflux Reservoir", _aetherflux_reservoir)
