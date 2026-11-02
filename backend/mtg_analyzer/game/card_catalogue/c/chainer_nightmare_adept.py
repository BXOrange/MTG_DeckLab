from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chainer_nightmare_adept() -> list[AbilitySpec]:
    """Discard a card: You may cast a creature spell from your graveyard this turn. Activate only once each turn.
    Whenever a nontoken creature you control enters, if you didn't cast it from your hand, it gains haste until your next turn.

    The activated ability is Backdraft Hellkite/Kethis's turn-scoped graveyard cast permission
    (`grant_graveyard_cast_permission_this_turn`, RULE 601.2) narrowed to creature cards, behind a "Discard a
    card" cost and the activated-ability once-per-turn marker. The trigger is a group ETB head over nontoken
    creatures you control, gated by the new ``not_cast_from_zone: "hand"`` (`binding/entry_origin.py`, RULE
    601.2a) intervening-if; the haste is Nissa, Vital Force's ``grant_until`` / ``your_next_turn`` duration
    (RULE 611.2b) applied to the entering creature through `trigger_subject_referent`.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("grant_graveyard_cast_permission_this_turn", {
                    "spell_criteria": {"type": "Creature"}, "instant_sorcery_only": False,
                }),
                EffectSpec("once_per_turn_marker", {"count": 1}),
            ],
            cost={"text": "Discard a card"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("trigger_subject_referent", {"effects": [{"type": "grant_until", "params": {
                "static": {"type": "grant_keyword", "params": {"keywords": ["haste"]}},
                "duration": "your_next_turn", "previous_subject": True,
            }}]})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "group", "controller": "you", "nontoken": True,
                              "filter": {"card_type": "creature"}},
                "not_cast_from_zone": "hand",
            },
        ),
    ]


register("Chainer, Nightmare Adept", _chainer_nightmare_adept)
