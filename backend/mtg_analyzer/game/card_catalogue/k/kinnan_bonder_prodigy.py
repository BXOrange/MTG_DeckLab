from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _kinnan_bonder_prodigy() -> list[AbilitySpec]:
    """Whenever you tap a nonland permanent for mana, add one mana of any
    type that permanent produced.
    {5}{G}{U}: Look at the top five cards of your library. You may put a
    non-Human creature card from among them onto the battlefield. Put the
    rest on the bottom of your library in a random order.

    — Kinnan, Bonder Prodigy. Wild Growth's sibling — the same RULE 605.4
    triggered mana ability — but the *type* isn't printed: "any type that
    permanent produced" is only knowable from the firing, so
    `MirrorProducedManaEffect` reads the `TAPPED_FOR_MANA` event's
    ``produced`` payload off `GameContext.trigger_event`. That is narrower
    than `AddManaEffect`'s ``"ANY"`` sentinel (which offers every colour):
    Basalt Monolith copies {C}, and a Bloom Tender copies only what it
    actually made.

    The trigger's group subject is ``{"controller": "you"}`` with a
    nonland type filter, so an opponent's taps and your own lands are both
    correctly ignored.

    **Documented simplification**: with 2+ distinct types produced in a
    single tap (only possible for an "any combination of colours" ability)
    the first is copied rather than opening a choice — see
    `MirrorProducedManaEffect`. The activated ability's "non-Human" filter
    likewise collapses to a plain creature filter, the same simplification
    the shipped `impulsive_look` grammar already makes for subtype-negated
    filters elsewhere.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mirror_produced_mana", {"count": 1})],
            trigger={
                "event": EventType.TAPPED_FOR_MANA,
                "condition": {"subject": "group", "controller": "you", "type": "nonland"},
                "mana_ability": True,
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("impulsive_look", {
                "count": 5,
                "criteria": "Creature",
                "hit_destination": "battlefield",
                "miss_destination": "library_bottom",
                "optional": True,
            })],
            cost={"text": "{5}{G}{U}"},
        ),
    ]


register("Kinnan, Bonder Prodigy", _kinnan_bonder_prodigy)
