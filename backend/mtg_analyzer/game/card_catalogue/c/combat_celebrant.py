from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _combat_celebrant() -> list[AbilitySpec]:
    """If this creature hasn't been exerted this turn, you may exert it as
    it attacks. When you do, untap all other creatures you control and
    after this phase, there is an additional combat phase.

    — Combat Celebrant. RULE 702.19's Exert is otherwise a plain oracle-text
    parse (`parser/oracle/segmenter.py`'s ``_EXERT_TRIGGER_RE``/
    ``_EXERT_PLAYER_TRIGGER_RE``, `EventType.EXERTED`) — this is the one
    card in the cache printing exert's optional "if ~ hasn't been exerted
    this turn" self-loop guard, hand-authored rather than building a general
    "once per turn" trigger-condition primitive for a single card. Without
    it, this ability's own granted extra combat phase would let the
    creature attack, exert, and grant *another* extra combat phase forever
    — a real infinite loop, not just a flavour simplification. The generic
    parser handler still claims this card's text (it just drops the guard),
    so this entry exists purely to override that with the safe,
    conditioned version; `ConditionalEffect`'s ``not_already_exerted`` key
    reads the firing `EventType.EXERTED` event's own ``already_exerted``
    snapshot (`GameEngine.declare_attackers`), not the object's live
    `exerted_this_turn` flag — that flag is already true by the time this
    trigger resolves.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec(
                    "tap",
                    {"selector": "other_creatures_you_control", "untap": True},
                    condition={"not_already_exerted": True},
                ),
                EffectSpec(
                    "extra_combat_phase", {},
                    condition={"not_already_exerted": True},
                ),
            ],
            trigger={"event": "EXERTED", "condition": {"subject": "self"}},
        ),
    ]


register("Combat Celebrant", _combat_celebrant)
