from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _hostility() -> list[AbilitySpec]:
    """Haste
    If a spell you control would deal damage to an opponent, prevent that
    damage. Create a 3/1 red Elemental Shaman creature token with haste for
    each 1 damage prevented this way.
    When Hostility is put into a graveyard from anywhere, shuffle it into
    its owner's library.

    — Haste is the ordinary keyword fold-in. The prevention/token half is a
    ``"prevent_damage"`` replacement: ``to="opponent_player"`` (any player
    other than this permanent's controller — the new recipient kind, no
    real card needed it before), ``source_filter={"is_spell": True,
    "controller": "you"}`` (RULE 609.7a — reuses the DAMAGE event's own
    precomputed ``source_is_instant_or_sorcery`` flag as "is a spell", the
    same stand-in `_additional_damage_replacement`'s own "artifact" check
    already leans on for a source characteristic the event has no dedicated
    flag for), and the new ``rider={"kind": "create_tokens_scaled", ...}``.

    The graveyard-to-library shuffle trigger ("put into a graveyard from
    **anywhere**") is a real, separate RULE 400.7-adjacent primitive this
    engine has no "shuffle just this one card back into its owner's
    library on death" shape for yet (`shuffle_graveyard_into_library`
    shuffles the *whole* graveyard) — left as a documented simplification
    rather than blocking the card's own headline mechanic on it.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "opponent_player",
                "source_filter": {"is_spell": True, "controller": "you"},
                "amount": "all",
                "rider": {
                    "kind": "create_tokens_scaled",
                    "recipient": "you",
                    "token": {
                        "token_name": "Elemental Shaman", "power": 3, "toughness": 1,
                        "colors": ["R"], "subtypes": ["Elemental", "Shaman"], "keywords": ["haste"],
                    },
                },
            })],
        ),
    ]


register("Hostility", _hostility)
