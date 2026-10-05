from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _deadeye_navigator() -> list[AbilitySpec]:
    """Soulbond
    As long as Deadeye Navigator is paired with another creature, each of
    those creatures has "{1}{U}: Exile this creature, then return it to the
    battlefield under your control."

    — Deadeye Navigator. **Soulbond (RULE 702.94)** is now real pairing
    rather than a bare flag keyword. The pair itself is genuine game state
    (`GameObject.paired_with`, held on both objects) rather than a
    continuous effect, because RULE 702.94c breaks it on *events* — either
    creature leaving the battlefield, stopping being a creature, or the two
    ceasing to share a controller — which `RulesEngine.
    break_illegal_soulbond_pairs` sweeps as a state-based action so no
    individual site has to remember to tear it down.

    The pairing trigger is synthesized from the keyword itself
    (`effect_binder`), as *two* abilities: "when **either** enters" means it
    must fire both when Deadeye arrives and when a later unpaired creature
    joins it.

    The grant is then an ordinary layer-6 `grant_activated_ability` static
    over the new ``soulbond_pair`` selector, which resolves to the source
    plus its partner *and only while paired* — so an unpaired Navigator
    grants nothing, with no separate teardown. The granted ability is the
    shipped `blink` effect (RULE 400.7's genuine zone change, which is why
    it re-triggers enters-the-battlefield abilities — the whole point).

    **Documented simplification**: the partner is an auto-pick (the first
    other unpaired creature you control). The trigger is already
    ``optional``, so a player who wants a different partner declines.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "soulbond_pair",
                "cost": {"text": "{1}{U}"},
                "grant_effects": [{"type": "blink", "params": {}}],
            })],
        ),
    ]


register("Deadeye Navigator", _deadeye_navigator)
