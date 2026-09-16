from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sanctifier_en_vec() -> list[AbilitySpec]:
    """Protection from black and from red
    When this creature enters, exile all cards that are black or red from
    all graveyards.
    If a black or red permanent, spell, or card not on the battlefield
    would be put into a graveyard, exile it instead.

    — MEC-43 round 2. Protection comes from the RULE 702 keyword catalogue
    (unaffected by hand-authoring — read straight off the printed card
    regardless of registration). The ETB sweep reuses `exile_all_
    graveyards`' new `colors` filter (round 1's Rest in Peace made the
    selector itself; this just narrows it). The replacement reuses round
    1's `graveyard_redirect` static with its new `colors` param instead of
    `scope` — Sanctifier's clause names no owner at all, so it always
    passes ``scope="any"`` alongside the colour filter that does the real
    work.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_all_graveyards", {"colors": ["B", "R"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("graveyard_redirect", {"scope": "any", "colors": ["B", "R"]})],
        ),
    ]


register("Sanctifier en-Vec", _sanctifier_en_vec)
