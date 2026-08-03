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
from .. import ability_catalogue, combat, condition_query, continuous, durations, face_down, variants
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
    @staticmethod
    def _flashback_cost(obj: GameObject) -> Optional["ManaCost"]:
        """RULE 702.34b: ``obj``'s Flashback cost as a `ManaCost`, or
        ``None`` if it carries no Flashback keyword (or one with no parsed
        cost)."""
        param = (getattr(obj, "parametric_keywords", None) or {}).get("flashback")
        if not param or not param.get("cost"):
            return None
        return ManaCost.parse(str(param["cost"]))
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
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        free: bool = False,
        mutate: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        targets: Optional[list[Any]] = None,
        assume_mana_available: bool = False,
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
        condition at all. ``sacrifice_choice``/``discard_choices`` are the
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
        in_castable_zone = (
            obj in player.hand
            or obj in player.command
            or (obj in player.exile and self._castable_from_exile(obj))
            or (obj.zone == Zone.EXILE and self._has_temp_play_permission(obj, player))
            or (obj in player.graveyard and self._castable_from_graveyard(obj))
            or (obj in player.graveyard and self._graveyard_cast_permission(player, obj))
            or (
                bool(player.library)
                and obj is player.library[-1]
                and self._castable_from_library(player, obj)
            )
        )
        if not in_castable_zone:
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
        # RULE 601.3a: a *conditional* prohibition on this specific spell,
        # rather than a flat per-turn count — a standing static (Lavinia,
        # Azorius Renegade's "each opponent can't cast noncreature spells
        # with mana value greater than the number of lands that player
        # controls") or a duration-bounded player effect with no permanent
        # left behind it at all (Hope of Ghirapur, which sacrificed itself).
        if continuous.cast_prohibited(self.state, player, card):
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
        has_temp_flash = self.state.temp_flash_until_turn.get(player.id) == self.state.turn_number
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
        sorcery_speed = not (
            card.is_instant or combat.has(obj, "flash") or has_conditional_flash or has_temp_flash
            or has_top_library_flash
        )
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
        if bargained and not self._bargain_candidate(player):
            # RULE 701.x: Bargain is optional, but *choosing* to bargain
            # requires something to sacrifice.
            return False
        if obj in player.graveyard and self._graveyard_cast_keyword(obj) == "escape":
            # RULE 702.138b: "exile N *other* cards from your graveyard" —
            # ``obj`` itself doesn't count toward that N.
            escape_cost = self._escape_cost(obj)
            if escape_cost is None:
                return False
            if len(player.graveyard) - 1 < escape_cost.exile_from_graveyard:
                return False
        if free:
            free_cast_condition = getattr(obj, "free_cast_condition", None)
            if free_cast_condition is None:
                return False
            if not condition_query.free_cast_condition_holds(free_cast_condition, obj, self.state):
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
                player, obj, x, face=face, kicked=kicked, kicker_x=kicker_x, buyback=buyback,
                mutate=mutate, entwine=entwine, targets=targets,
            )
            allows_restriction = restriction_predicate_for_cast(obj, has_x=cost.has_variable)
            wildcard = self.state.mana_wildcard_permission.get(obj.instance_id)
            if not player.mana_pool.can_pay(
                cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard
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
                remaining.pay(cost, life_available=player.life, allows_restriction=allows_restriction, wildcard=wildcard)
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
        bound" shape. Doesn't itself account for an independently announced
        Kicker ``{X}`` (`max_affordable_kicker_x`) — checked with
        ``kicker_x=0``, so a Kicker payable at all (any X, even 0) still
        reports 1 here; the two are meant to be read together.
        """
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is None:
            return 0
        kicker_param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
        upper = player.mana_pool.total() if kicker_param.get("multi") else 1
        for kicked in range(upper, -1, -1):
            if self.can_cast(player, obj, kicked=kicked):
                return kicked
        return 0
    def max_affordable_kicker_x(self, player: Player, obj: GameObject) -> int:
        """The highest X ``player`` could announce for Kicker's *own*
        ``{X}`` (RULE 702.33b, PAR-7 — Emblazoned Golem-shaped) and still
        cast ``obj`` kicked once. `max_affordable_x`'s sibling for an
        announced value living in Kicker's cost rather than the spell's own;
        0 if ``obj``'s Kicker cost has no ``{X}`` at all.
        """
        kicker_cost = self._kicker_cost(obj)
        if kicker_cost is None or not kicker_cost.has_variable:
            return 0
        bound = player.mana_pool.total()
        for kicker_x in range(bound, -1, -1):
            if self.can_cast(player, obj, kicked=1, kicker_x=kicker_x):
                return kicker_x
        return 0
    def effective_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        x: int = 0,
        face: str = "front",
        kicked: int = 0,
        kicker_x: int = 0,
        buyback: bool = False,
        mutate: bool = False,
        entwine: bool = False,
        targets: Optional[list[Any]] = None,
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
        """
        card = self._face_card(obj, face) or obj.card
        if mutate:
            # RULE 702.140b: the Mutate cost replaces the printed one — an
            # alternative cost, the same substitution shape Flashback/Escape
            # already use below (and, like those, still subject to the
            # reduction/tax applied afterwards).
            mutate_cost = self._mutate_cost(obj)
            if mutate_cost is not None:
                return self._adjust_cost(mutate_cost, player, obj)
        if obj in player.graveyard:
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
            cost = cost.with_x(x)
        cost = self._adjust_cost(cost, player, obj)
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
        if entwine:
            # RULE 702.42a: Entwine's cost is added on top of the printed
            # one, like Kicker/Buyback above — not substituted for it.
            entwine_cost = self._entwine_cost(obj)
            if entwine_cost is not None:
                cost = cost.add(entwine_cost)
        strive_cost = getattr(obj, "strive_cost", None)
        if strive_cost is not None and targets:
            # "This spell costs <cost> more to cast for each target beyond
            # the first." — the *first* target is free, every additional one
            # adds a full copy (not just generic, unlike a battlefield
            # anthem's tax — Strive's own cost can carry colored pips, e.g.
            # Aerial Formation's "{2}{U} more").
            for _ in range(max(0, len(targets) - 1)):
                cost = cost.add(strive_cost)
        return cost
    @staticmethod
    def commander_tax(player: Player, obj: GameObject) -> int:
        """Generic surcharge to cast ``obj`` from the command zone (RULE 903.8).

        {2} for each previous time this commander was cast from the command
        zone; 0 for a normal spell or a commander being cast from hand."""
        if obj.is_commander and obj in player.command:
            return 2 * player.commander_casts.get(obj.instance_id, 0)
        return 0
    def _adjust_cost(self, cost: "ManaCost", player: Player, obj: Optional[GameObject] = None) -> "ManaCost":
        """Apply the net static generic adjustment (reduce or increase).

        ``obj``, when given, also folds in a Delve/Affinity-shaped reduction
        printed on the card itself (`continuous.self_cost_reduction_for`) —
        distinct from a battlefield permanent's "your spells cost less".
        """
        reduction, _ = continuous.cost_reduction_for(self.state, player, obj)
        if obj is not None:
            self_reduction, _ = continuous.self_cost_reduction_for(obj, self.state)
            reduction += self_reduction
        if reduction > 0:
            return cost.reduce_generic(reduction)
        if reduction < 0:
            return cost.increase_generic(-reduction)
        return cost
    def max_affordable_x(self, player: Player, obj: GameObject) -> int:
        """The highest X ``player`` could announce and still pay for ``obj``.

        Only meaningful when the cost has ``{X}``; scans down from the
        pool's total mana (X can never exceed that) to the first payable
        value, 0 if even X=0 doesn't work.
        """
        bound = player.mana_pool.total()
        for x in range(bound, -1, -1):
            if self.can_cast(player, obj, x):
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
        mutate: bool = False,
        mutate_under: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
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
        if face in ("back", "fuse"):
            if not self.can_cast(player, obj, x, face=face, kicked=kicked, buyback=buyback, free=free):
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
                    target_groups=target_groups, free=free, mutate=mutate,
                    mutate_under=mutate_under, bargained=bargained, entwine=entwine,
                    sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                )
            except Exception:
                self.rules.restore_face(obj, snapshot)
                raise
            if is_adventure_cast:
                obj.adventure_snapshot = snapshot
            return result
        return self._cast_current_face(
            player, obj, targets, x, mode=mode, kicked=kicked, kicker_x=kicker_x, buyback=buyback,
            target_groups=target_groups, free=free, mutate=mutate,
            mutate_under=mutate_under, bargained=bargained, entwine=entwine,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
        )
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
        choose = getattr(obj, "spell_modes_choose", 1)
        at_least = getattr(obj, "spell_modes_at_least", False)
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
                and len(set(indices)) == len(indices)
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
    def _auto_tap_for_cast_if_needed(
        self,
        player: Player,
        obj: GameObject,
        x: int,
        kicked: int = 0,
        buyback: bool = False,
        free: bool = False,
        mutate: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
        targets: Optional[list[Any]] = None,
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
        """
        if free or self.can_cast(
            player, obj, x, kicked=kicked, buyback=buyback, free=free,
            mutate=mutate, bargained=bargained, entwine=entwine,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            targets=targets,
        ):
            return
        if not self.can_cast(
            player, obj, x, kicked=kicked, buyback=buyback, free=free,
            mutate=mutate, bargained=bargained, entwine=entwine,
            sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            targets=targets, assume_mana_available=True,
        ):
            return  # illegal for a reason other than mana — never auto-tap
        cost = self.effective_cast_cost(
            player, obj, x, kicked=kicked, buyback=buyback, mutate=mutate,
            entwine=entwine, targets=targets,
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
        mutate: bool = False,
        mutate_under: bool = False,
        bargained: bool = False,
        entwine: bool = False,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
    ):
        """The common cast body, reading whatever `obj.card` currently is.

        ``free=True`` (RULE 601.2f-adjacent condition-gated free-cast
        alternative cost — see `can_cast`) skips mana payment entirely via
        `RulesEngine.cast_without_paying`, instead of the ordinary
        `RulesEngine.cast_spell` mana-cost path.
        """
        if mode == "both" and not getattr(obj, "spell_modes_or_both", False):
            # RULE 702.42a: on an ordinary "choose one" block, "choose all"
            # exists only as Entwine's paid upgrade — never for free. (A
            # RULE 700.2e ``or_both`` block hands it over unpriced, hence
            # the guard only on the other branch.)
            if not entwine or self._entwine_cost(obj) is None:
                raise ValueError(f"{obj.name}: 'both' requires paying the entwine cost")
        with self._mode_effects_applied(obj, mode):
            self._auto_tap_for_cast_if_needed(
                player, obj, x, kicked=kicked, buyback=buyback, free=free,
                mutate=mutate, bargained=bargained, entwine=entwine,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                targets=targets,
            )
            if not self.can_cast(
                player, obj, x, kicked=kicked, kicker_x=kicker_x, buyback=buyback, free=free,
                mutate=mutate, bargained=bargained, entwine=entwine,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
                targets=targets,
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
            if free:
                result = self.rules.cast_without_paying(player, obj, targets, target_groups)
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
                    player, obj, x, kicked=kicked, kicker_x=kicker_x, buyback=buyback, mutate=mutate,
                    entwine=entwine, targets=targets,
                )
                result = self.rules.cast_spell(player, obj, targets, x, cost=cost, target_groups=target_groups)
                if kicked and kicker_x > 0 and self._kicker_x_distinct_colors(obj):
                    # PAR-7: Kicker's own distinct-color-capped {X} was
                    # excluded from ``cost`` above (`effective_cast_cost`) and
                    # is paid here instead, against whatever `cost` left in
                    # the pool — `can_cast` already verified this sequence is
                    # payable.
                    player.mana_pool.pay_distinct_colors(kicker_x)
            # RULE 601.2b/601.2h: an additional cost is paid as part of
            # casting, not resolving — so it stays paid even if the spell is
            # later countered. Paid *after* the mana cost (just above) so a
            # Phyrexian-mana payment reads the player's life before any
            # "pay N life" additional cost reduces it.
            self._pay_additional_cast_cost(
                player, obj, getattr(obj, "additional_cast_cost", None), x,
                sacrifice_choice=sacrifice_choice, discard_choices=discard_choices,
            )
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
            # Lurrus-shaped: record the casting turn so `_move_to_graveyard`
            # can honor the permission source's own "if a spell cast this
            # way would be put into a graveyard this turn, exile it
            # instead" clause — reassigned every cast (like the flag just
            # above), so a later normal recast this same turn clears it.
            obj.cast_via_graveyard_cast_permission_until_turn = (
                self.state.turn_number
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
            # RULE 500.4-adjacent: record this use of a Lurrus-shaped
            # "once during each of your turns" standing permission against
            # its *granting* permanent, not the cast card — untapped again
            # by `_step_untap` alongside `activated_loyalty_this_turn`.
            if graveyard_grant is not None and graveyard_grant.source is not None:
                graveyard_grant.source.graveyard_casts_this_turn += 1
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
        return True
    def _pay_additional_cast_cost(
        self,
        player: Player,
        obj: GameObject,
        cost: Optional["ActivationCost"],
        x: int,
        sacrifice_choice: Optional[int] = None,
        discard_choices: Optional[list[int]] = None,
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
