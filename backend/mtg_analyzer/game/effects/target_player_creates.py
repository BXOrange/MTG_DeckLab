"""Clauses where *target player* is the creator, beside a second target of the spell's controller or caster.

* Dark Salvation: "Target player creates X 2/2 black Zombie creature tokens, then up to one target creature gets
  -1/-1 until end of turn for each Zombie that player controls."
* Echocasting Symposium: "Target player creates a token that's a copy of target creature you control."

The creator is the targeted player (RULE 111.2: the token's controller is the player who creates it), so these
cannot reuse the source-controller-centred `create_token`/`copy_permanent` effects.
"""
from __future__ import annotations

from typing import Any, Optional

from ...models.game.player import Player
from ..targeting import TargetSpec
from .core import EffectRegistry, GameContext, GameEffect


def _split_targets(targets: Optional[list[Any]]) -> tuple[Optional[Player], Optional[Any]]:
    """The (player, object) pair of a "target player … target <object>" clause, in either slot order."""
    player = next((t for t in targets or [] if isinstance(t, Player)), None)
    obj = next((t for t in targets or [] if t is not None and not isinstance(t, Player)), None)
    return player, obj


class TargetPlayerTokensThenShrinkEffect(GameEffect):
    """Dark Salvation: ``count`` tokens for the targeted player, then -1/-1 per ``shrink_subtype`` they control."""

    def __init__(self, count: Any = 1, token: Optional[dict] = None, shrink_subtype: str = "Zombie", source=None) -> None:
        super().__init__(source)
        self.count = count  # the "x" sentinel is bound to the announced X (RULE 107.3c) by `_substitute_x`
        self.token = dict(token or {})
        self.shrink_subtype = shrink_subtype
        self.target_spec = TargetSpec(kind="player")
        self.extra_target_specs = (TargetSpec(kind="creature", optional=True),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card
        from .. import continuous

        player, creature = _split_targets(targets)
        if player is None:
            return
        amount = int(self.count or 0)
        if amount > 0:
            card = synthesize_token_card(
                self.token.get("token_name") or self.shrink_subtype, power=self.token.get("power"),
                toughness=self.token.get("toughness"), colors=list(self.token.get("colors", [])),
                subtypes=list(self.token.get("subtypes", [])),
            )
            made = context.create_token(player.id, card, amount)
            context.created_objects.extend(made)
        if creature is None or creature.zone.value != "battlefield":
            return
        # RULE 608.2: counted now that the tokens exist, for the targeted player (not the spell's controller).
        context.recompute()
        shrink = sum(
            1 for obj in context.state.permanents_controlled_by(player.id)
            if obj.is_creature and continuous.matches_permanent_word(obj, self.shrink_subtype.lower())
        )
        if shrink <= 0:
            return
        pump = EffectRegistry.create("pump", {"power": -shrink, "toughness": -shrink})
        pump.source = self.source
        pump._pump_one(creature)  # RULE 613.4d: until-end-of-turn P/T change on the one chosen creature
        context.recompute()


class TargetPlayerCopiesCreatureEffect(GameEffect):
    """Echocasting Symposium: the targeted player creates a token copy of the spell controller's target creature."""

    def __init__(self, source=None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="player")
        self.extra_target_specs = (TargetSpec(kind="creature_you_control"),)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player, creature = _split_targets(targets)
        if player is None or creature is None or creature.zone.value != "battlefield":
            return
        # RULE 707.2 / 111.2: copiable values of the creature, controlled by the player who creates the token.
        made = context.copy_permanent(player.id, creature, 1)
        context.created_objects.extend(made)


EffectRegistry.register(
    "target_player_tokens_then_shrink",
    lambda p: TargetPlayerTokensThenShrinkEffect(
        count=p.get("count", 1), token=p.get("token"), shrink_subtype=str(p.get("shrink_subtype", "Zombie")),
    ),
)
EffectRegistry.register("target_player_copies_creature", lambda p: TargetPlayerCopiesCreatureEffect())
