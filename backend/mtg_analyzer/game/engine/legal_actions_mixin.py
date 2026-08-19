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
from .. import combat, condition_query, continuous, durations, face_down, variants
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
from .. import mana_potential
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
from ..graveyard_cast import graveyard_cast_grant_for
from ..top_library import (
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).


class LegalActionsMixin:
    """The `legal_actions` query and the UI-facing action-descriptor builders."""

    def has_legal_targets(self, player: Player, obj: GameObject) -> bool:
        """Whether every target ``obj`` requires can be legally chosen now.

        True for a non-targeting spell (no requirements to satisfy). RULE
        601.2c / 608.2b: a targeting spell needs at least one legal target
        per non-optional requirement, computed from the live board.
        """
        requirements = requirements_with_targets(self.state, player.id, obj)
        return all_requirements_satisfiable(requirements)
    def legal_defenders_for(self, player: Player) -> list[dict[str, Any]]:
        """Who ``player``'s creatures may attack (RULE 508.1a).

        Each attacking creature is declared attacking a player, a
        planeswalker an opponent controls, or a battle (RULE 310.5). Returns
        those choices as serializable specs the UI renders as targets (and
        `declare_attackers` validates against). In a solo goldfish there are
        no opponents, so this is empty — attacks become "bare" swings with
        no target.
        """
        defenders: list[dict[str, Any]] = []
        for other in self.state.players:
            if other.id == player.id or other.has_lost:
                continue
            defenders.append({"kind": "player", "id": other.id, "label": other.name})
        for obj in self.state.battlefield:
            if obj.controller_id != player.id and obj.is_planeswalker:
                defenders.append(
                    {"kind": "planeswalker", "instance_id": obj.instance_id, "label": obj.name}
                )
        # RULE 310.8b: a battle can be attacked by any player for whom its
        # *protector* is a defending player — i.e. by everyone except the
        # protector themselves. Deliberately not filtered by controller, so
        # a Siege's own controller can attack it (310.8b calls this out
        # explicitly): a Siege is protected by an opponent, and attacking
        # your own Siege to flip it is the card's whole point.
        for obj in self.state.battlefield:
            if not obj.is_battle or obj.protector_id in (None, player.id):
                continue
            defenders.append(
                {"kind": "battle", "instance_id": obj.instance_id, "label": obj.name}
            )
        return defenders
    def _activate_action(
        self, player: Player, source: GameObject, index: int, ability: ActivatedAbility
    ) -> dict[str, Any]:
        """A ``activate_ability`` legal-action entry (RULE 602), mirroring the
        cast entry: cost label, ``{X}`` prompt, and per-requirement targets
        (marked ``locked`` when a required target has no legal option)."""
        action: dict[str, Any] = {
            "type": "activate_ability",
            "instance_id": source.instance_id,
            "ability_index": index,
            "name": source.name,
            "cost_label": ability.cost.label(),
            "description": ability.description or "",
        }
        if getattr(ability, "attach_kind", None):
            # RULE 301.5c/702.6a/702.151b: which attachment keyword this
            # ability is (equip/fortify/reconfigure) — see `ActivatedAbility.
            # attach_kind`'s docstring for why a bot wants to know.
            action["attach_kind"] = ability.attach_kind
        mana = ability.cost.mana
        remove_counters_x = ability.cost.remove_counters is not None and ability.cost.remove_counters[1] in (
            REMOVE_COUNTERS_X, REMOVE_COUNTERS_ANY,
        )
        if mana.has_variable or remove_counters_x:
            action["has_x"] = True
            action["max_x"] = self._max_x_for_activation_cost(player, source, ability.cost)
        requirements = self._ability_target_requirements(player, ability, source)
        if requirements:
            action["requires_target"] = True
            action["targets"] = requirements
            if not all_requirements_satisfiable(requirements):
                action["locked"] = True
                action["lock_reason"] = "Kein gültiges Ziel im Spiel"
        if ability.cost.tap_others:
            action["tap_cost"] = self._tap_cost_choice(player, source, ability.cost)
        if ability.cost.crew_power:
            # RULE 702.122a: which (and how many) untapped creatures pay a
            # Crew cost is the player's own choice — the `_crew_cost_choice`
            # UI shape (a power threshold, not `tap_cost`'s exact count).
            action["crew_cost"] = self._crew_cost_choice(player, source, ability.cost)
        if ability.cost.sacrifice and ability.cost.sacrifice != "self":
            # RULE 602.1: which permanent pays a "Sacrifice a <type>" cost is
            # the player's own choice — offer the pool so the UI can prompt
            # instead of the engine auto-picking (see `_sacrifice_candidate`).
            action["sacrifice_cost"] = self._sacrifice_cost_choice(player, ability.cost)
        return action
    def _land_action(
        self, obj: GameObject, face: Optional[str] = None
    ) -> dict[str, Any]:
        """A ``play_land`` legal-action entry, tagging RULE 614.1's tapped-
        entry prediction (`RulesEngine.predict_land_tapped`) as
        ``enters_tapped`` so a client — `services/bots.py`'s `GreedyBot`,
        chiefly — can prefer an untapped land when it has a choice, without
        actually playing anything to find out. ``face="back"`` previews a
        modal DFC's back face (the same face a `play_land` action carrying
        ``face="back"`` actually plays).
        """
        card = self._face_card(obj, face) if face is not None else obj.card
        action: dict[str, Any] = {
            "type": "play_land",
            "instance_id": obj.instance_id,
            "name": card.name if card is not None else obj.name,
            "enters_tapped": self.rules.predict_land_tapped(obj, card=card),
        }
        if face is not None:
            action["face"] = face
        return action
    def _cast_action(
        self,
        player: Player,
        obj: GameObject,
        face: str = "front",
        mode: Optional[Any] = None,
        entwine: bool = False,
        free: bool = False,
        alt_cost: bool = False,
    ) -> dict[str, Any]:
        """A ``cast_spell`` legal-action entry, flagging ``{X}`` and targets.

        ``free``/``alt_cost`` (MEC-15) build the RULE 601.2f-adjacent
        free-cast / RULE 118.9 alternative-cost sibling offer instead of the
        plain mana-cost one — `_offer_cast` calls this once per castable
        payment method, never more than one of the three flags set at once.
        Both skip the mana-value/{X}/Kicker/Buyback/cost-reduction fields
        below entirely (none of them apply to either alternative), and
        ``alt_cost`` surfaces its own `ActivationCost.label()` the same way
        ``additional_cost_label`` does.

        ``has_x`` tells the UI to prompt for a value; ``max_x`` is the
        highest it can offer up front (still re-validated server-side by
        `cast_spell`, which re-checks payability for the chosen ``x``).

        For a *targeting* spell (RULE 115) it reports ``requires_target`` and
        the per-requirement ``targets`` (the legal choices on the current
        board). When no legal target exists the entry is marked ``locked``
        with a reason — the UI renders it with a 🔒 and can't cast it, which
        is the offer-time face of RULE 601.2c.

        ``face="back"``/``"fuse"`` build this for a second castable face
        (see `_face_card`): ``obj`` is temporarily rebound onto that face
        (so targeting/cost read its *own* abilities, not the front's) then
        restored before returning — a pure preview, unlike `cast_spell`'s
        real (and rollback-on-failure) switch.

        ``mode`` (an index into ``obj.spell_modes``, or ``"both"``) tags the
        entry with that mode (RULE 700.2 — see `_modal_cast_actions`, which
        calls this once per mode instead of once per ``obj``) and computes
        ``targets``/``locked`` under that mode's own effects only.
        """
        if face in ("back", "fuse"):
            alt = obj.card.back_face() if face == "back" else obj.card.fuse_face()
            snapshot = self.rules.snapshot_face(obj)
            self.rules.switch_to_face(obj, alt)
            try:
                action = self._cast_action(player, obj)
            finally:
                self.rules.restore_face(obj, snapshot)
            action["face"] = face
            return action
        action = {"type": "cast_spell", "instance_id": obj.instance_id, "name": obj.name}
        if mode is not None:
            action["mode"] = mode
            action["mode_description"] = self._mode_description(obj, mode)
        if free or alt_cost:
            # RULE 601.2f-adjacent free cast / RULE 118.9 alternative cost
            # (MEC-15) — a wholly different payment method from the printed
            # mana cost, so none of the mana-value/{X}/Kicker/Buyback/cost-
            # reduction/additional-cost fields below apply; only the
            # target-requirement tail (below the entwine/mana block) is
            # still relevant, since targets don't depend on how the spell
            # was paid for.
            if free:
                action["free"] = True
            else:
                action["alt_cost"] = True
                alt_cast_cost = getattr(obj, "alt_cast_cost", None)
                if alt_cast_cost is not None:
                    action["alt_cost_label"] = alt_cast_cost.label()
        else:
            # RULE 702.42a: the Entwine offer is the same "both modes" action as
            # RULE 700.2e's, but priced — so it carries its cost and locks when
            # that cost can't be paid, which the free ``or_both`` offer never does.
            if entwine:
                entwine_cost = self._entwine_cost(obj)
                action["entwine"] = True
                action["entwine_cost"] = entwine_cost.raw if entwine_cost is not None else ""
                if not self.can_cast(player, obj, entwine=True):
                    action["locked"] = True
                    action["lock_reason"] = "Verflechten-Kosten nicht bezahlbar"
            cost = self.rules.mana_cost_of(obj.card)
            # RULE 202.3: the printed mana value, always present — a client
            # ordering offers by cost (`services/bots.py`' cheapest-first line)
            # otherwise has nowhere to read it from, since `GameObject.to_dict`
            # carries board state rather than printed characteristics.
            action["mana_value"] = cost.converted_mana_cost
            if cost.has_variable:
                action["has_x"] = True
                action["max_x"] = self.max_affordable_x(player, obj)

            # RULE 702.33: surface Kicker/Multikicker so the UI can prompt for
            # how many times to pay it, the same "has_x/max_x" shape as {X}.
            kicker_cost = self._kicker_cost(obj)
            if kicker_cost is not None:
                kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
                action["has_kicker"] = True
                action["kicker_cost"] = kicker_cost.raw
                action["kicker_multi"] = bool(kicker_param.get("multi"))
                action["max_kicker"] = self.max_affordable_kicker(player, obj)
                if kicker_cost.has_variable:
                    # PAR-7: Kicker's own {X} (Emblazoned Golem) — the same
                    # "has_x/max_x" shape as the spell's own {X} above, but for
                    # the value announced *inside* Kicker's cost.
                    action["kicker_has_x"] = True
                    action["kicker_max_x"] = self.max_affordable_kicker_x(player, obj)

            # RULE 702.27: surface Buyback so the UI can offer a "pay to buy
            # back" toggle, locked when its own cost isn't affordable.
            buyback_cost = self._buyback_cost(obj)
            if buyback_cost is not None:
                action["has_buyback"] = True
                action["buyback_cost"] = buyback_cost.raw
                action["buyback_affordable"] = self.can_cast(player, obj, buyback=True)

            # RULE 702.34/702.138: a graveyard cast is by definition via
            # Flashback/Escape's own alternative cost, not the printed one — tag
            # it so the UI can label the offer distinctly from a normal cast.
            graveyard_keyword = self._graveyard_cast_keyword(obj) if obj in player.graveyard else None
            if graveyard_keyword is not None:
                action["cast_from_graveyard"] = graveyard_keyword
                if graveyard_keyword == "escape":
                    escape_cost = self._escape_cost(obj)
                    if escape_cost is not None and escape_cost.exile_from_graveyard:
                        action["escape_exile_count"] = escape_cost.exile_from_graveyard

            # Static cost adjustment (RULE 601.2f): surface base vs. reduced so the
            # UI can show "was {3}, now {1}" and the static-effects panel can
            # attribute it. Only attached when something actually changes the cost.
            reduction, contributors = continuous.cost_reduction_for(self.state, player, obj)
            self_reduction, self_contributors = continuous.self_cost_reduction_for(obj, self.state)
            reduction += self_reduction
            contributors = contributors + self_contributors
            floor = continuous.cost_floor_for(self.state, player, obj)
            tax = self.commander_tax(player, obj)
            if (reduction or tax or graveyard_keyword or floor > cost.converted_mana_cost) and cost.raw:
                action["base_cost"] = cost.raw
                action["effective_cost"] = self.effective_cast_cost(player, obj).raw
                if reduction:
                    action["cost_reduction"] = contributors
                if tax:
                    action["commander_tax"] = tax

            # RULE 601.2b: surface the additional cast cost (if any) so the UI
            # can show it alongside the mana cost, and lock the offer when its
            # non-X portion (sacrifice/discard) isn't payable — the same
            # "offer-time face" treatment missing targets get above. A pending
            # "pay X life" isn't locked here since X isn't chosen until cast.
            additional_cost = getattr(obj, "additional_cast_cost", None)
            if additional_cost is not None and not additional_cost.is_free:
                action["additional_cost_label"] = additional_cost.label()
                if not self._can_pay_additional_cast_cost(player, obj, additional_cost, x=0):
                    action["locked"] = True
                    action["lock_reason"] = "Zusätzliche Kosten nicht bezahlbar"

        with self._mode_effects_applied(obj, mode):
            requirements = requirements_with_targets(self.state, player.id, obj)
        if requirements:
            action["requires_target"] = True
            action["targets"] = requirements
            if not all_requirements_satisfiable(requirements):
                action["locked"] = True
                action["lock_reason"] = "Kein gültiges Ziel im Spiel"
        return action
    def _modal_cast_actions(self, player: Player, obj: GameObject) -> list[dict[str, Any]]:
        """One ``cast_spell`` action per mode of a modal spell (RULE 700.2).

        For the ordinary "choose one" case (``spell_modes_choose == 1``):
        one action per single mode, plus a combined "both" action when
        ``obj.spell_modes_or_both`` (RULE 700.2e) or, priced and lockable,
        when the block carries an Entwine cost (RULE 702.42a) — the same
        "an offer per option" treatment `legal_actions` already gives an
        MDFC's two faces.
        For "choose *N*" (``N>=2`` — Kolaghan's Command/Austere Command
        -shaped): one action per legal *combination* of ``N`` modes
        (``itertools.combinations``), each tagged with a list of indices
        instead of a bare int (see `_effects_for_mode`). For "choose *N* or
        more" (``obj.spell_modes_at_least`` — Farewell-shaped): one action
        per combination of *every* size from ``N`` to all modes.
        """
        modes = list(getattr(obj, "spell_modes", None) or [])
        choose = getattr(obj, "spell_modes_choose", 1)
        at_least = getattr(obj, "spell_modes_at_least", False)
        if choose <= 1 and not at_least:
            actions = [self._cast_action(player, obj, mode=i) for i in range(len(modes))]
            if getattr(obj, "spell_modes_or_both", False) and len(modes) == 2:
                actions.append(self._cast_action(player, obj, mode="both"))
            elif self._entwine_cost(obj) is not None:
                # RULE 702.42a: the same combined offer, but sold rather
                # than given — see `_cast_action`'s ``entwine`` branch.
                actions.append(self._cast_action(player, obj, mode="both", entwine=True))
            return actions
        sizes = range(choose, len(modes) + 1) if at_least else [choose]
        return [
            self._cast_action(player, obj, mode=list(combo))
            for size in sizes
            for combo in itertools.combinations(range(len(modes)), size)
        ]
    def _plain_castable_now_or_via_potential(
        self, player: Player, obj: GameObject, face: str = "front",
    ) -> bool:
        """Whether ``obj`` is castable for its own printed mana cost right
        now — either already payable from the real pool (`can_cast`,
        unchanged), or legal except for mana and payable by tapping plain
        untapped sources (`game/mana_potential.py`, never a sacrifice- or
        hand-exile-cost one): clicking "Zaubern" then silently auto-taps
        first (`_auto_tap_for_cast_if_needed`) instead of failing. A
        read-only preview — never taps anything itself. Works for
        ``face="face_down"`` too (MEC-13, fixed 2026-08-04) — RULE
        702.37a's flat {3} morph/disguise cost, which `effective_cast_cost`
        already resolves correctly via `_face_card` on its own, without
        needing ``obj`` to already be turned face down.

        The *mana-cost-specific* half of `_castable_now_or_via_potential`
        (MEC-15 split it out): `_offer_cast` also calls this directly to
        decide whether the plain-cost `cast_spell` offer belongs alongside
        a free/alt-cost one, since the combined check answers only "offer
        *something*", not "offer *this specific* one".
        """
        if self.can_cast(player, obj, face=face):
            return True
        if not self.can_cast(player, obj, face=face, assume_mana_available=True):
            return False
        cost = self.effective_cast_cost(player, obj, face=face)
        return mana_potential.is_castable_via_potential(self, player, cost)
    def _castable_now_or_via_potential(
        self, player: Player, obj: GameObject, face: str = "front",
    ) -> bool:
        """Whether a `cast_spell` action should be offered for ``obj`` right
        now — the plain mana-cost path (`_plain_castable_now_or_via_
        potential`), or, since MEC-15, a free-cast permission (`free_cast_
        condition`, Deadly Rollick-shaped) or an alternative cost
        (`alt_cast_cost`, Force of Will/Daze-shaped) reaching castability
        with zero mana in the pool at all, neither of which the mana-
        potential probe (only ever "payable by tapping untapped lands")
        could ever answer.
        """
        if self._plain_castable_now_or_via_potential(player, obj, face=face):
            return True
        if getattr(obj, "free_cast_condition", None) is not None and self.can_cast(
            player, obj, face=face, free=True
        ):
            return True
        if getattr(obj, "alt_cast_cost", None) is not None and self.can_cast(
            player, obj, face=face, alt_cost=True
        ):
            return True
        return False
    def _activatable_now_or_via_potential(
        self, player: Player, source: GameObject, ability: ActivatedAbility,
    ) -> bool:
        """`_castable_now_or_via_potential`'s counterpart for an ordinary
        activated ability (RULE 602) — offered once it's either really
        payable, or legal except for mana and payable via plain untapped
        sources (clicking it then silently auto-taps first, `Activation
        Mixin._auto_tap_for_activation_if_needed`)."""
        if self.can_activate(player, source, ability):
            return True
        if not self.can_activate(player, source, ability, assume_mana_available=True):
            return False
        cost = ability.cost
        mana = cost.mana.with_x(0) if cost.mana.has_variable else cost.mana
        mana = self._reduced_activation_mana(source, mana, cost)
        if cost.spend_only_chosen_color:
            locked = self._chosen_color_locked_cost(source, mana)
            if locked is None:
                return False
            mana = locked
        return mana_potential.is_castable_via_potential(self, player, mana)
    def _offer_cast(self, actions: list[dict[str, Any]], player: Player, obj: GameObject) -> None:
        """Append the right cast offer(s) for ``obj``: one `_cast_action`
        entry, or one per mode via `_modal_cast_actions` if it's modal (RULE
        700.2). The common tail of every per-zone cast-offer loop in
        `legal_actions` below (hand/command/exile/graveyard/library-top),
        which otherwise repeated this identically five times.

        MEC-15: a free-cast permission or an alternative cost is a *second*,
        independent payment method — offered as its own `cast_spell` entry
        (``free``/``alt_cost`` flagged) alongside the plain mana-cost one,
        never in place of it, and each only when that specific method is
        actually payable right now (`_castable_now_or_via_potential`, this
        method's own caller, only proves *some* method is — see its
        docstring). A modal spell keeps its existing per-mode offers only;
        no printed card needs a modal free/alt-cost combination yet.
        """
        if getattr(obj, "spell_modes", None):
            actions.extend(self._modal_cast_actions(player, obj))
            return
        if self._plain_castable_now_or_via_potential(player, obj):
            actions.append(self._cast_action(player, obj))
        if getattr(obj, "free_cast_condition", None) is not None and self.can_cast(player, obj, free=True):
            actions.append(self._cast_action(player, obj, free=True))
        if getattr(obj, "alt_cast_cost", None) is not None and self.can_cast(player, obj, alt_cost=True):
            actions.append(self._cast_action(player, obj, alt_cost=True))

    def legal_actions(self, player: Player) -> list[dict[str, Any]]:
        """Every action ``player`` may legally take in the current state.

        The single source of truth the UI/bot should consult instead of
        letting any card be "played" with no rule checks (docs/02 R4.3).
        """
        actions: list[dict[str, Any]] = [{"type": "pass_priority"}]
        if self.state.game_over or player.has_lost:
            return actions

        for obj in list(player.hand):
            if self.can_play_land(player, obj):
                actions.append(self._land_action(obj))
            if self._castable_now_or_via_potential(player, obj):
                self._offer_cast(actions, player, obj)
            # A second castable face offers its own action(s) too — a modal
            # DFC's back (RULE 712.10), a split card's other half (RULE
            # 709.3), or an Adventure's instant/sorcery half (RULE 715.2b) —
            # a second, independently-gated action for the same hand card.
            if obj.card.back_face() is not None:
                if self.can_play_land(player, obj, face="back"):
                    actions.append(self._land_action(obj, face="back"))
                if self._castable_now_or_via_potential(player, obj, face="back"):
                    actions.append(self._cast_action(player, obj, face="back"))
            # A split card with Fuse offers casting both halves as one spell
            # too (RULE 709.4), for their combined cost.
            if obj.card.fuse_face() is not None and self._castable_now_or_via_potential(player, obj, face="fuse"):
                actions.append(self._cast_action(player, obj, face="fuse"))
            # RULE 702.37a/702.168a: a card with morph/disguise may instead be
            # cast **face down** for {3} — a separate offer for the same hand
            # card, like the second-face ones above, and the only way a
            # face-down spell ever reaches the stack. MEC-13: potential-
            # aware like every other offer above (an untapped-lands-only {3}
            # is exactly the common case) — `cast_spell`'s own `face_down`
            # branch now auto-taps for it too, so the click this offers
            # actually succeeds.
            if face_down.cast_face_down_kind(obj) and self._castable_now_or_via_potential(
                player, obj, face="face_down"
            ):
                actions.append(
                    {
                        "type": "cast_spell",
                        "instance_id": obj.instance_id,
                        "name": obj.name,
                        "face": "face_down",
                        "cost_label": face_down.FACE_DOWN_CAST_COST,
                        "face_down_kind": face_down.cast_face_down_kind(obj),
                    }
                )

        for obj in list(player.command):
            if self._castable_now_or_via_potential(player, obj):
                self._offer_cast(actions, player, obj)
            # A modal-DFC commander (RULE 712.10) gets its *castable* back
            # face offered from the command zone too — previously only the
            # hand-cast loop above did this, so such a commander could only
            # ever be cast as its front face. `can_cast`/`_cast_action`
            # already thread `face="back"` through generically (they're the
            # same calls the hand loop makes); `commander_tax` itself
            # doesn't care which face is being cast, only that `obj` is in
            # `player.command`. Unlike the hand loop, there's no
            # `can_play_land(face="back")` branch here: RULE 903.6 only
            # lets a commander be *cast* from the command zone — playing a
            # land isn't casting a spell, so a land back face is reachable
            # this way only once the card is actually in hand.
            if obj.card.back_face() is not None and self._castable_now_or_via_potential(player, obj, face="back"):
                actions.append(self._cast_action(player, obj, face="back"))

        for obj in list(player.exile):
            # RULE 715.3d / 722.3c: an Adventure creature exiled by its own
            # spell half, or a prepared copy, may be cast from exile — or
            # RULE 601.3b analogue's temporary "you may play/cast this"
            # permission (Light Up the Stage/Ragavan/Mnemonic Betrayal/
            # Ephemerate's Rebound-shaped, `_has_temp_play_permission`), or
            # its standing, never-turn-swept sibling (Lukka, Coppercoat
            # Outcast/Soul Partition-shaped, `_has_conditional_exile_
            # permission` — MEC-12 found this one missing here too, the
            # same "never actually offered" gap the comment below already
            # documents for the temp permission).
            # Previously missing here entirely — `can_cast`/`cast_spell`
            # already supported this zone/permission combination, but
            # nothing ever surfaced it as an actual offered action, so no
            # caller (UI or otherwise) could ever actually cast one of
            # these; found end-to-end testing Ephemerate's Rebound.
            castable = (
                self._castable_from_exile(obj)
                or self._has_temp_play_permission(obj, player)
                or self._has_conditional_exile_permission(obj, player)
            )
            if castable and self._castable_now_or_via_potential(player, obj):
                self._offer_cast(actions, player, obj)
            if self._has_temp_play_permission(obj, player) and self.can_play_land(player, obj):
                actions.append(self._land_action(obj))

        for obj in list(player.graveyard):
            # RULE 702.34 / 702.138: Flashback/Escape let a card be cast
            # from the graveyard for an alternative cost — or some other
            # permanent may grant a standing permission instead (Lurrus of
            # the Dream-Den-shaped, `_graveyard_cast_permission`).
            castable = (
                self._castable_from_graveyard(obj)
                or self._graveyard_cast_permission(player, obj)
            )
            if castable and self._castable_now_or_via_potential(player, obj):
                self._offer_cast(actions, player, obj)
            # Yawgmoth's Will's own first clause also covers lands, unlike
            # every other graveyard-cast permission source — `can_play_land`
            # already gates on `card.is_land`, so this is cheap to try for
            # every graveyard card.
            if self.can_play_land(player, obj):
                actions.append(self._land_action(obj))

        if player.library:
            # Oracle of Mul Daya/Glarb, Calamity's Augur-shaped: a permanent
            # may grant playing lands and/or casting spells straight off the
            # top of the library — see `game/top_library.py`. Only the top
            # card itself is ever offered.
            top = player.library[-1]
            if self.can_play_land(player, top):
                actions.append(self._land_action(top))
            if self._castable_now_or_via_potential(player, top):
                self._offer_cast(actions, player, top)

        if (
            player is self.state.active_player
            and self.state.current_step == "declare_attackers"
        ):
            # The defenders are the same for every attacker this combat, so
            # compute them once and attach to each attack offer. The UI reads
            # the count to decide a one-step declaration (0/1 defender) vs. a
            # two-step "pick a defender" choice (RULE 508.1a).
            defenders = self.legal_defenders_for(player)
            for obj in self.state.permanents_controlled_by(player.id):
                if self._can_attack(player, obj):
                    actions.append(
                        {
                            "type": "attack",
                            "instance_id": obj.instance_id,
                            "name": obj.name,
                            "legal_defenders": defenders,
                            # RULE 702.19a: whether the client may offer an
                            # "exert as it attacks" checkbox alongside this
                            # declaration (`GameEngine.declare_attackers`'s
                            # own ``exert`` flag).
                            "can_exert": combat.has(obj, "exert"),
                        }
                    )

        if (
            player is not self.state.active_player
            and self.state.current_step == "declare_blockers"
        ):
            # RULE 509.1a, the mirror of the attack offers above: one entry
            # per creature this *defending* player could block with, carrying
            # the attackers it may legally be assigned to (`can_block` covers
            # evasion, protection and the RULE 508/509 restriction family).
            # A creature already blocking is left out — `declare_blockers` is
            # additive, but re-offering it would let the UI double-assign it.
            attackers = [o for o in self.state.battlefield if o.attacking]
            for obj in self.state.permanents_controlled_by(player.id):
                if combat.blocking_attacker_ids(obj):
                    continue
                blockable = [a for a in attackers if self.can_block(player, obj, a)]
                if not blockable:
                    continue
                actions.append(
                    {
                        "type": "declare_blockers",
                        "instance_id": obj.instance_id,
                        "name": obj.name,
                        "player_id": player.id,
                        # The UI collects a whole block (every blocker for
                        # every attacker) and submits it as one action, so
                        # RULE 702.111b menace and its "…except by N or more
                        # creatures" siblings — validated across the complete
                        # assignment in `declare_blockers` — can be satisfied.
                        "legal_attackers": [
                            {"instance_id": a.instance_id, "name": a.name} for a in blockable
                        ],
                    }
                )

        for source in self.state.permanents_controlled_by(player.id):
            # One offer per mana ability the source has (almost always just
            # one) — `_can_pay_activation_cost` covers tap/summoning-sickness
            # *and* any extra cost component (Selvala's {G}, Gnarlroot
            # Trapper's life payment, Birchlore Rangers' "tap two other
            # Elves" — RULE 602.1), so a source that can't tap itself can
            # still offer an ability that doesn't need to.
            for ability_index, ability in enumerate(mana_abilities_for(source, state=self.state)):
                if not ability.options:
                    continue
                # Existence-only check here (no chosen tap_others yet — the
                # player picks those in the UI *after* choosing to activate,
                # same as a target); `tap_for_mana` re-validates the actual
                # choice at payment time.
                if not self._can_pay_activation_cost(
                    player, source, ability.cost, x=0, is_mana_ability=True
                ):
                    continue
                action = {
                    "type": "tap_for_mana",
                    "instance_id": source.instance_id,
                    "name": source.name,
                    "ability_index": ability_index,
                    "cost_label": ability.cost.label(),
                    # Each option is a distinct choice (dual-land "W or U");
                    # the UI shows one button per option so the player picks
                    # the colour.
                    "options": [
                        {"index": i, "mana": opt, "label": option_label(opt)}
                        for i, opt in enumerate(ability.options)
                    ],
                }
                if ability.any_combination:
                    # RULE 605.1a "any combination of colours" (Flamebraider/
                    # Gwenna/Smokebraider/Selvala) — the player may split
                    # this total across colours (`color_split`) instead of
                    # picking one of the single-colour ``options`` above;
                    # `gameBoardView.js`'s `colorSplitHtml` offers both: the
                    # single-colour buttons as a still-legal fallback, plus
                    # this split builder.
                    action["any_combination"] = True
                    action["combination_total"] = sum(ability.options[0].values())
                if ability.cost.tap_others:
                    action["tap_cost"] = self._tap_cost_choice(player, source, ability.cost)
                if ability.cost.sacrifice and ability.cost.sacrifice != "self":
                    # RULE 602.1: same cost choice as `_activate_action`'s,
                    # for a mana ability whose cost is a sacrifice (Ashnod's
                    # Altar-shaped).
                    action["sacrifice_cost"] = self._sacrifice_cost_choice(player, ability.cost)
                actions.append(action)

        for source in list(player.hand):
            # RULE 605.1a "Exile this card from your hand: Add …" (Elvish/
            # Simian Spirit Guide) — the hand-zone counterpart of the
            # battlefield loop above; every real card's cost is just the
            # exile itself, so (unlike `tap_for_mana`'s offer) there's no
            # extra payability check here.
            for ability_index, ability in enumerate(hand_mana_abilities_for(source, state=self.state)):
                if not ability.options:
                    continue
                action = {
                    "type": "activate_hand_mana",
                    "instance_id": source.instance_id,
                    "name": source.name,
                    "ability_index": ability_index,
                    "cost_label": ability.cost.label(),
                    "options": [
                        {"index": i, "mana": opt, "label": option_label(opt)}
                        for i, opt in enumerate(ability.options)
                    ],
                }
                if ability.any_combination:
                    action["any_combination"] = True
                    action["combination_total"] = sum(ability.options[0].values())
                actions.append(action)

        if self.can_roll_planar_die(player):
            # RULE 901.6: rolling the planar die is a special action too, and
            # only ever offered on its roller's own turn.
            actions.append(
                {
                    "type": "roll_planar_die",
                    "cost_label": self.planar_die_cost(player).raw or "{0}",
                    "rolls_this_turn": self.state.planar_die_rolls_this_turn.get(player.id, 0),
                }
            )

        for obj in self.state.permanents_controlled_by(player.id):
            # RULE 116.2b: turning a face-down permanent face up is a
            # *special action* — no stack, no timing gate beyond holding
            # priority — so it's offered here for every face-down permanent
            # this player controls with a payable route (RULE 702.37e/
            # 702.168d/701.40b/701.58b; a manifested noncreature card offers
            # none, RULE 701.40g).
            actions.extend(self.turn_face_up_actions(player, obj))

        for obj in self.state.permanents_controlled_by(player.id):
            # RULE 502.1 "you may choose not to untap ~ during your untap
            # step" (Rubinia Soulsinger/Hivis of the Scale/The Pandorica-
            # shaped) — a sticky preference toggle (see `GameObject.
            # skip_untap`'s docstring for why: the untap step has no mid-step
            # pause to ask fresh every turn), so it's offered any time this
            # player controls the permanent, not just during untap.
            if continuous.has_optional_no_untap_permission(self.state, obj):
                actions.append(
                    {
                        "type": "set_skip_untap",
                        "instance_id": obj.instance_id,
                        "name": obj.name,
                        "skip_untap": obj.skip_untap,
                    }
                )

        # Activated abilities (RULE 602) bound onto permanents this player
        # controls — one offer per payable ability (a fetch land's
        # "{T}, Sacrifice: …", a mana rock, a pinger, …). Includes any
        # layer-6-granted ones (Umbral Mantle/Squirrel Nest-shaped) so the
        # index offered here lines up with `activate_ability`'s own combined
        # list — both must enumerate the identical concatenation.
        for source in self.state.permanents_controlled_by(player.id):
            for index, ability in enumerate(source.activated_abilities + source.granted_activated_abilities):
                if self._activatable_now_or_via_potential(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))

        # RULE 602.2b: an ability "any player may activate" (Mercenaries)
        # must be offered to non-controllers too, not just discoverable by a
        # raw can_activate()/activate_ability() call — legal_actions() is the
        # single source of truth the UI/bots consult.
        for source in self.state.battlefield:
            if source.controller_id == player.id or source.phased_out:
                continue
            for index, ability in enumerate(source.activated_abilities + source.granted_activated_abilities):
                if not getattr(ability.cost, "any_player_may_activate", False):
                    continue
                if self._activatable_now_or_via_potential(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))

        # RULE 114.4: an emblem's own activated ability (MEC-8) — offered off
        # `player.emblems` the same way the battlefield loop above offers a
        # permanent's, since `can_activate`/`_activate_action` already accept
        # an `Emblem` source (`models/emblem.py`).
        for emblem in player.emblems:
            for index, ability in enumerate(emblem.activated_abilities):
                if self._activatable_now_or_via_potential(player, emblem, ability):
                    actions.append(self._activate_action(player, emblem, index, ability))

        # Channel (RULE 702.29)/Cycling (RULE 702.28): a hand-zone card's own
        # "Discard this card: <effect>" activated ability — unlike the
        # battlefield loop above, discovered off `player.hand`, since the
        # card itself (not a permanent) is the ability's source. Combined
        # with `granted_activated_abilities` (PAR-8's "Each card in your
        # hand has cycling `<cost>`.") the same way the battlefield loop
        # combines the two lists — `activate_ability` always indexes into
        # that same concatenation regardless of zone.
        for source in list(player.hand):
            combined = source.activated_abilities + source.granted_activated_abilities
            for index, ability in enumerate(combined):
                if (
                    ability.cost.discard_self or ability.cost.hand_zone
                ) and self.can_activate(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))

        # PAR-10: "Return this card from your graveyard to the
        # battlefield[, tapped]." — a graveyard-zone card's own ability,
        # the same "discovered off the owning zone, not the battlefield"
        # shape as Cycling above.
        for source in list(player.graveyard):
            combined = source.activated_abilities + source.granted_activated_abilities
            for index, ability in enumerate(combined):
                if ability.cost.graveyard_zone and self.can_activate(player, source, ability):
                    actions.append(self._activate_action(player, source, index, ability))
        return actions
