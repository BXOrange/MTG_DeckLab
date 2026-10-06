from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "…this creature deals 5 damage to that player" — the printed amount.
_REFUSAL_DAMAGE = 5


def _star_athlete() -> list[AbilitySpec]:
    """Menace
    Whenever this creature attacks, choose up to one target nonland permanent. Its controller may sacrifice it. If they don't, this creature deals 5 damage to that player.
    Blitz {3}{R} (If you cast this spell for its blitz cost, it gains haste and "When this creature dies, draw a card." Sacrifice it at the beginning of the next end step.)

    — PLAY-ALL (Endless Punishment). Menace and Blitz are keywords. The attack trigger is the parser's `choose_targets` (up to one nonland permanent) followed by an
    `optional` asked of that permanent's controller (``previous_target`` referent) whose body is `sacrifice_target` and whose new ``else_effects`` ("if they don't")
    is 5 damage to that player (``previous_subject_controller``).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("choose_targets", {"kinds": ["nonland_permanent"], "optional": True}),
                EffectSpec("optional", {
                    "player": {"of": "previous_target", "as": "controller"},
                    "prompt": "Das Permanent opfern? (Sonst 5 Schaden)",
                    "effects": [{"type": "sacrifice_target", "params": {}}],
                    "else_effects": [{"type": "damage", "params": {"amount": _REFUSAL_DAMAGE, "recipient_subject": "previous_subject_controller"}}],
                }),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Star Athlete", _star_athlete)
