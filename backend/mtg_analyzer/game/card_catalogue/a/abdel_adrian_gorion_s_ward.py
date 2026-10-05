from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _abdel_adrian_gorions_ward() -> list[AbilitySpec]:
    """When Abdel Adrian enters, exile any number of other nonland
    permanents you control until Abdel Adrian leaves the battlefield.
    Create a 1/1 white Soldier creature token for each permanent exiled
    this way.
    Choose a Background (You can have a Background as a second commander.)

    — MEC-12 (cEDH staples 2), the O-Ring/exile family's last remaining
    member. The new `ExileAnyNumberYouControlEffect` is a *selection*
    among the controller's own permanents, not a RULE 115 target at all —
    `RulesEngine._request_choose_objects`'s chooser, with its own new
    `track_exiled_with=True` accumulating every pick onto `GameObject.
    exiled_with_ids`, the same field `ExileEffect(track_exiled_with=True)`
    uses. The token count is the new `exiled_with_count` count_selector
    (`continuous.count_selector`, threaded a `source` param `CreateTokenEffect`
    never passed before), freshly reading that list's length rather than a
    fixed number — "a token for each permanent exiled **this way**". The
    leaves-battlefield half reuses `ReturnAllExiledWithEffect` verbatim, no
    new code at all — built for Parallax Wave in this same batch, and
    exactly the same shape here (several permanents, each returning to
    *their own* owner, which for Abdel Adrian is always its own controller
    since it only ever exiles its own stuff). Background deckbuilding
    (choosing a second commander, RULE 903-adjacent) isn't a board-state
    mechanic and needs no engine support.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("exile_any_number_you_control", {}),
                EffectSpec("create_token", {
                    "count_selector": "exiled_with_count",
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Soldier"],
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_all_exiled_with", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Abdel Adrian, Gorion's Ward", _abdel_adrian_gorions_ward)
