from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _puppeteer_clique() -> list[AbilitySpec]:
    """When this creature enters, put target creature card from an
    opponent's graveyard onto the battlefield under your control. It
    gains haste. At the beginning of your next end step, exile it.

    — Puppeteer Clique. The reanimate-and-exile sibling of Kiki-Jiki's
    copy-and-sacrifice template (same batch, same primitives):
    `effects.ReturnFromGraveyardEffect`'s new ``haste`` param plus
    `create_delayed_trigger`'s ``capture="created_objects"`` to arm a
    RULE 603.7 delayed ``exile`` naming the exact permanent this
    resolution just reanimated (`GameContext.created_objects`) — see
    `_kiki_jiki_mirror_breaker`'s docstring for the shared design.
    ``target_kind="opponent_graveyard_creature"`` already exists in
    `targeting.py` for exactly this card (its own docstring names
    Puppeteer Clique as the motivating example).
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("return_from_graveyard", {
                    "target_kind": "opponent_graveyard_creature",
                    "destination": "battlefield",
                    "under_your_control": True,
                    "haste": True,
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "controller",
                    "capture": "created_objects",
                    "effects": [{"type": "exile", "params": {"target_kind": None}}],
                    "description": "Puppeteer Clique: Kreatur verbannen",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Puppeteer Clique", _puppeteer_clique)
