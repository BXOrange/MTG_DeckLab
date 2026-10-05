from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _scheming_fence() -> list[AbilitySpec]:
    """As this creature enters, you may choose a nonland permanent.
    Activated abilities of the chosen permanent can't be activated.
    This creature has all activated abilities of the chosen permanent
    except for loyalty abilities. You may spend mana as though it were
    mana of any color to activate those abilities.

    — MEC-26's second card, the ``source_mode="chosen_permanent"`` sibling
    of Drana and Linvala's ``"group"`` mode: a single donor picked once
    ("the chosen permanent") rather than a whole group, needing its own
    new selector rather than reusing an existing ``affects`` value —
    `GameObject.chosen_permanent_id` (a new ``chosen_*`` field alongside
    `chosen_type`/`chosen_color`/`chosen_player_id`), a new
    ``"chosen_permanent"`` `continuous.group_selector_objects` case (the
    `attached_permanent` idiom, reading a chosen id instead of an
    attachment), and a new `ChoosePermanentEffect`/``"choose_permanent"``
    `RulesEngine._request_choose_objects` action to make the pick (an
    ordinary interactive ETB trigger, not a pre-entry RULE 601.2b
    replacement like `chosen_type`/`chosen_color` — see `GameObject.
    chosen_permanent_id`'s own docstring for why the "as it enters" wording
    doesn't need a pre-entry choice here). "You may" makes this genuinely
    optional (`ChoosePermanentEffect(optional=True)`, the default),
    unlike `chosen_type`/`chosen_color`'s always-mandatory pick.

    "…except for loyalty abilities" is `grant_borrowed_activated_ability`'s
    new ``exclude_loyalty`` param — a planeswalker-only RULE 606.5c concept
    that makes no sense copied onto a creature, dropped at the source
    rather than granted-and-then-unusable. Candidates are *any* nonland
    permanent on the whole battlefield, not just this creature's
    controller's own (`ChoosePermanentEffect`'s own docstring) — Scheming
    Fence borrows an opponent's activated ability just as readily as its
    own controller's.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_permanent", {"optional": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("activation_prohibition", {"affects": "chosen_permanent"})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self",
                "source_mode": "chosen_permanent",
                "exclude_loyalty": True,
                # "a nonland permanent" — unlike Drana and Linvala's
                # creature-only donor pool, the chosen permanent can be any
                # nonland type (artifact/enchantment/planeswalker/battle),
                # so the default creature-only donor filter must be off.
                "creature_only": False,
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


register("Scheming Fence", _scheming_fence)
