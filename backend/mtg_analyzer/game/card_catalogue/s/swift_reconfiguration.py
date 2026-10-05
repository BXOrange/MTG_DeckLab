from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _swift_reconfiguration() -> list[AbilitySpec]:
    """Flash
    Enchant creature or Vehicle
    Enchanted permanent is a Vehicle artifact with crew 5 and it loses all
    other card types. (It's not a creature unless it's crewed.)

    — MEC-43 round 4E. Flash/"Enchant creature or Vehicle" come from the
    RULE 702 keyword catalogue — the latter needed `targeting.py`'s
    "enchant" quality dispatch widened for a genuine RULE 702.5 compound
    quality (``_ENCHANT_QUALITY_PREDICATES``, unioned by ``" or "`` — every
    real printed card only ever pairs two simple type/subtype words this
    way), since "Vehicle" is a subtype word no existing single-quality
    branch recognized.

    The permanent overwrite is Vraska, Betrayal's Sting's own ``-2``
    template (`type_change`'s ``remove_types``/``add_types``/
    ``add_subtypes``, RULE 613.7f) applied as a *standing* Aura static
    (``affects="attached_permanent"``, Kenrith's Transformation-shaped)
    instead of a resolve-time ``grant_until`` — this is a permanent
    attachment effect, not a one-shot cast trigger. Crew 5 is granted via
    the general `grant_activated_ability` static (its own default
    ``affects="attached_permanent"``), built to exactly mirror what a
    *printed* "Crew N" keyword binds to (`effect_binder._crew_activated_
    ability`): an `ActivationCost.crew_power` cost and a self-targeted
    ``grant_until``/``type_change`` "becomes a creature until end of turn"
    effect — `grant_activated_ability` is a *layer-6 grant*, unlike the
    printed keyword's bind-on-load dispatch, which is exactly what makes
    this reachable at all (the enchanted permanent's own printed keywords
    never include Crew).

    **Documented simplification**: the granted Crew ability doesn't pass
    ``power``/``toughness`` overrides the way `_crew_activated_ability`
    does for a *printed* Vehicle's own ``vehicle_power``/
    ``vehicle_toughness`` — for the overwhelmingly common case (enchanting
    an ordinary creature), this needs no override at all: `Card.power`
    stays whatever was printed regardless of the current layer-4 type
    words, so the crewed permanent's base P/T falls out of the same
    `continuous.recompute` base array every creature already reads. Only
    the rare case of enchanting an *already-printed* Vehicle (rather than
    a creature) would fall back to 0/0 when crewed, since that Vehicle's
    own ``vehicle_power``/``vehicle_toughness`` isn't threaded through a
    static grant authored once for any target.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("type_change", {
                    "affects": "attached_permanent",
                    "add_types": ["artifact"],
                    "remove_types": ["creature", "enchantment", "land", "planeswalker", "battle"],
                    "add_subtypes": ["Vehicle"],
                }),
                EffectSpec("grant_activated_ability", {
                    "affects": "attached_permanent",
                    "cost": {"crew_power": 5},
                    "grant_effects": [{
                        "type": "grant_until",
                        "params": {
                            "target_kind": None, "duration": "end_of_turn",
                            "static": {"type": "type_change", "params": {"add_types": ["creature"]}},
                        },
                    }],
                }),
            ],
        ),
    ]


register("Swift Reconfiguration", _swift_reconfiguration)
