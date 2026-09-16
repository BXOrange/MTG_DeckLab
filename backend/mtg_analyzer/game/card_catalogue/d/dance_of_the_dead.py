from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _dance_of_the_dead() -> list[AbilitySpec]:
    """Enchant creature card in a graveyard
    When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto
    the battlefield with this Aura." Put enchanted creature card onto the
    battlefield tapped under your control and attach this Aura to it.
    When this Aura leaves the battlefield, that creature's controller
    sacrifices it.
    Enchanted creature gets +1/+1 and doesn't untap during its
    controller's untap step.
    At the beginning of the upkeep of enchanted creature's controller,
    that player may pay {1}{B}. If the player does, untap that creature.

    — MEC-43 round 4F, RULE 704.5n Necromancy-shaped. Reuses Animate
    Dead's own reanimate-Aura core wholesale (`ReturnFromGraveyardEffect
    (target_kind="self_enchant_target")`/`AttachEffect(target_kind=
    "created")`/`SacrificeAttachedPermanentEffect` — see that entry's own
    docstring for the three primitives the whole family rides on:
    `GameObject.reanimate_target_id`, the graveyard-wide `targeting.
    legal_targets` branch, and `RulesEngine._resolve_permanent_spell`'s
    "leave unattached instead of failing" special-case for a graveyard-zone
    attach target). The one difference from Animate Dead's reanimate
    clause is "tapped" instead of a P/T rider — already a plain param
    (`tapped=True`, MEC-43 round 2's Tenacious Dead). The +1/+1 anthem and
    "doesn't untap" are both free, already-``affects="attached_permanent"``
    reuses (`anthem`/`no_untap` — Paralyzing Grasp already prints the
    latter on an enchanted host). The pay-or-untap upkeep clause needed two
    small, genuinely general additions rather than a one-off: RULE 500.7's
    ``phase_relation`` gained a third value, ``"attached_permanent"``
    (`effect_binder._trigger_condition`, read live off `source.
    attached_to`'s *current* controller rather than the ability's own
    source's controller — so the trigger stays correctly silent during the
    brief window before the ETB trigger has attached this Aura to
    anything), and `PayCostThenEffect.payer` (RULE 118.3) gained the same
    sentinel, so "that player may pay" asks the *enchanted creature's*
    controller, not the Aura's own. The untap itself is `TapEffect
    (target_kind="attached_permanent", untap=True)`, already built for
    Freed from the Real/Pemmin's Aura.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "self_enchant_target",
                    "under_your_control": True,
                    "tapped": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1})],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("no_untap", {"affects": "attached_permanent"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{1}{B}",
                "payer": "attached_permanent",
                "effects": [
                    {"type": "tap", "params": {"target_kind": "attached_permanent", "untap": True}},
                ],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"},
                "phase_relation": "attached_permanent",
            },
        ),
    ]


register("Dance of the Dead", _dance_of_the_dead)
