from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _avatar_aang() -> list[AbilitySpec]:
    """Flying, firebending 2
    Whenever you waterbend, earthbend, firebend, or airbend, draw a card.
    Then if you've done all four this turn, transform Avatar Aang.

    — PAR-30 ("Firebending grants residue" — the last open sub-bullet of
    that ticket). Flying + Firebending 2 are RULE 702 keywords, auto-bound
    on the front face off `Card.keywords`; the Firebending attack trigger
    now *also* fires `EventType.BENT` (`effect_binder._kw_firebending`
    appends a `RecordBendEffect`), joining the three other bending
    primitives that gained the same event this batch — `RulesEngine.
    earthbend`, the waterbend additional-cast-cost payment (RULE 701.67c),
    and airbend (`ExileEffect.bend_kind`). So the one trigger below reacts
    to all four via `{"subject": "you"}` on `BENT` (the "whenever **you**
    scry/surveil" idiom, `_GROUP_CONTROLLER_EVENT_KEYS["BENT"]`).

    The reflexive "then if you've done all four this turn, transform ~." is
    `EffectSpec.condition`'s new `did_all_bends_this_turn` key — the
    ability controller's `GameState.bends_this_turn` set (cleared each
    `begin_turn`) must cover every entry of `RulesEngine.BEND_KINDS`.
    `transform` with no target flips the source DFC (RULE 712.8); the
    engine rebinds the back face ("Aang, Master of Elements") off its own
    name through the ordinary parser fallback, so nothing here need author
    it.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("transform", {}, condition={"did_all_bends_this_turn": True}),
            ],
            trigger={"event": EventType.BENT, "condition": {"subject": "you"}},
        ),
    ]


register("Avatar Aang", _avatar_aang)
register("Avatar Aang // Aang, Master of Elements", _avatar_aang)
