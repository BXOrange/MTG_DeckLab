from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _quicksilver_elemental() -> list[AbilitySpec]:
    """{U}: This creature gains all activated abilities of target creature
    until end of turn. (If any of the abilities use that creature's name,
    use this creature's name instead.)
    You may spend blue mana as though it were mana of any color to pay the
    activation costs of this creature's abilities.

    — MEC-23, the one card the Vivi B4 batch (2026-08-10) left open. Two new
    general primitives, both closing this ticket:

    - `effects.GainActivatedAbilitiesOfTargetEffect` (``"gain_target_
      activated_abilities"``) is the resolve-time, single-target sibling of
      MEC-21's standing layer-6 `grant_borrowed_activated_ability`
      (Agatha's Soul Cauldron): it snapshots ``target.activated_abilities``
      once, at resolution, redirecting each via the same `continuous.
      _retarget_effect_source` (RULE 113.7c), onto a turn-scoped
      `GameObject.temp_granted_activated_abilities` field rather than
      re-deriving live off a standing static every recompute — a later
      change to the target's own ability set doesn't retroactively change
      what was copied, matching the card's own ruling.
    - `continuous.any_color_for_activation` (MEC-21's wildcard-activation
      permission) gained ``from_color``/``self_only`` params: Agatha's
      grant is unscoped ("creatures you control") and lets *any* of the
      five colors pay any colored pip, while this card's is self-scoped
      ("this creature's abilities") and only blue mana counts as the
      wildcard (`ManaPool._solve`'s matching single-color branch) — a red
      pip still needs real red or blue mana, never green/white/black.

    The card's own parenthetical ("use this creature's name instead") is
    reminder text about the *retargeting itself* (RULE 113.7c), not a
    separate behaviour — already covered by `_retarget_effect_source`
    redirecting each borrowed effect's ``.source`` to Quicksilver Elemental.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("gain_target_activated_abilities", {})],
            cost={"mana": "{U}"},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "from_color": "U",
                "self_only": True,
            })],
        ),
    ]


register("Quicksilver Elemental", _quicksilver_elemental)
