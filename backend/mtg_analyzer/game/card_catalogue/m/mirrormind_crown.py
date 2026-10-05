from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirrormind_crown() -> list[AbilitySpec]:
    """As long as this Equipment is attached to a creature, the first time
    you would create one or more tokens each turn, you may instead create
    that many tokens that are copies of equipped creature.
    Equip {2}

    — Eliferate deck batch. Equip is a RULE 702 keyword, auto-bound.
    **Documented simplification**: modeled as an ordinary once-per-turn
    trigger that *additionally* creates the copies (`CopyPermanentEffect`'s
    new `attached_permanent` self-mode + `count_from_trigger_event`)
    rather than a true `CREATE_TOKENS` replacement that *redirects*
    (blocks the original tokens and substitutes copies instead) — that
    event's own replacement hook only lets a `ReplacementEffect` rescale
    the *amount*, never swap in a different token identity, and building
    that redirection is real engine plumbing disproportionate to one
    Equipment. The practical difference only matters when a player would
    have preferred *not* getting the original tokens too, which is rare
    for an "instead" upgrade like this one.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "count_from_trigger_event": "amount",
            })],
            trigger={
                "event": EventType.CREATE_TOKENS,
                "condition": {"subject": "group", "controller": "you"},
                "limit": True,
                "requires_attached": True,
            },
        ),
    ]


register("Mirrormind Crown", _mirrormind_crown)
