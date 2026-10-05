from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _baral_chief_of_compliance() -> list[AbilitySpec]:
    """Instant and sorcery spells you cast cost {1} less to cast.
    Whenever a spell or ability you control counters a spell, you may draw a
    card. If you do, discard a card.

    — PLAY-ALL Step 2 (yshtola). The discount is the parser's own claim
    (`cost_reduction` over an instant/sorcery ``spell_type`` list). The trigger
    is the new `SPELL_COUNTERED` event (RULE 701.5a, fired by `RulesEngine.
    counter_spell`; ``player_id`` = the controller of the spell or ability that
    countered it, read off the counterspell's source) with the subject
    ``you``; the body is an `optional` wrapper around draw-then-discard, so
    declining skips both. **Gap:** a spell countered by Ward's own trigger or by
    another rules-driven counter carries no countering controller and does not
    trigger Baral.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_type": ["instant", "sorcery"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("optional", {"effects": [
                {"type": "draw", "params": {"count": 1}},
                {"type": "discard", "params": {"count": 1}},
            ]})],
            trigger={"event": EventType.SPELL_COUNTERED, "condition": {"subject": "you"}},
        ),
    ]


register("Baral, Chief of Compliance", _baral_chief_of_compliance)
