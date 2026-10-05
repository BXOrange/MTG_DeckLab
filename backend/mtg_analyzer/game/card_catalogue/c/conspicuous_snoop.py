from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _conspicuous_snoop() -> list[AbilitySpec]:
    """Play with the top card of your library revealed.
    You may cast Goblin spells from the top of your library.
    As long as the top card of your library is a Goblin card, this
    creature has all activated abilities of that card.

    — MEC-43. The first two lines are `top_library.py`'s existing standing
    permission (`TopLibraryPermissionEffect`, ``subtypes=["goblin"]`` —
    "play with revealed" is this permission's own always-on visibility
    side effect, per its docstring, so it needs no separate clause here);
    the third is `grant_borrowed_activated_ability`'s new ``source_mode=
    "top_of_library"`` — a scratch, off-zone `GameObject` bound purely to
    read the top card's own activated abilities (a library card is never
    otherwise boarded), narrowed by the new ``donor_subtype`` filter.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("top_library_permission", {
                "look": True, "cast_spells": True, "subtypes": ["goblin"],
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("grant_borrowed_activated_ability", {
                "affects": "self", "source_mode": "top_of_library",
                "donor_subtype": "goblin", "creature_only": False,
            })],
        ),
    ]


register("Conspicuous Snoop", _conspicuous_snoop)
