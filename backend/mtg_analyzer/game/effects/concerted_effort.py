"""Resolution-time sharing of the abilities named by Concerted Effort."""
from __future__ import annotations

from .core import YOUR_CREATURES_GROUP, GameEffect, EffectRegistry, _controller_of
from .counters_tokens import GrantUntilEffect
from .. import combat

SHARED_KEYWORDS = frozenset({'flying', 'fear', 'first_strike', 'double_strike', 'trample', 'vigilance'})



class ShareCreatureCombatAbilitiesEffect(GameEffect):
    def apply(self, context, targets=None):
        player = _controller_of(self.source, context)
        if player is None:
            return
        creatures = [obj for obj in context.state.permanents_controlled_by(player.id) if obj.is_creature]
        keywords, protections = set(), set()
        for obj in creatures:
            current = combat._obj_keywords(obj)
            keywords.update(current & SHARED_KEYWORDS)
            if not obj.loses_all_abilities:
                keywords.update(combat._landwalk_slugs(obj))
                protections.update(combat.protections_of_text(obj.effective_oracle_text))
            else:
                keywords.update(kw for kw in current if kw.endswith('walk'))
            protections.update(obj.granted_protections)
            protections.update(obj.temp_protections)
        keywords.discard('landwalk')  # Scryfall's generic category carries no land quality.
        if not keywords and not protections:
            return
        GrantUntilEffect(source=self.source, target_kind=None, duration='end_of_turn', lock_group=True,
            static={'type': 'grant_keyword', 'params': {
                'affects': YOUR_CREATURES_GROUP, 'keywords': sorted(keywords)}},
            extra_statics=[{'type': 'grant_protection_static', 'params': {
                'affects': YOUR_CREATURES_GROUP, 'protections': sorted(protections)}}],
        ).apply(context)


EffectRegistry.register('share_creature_combat_abilities', lambda p: ShareCreatureCombatAbilitiesEffect())
