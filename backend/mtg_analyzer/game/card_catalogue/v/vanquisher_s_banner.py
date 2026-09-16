from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vanquishers_banner() -> list[AbilitySpec]:
    """As this artifact enters, choose a creature type.
    Creatures you control of the chosen type get +1/+1.
    Whenever you cast a creature spell of the chosen type, draw a card.

    — Eliferate deck batch. The ETB type choice and the anthem parse on
    their own (`choose_creature_type_on_enter`/`anthem` with
    `subtype_from_source`) — reproduced here verbatim (whole-card hand-
    authoring replaces the parser's own specs entirely, `specs_for`'s
    registry-wins precedence, so a partial registration would silently
    drop them) — alongside the one clause that didn't: the cast trigger.
    That's a new `effect_binder` predicate, `"cast_of_chosen_type"` —
    reads `GameObject.chosen_type` live at check time (unlike the
    fixed-at-bind `"subtypes"` group filter, the wanted type isn't known
    until the ETB choice resolves) against the live-looked-up cast spell's
    own printed subtypes.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "power": 1, "toughness": 1, "affects": "creatures_you_control",
                "subtype_from_source": True,
            })],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "type": "creature", "controller": "you"},
                "cast_of_chosen_type": True,
            },
        ),
    ]


register("Vanquisher's Banner", _vanquishers_banner)
