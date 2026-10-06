from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _inscription_of_abundance() -> list[AbilitySpec]:
    """Kicker {2}{G}
    Choose one. If this spell was kicked, choose any number instead.
    • Put two +1/+1 counters on target creature.
    • Target player gains X life, where X is the greatest power among creatures they control.
    • Target creature you control fights target creature you don't control.

    — PLAY-ALL (Death Toll). Kicker is the keyword catalogue's. The modal block's ``override`` (RULE 700.2: the kicked cast chooses one *or more*)
    is the engine's modal-override mechanism. The life gain measures the greatest power among *the target player's* creatures
    (a ``count_selector`` amount counted ``of`` the target, structured ``aggregate: max``).
    """
    return [
        AbilitySpec(
            "spell_effect", [],
            modes={
                "choose": 1,
                "override": {"condition": {"kind": "kicked"}, "choose": 1, "at_least": True},
                "options": [
                    [EffectSpec("add_counters", {"count": 2, "kind": "+1/+1", "target_kind": "creature"})],
                    [EffectSpec("gain_life", {"target_kind": "player", "amount": {
                        "kind": "count_selector", "of": "target",
                        "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"},
                                     "aggregate": "max", "value": "power"},
                    }})],
                    [EffectSpec("fight", {"fighter_kind": "creature_you_control", "other_kind": "creature_you_dont_control"})],
                ],
                "descriptions": [
                    "Lege zwei +1/+1-Marken auf eine Zielkreatur.",
                    "Ein Zielspieler erhält X Leben, X = größte Stärke unter seinen Kreaturen.",
                    "Eine Kreatur, die du kontrollierst, kämpft gegen eine Zielkreatur, die du nicht kontrollierst.",
                ],
            },
        ),
    ]


register("Inscription of Abundance", _inscription_of_abundance)
