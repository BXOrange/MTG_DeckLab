from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_jolly_balloon_man() -> list[AbilitySpec]:
    """The Jolly Balloon Man (Legendary Creature — Human Clown, {1}{R}{W})

    "Haste
    {1}, {T}: Create a token that's a copy of another target creature you
    control, except it's a 1/1 red Balloon creature in addition to its
    other colors and types and it has flying and haste. Sacrifice it at
    the beginning of the next end step. Activate only as a sorcery."

    Haste is already parser-claimable. The activated ability reuses
    `CopyPermanentEffect`'s new ``set_power``/``set_toughness``
    (MEC-40, "except it's a 1/1") and ``extra_temp_keywords`` (flying,
    alongside the existing ``haste`` bool) plus its existing
    ``add_subtypes``; the delayed self-sacrifice reuses the already-general
    `CreateDelayedTriggerEffect` (RULE 603.7, step="end") the Marchesa
    V4.2 batch's Kiki-Jiki primitive established. **Documented
    simplification**: the token doesn't actually gain the printed extra
    "red" colour (`Card` has no colour-override field — colours are
    derived from mana cost, which a token has none of to override) —
    cosmetic only, no gameplay-visible effect for a token sacrificed at
    the next end step.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "copy_permanent",
                    {
                        "target_kind": "other_creature_you_control",
                        "set_power": 1, "set_toughness": 1,
                        "add_subtypes": ["Balloon"],
                        "haste": True, "extra_temp_keywords": ["flying"],
                    },
                ),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "end", "scope": "any", "capture": "created_objects",
                        "effects": [{"type": "sacrifice_specific", "params": {}}],
                        "description": "The Jolly Balloon Man: Balloon-Token am "
                                        "nächsten Endsegment opfern",
                    },
                ),
            ],
            cost={"text": "{1}, {T}", "sorcery_speed_only": True},
        ),
    ]


register("The Jolly Balloon Man", _the_jolly_balloon_man)
