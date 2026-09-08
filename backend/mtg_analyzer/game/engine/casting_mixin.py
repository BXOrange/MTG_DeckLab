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
from .. import (
    ability_catalogue, combat, condition_query, continuous, durations, face_down, mana_potential, variants,
)
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
from ..graveyard_cast import graveyard_cast_grant_for
from ..top_library import (
    may_cast_flash_from_top_of_library,
    may_cast_spell_from_top_of_library,
    may_play_land_from_top_of_library,
    top_library_life_payment_required,
)

#: Maximum hand size enforced at cleanup (RULE 402.2 / 514.1).


class CastingMixin:
    """Casting a spell: legality, alternate costs, cost calculation, stack placement."""

    def _in_main_phase(self) -> bool:
        return self.state.current_step in ("main1", "main2")
    def _face_card(self, obj: GameObject, face: str = "front") -> Optional[Card]:
        """The `Card` ``face`` ("front"/"back"/"fuse") refers to for ``obj``.

        "front" is always ``obj.card`` as it currently stands — which also
        makes this work after a second face has already been switched to,
        since at that point "the current face" *is* the back. "back" is
        whatever `Card.back_face` captured — a modal DFC's back (RULE
        712.10), a split card's other half (RULE 709.3), or an Adventure's
        instant/sorcery half (RULE 715.2b) — or None if nothing was
        captured for this card. "fuse" is a split card's synthetic combined
        cast (RULE 709.4, `Card.fuse_face`), or None without Fuse. Read-only:
        never mutates ``obj``, so callers can use it to preview an un-chosen
        face (e.g. for `legal_actions`) without committing to it.
        """
        if face == "back":
            return obj.card.back_face()
        if face == "fuse":
            return obj.card.fuse_face()
        if face == "face_down":
            # RULE 702.37a/702.168a: casting a card face down is a fourth
            # "face" — the synthetic 2/2 with no text and a flat {3}
            # alternative cost (`game/face_down.py`). Only a card whose own
            # morph/disguise keyword grants that permission has one, so
            # ``None`` here is exactly the RULE 702.37d "you can't normally
            # cast a card face down" default, and `can_cast` fails closed.
            kind = face_down.cast_face_down_kind(obj)
            return face_down.face_down_card(kind) if kind else None
        return obj.card
    def _flashback_cost(self, obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.34b: ``obj``'s Flashback cost as a `ManaCost`, or
        ``None`` if it carries no Flashback keyword (or one with no parsed
        cost) and no *granted* one either.

        A granted flashback (MEC-24 — "target instant or sorcery card in
        your graveyard gains flashback [until end of turn]", Recoup/
        Snapcaster Mage-shaped) has no printed keyword to read; its cost
        comes from `GameState.temp_flashback_grants` instead, the same
        "no printed text, assemble the cost from the grant" split
        `_escape_cost`'s own `continuous.granted_escape_for` branch uses.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("flashback")
        if param and param.get("cost"):
            return ManaCost.parse(str(param["cost"]))
        granted = self.state.temp_flashback_grants.get(obj.instance_id)
        if granted is not None:
            return ManaCost.parse(str(granted))
        return None
    @staticmethod
    def _foretell_cost(obj: GameObject) -> Optional["ManaCost"]:
        """Return the printed Foretell cost, if present."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("foretell")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))

    def _can_cast_foretold(self, player: Player, obj: GameObject) -> bool:
        """RULE 702.143d: cast a foretold card from exile on a later turn."""
        return (
            obj in player.exile and bool(getattr(obj, "foretold", False))
            and self._foretell_cost(obj) is not None
            and self.state.internal_turn.number > int(getattr(obj, "foretold_turn", -1) or -1)
        )

    def can_foretell(self, player: Player, obj: GameObject, *, assume_mana_available: bool = False) -> bool:
        """RULE 702.143a's hand-zone special action, including its {2}."""
        if obj not in player.hand or player is not self.state.active_player:
            return False
        if self._foretell_cost(obj) is None:
            return False
        return assume_mana_available or player.mana_pool.can_pay(ManaCost.parse("{2}"), life_available=player.life)

    @staticmethod
    def _suspend_params(obj: GameObject) -> Optional[dict[str, Any]]:
        """Return the printed Suspend parameters, if this card has them.

        RULE 702.62a's first ability is a hand-zone special action. A
        Suspend granted later (for example by Delay) deliberately does not
        create that action: it has no printed ``N—cost`` to pay.
        """
        params = (getattr(obj, "parametric_keywords", None) or {}).get("suspend")
        if not isinstance(params, dict) or params.get("cost") is None:
            return None
        try:
            if int(params.get("n", 0)) < 0:
                return None
        except (TypeError, ValueError):
            return None
        return params

    def can_suspend(self, player: Player, obj: GameObject, *, assume_mana_available: bool = False) -> bool:
        """RULE 702.62a: may ``player`` suspend this hand card now?"""
        params = self._suspend_params(obj)
        if obj not in player.hand or player is not self.state.active_player or params is None:
            return False
        # Suspending is permitted only at a time the card could be cast.
        # ``can_cast`` cannot be reused because it also requires payment of
        # the normal mana cost, which is precisely what Suspend replaces.
        card = obj.card
        sorcery_speed = not (card.is_instant or combat.has(obj, "flash"))
        if sorcery_speed and (not self._in_main_phase() or bool(self.state.stack)):
            return False
        cost = ManaCost.parse(str(params["cost"]))
        return assume_mana_available or player.mana_pool.can_pay(cost, life_available=player.life)

    def suspend(self, player: Player, obj: GameObject) -> None:
        """Pay Suspend's alternate cost and exile the card with time counters.

        This is a special action, so it never uses the stack (RULE 116.2f).
        The existing upkeep trigger scans exile for the printed keyword plus
        these counters; no separate marker is necessary for a printed
        Suspend card.
        """
        if not self.can_suspend(player, obj):
            if self.can_suspend(player, obj, assume_mana_available=True):
                try:
                    params = self._suspend_params(obj)
                    assert params is not None
                    self.auto_tap_for(player, cost=ManaCost.parse(str(params["cost"])))
                except ValueError:
                    pass
        if not self.can_suspend(player, obj):
            raise ValueError(f"{player.id} cannot suspend {obj.name} now")
        params = self._suspend_params(obj)
        assert params is not None
        player.mana_pool.pay(ManaCost.parse(str(params["cost"])), life_available=player.life)
        self.rules.exile(obj)
        obj.add_counters("time", int(params["n"]))

    def foretell(self, player: Player, obj: GameObject) -> None:
        """Pay {2}, then exile a hand card face down (no stack involved)."""
        if not self.can_foretell(player, obj):
            if self.can_foretell(player, obj, assume_mana_available=True):
                try:
                    self.auto_tap_for(player, cost=ManaCost.parse("{2}"))
                except ValueError:
                    pass
        if not self.can_foretell(player, obj):
            raise ValueError(f"{player.id} cannot foretell {obj.name} now")
        player.mana_pool.pay(ManaCost.parse("{2}"), life_available=player.life)
        self.rules.exile(obj)
        obj.face_down_in_exile = True
        obj.foretold = True
        obj.foretold_turn = self.state.internal_turn.number
    @staticmethod
    def _mutate_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.140b: ``obj``'s Mutate cost as a `ManaCost`, or ``None``
        if it carries no Mutate keyword (or one with no parsed cost) — the
        same shape `_buyback_cost`/`_flashback_cost` take for their own
        keywords' costs."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("mutate")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
    @staticmethod
    def _evoke_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.74b: ``obj``'s Evoke cost as a `ManaCost`, or ``None``
        if it carries no Evoke keyword (or one with no parsed cost) — the
        same shape `_mutate_cost`/`_escalate_cost` take for their own
        cost-bearing keywords. Structurally closest to Mutate (a hand-cast
        substitution with its own post-resolution behaviour), not
        Flashback/Escape (both graveyard-only) — see `_finish` in
        `game/rules/casting_mixin.py`'s `_resolve_permanent_spell` for the
        "sacrificed when it enters" half (MEC-42, Ashling, the Limitless's
        own granted evoke also reads this).
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("evoke")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))

    @staticmethod
    def _evoke_exile_hand_color(obj: GameObject) -> Optional[str]:
        """The coloured-card alternative Evoke payment, if printed."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("evoke") or {}
        color = param.get("exile_hand_card_color")
        return str(color) if color in {"W", "U", "B", "R", "G"} else None

    def _has_evoke(self, obj: GameObject) -> bool:
        return (
            self._evoke_cost(obj) is not None
            or self._evoke_exile_hand_color(obj) is not None
            or continuous.granted_evoke_cost_for(self.state, obj) is not None
        )
    @staticmethod
    def _entwine_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.42a: ``obj``'s Entwine cost as a `ManaCost`, or ``None``
        if it isn't a modal spell carrying one.

        Entwine is an *additional* cost that changes what the modal header
        means — pay it and "choose one" becomes "choose all" — so unlike
        Kicker/Buyback it isn't stored as a parametric keyword on the card
        but on the modal block itself (`effect_binder._attach_modes`), next
        to the modes it upgrades.
        """
        raw = getattr(obj, "spell_modes_entwine", None)
        if not raw:
            return None
        return ManaCost.parse(str(raw))
    @staticmethod
    def _escalate_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.120: ``obj``'s Escalate cost as a `ManaCost`, or ``None``
        if it carries no Escalate keyword (or one with no parsed cost) —
        the same shape `_buyback_cost`/`_mutate_cost` take for their own
        cost-bearing keywords. Already a plain parsed parametric keyword
        (`parser/oracle/catalogue/keywords.py`'s cost-bearing table) —
        Escalate needed no parser handler of its own (MEC-31): only
        `_modal_extra_cost` below, which reads this once per mode chosen
        *beyond the first*, was missing.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("escalate")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
    def _modal_extra_cost(self, obj: GameObject, mode: Any) -> Optional["ManaCost"]:
        """RULE 702.172a Spree / RULE 702.120 Escalate (MEC-31): the extra
        mana a chosen mode *combination* costs on top of the spell's own
        printed cost, for a "choose one or more" modal block whose modes
        aren't priced identically.

        Spree prices each mode individually — ``obj.spell_modes[i]["cost"]``
        (attached per option by `effect_binder._build_mode_entries` from the
        parser's ``modes["mode_costs"]``, or a hand-authored catalogue
        entry's own ``modes`` dict) — so the total is the sum of every
        *chosen* mode's own cost. Escalate is the opposite split: one flat
        keyword cost (`_escalate_cost`) paid once per mode chosen *beyond
        the first*, regardless of which modes those are — Blessed
        Alliance's "Escalate {2}" printed once, not per mode. The two never
        appear on the same card; Spree is checked first since it's the one
        that needs ``obj.spell_modes`` at all.

        ``None`` (no surcharge) for a bare int/``"both"`` mode — neither
        mechanic's header is ever anything but "choose one or more", so a
        single-mode/"both" selection can't be either — or when ``obj``
        carries neither.
        """
        if not isinstance(mode, (list, tuple)):
            return None
        modes = list(getattr(obj, "spell_modes", None) or [])
        total: Optional["ManaCost"] = None
        for i in mode:
            if 0 <= i < len(modes):
                raw = modes[i].get("cost")
                if raw:
                    piece = ManaCost.parse(str(raw))
                    total = piece if total is None else total.add(piece)
        if total is not None:
            return total
        escalate_cost = self._escalate_cost(obj)
        if escalate_cost is None:
            return None
        extra = max(0, len(mode) - 1)
        if extra <= 0:
            return None
        total = escalate_cost
        for _ in range(extra - 1):
            total = total.add(escalate_cost)
        return total
    def legal_mutate_hosts(self, player: Player, obj: GameObject) -> list[GameObject]:
        """RULE 702.140a: the creatures ``obj`` could mutate onto — "target
        **non-Human** creature you own".

        Ownership, not control (RULE 108.3): a creature you own but an
        opponent currently controls is still a legal host. Shared by
        `can_cast` (which refuses a mutate cast with no host) and
        `_cast_current_face` (which refuses an illegal one).
        """
        options = legal_targets(
            self.state, player.id, TargetSpec(kind="non_human_creature_you_own"), obj
        )
        ids = {entry["instance_id"] for entry in options}
        return [o for o in self.state.permanents() if o.instance_id in ids]
    def _bargain_candidate(self, player: Player) -> Optional[GameObject]:
        """A permanent ``player`` could sacrifice to Bargain (RULE 701.x):
        "an artifact, enchantment, or **token**".

        An auto-pick, like every other non-interactive cost choice here
        (`_sacrifice_candidate`) — and deliberately preferring a **token**,
        since sacrificing a Treasure/Clue is what a real player bargains
        with, and only a *worse* choice (a real artifact/enchantment) is
        left if no token is available.
        """
        candidates = [
            obj
            for obj in self.state.permanents_controlled_by(player.id)
            if obj.is_token or obj.card.is_artifact or obj.card.is_enchantment
        ]
        if not candidates:
            return None
        return next((o for o in candidates if o.is_token), candidates[0])

    def _teamwork_candidates(self, player: Player) -> list[GameObject]:
        """Untapped creatures available for Teamwork (RULE 702.194)."""
        self.recompute_continuous_effects()
        return [obj for obj in self.state.permanents_controlled_by(player.id)
                if obj.is_creature and not obj.tapped]

    def _teamwork_selection(self, player: Player, obj: GameObject,
                            choices: Optional[list[int]] = None) -> Optional[list[GameObject]]:
        params = (getattr(obj, "parametric_keywords", None) or {}).get("teamwork") or {}
        try:
            threshold = int(params.get("n", -1))
        except (TypeError, ValueError):
            return None
        candidates = self._teamwork_candidates(player)
        by_id = {candidate.instance_id: candidate for candidate in candidates}
        if choices is None:
            picked: list[GameObject] = []
            power = 0
            for candidate in sorted(candidates, key=lambda c: c.power, reverse=True):
                picked.append(candidate)
                power += candidate.power
                if power >= threshold:
                    return picked
            return None
        picked = []
        seen: set[int] = set()
        for instance_id in choices:
            if instance_id in seen or instance_id not in by_id:
                return None
            seen.add(instance_id)
            picked.append(by_id[instance_id])
        return picked if sum(candidate.power for candidate in picked) >= threshold else None
    def _escape_cost(self, obj: GameObject) -> Optional["ActivationCost"]:
        """RULE 702.138b: ``obj``'s Escape cost — mana plus "exile N other
        cards from your graveyard" — as a parsed `ActivationCost`, or
        ``None`` if it carries no Escape keyword (or one with no parsed
        cost). Uses the full activated-ability cost grammar (`game/costs.
        parse_activation_cost`), not just `ManaCost`, since Escape's cost
        has a non-mana component the mana model alone can't hold.

        A *granted* escape (Underworld Breach's "the escape cost is equal to
        the card's mana cost plus exile three other cards from your
        graveyard") has no printed cost text to read, so its cost is
        assembled per-card from the grant's parameters plus the card's own
        mana cost — which is why the grant can't just hand back a fixed
        string like a printed keyword does.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("escape")
        if param and param.get("cost"):
            return parse_activation_cost(str(param["cost"]))
        grant = continuous.granted_escape_for(self.state, obj)
        if grant is None:
            return None
        cost = parse_activation_cost(obj.card.mana_cost_string or "{0}")
        cost.exile_from_graveyard = int(grant.get("exile_from_graveyard", 0) or 0)
        return cost
    def can_cast(
        self,
        player: Player,
        obj: GameObject,
        x: int = 0,
        face: str = "front",
        mode: Optional[Any] = None,
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        free: bool = False,
        alt_cost: bool = False,
        mutate: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        evoke: bool = False,
        exile_discount: int = 0,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        targets: Optional[list[Any]] = None,
        assume_mana_available: bool = False,
        help_pay: bool = False,
        pay_additional: bool = False,
        teamwork: bool = False,
        teamwork_choices: Optional[list[int]] = None,
    ) -> bool:
        """RULE 601/602.5: is this spell castable by ``player`` right now?

        ``x`` is the value that would be announced for a cost containing
        ``{X}`` (ignored otherwise) — pass 0 (the default) to check bare
        castability, or a specific value to check whether *that* X is
        affordable. ``face="back"``/``"fuse"`` check a second castable face
        (see `_face_card`) instead, without mutating ``obj`` — a preview,
        used by `legal_actions` to decide whether to offer casting it.
        ``kicked`` is how many times Kicker (RULE 702.33) would be paid — 0
        (the default), or a value validated against the object's own
        ``kicker`` parametric keyword (see `_kicker_cost`): any nonzero value
        without one is illegal, and only Multikicker permits more than 1.
        ``kicker_x`` (PAR-7) is the value announced for Kicker's *own*
        ``{X}`` when ``obj``'s Kicker cost is itself variable (Emblazoned
        Golem-shaped — a wholly separate announced value from the spell's
        own ``x`` above); ignored otherwise. See `max_affordable_kicker_x`.
        ``buyback`` is whether Buyback's own additional cost (RULE 702.27)
        would also be paid — illegal (``False``) for an object with no
        ``buyback`` parametric keyword. ``free=True`` checks the RULE
        601.2f-adjacent condition-gated free-cast alternative cost instead
        of paying the mana cost at all ("If you control a commander, you may
        cast this spell without paying its mana cost." — Deadly Rollick/
        Deflecting Swat/Fierce Guardianship-shaped): legal only when ``obj``
        carries a `free_cast_condition` (`game/effect_binder.py`) whose
        condition currently holds (`condition_query.
        free_cast_condition_holds`); illegal for an object with no such
        condition at all. ``alt_cost=True`` (RULE 118.9, MEC-15 — "You may
        pay `<cost>` rather than pay this spell's mana cost." — Force of
        Will/Negation/Vigor/Daze-shaped) checks a *different* alternative
        cost instead: legal only when ``obj`` carries a `GameObject.
        alt_cast_cost` (bound from `AbilitySpec.alt_cost`) whose own
        optional gate (``alt_cast_condition``, if any) currently holds and
        whose payment (life/return-to-hand/exile-a-hand-card-of-a-color) is
        actually payable right now (`_can_pay_alt_cast_cost`) — mutually
        exclusive with ``free`` in practice (no real card prints both).
        ``sacrifice_choice``/``discard_choices`` are the
        caster's own pick for an "as an additional cost, sacrifice/discard
        …" clause (RULE 601.2b) — the same RULE 602.1 cost-choice shape
        `can_activate`'s ``sacrifice_choice``/``tap_choices`` are; ``None``
        falls back to an auto-pick, for non-interactive callers and for
        every other caller of `can_cast` that isn't checking one specific
        choice (`legal_actions`, the mid-cast face-swap validation above).
        ``targets``, when given, is consulted only by a `conditional_flash`
        condition that depends on the actual chosen target (``"targets_a_
        commander"``, MEC-7) — every offer-time caller omits it (``None``),
        which answers that condition optimistically; `_cast_current_face`
        passes the real chosen targets for the final, enforced check.
        ``assume_mana_available`` (default ``False``) skips only the mana-
        pool payability check above, leaving every other legality
        requirement (timing, targets, additional costs, …) enforced as
        normal — a read-only probe `_cast_current_face` uses to decide
        whether an otherwise-legal cast is *just* short on mana, in which
        case it's worth trying to auto-tap for the rest (`game/mana_
        potential.py`) before failing for real.

        ``mode`` (MEC-31), when it's a chosen combination of modal indices,
        is consulted only for its cost side here — RULE 702.172a Spree/RULE
        702.120 Escalate's own per-combination surcharge
        (`_modal_extra_cost`), folded into the mana-pool check below via
        `effective_cast_cost`. Every other modal shape (a bare int, or
        ``"both"``) prices identically regardless of ``mode``, so passing it
        is harmless there too.
        """
        # A commander may be cast from the command zone as well as the
        # hand (RULE 903.6, 903.8) — commander tax (RULE 903.8, +{2} per
        # previous cast from there) isn't modeled yet. An Adventure creature
        # or a prepared copy sitting in exile may also be castable — see
        # `_castable_from_exile`. A graveyard card with Flashback/Escape may
        # be castable from there too — see `_castable_from_graveyard` — as
        # may one some other permanent grants standing permission for
        # (Lurrus of the Dream-Den-shaped) — see `_graveyard_cast_permission`.
        # The top of the library may be castable too (Oracle of Mul Daya/
        # Glarb, Calamity's Augur-shaped) — see `_castable_from_library`;
        # only the top card itself ever qualifies, never anything deeper.
        # RULE 702.61b (Legolas's Quick Reflexes, MEC-43): a split second
        # spell on the stack blocks casting anything else at all (mana
        # abilities never reach `can_cast` — see `continuous.split_second_
        # active`'s own docstring for why that needs no exemption here).
        if continuous.split_second_active(self.state):
            return False
        if help_pay and self._help_pay_keyword(obj) is None:
            # RULE 702.51/702.66/702.126 (PAR-23): the "cast using Convoke/
            # Delve/Improvise" offer is illegal for a spell that has none of
            # them — same guard shape as `evoke`/`buyback` without the keyword.
            return False
        if teamwork and self._teamwork_selection(player, obj, teamwork_choices) is None:
            return False
        in_castable_zone = (
            obj in player.hand
            or obj in player.command
            or (obj in player.exile and self._castable_from_exile(obj))
            or (obj.zone == Zone.EXILE and self._has_temp_play_permission(obj, player))
            or (obj.zone == Zone.EXILE and self._has_conditional_exile_permission(obj, player))
            or self._can_cast_foretold(player, obj)
            or (obj in player.graveyard and self._castable_from_graveyard(obj))
            or (obj in player.graveyard and self._graveyard_cast_permission(player, obj))
            or (
                obj in player.graveyard
                and self._self_graveyard_or_exile_cast_permission(obj)
            )
            or (
                obj in player.exile
                and self._self_graveyard_or_exile_cast_permission(obj)
            )
            or (
                bool(player.library)
                and obj is player.library[-1]
                and self._castable_from_library(player, obj)
            )
        )
        if not in_castable_zone:
            return False
        # RULE 601.3a: "Players can't cast spells from graveyards or
        # libraries." (Grafdigger's Cage/Weathered Runestone) — checked
        # once here rather than duplicated into every graveyard/library
        # permission source above (Flashback/Escape, a Lurrus-shaped grant,
        # the top-of-library permission); hand/command/exile castability is
        # unaffected.
        if obj.zone in (Zone.GRAVEYARD, Zone.LIBRARY) and continuous.graveyard_library_cast_prohibited(
            self.state, zone=obj.zone.value
        ):
            return False
        card = self._face_card(obj, face)
        if card is None or card.is_land:
            return False
        # RULE 601-area: "Each player can't cast more than N spells each
        # turn." (Eidolon of Rhetoric/Rule of Law/Archon of Emeria) — a flat
        # cap tracked per player, reset each turn (`state.spells_cast_this_
        # turn`, already maintained by `RulesEngine._track_spell_cast`).
        max_spells = continuous.max_spells_per_turn(self.state)
        if max_spells is not None and self.state.spells_cast_this_turn.get(player.id, 0) >= max_spells:
            return False
        if not card.is_creature:
            max_noncreature = continuous.max_noncreature_spells_per_turn(self.state)
            if (
                max_noncreature is not None
                and self.state.noncreature_spells_cast_this_turn.get(player.id, 0) >= max_noncreature
            ):
                return False
        # RULE 601.3a: a *conditional* prohibition on this specific spell,
        # rather than a flat per-turn count — a standing static (Lavinia,
        # Azorius Renegade's "each opponent can't cast noncreature spells
        # with mana value greater than the number of lands that player
        # controls") or a duration-bounded player effect with no permanent
        # left behind it at all (Hope of Ghirapur, which sacrificed itself).
        if continuous.cast_prohibited(self.state, player, card, zone=obj.zone):
            return False
        if any(
            getattr(e, "player_cast_restriction", False) and e.restricts(card)
            for e in player.player_effects
        ):
            return False
        # Timing (RULE 601.3a): sorcery-speed spells need an empty stack,
        # the player's own main phase, and their priority. RULE 702.8b:
        # Flash lets an otherwise-sorcery-speed card (Embercleave, The
        # Wandering Emperor) be cast any time its controller could cast an
        # instant instead — checked off the *object* (`combat.has`, the same
        # printed+intrinsic+granted keyword union combat reads elsewhere),
        # not just the card, so a temporary flash grant works too. A
        # `conditional_flash` (RULE 702.8b's "as though it had flash if
        # <condition>") grants the same permission only while its condition
        # holds, checked live (`condition_query`).
        conditional_flash = getattr(obj, "conditional_flash", None)
        has_conditional_flash = (
            conditional_flash is not None
            and condition_query.conditional_flash_holds(conditional_flash, obj, self.state, targets=targets)
        )
        # "You may cast spells this turn as though they had flash." (Borne
        # Upon a Wind-shaped) — a temporary, player-scoped blanket flash
        # grant (`GameState.temp_flash_until_turn`, `GrantFlashUntilEndOf
        # TurnEffect`), independent of any keyword/condition on the object
        # itself.
        has_temp_flash = self.state.temp_flash_until_turn.get(player.id) == self.state.internal_turn.number
        # Elsha of the Infinite-shaped: "you may cast [noncreature spells
        # cast this way] as though [they] had flash" — a standing grant
        # tied to the *permission*, not the object's own printed/granted
        # keywords, so it's consulted live off `game/top_library.py` like
        # every other part of this permission family.
        has_top_library_flash = (
            bool(player.library)
            and obj is player.library[-1]
            and may_cast_flash_from_top_of_library(player, self.state, card)
        )
        # Aluren-shaped: "…and as though they had flash." is bundled into
        # the *same* standing permission as the free cost right below, not
        # a blanket flash grant on the card itself — it only exempts the
        # `free=True` cast this permission itself authorizes; paying the
        # real mana cost at sorcery speed is still an ordinary cast,
        # unaffected (see `continuous.standing_free_cast_grants_flash`'s
        # own docstring for why this is gated on ``free`` rather than
        # joining `has_standing_flash_permission` unconditionally above).
        has_aluren_free_cast_flash = free and continuous.standing_free_cast_grants_flash(
            self.state, player, card
        )
        # Etali, Primal Storm/Primal Conqueror (RULE 601.3b analogue):
        # "timing permissions based on a card's type are ignored" for a
        # card exiled by one of these — `grant_free_cast_window_from_exile
        # (ignore_timing=True)`'s own marker, not a real Flash grant, so it
        # doesn't leak into anything that reads the object's own keywords.
        has_free_cast_timing_override = obj.instance_id in self.state.free_cast_ignore_timing_instance_ids
        sorcery_speed = not (
            card.is_instant or combat.has(obj, "flash") or has_conditional_flash or has_temp_flash
            or has_top_library_flash
            or continuous.has_standing_flash_permission(self.state, player, card)
            or has_aluren_free_cast_flash
            or has_free_cast_timing_override
        )
        if continuous.forced_sorcery_speed_only(self.state, player):
            # Teferi, Time Raveler (MEC-42): "each opponent can cast spells
            # only any time they could cast a sorcery" — overrides every
            # Flash/instant-speed exemption just computed above, for a
            # restricted player.
            sorcery_speed = True
        if face == "face_down":
            # RULE 708.4: an object cast face down is turned face down
            # *before* it goes on the stack, so "effects that care about the
            # characteristics of a spell will see only the face-down spell's
            # characteristics" — a 2/2 creature with no text. The face-up
            # card's own Flash (which `combat.has` reads off the still-face-up
            # object above) therefore doesn't apply to this cast.
            sorcery_speed = True
            if player is not self.state.active_player:
                return False
            if not self._in_main_phase() or self.state.stack:
                return False
        if sorcery_speed:
            if player is not self.state.active_player:
                return False
            if not self._in_main_phase() or self.state.stack:
                return False
        if kicked:
            kicker_cost = self._kicker_cost(obj)
            if kicker_cost is None:
                return False
            kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
            if kicked > 1 and not kicker_param.get("multi"):
                return False
        if buyback and self._buyback_cost(obj) is None:
            return False
        if face == "bestow" and self._bestow_cost(obj) is None:
            # RULE 702.103: only a card that actually carries Bestow can be
            # cast this way — fails closed, like evoke/buyback above.
            return False
        if mutate:
            if self._mutate_cost(obj) is None:
                return False
            # RULE 702.140a: mutate targets "**non-Human** creature you
            # own" — with no legal host the spell simply can't be cast this
            # way (RULE 601.2c), only for its printed cost.
            if not self.legal_mutate_hosts(player, obj):
                return False
        if entwine and self._entwine_cost(obj) is None:
            # RULE 702.42a: Entwine is only payable on a spell that has one.
            return False
        if evoke and not self._has_evoke(obj):
            # RULE 702.74b: Evoke is only payable on a spell that carries
            # (or was granted, Ashling the Limitless-shaped) one.
            return False
        if evoke:
            evoke_exile_color = self._evoke_exile_hand_color(obj)
            if evoke_exile_color and self._exile_hand_card_candidate(
                player, evoke_exile_color, exclude=obj
            ) is None:
                return False
        if exile_discount:
            # March of Swirling Mist (MEC-42): only legal on a spell that
            # actually prints this additional cost, and only up to the
            # number of *other* matching-color cards actually in hand.
            spec = continuous.exile_discount_spec_for(obj)
            if spec is None:
                return False
            color = str(spec.get("color", "U"))
            eligible_in_hand = sum(
                1 for c in player.hand
                if c is not obj and color in (getattr(c, "colors", None) or set())
            )
            if exile_discount > eligible_in_hand:
                return False
        if bargained:
            # RULE 702.166: the flag is a cost choice only for a spell that
            # actually has Bargain.  Besides enforcing the rules, this keeps
            # an arbitrary API caller from sacrificing a permanent to mark an
            # unrelated spell as bargained.
            if "bargain" not in getattr(obj, "intrinsic_keywords", set()):
                return False
            if not self._bargain_candidate(player):
                # Bargain is optional, but choosing it requires something to
                # sacrifice.
                return False
        if obj in player.graveyard and self._graveyard_cast_keyword(obj) == "escape":
            # RULE 702.138b: "exile N *other* cards from your graveyard" —
            # ``obj`` itself doesn't count toward that N.
            escape_cost = self._escape_cost(obj)
            if escape_cost is None:
                return False
            if len(player.graveyard) - 1 < escape_cost.exile_from_graveyard:
                return False
        if obj in player.graveyard and self._graveyard_cast_keyword(obj) == "retrace":
            # RULE 702.81a: "…by discarding a land card in addition to paying
            # its other costs." — unpayable with no land card in hand.
            if not any(getattr(c, "is_land", False) for c in player.hand):
                return False
        if free:
            # Two independent sources of a "you may cast this without
            # paying its mana cost" permission: a per-object condition
            # bound at bind-on-load (RULE 601.2f, `GameObject.free_cast_
            # condition` — Deadly Rollick-shaped, "if you control a
            # commander, …"), or a standing board-wide permission that
            # covers *any* qualifying card, not just this one specifically
            # bound (Aluren, `continuous.has_standing_free_cast_
            # permission`) — legal if either currently holds.
            free_cast_condition = getattr(obj, "free_cast_condition", None)
            condition_ok = (
                free_cast_condition is not None
                and condition_query.free_cast_condition_holds(free_cast_condition, obj, self.state)
            )
            if not condition_ok and not continuous.has_standing_free_cast_permission(
                self.state, player, card
            ):
                return False
        elif alt_cost:
            alt_cast_cost = getattr(obj, "alt_cast_cost", None) or continuous.granted_alt_cast_cost_for(
                self.state, player, card
            )
            if alt_cast_cost is None:
                return False
            alt_cast_condition = getattr(obj, "alt_cast_condition", None)
            if alt_cast_condition and not condition_query.free_cast_condition_holds(
                alt_cast_condition, obj, self.state
            ):
                return False
            if not self._can_pay_alt_cast_cost(player, obj, alt_cast_cost):
                return False
        elif obj.instance_id in self.state.free_cast_instance_ids:
            # RULE 702.88b Rebound's own free-cast window
            # (`RulesEngine.grant_free_cast_window_from_exile`) — already
            # armed for this specific instance, no mana check needed.
            pass
        elif self._top_library_life_payment(player, obj, card):
            # Bolas's Citadel-shaped: casting this way pays life equal to
            # the spell's mana value instead of its mana cost — mandatory,
            # not optional, so no mana-pool check applies at all here.
            if player.life < card.converted_mana_cost:
                return False
        elif not assume_mana_available:
            cost = self.effective_cast_cost(
                player, obj, x, face=face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback,
                mutate=mutate, entwine=entwine, evoke=evoke, exile_discount=exile_discount, targets=targets,
                help_pay=help_pay, pay_additional=pay_additional,
            )
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            wildcard = self.state.mana_wildcard_permission.get(obj.instance_id)
            require_source_kind = getattr(obj, "mana_source_kind_restriction", None)
            # MEC-43: K'rrik, Son of Yawgmoth's standing "pay 2 life instead
            # of a {B} pip" permission (`continuous.life_for_mana_pip_color`).
            extra_life_color = continuous.life_for_mana_pip_color(self.state, player)
            if not player.mana_pool.can_pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                require_source_kind=require_source_kind, extra_life_color=extra_life_color,
            ):
                return False
            if kicked and kicker_x > 0 and self._kicker_x_distinct_colors(obj):
                # PAR-7: Kicker's own distinct-color-capped {X} is excluded
                # from ``cost`` above (see `effective_cast_cost`) and paid
                # separately, so it must also be checked separately — against
                # whatever the pool has *left* once the rest of the cost is
                # paid, not the pool as a whole (the same mana can't cover
                # both). A clone keeps this a pure read.
                remaining = player.mana_pool.clone()
                remaining.pay(
                    cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard,
                    extra_life_color=extra_life_color,
                )
                if not remaining.can_pay_distinct_colors(kicker_x):
                    return False
        # RULE 601.2b: an "as an additional cost to cast this spell, …"
        # clause is a separate legality gate from the mana cost above — a
        # sacrifice/discard/life payment that isn't payable makes the spell
        # uncastable even with the mana in hand.
        additional_cost = getattr(obj, "additional_cast_cost", None)
        if face == "face_down":
            # RULE 708.4 again: no text means no "as an additional cost to
            # cast this spell, …" clause either — the {3} is the whole price.
            additional_cost = None
        return self._can_pay_additional_cast_cost(
            player, obj, additional_cost, x,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            pay_additional=pay_additional,
        )
    @staticmethod
    def _buyback_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.27: ``obj``'s Buyback cost as a `ManaCost`, or ``None``
        if it carries no Buyback keyword (or one with no parsed cost)."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("buyback")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
    @staticmethod
    def _bestow_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.103: ``obj``'s Bestow cost as a `ManaCost`, or ``None``
        if it carries no Bestow keyword (or one with no parsed cost). Read
        off the ``bestow`` parametric keyword the parser already docks
        (`parser/oracle/catalogue/keywords.py`), the same shape as
        `_buyback_cost`/`_kicker_cost` — PAR-26 is purely engine work."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("bestow")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
    @staticmethod
    def _kicker_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.33: ``obj``'s Kicker cost as a `ManaCost`, or ``None`` if
        it carries no Kicker/Multikicker keyword (or one with no parsed
        cost). Multikicker shares this same ``kicker`` param shape — see
        `effect_binder.attach_keyword` — distinguished only by its ``multi``
        flag, which callers check separately.
        """
        param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
    @staticmethod
    def _kicker_x_distinct_colors(obj: GameObject) -> bool:
        """PAR-7: whether ``obj``'s Kicker ``{X}`` carries the "spend only
        colored mana on X. No more than one mana of each color may be spent
        this way." restriction (Emblazoned Golem) — see
        `ability_catalogue.kicker_x_mana_restriction`. Read off the printed
        card fresh each call rather than cached onto the object, the same
        "recomputed from raw text" treatment `entry_counters` gets."""
        return ability_catalogue.kicker_x_mana_restriction(obj.card) == "distinct_colors"
    def max_affordable_kicker(self, player: Player, obj: GameObject) -> int:
        """The highest number of times ``player`` could pay Kicker and still
        cast ``obj`` (RULE 702.33) — 0 or 1 for a plain Kicker, 0..N for
        Multikicker. Mirrors `max_affordable_x`'s "scan down from an upper
        bound" shape, and the same MEC-13 mana-potential awareness (the
        bound and each candidate's payability go through `game/mana_
        potential.py` rather than the real pool alone). Doesn't itself
        account for an independently announced Kicker ``{X}``
        (`max_affordable_kicker_x`) — checked with ``kicker_x=0``, so a
        Kicker payable at all (any X, even 0) still reports 1 here; the two
        are meant to be read together.
        """
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is None:
            return 0
        kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
        potential_total = player.mana_pool.total() + mana_potential.max_potential_total(self, player)
        upper = potential_total if kicker_param.get("multi") else 1
        for kicked in range(upper, -1, -1):
            if not self.can_cast(player, obj, kicked=kicked, assume_mana_available=True):
                continue
            cost = self.effective_cast_cost(player, obj, kicked=kicked)
            if mana_potential.is_castable_via_potential(self, player, cost):
                return kicked
        return 0
    def max_affordable_kicker_x(self, player: Player, obj: GameObject) -> int:
        """The highest X ``player`` could announce for Kicker's *own*
        ``{X}`` (RULE 702.33b, PAR-7 — Emblazoned Golem-shaped) and still
        cast ``obj`` kicked once. `max_affordable_x`'s sibling for an
        announced value living in Kicker's cost rather than the spell's own
        (same MEC-13 mana-potential awareness); 0 if ``obj``'s Kicker cost
        has no ``{X}`` at all.

        `_kicker_x_distinct_colors`'s own "no more than one mana of each
        colour spent on X" restriction (Emblazoned Golem) is a real-pool
        *shape* check `can_cast` only runs with ``assume_mana_available=
        False`` — `game/mana_potential.py`'s tap-plan search has no concept
        of it (auto-tapping doesn't know to diversify colours for one
        narrow restriction), so a card carrying it falls back to the
        original real-pool-only search rather than risk answering "yes"
        for an X that potential mana could reach in total but not in the
        colour spread this restriction actually demands.
        """
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is None or not kicker_cost.has_variable:
            return 0
        if self._kicker_x_distinct_colors(obj):
            bound = player.mana_pool.total()
            for kicker_x in range(bound, -1, -1):
                if self.can_cast(player, obj, kicked=1, kicker_x=kicker_x):
                    return kicker_x
            return 0
        bound = player.mana_pool.total() + mana_potential.max_potential_total(self, player)
        for kicker_x in range(bound, -1, -1):
            if not self.can_cast(player, obj, kicked=1, kicker_x=kicker_x, assume_mana_available=True):
                continue
            cost = self.effective_cast_cost(player, obj, kicked=1, kicker_x=kicker_x)
            if mana_potential.is_castable_via_potential(self, player, cost):
                return kicker_x
        return 0
    def effective_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        x: int = 0,
        face: str = "front",
        mode: Optional[Any] = None,
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        mutate: bool = False,
        entwine: bool = False,
        evoke: bool = False,
        exile_discount: int = 0,
        targets: Optional[list[Any]] = None,
        help_pay: bool = False,
        pay_additional: bool = False,
    ) -> "ManaCost":
        """``obj``'s mana cost after static cost adjustments (RULE 601.2f/903.8).

        Starts from the printed cost (with ``{X}`` resolved), applies the net
        generic reduction from "spells you cast cost {N} less/more" statics in
        play, then adds commander tax ({2} per previous cast of this commander
        from the command zone, RULE 903.8) when it's being cast from there.
        Generic-only and floored at zero — the common, safe case. ``face``
        previews a second castable face's own printed cost (see
        `_face_card`) without mutating ``obj``. ``kicked`` adds Kicker's own
        cost (RULE 702.33b) once per time paid, and ``buyback`` adds
        Buyback's own cost once (RULE 702.27), both via `ManaCost.add` — not
        subject to the generic-only reduction above, since each is a
        distinct additional cost, not part of the printed one. When Kicker's
        own cost is itself variable (PAR-7), ``kicker_x`` resolves it — unless
        `_kicker_x_distinct_colors` flags it as paid separately (Emblazoned
        Golem's "spend only colored mana on X" cap), in which case it's
        zeroed here so it isn't double-counted; `can_cast`/`cast_spell` check
        and pay that portion themselves via `ManaPool.can_pay_distinct_colors`/
        `pay_distinct_colors`.

        RULE 601.2b/702.34b: a card actually sitting in ``player``'s
        graveyard (only reachable at all via `_castable_from_graveyard`) is
        cast for its alternative Flashback/Escape cost *instead of* the
        printed one — a substitution, not an addition, applied before the
        reduction/tax below so those still apply on top of it as usual.

        ``targets``, when given, adds one copy of ``obj.strive_cost`` per
        target *beyond the first* (Strive, MEC-4 — RULE 601.2c precedes
        601.2f, so unlike `conditional_flash`'s pre-cast timing check this
        one reads the caster's actual, already-chosen targets) — omitted
        (``None``) at every offer-time preview caller, the same "no surcharge
        until the real cast supplies it" treatment `can_cast` gives it.

        ``mode``, when it's a chosen combination of modal indices, adds RULE
        702.172a Spree/RULE 702.120 Escalate's own surcharge for that
        combination (`_modal_extra_cost`, MEC-31) — ``None``/a bare
        int/``"both"`` add nothing, since neither mechanic's header is ever
        anything but "choose one or more".
        """
        card = self._face_card(obj, face) or obj.card
        if face == "bestow":
            # RULE 702.103a: the Bestow cost replaces the printed mana cost
            # (an alternative cost, the same substitution shape Mutate/Evoke
            # use just below) — still subject to the generic reduction/tax
            # `_adjust_cost` applies afterward.
            bestow_cost = self._bestow_cost(obj)
            if bestow_cost is not None:
                return self._adjust_cost(bestow_cost, player, obj)
        if mutate:
            # RULE 702.140b: the Mutate cost replaces the printed one — an
            # alternative cost, the same substitution shape Flashback/Escape
            # already use below (and, like those, still subject to the
            # reduction/tax applied afterwards).
            mutate_cost = self._mutate_cost(obj)
            if mutate_cost is not None:
                return self._adjust_cost(mutate_cost, player, obj)
        if evoke:
            # RULE 702.74b: likewise a substitution, not an addition — a
            # printed keyword cost, or one granted by another permanent
            # (Ashling, the Limitless-shaped, `continuous.granted_evoke_
            # cost_for`), since a grant has no keyword line of its own to
            # read.
            evoke_cost = self._evoke_cost(obj) or continuous.granted_evoke_cost_for(self.state, obj)
            if evoke_cost is not None:
                return self._adjust_cost(evoke_cost, player, obj)
            if self._evoke_exile_hand_color(obj) is not None:
                # A non-mana alternative cost still receives commander tax
                # and ordinary cost adjustments (RULE 118.9).
                return self._adjust_cost(ManaCost.parse("{0}"), player, obj)
        override = self.state.exile_cast_cost_override.get(obj.instance_id)
        if self._can_cast_foretold(player, obj):
            cost = self._foretell_cost(obj) or self.rules.mana_cost_of(card)
        elif override is not None and getattr(obj, "zone", None) == Zone.EXILE:
            # RULE 701.65 (Airbend, PAR-29): "its owner may cast it for {2}
            # rather than its mana cost." — a *fixed* alternative cost
            # while the card sits in exile under an `exile_cast_condition`
            # grant, substituted (not added) before the reduction/tax
            # below, exactly like Flashback/Escape's own graveyard alt cost.
            cost = ManaCost.parse(override)
        elif obj in player.graveyard:
            keyword = self._graveyard_cast_keyword(obj)
            if keyword == "flashback":
                alt_cost = self._flashback_cost(obj)
            elif keyword == "escape":
                escape_cost = self._escape_cost(obj)
                alt_cost = escape_cost.mana if escape_cost is not None else None
            else:
                alt_cost = None
            cost = alt_cost if alt_cost is not None else self.rules.mana_cost_of(card)
        else:
            cost = self.rules.mana_cost_of(card)
        if cost.has_variable:
            # "Spend only <color> mana on X." (Drain Life, MEC-43) —
            # RULE 605.3a scoped to just the {X} portion of the printed
            # cost, not the whole thing (unlike `mana_source_kind_
            # restriction` above/`ActivationCost.spend_only_chosen_color`).
            x_color = getattr(obj, "x_spend_color_restriction", None)
            cost = cost.with_x_colored(x, x_color) if x_color else cost.with_x(x)
        cost = self._adjust_cost(cost, player, obj, targets=targets)
        tax = self.commander_tax(player, obj)
        if tax:
            cost = cost.increase_generic(tax)
        if kicked:
            kicker_cost = self._kicker_cost(obj)
            if kicker_cost is not None:
                if kicker_cost.has_variable:
                    resolved_x = 0 if self._kicker_x_distinct_colors(obj) else kicker_x
                    kicker_cost = kicker_cost.with_x(resolved_x)
                for _ in range(kicked):
                    cost = cost.add(kicker_cost)
        if buyback:
            buyback_cost = self._buyback_cost(obj)
            if buyback_cost is not None:
                cost = cost.add(buyback_cost)
        # ENG-32 (RULE 601.2b/701.67): "as an additional cost to cast this
        # spell, waterbend {N}." — a {N}/{X} generic mana cost folded into
        # the spell's total here (not paid separately in
        # `_pay_additional_cast_cost`), so `can_cast`'s pool check and
        # `_auto_tap_for_cast_if_needed` both see it. Only the *mandatory*
        # form is folded unconditionally; the *optional* "you may waterbend
        # {N}" form (PAR-30, `additional_cast_cost_optional`) only when the
        # caller chose the `pay_additional` cast variant (`_offer_cast`).
        add_cost = getattr(obj, "additional_cast_cost", None)
        add_optional = getattr(obj, "additional_cast_cost_optional", False)
        if (
            add_cost is not None and add_cost.mana.symbols and face != "face_down"
            and (not add_optional or pay_additional)
        ):
            wb_mana = add_cost.mana.with_x(x) if add_cost.mana.has_variable else add_cost.mana
            cost = cost.add(wb_mana)
        if entwine:
            # RULE 702.42a: Entwine's cost is added on top of the printed
            # one, like Kicker/Buyback above — not substituted for it.
            entwine_cost = self._entwine_cost(obj)
            if entwine_cost is not None:
                cost = cost.add(entwine_cost)
        modal_extra_cost = self._modal_extra_cost(obj, mode)
        if modal_extra_cost is not None:
            # MEC-31: RULE 702.172a Spree / RULE 702.120 Escalate — likewise
            # additive, on top of everything above, never substituted.
            cost = cost.add(modal_extra_cost)
        strive_cost = getattr(obj, "strive_cost", None)
        if strive_cost is not None and targets:
            # "This spell costs <cost> more to cast for each target beyond
            # the first." — the *first* target is free, every additional one
            # adds a full copy (not just generic, unlike a battlefield
            # anthem's tax — Strive's own cost can carry colored pips, e.g.
            # Aerial Formation's "{2}{U} more").
            for _ in range(max(0, len(targets) - 1)):
                cost = cost.add(strive_cost)
        if exile_discount:
            # March of Swirling Mist (MEC-42): "you may exile any number
            # of blue cards from your hand. This spell costs {2} less to
            # cast for each card exiled this way." — RULE 601.2b's
            # announced-and-then-paid shape, the same "compute the
            # adjusted cost before payment" treatment Kicker's own extra
            # cost gets, just subtracted — `reduce_generic_and_x`, since
            # this printed cost's only generic component is {X} itself.
            spec = continuous.exile_discount_spec_for(obj)
            if spec is not None:
                cost = cost.reduce_generic_and_x(int(spec.get("generic_per_card", 2)) * exile_discount)
        if help_pay and self._help_pay_keyword(obj) is not None:
            # RULE 702.51/702.66/702.126 (PAR-23): the offer-time upper
            # bound — the *real* cast consumes only the minimum
            # (`_consume_cast_help`), but `can_cast`/the displayed cost want
            # the best case this help could reach.
            cost = self._cast_help_capacity(player, obj, cost)
        return cost
    @staticmethod
    def commander_tax(player: Player, obj: GameObject) -> int:
        """Generic surcharge to cast ``obj`` from the command zone (RULE 903.8).

        {2} for each previous time this commander was cast from the command
        zone; 0 for a normal spell or a commander being cast from hand."""
        if obj.is_commander and obj in player.command:
            return 2 * player.commander_casts.get(obj.instance_id, 0)
        return 0
    def _adjust_cost(
        self, cost: "ManaCost", player: Player, obj: Optional[GameObject] = None,
        targets: Optional[list[Any]] = None,
    ) -> "ManaCost":
        """Apply the net static generic adjustment (reduce or increase).

        ``obj``, when given, also folds in a Delve/Affinity-shaped reduction
        printed on the card itself (`continuous.self_cost_reduction_for`) —
        distinct from a battlefield permanent's "your spells cost less".
        ``targets`` (the caster's already-chosen targets, RULE 601.2c
        precedes 601.2f) lets a "costs {N} less if it targets a `<criteria>`"
        static resolve; ``None`` at every offer-time caller (best case).
        """
        reduction, _ = continuous.cost_reduction_for(self.state, player, obj, targets=targets)
        if obj is not None:
            self_reduction, _ = continuous.self_cost_reduction_for(
                obj, self.state, caster_id=player.id, targets=targets,
            )
            reduction += self_reduction
        if reduction > 0:
            cost = cost.reduce_generic(reduction)
        elif reduction < 0:
            cost = cost.increase_generic(-reduction)
        floor = continuous.cost_floor_for(self.state, player, obj)
        if floor > cost.converted_mana_cost:
            # RULE 601.2f's reminder text example is explicit: a {1}{B}
            # spell under a floor of 3 becomes {2}{B}, not {3}{B} — the
            # floor bounds the spell's *total* mana value, and only the
            # shortfall is added as generic, leaving colored pips alone.
            cost = cost.increase_generic(floor - cost.converted_mana_cost)
        return cost
    def max_affordable_x(self, player: Player, obj: GameObject) -> int:
        """The highest X ``player`` could announce and still pay for ``obj``.

        MEC-13: mana-potential-aware, not real-pool-only — a player with
        four untapped Mountains and an empty pool can still announce X=3
        for a `{X}{R}` spell (`GameEngine.auto_tap_for`/`_auto_tap_for_
        cast_if_needed` already handles the *execution* of any X the
        caller supplies correctly; this is the offer-time hint that used
        to undersell it). The search bound and each candidate's
        payability both go through `game/mana_potential.py`: the bound is
        real pool total plus `max_potential_total`'s colour-blind ceiling
        (safe here since X is always a generic cost, RULE 107.3c), and
        each candidate ``x`` is accepted once it's legal apart from mana
        (``assume_mana_available``) and its own effective cost is payable
        via `mana_potential.is_castable_via_potential`. Scans down to the
        first payable value, 0 if even X=0 doesn't work.
        """
        bound = player.mana_pool.total() + mana_potential.max_potential_total(self, player)
        for x in range(bound, -1, -1):
            if not self.can_cast(player, obj, x, assume_mana_available=True):
                continue
            cost = self.effective_cast_cost(player, obj, x)
            if mana_potential.is_castable_via_potential(self, player, cost):
                return x
        return 0
    def cast_spell(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]] = None,
        x: int = 0,
        face: str = "front",
        mode: Optional[Any] = None,
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        target_groups: Optional[list[list[Any]]] = None,
        free: bool = False,
        alt_cost: bool = False,
        mutate: bool = False,
        mutate_under: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        evoke: bool = False,
        exile_discount: int = 0,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        help_pay: bool = False,
        pay_additional: bool = False,
        teamwork: bool = False,
        teamwork_choices: Optional[list[int]] = None,
    ):
        """Cast a spell after validating timing, payability and targets (RULE 601).

        ``face="back"``/``"fuse"`` cast a second castable face instead (see
        `_face_card`) — a modal DFC's back (RULE 712.10), a split card's
        other half or fused combination (RULE 709.3/709.4), or an
        Adventure's instant/sorcery half (RULE 715.2b): ``obj`` is rebound
        onto that face (`RulesEngine.switch_to_face`, the same "clear +
        rebind catalogue abilities" treatment `become_copy` uses) before the
        ordinary cast validation/commit runs — so any failure below leaves
        ``obj`` restored to its original face rather than silently stuck on
        the second one.

        ``mode`` chooses which of a modal spell's ("Choose one —", RULE
        700.2) printed options resolves: an index into ``obj.spell_modes``,
        or the literal ``"both"`` (RULE 700.2e, only when
        ``obj.spell_modes_or_both``; or RULE 702.42a with ``entwine=True``).
        Required — raises — for a spell that
        carries ``spell_modes``; ignored otherwise. See `_mode_effects_applied`.

        ``entwine`` pays Entwine's additional cost (RULE 702.42a) so that
        ``mode="both"`` resolves *every* mode of an ordinary "choose one"
        block — illegal for a spell with no entwine cost, and the only way
        to reach "both" on one.

        ``kicked`` is how many times to pay Kicker (RULE 702.33b) — see
        `can_cast`/`effective_cast_cost`; recorded on ``obj.kicker_count``
        once the cast succeeds. ``kicker_x`` (PAR-7) is the value announced
        for Kicker's own ``{X}`` when it's variable; recorded on
        ``obj.kicker_x_paid``. ``buyback`` is whether to pay Buyback's
        additional cost (RULE 702.27) — recorded on ``obj.buyback_paid``,
        consulted by `RulesEngine.resolve_top_of_stack` to route the spell
        back to hand instead of the graveyard.

        ``target_groups``, when given, partitions ``targets`` per targeting
        effect (`StackItem.target_groups`) — needed only when ``obj`` carries
        2+ *different* targeting effects; omitted (``None``), every effect
        reads ``targets`` directly, unchanged from before this existed.

        ``sacrifice_choice``/``discard_choices`` answer a spell's own "as an
        additional cost to cast this spell, sacrifice/discard …" clause
        (RULE 601.2b) — see `can_cast`; ``None`` falls back to an auto-pick,
        for non-interactive callers.
        """
        if face == "face_down":
            # RULE 702.37c/702.168b: "turn it face down and announce that
            # you're using a morph ability … put it onto the stack (as a
            # face-down spell with the same characteristics), and pay {3}".
            # The face swap therefore happens *before* the ordinary cast
            # body runs — the same order (and the same rollback-on-failure
            # discipline) as the second-face branch below, so a rejected
            # cast never leaves the card stuck face down in hand.
            #
            # MEC-13: auto-tap for the flat {3} *before* the legality gate
            # below — `_cast_current_face` (reached only after the swap)
            # can't do this itself, since by then ``face`` is gone (it
            # reads whatever `obj.card` currently is), so a face-down cast
            # payable only by tapping untapped lands used to be rejected
            # here outright, `legal_actions` never even offering it (see
            # `_castable_now_or_via_potential`'s own docstring, since fixed
            # to use it here for face_down too).
            self._auto_tap_for_cast_if_needed(player, obj, x, face=face)
            if not self.can_cast(player, obj, x, face=face):
                raise ValueError(f"{player.id} cannot cast {obj.name} face down now")
            kind = face_down.cast_face_down_kind(obj)
            snapshot = self.rules.snapshot_face(obj)
            self.rules.turn_face_down(obj, kind)
            try:
                return self._cast_current_face(player, obj, None, 0)
            except Exception:
                obj.turn_face_up()
                self.rules.restore_face(obj, snapshot)
                raise
        if face == "bestow":
            # RULE 702.103a/b: a creature card cast for its Bestow cost goes
            # on the stack as an Aura spell with "enchant creature"
            # (`_begin_bestow` reshapes ``obj`` first, so the ordinary Aura
            # target/attach machinery takes it from here) and pays the
            # bestow cost rather than its mana cost. Same "reshape before
            # the body, roll it back on any failure" discipline as the
            # face-down / second-face branches.
            if self._bestow_cost(obj) is None:
                raise ValueError(f"{obj.name} has no bestow cost")
            self._auto_tap_for_cast_if_needed(player, obj, x, face="bestow")
            if not self.can_cast(player, obj, x, face="bestow"):
                raise ValueError(f"{player.id} cannot cast {obj.name} bestowed now")
            self.rules._begin_bestow(obj)
            try:
                return self._cast_current_face(
                    player, obj, targets, x, target_groups=target_groups, bestow=True,
                )
            except Exception:
                self.rules._end_bestow(obj)
                raise
        if face in ("back", "fuse"):
            if not self.can_cast(
                player, obj, x, face=face, kicked=kicked, buyback=buyback, free=free, alt_cost=alt_cost,
            ):
                raise ValueError(f"{player.id} cannot cast {obj.name} now")
            # RULE 715.2b: an Adventure spell half must be recognized while
            # ``obj.card`` is still the front (creature) face, before the
            # switch below — resolution needs to know to exile-and-restore
            # rather than send it to the graveyard.
            is_adventure_cast = face == "back" and obj.card.is_adventure
            alt = obj.card.back_face() if face == "back" else obj.card.fuse_face()
            snapshot = self.rules.snapshot_face(obj)
            self.rules.switch_to_face(obj, alt)
            try:
                result = self._cast_current_face(
                    player, obj, targets, x, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback,
                    target_groups=target_groups, free=free, alt_cost=alt_cost, mutate=mutate,
                    mutate_under=mutate_under, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
                    sacrifice_choice=sacrifice_choice, discard_choices=discard_choices, help_pay=help_pay,
                    pay_additional=pay_additional, teamwork=teamwork, teamwork_choices=teamwork_choices,
                )
            except Exception:
                self.rules.restore_face(obj, snapshot)
                raise
            if is_adventure_cast:
                obj.adventure_snapshot = snapshot
            return result
        # The mode is chosen before costs are paid (RULE 601.2b), but a
        # conditional modal header can depend on the *announced* Kicker.
        # Keep that prospective value only for this validation/resolution
        # window; the successful cast later persists `kicker_count` normally.
        obj._modal_announced_kicked = kicked
        obj._modal_announced_teamwork = teamwork
        # Snapshot non-cost conditional modal headers at the choice point.
        # In particular, "as you cast" reads the pre-cast battlefield, not
        # whatever it looks like when the spell eventually resolves.
        obj._modal_override_condition_met = self._modal_override_active(obj)
        try:
            return self._cast_current_face(
                player, obj, targets, x, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback,
                target_groups=target_groups, free=free, alt_cost=alt_cost, mutate=mutate,
                mutate_under=mutate_under, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices, help_pay=help_pay,
                pay_additional=pay_additional, teamwork=teamwork, teamwork_choices=teamwork_choices,
            )
        finally:
            delattr(obj, "_modal_announced_kicked")
            delattr(obj, "_modal_announced_teamwork")
            delattr(obj, "_modal_override_condition_met")

    def _modal_override_active(self, obj: GameObject) -> bool:
        """Evaluate the closed conditional-modal vocabulary at choice time."""
        override = getattr(obj, "spell_modes_override", None) or {}
        condition = override.get("condition")
        if isinstance(condition, str):  # compatibility with pre-PAR-55 fixtures
            condition = {"kind": condition}
        if not isinstance(condition, dict):
            return False
        kind = condition.get("kind")
        if kind == "kicked":
            return bool(getattr(obj, "_modal_announced_kicked", obj.kicker_count))
        if kind == "additional_cost_paid":
            return bool(getattr(obj, "additional_cost_paid", False))
        if kind == "teamwork_paid":
            return bool(getattr(obj, "_modal_announced_teamwork", getattr(obj, "teamwork_paid", False)))
        if hasattr(obj, "_modal_override_condition_met"):
            return bool(obj._modal_override_condition_met)
        player = next((p for p in self.state.players if p.id == obj.controller_id), None)
        if player is None:
            return False
        if kind == "controls_subtype_as_cast":
            subtype = str(condition.get("subtype", "")).lower()
            return bool(subtype) and any(
                o.controller_id == player.id and subtype in o.card.type_line.lower().split()
                for o in self.state.battlefield
            )
        if kind == "controls_commander_as_cast":
            return any(o.controller_id == player.id and o.is_commander for o in self.state.battlefield)
        if kind == "card_types_in_graveyard_at_least":
            types: set[str] = set()
            for card in player.graveyard:
                types |= card.type_words
            types.discard("permanent")
            return len(types) >= int(condition.get("amount", 0))
        if kind == "life_total_exactly":
            return player.life == int(condition.get("amount", -1))
        if kind == "descended_this_turn":
            return player.id in (getattr(self.state, "permanent_card_to_graveyard_this_turn", set()) or set())
        return False

    def _modal_choice_config(self, obj: GameObject) -> tuple[int, bool]:
        """Return the active exact/minimum count for a modal spell."""
        choose = int(getattr(obj, "spell_modes_choose", 1))
        at_least = bool(getattr(obj, "spell_modes_at_least", False))
        override = getattr(obj, "spell_modes_override", None) or {}
        if self._modal_override_active(obj):
            choose = int(override.get("choose", choose))
            at_least = bool(override.get("at_least", False))
        return choose, at_least
    def _effects_for_mode(self, obj: GameObject, mode: Any) -> list[Any]:
        """The `GameEffect`s a modal spell's chosen ``mode`` resolves with.

        ``mode`` is an index into ``obj.spell_modes`` (only when
        ``obj.spell_modes_choose == 1``), the literal ``"both"`` (RULE
        700.2e — both modes' effects, in printed order), or a list/tuple of
        distinct indices: exactly ``obj.spell_modes_choose`` of them (RULE
        700.2 "choose *N*", ``N>=2``), or at least that many when
        ``obj.spell_modes_at_least`` (RULE 700.2 "choose *N* or more —",
        ``N>=1``) — `_modal_cast_actions` offers one action per legal
        combination either way. Combined effects always run in *printed*
        order, not the order given in ``mode``. Raises for an out-of-range/
        wrong-length/duplicate index, or a "both" not actually offered
        (`obj` has no ``spell_modes`` at all, or isn't
        ``spell_modes_or_both``, or doesn't have exactly the two modes RULE
        700.2e's "or both" implies).
        """
        modes = list(getattr(obj, "spell_modes", None) or [])
        choose, at_least = self._modal_choice_config(obj)
        repeatable = getattr(obj, "spell_modes_repeatable", False)
        if mode == "both":
            # RULE 700.2e gives both modes away for free (and only ever on a
            # two-mode block); RULE 702.42a's Entwine sells "choose *all*"
            # for its own additional cost — whether that cost is actually
            # being paid is checked by `_cast_current_face`, not here.
            or_both = getattr(obj, "spell_modes_or_both", False) and len(modes) == 2
            if not or_both and self._entwine_cost(obj) is None:
                raise ValueError(f"{obj.name} has no 'choose both' mode")
            effects: list[Any] = []
            for entry in modes:
                effects.extend(entry["effects"])
            return effects
        if isinstance(mode, (list, tuple)):
            indices = list(mode)
            count_ok = len(indices) >= choose if at_least else len(indices) == choose
            valid = (
                count_ok
                and (repeatable or len(set(indices)) == len(indices))
                and all(isinstance(i, int) and 0 <= i < len(modes) for i in indices)
            )
            if not valid:
                raise ValueError(f"{obj.name}: invalid mode combination {mode!r}")
            effects = []
            for i in sorted(indices):
                effects.extend(modes[i]["effects"])
            return effects
        if choose != 1 or not isinstance(mode, int) or not (0 <= mode < len(modes)):
            raise ValueError(f"{obj.name}: invalid mode {mode!r}")
        return list(modes[mode]["effects"])
    def _mode_description(self, obj: GameObject, mode: Any) -> str:
        """A modal spell's chosen ``mode`` as UI label text."""
        modes = list(getattr(obj, "spell_modes", None) or [])
        if mode == "both":
            return " + ".join(entry.get("description", "") for entry in modes)
        if isinstance(mode, (list, tuple)):
            return " + ".join(
                modes[i].get("description", "") for i in sorted(mode) if 0 <= i < len(modes)
            )
        if isinstance(mode, int) and 0 <= mode < len(modes):
            return modes[mode].get("description", "")
        return ""
    @contextmanager
    def _mode_effects_applied(self, obj: GameObject, mode: Optional[Any]):
        """Temporarily point ``obj.spell_effects`` at a modal spell's chosen
        mode(s) (RULE 601.2b: the mode is chosen before targets/costs).

        `has_legal_targets`/`RulesEngine._effects_for_spell` both read
        ``obj.spell_effects`` — swapping it here (and restoring it on exit,
        success or failure) means neither needs to know modes exist at all,
        the same "no top-level change needed" trick `switch_to_face` uses
        for a second castable face. A no-op for a non-modal ``obj``
        (``spell_modes`` unset/empty).
        """
        modes = getattr(obj, "spell_modes", None)
        if not modes:
            yield
            return
        if mode is None:
            raise ValueError(f"{obj.name} requires a mode choice (RULE 601.2b)")
        previous = list(getattr(obj, "spell_effects", None) or [])
        obj.spell_effects = self._effects_for_mode(obj, mode)
        try:
            yield
        finally:
            obj.spell_effects = previous
    # -- RULE 702.51 Convoke / 702.66 Delve / 702.126 Improvise (PAR-23) ----
    #
    # Three keywords that let a spell's *generic* cost be paid with a
    # non-mana resource — a tapped creature you control (Convoke), a card
    # exiled from your graveyard (Delve), a tapped artifact you control
    # (Improvise). Modeled as a single opt-in ``help_pay`` cast flag (the
    # same "second offered action" shape `evoke` uses), not one flag each,
    # since no cached card carries two of them. Generic-only (Convoke's RULE
    # 702.51b "or one mana of that creature's colour" is a documented
    # simplification), and auto-*minimal* at the real cast (tap/exile only
    # what the pool still can't cover) — a per-resource "which creatures"
    # picker is a future UI refinement, not a rules gap.

    _HELP_PAY_KEYWORDS: tuple[str, ...] = ("convoke", "delve", "improvise")

    def _help_pay_keyword(self, obj: GameObject) -> Optional[str]:
        """Which of Convoke/Delve/Improvise ``obj`` has printed (or ``None``)."""
        for kw in self._HELP_PAY_KEYWORDS:
            if combat.has(obj, kw):
                return kw
        return None

    def _cast_help_pool(self, player: Player, obj: GameObject) -> list[GameObject]:
        """The resources available to help pay ``obj``'s generic cost, in the
        order they'd be spent: untapped creatures (Convoke) / untapped
        artifacts (Improvise) you control, or cards in your graveyard
        (Delve)."""
        kw = self._help_pay_keyword(obj)
        if kw == "convoke":
            return [
                o for o in self.state.battlefield
                if o.controller_id == player.id and o.is_creature
                and not o.tapped and o is not obj
            ]
        if kw == "improvise":
            return [
                o for o in self.state.battlefield
                if o.controller_id == player.id and combat._is_artifact(o) and not o.tapped
            ]
        if kw == "delve":
            return list(player.graveyard)
        return []

    @staticmethod
    def _generic_of(cost: "ManaCost") -> int:
        from ...models.mana_cost import GENERIC

        return sum(s.amount for s in cost.symbols if s.kind == GENERIC)

    def _consume_cast_help(
        self, player: Player, obj: GameObject, cost: "ManaCost"
    ) -> "ManaCost":
        """Spend the *minimum* number of help resources (RULE 702.51/702.66/
        702.126) needed for ``player``'s pool to be able to pay ``cost``,
        returning the reduced cost. Called from the real cast path only —
        `can_cast`/previews use `_cast_help_capacity` for the best case."""
        pool = iter(self._cast_help_pool(player, obj))
        while self._generic_of(cost) > 0 and not player.mana_pool.can_pay(cost):
            res = next(pool, None)
            if res is None:
                break
            if res.zone == Zone.GRAVEYARD:
                self.rules.exile(res)  # RULE 702.66: "Each card you exile … pays for {1}."
            else:
                self.rules.set_tapped(res, True)  # RULE 702.51c/702.126b
            cost = cost.reduce_generic(1)
        return cost

    def _cast_help_capacity(self, player: Player, obj: GameObject, cost: "ManaCost") -> "ManaCost":
        """``cost`` with its generic lowered by the *most* the available help
        resources could pay (the offer-time upper bound — `can_cast` and
        `_cast_action`'s displayed cost use this)."""
        return cost.reduce_generic(min(self._generic_of(cost), len(self._cast_help_pool(player, obj))))

    def _auto_tap_for_cast_if_needed(
        self,
        player: Player,
        obj: GameObject,
        x: int,
        face: str = "front",
        mode: Optional[Any] = None,
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        free: bool = False,
        alt_cost: bool = False,
        mutate: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        evoke: bool = False,
        exile_discount: int = 0,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        targets: Optional[list[Any]] = None,
        help_pay: bool = False,
        pay_additional: bool = False,
        teamwork: bool = False,
        teamwork_choices: Optional[list[int]] = None,
    ) -> None:
        """"Automatisches Tappen": best-effort, silent mana top-up right
        before a real cast attempt — only when ``obj`` would already be
        castable except for the real pool falling short (`can_cast`'s
        ``assume_mana_available`` probe both proves everything *else* about
        the cast is legal right now, and confirms this isn't already a
        no-mana alternative cost, before a single mana source is touched).
        Uses `auto_tap_for`/`game/mana_potential.py`'s `find_tap_plan`,
        which never spends a sacrifice- or hand-exile-cost source (a
        Treasure, a Spirit Guide) — only plain tap (± life) sources,
        exactly what a player would expect "just tap what's needed" to
        mean. A `ValueError` (no plan found even among those) is swallowed
        here — the real `can_cast` check right after this call then fails
        normally, with its usual error message, unchanged from before this
        existed.

        ``face`` (MEC-13) is threaded through to `can_cast`/`effective_
        cast_cost` so this also runs for a `face="face_down"` cast — RULE
        702.37a's flat {3} morph/disguise cost, which `effective_cast_cost`
        already resolves correctly via `_face_card` (it doesn't need
        ``obj`` to already be turned face down to compute it); the
        `cast_spell` `face_down` branch calls this *before* the actual
        face-down swap for exactly that reason.

        ``kicker_x`` (MEC-13, PAR-7 — Emblazoned Golem-shaped) was missing
        here entirely before this fix: `_cast_current_face` calls this with
        every *other* real cast parameter (``x``, ``kicked``, …) but had
        never threaded a caller-announced Kicker-{X} through, so a Kicker
        spell whose own cost is variable always auto-tapped for
        ``kicker_x=0`` regardless of what was actually announced —
        silently under-tapping (or auto-tapping just fine for a value that
        then failed the real, correctly-costed `can_cast` right after).
        Zeroed under `_kicker_x_distinct_colors` exactly as `effective_
        cast_cost` itself zeroes it, since that portion is paid separately
        (`ManaPool.pay_distinct_colors`), never through auto-tap.
        """
        if free or alt_cost or self.can_cast(
            player, obj, x, face=face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, free=free,
            alt_cost=alt_cost, mutate=mutate, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            targets=targets, help_pay=help_pay, pay_additional=pay_additional,
            teamwork=teamwork, teamwork_choices=teamwork_choices,
        ):
            return
        if not self.can_cast(
            player, obj, x, face=face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, free=free,
            alt_cost=alt_cost, mutate=mutate, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            targets=targets, assume_mana_available=True, help_pay=help_pay, pay_additional=pay_additional,
            teamwork=teamwork, teamwork_choices=teamwork_choices,
        ):
            return  # illegal for a reason other than mana — never auto-tap
        cost = self.effective_cast_cost(
            player, obj, x, face=face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, mutate=mutate,
            entwine=entwine, evoke=evoke, exile_discount=exile_discount, targets=targets, help_pay=help_pay,
            pay_additional=pay_additional,
        )
        try:
            self.auto_tap_for(player, cost=cost)
        except ValueError:
            pass
    def _cast_current_face(
        self,
        player: Player,
        obj: GameObject,
        targets: Optional[list[Any]],
        x: int,
        mode: Optional[Any] = None,
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        target_groups: Optional[list[list[Any]]] = None,
        free: bool = False,
        alt_cost: bool = False,
        mutate: bool = False,
        mutate_under: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        evoke: bool = False,
        exile_discount: int = 0,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        help_pay: bool = False,
        bestow: bool = False,
        pay_additional: bool = False,
        teamwork: bool = False,
        teamwork_choices: Optional[list[int]] = None,
    ):
        """The common cast body, reading whatever `obj.card` currently is.

        ``free=True`` (RULE 601.2f-adjacent condition-gated free-cast
        alternative cost — see `can_cast`) skips mana payment entirely via
        `RulesEngine.cast_without_paying`, instead of the ordinary
        `RulesEngine.cast_spell` mana-cost path. ``alt_cost=True`` (RULE
        118.9, MEC-15) does the same, then pays `GameObject.alt_cast_cost`
        (`_pay_alt_cast_cost`) instead of nothing. ``bestow=True`` (RULE
        702.103) pays the Bestow cost (`_bestow_cost`) instead of the mana
        cost — an ordinary paid cast with a substituted cost; ``obj`` is
        already reshaped to a bestowed Aura spell by the `cast_spell`
        branch that got here (`RulesEngine._begin_bestow`).
        """
        if mode == "both" and not getattr(obj, "spell_modes_or_both", False):
            # RULE 702.42a: on an ordinary "choose one" block, "choose all"
            # exists only as Entwine's paid upgrade — never for free. (A
            # RULE 700.2e ``or_both`` block hands it over unpriced, hence
            # the guard only on the other branch.)
            if not entwine or self._entwine_cost(obj) is None:
                raise ValueError(f"{obj.name}: 'both' requires paying the entwine cost")
        with self._mode_effects_applied(obj, mode):
            # RULE 601.2c/601.2b ordering: X is announced *before* targets
            # are chosen, so a target requirement whose own bound reads {X}
            # ("target permanent with mana value X or less" — March of
            # Otherworldly Light, MEC-43; "up to X target creatures" —
            # March of Swirling Mist, MEC-42) needs it stamped here already,
            # not only after `cast_spell` commits for real below (`targeting.
            # legal_targets`'s own ``"x"``/``"-x"`` sentinel resolution reads
            # this same field). Harmless to stamp early: the real cast path
            # re-stamps the identical value once resolved.
            if x:
                obj.x_paid = x
            # RULE 702.103: a bestowed cast reads its cost off ``face=
            # "bestow"`` in `can_cast`/`effective_cast_cost` (``obj`` has no
            # ``face`` param of its own to carry down here) — every other
            # cast keeps the default "front".
            bestow_face = "bestow" if bestow else "front"
            self._auto_tap_for_cast_if_needed(
                player, obj, x, face=bestow_face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, free=free,
                alt_cost=alt_cost, mutate=mutate, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                targets=targets, help_pay=help_pay, pay_additional=pay_additional,
                teamwork=teamwork, teamwork_choices=teamwork_choices,
            )
            if not self.can_cast(
                player, obj, x, face=bestow_face, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, free=free,
                alt_cost=alt_cost, mutate=mutate, bargained=bargained, entwine=entwine, evoke=evoke, exile_discount=exile_discount,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                targets=targets, help_pay=help_pay, pay_additional=pay_additional,
                teamwork=teamwork, teamwork_choices=teamwork_choices,
            ):
                raise ValueError(f"{player.id} cannot cast {obj.name} now")
            # RULE 601.2c: a spell that requires a target can't be cast unless
            # a legal target is available — the same check that locks the offer.
            if not self.has_legal_targets(player, obj):
                raise ValueError(f"{obj.name} has no legal target")
            # RULE 115.1: a spell announcing 2+ requirements needs its flat,
            # in-printed-order picks split per targeting effect, or every
            # effect would read the same first target ("target creature you
            # control gets +1/+2 …. It fights target creature you don't
            # control." would pump and fight the same creature). A caller
            # that can *decline* an optional requirement must still send
            # explicit groups — `partition_targets` returns None rather than
            # guess which slot was skipped.
            if target_groups is None:
                target_groups = partition_targets(spell_target_specs(obj), targets)
            # RULE 903.8: record this command-zone cast so the next one is
            # taxed {2} more. Read *before* the cast moves the card off the
            # command zone.
            from_command = obj.is_commander and obj in player.command
            # RULE 702.34a: likewise read *before* the cast moves the card
            # off the graveyard — only a Flashback cast is exiled instead of
            # going to the graveyard on resolution (Escape has no such
            # after-resolving clause).
            graveyard_keyword = (
                self._graveyard_cast_keyword(obj) if obj in player.graveyard else None
            )
            # Lurrus-shaped standing permission, read *before* the cast for
            # the same "off the object's current zone" reason as above — only
            # relevant when no closed-vocabulary keyword already covers it.
            graveyard_grant = (
                graveyard_cast_grant_for(player, self.state, obj.card)
                if obj in player.graveyard and graveyard_keyword is None
                else None
            )
            # MEC-44: RULE 601.3a — remembered once, here, since whether a
            # sorcery could have been cast depends on the board at THIS
            # moment (own main phase, empty stack, own turn), not whatever
            # it is by the time a later effect reads it ("if you cast it
            # any time a sorcery couldn't have been cast, `<downside>`.",
            # Necromancy-shaped) — legal only via some flash grant when
            # this is true, never RULE 601.3a's own default window.
            obj.cast_outside_sorcery_speed = not (
                player is self.state.active_player and self._in_main_phase() and not self.state.stack
            )
            if free:
                result = self.rules.cast_without_paying(player, obj, targets, target_groups)
            elif bestow:
                # RULE 702.103a: pay the Bestow cost in place of the mana
                # cost — otherwise an ordinary paid cast (`rules.cast_spell`
                # with an explicit ``cost``), unlike the no-mana free/
                # alt-cost paths above.
                cost = self.effective_cast_cost(player, obj, x, face="bestow")
                result = self.rules.cast_spell(
                    player, obj, targets, x, cost=cost, target_groups=target_groups,
                )
            elif alt_cost:
                # RULE 118.9 (MEC-15): no mana leaves the pool at all — the
                # spell goes on the stack for free, then its controller
                # pays the alternative cost instead, the same "free push,
                # pay something else after" order the RULE 118-life-payment
                # branch just below uses.
                result = self.rules.cast_without_paying(player, obj, targets, target_groups)
                self._pay_alt_cast_cost(
                    player, obj,
                    getattr(obj, "alt_cast_cost", None)
                    or continuous.granted_alt_cast_cost_for(self.state, player, obj.card),
                )
                if getattr(obj, "dash", False):
                    # RULE 702.109c/d (PAR-26): a creature cast for its dash
                    # cost gains haste and is bounced at the next end step —
                    # consumed at resolution, next to `cast_via_evoke`.
                    obj.cast_via_dash = True
            elif self._top_library_life_payment(player, obj):
                # Bolas's Citadel-shaped: no mana leaves the pool — the
                # spell goes on the stack for free, then its controller
                # pays life equal to its mana value as the cost instead
                # (RULE 118), mirroring `RulesEngine.cast_spell`'s own
                # "lose_life *after* the card leaves its current zone" order.
                result = self.rules.cast_without_paying(player, obj, targets, target_groups)
                self.rules.lose_life(player, obj.card.converted_mana_cost, cause="cost")
            else:
                cost = self.effective_cast_cost(
                    player, obj, x, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback, mutate=mutate,
                    entwine=entwine, evoke=evoke, exile_discount=exile_discount, targets=targets,
                    pay_additional=pay_additional,
                )
                if help_pay and self._help_pay_keyword(obj) is not None:
                    # RULE 702.51/702.66/702.126 (PAR-23): spend the minimum
                    # help resources the pool still can't cover, *after*
                    # `_auto_tap` has already put in what lands it could —
                    # then pay the (further-reduced) mana cost as normal.
                    cost = self._consume_cast_help(player, obj, cost)
                result = self.rules.cast_spell(player, obj, targets, x, cost=cost, target_groups=target_groups)
                # RULE 702.74b's Incarnation-cycle Evoke cost is paid while
                # casting, just like the Force-of-Will-style hand-exile
                # alternative cost it reuses.  The spell has already left
                # hand, so the selector can never pay by exiling itself.
                if evoke:
                    evoke_exile_color = self._evoke_exile_hand_color(obj)
                    if evoke_exile_color:
                        victim = self._exile_hand_card_candidate(player, evoke_exile_color)
                        if victim is not None:
                            self.rules.exile(victim)
                if kicked and kicker_x > 0 and self._kicker_x_distinct_colors(obj):
                    # PAR-7: Kicker's own distinct-color-capped {X} was
                    # excluded from ``cost`` above (`effective_cast_cost`) and
                    # is paid here instead, against whatever `cost` left in
                    # the pool — `can_cast` already verified this sequence is
                    # payable.
                    player.mana_pool.pay_distinct_colors(kicker_x)
                if exile_discount:
                    # March of Swirling Mist (MEC-42): the additional cost
                    # itself, paid *after* the (already-discounted) mana
                    # cost — RULE 601.2b, same "cost as part of casting"
                    # ordering as the sacrifice/discard additional costs
                    # right below. Auto-picked, the same "no chooser for an
                    # equally-valid pick" idiom this engine's other untargeted
                    # picks already use, since which matching-color card is
                    # exiled has no further mechanical consequence.
                    spec = continuous.exile_discount_spec_for(obj)
                    color = str((spec or {}).get("color", "U"))
                    for _ in range(exile_discount):
                        victim = self._exile_hand_card_candidate(player, color, exclude=obj)
                        if victim is not None:
                            self.rules.exile(victim)
            # RULE 601.2b/601.2h: an additional cost is paid as part of
            # casting, not resolving — so it stays paid even if the spell is
            # later countered. Paid *after* the mana cost (just above) so a
            # Phyrexian-mana payment reads the player's life before any
            # "pay N life" additional cost reduces it.
            self._pay_additional_cast_cost(
                player, obj, getattr(obj, "additional_cast_cost", None), x,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                pay_additional=pay_additional,
            )
            # RULE 601.2b (PAR-30): record whether the additional cost was
            # paid — a *mandatory* one always (it was), an *optional* "you
            # may <…>" one only when the caller chose the `pay_additional`
            # cast variant (`_offer_cast`). Read by a following
            # `ConditionalEffect(condition={"additional_cost_paid": …})`.
            _add_cost = getattr(obj, "additional_cast_cost", None)
            obj.additional_cost_paid = _add_cost is not None and (
                not getattr(obj, "additional_cast_cost_optional", False) or pay_additional
            )
            # RULE 701.67c: "an ability that triggers whenever a player
            # waterbends triggers whenever that player pays a waterbend
            # cost" — the waterbend additional cast cost has just been paid
            # (it is folded into the mana total in `effective_cast_cost`, so
            # there is no earlier discrete moment). Fires EventType.BENT for
            # Avatar Aang's "whenever you … waterbend" trigger. ``amount``
            # left 0 — the bending verb, not its {N}, is what any trigger
            # reads.
            if (
                obj.additional_cost_paid
                and getattr(_add_cost, "help_pay_kind", None) == "waterbend"
            ):
                self.rules.record_bend(player, "waterbend", source=obj)
            # RULE 702.33b: record how many times Kicker was paid, so a
            # resolve-time effect that reads "if this spell was kicked" (a
            # follow-up, not yet parsed) has something to consult.
            obj.kicker_count = kicked
            # RULE 702.33b/PAR-7: record Kicker's own announced {X}, when it
            # has one — consulted by `_apply_entry_counters`'s
            # ``kicked_x_scale`` shape (Emblazoned Golem's "it enters with X
            # +1/+1 counters on it").
            obj.kicker_x_paid = kicker_x if kicked else 0
            # RULE 702.27a: record whether Buyback was paid — consulted by
            # `RulesEngine.resolve_top_of_stack` to route the spell back to
            # hand instead of the graveyard.
            obj.buyback_paid = buyback
            obj.teamwork_paid = False
            if teamwork:
                selected = self._teamwork_selection(player, obj, teamwork_choices)
                if selected is None:
                    raise ValueError(f"{obj.name}: illegal Teamwork payment")
                for creature in selected:
                    self.rules.set_tapped(creature, True)
                obj.teamwork_paid = True
            if mutate:
                # RULE 702.140a/601.2c: the host must be a legal mutate
                # target — checked here rather than by the ordinary
                # targeting machinery, since a mutate creature spell carries
                # no targeting *effect* for that machinery to read.
                host = next((t for t in (targets or []) if isinstance(t, GameObject)), None)
                if host is None or host not in self.legal_mutate_hosts(player, obj):
                    raise ValueError(f"{obj.name}: illegal mutate host")
            # RULE 702.140b: record a Mutate cast — consulted by
            # `RulesEngine._resolve_permanent_spell`, which merges the spell
            # onto its target instead of letting it enter as its own
            # permanent.
            obj.cast_via_mutate = mutate
            # RULE 702.140b: "over **or** under" is chosen as the spell is
            # cast, not as it resolves.
            obj.mutate_under = mutate and mutate_under
            # RULE 701.x Bargain: the optional "sacrifice an artifact,
            # enchantment, or token as you cast this spell" cost, charged
            # here alongside every other additional cost and recorded so an
            # "if this spell was bargained" condition can read it.
            obj.bargained = False
            if bargained:
                victim = self._bargain_candidate(player)
                if victim is not None:
                    self.rules.put_into_graveyard(victim)
                    obj.bargained = True
            # RULE 702.34a: record a Flashback cast — consulted by
            # `RulesEngine.resolve_top_of_stack` to exile the spell instead
            # of returning it to the graveyard on resolution.
            obj.cast_via_flashback = graveyard_keyword == "flashback"
            # RULE 702.138 (PAR-60, Woe Strider's "~ escapes with two +1/+1
            # counters on it"): record an Escape cast so a hand-authored ETB
            # can gate an enters-with-counters rider on it. Reassigned every
            # cast (like ``cast_via_flashback``), so a later normal recast
            # this same turn clears it.
            obj.cast_via_escape = graveyard_keyword == "escape"
            # RULE 702.74a: record an Evoke cast — consulted right after
            # `_resolve_permanent_spell` adds the object to the battlefield
            # to sacrifice it (a *consequence* of entering, not a
            # replacement of it, so its own ETB trigger still fires first).
            obj.cast_via_evoke = evoke
            # Lurrus-shaped: record the casting turn so `_move_to_graveyard`
            # can honor the permission source's own "if a spell cast this
            # way would be put into a graveyard this turn, exile it
            # instead" clause — reassigned every cast (like the flag just
            # above), so a later normal recast this same turn clears it.
            obj.cast_via_graveyard_cast_permission_until_turn = (
                self.state.internal_turn.number
                if graveyard_grant is not None and graveyard_grant.exile_if_would_be_put_into_graveyard
                else None
            )
            # RULE 702.138b: Escape's own "exile N other cards from your
            # graveyard" cost, paid as part of casting (like any other
            # additional cost) now that ``obj`` itself has left the
            # graveyard (so it can't accidentally exile itself).
            if graveyard_keyword == "escape":
                escape_cost = self._escape_cost(obj)
                if escape_cost is not None and escape_cost.exile_from_graveyard:
                    self._pay_escape_graveyard_cost(player, escape_cost.exile_from_graveyard)
            # RULE 702.81a: Retrace's "discard a land card" additional cost,
            # paid now that ``obj`` itself has left the graveyard (MEC-53).
            if graveyard_keyword == "retrace":
                self._pay_retrace_discard(player)
            # RULE 500.4-adjacent: record this use of a Lurrus-shaped
            # "once during each of your turns" standing permission against
            # its *granting* permanent, not the cast card — untapped again
            # by `_step_untap` alongside `activated_loyalty_this_turn`.
            if graveyard_grant is not None and graveyard_grant.source is not None:
                graveyard_grant.source.graveyard_casts_this_turn += 1
                if graveyard_grant.per_permanent_type:
                    from ..graveyard_cast import permanent_types
                    used = getattr(graveyard_grant.source, "graveyard_cast_types_this_turn", set())
                    available = permanent_types(obj.card) - used
                    if available:
                        graveyard_grant.source.graveyard_cast_types_this_turn = used | {sorted(available)[0]}
        if from_command:
            player.commander_casts[obj.instance_id] = (
                player.commander_casts.get(obj.instance_id, 0) + 1
            )
        # RULE 117.3c: taking an action reclaims priority for its taker.
        self.give_priority(player)
        return result
    def _can_pay_additional_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        cost: Optional["ActivationCost"],
        x: int,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        pay_additional: bool = False,
    ) -> bool:
        """RULE 601.2b: whether ``player`` can pay a spell's "as an
        additional cost to cast this spell, …" clause right now.

        A narrow subset of `_can_pay_activation_cost` — only the three
        shapes the oracle-text parser recognizes for it (sacrifice/discard/
        pay life); there's no mana or {T}/{Q} portion to an additional cost.
        A ``pay_life`` of `costs.PAY_LIFE_X` checks the spell's own
        announced ``x`` rather than a fixed amount (RULE 601.2b: "pay X
        life" is tied to *this* spell's X, chosen in the same announcement).
        ``obj`` — the spell itself, still sitting in hand at legality-check
        time — is excluded from its own "discard a card" count: it isn't a
        legal discard candidate for its own cost.

        ``sacrifice_choice``/``discard_choices`` are the same RULE 602.1 cost
        *choices* `can_activate`'s own ``sacrifice_choice``/``tap_choices``
        are — the caster's own pick, validated against the legal candidates;
        ``None`` falls back to an auto-pick (non-interactive callers, and
        existence-only checks like `legal_actions` before a choice has been
        made yet).
        """
        if cost is None:
            return True
        # Yasharn, Implacable Earth (MEC-40): "Players can't pay life or
        # sacrifice nonland permanents to cast spells or activate
        # abilities." — checked before the ordinary payability gates below
        # so a Yasharn on the battlefield makes the whole additional cost
        # illegal to pay, not merely unaffordable.
        if cost.sacrifice and cost.sacrifice != "land" and continuous.cost_restricted(
            self.state, "sacrifice_nonland_permanent"
        ):
            return False
        if cost.pay_life and continuous.cost_restricted(self.state, "pay_life"):
            return False
        if cost.sacrifice and self._sacrifice_candidate(
            player, obj, cost.sacrifice, chosen_id=sacrifice_choice
        ) is None:
            return False
        if cost.discard and cost.discard != DISCARD_HAND:
            if self._resolve_discard_cost(
                player, cost.discard, discard_choices, exclude=obj
            ) is None:
                return False
        if cost.pay_life:
            amount = x if cost.pay_life == PAY_LIFE_X else cost.pay_life
            if player.life < amount:
                return False
        # RULE 701.4a / 701.68 (PAR-29): a `behold` or `blight` additional
        # cost never blocks casting — the "or pay {N}" alternative (the
        # documented-dropped half) means a player who can't behold / has no
        # creature to blight still gets to cast. `_pay_additional_cast_cost`
        # does the reveal / -1/-1 counters if able.
        # RULE 601.2b (PAR-30): "behold a `<type>` **and exile it**" (the
        # Lorwyn "Champion" cycle) has *no* alternative — unlike `behold`, it
        # blocks casting when the caster controls no matching permanent and
        # holds no matching card.
        if cost.behold_exile and self._behold_exile_candidate(
            player, obj, cost.behold_exile
        ) is None:
            return False
        # RULE 601.2b (PAR-41): "exile N [<type>] cards from your graveyard"
        # (Cobbled Lancer / Abhorrent Oculus) — a hard gate, no alternative:
        # the caster's graveyard must hold at least N matching cards. The
        # spell itself is still in hand at check time, so it's never one of
        # them anyway.
        if cost.exile_from_graveyard and len(
            self._graveyard_exile_cost_candidates(
                player, cost.exile_from_graveyard, cost.exile_from_graveyard_filter
            )
        ) < cost.exile_from_graveyard:
            return False
        # RULE 701.4a (PAR-30, Celestial Reunion): "you may choose a creature
        # type and behold two creatures of that type." — an *optional*
        # additional cost. Only its `pay_additional` cast variant needs the
        # payability check (the plain cast never touches it); when nothing
        # qualifies, `_offer_cast` must not offer that variant.
        if pay_additional and cost.behold_two_shared_type and self._behold_two_shared_type(
            player, obj
        ) is None:
            return False
        return True
    def _behold_two_shared_type(
        self, player: Player, obj: GameObject
    ) -> Optional[str]:
        """A creature type ``player`` has at least two of, counting permanents
        they control and creature cards in hand (`RulesEngine.behold`'s own
        two zones), to pay Celestial Reunion's "choose a creature type and
        behold two creatures of that type" optional additional cost — or
        ``None`` if no such type exists. ``obj`` (the spell itself) is kept
        out of the hand pool. Auto-picks the first qualifying type (the
        "no chooser in this MVP" idiom); type lists come off the printed
        type line, sufficient at cost-payment time.
        """
        from collections import Counter

        def _subs(card: "GameObject") -> list[str]:
            line = (getattr(card.card, "type_line", "") or "")
            if "creature" not in line.lower() or "—" not in line:
                return []
            return [w.lower() for w in line.split("—", 1)[1].split()]

        counts: "Counter[str]" = Counter()
        for perm in self.state.permanents_controlled_by(player.id):
            if getattr(perm, "is_creature", False):
                counts.update(set(_subs(perm)))
        for card in player.hand:
            if card is obj:
                continue
            counts.update(set(_subs(card)))
        for kind, n in counts.items():
            if n >= 2:
                return kind
        return None
    def _behold_exile_candidate(
        self, player: Player, obj: GameObject, quality: str
    ) -> Optional[GameObject]:
        """A permanent ``player`` controls with subtype ``quality``, or a
        card of that subtype in their hand, eligible to pay a ``behold_exile``
        additional cast cost (RULE 701.4a — "behold a `<type>` and exile
        it"). ``obj`` (the spell itself, still in hand at legality-check
        time) is kept out of its own hand pool.

        **Documented simplification:** an auto-pick, not an interactive one —
        the same "no chooser in this MVP" idiom `behold` / the other
        additional-cost payers use. Battlefield first (matching
        `RulesEngine.behold`'s own scan order and the reminder text), lowest
        mana value within each zone, so the least is spent for a card that
        comes back to hand later anyway.
        """
        on_bf = sorted(
            (
                o
                for o in self.state.permanents_controlled_by(player.id)
                if continuous.has_subtype(o, quality)
            ),
            key=lambda o: o.card.converted_mana_cost,
        )
        if on_bf:
            return on_bf[0]
        in_hand = sorted(
            (
                c
                for c in player.hand
                if c is not obj and continuous.has_subtype(c, quality)
            ),
            key=lambda c: c.card.converted_mana_cost,
        )
        return in_hand[0] if in_hand else None
    def _pay_additional_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        cost: Optional["ActivationCost"],
        x: int,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        pay_additional: bool = False,
    ) -> None:
        """Pay a spell's additional cast cost (RULE 601.2b), assumed already
        checked payable by `_can_pay_additional_cast_cost`/`can_cast` (with
        the same ``sacrifice_choice``/``discard_choices``, if any).

        A real RULE 602.1 cost choice (ENG-3), the same
        ``sacrifice_choice``/``tap_choices``-as-an-action-parameter shape
        `activate_ability` already uses for an activated ability's cost —
        cost payment is one synchronous call inside `cast_spell`, so it
        can't pause for a `request_choose_objects` chooser the way an
        *effect* resolving can (see `RulesEngine.sacrifice`, ENG-2's
        upgrade); the choice has to already be known when this runs.
        ``obj`` — the spell itself — is never a valid sacrifice candidate at
        this point (it's a spell on the stack, not a permanent), so passing
        it as the sacrifice ability's "self" source is only ever a no-op
        fallback.
        """
        if cost is None:
            return
        # RULE 601.2b (PAR-30): an *optional* "you may <…>." additional cost
        # the caster declined (no `pay_additional`) is paid nothing at all —
        # its mana portion is already gated out of `effective_cast_cost`, and
        # its non-mana portion (sacrifice/discard/…) must not fire here.
        if getattr(obj, "additional_cast_cost_optional", False) and not pay_additional:
            return
        obj.sacrificed_cost_mana_value = None
        if cost.sacrifice:
            victim = self._sacrifice_candidate(
                player, obj, cost.sacrifice, chosen_id=sacrifice_choice
            )
            if victim is not None:
                # RULE 601.2b: stash what was sacrificed *before* it leaves,
                # so a resolving effect can still read "the sacrificed
                # creature's mana value" (Eldritch Evolution/Neoform) —
                # `StackItem.x` only ever threads an announced {X}.
                obj.sacrificed_cost_mana_value = victim.card.converted_mana_cost
                # RULE 701.16c: sacrifice isn't destruction — regeneration
                # can't save it — so this bypasses `destroy` and its
                # regeneration-shield check.
                self.rules.put_into_graveyard(victim)
        if cost.discard:
            if cost.discard == DISCARD_HAND:
                self.rules.discard(player, len(player.hand))
            else:
                chosen = self._resolve_discard_cost(
                    player, cost.discard, discard_choices, exclude=obj
                )
                for card in chosen or []:
                    self.rules.discard_specific(card)
        if cost.pay_life:
            amount = x if cost.pay_life == PAY_LIFE_X else cost.pay_life
            self.rules.lose_life(player, amount, cause="cost")
        if cost.exile_from_graveyard:
            # RULE 601.2b (PAR-41): `_can_pay_additional_cast_cost` already
            # confirmed enough matching cards are there.
            for victim in self._graveyard_exile_cost_candidates(
                player, cost.exile_from_graveyard, cost.exile_from_graveyard_filter
            ):
                self.rules.exile(victim)
        if cost.behold:
            # RULE 701.4a (PAR-29): reveal a matching permanent/hand card if
            # one exists. Non-blocking — `_can_pay_additional_cast_cost`
            # never rejects a behold cost (the "or pay {N}" alternative is
            # the documented-dropped half), so this is a best-effort reveal:
            # a `behold` returning False just means nothing was revealed.
            self.rules.behold(player, cost.behold, source=obj)
        if cost.blight:
            # RULE 701.68 (PAR-29): "blight N or pay {M}" as an additional
            # cast cost (Bogslither's Embrace/Wild Unraveling). Same
            # non-blocking, "or pay {M}"-dropped treatment as `behold`:
            # `_can_pay_additional_cast_cost` never rejects it, so this is
            # best-effort — auto-picking the least-harmful creature since
            # payment can't pause for a chooser. A player with no creature
            # simply pays nothing (the {M} they'd owe isn't modeled).
            self.rules.blight(player, cost.blight, source=obj, interactive=False)
        if cost.behold_exile:
            # RULE 701.4a (PAR-30): "behold a `<type>` and exile it." (the
            # Lorwyn "Champion" cycle). `_can_pay_additional_cast_cost`
            # already refused the cast if nothing matched, so a candidate
            # exists here. Exile it and stamp its id onto the spell — which
            # is the same `GameObject` once it enters the battlefield
            # (`casting_mixin._resolve_permanent_spell` adds ``obj`` itself),
            # so the card's own `LEAVES_BATTLEFIELD` `return_linked_exile`
            # trigger can hand it back (RULE 400.7: new object on return).
            victim = self._behold_exile_candidate(player, obj, cost.behold_exile)
            if victim is not None:
                self.state.fire_event(GameEvent(
                    EventType.BEHELD,
                    player_id=player.id, controller_id=player.id,
                    instance_id=victim.instance_id, quality=cost.behold_exile,
                ))
                self.rules.exile(victim)
                obj.linked_exile_id = victim.instance_id
        if cost.behold_two_shared_type:
            # RULE 701.4a (PAR-30, Celestial Reunion): "choose a creature type
            # and behold two creatures of that type." Optional — only reached
            # here when `pay_additional` (the guard at the top of this method
            # returned early otherwise). Stamp the chosen type so the
            # resolving search can put the found creature onto the
            # battlefield if it matches (RULE 700.6-adjacent, `chosen_type`,
            # the field the RULE 601.2b enter-time creature-type choice
            # already uses).
            chosen = self._behold_two_shared_type(player, obj)
            if chosen is not None:
                obj.chosen_type = chosen
                self.state.fire_event(GameEvent(
                    EventType.BEHELD,
                    player_id=player.id, controller_id=player.id,
                    quality=chosen,
                ))
    def _exile_hand_card_candidate(
        self, player: Player, color: str, exclude: Optional[GameObject] = None
    ) -> Optional[GameObject]:
        """A hand card of ``color`` (WUBRG letter) to pay a RULE 118.9
        "exile a `<color>` card from your hand" alternative cost (Force of
        Will/Negation/Vigor, MEC-15) — an auto-choice, the same non-
        interactive first-match convention `_return_to_hand_candidate`/
        `_sacrifice_candidate` use. ``exclude`` keeps the spell's own hand
        copy of itself out of its own pool, mirroring `_discard_cost_pool`'s
        identical reasoning: its alt cost can't be paid by exiling itself.
        """
        for card_obj in player.hand:
            if card_obj is exclude:
                continue
            if color in (card_obj.card.color_identity or set()):
                return card_obj
        return None
    def _exile_hand_card_color_count_candidates(
        self, player: Player, count: int, color: str, exclude: Optional[GameObject] = None
    ) -> Optional[list[GameObject]]:
        """PAR-19: ``count`` hand cards of ``color`` to pay a "exile N
        `<color>` cards from your hand rather than pay this spell's mana
        cost" alt-cast cost (Soul Spike/Sunscour/Allosaurus Rider-shaped) —
        the counted sibling of `_exile_hand_card_candidate`, same auto-pick-
        the-first-matches convention `_return_to_hand_count_candidates`
        uses for its own counted alt-cast cost. ``None`` (not payable) if
        fewer than ``count`` are eligible.
        """
        pool = [
            card_obj for card_obj in player.hand
            if card_obj is not exclude and color in (card_obj.card.color_identity or set())
        ]
        return pool[:count] if len(pool) >= count else None
    def _discard_land_type_candidate(
        self, player: Player, land_type: str, exclude: Optional[GameObject] = None
    ) -> Optional[GameObject]:
        """PAR-19: a hand card of the named basic land type to pay a
        "discard a `<land type>` card rather than pay this spell's mana
        cost" alt-cast cost (Abolish/Flameshot/Outbreak/Snag) — the
        discard-zone sibling of `_exile_hand_card_candidate`, matched by
        land subtype the same way `continuous.has_subtype` would (checked
        directly against the type line here rather than through that
        battlefield-only helper, since a hand card never goes through
        `continuous.recompute`).
        """
        word = land_type.strip().capitalize()
        for card_obj in player.hand:
            if card_obj is exclude:
                continue
            if card_obj.card.is_land and word in card_obj.card.type_line:
                return card_obj
        return None
    def _can_pay_alt_cast_cost(
        self, player: Player, obj: GameObject, cost: Optional["ActivationCost"]
    ) -> bool:
        """RULE 118.9: whether ``player`` can pay ``obj``'s own
        `GameObject.alt_cast_cost` right now — the payment half of
        `can_cast`'s ``alt_cost=True`` branch. The *gate* half
        (`GameObject.alt_cast_condition`, Force of Negation/Vigor's own "if
        it's not your turn") is checked separately by the caller, via
        `condition_query.free_cast_condition_holds`.
        """
        if cost is None:
            return False
        if cost.mana.symbols and not player.mana_pool.can_pay(
            cost.mana, life_available=player.life, require_source_kind=cost.mana_source_kind,
        ):
            # "You may pay {R}{G} rather than pay this spell's mana cost."
            # (the Bringer cycle/Admiral's Order-shaped RULE 118.9 family) —
            # a genuinely *different* fixed mana cost, not "no mana cost"
            # (`free=True`'s own branch, which is why `cast_without_paying`
            # can't be reused unconditionally for every `alt_cost=True`
            # spell — see `_pay_alt_cast_cost`'s matching check below).
            return False
        if cost.pay_life and player.life < cost.pay_life:
            return False
        if cost.return_to_hand and self._return_to_hand_candidate(player, cost.return_to_hand) is None:
            return False
        if cost.return_to_hand_count:
            count, subtype = cost.return_to_hand_count
            if self._return_to_hand_count_candidates(player, count, subtype) is None:
                return False
        if cost.sacrifice and self._sacrifice_candidate(player, obj, cost.sacrifice) is None:
            return False
        if cost.sacrifice_count:
            count, subtype = cost.sacrifice_count
            if self._resolve_sacrifice_count(player, count, subtype, None) is None:
                return False
        if cost.sacrifice_filter and self._sacrifice_filter_candidate(player, cost.sacrifice_filter) is None:
            return False
        if cost.exile_hand_card_color and self._exile_hand_card_candidate(
            player, cost.exile_hand_card_color, exclude=obj
        ) is None:
            return False
        if cost.exile_hand_card_color_count:
            count, color = cost.exile_hand_card_color_count
            if self._exile_hand_card_color_count_candidates(player, count, color, exclude=obj) is None:
                return False
        if cost.discard_land_type and self._discard_land_type_candidate(
            player, cost.discard_land_type, exclude=obj
        ) is None:
            return False
        if cost.tap_others:
            count, subtype = cost.tap_others
            if self._resolve_tap_others(player, obj, count, subtype, None) is None:
                return False
        # PAR-30: "collect evidence N rather than pay the mana cost"
        # (Conspiracy Unraveler's board-wide grant — `continuous.
        # granted_alt_cast_cost_for`).
        if cost.collect_evidence and not self.rules.collect_evidence_possible(
            player, cost.collect_evidence
        ):
            return False
        return True
    def _pay_alt_cast_cost(
        self, player: Player, obj: GameObject, cost: Optional["ActivationCost"]
    ) -> None:
        """Pay ``obj``'s RULE 118.9 alternative cost, assumed already
        checked payable by `_can_pay_alt_cast_cost`."""
        if cost is None:
            return
        if cost.mana.symbols:
            life_spent = player.mana_pool.pay(
                cost.mana, life_available=player.life, require_source_kind=cost.mana_source_kind,
            )
            if life_spent:
                self.rules.lose_life(player, life_spent, cause="cost")
        if cost.pay_life:
            self.rules.lose_life(player, cost.pay_life, cause="cost")
        if cost.return_to_hand:
            bounced = self._return_to_hand_candidate(player, cost.return_to_hand)
            if bounced is not None:
                self.rules.return_to_hand(bounced)
        if cost.return_to_hand_count:
            count, subtype = cost.return_to_hand_count
            for bounced in self._return_to_hand_count_candidates(player, count, subtype) or []:
                self.rules.return_to_hand(bounced)
        if cost.sacrifice:
            victim = self._sacrifice_candidate(player, obj, cost.sacrifice)
            if victim is not None:
                self.rules.put_into_graveyard(victim)
        if cost.sacrifice_count:
            count, subtype = cost.sacrifice_count
            for victim in self._resolve_sacrifice_count(player, count, subtype, None) or []:
                self.rules.put_into_graveyard(victim)
        if cost.sacrifice_filter:
            victim = self._sacrifice_filter_candidate(player, cost.sacrifice_filter)
            if victim is not None:
                self.rules.put_into_graveyard(victim)
        if cost.exile_hand_card_color:
            victim = self._exile_hand_card_candidate(player, cost.exile_hand_card_color, exclude=obj)
            if victim is not None:
                self.rules.exile(victim)
        if cost.exile_hand_card_color_count:
            count, color = cost.exile_hand_card_color_count
            for victim in self._exile_hand_card_color_count_candidates(player, count, color, exclude=obj) or []:
                self.rules.exile(victim)
        if cost.discard_land_type:
            victim = self._discard_land_type_candidate(player, cost.discard_land_type, exclude=obj)
            if victim is not None:
                self.rules.discard_specific(victim)
        if cost.tap_others:
            count, subtype = cost.tap_others
            for tapped in self._resolve_tap_others(player, obj, count, subtype, None) or []:
                self.rules.set_tapped(tapped, True)
        if cost.collect_evidence:
            # PAR-30 (Conspiracy Unraveler's granted alt cost).
            self.rules.collect_evidence(player, cost.collect_evidence)
    def _sacrifice_filter_candidate(
        self, player: Player, filt: dict, exclude: Optional[GameObject] = None
    ) -> Optional[GameObject]:
        """A permanent matching a `combat.matches_object_filter`-shaped
        ``filt`` ``player`` can sacrifice — the qualifier-filtered sibling
        of `_sacrifice_candidate`/`_sacrifice_count_pool` for an alt-cast
        cost whose object description is more than a bare type/subtype word
        ("a nontoken blue creature", Flare of Denial)."""
        for candidate in self.state.permanents_controlled_by(player.id):
            if candidate is exclude:
                continue
            if combat.matches_object_filter(candidate, filt):
                return candidate
        return None
    def _return_to_hand_count_candidates(
        self, player: Player, count: int, subtype: str
    ) -> Optional[list[GameObject]]:
        """``count`` permanents of ``subtype`` ``player`` controls, to pay a
        "Return N `<Type>`s you control to their owner's hand" alt-cast
        cost (Gush's "return two Islands") — the `return_to_hand_count`
        sibling of `_return_to_hand_candidate`'s singular form, auto-picking
        the first ``count`` matches the same non-interactive way every other
        alt-cast payment here does. ``None`` (not payable) if fewer than
        ``count`` are eligible. ``subtype="basic land"`` (the Borderpost
        cycle's own alt-cast cost) is RULE 205.4a's *supertype* qualifier,
        not a real subtype at all, so it's matched by ``is_land`` plus the
        printed "Basic" word rather than `continuous.has_subtype`.
        """
        if subtype == "basic land":
            pool = [
                o for o in self.state.permanents_controlled_by(player.id)
                if o.card.is_land and "basic" in o.card.type_line.lower()
            ]
        else:
            pool = [
                o for o in self.state.permanents_controlled_by(player.id) if continuous.has_subtype(o, subtype)
            ]
        return pool[:count] if len(pool) >= count else None
    def _graveyard_exile_cost_candidates(
        self, player: Player, count: int, filter_word: Optional[str],
    ) -> list[GameObject]:
        """Up to ``count`` cards from ``player``'s graveyard eligible to pay
        a RULE 601.2b "exile N [<type>] cards from your graveyard" additional
        cast cost (PAR-41). ``filter_word`` ("creature") narrows by main
        type; ``None`` accepts any card. Auto-picked (the first matches) —
        cost payment can't pause for a chooser, the same MVP simplification
        `_pay_escape_graveyard_cost` already makes.
        """
        out: list[GameObject] = []
        for card_obj in player.graveyard:
            if filter_word and filter_word not in card_obj.card.type_line.lower():
                continue
            out.append(card_obj)
            if len(out) >= count:
                break
        return out

    def _pay_retrace_discard(self, player: Player) -> None:
        """RULE 702.81a: discard one land card from ``player``'s hand as an
        additional cost of casting via Retrace. Auto-picks the first land
        card — the same non-interactive MVP simplification
        `_pay_escape_graveyard_cost` and the additional-cost payers make.
        """
        victim = next((c for c in player.hand if getattr(c, "is_land", False)), None)
        if victim is not None:
            self.rules.discard_specific(victim)

    def _pay_escape_graveyard_cost(self, player: Player, count: int) -> None:
        """RULE 702.138b: exile ``count`` other cards from ``player``'s
        graveyard as part of casting via Escape — an auto-choice (the first
        ``count`` remaining cards), the same non-interactive MVP
        simplification `_sacrifice_candidate`'s callers already make for
        other costs. Called after the escaping card itself has already left
        the graveyard, so it can never be exiled as its own cost.
        """
        for victim in list(player.graveyard)[:count]:
            self.rules.exile(victim)
