from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kamiz_obscura_oculus() -> list[AbilitySpec]:
    """Whenever you attack, target attacking creature can't be blocked this turn. It connives. Then choose another attacking creature with lesser power. That creature gains double strike until end of turn. (To have a creature connive, draw a card, then discard a card. If you discarded a nonland card, put a +1/+1 counter on that creature.)

    RULE 701.47: connive (Ledger Shredder's primitive) acts on the clause-1 target via ``previous_subject``. The "choose" is
    a resolution-time pick (RULE 608.2d, not a target): `choose_objects` ``select_only`` over attacking creatures with
    lesser power than that same creature -- its ``reference`` axis, read after the connive counter landed (RULE 608.2h:
    the power it has now) -- hands the pick to the `pump` as its previous subject.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"attacking": True}}),
                EffectSpec("connive", {"previous_subject": True}),
                EffectSpec("choose_objects", {
                    "action": "select_only", "what": "creature", "pool_player_selector": "all",
                    "permanent_filter": {"attacking": True, "power_vs_reference": "less"},
                    "reference": "previous_subject",
                    "then": [{"type": "pump", "params": {
                        "power": 0, "toughness": 0, "keywords": ["double strike"], "previous_subject": True,
                    }}],
                    "prompt": "Wähle eine andere angreifende Kreatur mit geringerer Stärke",
                }),
            ],
            trigger={"event": EventType.ATTACKERS_DECLARED, "condition": {"subject": "you"}},
        ),
    ]


register("Kamiz, Obscura Oculus", _kamiz_obscura_oculus)
