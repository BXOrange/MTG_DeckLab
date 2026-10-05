from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _jeweled_amulet() -> list[AbilitySpec]:
    """{1}, {T}: Put a charge counter on this artifact. Note the type of
    mana spent to pay this activation cost. Activate only if there are no
    charge counters on this artifact.
    {T}, Remove a charge counter from this artifact: Add one mana of this
    artifact's last noted type.

    — MEC-43 (the ticket's one deliberately-deferred card, closed in a
    follow-up pass rather than a third deferral). "Note the type of mana
    spent" needed a genuinely new primitive: `ManaPool.pay` now stamps
    `last_payment_types` (which type(s) it actually drained — this card's
    own {1} cost has no fixed pip of its own to read instead), and
    `ActivationCost.note_spent_color` copies that onto `GameObject.
    noted_mana_color` right after payment (`GameEngine._pay_ability_cost`).
    This engine has no interactive "which color pays a generic pip" choice
    (`ManaPool._spend_generic`'s own colorless-first order decides it
    deterministically), so what gets noted isn't always a genuine player
    pick — an accepted simplification, the same tier every other "spend
    from the pool" caller already gets. The second ability reads it back
    via `AddManaEffect`'s new `color_from_source_noted_color`, the exact
    sibling of the existing `color_from_source_chosen_color` (Utopia
    Sprawl-shaped RULE 601.2b colour choices already use it the same way).
    "Activate only if there are no charge counters" is `ActivationCost.
    activation_condition` reusing the existing `source_counters` kind.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"kind": "charge", "count": 1}),
            ],
            cost={
                "text": "{1}, {T}",
                "note_spent_color": True,
                "activation_condition": {"kind": "source_counters", "counter": "charge", "max": 0},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"color_from_source_noted_color": True})],
            cost={"taps_self": True, "remove_counters": ["charge", 1]},
        ),
    ]


register("Jeweled Amulet", _jeweled_amulet)
