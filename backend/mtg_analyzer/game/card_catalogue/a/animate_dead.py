from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _animate_dead() -> list[AbilitySpec]:
    """Enchant creature card in a graveyard
    When this Aura enters, if it's on the battlefield, it loses "enchant
    creature card in a graveyard" and gains "enchant creature put onto the
    battlefield with this Aura." Return enchanted creature card to the
    battlefield under your control and attach this Aura to it. When this
    Aura leaves the battlefield, that creature's controller sacrifices it.
    Enchanted creature gets -1/-0.

    — MEC-34, RULE 303.4f's reanimator-Aura template: the Aura's own cast
    target is a graveyard *card*, not a battlefield permanent, so it can't
    attach the ordinary way as it resolves. Needed three pieces, none of
    them previously reachable by any shipped card: (1) `RulesEngine.
    _resolve_permanent_spell` recognizes a graveyard-zone attach target
    and leaves the Aura on the battlefield unattached instead of sending
    it to the graveyard for the "failed" attach, stashing the target on
    the new `GameObject.reanimate_target_id`; (2) `targeting.legal_
    targets` gained a graveyard-wide branch for an "Enchant `<type>` card
    in a graveyard" quality, since the existing "enchant" branch only ever
    searched the battlefield; (3) the ETB ability itself —
    `ReturnFromGraveyardEffect`'s new ``target_kind="self_enchant_
    target"`` reads that stashed id back (rather than a fresh RULE 115
    target) to reanimate the right card under this Aura's controller, then
    the already-shipped `AttachEffect(target_kind="created")` attaches
    this Aura to whatever `ReturnFromGraveyardEffect` just put onto the
    battlefield. The "when this Aura leaves the battlefield, sacrifice
    it" clause is the new `SacrificeAttachedPermanentEffect` (reads
    `attached_to` live, since `GameState.remove_from_battlefield` never
    clears it). The self-referential "it loses/gains" text-change clause
    is RULE 303.4f reminder text describing exactly this behavior with no
    separate gameplay effect — not modeled as its own clause. RULE 704.5n's
    "Aura attached to nothing → owner's graveyard" SBA sweep never
    interferes: it only ever revalidates a permanent whose `attached_to`
    is already set, so the brief window where this Aura is on the
    battlefield but not yet attached is naturally safe.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "self_enchant_target",
                    "under_your_control": True,
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
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": -1, "toughness": 0})],
        ),
    ]


register("Animate Dead", _animate_dead)
