from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mana_vault() -> list[AbilitySpec]:
    """This artifact doesn't untap during your untap step.
    At the beginning of your upkeep, you may pay {4}. If you do, untap this
    artifact.
    At the beginning of your draw step, if this artifact is tapped, it deals
    1 damage to you.
    {T}: Add {C}{C}{C}.

    — Mana Vault. Three of the four lines were already expressible; the two
    that weren't are now general primitives rather than one-offs:

    * "you may pay {4}. If you do, untap ~." is the new ``pay_cost_then``
      (RULE 118.3) — the general form of the shipped, energy-only
      `PayEnergyThenEffect`, reusing the very same `_can_pay_player_cost`/
      `_pay_player_cost` machinery ward and "sacrifice ~ unless you pay"
      share, so an arbitrary `ActivationCost` works without a fourth
      parallel payment path. `UntapSelfEffect` deliberately bypasses the
      untap-step restriction the card's own first line imposes — that
      restriction is about RULE 502.4, not about this ability.
    * "if this artifact is tapped" is a RULE 603.4 intervening-if about the
      ability's **own source's** state (`effect_binder`'s new
      ``source_state`` trigger key), rather than about the event or whose
      turn it is — the two intervening-if flavours that already existed.

    The mana ability and the untap restriction both come from the engine
    directly (the printed mana ability needs no spec; the restriction is the
    shipped ``no_untap`` static).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("no_untap", {})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{4}",
                "effects": [{"type": "untap_self", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "target_kind": None, "selector": "controller"})],
            trigger={
                "event": EventType.STEP_BEGIN,
                "filter": {"step": "draw"},
                "phase_relation": "you",
                "source_state": "tapped",
            },
        ),
    ]


register("Mana Vault", _mana_vault)
