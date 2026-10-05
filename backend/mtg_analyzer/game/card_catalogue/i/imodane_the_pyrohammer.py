from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _imodane_the_pyrohammer() -> list[AbilitySpec]:
    """Whenever an instant or sorcery spell you control that targets only
    a single creature deals damage to that creature, Imodane deals that
    much damage to each opponent.

    — Imodane deck batch, the commander's own signature ability and this
    batch's biggest new-primitive investment: `DealDamageEffect.amount_
    from_trigger_event` (new — every other damage-doubling/mirroring
    card in this catalogue reads a count selector or a flat override, not
    a *firing event's own* damage amount) reads the DAMAGE event's
    ``amount`` field the trigger fired with. Two new event flags make the
    trigger condition possible at all: `RulesEngine.deal_damage`/
    `DealDamageEffect.apply` now stamp ``source_is_instant_or_sorcery``
    (the source's own printed card type) and ``source_targets_only_
    single_creature`` (computed from the *resolving effect's own*
    ``target_spec`` — count 1, not optional, not a mass selector — and
    the target's own `is_creature`) onto every DAMAGE event; two matching
    `effect_binder._trigger_condition` predicate keys
    (``requires_source_instant_or_sorcery``/``requires_single_creature_
    target``) check them. "You control" is the ordinary ``"subject":
    "group", "controller": "you"`` group-subject check (DAMAGE's group-
    controller key is already ``source_controller_id``).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {
                "amount_from_trigger_event": "amount", "selector": "each_opponent",
            })],
            trigger={
                "event": "DAMAGE",
                "condition": {"subject": "group", "controller": "you"},
                "requires_source_instant_or_sorcery": True,
                "requires_single_creature_target": True,
            },
        ),
    ]


register("Imodane, the Pyrohammer", _imodane_the_pyrohammer)
