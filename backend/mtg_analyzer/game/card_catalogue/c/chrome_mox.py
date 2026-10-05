from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chrome_mox() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, you may exile a nonartifact,
    nonland card from your hand.
    {T}: Add one mana of any of the exiled card's colors.

    — Chrome Mox (ENG-27's own sibling primitive, MEC-17 — RULE 702.45-
    adjacent Imprint's solo real card). The mana ability parses on its own
    (`game/mana_abilities.py`'s new ``_IMPRINTED_COLOR_ADD_RE`` →
    `ManaAbility.color_selector`'s ``"imprinted_card_colors"``, read fresh
    off `GameObject.linked_exile_id` every tap, unconditionally — mana
    abilities are parsed straight from the printed card, not gated on
    hand-authoring, the same reason ENG-27's Bloom Tender/Carpet of
    Flowers primitives needed no catalogue entry either); only the ETB
    exile-and-remember half is hand-authored here, via `ImprintEffect`
    (``exclude_card_types=["artifact", "land"]`` — Chrome Mox's own
    "nonartifact, nonland" filter) with ``remember=True`` threaded through
    `RulesEngine._request_choose_objects`'s general chooser.
    """
    # `optional` deliberately stays off the *spec* — the trigger itself is
    # unconditionally put on the stack (there's no separate RULE 603.5 "you
    # may" gating the trigger header, unlike a plain "you may draw a card"
    # body); `ImprintEffect`'s own `optional=True` default is what asks the
    # real "you may exile…" question at resolution, one prompt not two.
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("imprint", {"exclude_card_types": ["artifact", "land"]})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        )
    ]


register("Chrome Mox", _chrome_mox)
