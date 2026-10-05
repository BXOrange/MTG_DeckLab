from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _resculpt() -> list[AbilitySpec]:
    """Exile target artifact or creature. Its controller creates a 4/4 blue
    and red Elemental creature token.

    — Resculpt. ``target_kind="permanent"`` is the same documented
    simplification Feed the Swarm's entry above uses (drops the artifact/
    creature type union — no target kind names exactly that pair). ENG-37 B3:
    a `seq` of `exile` then `create_token` with ``creators="previous_target_
    controller"`` — `create_token` reads the just-exiled object's last-known
    controller (RULE 608.2h), which survives the zone change — retiring the
    fused `exile_create_token`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("seq", {"effects": [
                {"type": "exile", "params": {"target_kind": "permanent"}},
                {"type": "create_token", "params": {
                    "power": 4, "toughness": 4, "colors": ["U", "R"],
                    "subtypes": ["Elemental"],
                    "creators": "previous_target_controller",
                }},
            ]})],
        )
    ]


register("Resculpt", _resculpt)
