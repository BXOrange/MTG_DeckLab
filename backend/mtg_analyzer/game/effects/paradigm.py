"""Paradigm (RULE 702.192) for sorceries such as Echocasting Symposium.

"Then exile this spell. After you first resolve a spell with this name, you may cast a copy of it from exile
without paying its mana cost at the beginning of each of your first main phases."

* `ParadigmExileEffect` is the first half, the spell's final instruction: the resolving card is exiled instead of
  going to the graveyard (`RulesEngine._finish_spell_routing` honours a spell that already left the stack) and is
  stamped with the player who resolved it — that stamp *is* "after you first resolve a spell with this name",
  because only a resolution can have put the card in exile this way.
* `ParadigmCastCopyEffect` is the recurring half: a fresh copy of the exiled card is offered for a free cast
  (RULE 707.10, the Isochron Scepter idiom of `CopyImprintedCardEffect`). The exiled card itself never leaves exile.
* `collect_paradigm_triggers` is how that half fires at all: an exiled card has no battlefield presence for the
  ordinary trigger scan to find, the same reason Suspend's exile-zone triggers are built per step
  (`_collect_suspend_triggers`).
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.events import EventType, GameEvent
from ...models.game.game_object import GameObject, Zone
from .core import EffectRegistry, GameContext, GameEffect, TriggeredAbility


class ParadigmExileEffect(GameEffect):
    """RULE 702.192a: "Then exile this spell." — a copy of the spell just ceases to exist instead."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        spell = self.source
        if spell is None or getattr(spell, "is_copy", False) or spell.zone != Zone.STACK:
            return
        context.engine.exile(spell)
        spell.paradigm_player_id = spell.controller_id or spell.owner_id  # set after the move: a zone change resets state


class ParadigmCastCopyEffect(GameEffect):
    """RULE 702.192a: "you may cast a copy of it from exile without paying its mana cost" (RULE 707.12)."""

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ..binding.core import bind_from_catalogue  # function-scoped: binding imports the effect layer

        exiled = self.source
        if exiled is None or exiled.zone != Zone.EXILE:
            return
        player = context.state.player_by_id(exiled.paradigm_player_id)
        copy_obj = GameObject(exiled.card.as_copy(), owner_id=player.id, zone=Zone.EXILE)
        copy_obj.is_copy = True
        copy_obj.controller_id = player.id
        bind_from_catalogue(copy_obj)
        player.add_to_zone(copy_obj, Zone.EXILE)
        context.engine._request_resolution_play(player, [copy_obj], free=True, only_spells=True)


def collect_paradigm_triggers(rules: Any, event: GameEvent) -> None:
    """Queue the Paradigm cast-copy trigger of every Paradigm card the stepping player exiled (RULE 702.192a).

    Fires on the beginning of that player's *first* main phase of the turn only, i.e. the precombat main
    (RULE 505.1); a postcombat main is not "a first main phase".
    """
    if event.type != EventType.STEP_BEGIN or event.get("step") != "main1":
        return
    active_id = rules.state.active_player.id
    for player in rules.state.players:
        for obj in list(player.exile):
            if getattr(obj, "paradigm_player_id", None) != active_id:
                continue
            ability = TriggeredAbility(
                trigger_event=EventType.STEP_BEGIN,
                effects=[ParadigmCastCopyEffect(source=obj)],
                controller_id=active_id,
                source=obj,
                description="Paradigm: cast a copy of this card from exile without paying its mana cost.",
            )
            rules._queue_firing(ability, event, obj)


EffectRegistry.register("paradigm_exile", lambda p: ParadigmExileEffect())
EffectRegistry.register("paradigm_cast_copy", lambda p: ParadigmCastCopyEffect())
