"""Reveal a library card matching a targeted spell's mana value."""
from .core import GameEffect, _controller_of, _apply_effects_partitioned
from .library import ShuffleLibraryEffect
from ..targeting import TargetSpec
from ...models.game.events import EventType, GameEvent


class RevealMatchingSpellValueEffect(GameEffect):
    def __init__(self, source=None):
        super().__init__(source)
        self.target_spec = TargetSpec(kind="spell_you_dont_control")

    def apply(self, context, targets=None):
        spell = targets[0] if targets else None
        reference = getattr(spell, "obj", None) or spell
        player = _controller_of(self.source, context)
        if reference is None or player is None:
            return
        mana_value = reference.mana_value
        # Revealing does not move the cards out of the library. The matching
        # card is cast during this resolution; the deferred remainder shuffles.
        hit = None
        for obj in reversed(list(player.library)):
            context.fire_event(GameEvent(
                EventType.REVEAL, player_id=player.id, object=obj.name,
                instance_id=obj.instance_id, from_zone="library",
            ))
            if obj.mana_value == mana_value:
                hit = obj
                break
        effects = ([_CastRevealedLibraryCardEffect(player.id, hit.instance_id)] if hit else [])
        effects.append(ShuffleLibraryEffect(player=player, source=self.source))
        _apply_effects_partitioned(effects, context, None, None, source=self.source)


class _CastRevealedLibraryCardEffect(GameEffect):
    def __init__(self, player_id, instance_id):
        super().__init__()
        self.player_id = player_id
        self.instance_id = instance_id

    def apply(self, context, targets=None):
        player = context.state.player_by_id(self.player_id)
        obj = context.state.find_object(self.instance_id)
        if obj is not None and obj in player.library:
            context.engine._request_resolution_play(
                player, [obj], zone="library", only_spells=True, mandatory=True,
            )
