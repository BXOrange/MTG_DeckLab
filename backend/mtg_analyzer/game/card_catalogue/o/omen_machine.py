from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _omen_machine() -> list[AbilitySpec]:
    """Players can't draw cards.
    At the beginning of each player's draw step, that player exiles the
    top card of their library. If it's a land card, the player puts it
    onto the battlefield. Otherwise, the player casts it without paying
    its mana cost if able.

    — MEC-33. Two independent pieces, neither needing a genuinely new
    engine mechanism once diagnosed against what already exists. (1) "Players
    can't draw cards" is just RULE 121.5-adjacent `draw_limit`
    (`continuous.max_draws_per_turn`, already built for Spirit of the
    Labyrinth/Narset, Parter of Veils) at `max_per_turn=0` with its
    already-default `affects="all"` — a flat cap of zero *is* an outright
    ban, no new code at all, just a value the primitive had never been
    asked for before. (2) The replacement action is a `STEP_BEGIN`
    trigger on the "draw" step with no `phase_relation` at all (RULE
    500.7 — since only the active player ever has a draw step, an
    unscoped "at the beginning of the draw step" trigger fires exactly
    once per turn, for whoever that is — the same "each player's step"
    shape a `phase_relation` of "you"/"not_you" would otherwise narrow,
    just left unnarrowed here) chaining `ExileTopOfLibraryEffect`'s new
    `player_selector="active_player"` (mirroring `DealDamageEffect`'s own
    `"active_player"` selector, the established "no subject of its own,
    read live off `GameState.active_player`" idiom — Roiling Vortex-
    shaped) into the new `LandOrFreeCastEffect`, which reads whatever
    `ExileTopOfLibraryEffect` just exiled (`GameContext.created_objects`)
    and either puts a land onto the battlefield or attempts a free cast
    "if able" (RULE 601.2c — no legal target, and it just stays exiled;
    the printed text names no other fallback). The same tail also prints
    on Wild Evocation (off a *revealed random hand card* instead of an
    exiled library card), confirming `LandOrFreeCastEffect` is a real
    two-card shared primitive worth building generally rather than a
    one-off tied to how the card got there.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("draw_limit", {"max_per_turn": 0})],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_top_of_library", {"player_selector": "active_player"}),
                EffectSpec("land_or_free_cast", {"player_selector": "active_player"}),
            ],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "draw"}},
        ),
    ]


register("Omen Machine", _omen_machine)
