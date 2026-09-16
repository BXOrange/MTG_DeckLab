from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _selfless_safewright() -> list[AbilitySpec]:
    """Flash
    Convoke (Your creatures can help cast this spell. Each creature you tap
    while casting this spell pays for {1} or one mana of that creature's
    color.)
    When this creature enters, choose a creature type. Other permanents you
    control of that type gain hexproof and indestructible until end of
    turn.

    — Eliferate deck batch. Flash/Convoke come from the RULE 702 keyword
    catalogue automatically. The ETB clause is a *resolve-time* "choose a
    creature type" (RulesEngine._request_choose_creature_type_grant — see
    its docstring for why this is a different primitive from RULE 601.2b's
    as-it-enters `choose_creature_type_on_enter`), immediately followed by
    the grant (`grant_keywords_to_chosen_type_until_eot`) as its own
    ``then_specs`` tail, parked/resumed by the existing RULE 608.2
    suspended-resolution machinery (`GameState.deferred_effects`) rather
    than any new continuation plumbing.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("_request_choose_creature_type_grant", {
                "then_specs": [
                    {
                        "type": "grant_keywords_to_chosen_type_until_eot",
                        "params": {"keywords": ["hexproof", "indestructible"]},
                    },
                ],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Selfless Safewright", _selfless_safewright)
