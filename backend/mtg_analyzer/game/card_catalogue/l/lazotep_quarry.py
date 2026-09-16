from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _lazotep_quarry() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice a creature: Add one mana of any color.
    {X}{2}, {T}, Sacrifice a Desert: Exile target creature card with mana
    value X from your graveyard. Create a token that's a copy of it,
    except it's a 4/4 black Zombie. Activate only as a sorcery.

    — MEC-41. The two mana abilities are plain oracle-derived RULE 605.1a
    lines (`game/mana_abilities.py`'s `parse_mana_abilities`, read off the
    card's own printed text unconditionally regardless of catalogue
    registration — see this module's own opening docstring) and need no
    entry here; only the third needs hand-authoring. New
    `exile_own_graveyard_card_mana_value_x` (reading the ability's own
    announced ``{X}`` via `GameObject.x_paid`, now stamped for an
    activated ability's own source too — see `GameEngine.activate_
    ability`) chained via ``then_specs`` into `create_token_copy_of_
    linked_exile`. **Documented simplifications**: RULE 115's "target" is
    read as a resolve-time pick instead (see the first effect's own
    docstring for why); colour ("black") is dropped, the same
    simplification The Jolly Balloon Man's own entry accepts (`Card.
    as_copy` has no colour override).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("exile_own_graveyard_card_mana_value_x", {
                "then_specs": [
                    {"type": "copy_permanent", "params": {
                        "target_kind": None, "referent": "linked_exile",
                        "set_power": 4, "set_toughness": 4, "add_subtypes": ["Zombie"],
                    }},
                ],
            })],
            cost={"text": "{X}{2}, {T}, Sacrifice a Desert", "sorcery_speed_only": True},
        ),
    ]


register("Lazotep Quarry", _lazotep_quarry)
