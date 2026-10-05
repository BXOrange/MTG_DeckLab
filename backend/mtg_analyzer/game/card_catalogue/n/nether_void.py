from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nether_void() -> list[AbilitySpec]:
    """Whenever a player casts a spell, counter it unless that player pays
    {3}.

    — Nether Void. A plain "group" trigger subject with no ``"controller"``
    filter already matches *any* player's `SPELL_CAST` (the vocabulary's
    unrestricted default); `CounterSpellEffect`'s own ``target_spec``
    (``kind="spell"``) is gathered interactively same as any other
    triggered ability's target — since the triggering spell is pushed onto
    `state.stack` before `SPELL_CAST` fires, it's already a legal option by
    the time the ability asks.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("counter", {"unless_pays": "{3}"})],
            trigger={"event": EventType.SPELL_CAST, "condition": {"subject": "group"}},
        )
    ]


register("Nether Void", _nether_void)
