from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _chains_of_mephistopheles() -> list[AbilitySpec]:
    """If a player would draw a card except the first one they draw in
    each of their draw steps, that player discards a card instead. If the
    player discards a card this way, they draw a card. If the player
    doesn't discard a card this way, they mill a card.

    — MEC-32. The same ``first_in_draw_step`` exemption Notion Thief's
    entry above reads, but table-wide (no opponent/you scoping) and its
    own three-branch discard/draw/mill body, genuinely bespoke enough to
    need its own replacement type rather than a combination of existing
    ones — see `effects._discard_instead_of_non_first_draw_replacement`
    for the full RULE 616.1f recursive-termination reasoning (each
    replaced draw's own compensating draw can itself be replaced again,
    strictly shrinking the affected player's hand each time, until it's
    empty and the mill branch fires instead).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("discard_instead_of_non_first_draw", {})],
        ),
    ]


register("Chains of Mephistopheles", _chains_of_mephistopheles)
