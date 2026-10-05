from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tectonic_giant() -> list[AbilitySpec]:
    """Whenever this creature attacks or becomes the target of a spell an
    opponent controls, choose one —
    • This creature deals 3 damage to each opponent.
    • Exile the top two cards of your library. Choose one of them. Until
    the end of your next turn, you may play that card.

    — Tectonic Giant, MEC-19's second named card. Same "one AbilitySpec per
    compound-triggered event" idiom as Goldspan Dragon's own entry (this
    trigger only needs the ``caster_relation: "opponent"`` filter Goldspan
    Dragon's plain "of a spell" doesn't).

    Documented simplification on the second mode: "exile the top two
    cards, **choose one of them**, until the end of your next turn you may
    play *that* card" is a distinct RULE 601.3b shape from the already-
    shipped `ImpulsiveDrawEffect` ("exile N, *all* of them stay playable")
    — a filtered choice-and-route dig, not a plain reveal-and-window one.
    No shipped primitive covers "exile N, pick 1 to keep playable, discard
    the rest" (7 real cache cards total, `parser_probe.py cards` — its own
    small, real gap, orthogonal to MEC-19's `BECOMES_TARGET` work and not
    built here). Modeled instead with the closest existing effect,
    `impulsive_draw` at ``count=2``: strictly more generous than print
    (both exiled cards stay playable, not just one chosen), same
    "until the end of your next turn" window (``same_turn_only=False``).
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("damage", {"amount": 3, "selector": "each_opponent"})],
                    [EffectSpec("impulsive_draw", {"count": 2, "same_turn_only": False})],
                ],
                "descriptions": [
                    "~ fügt jedem Gegner 3 Schadenspunkte zu.",
                    "Exiliere die obersten zwei Karten deiner Bibliothek. Du "
                    "darfst sie bis zum Ende deines nächsten Zuges spielen.",
                ],
            },
            trigger={
                "event": EventType.BECOMES_TARGET,
                "condition": {"subject": "self"},
                "filter": {"item_kind": "spell"},
                "caster_relation": "opponent",
            },
        ),
    ]


register("Tectonic Giant", _tectonic_giant)
