from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _espers_to_magicite() -> list[AbilitySpec]:
    """Exile each opponent's graveyard. When you do, choose up to one target creature card exiled this way. Create a token that's a copy of that card, except it's an artifact and it loses all other card types.

    — PLAY-ALL (Revival Trance). The new `exile_opponent_graveyards_copy_creature` exiles every opponent's graveyard and
    makes the artifact-only token copy (``Card.as_copy(only_types=…)``) of one creature card among them.
    A separate reflexive trigger announces an optional target among the cards actually exiled this way;
    its allowed zone incarnations survive responses and copy-target changes (RULE 603.12/400.7).
    """
    return [
        AbilitySpec("spell_effect", [EffectSpec("exile_opponent_graveyards_copy_creature", {})]),
    ]


register("Espers to Magicite", _espers_to_magicite)
