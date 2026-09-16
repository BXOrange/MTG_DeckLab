from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _the_master_gallifreys_end() -> list[AbilitySpec]:
    """Make Them Pay — Whenever a nontoken artifact creature you control
    dies, you may exile it. If you do, choose an opponent with the most life
    among your opponents. That player faces a villainous choice — They lose
    4 life, or you create a token that's a copy of that card.

    — MEC-52. Hand-authored: the DIES group trigger with a nontoken +
    artifact filter and the "you may exile **it**" reflexive on the dying
    creature (RULE 603.6e last-known info, `ExileEffect` ``target_kind=
    "trigger_subject"``) are past what the parser's villainous grammar
    reaches. Two general engine primitives it drove:
    `FaceVillainousChoiceEffect` ``subject="opponent_with_most_life"`` (RULE
    701.55 pre-selection; ties → first in APNAP order, a documented
    simplification of the printed "your choice") and ``capture_previous`` —
    the just-exiled card (`context.previous_targets`, now also seeded by
    `ExileEffect`'s trigger-subject branch) is baked into the choice so
    option B's `copy_permanent` ``referent="previous"`` still resolves once
    the choice is *answered*, well after this resolution's context is gone.
    ``optional`` on the whole ability is the "you may exile it. If you do,
    …" gate: decline and nothing happens; accept and the exile always
    succeeds (the creature is in the graveyard), so the "if you do" is
    exact rather than simplified.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile", {"target_kind": "trigger_subject"}),
                EffectSpec("face_villainous_choice", {
                    "subject": "opponent_with_most_life",
                    "capture_previous": True,
                    "option_a": [{"type": "lose_life",
                                  "params": {"amount": 4, "target_kind": "player"}}],
                    "option_b": [{"type": "copy_permanent",
                                  "params": {"target_kind": None, "referent": "previous"}}],
                }),
            ],
            trigger={
                "event": EventType.DIES,
                "condition": {
                    "subject": "group", "controller": "you",
                    "type": "artifact", "nontoken": True,
                },
            },
            optional=True,
        ),
    ]


register("The Master, Gallifrey's End", _the_master_gallifreys_end)
