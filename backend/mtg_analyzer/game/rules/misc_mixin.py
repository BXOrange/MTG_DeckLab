"""Compatibility entry point composing the focused miscellaneous rules subsystems.

Implementations live in the adjacent topic mixins; shared helpers stay re-exported
for existing effect and rules callers. No independent engine state is stored here.
"""
from __future__ import annotations

from ...models.game.player import Player
from .. import continuous
from ..effects.core import StaticEffect

from .misc_helpers import (
    CHOOSE_PLANAR_FACE_KIND,
    PAY_COST_THEN_MAX_X,
    CHEAP_CREATURE_MAX_MANA_VALUE,
    CHEAP_CREATURE_BONUS_COUNTERS,
    PAY_X_OPTION_PREFIX,
    _cost_with_x,
    _CARD_TYPE_WORDS,
    _card_type_words,
    _distinct_card_type_assignment,
    _that_many_value,
    _substitute_x_specs,
    _substitute_x_modes,
    _saga_final_chapter,
    _names_other_word,
    _matches_permanent_type,
    _creature_type_options,
)
from .payment_choices_mixin import PaymentChoicesMixin
from .voting_mixin import VotingMixin
from .resolution_choices_mixin import ResolutionChoicesMixin
from .source_choices_mixin import SourceChoicesMixin
from .tokens_sagas_mixin import TokensSagasMixin
from .variant_systems_mixin import VariantSystemsMixin
from .keyword_actions_mixin import KeywordActionsMixin
from .designations_mixin import DesignationsMixin
from .object_selection_mixin import ObjectSelectionMixin
from .chosen_object_actions_mixin import ChosenObjectActionsMixin
from .stack_interaction_mixin import StackInteractionMixin
from .ward_combat_mixin import WardCombatMixin
from .player_costs_mixin import PlayerCostsMixin


class MiscSystemsMixin(
    PaymentChoicesMixin,
    VotingMixin,
    ResolutionChoicesMixin,
    SourceChoicesMixin,
    TokensSagasMixin,
    VariantSystemsMixin,
    KeywordActionsMixin,
    DesignationsMixin,
    ObjectSelectionMixin,
    ChosenObjectActionsMixin,
    StackInteractionMixin,
    WardCombatMixin,
    PlayerCostsMixin,
):
    """Compose rules operations without changing the RulesEngine entry point."""

    def should_skip_step(self, player: Player, step_name: str) -> bool:
        for effect in player.player_effects:
            if isinstance(effect, StaticEffect) and effect.skips_step(step_name):
                if effect.duration == "once":
                    effect.active = False
                return True
        # MEC-38 (Necropotence's "Skip your draw step."): a standing,
        # battlefield-sourced skip rather than a one-shot/duration-scoped
        # `player_effects` entry — see `continuous.skipped_steps_for`.
        if step_name in continuous.skipped_steps_for(self.state, player):
            return True
        return False
