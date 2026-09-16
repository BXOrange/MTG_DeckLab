from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _teferi_time_raveler() -> list[AbilitySpec]:
    """Each opponent can cast spells only any time they could cast a
    sorcery.
    +1: Until your next turn, you may cast sorcery spells as though they
    had flash.
    −3: Return up to one target artifact, creature, or enchantment to
    its owner's hand. Draw a card.

    — MEC-42. The static needed a genuinely new restriction — new
    `sorcery_speed_only` (`continuous.forced_sorcery_speed_only`,
    consulted directly in `GameEngine.can_cast`'s own timing computation,
    forcing RULE 601.3b sorcery-speed timing for a restricted opponent
    even over an instant/Flash spell) — the mirror image of `flash_
    permission`'s existing "permission static outside the layer engine"
    treatment. The +1 reuses that same `flash_permission` static with a
    widened ``type_filter`` (``"sorcery"``, `continuous.has_standing_
    flash_permission`'s own word-list check) wrapped in `GrantUntilEffect`
    at the ``"your_next_turn"`` duration RULE 611.2b already supports.
    The −3 is fully `MODELED` by the oracle-text parser already
    (`ReturnToHandEffect` + `DrawCardEffect`); reused as-is via the
    `hand-author-card` skill's own `reuse` command rather than re-derived.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("sorcery_speed_only", {})],
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "static": {"type": "flash_permission", "params": {"type_filter": ["sorcery"]}},
                "duration": "your_next_turn",
                "target_kind": None,
            })],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_to_hand", {"target_kind": "permanent", "optional": True}), EffectSpec("draw", {"count": 1})],
            cost={"loyalty": -3},
        ),
    ]


register("Teferi, Time Raveler", _teferi_time_raveler)
