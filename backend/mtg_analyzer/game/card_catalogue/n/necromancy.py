from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _necromancy() -> list[AbilitySpec]:
    """You may cast this spell as though it had flash. If you cast it any
    time a sorcery couldn't have been cast, the controller of the
    permanent it becomes sacrifices it at the beginning of the next
    cleanup step.
    When this enchantment enters, if it's on the battlefield, it becomes
    an Aura with "enchant creature put onto the battlefield with
    Necromancy." Put target creature card from a graveyard onto the
    battlefield under your control and attach this enchantment to it.
    When this enchantment leaves the battlefield, that creature's
    controller sacrifices it.

    — MEC-44, RULE 303.4f's *non-Aura* reanimator template (Animate Dead's
    own sibling ticket, MEC-34 — that card is a real Aura from load time;
    this one prints as a plain Enchantment and only becomes an Aura once
    it resolves). Three real gaps closed, none needing as much new
    machinery as first diagnosed. (1) The unconditional flash grant needed
    only a trivially-true `conditional_flash={"unconditional": True}`
    key (`ALLOWED_CAST_CONDITION_KEYS`/`condition_query.
    conditional_flash_holds`), since every prior key gated on something.
    (2) "If cast at a time a sorcery couldn't have been cast, sacrifice at
    next cleanup" needed a new `GameObject.cast_outside_sorcery_speed`
    flag, stamped once at cast time (`GameEngine._cast_current_face`,
    since the board — and so the answer — has moved on by the time this
    resolves) and read by a new `EffectSpec.condition` key of the same
    name gating a `create_delayed_trigger`/`sacrifice_self` pair — no new
    delayed-trigger primitive at all: `CreateDelayedTriggerEffect`'s
    existing `step`/`scope` params already cover "at the beginning of the
    next cleanup step" (RULE 514), and `sacrifice_self` already exists
    (Dress Down/Underworld Breach). (3) "It becomes an Aura with
    '`<quoted text>`'" — the ticket's own flagged "real blocker" — turned
    out to need far less than fresh threading through every
    `_attachment_kind`/`_attachment_legal`/`_detach_attachments_from`
    reader: all three already read `GameObject.parametric_keywords` fresh
    off the live object every call, never a load-time snapshot, so the
    new `BecomeAuraEffect` just writes `parametric_keywords["enchant"]`
    directly and every reader picks it up for free.

    Reuses Animate Dead's own `ReturnFromGraveyardEffect`/`AttachEffect
    (target_kind="created")`/`SacrificeAttachedPermanentEffect` wholesale,
    but with a genuine RULE 115 target on the *reanimate* clause itself
    (`target_kind="any_graveyard_creature"` — "**a** graveyard", any
    player's, unlike Animate Dead's own printed-on-the-Aura target)
    rather than Animate Dead's stashed-at-cast-time shape, since Necromancy
    carries no "Enchant" line at cast time at all for `_resolve_permanent_
    spell`'s graveyard-attach recognition to key off — its target is
    chosen when the *triggered ability* resolves instead. **Documented
    simplification**, matching Animate Dead's own: the "it loses/gains"
    self-referential quality-text-change isn't modeled as its own clause
    (RULE 303.4f reminder text describing exactly this behavior, no
    separate gameplay effect) — `BecomeAuraEffect`'s `quality="creature"`
    default is close enough that `_attachment_legal`'s permissive fallback
    (any quality string it doesn't recognize matches everything) covers it
    regardless.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("become_aura", {"quality": "creature"}),
                EffectSpec("return_from_graveyard", {
                    "target_kind": "any_graveyard_creature",
                    "under_your_control": True,
                }),
                EffectSpec("attach", {"target_kind": "created"}),
                EffectSpec(
                    "create_delayed_trigger",
                    {
                        "step": "cleanup", "scope": "controller",
                        "effects": [{"type": "sacrifice_self", "params": {}}],
                        "description": "Necromancy: am Anfang des nächsten "
                                        "Aufräumschritts opfern",
                    },
                    condition={"cast_outside_sorcery_speed": True},
                ),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            conditional_flash={"unconditional": True},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_attached_permanent", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Necromancy", _necromancy)
