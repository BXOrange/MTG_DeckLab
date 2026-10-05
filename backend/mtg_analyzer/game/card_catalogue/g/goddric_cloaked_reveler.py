from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _goddric_cloaked_reveler() -> list[AbilitySpec]:
    """Haste
    Celebration — As long as two or more nonland permanents entered the battlefield under your control this
    turn, Goddric is a Dragon with base power and toughness 4/4, flying, and "{R}: Dragons you control get
    +1/+0 until end of turn." (He loses all other creature types.)

    — Reign of Dragons deck batch. Haste is a keyword. The celebration is one `active_if` gate (the new
    ``nonland_permanents_entered_this_turn``, event-derived) on three self statics: a layer-4
    ``type_change`` that *replaces* his creature types (``set_subtypes``) and sets base 4/4, flying, and a
    granted activated ability whose body pumps every Dragon you control (a structured selector, so it counts Goddric's own derived
    Dragon type). Scryfall's ``keywords`` lists Flying
    for him, which the keyword fold-in would grant unconditionally, so the registration suppresses it
    (``suppress_keywords``) and the celebration static is the only source.
    """
    celebration = {"kind": "nonland_permanents_entered_this_turn", "min": 2}
    return [
        AbilitySpec("static", [EffectSpec("type_change", {
            "affects": "self", "set_subtypes": ["Dragon"], "power": 4, "toughness": 4,
            "active_if": dict(celebration),
        })]),
        AbilitySpec("static", [EffectSpec("grant_keyword", {
            "affects": "self", "keywords": ["flying"], "active_if": dict(celebration),
        })]),
        AbilitySpec("static", [EffectSpec("grant_activated_ability", {
            "affects": "self", "cost": {"text": "{R}"},
            "grant_effects": [{"type": "pump", "params": {
                "power": 1, "toughness": 0, "selector": {
                    "zone": "battlefield", "of": "you", "filter": {"card_type": "creature", "subtype": "dragon"},
                },
            }}],
            "active_if": dict(celebration),
        })]),
    ]


register("Goddric, Cloaked Reveler", _goddric_cloaked_reveler, suppress_keywords=("flying",))
