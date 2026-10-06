from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: "Exile Suspended Sentence with three time counters on it" — the printed count.
_TIME_COUNTERS = 3


def _suspended_sentence() -> list[AbilitySpec]:
    """Destroy target creature an opponent controls. That player loses 3 life. Exile Suspended Sentence with three time counters on it.
    Suspend 3—{1}{B} (Rather than cast this card from your hand, you may pay {1}{B} and exile it with three time counters on it. At the beginning of your upkeep, remove a time counter. When the last is removed, you may cast it without paying its mana cost.)

    — PLAY-ALL (Endless Punishment). Suspend is the keyword (engine-backed: `GameEngine.suspend` + the upkeep trigger scanning exile for time counters). The spell is the
    parser's destroy + life loss, then the new `exile_self_with_counters`: the resolving spell exiles itself with three time counters instead of going to the graveyard
    (`_resolve_spell`'s "an effect already moved it" branch), so it comes back through its own Suspend.
    """
    return [
        AbilitySpec("spell_effect", [
            EffectSpec("destroy", {"target_kind": "creature_you_dont_control"}),
            EffectSpec("lose_life", {"amount": 3, "player": {"of": "previous_target", "as": "controller"}}),
            EffectSpec("exile_self_with_counters", {"kind": "time", "count": _TIME_COUNTERS}),
        ]),
    ]


register("Suspended Sentence", _suspended_sentence)
