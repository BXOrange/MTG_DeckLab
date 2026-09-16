from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


# ---------------------------------------------------------------------------
# MEC-42: `cEDH staples`'s remaining 12 gaps
# ---------------------------------------------------------------------------


def _ashling_the_limitless() -> list[AbilitySpec]:
    """Elemental permanent spells you cast from your hand gain evoke {4} as
    you cast them. (If you cast a spell for its evoke cost, it's
    sacrificed when it enters.)
    Whenever you sacrifice a nontoken Elemental, create a token that's a
    copy of it. The token gains haste until end of turn. At the beginning
    of your next end step, sacrifice it unless you pay {W}{U}{B}{R}{G}.

    — MEC-42. Evoke (RULE 702.74) had never been built at all — Solitude's
    own catalogue entry explicitly documented it as unmodeled — so this
    card needed the real primitive, not just a per-card workaround: a new
    ``evoke`` cast branch threaded through `can_cast`/`effective_cast_cost`/
    `cast_spell` exactly like Mutate's own substitution (`GameEngine.
    _evoke_cost`, `GameObject.cast_via_evoke`), and a genuinely new "sacrifice
    it when it enters" consequence (not a replacement — its own ETB trigger
    fires first) added right after `_resolve_permanent_spell`'s
    ENTERS_BATTLEFIELD event. This closes the *mana-cost* Evoke family for
    free (Mulldrifter/Shriekmaw/Wall of Reverence-shaped, whose printed
    Evoke line is a plain mana cost parsed straight into `parametric_
    keywords` like Mutate/Escalate's own cost-bearing keywords). MEC-65
    subsequently extended the same keyword binding and cast path to
    Solitude/Endurance/Fury/Subtlety/Grief's "exile a `<color>` card from
    your hand" payment, storing `exile_hand_card_color` in the existing
    parametric-keyword payload.
    Ashling's own *grant* ("Elemental permanent spells you cast from your
    hand gain evoke {4}") is a new `grant_evoke` static
    (`continuous.granted_evoke_cost_for`, the hand-cast-cost sibling of
    `has_standing_flash_permission`'s "permission static outside the layer
    engine" idiom, since a card still in hand has nothing for RULE 613's
    layer engine to have stamped).

    The second ability needed two more small primitives: `CopyPermanentEffect`'s
    new ``referent="trigger_event"`` (reads the firing SACRIFICE event's own
    ``instance_id`` via `GameState.find_object`, which searches every zone —
    the sacrificed creature is already in the graveyard by the time this
    trigger resolves, so neither the existing ``"source"`` nor ``"previous"``
    referent could name it), and `SacrificeUnlessPayEffect`'s new ``target``
    override (falls back to its own source, as every existing caller already
    relies on) so `CreateDelayedTriggerEffect`'s existing ``capture=
    "created_objects"`` — the same Kiki-Jiki/Puppeteer Clique "create/
    reanimate with haste, [sacrifice/exile] it at the beginning of the next
    end step" primitive — can bake the *token*, not Ashling herself, into
    the delayed "unless you pay" sacrifice. The trigger itself is RULE
    701.17's `EventType.SACRIFICE`, scoped ``sacrifice_type="elemental"`` +
    ``filter={"is_token": False}`` + ``condition={"subject": "you"}`` —
    entirely off the event's own existing payload, no new trigger-condition
    vocabulary needed.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_evoke", {"cost": "{4}", "subtype": "elemental"})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("copy_permanent", {
                    "target_kind": None, "referent": "trigger_event", "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [
                        {"type": "sacrifice_unless_pay", "params": {"cost": "{W}{U}{B}{R}{G}"}},
                    ],
                    "description": "Ashling, the Limitless: Kopie opfern, "
                                   "außer {W}{U}{B}{R}{G} wird bezahlt",
                }),
            ],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "elemental",
                "filter": {"is_token": False},
            },
        ),
    ]


register("Ashling, the Limitless", _ashling_the_limitless)
