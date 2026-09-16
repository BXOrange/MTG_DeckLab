from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _mesmeric_orb() -> list[AbilitySpec]:
    """Whenever a permanent becomes untapped, that permanent's controller
    mills a card.

    — MEC-43 round 4E, the ticket's own headline engine gap: "becomes
    untapped" had no per-permanent engine event to trigger off at all
    (`EventType.UNTAP` fires once per untap *step*, keyed by player, never
    per permanent). Closed at the root rather than special-cased for this
    one card — `RulesEngine.set_tapped` (already the untap direction's
    real choke point, mirroring how it already fires `TAPPED` for the tap
    direction) now also fires the new `EventType.UNTAPPED`, and every
    other real untap route that used to bypass it (the untap step's own
    per-permanent loop, an ability's own ``{Q}``/"Untap ~" cost) was
    switched to call it too — `TapEffect`'s own ``untap=True`` mode
    already went through `set_tapped` unconditionally, so it needed no
    change to pick this up. `parser/oracle/segmenter.py`'s `_TRIGGER_VERBS`
    then gained the matching "becomes untapped" row, so a future oracle-
    text card with this same trigger phrase parses for free.

    The card's own effect — "**that permanent's controller** mills a
    card", not "you" — needed `MillEffect` widened with a new
    ``selector="event_controller"`` (mirroring `LoseLifeEffect.
    selector="event_player"`/`DealDamageEffect.selector`'s identical
    "read the firing event's own payload" idiom via the shared
    `_event_player` helper), since nothing had ever needed "whoever the
    firing event names" as *mill's* own subject before. Hand-authored
    since the front-end has no grammar yet for a group condition's own
    matched object flowing into its effect's subject.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("mill", {"count": 1, "selector": "event_controller"})],
            trigger={"event": EventType.UNTAPPED},
        ),
    ]


register("Mesmeric Orb", _mesmeric_orb)
