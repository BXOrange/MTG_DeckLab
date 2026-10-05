from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _umezawas_jitte() -> list[AbilitySpec]:
    """Whenever equipped creature deals combat damage, put two charge
    counters on Umezawa's Jitte.
    Remove a charge counter from Umezawa's Jitte: Choose one —
    • Equipped creature gets +2/+2 until end of turn.
    • Target creature gets -1/-1 until end of turn.
    • You gain 2 life.
    Equip {2}

    — MEC-43 round 4A. The trigger is the same "attached_permanent" DAMAGE
    subject every other Sword uses, minus the "is_player" filter (this one
    fires on **any** combat damage, not just to a player); "put two charge
    counters on ~" is a plain untargeted `AddCountersEffect` (no
    ``target_kind``, so it acts on its own source). The activated ability
    is this round's real primitive gap: RULE 700.2 modal choice
    (``AbilitySpec.modes``) had never been wired for an *activated*
    ability before, only spell/triggered ones — `AbilitySpec._validate_
    modes` now permits ``"activated"``, `effect_binder.bind_ability` builds
    `ActivatedAbility.modes` off the same `_build_mode_entries` helper a
    modal spell/triggered ability already shares, and `GameEngine.
    activate_ability` gained a ``mode`` param (`_resolve_activation_mode`)
    that picks the chosen mode's own effects *before* targets are
    gathered — mirroring a modal spell's own mode-before-target ordering,
    and `_place_trigger`'s existing `effects_override` idiom for a modal
    trigger's chosen mode. `legal_actions`'s activate-ability offer
    (`_activate_actions_for`) now emits one action per mode the same way
    `_modal_cast_actions` already does for spells. Deliberately scoped to
    the plain "choose one" shape only — no printed activated ability needs
    "choose N"/"or both" yet.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"amount": 2, "kind": "charge"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True},
            },
        ),
        AbilitySpec(
            "activated",
            [],
            cost={"remove_counters": ("charge", 1)},
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("pump", {
                        "power": 2, "toughness": 2, "target_kind": "attached_permanent",
                    })],
                    [EffectSpec("pump", {
                        "power": -1, "toughness": -1, "target_kind": "creature",
                    })],
                    [EffectSpec("gain_life", {"amount": 2})],
                ],
                "descriptions": [
                    "Equipped creature gets +2/+2 until end of turn.",
                    "Target creature gets -1/-1 until end of turn.",
                    "You gain 2 life.",
                ],
            },
        ),
    ]


register("Umezawa's Jitte", _umezawas_jitte)
