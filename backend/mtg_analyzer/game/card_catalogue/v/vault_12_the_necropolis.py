from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _vault_12_the_necropolis() -> list[AbilitySpec]:
    """I — Each player gets three rad counters.
    II — Create X 2/2 black Zombie Mutant creature tokens, where X is the
    total number of rad counters among players.
    III — Put two +1/+1 counters on each creature you control that's a
    Zombie or Mutant.

    — Vault 12: The Necropolis. Chapter I parses fine on its own (it's
    registered here only because chapters II/III need hand-authoring, and a
    registered card's other specs no longer fall back to the parser —
    `card_registry.specs_for`), so it's just carried over verbatim.
    Chapter II needs two things no card in this pool needed before: a
    cross-player aggregate count (`continuous.count_selector`'s new
    ``"total_rad_counters_among_players"``, unlike every other entry there,
    which scopes to a single controller) and a "create X tokens, where X is
    ..." dynamic count (`CreateTokenEffect.count_selector` — the same
    primitive Dockside Extortionist already uses, just with this new
    selector). Chapter III needs a tribal mass-counter filter
    (`AddCountersEffect`'s new ``subtypes`` param).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_player_counters", {"amount": 3, "kind": "rad", "selector": "each_player"})],
            trigger={"event": "SAGA_CHAPTER", "chapter": [1]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count_selector": "total_rad_counters_among_players",
                "power": 2, "toughness": 2, "colors": ["B"],
                "subtypes": ["Zombie", "Mutant"], "token_name": "Zombie Mutant",
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [2]},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {
                "amount": 2, "kind": "+1/+1", "selector": "each_creature_you_control",
                "subtypes": ["Zombie", "Mutant"],
            })],
            trigger={"event": "SAGA_CHAPTER", "chapter": [3]},
        ),
    ]


register("Vault 12: The Necropolis", _vault_12_the_necropolis)
