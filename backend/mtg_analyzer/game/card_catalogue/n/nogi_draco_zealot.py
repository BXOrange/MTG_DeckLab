from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _nogi_draco_zealot() -> list[AbilitySpec]:
    """Dragon spells you cast cost {1} less to cast.
    Whenever Nogi attacks, if you control three or more Dragons, until end of turn, Nogi becomes a Dragon
    with base power and toughness 5/5 and gains flying.

    — Reign of Dragons deck batch. The discount is the parser's own claim. The attack trigger is an
    intervening-if (RULE 603.4: three or more Dragons — Nogi itself counts only once it is one) over a
    resolve-time `grant_until` on itself: a layer-4 ``type_change`` (Dragon, base 5/5) plus a layer-6
    flying grant (``extra_statics``), both until end of turn.
    """
    gate = {"kind": "control_count", "min": 3, "selector": {
        "zone": "battlefield", "of": "you", "filter": {"subtype": "dragon"},
    }}
    return [
        AbilitySpec("static", [EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_subtype": "dragon"})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_until", {
                "static": {"type": "type_change", "params": {"add_subtypes": ["Dragon"], "power": 5, "toughness": 5}},
                "extra_statics": [{"type": "grant_keyword", "params": {"keywords": ["flying"]}}],
                "duration": "end_of_turn", "target_kind": None, "self_subject": True,
            }, condition=gate)],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}, "active_if": gate},
        ),
    ]


register("Nogi, Draco-Zealot", _nogi_draco_zealot)
