from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: Ruby Medallion ("Red spells you cast cost {1} less to cast.") was
#: originally hand-authored here (Imodane deck batch, when `cost_reduction`
#: first gained its `spell_color` filter but the parser had no recognizer
#: for the colour-scoped phrasing yet). `parser/oracle/catalogue/
#: static_handlers.py`'s `_SPELL_COST_TAX_COLOR_RE` now claims the whole
#: Medallion cycle generically — confirmed live: Pearl/Sapphire/Jet/Emerald
#: Medallion all already resolve `coverage=MODELED, hand-authored=False`
#: with the identical `cost_reduction` spec shape. Removed as redundant
#: rather than left as a stale duplicate of what the parser now does on its
#: own (2026-08-27 architecture-efficiency pass, A2/A3/B2).


def _runaway_steam_kin() -> list[AbilitySpec]:
    """Whenever you cast a red spell, if this creature has fewer than
    three +1/+1 counters on it, put a +1/+1 counter on this creature.
    Remove three +1/+1 counters from this creature: Add {R}{R}{R}.

    — Imodane deck batch. The trigger's intervening-if is the new
    ``source_counters_below`` (`effect_binder._trigger_condition`) — the
    counter-count sibling of the shipped ``source_state`` (Mana Vault's
    own "if this artifact is tapped"). The mana ability is a plain
    "remove N counters: add mana" activation cost, recognized directly
    from its printed text by `game/costs.py`'s existing
    `_REMOVE_COUNTERS_RE`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_color": "R",
                "source_counters_below": {"kind": "+1/+1", "count": 3},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"colors": ["R", "R", "R"]})],
            cost={"text": "Remove three +1/+1 counters from this creature"},
        ),
    ]


register("Runaway Steam-Kin", _runaway_steam_kin)
