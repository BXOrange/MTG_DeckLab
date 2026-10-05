from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mirror_mirror() -> list[AbilitySpec]:
    """This artifact enters tapped.
    {7}, {T}, Sacrifice this artifact: Choose target player. At the
    beginning of the next end step, exchange life totals with that player,
    exchange control of all permanents you and that player control, and
    exchange cards in your hands, cards in your libraries, and cards in
    your graveyards.

    — "This artifact enters tapped" needs no entry here at all:
    `card_registry.core.enters_tapped` derives RULE 614.1 tap-lands (and
    this same shape on any other permanent) straight from the card's own
    printed oracle text (`parser.oracle.catalogue.lands.land_tap_condition`),
    independent of this hand-authored registry.
    `CreateDelayedTriggerEffect(step="end", scope="any", capture=
    "target_player")` arms the delayed firing (RULE 603.7), baking in the
    player chosen when the ability first resolved; `choose_targets` is what
    actually offers that RULE 115 pick — a `target_groups=None` ability
    passes its whole ``targets`` list to every one of its own effects, so
    the delayed-trigger effect sees the same pick with no `target_spec` of
    its own. The new `TripleExchangeEffect` (`capture="target_player"`'s
    own new mode) is the delayed effect itself — see its docstring for why
    the three swaps are one bespoke effect rather than three.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("choose_targets", {"kinds": ["player"]}),
                EffectSpec("create_delayed_trigger", {
                    "step": "end", "scope": "any", "capture": "target_player",
                    "effects": [{"type": "triple_exchange", "params": {}}],
                    "description": "Mirror Mirror: Lebenspunkte, Permanents und Zonen tauschen",
                }),
            ],
            cost={"text": "{7}, {T}, Sacrifice ~"},
        ),
    ]


register("Mirror Mirror", _mirror_mirror)
