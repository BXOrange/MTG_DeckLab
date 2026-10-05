from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


#: The Lander token's own ability (the curated token catalogue has no entry for it).
_LANDER_TEXT = (
    "{2}, {T}, Sacrifice this token: Search your library for a basic land card, "
    "put it onto the battlefield tapped, then shuffle."
)


def _horizon_explorer() -> list[AbilitySpec]:
    """Lands you control enter untapped.
    Whenever you attack a player, create a Lander token. (It's an artifact with
    "{2}, {T}, Sacrifice this token: Search your library for a basic land card,
    put it onto the battlefield tapped, then shuffle.")

    — PLAY-ALL Step 2 (World Shaper). The attack trigger is the parser's
    `PLAYER_ATTACKED` head (subject you) over `create_token` of a Lander
    token synthesized from its printed ability text (no curated catalogue entry). The first
    clause is the new `lands_enter_untapped` static (layer ``enters_untapped``,
    `continuous.enters_untapped_from_static`): it overrides a land's own
    tapped-entry clause — a shock land's pay-life prompt is skipped and a
    "tapped" land enters untapped — wherever `enter_land_tapped` /
    `predict_land_tapped` / the entry-by-effect site decide tapped-ness.
    """
    return [
        AbilitySpec("static", [EffectSpec("lands_enter_untapped", {})]),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Lander", "is_artifact": True,
                "oracle_text": _LANDER_TEXT,
            })],
            trigger={"event": EventType.PLAYER_ATTACKED, "condition": {"subject": "you"}},
        ),
    ]


register("Horizon Explorer", _horizon_explorer)
