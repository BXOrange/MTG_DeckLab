from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arixmethes_slumbering_isle() -> list[AbilitySpec]:
    """Arixmethes enters tapped with five slumber counters on it.
    As long as Arixmethes has a slumber counter on it, it's a land. (It's not a creature.)
    Whenever you cast a spell, you may remove a slumber counter from Arixmethes.
    {T}: Add {G}{U}.

    — PLAY-ALL (Jump Scare!). Entering tapped with the counters and the mana ability are read off the text; the
    optional cast trigger is the parser's. The land clause is a layer-4 `type_change` that adds Land and removes
    Creature while a slumber counter remains (`source_counters` gate).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("remove_counters", {"self_only": True, "kind": "slumber", "count": 1})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "you"}},
            optional=True,
        ),
        AbilitySpec("static", [EffectSpec("type_change", {
            "affects": "self", "add_types": ["land"], "remove_types": ["creature"],
            "active_if": {"kind": "source_counters", "counter": "slumber", "min": 1},
        })]),
    ]


register("Arixmethes, Slumbering Isle", _arixmethes_slumbering_isle)
