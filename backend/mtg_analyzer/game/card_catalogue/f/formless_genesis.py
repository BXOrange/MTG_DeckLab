from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _formless_genesis() -> list[AbilitySpec]:
    """Changeling (This card is every creature type.)
    Create an X/X colorless Shapeshifter creature token with changeling and
    deathtouch, where X is the number of land cards in your graveyard.
    Retrace (You may cast this card from your graveyard by discarding a land
    card in addition to paying its other costs.)

    — PLAY-ALL Step 2 (World Shaper). Changeling and Retrace are keyword
    fold-ins (Retrace is engine-backed: `GameEngine._graveyard_cast_keyword`).
    The token is `create_token` with a ``pt_amount`` operand (Nissa, Ascended
    Animist's dynamic-P/T shape) — a `count_selector` over the land cards in
    *your* graveyard, evaluated as the spell resolves (so the retrace discard,
    which put a land there as a cost, already counts).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("create_token", {
                "count": 1, "colors": [], "subtypes": ["Shapeshifter"], "keywords": ["changeling", "deathtouch"],
                "token_name": "Shapeshifter",
                "pt_amount": {
                    "kind": "count_selector",
                    "selector": {"zone": "graveyard", "of": "you", "filter": {"card_type": "land"}},
                },
            })],
        ),
    ]


register("Formless Genesis", _formless_genesis)
