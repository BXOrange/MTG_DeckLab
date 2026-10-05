from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _machine_gods_effigy() -> list[AbilitySpec]:
    """You may have this artifact enter as a copy of any creature on the
    battlefield, except it's an artifact and it has "{T}: Add {U}." (It's
    not a creature.)
    {T}: Add {U}.

    — MEC-12 (cEDH Kinnan). `EnterAsCopyReplacement`'s new
    ``grant_mana_option`` param — RULE 707.2's copy replaces the card's
    own printed text (including its own real "{T}: Add {U}." line) with
    the copied creature's, so that ability has to be re-granted as part
    of this same "except" clause rather than assumed to survive; applied
    as a fresh `StaticAbility` on the copy itself once `become_copy`
    resolves (`GameObject.granted_mana_options` is a read-only,
    every-recompute-rederived property, not a settable field). The plain
    "{T}: Add {U}." second line needs no entry of its own — read straight
    off oracle text by `mana_abilities_for`, same as Treasure Vault/
    Horizon of Progress — but note it only actually produces mana while
    this artifact *hasn't* copied anything (a successful copy overwrites
    it, which is exactly why the grant above exists).
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("enter_as_copy", {
                "target_kind": "creature", "add_types": ["artifact"],
                "grant_mana_option": {"U": 1},
                "optional": True,
            })],
        ),
    ]


register("Machine God's Effigy", _machine_gods_effigy)
