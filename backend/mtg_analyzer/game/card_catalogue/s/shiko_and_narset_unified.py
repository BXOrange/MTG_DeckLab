from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _shiko_and_narset_unified() -> list[AbilitySpec]:
    """Flying, vigilance
    Whenever you cast your second spell each turn, copy that spell if it
    targets a permanent or player, and you may choose new targets for the
    copy. If you don't copy a spell this way, draw a card.

    — Shiko and Narset, Unified. Flying and vigilance come from the RULE 702
    keyword catalogue. One trigger event with a binary outcome is two
    triggers over the same head split on the SPELL_CAST event's
    ``targets_permanent_or_player`` flag (`casting_mixin.
    _targets_permanent_or_player`): the copy (Owlin Spiralmancer's
    ``copy_spell`` off the trigger event, but not optional — the card says
    "copy", not "may copy") and the draw for the spell that doesn't qualify.
    New targets for the copy keep the original's, as `CopySpellEffect`
    documents for every copy effect so far.
    """
    head = {
        "event": EventType.SPELL_CAST, "condition": {"subject": "you"},
        "is_nth_spell_cast_this_turn": 2,
    }
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_spell", {"spell_from_trigger_event": "instance_id"})],
            trigger={**head, "spell_targets_permanent_or_player": True},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={**head, "spell_targets_permanent_or_player": False},
        ),
    ]


register("Shiko and Narset, Unified", _shiko_and_narset_unified)
