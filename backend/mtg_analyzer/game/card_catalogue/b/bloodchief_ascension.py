from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _bloodchief_ascension() -> list[AbilitySpec]:
    """At the beginning of each end step, if an opponent lost 2 or more life
    this turn, you may put a quest counter on this enchantment. (Damage
    causes loss of life.)
    Whenever a card is put into an opponent's graveyard from anywhere, if
    this enchantment has three or more quest counters on it, you may have
    that player lose 2 life. If you do, you gain 2 life.

    — PLAY-ALL Step 2 (yshtola). Both clauses were "unclaimed" only because
    of their intervening-if / "if you do" tails; every part parses alone
    (probed per piece), so this reproduces those shapes. RULE 603.4: each
    "if" is the trigger's ``active_if`` (checked on trigger and again on
    resolution) — ``opponent_lost_life_this_turn`` and ``source_counters``,
    the vocabulary Adaptive Training Post already uses. "You may have that
    player lose 2 life. If you do, you gain 2" is one optional ability whose
    body is both effects: declining skips both, so "if you do" holds by
    construction. "That player" is the card's owner (``entering``'s
    controller, as the parser spells it for a graveyard arrival).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"count": 1, "kind": "quest"})],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "active_if": {"kind": "opponent_lost_life_this_turn", "min": 2},
            },
            optional=True,
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {"amount": 2, "player": {"of": "entering", "as": "controller"}}),
                EffectSpec("gain_life", {"amount": 2}),
            ],
            trigger={
                "event": EventType.PUT_INTO_GRAVEYARD,
                "condition": {"subject": "group", "controller": "not_you", "other": False, "nontoken": True},
                "active_if": {"kind": "source_counters", "counter": "quest", "min": 3},
            },
            optional=True,
        ),
    ]


register("Bloodchief Ascension", _bloodchief_ascension)
