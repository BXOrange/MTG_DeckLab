from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _doomsday_excruciator() -> list[AbilitySpec]:
    """Doomsday Excruciator (Creature — Demon, {B}{B}{B}{B}{B}{B}, 6/6)

    "Flying
    When this creature enters, if it was cast, each player exiles all but
    the bottom six cards of their library face down.
    At the beginning of your upkeep, draw a card."

    `ExileTopOfLibraryEffect`'s new ``player_selector="each_player"``/
    ``keep_bottom`` params (MEC-43 round 4C) close the ETB's mass,
    deterministic library exile — "all but the bottom six" is just "the
    top (library size minus six)", no chooser needed since library order
    isn't a real chosen thing this engine exposes a distinction for.
    `EffectSpec.condition`'s existing ``source_was_cast`` (Rocco, Cabaretti
    Caterer) gates it on "if it was cast" (RULE 601.2 — not a reanimated/
    searched/tutored-onto-battlefield entry).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "triggered",
            [EffectSpec(
                "exile_top_of_library",
                {"player_selector": "each_player", "keep_bottom": 6, "face_down": True},
                condition={"source_was_cast": True},
            )],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={"event": "STEP_BEGIN", "filter": {"step": "upkeep"}, "phase_relation": "you"},
        ),
    ]


register("Doomsday Excruciator", _doomsday_excruciator)
