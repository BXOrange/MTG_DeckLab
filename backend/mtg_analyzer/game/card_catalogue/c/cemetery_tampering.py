from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register

#: RULE 702.75 / the card: the exiled card may be played only with twenty or more cards in your graveyard.
_GRAVEYARD_THRESHOLD = 20


def _cemetery_tampering() -> list[AbilitySpec]:
    """Hideaway 5 (When this enchantment enters, look at the top five cards of your library, exile one face down, then put the rest on the bottom in a random order.)
    At the beginning of your upkeep, you may mill three cards. Then if there are twenty or more cards in your graveyard, you may play the exiled card without paying its mana cost.

    — PLAY-ALL (Death Toll). Hideaway is the keyword catalogue's. The upkeep trigger is an ``optional`` mill (only the mill is "you may")
    followed by Mosswort Bridge's `play_hideaway_card` gated on the ``graveyard_count`` condition, evaluated after the mill.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "hideaway", "n": 5}),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("optional", {"prompt": "3 Karten mahlen?", "effects": [{"type": "mill", "params": {"count": 3}}]}),
                EffectSpec("play_hideaway_card", {"condition": {"kind": "graveyard_count", "min": _GRAVEYARD_THRESHOLD}}),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Cemetery Tampering", _cemetery_tampering)
