from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _sheoldred_whispering_one() -> list[AbilitySpec]:
    """Swampwalk
    At the beginning of your upkeep, return target creature card from your
    graveyard to the battlefield.
    At the beginning of each opponent's upkeep, that player sacrifices a
    creature of their choice.

    — MEC-43 round 4B. Swampwalk folds in via the ordinary keyword
    catalogue. The first trigger already parses on its own — reproduced
    verbatim (same registered-card reproduction reason as Jin-Gitaxias
    above). The second needed `ChooseObjectsEffect`'s new
    ``player_selector="active_player"`` (the "no subject of its own, read
    live off `GameState.active_player`" idiom `ExileTopOfLibraryEffect`/
    `LandOrFreeCastEffect` already established for Omen Machine) paired
    with a ``phase_relation="not_you"`` upkeep trigger — "each opponent's
    upkeep" fires exactly when the active player is an opponent, so "that
    player" is simply whoever is active when this checks.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_creature", "destination": "battlefield"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("choose_objects", {
                "action": "sacrifice", "what": "creature", "player_selector": "active_player",
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "not_you"},
        ),
    ]


register("Sheoldred, Whispering One", _sheoldred_whispering_one)
