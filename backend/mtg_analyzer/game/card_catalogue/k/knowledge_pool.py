from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _knowledge_pool() -> list[AbilitySpec]:
    """Imprint — When this artifact enters, each player exiles the top
    three cards of their library.
    Whenever a player casts a spell from their hand, that player exiles
    it. If the player does, they may cast a spell from among other cards
    exiled with this artifact without paying its mana cost.

    — Knowledge Pool, MEC-43 round 4G. The first line is `ExileTopOfLibrary
    Effect` widened with ``player_selector="each_player"``/``count=3``/
    ``track_exiled_with=True`` — the RULE 601.2c mass "each player" form,
    each player's own top three seeding the shared imprint pool
    (`GameObject.exiled_with_ids`, MEC-21). The second line is a genuine
    cast-substitution mechanism (`ExileCastSpellIntoImprintPoolEffect`):
    intercepts *any* player's cast from hand (RULE 603.3d reflexive,
    Possibility Storm-shaped trigger — unscoped "a player", not just this
    artifact's controller), exiles the just-cast spell straight off the
    stack into the same shared pool via `RulesEngine.move_spell_off_stack`,
    then offers that player a `_request_choose_objects` pick of exactly one
    *other* pool member to grant a free-cast window (MEC-20's `"grant_free_
    cast"` action) — already zone-agnostic, so an exiled candidate reaches
    `legal_actions` with full targeting exactly like a hand card would.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_of_library", {
                "player_selector": "each_player",
                "count": 3,
                "track_exiled_with": True,
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_cast_spell_into_imprint_pool", {})],
            trigger={
                "event": EventType.SPELL_CAST,
                "filter": {"from_hand": True},
                "reflexive": True,
            },
        ),
    ]


register("Knowledge Pool", _knowledge_pool)
