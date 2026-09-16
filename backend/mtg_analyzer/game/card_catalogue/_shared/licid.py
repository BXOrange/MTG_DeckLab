from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec

#: MEC-47 — the Tempest Licid cycle. Every Licid shares the same activation
#: line ("{cost}, {T}: This creature loses this ability and becomes an Aura
#: enchantment with enchant creature. Attach it to target creature. You may
#: pay {end_cost} to end this effect.") and differs only in its "Enchanted
#: creature …" clause. `LicidBecomeAuraEffect`/`LicidRevertEffect` +
#: `GameObject.is_licid_aura` + the `is_licid_aura`/`not_licid_aura`
#: `static_conditions` do the transform; the granted clause is an ordinary
#: `affects="attached_permanent"` static that only bites once
#: `attached_to` is set. Shared by every card in `card_catalogue`'s Licid
#: family (see e.g. `card_catalogue/g/gliding_licid.py`).
def _cond_marker(kind: str) -> EffectSpec:
    # Fresh every call — the binder mutates specs when binding, so a shared
    # module constant would be corrupted for the next Licid (and every
    # subsequent `specs_for`).
    return EffectSpec("activation_condition_marker", {"condition": {"kind": kind}})


def _licid(name: str, cost: str, end_cost: str, granted, granted_raw: str,
           granted_kind: str = "static", trigger=None,
           granted_cost=None, keep_creature: bool = False) -> list[AbilitySpec]:
    """``granted`` — the `EffectSpec`s of the Licid's "Enchanted creature …"
    ability. ``granted_kind`` is ``"static"`` (the anthem/keyword/control
    grants — inert until `attached_to` is set), ``"triggered"`` (Leeching /
    Stinging — needs ``trigger``) or ``"activated"`` (Nurturing — needs
    ``granted_cost``)."""
    granted_specs = [EffectSpec(s.type, dict(s.params)) for s in granted]
    if granted_kind == "triggered":
        granted_ability = AbilitySpec("triggered", granted_specs,
                                      trigger=dict(trigger or {}))
    elif granted_kind == "activated":
        granted_ability = AbilitySpec("activated", granted_specs,
                                      cost={"text": granted_cost or "{0}"})
    else:
        granted_ability = AbilitySpec("static", granted_specs)
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("licid_become_aura", {"keep_creature": True} if keep_creature else {}),
             _cond_marker("not_licid_aura")],
            cost={"text": f"{cost}, {{T}}"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("licid_revert", {}), _cond_marker("is_licid_aura")],
            cost={"text": end_cost},
        ),
        granted_ability,
    ]


def _kw_at(kw: str) -> EffectSpec:
    return EffectSpec("grant_keyword", {"keywords": [kw], "affects": "attached_permanent"})
