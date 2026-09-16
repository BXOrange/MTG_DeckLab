from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _soul_partition() -> list[AbilitySpec]:
    """Exile target nonland permanent. For as long as that card remains
    exiled, its owner may play it. A spell cast by an opponent this way
    costs {2} more to cast.

    — MEC-12 (cEDH staples 2). `ExileEffect`'s new `grant_owner_play_
    permission`/`owner_play_permission_tax` params: the standing sibling
    of Lukka, Coppercoat Outcast's own board-gated `GameState.exile_cast_
    condition` grant (an empty condition dict always holds, per
    `static_conditions.condition_holds`'s own "no condition = always
    true") — keyed to the exiled card's *owner* rather than this spell's
    caster — plus a per-instance cost tax stamped directly onto that one
    card at exile time (`continuous.self_cost_reduction_for`'s new
    `caster_id` param, `except_same_controller_as` naming the exiler so
    only they're ever exempt from their own tax). Surfaced and fixed a
    real latent bug along the way: `legal_actions`'s own exile-zone offer
    list never checked `_has_conditional_exile_permission` at all — Lukka's
    permission worked when driven directly through `can_cast`/`cast_spell`
    in a test, but nothing had ever actually offered it as a real action,
    the same "parse-only masks real bugs" shape this project's own testing
    lesson warns about.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("exile", {
                "target_kind": "nonland_permanent",
                "grant_owner_play_permission": True,
                "owner_play_permission_tax": 2,
            })],
        ),
    ]


register("Soul Partition", _soul_partition)
