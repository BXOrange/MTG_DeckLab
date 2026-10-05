from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _perplexing_chimera() -> list[AbilitySpec]:
    """Whenever an opponent casts a spell, you may exchange control of
    this creature and that spell. If you do, you may choose new targets
    for the spell. (If the spell becomes a permanent, you control that
    permanent.)

    — RULE 603.3d's reflexive "that spell" (the firing SPELL_CAST event's
    own subject, never a RULE 115 target) combined with RULE 603.5's "you
    may" (`TriggeredAbility.optional` — `_place_triggers`'s reflexive
    branch now pauses on a do/decline choice instead of placing blind when
    both are set, PAR-30's own new primitive). `ExchangeControlSpellEffect
    (reflexive_spell=True)` is the still-on-the-stack sibling of the
    ordinary battlefield `ExchangeControlEffect`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exchange_control_spell", {"reflexive_spell": True})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "not_you"},
                "reflexive": True,
            },
            optional=True,
        ),
    ]


register("Perplexing Chimera", _perplexing_chimera)
