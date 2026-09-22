from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _loxodon_smiter() -> list[AbilitySpec]:
    """This spell can't be countered.
    If a spell or ability an opponent controls causes you to discard this
    card, put it onto the battlefield instead of putting it into your
    graveyard.

    MEC-102 — the discard-destination half of the "caused you to discard"
    cycle MEC-101 built the provenance for: `EventType.WOULD_DISCARD` (fired
    by `RulesEngine.discard`/`discard_specific`/`discard_random` just before
    the hand→graveyard move) plus the `discard_to_battlefield` replacement
    (`game/effects/replacements.py`), checked directly against this card's
    own `replacement_effects` rather than through the battlefield-only
    `RulesEngine._all_replacement_effects()` — see that factory's own
    docstring for why. `DISCARD_CARD`/`DISCARD` still fire normally (RULE
    614.1 changes how the discard happens, not whether it did), so any
    "whenever you discard a card" ability still sees it.

    The "can't be countered" line is the pre-existing, already-general
    `cant_be_countered` static (`CantBeCounteredEffect`) — unrelated to this
    ticket, included here only because it's this card's other ability.
    """
    return [
        AbilitySpec("static", [EffectSpec("cant_be_countered", {})]),
        AbilitySpec("replacement", [EffectSpec("discard_to_battlefield", {})]),
    ]


register("Loxodon Smiter", _loxodon_smiter)
