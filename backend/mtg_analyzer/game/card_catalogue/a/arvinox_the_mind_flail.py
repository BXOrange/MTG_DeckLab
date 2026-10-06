from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _arvinox_the_mind_flail() -> list[AbilitySpec]:
    """Arvinox isn't a creature unless you control three or more permanents you don't own.
    At the beginning of your end step, exile the bottom card of each opponent's library face down. For as long as those cards remain exiled, you may look at them, you may cast permanent spells from among them, and you may spend mana as though it were mana of any color to cast those spells.

    — PLAY-ALL (Miracle Worker). The first line is a `type_change` removing ``creature`` while the new ``not_owned_by_you`` count of
    permanents you control is below 3. The end-step trigger is `exile_top_of_library` from the ``bottom`` of ``each_opponent``'s
    library face down, then Gix's `grant_conditional_cast_from_exile` (a standing permission) narrowed to permanent spells with
    ``any_color`` (the card's `mana_wildcard_permission`).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "self", "remove_types": ["creature"],
                "active_if": {"kind": "not", "condition": {
                    "kind": "control_count",
                    "selector": {"zone": "battlefield", "of": "you", "filter": {"not_owned_by_you": True}},
                    "min": 3,
                }},
            })],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {
                    "player_selector": "each_opponent", "position": "bottom", "face_down": True,
                }),
                EffectSpec("grant_conditional_cast_from_exile", {
                    "all_cards": True, "condition": {}, "permanent_only": True, "any_color": True,
                }),
            ],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
        ),
    ]


register("Arvinox, the Mind Flail", _arvinox_the_mind_flail)
