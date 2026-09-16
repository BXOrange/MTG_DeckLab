from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _birthing_pod() -> list[AbilitySpec]:
    """{1}{G/P}, {T}, Sacrifice a creature: Search your library for a
    creature card with mana value equal to 1 plus the sacrificed
    creature's mana value, put that card onto the battlefield, then
    shuffle. Activate only as a sorcery.

    — MEC-43, the other shared-primitive cluster: `GameObject.sacrificed_
    cost_mana_value` was only ever stamped for a *spell's* RULE 601.2b
    additional cost (`_pay_additional_cast_cost`) — an *activated
    ability's* own sacrifice cost (`_pay_activation_cost`) stamped
    nothing at all. Mirroring the same stamp there (right after the
    victim reaches the graveyard, cleared unconditionally at the top of
    every payment the same way the cast-cost site does) is the one new
    piece; `SearchLibraryEffect.mana_value_from` (Eldritch Evolution/
    Neoform's own "N plus the sacrificed X's mana value" shape) already
    reads it generically off whatever `GameObject` an effect's ``source``
    resolves to — an activated ability's own permanent, here — with no
    changes needed on the search side at all.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"},
                "destination": "battlefield",
                "mana_value_from": {"source": "sacrificed_cost", "plus": 1, "cmp": "eq"},
            })],
            cost={"text": "{1}{G/P}, {T}, Sacrifice a creature", "sorcery_speed_only": True},
        ),
    ]


register("Birthing Pod", _birthing_pod)
