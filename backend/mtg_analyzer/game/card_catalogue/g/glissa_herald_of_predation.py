from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _glissa_herald_of_predation() -> list[AbilitySpec]:
    """At the beginning of combat on your turn, choose one —
    • Incubate 2 twice. (To incubate 2, create an Incubator token with two
      +1/+1 counters on it and "{2}: Transform this token." It transforms
      into a 0/0 Phyrexian artifact creature.)
    • Transform all Incubator tokens you control.
    • Phyrexians you control gain first strike and deathtouch until end of
      turn.

    — Eliferate deck batch. Incubate (RULE 701.51-adjacent) is modeled as
    a genuine two-state token, the same way morph/manifest's face-down
    permanents are: "Incubate 2 twice" creates two power/toughness-less
    "Incubator" tokens (`services.token_database.synthesize_token_card`
    makes a bare token with no P/T a plain noncreature "Token Artifact"
    on its own) each carrying 2 +1/+1 counters (`create_token`'s new
    `extra_counters` param), and the standalone `Incubator` catalogue
    entry below binds onto every one of them (`bind_from_catalogue` reads
    a token's abilities off its own name, "exactly like a real
    permanent") its own "{2}: Transform this token" — a permanent
    (RAW: no "until") `type_change` animation into a 0/0 Phyrexian
    artifact creature, so its counters do the rest. The second mode,
    "transform all Incubator tokens you control", reuses that exact same
    animation en masse via the new `transform_named_tokens` primitive
    rather than a bespoke one-off. The third mode is a plain `pump` with a
    subtype-scoped `selector`, the same `creatures_you_control_of_type_<x>`
    vocabulary `Elvish Warmaster`'s pump ability already uses.
    """
    return [
        AbilitySpec(
            "triggered",
            [],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"},
                "phase_relation": "you",
            },
            modes={
                "options": [
                    [EffectSpec("create_token", {
                        "count": 2, "token_name": "Incubator",
                        "extra_counters": {"kind": "+1/+1", "count": 2},
                    })],
                    [EffectSpec("transform_named_tokens", {
                        "token_name": "Incubator", "add_types": ["creature"],
                        "add_subtypes": ["Phyrexian"], "power": 0, "toughness": 0,
                    })],
                    [EffectSpec("pump", {
                        "selector": "creatures_you_control_of_type_phyrexian",
                        "keywords": ["first_strike", "deathtouch"],
                    })],
                ],
                "descriptions": [
                    "Inkubiere 2 zweimal.",
                    "Transformiere alle Inkubator-Spielsteine unter deiner Kontrolle.",
                    "Phyrexianer unter deiner Kontrolle erhalten Erstschlag und "
                    "Todesberührung bis zum Ende des Zuges.",
                ],
            },
        ),
    ]


register("Glissa, Herald of Predation", _glissa_herald_of_predation)
