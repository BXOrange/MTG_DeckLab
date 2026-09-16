from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _praetors_grasp() -> list[AbilitySpec]:
    """Search target opponent's library for a card and exile it face down.
    Then that player shuffles. You may play that card for as long as it
    remains exiled.

    — MEC-42. RULE 701.19a "search **target opponent's** library" needed
    `SearchLibraryEffect`'s own controller (who actually picks) to differ
    from the library it searches/shuffles (the RULE 115 target) — new
    ``player_from_target`` (resolves ``player`` to the targeted opponent)
    threading a real ``chooser`` through `RulesEngine._request_search`
    down to `_search_choice`/`_finish_search`/`_put_searched_card`
    (``player_id`` in the pending choice becomes "who answers", a new
    ``library_owner_id`` carries "whose library" — the general "who's
    searching vs. who owns the library" split, reusable by any future
    Bribery/Mind's Desire-shaped card). The new ``"exile_face_down_
    standing_cast"`` destination combines the existing face-down-in-exile
    marker (Beseech the Mirror) with a standing (never-swept)
    `GameState.exile_cast_condition` grant to the *chooser*, not the
    searched player — the ordinary-cost sibling of Bring to Light's own
    same-player ``"exile_free_cast"`` (MEC-41). Also fixed a real, general
    gap found on the way: `can_play_land` never checked `_has_conditional_
    exile_permission` at all, so this permission (or Lukka's own) could
    never actually offer a land.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("search", {
                "criteria": "", "destination": "exile_face_down_standing_cast",
                "player_from_target": True,
            })],
        ),
    ]


register("Praetor's Grasp", _praetors_grasp)
