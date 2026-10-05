from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _etali_primal_sickness() -> list[AbilitySpec]:
    """Back face — Etali, Primal Sickness (Legendary Creature — Phyrexian
    Elder Dinosaur, 11/11):
    Trample, indestructible
    Whenever Etali deals combat damage to a player, they get that many
    poison counters. (A player with ten or more poison counters loses the
    game — a standing rule, not something this ability itself needs to
    enforce; RULE 704's SBA pass already checks poison counters on every
    permission-generating event.)

    — checked against Scryfall's own rulings for this card (2026-09-04).
    `Card.back_face()` carries no keywords array of its own (the same gap
    the Daybound/Nightbound cross-check in `parser.oracle.catalogue.
    keywords.parse_keywords` already works around for other DFCs — see
    `Done_Backend.md`'s Replay-deserializer entry), so Trample/
    Indestructible are hand-authored here rather than left to the RULE 702
    auto-bind, which would otherwise see nothing at all for this face. The
    poison trigger is the new `add_counters_to_trigger_damaged_player`
    (``kind="poison"``) — RULE 603.3d's "they"/"that many" pronouns read
    the firing `DAMAGE` event's own recipient/amount directly, the same
    shape `LoseGameTriggerDamagedPlayerEffect` (Frodo, Sauron's Bane)
    already established for a player-scoped pronoun off that event.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("keyword", [], keyword={"name": "indestructible"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters_to_trigger_damaged_player", {"kind": "poison"})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Etali, Primal Sickness", _etali_primal_sickness)
