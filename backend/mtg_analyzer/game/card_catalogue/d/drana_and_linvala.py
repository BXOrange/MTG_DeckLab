from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _drana_and_linvala() -> list[AbilitySpec]:
    """Flying, vigilance
    Activated abilities of creatures your opponents control can't be
    activated.
    Drana and Linvala has all activated abilities of all creatures your
    opponents control. You may spend mana as though it were mana of any
    color to activate those abilities.

    — MEC-26, the first of the two cards a second MEC-23 deferral had left
    open (found while sizing MEC-21, 2026-07-22; deferred again by MEC-23,
    2026-08-11 — this batch is the mandatory "hand-author or promote" close
    per the project's no-half-implementations rule). Needed a genuinely
    **standing, group-scoped** sibling of MEC-21's `grant_borrowed_
    activated_ability` (Agatha's Soul Cauldron) rather than MEC-23's own
    resolve-time single-target snapshot: the donor set here is "all
    creatures your opponents control", read live off the battlefield every
    recompute, not a fixed exiled-card or once-copied list. One new
    ``source_mode="group"`` on the existing static (`continuous.
    _apply_borrowed_activated_abilities`) covers it — reusing the ordinary
    ``affects`` selector vocabulary (`"creatures_opponents_control"`,
    already built for Manglehorn/goad-adjacent cards) as the *donor* scope
    rather than the *grantee* scope `affects` already served.

    The other two printed lines turned out to need no new machinery at
    all: "Activated abilities of creatures your opponents control can't be
    activated" is `activation_prohibition`'s own existing, already-general
    ``affects`` selector (Collector Ouphe-shaped, just never scoped to
    ``"creatures_opponents_control"`` by a real card before); and "You may
    spend mana as though it were mana of any color to activate **those**
    abilities" is MEC-23's `grant_any_color_for_activation`'s own
    ``self_only=True`` — the original MEC-26 filing worried ``self_only``
    would over-scope to "any ability Drana and Linvala has", not just the
    borrowed set, but Drana and Linvala prints no *other* activated
    ability of her own, so in practice the two sets are identical and no
    third param was needed. (Scheming Fence, below, is the same story.)
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "creatures_opponents_control"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "group",
                "source_affects": "creatures_opponents_control",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_any_color_for_activation", {
                "creature_abilities_only": True,
                "self_only": True,
            })],
        ),
    ]


register("Drana and Linvala", _drana_and_linvala)
