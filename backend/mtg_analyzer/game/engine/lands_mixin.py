"""The game engine: turn/phase/step loop, actions, goldfish (docs/02 R4.*).

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R4.1-R4.3 (Game Loop, Priority,
Action Validation), UC3 (Goldfisch), docs/07 PART 1/8.

`RulesEngine` is the toolbox of rules primitives; `GameEngine` is the
loop that drives it: it walks a `TurnSequence`, opens priority windows in
which the stack resolves (RULE 117/608), runs step bodies (untap, draw,
combat damage, cleanup), and exposes validated player actions (play a
land, cast a spell, attack) plus a `legal_actions` query the UI/bot can
ask instead of guessing (docs/02 R4.3 — the frontend has no such check
today). `run_goldfish_turn` wires those together into a solo auto-turn
(UC3).
"""

from __future__ import annotations

import itertools
from contextlib import contextmanager
from typing import Any, Optional

from ...models.card import Card
from ...models.events import EventType, GameEvent
from ...models.game_object import GameObject, Zone
from ...models.game_state import GameState, StackItem
from ...models.mana_cost import ManaCost
from ...models.player import Player
from .. import combat, condition_query, continuous, durations, face_down, static_conditions, variants
from ...models import game_format
from ...models.game_format import GameFormat, get_format
from ..costs import (
    DISCARD_HAND,
    PAY_LIFE_X,
    REMOVE_COUNTERS_ANY,
    REMOVE_COUNTERS_X,
    ActivationCost,
    parse_activation_cost,
)
from ..effects import ActivatedAbility
from ..mana_abilities import (
    hand_mana_abilities_for,
    mana_abilities_for,
    option_label,
    restriction_predicate_for_activation,
    restriction_predicate_for_cast,
    validate_color_split,
)
from ..phases import GamePhase, GameStep, default_turn_sequence
from ..rules_engine import RulesEngine
from ..targeting import (
    TargetSpec,
    ability_target_specs,
    all_requirements_satisfiable,
    legal_targets,
    partition_targets,
    requirements_with_targets,
    resolved_count,
    spell_target_specs,
)
from ..graveyard_cast import graveyard_cast_grant_for, has_temporary_graveyard_play_permission
from ..top_library import (
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).


class LandsMixin:
    """Playing lands and casting from a non-hand zone (exile/graveyard/library)."""

    def can_play_land(self, player: Player, obj: GameObject, face: str = "front") -> bool:
        card = self._face_card(obj, face)
        # RULE 505.5b: from hand, always — or from the top of the library
        # (Oracle of Mul Daya-shaped) when some permanent grants that.
        in_playable_zone = (
            obj in player.hand
            or (
                bool(player.library)
                and obj is player.library[-1]
                and may_play_land_from_top_of_library(player, self.state)
            )
            or (obj.zone == Zone.EXILE and self._has_temp_play_permission(obj, player))
            or (
                obj.zone == Zone.GRAVEYARD
                and obj in player.graveyard
                and has_temporary_graveyard_play_permission(player, self.state)
            )
        )
        return (
            card is not None
            and player is self.state.active_player
            and self._in_main_phase()
            and not self.state.stack
            and player.lands_played_this_turn < (
                player.max_lands_per_turn
                + continuous.extra_land_plays_for(self.state, player)
                + player.extra_land_plays_this_turn
            )
            and in_playable_zone
            and card.is_land
        )
    def play_land(self, player: Player, obj: GameObject, face: str = "front") -> GameObject:
        """Play a land from hand (RULE 505.5b — a special action, no stack).

        ``face="back"`` plays a modal DFC's back face instead (RULE 712.10) —
        legal only when that face is itself a land; the front/back choice is
        made once, here, by rebinding ``obj`` onto the back `Card` before the
        rest of this method (which then reads ``obj.card`` exactly as for any
        other land) runs unchanged.

        RULE 601.2b's "as this land enters, choose a creature type/color"
        (Cavern of Souls/Unclaimed Territory-shaped) must be resolved
        *before* the land actually joins the battlefield — the same
        ordering `RulesEngine._resolve_permanent_spell` already gives a
        cast creature/artifact's own `enter_choice_effects`. A land never
        goes through that method at all (RULE 505.5b is a special action,
        not a cast spell going on the stack), so `_offer_enter_choices` is
        called directly here; ``_finish`` is its continuation, mirroring
        `_resolve_permanent_spell`'s own split between "things that don't
        need the choice answered yet" (already done above) and "things
        that do" (deferred into here).
        """
        if not self.can_play_land(player, obj, face=face):
            raise ValueError(f"{player.id} cannot play {obj.name} now")
        if face == "back":
            self.rules.switch_to_face(obj, obj.card.back_face())
        # Zone-agnostic (not just hand) so a land can be played from the top
        # of the library (Oracle of Mul Daya-shaped, `can_play_land` above) —
        # ``obj.zone`` is always accurate (set on creation/every zone move),
        # the same "read the object's own zone" idiom
        # `RulesEngine._remove_from_current_zone` uses for casting.
        player.remove_from_zone(obj, obj.zone)

        def _finish() -> None:
            obj.summoning_sick = True
            # RULE 614.1: a tap-land enters the battlefield tapped —
            # including a shock/check/fast/slow land's conditional shape
            # (payment choice or board-state check), resolved by
            # `enter_land_tapped`.
            self.rules.enter_land_tapped(obj)
            self.state.add_to_battlefield(obj)
            player.lands_played_this_turn += 1
            self.state.record_stat(player.id, "land", name=obj.name)
            self.state.fire_event(
                GameEvent(
                    EventType.LAND_PLAYED,
                    player_id=player.id,
                    card_id=obj.card.id,
                    land=obj.name,
                    # A "whenever you play another land" trigger (City of
                    # Traitors) needs to exclude its own play event via
                    # `effect_binder`'s "group"/"other" subject condition.
                    instance_id=obj.instance_id,
                )
            )
            self.state.fire_event(
                GameEvent(
                    EventType.ENTERS_BATTLEFIELD,
                    controller_id=player.id,
                    object=obj.name,
                    instance_id=obj.instance_id,
                    object_types=sorted(obj.type_words),
                )
            )
            # RULE 117.3c: taking an action reclaims priority for its taker.
            self.give_priority(player)

        self.rules._offer_enter_choices(obj, _finish)
        return obj
    @staticmethod
    def _castable_from_exile(obj: GameObject) -> bool:
        """Whether an object sitting in exile is castable from there.

        Two independent cases: an Adventure creature exiled by its own
        spell half (RULE 715.3d, flagged `adventure_castable`), or a
        prepared copy (RULE 722.3c) — the copy's mere presence in exile
        already proves it's still valid, since `RulesEngine.
        _remove_stranded_tokens` reaps it the instant its source stops
        being prepared/on the battlefield, so no extra freshness check is
        needed here beyond the `prepared_source_id` link existing.
        """
        return obj.adventure_castable or obj.prepared_source_id is not None
    def _has_temp_play_permission(self, obj: GameObject, player: Player) -> bool:
        """RULE 601.3b analogue: a temporary "you may play this card"
        permission (Light Up the Stage-shaped impulsive draw,
        `RulesEngine.exile_with_play_permission`,
        `GameState.temp_play_permissions`) — swept once its "until the end
        of your next turn" (or, Ragavan/Mnemonic Betrayal-shaped, "until
        end of turn") window lapses (`_step_cleanup`), so mere presence
        here means "still valid" without re-checking the turn number.

        Also checks `GameState.temp_play_permission_player`: the permission
        belongs to a *specific* player, not to whoever's zone the card
        happens to sit in (Ragavan exiles from the player it damaged, but
        only its own controller may cast the result) — an absent entry
        (an older snapshot predating that dict, or a caller that never set
        it) defaults to "anyone may", matching every pre-existing single-
        player grant's behaviour.
        """
        if obj.instance_id not in self.state.temp_play_permissions:
            return False
        holder_id = self.state.temp_play_permission_player.get(obj.instance_id)
        return holder_id is None or holder_id == player.id
    def _has_conditional_exile_permission(self, obj: GameObject, player: Player) -> bool:
        """"You may cast this card from exile as long as `<condition>`."
        (Lukka, Coppercoat Outcast) — `GameState.exile_cast_condition`'s
        standing, never-turn-swept sibling of `_has_temp_play_permission`;
        see that field's own docstring for why the two are kept apart.
        """
        entry = self.state.exile_cast_condition.get(obj.instance_id)
        if entry is None:
            return False
        holder_id, condition = entry
        if holder_id != player.id:
            return False
        return static_conditions.condition_holds(condition, self.state, obj, player.id)
    def _graveyard_cast_keyword(self, obj: GameObject) -> Optional[str]:
        """Which alt-cost-from-graveyard keyword ``obj`` carries — ``"flashback"``
        (RULE 702.34) or ``"escape"`` (RULE 702.138) — or ``None``. The two
        share the same "cast from the graveyard for an alternative cost"
        zone gate; only what that cost is (and whether the card is exiled
        after resolving, Flashback only) differs.

        Escape may also be *granted* rather than printed — "Each nonland card
        in your graveyard has escape." (Underworld Breach), a layer-6
        ability grant that no printed keyword scan would ever see, so the
        board is consulted too (`continuous.granted_escape_for`).

        Flashback may likewise be *granted* to one specific graveyard card
        (MEC-24 — "target instant or sorcery card in your graveyard gains
        flashback until end of turn.", Recoup/Snapcaster Mage-shaped) —
        `GameState.temp_flashback_grants`, a resolve-time, turn-scoped,
        per-object marker rather than a continuously-rederived static (the
        granting permanent may leave play or change before the graveyard
        card is ever cast, unlike Underworld Breach's own live grant).
        """
        params = getattr(obj, "parametric_keywords", None) or {}
        if "flashback" in params:
            return "flashback"
        if "escape" in params:
            return "escape"
        if obj.instance_id in self.state.temp_flashback_grants:
            return "flashback"
        if continuous.granted_escape_for(self.state, obj) is not None:
            return "escape"
        return None
    def _castable_from_graveyard(self, obj: GameObject) -> bool:
        """Whether an object sitting in a graveyard is castable from there
        (RULE 702.34/702.138) — unlike `_castable_from_exile`, this needs no
        extra per-object flag: the keyword's mere presence is enough, since
        Flashback/Escape are always-available alternative costs, not a
        one-shot grant from some other effect.
        """
        return self._graveyard_cast_keyword(obj) is not None
    def _graveyard_cast_permission(self, player: Player, obj: GameObject) -> bool:
        """Whether ``obj`` — sitting in ``player``'s own graveyard — is
        castable from there via a standing permission some other permanent
        grants (Lurrus of the Dream-Den-shaped, `game/graveyard_cast.py`) —
        the open-ended sibling of `_castable_from_graveyard`'s closed
        Flashback/Escape keyword vocabulary. Cast this way, ``obj`` pays its
        own normal mana cost (`effective_cast_cost` only substitutes an
        alternative cost for a recognised graveyard keyword, so this falls
        through to the printed cost unchanged). Also true under Yawgmoth's
        Will's own player-scoped "you may cast spells from your graveyard"
        grant (`has_temporary_graveyard_play_permission`), which covers
        every card rather than one permanent's own filtered set.
        """
        return (
            graveyard_cast_grant_for(player, self.state, obj.card) is not None
            or has_temporary_graveyard_play_permission(player, self.state)
        )
    def _castable_from_library(self, player: Player, obj: GameObject) -> bool:
        """Whether the top-of-library card ``obj`` is castable from there
        right now (Oracle of Mul Daya/Glarb, Calamity's Augur-shaped — see
        `game/top_library.py`). Only ever called for ``player.library[-1]``
        (the top); a card any deeper in the library is never castable."""
        return may_cast_spell_from_top_of_library(player, self.state, obj.card)
    def _top_library_life_payment(
        self, player: Player, obj: GameObject, card: Optional["Card"] = None
    ) -> bool:
        """Whether casting ``obj`` right now pays life equal to its mana
        value instead of its mana cost (Bolas's Citadel-shaped, RULE 118) —
        true only for the actual top-of-library card, and only when some
        active grant that permits casting it also requires this
        substitution (`top_library.top_library_life_payment_required`).
        ``card`` is the face actually being cast (defaults to ``obj.card``)
        so a back/fuse-face preview checks the right mana value.
        """
        return (
            bool(player.library)
            and obj is player.library[-1]
            and top_library_life_payment_required(player, self.state, card or obj.card)
        )
