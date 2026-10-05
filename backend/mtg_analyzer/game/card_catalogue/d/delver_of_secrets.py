from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _delver_of_secrets() -> list[AbilitySpec]:
    """At the beginning of each upkeep, look at the top card of your
    library. You may reveal that card. If an instant or sorcery card is
    revealed this way, transform Delver of Secrets.

    — Delver of Secrets. RULE 712's one still-open template
    (`docs/implementation-state/BACKLOG.md` called it out by name): a *conditional*
    transform gated on a library-peek rather than RULE 731's day/night
    spells-cast count. `RevealTopThenTransformEffect` (`game/effects/core.py`)
    is the new general-purpose primitive — it takes a `models.cards.card_query`
    criteria dict, so any future card sharing this exact template ("look at
    the top card…, if it's a[n] X card, transform ~") reuses it instead of
    a bespoke class. The "reveal" and "may" in the printed text don't
    change any actual decision here (the check is unconditional on what's
    really on top, and there's no consequence to *not* revealing it since
    nothing else looks at it), so both are simplifications with no
    observable difference to a solo player. Fires on every player's
    upkeep, not just its controller's, and reads *its own controller's*
    library regardless of whose upkeep triggered it, exactly like Tangle
    Wire's "each player's upkeep" trigger reads "that player" for its own
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_transform", {
                "criteria": {"type": ["instant", "sorcery"]},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
        ),
    ]


register("Delver of Secrets", _delver_of_secrets)
