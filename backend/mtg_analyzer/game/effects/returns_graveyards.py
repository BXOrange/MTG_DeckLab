"""Return, graveyard, library-recovery, and linked-zone effects."""
from __future__ import annotations

from .core import GameEffect
from ._runtime import install, register
from ..targeting import graveyard_card_matches, legal_targets

install(globals())


class ReturnMilledCardsEffect(GameEffect):
    """Return cards named by the firing ``CARDS_MILLED`` batch.

    The event's LKI list, rather than a fresh graveyard scan, is the RULE
    701.13 referent for “them” / “one of them”.  This matters when another
    trigger has already moved a card from the same mill, or a later card has
    entered the graveyard before this trigger resolves.
    """

    def __init__(self, card_type: str, choose_one: bool = False, tapped: bool = False,
                 source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.card_type = card_type.lower()
        self.choose_one = bool(choose_one)
        self.tapped = bool(tapped)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        candidates = []
        for snapshot in event.get("cards") or []:
            if self.card_type not in snapshot.get("object_types", ()):
                continue
            obj = context.state.find_object(snapshot.get("instance_id"))
            if obj is not None and obj.zone == Zone.GRAVEYARD:
                candidates.append(obj)
        if not candidates:
            return
        controller = _controller_of(self.source, context)
        if self.choose_one:
            if controller is not None:
                context.choose_objects(
                    controller, candidates, "return_from_graveyard", count=1,
                    prompt="Wähle eine gemillte Karte zum Zurückbringen", source=self.source,
                )
            return
        destination = "battlefield_tapped" if self.tapped else "battlefield"
        with context.state.simultaneous():
            for obj in candidates:
                context.return_from_graveyard(obj, destination)


class LoseLifeForMilledCardTypesEffect(GameEffect):
    """Polluted Cistern's count of distinct card types in one mill batch."""

    _CARD_TYPES = frozenset({
        "artifact", "battle", "creature", "enchantment", "instant", "kindred",
        "land", "planeswalker", "sorcery", "tribal",
    })

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        types = {
            word for card in ((context.trigger_event or {}).get("cards") or [])
            for word in card.get("object_types", ()) if word in self._CARD_TYPES
        }
        controller = _controller_of(self.source, context)
        if controller is None or not types:
            return
        for player in context.state.living_players():
            if player.id != controller.id:
                context.lose_life(player, len(types))

class ReturnToHandEffect(GameEffect):
    """Return a target permanent to its owner's hand (RULE 701.3 "return").

    ``target_kind`` is usually ``"creature"``/``"permanent"``/``"any"`` (a
    plain "return target X to its owner's hand"), or a controller-restricted
    kind (``"land_you_control"``/``"creature_you_control"``) for a
    non-"target" resolve-time choice among the controller's own permanents —
    a bounce land's "return a land you control to its owner's hand" — see
    `targeting.legal_targets`. ``count`` > 1 targets several independent
    objects (RULE 115.1a generalized to N>=2, the same shape
    `DestroyEffect.count` uses) — "return two target creatures to their
    owners' hands".

    ``distinct_controllers`` (Run Away Together's "choose two target
    creatures controlled by **different players**. Return those creatures
    to their owners' hands.") is `targeting.TargetSpec.distinct_controllers`
    — see its docstring; only meaningful with ``count >= 2``.

    ``previous_subject=True`` (PAR-1) is Run Away Together's own two-sentence
    "choose N target X [constraint]. Verb **those** [referent]s." shape — a
    different, indirect-referent grammar from the single-sentence "destroy/
    exile N target X controlled by different players" `handlers.
    _MULTI_TARGET_DISTINCT_CONTROLLERS` claims: the *targets* are announced
    by a preceding `ChooseTargetsEffect` (RULE 601.2c, "choose N target
    creatures…") and read back here from `GameContext.previous_targets`
    (the same pronoun idiom `FightEffect`'s ``previous_target``/
    ``GrantUntilEffect.previous_subject`` use) instead of opening a fresh
    RULE 115 choice of its own — mutually exclusive with ``target_kind``,
    which is why it forces ``target_spec`` to ``None`` exactly like the self
    form below.

    ``target_kind=None`` is the **self** form — "Return ~ to its owner's
    hand." with no RULE 115 target and no player choice, mirroring
    `TapEffect`/`AddCountersEffect`'s own untargeted mode. It acts on the
    effect's own source wherever that currently is: Rancor's "When ~ dies,
    return it to its owner's hand." resolves with the source already in a
    *graveyard* (RULE 400.7 — it's a new object there), and
    `RulesEngine.return_to_hand` moves an object out of whatever zone it's
    in, so no separate graveyard path is needed. Flickering Ward's "{W}:
    Return ~ to its owner's hand." is the same effect from the
    battlefield.

    ``spell_or_permanent`` (Sink into Stupor's "Return target spell or
    nonland permanent…") routes through `RulesEngine.
    bounce_spell_or_permanent` instead of `return_to_hand` — a target still
    on the stack needs pulling out of `GameState.stack` (which
    `return_to_hand`'s ordinary battlefield/zone removal doesn't know
    exists), not just a hand-ward move.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "permanent",
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        distinct_controllers: bool = False,
        previous_subject: bool = False,
        selector: Optional[str] = None,
        filter: Optional[dict[str, Any]] = None,
        spell_or_permanent: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
        colors: Optional[list[str]] = None,
        to_library_top_if_clash_won: bool = False,
        then_specs: Optional[list[dict]] = None,
        trigger_event_key: Optional[str] = None,
        group: Optional[dict[str, Any]] = None,
        group_player: Optional[str] = None,
        count_selector: Optional[str] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Return **X** target creatures to their owners' hands" (Alexi, Zephyr Mage) —
        #: `TargetSpec.count_selector` (``"source_x_paid"``), read at announce time.
        self._count_selector = count_selector
        #: PAR-128: "return all creatures to their owners' hands" / "return each other creature
        #: you control …" — a structured battlefield selector (`_group_objects`), the mass
        #: sibling of `DestroyEffect.group`.
        self.group = dict(group) if isinstance(group, dict) and group.get("zone", "battlefield") == "battlefield" else None
        self.group_player = group_player if group_player in GROUP_SCOPE_PLAYERS else None
        #: ``target_kind="trigger_subject"`` (PAR-123, Cunning Evasion's "whenever
        #: a creature you control becomes blocked, you may return **it** …") —
        #: the acted-on object is whichever one fired this trigger, read live
        #: off `GameContext.trigger_event` under ``trigger_event_key``, the
        #: same mode `TapEffect`/`ExileEffect` already have.
        self._trigger_subject_mode = target_kind == "trigger_subject"
        self.trigger_event_key = trigger_event_key or "instance_id"
        #: "Clash with an opponent, then return target creature to its
        #: owner's hand. **If you win, you may put that creature on top of
        #: its owner's library instead.**" (Whirlpool Whelm) — the clash
        #: resolved first (RULE 608.2a, printed order), so `context.
        #: clash_won` is already set when this effect applies: on a win the
        #: single target goes to the top of its owner's *library* instead
        #: of hand. The "you may" is auto-taken (a beneficial *may*, the
        #: same convention `CoinFlipEffect` documents) — one effect, so no
        #: stale RULE 400.7 reference to "that creature" after a zone change.
        self.to_library_top_if_clash_won = bool(to_library_top_if_clash_won)
        self.then_specs = list(then_specs or [])
        #: "return target `<c1>` or `<c2>` creature you control to its
        #: owner's hand" (Escape Routes) — `TargetSpec.colors`' OR
        #: narrowing, offer-time (`targeting._color_ok`).
        self.colors = tuple(colors) if colors else None
        self.previous_subject = previous_subject
        self.spell_or_permanent = spell_or_permanent
        # RULE 601.2c mass "return all X [with condition]" (Displacement
        # Wave's "return all nonland permanents with mana value X or less to
        # their owners' hands.") — `DestroyEffect.selector`'s own untargeted
        # board-sweep shape, shared via `_mass_selector_objects`/
        # `_MASS_DESTROY_SELECTORS`.
        self.selector = selector if selector in _MASS_DESTROY_SELECTORS else None
        self.filter = filter
        # ``target_kind=None`` is the self form — no `TargetSpec` at all, the
        # same way `TapEffect`'s own untargeted modes leave it ``None``, so
        # `RulesEngine._trigger_target_specs` doesn't count this as a
        # targeting effect and open a RULE 115 choice with nothing to pick.
        # ``previous_subject``/``selector`` are the same "nothing of its own
        # to announce" shape, for the same reason (PAR-1) — their targets
        # already were the preceding clause's, or there's no RULE 115 choice
        # to begin with.
        self.target_spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                distinct_controllers=distinct_controllers, colors=self.colors,
                count_selector=count_selector,
                # "target **Human** you control" (Kogla, the Titan Ape,
                # MEC-43) — the same `TargetSpec.creature_filter` narrowing
                # `BlinkEffect`/`CounterUntapGrantKeywordEffect` already
                # thread through; ``"creature_you_control"`` (and every
                # other kind `legal_targets` already checks it against)
                # picks it up with no new target kind needed.
                creature_filter=creature_filter,
            )
            if target_kind is not None and not previous_subject and self.selector is None
            and not self._trigger_subject_mode and self.group is None
            else TargetSpec(kind=self.group_player)
            if self.group is not None and self.group_player in ("player", "opponent")
            else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.to_library_top_if_clash_won and getattr(context, "clash_won", None):
            bounce = lambda obj: context.return_to_library(obj, "top")  # noqa: E731
        else:
            bounce = (
                context.bounce_spell_or_permanent if self.spell_or_permanent
                else context.return_to_hand
            )
        if self.group is not None:
            chosen = (targets or [self.target])[0] if (targets or self.target is not None) else None
            for obj in _group_objects(context, self.group, self.group_player, self.source, chosen) or []:
                bounce(obj)
            return
        if self.selector is not None:
            # "…with mana value X or less" — the ``"x"`` sentinel on
            # ``self.filter`` is already substituted for the spell's real
            # announced {X} by `RulesEngine._substitute_x` at cast time
            # (it walks any effect's ``filter`` dict generically, the same
            # path `DestroyEffect`'s own mass wipes use).
            for obj in _mass_selector_objects(context, self.selector, self.filter, source=self.source):
                bounce(obj)
            return
        if self._trigger_subject_mode:
            obj_id = (context.trigger_event or {}).get(self.trigger_event_key)
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is not None:
                bounce(target)
            return
        if self.previous_subject:
            # "Return those creatures to their owners' hands." (PAR-1) — the
            # whole group the preceding "choose N target …" clause announced.
            for target in list(context.previous_targets):
                bounce(target)
            return
        if self.target_spec is None:
            # Self form — the source itself, from whatever zone it's in.
            if self.source is not None:
                bounce(self.source)
            return
        if self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for target in chosen:
                bounce(target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            bounce(target)
            if self.then_specs:
                # RULE 608.2h: a nested "if you do" rider reads the
                # returned object by last-known information after its zone
                # change, not an unrelated prior effect's target.
                context.previous_targets = [target]
                context.engine._apply_effect_specs(self.then_specs, self.source)


class ReturnToLibraryEffect(GameEffect):
    """"Put target X on top/the bottom of its owner's library." (RULE 701.3
    "put" — Time Ebb/Griptide/Roil Spout/Vedalken Dismisser-shaped tempo
    bounce; 10 SOLO cards on this exact template, `parser_probe.py blocked`).
    `ReturnToHandEffect`'s library-destination sibling — see
    `RulesEngine.return_to_library`.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: Optional[str] = "creature",
        position: str = "top",
        optional: bool = False,
        count: int = 1,
        colors: Optional[list[str]] = None,
        depth: int = 1,
        group: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "Put all creatures on the bottom of their owners' libraries." (Terminus, Hallowed Burial) — a structured
        #: battlefield selector (`_group_objects`), `ReturnToHandEffect.group`'s library sibling. Each owner's cards
        #: go in the order found (RULE 401.4 lets them arrange them; the engine keeps one fixed order).
        self.group = dict(group) if isinstance(group, dict) and group.get("zone", "battlefield") == "battlefield" else None
        #: "put it into its owner's library third from the top" (God-Eternal
        #: Oketra) — ``position="top"`` with ``depth`` 3; 1 is plain "on top".
        self.depth = max(1, int(depth))
        #: "put target `<c1>` or `<c2>` creature on top of its owner's
        #: library" (Hunting Drake) — `TargetSpec.colors`' OR narrowing.
        self.colors = tuple(colors) if colors else None
        self.position = position if position in ("top", "bottom") else "top"
        #: ``target_kind=None`` — "Put **this**/~ on top of its owner's
        #: library." (Sensei's Divining Top-shaped) — no RULE 115 target at
        #: all, mirroring `ExileEffect`/`TapEffect`'s own self mode.
        #: ``target_kind="attached_permanent"`` — "{3}{U}{U}: Put enchanted creature into its owner's library third
        #: from the top." (Shattered Ego): the Aura's host, not a target.
        self.attached = target_kind == "attached_permanent"
        self.target_spec = (
            TargetSpec(kind=target_kind, optional=optional, count=count, colors=self.colors)
            if target_kind and self.group is None and not self.attached else None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.attached:
            from .. import effect_conditions  # function-scoped: effects↔conditions cycle

            host = effect_conditions.subject_of("attached", context, self.source, targets)
            if host is not None:
                context.return_to_library(host, self.position, self.depth)
            return
        if self.group is not None:
            for obj in _group_objects(context, self.group, None, self.source, None) or []:
                context.return_to_library(obj, self.position, self.depth)
            return
        if self.target_spec is None:
            target = (targets[0] if targets else None) or self.target or self.source
            if target is not None:
                context.return_to_library(target, self.position, self.depth)
            return
        if self.target_spec.effective_count != 1:
            chosen = _chosen_targets(targets, self.target_spec.effective_count, self.target)
            for target in chosen:
                context.return_to_library(target, self.position, self.depth)
            return
        target = (targets[0] if targets else None) or self.target
        if target is not None:
            context.return_to_library(target, self.position, self.depth)


class ReturnToLibraryThenDigSharedTypeEffect(GameEffect):
    """"Put target permanent you own on the bottom of your library. Reveal
    cards from the top of your library until you reveal a card that shares
    a card type with that permanent. Put that card onto the battlefield and
    the rest on the bottom of your library in a random order." (Reality
    Scramble) — the type-matching predicate is read live off the
    just-bottomed permanent's own printed type words (RULE 205's main types
    only; ``GameObject.type_words`` also carries a supertype like
    "legendary" and the always-added "permanent", neither of which counts
    as a "card type" a `card_query` type match should require), so one
    effect covers whatever gets targeted rather than a fixed criteria.
    """

    _MAIN_TYPES = (
        "land", "creature", "artifact", "enchantment",
        "planeswalker", "instant", "sorcery", "battle", "kindred",
    )

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "permanent_you_control",
    ) -> None:
        super().__init__(source)
        self.target = target
        self.target_spec = TargetSpec(kind=target_kind)

    def target_polarity(self) -> Optional[str]:
        return "beneficial"

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        player = _controller_of(self.source, context)
        if player is None:
            return
        shared_types = [t for t in self._MAIN_TYPES if t in target.type_words]
        context.return_to_library(target, "bottom")
        if not shared_types:
            return
        context.engine.dig_until(
            player, {"type": shared_types},
            hit_destination="battlefield", rest_destination="library_bottom_random",
        )


class ShuffleSelfIntoLibraryEffect(GameEffect):
    """"Shuffle ~ into its owner's library." (RULE 701.20 — Green Sun's
    Zenith's own trailing sentence, overriding the spell's default RULE
    608.2m "goes to the graveyard as it resolves" routing). Self-only, no
    RULE 115 target, mirroring `ReturnToHandEffect`'s ``target_kind=None``
    self mode; `_apply_stack_item`'s existing ``obj.zone != Zone.STACK``
    check already treats any self-move away from the stack (previously only
    a trailing self-`ExileEffect`) as an override, so nothing else needs to
    know this effect exists.
    """

    def __init__(
        self, subject: str = "self", source: Optional["GameObject"] = None
    ) -> None:
        super().__init__(source)
        self.target_spec = None
        #: ``"attached_permanent"`` — "Enchanted creature's owner shuffles it
        #: into their library." (Watery Grasp, ENG-32): act on whatever this
        #: Aura is currently `attached_to`, re-read live at resolution.
        self.subject = subject

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        obj = self.source
        if self.subject == "attached_permanent":
            host_id = getattr(self.source, "attached_to", None)
            obj = context.state.find_object(host_id) if host_id is not None else None
        if obj is not None:
            context.shuffle_into_library(obj)


class ReturnFromGraveyardEffect(GameEffect):
    """Return/put a target card from a graveyard onto the battlefield or to
    a hand (RULE 701.3, the Regrowth/Reanimate/Deathrite-adjacent recursion
    family — see `targeting.legal_targets`'s `_GRAVEYARD_TARGET_KINDS` for
    the full ``target_kind`` vocabulary: own/any/opponent graveyard scope ×
    card/creature/land/artifact/enchantment/instant-or-sorcery/permanent
    type). ``destination`` is ``"battlefield"`` (default) or ``"hand"``.

    ``under_your_control`` is the Reanimate/Rise from the Grave/Virtue of
    Persistence shape — "put target creature card from a graveyard onto
    the battlefield **under your control**" — as opposed to the plain
    Regrowth/Karmic Guide/Kenrith shape (this effect's default), which
    always returns to the card's *owner*'s control, matching how "return
    … to the battlefield"/"under its owner's control" reads. Only
    meaningful with ``destination="battlefield"`` — a card can't go to
    "your hand" when it isn't yours; real cards never combine the two.
    """

    #: Destinations this effect will route to (all handled by the engine's
    #: `_put_searched_card`): battlefield/hand (the recursion default pair)
    #: plus ``library_top`` (Noxious Revival "put … on top of its owner's
    #: library") / ``library_bottom``.
    _DESTINATIONS: frozenset[str] = frozenset(
        {"battlefield", "hand", "library_top", "library_bottom"}
    )

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "graveyard_creature",
        destination: str = "battlefield",
        under_your_control: bool = False,
        optional: bool = False,
        lose_life_equal_mv: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        shuffle_after: bool = False,
        subtype: Optional[str] = None,
        haste: bool = False,
        max_mana_value: Optional[int] = None,
        exact_mana_value: Optional[Union[int, str]] = None,
        tapped: bool = False,
        trigger_subject_key: Optional[str] = None,
        players: Optional[str] = None,
        count_selector: Optional[str] = None,
        colors: Optional[list[str]] = None,
        extra_counters: Optional[dict[str, Any]] = None,
        exclude_legendary: bool = False,
        positional_top_creature: bool = False,
        unless_flag: Optional[str] = None,
        attacking: bool = False,
        pick: bool = False,
        creature_filter: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: "…to the battlefield tapped **and attacking**" (Alesha, Interceptor) — RULE 508.4: put into
        #: combat right after it lands (`RulesEngine.put_onto_battlefield_attacking`, the primitive
        #: "create a tapped and attacking token" already uses).
        self.attacking = bool(attacking)
        #: "return **a** land card from your graveyard to the battlefield tapped" (Blossoming Tortoise) —
        #: not a RULE 115 target: the controller picks among the cards the ``target_kind``/filters
        #: describe when this resolves (`RulesEngine._request_choose_objects`), and may pick none only
        #: when ``optional``. An exactly-one pool is taken without asking.
        self.pick = bool(pick)
        self.optional = bool(optional)
        #: "…creature card with power 2 or less…" — a filter on the graveyard card itself
        #: (`TargetSpec.creature_filter`, read by `targeting.legal_targets`' graveyard branch).
        self.creature_filter = dict(creature_filter) if creature_filter else None
        #: "Return the **top** creature card of your graveyard to the
        #: battlefield." (Corpse Dance) — a positional pick (the graveyard's
        #: own insertion order, most-recently-added last), *not* a RULE 115
        #: target, so no `target_spec`. Runs the returned card through the
        #: same `_apply_one` as every other mode (haste/tapped/counters
        #: riders, `created_objects` referent for a trailing "exile it").
        self.positional_top_creature = bool(positional_top_creature)
        #: "return target `<c1>` or `<c2>` creature card from your
        #: graveyard …" (Crypt Angel) — `TargetSpec.colors`' OR narrowing.
        self.colors = tuple(colors) if colors else None
        #: Living Death family — "[each player / you] return[s] all/each
        #: creature card from [their / your] graveyard to the battlefield /
        #: hand". A mass, untargeted return over every matching card in the
        #: named graveyard(s); bypasses ``target_spec`` entirely and runs
        #: each card through the same `_apply_one` (ETB prohibition, owner
        #: control, riders). ``"you"`` = this effect's controller's
        #: graveyard; ``"each_player"`` = every living player's.
        self.players = players if players in ("you", "each_player") else None
        self.destination = destination if destination in self._DESTINATIONS else "battlefield"
        self.under_your_control = under_your_control
        #: "It gains haste." (Puppeteer Clique-shaped reanimate-and-exile) —
        #: a temp keyword grant on the returned permanent, same idiom
        #: `CopyPermanentEffect.haste` uses.
        self.haste = haste
        #: "…return it to the battlefield **tapped** under its owner's
        #: control." (MEC-43 round 2, Tenacious Dead) — Persist/Undying-
        #: shaped, but through the graveyard-recursion effect rather than
        #: an in-place return, since this card's own trigger targets no
        #: pre-existing "persist" mechanic.
        self.tapped = tapped
        #: "When ~ dies, you may pay `<cost>`. If you do, return **it** to
        #: the battlefield…" (Tenacious Dead) — the object to return isn't
        #: a fresh RULE 115 target at all, it's whatever fired this
        #: ability's own trigger (mirrors `AddCountersEffect.
        #: trigger_subject_key`'s ``"remembered"`` idiom exactly: reads
        #: `GameObject.remembered_instance_id`, stamped by an outer
        #: `PayCostThenEffect(remember_trigger_subject=True)` since
        #: `context.trigger_event` is no longer live once the interactive
        #: "if you do" choice resolves).
        self.trigger_subject_key = trigger_subject_key
        # RULE 701.3 rider: "You lose life equal to that creature's mana
        # value." (Reanimate) — read off the returned card, paid by the
        # effect's own controller, after the return resolves.
        self.lose_life_equal_mv = lose_life_equal_mv
        # PAR-15: "shuffle target card(s) from your graveyard into your
        # library" (Piper's Melody/Renewing Touch/Perpetual Timepiece) —
        # RULE 701.3's own recursion, just with an unknown final position
        # rather than a fixed top/bottom; modeled as "put on the bottom,
        # then shuffle" (the position `_put_searched_card`'s
        # ``"library_bottom"`` gives it is immediately randomized away, so
        # the result is exactly "shuffled into the library") rather than a
        # third `_DESTINATIONS` entry, mirroring how `SearchLibraryEffect`
        # already treats a shuffle destination as a placement + a follow-up
        # `shuffle_library` call rather than its own zone.
        self.shuffle_after = shuffle_after
        # RULE 303.4f (MEC-34): "Return enchanted creature card to the
        # battlefield…" (Animate Dead-shaped) — a fifth, non-RULE-115 mode
        # alongside the ordinary target/self shapes `AttachEffect`'s own
        # ``target_kind="created"`` mirrors: the card to return isn't a
        # fresh choice at all, it's the *same* graveyard card this Aura's
        # own spell already targeted when cast, stashed on `GameObject.
        # reanimate_target_id` since it can't attach the ordinary way.
        self._self_enchant_mode = target_kind == "self_enchant_target"
        #: "return X target creature cards from your graveyard …" — the
        #: count is the spell/ability's announced {X}, read at target-
        #: gathering time (`targeting.resolved_count`, ``"source_x_paid"``).
        self.count_selector = count_selector
        #: "…with a -1/-1 counter on it." (Persist) / "Each of them enters
        #: with an additional -1/-1 counter on it." (Aberrant Return) — the
        #: same ``{"kind", "count"}`` shape `ReturnToBattlefieldDelayed`'s
        #: own ``extra_counters`` uses, placed on each returned permanent
        #: right after it lands (via `context.add_counters`, so a "whenever
        #: a -1/-1 counter is put on a creature" trigger still sees it).
        self.extra_counters = dict(extra_counters) if extra_counters else None
        #: "return target **nonlegendary** creature card …" (Persist) — RULE
        #: 205.4a supertype exclusion on the graveyard target pool.
        self.exclude_legendary = bool(exclude_legendary)
        self._kind = target_kind
        spec = (
            TargetSpec(
                kind=target_kind, optional=optional, count=count, count_max=count_max,
                subtype=subtype, max_mana_value=max_mana_value,
                # "…creature card with mana value X…" (Isareth the Awakener, PAR-139): an exact match,
                # ``"x"`` until `RulesEngine._substitute_x` binds it.
                exact_mana_value=exact_mana_value,
                count_selector=count_selector, colors=self.colors,
                exclude_legendary=self.exclude_legendary,
                creature_filter=self.creature_filter,
                # "…with mana value 4 or less. If this spell was cast using
                # teamwork, instead choose target creature card in your
                # graveyard[.]" (MEC-85, Too Evil to Stay Dead) — see
                # `targeting.TargetSpec.unless_flag`.
                unless_flag=unless_flag,
            )
            if not self._self_enchant_mode and not self.trigger_subject_key
            and not self.positional_top_creature
            else None
        )
        #: An untargeted pick / mass ("return a land card …", "return all land cards …") announces no
        #: RULE 115 target — a spell must not need a legal one to be cast — but still describes the pool
        #: through the same spec, kept privately for `legal_targets`.
        self._pool_spec = spec
        self.target_spec = None if (self.pick or self.players is not None) else spec

    def _apply_one(self, context: GameContext, target: Any) -> None:
        if self.destination == "battlefield":
            # RULE 601.3a-adjacent: "`<type>` cards in graveyards … can't
            # enter the battlefield." (Grafdigger's Cage/Weathered
            # Runestone) — checked against the target's own printed card
            # while it's still sitting in the graveyard, before anything
            # moves; a prohibited card simply stays put; there's no target
            # to fall back to (RULE 608.2b covers a spell fizzling on an
            # illegal target, but this is a static prevention, not that).
            from .. import continuous  # local: continuous imports this module under TYPE_CHECKING

            target_zone = getattr(target, "zone", None)
            if continuous.graveyard_library_entry_prohibited(
                context.state, target.card, zone=getattr(target_zone, "value", None)
            ):
                return
            # "If a nontoken creature would enter and it wasn't cast, exile
            # it instead." (MEC-43 round 4D, Containment Priest) — checked
            # right alongside the prohibition above, the same choke point;
            # unlike a prohibition this redirects the move rather than
            # cancelling it outright.
            if continuous.uncast_creature_entry_exiled(context.state, target.card):
                context.exile(target)
                return
        controller_id = None
        if self.under_your_control and self.destination == "battlefield":
            player = _controller_of(self.source, context)
            controller_id = player.id if player is not None else None
        mv = getattr(getattr(target, "card", None), "converted_mana_cost", 0) or 0
        owner_id = getattr(target, "owner_id", None)
        # RULE 110.5b: "…to the battlefield tapped" *enters* tapped — the destination string
        # `return_from_graveyard` reads, so an enters-the-battlefield trigger sees it tapped.
        destination = (
            "battlefield_tapped" if self.tapped and self.destination == "battlefield"
            else self.destination
        )
        context.return_from_graveyard(target, destination, controller_id=controller_id)
        if self.destination == "battlefield":
            # RULE 400.7: the object's `instance_id` stays stable across
            # the zone change (see `GameObject.reset_as_new_object`'s own
            # docstring), so `target` is still the right reference to hand
            # a following "it gains haste"/"exile it" clause — RULE 608.2's
            # referent, `GameContext.created_objects`, the same list
            # `CreateTokenEffect`/`CopyPermanentEffect` populate.
            context.created_objects.append(target)
            if self.haste:
                target.temp_keywords.add("haste")
            if self.attacking:
                context.engine.put_onto_battlefield_attacking(target)
            if self.extra_counters:
                kind = str(self.extra_counters.get("kind", "-1/-1"))
                count = int(self.extra_counters.get("count", 1) or 1)
                context.add_counters(target, count, kind, source=self.source)
        if self.shuffle_after and owner_id is not None:
            owner = context.state.player_by_id(owner_id)
            context.shuffle_library(owner)
        if self.lose_life_equal_mv and mv:
            player = _controller_of(self.source, context)
            if player is not None:
                context.lose_life(player, int(mv))

    def _request_pick(self, context: GameContext) -> None:
        """An untargeted "return a `<type>` card from your graveyard" — the controller chooses one."""
        player = _controller_of(self.source, context)
        if player is None or self._pool_spec is None:
            return
        found = legal_targets(context.state, player.id, self._pool_spec, self.source)
        ids = {item["instance_id"] for item in found}
        candidates = [
            o for owner in context.state.living_players() for o in owner.graveyard
            if o.instance_id in ids
        ]
        if not candidates:
            return
        if self.destination == "hand":
            action = "return_from_graveyard_to_hand"
        else:
            action = "return_from_graveyard_tapped" if self.tapped else "return_from_graveyard"
        context.engine._request_choose_objects(
            player, candidates, action, count=1, optional=self.optional,
            prompt="Karte aus dem Friedhof zurückbringen", source=self.source,
            control_recipient_id=player.id if self.under_your_control else None,
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.positional_top_creature:
            player = _controller_of(self.source, context)
            if player is None:
                return
            creature = next(
                (o for o in reversed(player.graveyard) if o.card.is_creature), None
            )
            if creature is not None:
                with context.state.simultaneous():
                    self._apply_one(context, creature)
                # RULE 608.2's referent for a trailing "that creature …"
                # clause — `_apply_one` already appended it to
                # `created_objects`; naming it here too lets a following
                # `if_else`/`grant_until` read it via ``previous_target``
                # (the positional pick declared no `target_spec`, so
                # `_apply_effects_partitioned` won't set this itself).
                context.previous_targets = [creature]
            return
        if self.players is not None:
            # Living Death mass return — every matching card in the named
            # graveyard(s), no target choice. Snapshot per player first
            # (``_apply_one`` mutates the graveyard as it goes).
            if self.players == "you":
                ctrl = _controller_of(self.source, context)
                players = [ctrl] if ctrl is not None else []
            else:
                players = list(context.state.living_players())
            kind = self._kind or "graveyard_creature"
            with context.state.simultaneous():
                for player in players:
                    # "return all **land** cards from your graveyard to the battlefield tapped"
                    # (Aftermath Analyst, Lumra): the kind's own type filter, not just creature/any.
                    cards = [o for o in list(player.graveyard) if graveyard_card_matches(kind, o)]
                    for card in cards:
                        self._apply_one(context, card)
            return
        if self.pick:
            self._request_pick(context)
            return
        if self._self_enchant_mode:
            target_id = getattr(self.source, "reanimate_target_id", None)
            target = context.state.find_object(target_id) if target_id is not None else None
            if target is None:
                return
            self._apply_one(context, target)
            return
        if self.trigger_subject_key:
            obj_id = (
                getattr(self.source, "remembered_instance_id", None)
                if self.trigger_subject_key == "remembered"
                else (context.trigger_event or {}).get(self.trigger_subject_key)
            )
            target = context.state.find_object(obj_id) if obj_id is not None else None
            if target is None:
                return
            self._apply_one(context, target)
            return
        if self.count_selector or self.target_spec.effective_count != 1:
            # A ``count_selector`` spec's real count is resolved by the
            # targeting layer at cast (`resolved_count`), so ``targets``
            # already holds exactly the X picks it offered — take them all
            # rather than the printed ``effective_count`` (still 1 here).
            cap = (
                len(targets or [])
                if self.count_selector and targets is not None
                else self.target_spec.effective_count
            )
            with context.state.simultaneous():
                for target in _chosen_targets(targets, cap, self.target):
                    self._apply_one(context, target)
            return
        target = (targets[0] if targets else None) or self.target
        if target is None:
            return
        self._apply_one(context, target)


class ReturnCreatureCardsWithTotalMVEffect(GameEffect):
    """Ancient Brass Dragon's any-number graveyard return (RULE 701.3)."""

    def __init__(self, budget: int = 0, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.budget = int(budget)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.budget < 0:
            return
        candidates = [obj for owner in context.state.living_players() for obj in owner.graveyard if obj.card.is_creature]
        context.engine._request_choose_objects(
            player, candidates, "return_from_graveyard", count=len(candidates), optional=True,
            prompt=f"Kreaturenkarten mit Gesamtmanawert bis {self.budget} zurückbringen",
            source=self.source, control_recipient_id=player.id,
            total_mana_value_budget=self.budget,
        )


class ReturnChosenCreatureTypeFromGraveyardEffect(GameEffect):
    """Resolve Haunting Voyage after its creature-type choice.

    The normal branch asks for up to two actual cards.  A foretold source
    returns the whole matching snapshot, exactly as the printed replacement
    clause requires.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        chosen = str(getattr(self.source, "chosen_type", "") or "").lower()
        if not chosen:
            return
        cards = [
            obj for obj in list(player.graveyard)
            if obj.card.is_creature and chosen in obj.card.type_line.lower().split()
        ]
        if getattr(self.source, "foretold", False):
            with context.state.simultaneous():
                for obj in cards:
                    context.return_from_graveyard(obj, "battlefield")
            return
        context.engine._request_choose_objects(
            player, cards, "return_from_graveyard", count=2, optional=True,
            prompt=f"Bis zu zwei {chosen.capitalize()}-Kreaturenkarten zurückbringen",
            source=self.source,
        )


class CastTargetElementalFromGraveyardFreeEffect(GameEffect):
    """Horde of Notions' targeted graveyard permission.

    The selected card moves to exile and opens the ordinary free-cast window,
    so its controller makes the cast and target choices. The card follows its
    normal later zone changes; Horde's Oracle text has no exile rider.
    """

    def __init__(self, source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.target_spec = TargetSpec(kind="graveyard_card", subtype="Elemental")

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        target = (targets or [None])[0]
        player = _controller_of(self.source, context)
        if player is None or target is None or target not in player.graveyard:
            return
        context.exile(target)
        context.engine.grant_free_cast_window_from_exile(target, caster=player)


class KindredSummonsEffect(GameEffect):
    """Resolve Kindred Summons after its creature-type choice (MEC-72).

    Counts creatures controller controls of the chosen type, then reveals
    until that many creature cards of the chosen type are revealed, putting
    them onto the battlefield and shuffling the rest into the library.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from .. import continuous
        player = _controller_of(self.source, context)
        if player is None or self.source is None:
            return
        chosen = str(getattr(self.source, "chosen_type", "") or "").lower()
        if not chosen:
            return
        x = sum(
            1 for o in context.state.battlefield
            if o.controller_id == player.id and o.is_creature and continuous.has_subtype(o, chosen)
        )
        context.engine.reveal_until_creature_type(
            player,
            creature_types=[chosen],
            count=x,
            hit_destination="battlefield",
            rest_destination="library_shuffled",
        )


class RevealUntilMatchingEffect(GameEffect):
    """"Reveal cards from the top of your library until you reveal X `<type>`
    cards. Put those onto the battlefield [tapped] / into your hand and the
    rest on the bottom of your library in a random order." (Open the Way,
    PAR-60) — a thin wrapper over `RulesEngine.reveal_until_matching`.

    ``count`` may be the ``"x"`` sentinel (`_substitute_x`). Documented
    simplification for Open the Way: the printed "X can't be greater than
    the number of players in the game" cap is not enforced (the caster
    chooses X and has no reason to over-announce it)."""

    def __init__(
        self,
        criteria: Any = "land",
        count: Any = 1,
        hit_destination: str = "battlefield",
        rest_destination: str = "library_bottom_random",
        tapped: bool = False,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.criteria = criteria
        self.count = count
        self.hit_destination = hit_destination
        self.rest_destination = rest_destination
        self.tapped = bool(tapped)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        count = self.count if isinstance(self.count, int) else 0
        context.engine.reveal_until_matching(
            player, self.criteria, count=count,
            hit_destination=self.hit_destination,
            rest_destination=self.rest_destination, tapped=self.tapped,
        )


class ExpressiveIterationEffect(GameEffect):
    """"Look at the top three cards of your library. Put one of them into
    your hand, put one of them on the bottom of your library, and exile one
    of them. You may play the exiled card this turn." (Expressive Iteration,
    PAR-60.)

    Two interactive picks: the hand card (``"library_to_hand"``), then which
    of the remaining two to exile (``"choose_permanent"`` stamps the id,
    `expressive_iteration_exile_step` finishes — exile it with a
    this-turn play window, the last card to the bottom).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context) or context.active_player
        if player is None or not player.library:
            return
        top3 = list(reversed(player.library[-3:]))  # top-of-library first
        # Stashed on the state, not the source: a resolving *spell* has
        # already left the stack by the time `then_specs` run and cannot be
        # recovered by instance id (`_object_by_instance_id`).
        context.state._expressive_iteration_ids = [o.instance_id for o in top3]
        context.state._expressive_iteration_player = player.id
        context.engine._request_choose_objects(
            player, top3, "library_to_hand", count=1, optional=False,
            prompt="Expressive Iteration: eine Karte auf die Hand",
            source=self.source,
            then_specs=[{"type": "expressive_iteration_exile_step", "params": {}}],
        )


class ExpressiveIterationExileStepEffect(GameEffect):
    """``then_specs`` tail of `ExpressiveIterationEffect`: of the two cards
    left on top of the library, pick one to exile with a this-turn play
    window; the last goes to the bottom."""

    def _player(self, context: GameContext) -> Any:
        pid = getattr(context.state, "_expressive_iteration_player", None)
        if pid is not None:
            try:
                return context.state.player_by_id(pid)
            except (KeyError, ValueError):
                pass
        return _controller_of(self.source, context) or context.active_player

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = self._player(context)
        ids = list(getattr(context.state, "_expressive_iteration_ids", None) or [])
        remaining = [
            o for o in (context.state.find_object(i) for i in ids)
            if o is not None and o.zone == Zone.LIBRARY
        ]
        if player is None or not remaining:
            return
        if len(remaining) == 1:
            ExpressiveIterationFinishEffect(source=self.source)._mark_playable(
                context, player, remaining[0]
            )
            context.state._expressive_iteration_ids = []
            return
        context.engine._request_choose_objects(
            player, remaining, "exile", count=1, optional=False,
            prompt="Expressive Iteration: eine Karte verbannen (diesen Zug spielbar)",
            source=self.source,
            then_specs=[{"type": "expressive_iteration_finish", "params": {}}],
        )


class ExpressiveIterationFinishEffect(GameEffect):
    """``then_specs`` tail of the exile pick: the ``"exile"`` action already
    moved the chosen card to exile and left it on ``context.previous_targets``
    — grant it a this-turn play window; the last library card to the bottom.
    """

    def _mark_playable(self, context: GameContext, player: Any, obj: "GameObject") -> None:
        if obj is None:
            return
        if obj.zone == Zone.LIBRARY:  # single-remaining shortcut path
            if obj in player.library:
                player.library.remove(obj)
            obj.zone = Zone.EXILE
            player.exile.append(obj)
            context.state.fire_event(GameEvent(
                EventType.EXILE, player_id=player.id, object=obj.name, from_zone="library",
            ))
        context.engine._grant_temp_play_permission(
            obj, player, "Expressive Iteration", True, None
        )

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        pid = getattr(context.state, "_expressive_iteration_player", None)
        try:
            player = context.state.player_by_id(pid) if pid is not None else None
        except (KeyError, ValueError):
            player = None
        player = player or context.active_player
        ids = list(getattr(context.state, "_expressive_iteration_ids", None) or [])
        context.state._expressive_iteration_ids = []
        prev = list(context.previous_targets or [])
        exiled = prev[0] if prev else None
        if exiled is not None:
            self._mark_playable(context, player, exiled)
        for o in (context.state.find_object(i) for i in ids):
            if o is not None and o is not exiled and o.zone == Zone.LIBRARY:
                if o in player.library:
                    player.library.remove(o)
                o.zone = Zone.LIBRARY
                player.library.insert(0, o)  # bottom


class PlarggAndNassariEffect(GameEffect):
    """"At the beginning of your upkeep, each player exiles cards from the
    top of their library until they exile a nonland card. An opponent
    chooses a nonland card exiled this way. You may cast up to two spells
    from among the other cards exiled this way without paying their mana
    costs." (Plargg and Nassari, PAR-60.)

    Documented simplification: "an opponent chooses a nonland card exiled
    this way" is auto-resolved — the highest-mana-value nonland exiled is
    the one denied; up to two of the remaining nonland cards (highest mana
    value first) get a this-turn free-cast window.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        cid = getattr(self.source, "controller_id", None)
        name = self.source.name if self.source is not None else "Plargg and Nassari"
        nonlands: list[GameObject] = []
        for player in list(context.state.players):
            while player.library:
                top = player.library.pop()
                top.zone = Zone.EXILE
                player.exile.append(top)
                context.state.fire_event(GameEvent(
                    EventType.EXILE, player_id=player.id, object=top.name,
                    from_zone="library",
                ))
                if not top.card.is_land:
                    nonlands.append(top)
                    break
        if not nonlands:
            return
        nonlands.sort(
            key=lambda o: int(getattr(o.card, "converted_mana_cost", 0) or 0), reverse=True,
        )
        denied = nonlands[0]
        castable = [o for o in nonlands[1:] if not o.card.is_land][:2]
        try:
            caster = context.state.player_by_id(cid) if cid is not None else None
        except (KeyError, ValueError):
            caster = None
        for o in castable:
            holder = caster or context.state.player_by_id(o.owner_id)
            context.engine._grant_temp_play_permission(o, holder, name, True, None)
            context.state.free_cast_instance_ids.add(o.instance_id)
        _ = denied  # stays exiled with no permission


class AbstractPerformanceEffect(GameEffect):
    """"Exile the top four cards of your library in a face-down pile, then
    exile the top four cards of your library in a face-up pile. An opponent
    chooses one of those piles. Put that pile into your graveyard. Look at
    the cards in the other pile. You may cast a spell from among them
    without paying its mana cost. Put the rest into your hand." (Abstract
    Performance, PAR-60.)

    Documented simplification: "an opponent chooses one of those piles" is
    auto-resolved — the pile with the higher total mana value goes to your
    graveyard (the denial an opponent would pick). From the kept pile, the
    highest-mana-value non-land card gets a this-turn free-cast window; the
    rest go to your hand.
    """

    _PILE = 4

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return

        def _take(n: int) -> list[GameObject]:
            out: list[GameObject] = []
            for _ in range(n):
                if not player.library:
                    break
                out.append(player.library.pop())
            return out

        pile_a = _take(self._PILE)
        pile_b = _take(self._PILE)
        if not pile_a and not pile_b:
            return

        def _mv(pile: list[GameObject]) -> int:
            return sum(int(getattr(o.card, "converted_mana_cost", 0) or 0) for o in pile)

        to_graveyard, kept = (
            (pile_a, pile_b) if _mv(pile_a) >= _mv(pile_b) else (pile_b, pile_a)
        )
        for o in to_graveyard:
            o.zone = Zone.GRAVEYARD
            player.graveyard.append(o)
        spells = sorted(
            (o for o in kept if not o.card.is_land),
            key=lambda o: int(getattr(o.card, "converted_mana_cost", 0) or 0),
            reverse=True,
        )
        free = spells[0] if spells else None
        name = self.source.name if self.source is not None else "Abstract Performance"
        for o in kept:
            if o is free:
                o.zone = Zone.EXILE
                player.exile.append(o)
                context.state.fire_event(GameEvent(
                    EventType.EXILE, player_id=player.id, object=o.name, from_zone="library",
                ))
                context.engine._grant_temp_play_permission(o, player, name, True, None)
                context.state.free_cast_instance_ids.add(o.instance_id)
            else:
                o.zone = Zone.HAND
                player.hand.append(o)


class DanceWithCalamityEffect(GameEffect):
    """"Shuffle your library. As many times as you choose, you may exile the
    top card of your library. If the total mana value of the cards exiled
    this way is 13 or less, you may cast any number of spells from among
    those cards without paying their mana costs." (Dance with Calamity,
    PAR-60.)

    Documented simplification: the "as many times as you choose" gamble is
    auto-resolved greedily — exile from the top while the running total mana
    value stays ``<= budget``, stop before the first card that would exceed
    it — rather than an interactive stop/continue loop. Every non-land card
    exiled this way gets a this-turn free-cast window from exile.
    """

    _BUDGET = 13  # RULE-neutral: the printed threshold.

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        context.engine.shuffle_library(player)
        total = 0
        name = self.source.name if self.source is not None else "Dance with Calamity"
        while player.library:
            top = player.library[-1]
            mv = int(getattr(top.card, "converted_mana_cost", 0) or 0)
            if total + mv > self._BUDGET:
                break
            total += mv
            player.library.pop()
            top.zone = Zone.EXILE
            player.exile.append(top)
            context.state.fire_event(GameEvent(
                EventType.EXILE, player_id=player.id, object=top.name, from_zone="library",
            ))
            if not top.card.is_land:
                context.engine._grant_temp_play_permission(top, player, name, True, None)
                context.state.free_cast_instance_ids.add(top.instance_id)


class BudgetDigOntoBattlefieldEffect(GameEffect):
    """"Look at the top N cards of your library. Put any number of nonland
    permanent cards with total mana value M or less from among them onto the
    battlefield. Put the rest on the bottom of your library in a random
    order." (Ao, the Dawn Sky's first mode, PAR-60.)

    Documented simplification: "any number … with total mana value M or
    less" is auto-resolved greedily — take nonland permanent cards
    cheapest-first while the running total stays within ``budget`` — rather
    than an interactive multi-pick.
    """

    def __init__(
        self, look: int = 7, budget: int = 4, source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.look = int(look)
        self.budget = int(budget)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        import random

        player = _controller_of(self.source, context)
        if player is None or not player.library:
            return
        looked = [player.library.pop() for _ in range(min(self.look, len(player.library)))]
        for o in looked:
            context.state.fire_event(GameEvent(
                EventType.REVEAL, player_id=player.id, object=o.name,
                instance_id=o.instance_id, from_zone="library",
            ))
        cands = sorted(
            (o for o in looked if _is_permanent_card_obj(o) and not o.card.is_land),
            key=lambda o: int(getattr(o.card, "converted_mana_cost", 0) or 0),
        )
        taken: list[GameObject] = []
        total = 0
        for o in cands:
            mv = int(getattr(o.card, "converted_mana_cost", 0) or 0)
            if total + mv <= self.budget:
                total += mv
                taken.append(o)
        for o in taken:
            context.engine._put_searched_card(player, o, "battlefield")
        rest = [o for o in looked if o not in taken]
        random.shuffle(rest)
        for o in rest:
            o.zone = Zone.LIBRARY
            player.library.insert(0, o)
        context.recompute()


def _is_permanent_card_obj(obj: Any) -> bool:
    card = getattr(obj, "card", None)
    if card is None:
        return False
    tl = (getattr(card, "type_line", "") or "").lower()
    return any(w in tl for w in (
        "creature", "artifact", "enchantment", "planeswalker", "land", "battle",
    ))


# ===========================================================================
# PAR-60 round 4 (waves 97-103) — the last Secrets of Strixhaven cards, each
# reducible to an existing primitive + a small extension or a documented
# simplification (per the user's read that "the last cards … have mainly a
# generalization for existing effects or a combination of mechanics that
# already exist").
# ===========================================================================


class SacrificeAnyNumberDrawLoseScaledEffect(GameEffect):
    """Plumb the Forbidden — "As an additional cost to cast this spell, you
    may sacrifice one or more creatures. When you do, copy this spell for
    each creature sacrificed this way. You draw a card and lose 1 life."

    Reuses the Eventide's Shadow idiom (`RemoveCountersFromAmongThenDraw
    LoseLifeEffect`): an optional multi-pick `_request_choose_objects`
    (action ``sacrifice``) plus a queued ``then_specs`` tail that reads a
    before/after graveyard-size delta to learn how many were sacrificed.

    Documented simplifications: the additional cost is paid at *resolution*
    rather than at announcement (RULE 601.2b), and "copy this spell for each
    creature sacrificed" is modeled as its net effect — one extra "draw a
    card, lose 1 life" per creature sacrificed — instead of putting real
    copies on the stack.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        # Base spell effect (RULE 601.2b's cost is optional, so this always
        # happens exactly once regardless of the sacrifice).
        context.draw(player, 1)
        context.lose_life(player, 1)
        creatures = [
            o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
        ]
        if not creatures:
            return
        before = len(player.graveyard)
        context.engine._request_choose_objects(
            player, creatures, "sacrifice", count=len(creatures), optional=True,
            source=self.source, prompt="Opfere beliebig viele Kreaturen",
            then_specs=[{
                "type": "sacrifice_count_draw_lose",
                "params": {"player_id": player.id, "before": before},
            }],
        )


class SacrificeCountDrawLoseTailEffect(GameEffect):
    """The "…for each creature sacrificed this way" tail of
    `SacrificeAnyNumberDrawLoseScaledEffect` — queued as ``then_specs``,
    reads a graveyard-size delta against a snapshot. Not for direct card use.
    """

    def __init__(
        self, player_id: Optional[str] = None, before: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.player_id = player_id
        self.before = int(before)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        try:
            player = context.state.player_by_id(self.player_id)
        except (KeyError, ValueError):
            return
        n = len(player.graveyard) - self.before
        if n > 0:
            context.draw(player, n)
            context.lose_life(player, n)


class ImmoralBargainEffect(GameEffect):
    """Immoral Bargain — "As an additional cost to cast this spell, sacrifice
    X creatures. Destroy X target nonland permanents."

    Immoral Bargain has no {X} in its printed mana cost — X is defined
    solely by how many creatures are sacrificed as the additional cost
    (RULE 601.2b). Reuses the same sacrifice-choose + delta-tail idiom as
    `SacrificeAnyNumberDrawLoseScaledEffect`, then destroys that many
    nonland permanents chosen the same way (the new ``destroy`` action of
    `_request_choose_objects`).

    Documented simplification: both the additional-cost sacrifice and the
    number of targets are resolved at *resolution* rather than at
    announcement.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        creatures = [
            o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
        ]
        if not creatures:
            return
        before = len(player.graveyard)
        context.engine._request_choose_objects(
            player, creatures, "sacrifice", count=len(creatures), optional=True,
            source=self.source, prompt="Opfere X Kreaturen",
            then_specs=[{
                "type": "immoral_bargain_destroy",
                "params": {"player_id": player.id, "before": before},
            }],
        )


class ImmoralBargainDestroyTailEffect(GameEffect):
    """The "Destroy X target nonland permanents" tail of `ImmoralBargain
    Effect` — X is the graveyard-size delta from the sacrifice. Not for
    direct card use.
    """

    def __init__(
        self, player_id: Optional[str] = None, before: int = 0,
        source: Optional["GameObject"] = None,
    ) -> None:
        super().__init__(source)
        self.player_id = player_id
        self.before = int(before)

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        try:
            player = context.state.player_by_id(self.player_id)
        except (KeyError, ValueError):
            return
        n = len(player.graveyard) - self.before
        if n <= 0:
            return
        cands = [o for o in context.state.battlefield if not o.card.is_land]
        if not cands:
            return
        context.engine._request_choose_objects(
            player, cands, "destroy", count=min(n, len(cands)), optional=False,
            source=self.source, prompt="Zerstoere X Nichtland-bleibende Karten",
        )


class Base0CombatDamageFractalEffect(GameEffect):
    """Primo, the Unbounded's second ability — "Whenever one or more
    creatures you control with base power 0 deal combat damage to a player,
    create a 0/0 green and blue Fractal creature token. Put a number of
    +1/+1 counters on it equal to the damage dealt."

    The base-power-0 filter is the trigger's per-contributor ``base_power``
    filter (PAR-131). This effect reads `EventType.CREATURES_DEALT_COMBAT_
    DAMAGE_TO_PLAYER`'s ``base_power_0_amount`` (stamped by
    `combat_mixin._apply_combat_damage`) for the counter count — the combat
    damage those base-power-0 creatures dealt to that player this step.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        event = context.trigger_event or {}
        n = int(event.get("base_power_0_amount") or event.get("amount") or 0)
        card = synthesize_token_card(
            "Fractal", power=0, toughness=0, colors=["G", "U"], subtypes=["Fractal"],
        )
        made = context.create_token(cid, card, 1)
        for tok in made or []:
            if n > 0:
                context.add_counters(tok, n, "+1/+1", source=self.source)
        context.recompute()


class DoubleCastXEffect(GameEffect):
    """Unbound Flourishing's first ability — "Whenever you cast a permanent
    spell with a mana cost that contains {X}, double the value of X."

    Finds the just-cast spell's `StackItem` (via the SPELL_CAST event's
    ``instance_id``) and doubles its announced X (RULE 107.3-adjacent) so
    the spell's own resolution — X entering counters, an X/X body, X tokens
    — sees 2X.

    Documented simplification: the trigger fires for every {X} spell you
    cast; this effect no-ops unless the spell is a *permanent* spell (the
    clause's own scope), and doubles the value on the stack item already
    announced rather than as a RULE 614 cast-announcement replacement —
    the same board state for every permanent spell in scope.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        event = context.trigger_event or {}
        iid = event.get("instance_id")
        if iid is None:
            return
        for item in list(context.state.stack):
            obj = getattr(item, "obj", None)
            if obj is None or obj.instance_id != iid:
                continue
            if not _is_permanent_card_obj(obj):
                return
            if getattr(item, "x", 0):
                item.x = int(item.x) * 2
            if getattr(obj, "x_paid", 0):
                obj.x_paid = int(obj.x_paid) * 2
            return


class MirrorwingCopyEffect(GameEffect):
    """Mirrorwing Dragon — "Whenever a player casts an instant or sorcery
    spell that targets only this creature, that player copies that spell for
    each other creature they control that the spell could target. Each copy
    targets a different one of those creatures."

    Reuses `RulesEngine.copy_spell` once per creature with a per-copy
    ``new_targets`` list — the "each copy targets a different one" clause
    that `CopySpellEffect`'s shared-``new_targets`` path can't express on
    its own.

    Documented simplification: "that the spell could target" is read as
    "every other creature that player controls" — the per-copy legality
    re-check against the copied spell's own `TargetSpec` is skipped, which
    is exact for the common "target creature"/"any target" burn and pump
    Mirrorwing is built around.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self.source is None:
            return
        event = context.trigger_event or {}
        iid = event.get("instance_id")
        item = None
        for entry in list(context.state.stack):
            if getattr(entry, "obj", None) is not None and entry.obj.instance_id == iid:
                item = entry
                break
        if item is None:
            return
        # "targets only this creature": every target of the spell is this
        # permanent, and there is at least one.
        tgts = list(getattr(item, "targets", []) or [])

        def _tid(t: Any) -> Any:
            return t.get("instance_id") if isinstance(t, dict) else getattr(t, "instance_id", None)

        if not tgts or any(_tid(t) != self.source.instance_id for t in tgts):
            return
        caster_id = event.get("player_id") or getattr(item, "controller_id", None)
        if caster_id is None:
            return
        others = [
            o for o in context.state.permanents_controlled_by(caster_id)
            if o.is_creature and o.instance_id != self.source.instance_id
        ]
        for creature in others:
            context.engine.copy_spell(item, caster_id, 1, [creature])


class NilsEndStepCountersEffect(GameEffect):
    """Nils, Discipline Enforcer's first ability — "At the beginning of your
    end step, for each player, put a +1/+1 counter on up to one target
    creature that player controls."

    Documented simplification: "up to one target creature that player
    controls" is auto-resolved per player rather than an interactive pick —
    Nils's controller would spread counters to grow their own board and to
    load opponents' best attackers with the (clause-2) attack tax, so the
    pick is that player's highest-power creature.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        for player in list(context.state.players):
            creatures = [
                o for o in context.state.permanents_controlled_by(player.id) if o.is_creature
            ]
            if not creatures:
                continue
            pick = max(creatures, key=lambda o: int(o.power or 0))
            context.add_counters(pick, 1, "+1/+1", source=self.source)
        context.recompute()


class IntermediateChirographyL3Effect(GameEffect):
    """Intermediate Chirography's level-3 body — "At the beginning of each
    end step, if a modified creature died under your control this turn,
    create a 2/1 white and black Inkling creature token with flying."

    Self-gates on `GameState.modified_creatures_died_this_turn` (a
    ``creatures_died_this_turn`` sibling), the same inline-gate idiom
    `ZimoneAllQuestioningEndStepEffect` uses rather than a `static_
    conditions` intervening-if. Fires at every player's end step (no
    ``phase_relation``); the level-3 gate is on the trigger.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        from ...services.token_database import synthesize_token_card

        cid = getattr(self.source, "controller_id", None)
        if cid is None:
            return
        if context.state.modified_creatures_died_this_turn.get(cid, 0) <= 0:
            return
        card = synthesize_token_card(
            "Inkling", power=2, toughness=1, colors=["W", "B"],
            subtypes=["Inkling"], keywords=["Flying"],
        )
        context.create_token(cid, card, 1)


class AdvancedReconstructionL1Effect(GameEffect):
    """Advanced Reconstruction's level-1 body — "At the beginning of your
    first main phase, mill a card, then exile a card from your graveyard at
    random. You may play the exiled card this turn."

    Mill + a uniformly-random graveyard pick + `RulesEngine._grant_temp_
    play_permission` (a normal-cost "you may play this" window, not a free
    cast).
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        import random

        player = _controller_of(self.source, context)
        if player is None:
            return
        context.mill(player, 1)
        if not player.graveyard:
            return
        pick = random.choice(list(player.graveyard))
        context.exile(pick)
        name = self.source.name if self.source is not None else "Advanced Reconstruction"
        context.engine._grant_temp_play_permission(pick, player, name, True, None)


class AnimistsAwakeningEffect(GameEffect):
    """"Reveal the top X cards of your library. Put all land cards from among
    them onto the battlefield tapped and the rest on the bottom of your
    library in a random order. Spell mastery — If there are two or more
    instant and/or sorcery cards in your graveyard, untap those lands."
    (Animist's Awakening, PAR-60.)

    ``count`` accepts the ``"x"`` sentinel `_substitute_x` rewrites with the
    announced {X}. Distinct from `RevealUntilMatchingEffect` (reveal *until*
    N hits): this reveals a *fixed* X and takes *every* land among them.
    """

    #: RULE 702.101a — spell mastery threshold.
    _SPELL_MASTERY_MIN = 2

    def __init__(self, count: Any = "x", source: Optional["GameObject"] = None) -> None:
        super().__init__(source)
        self.count = count

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        import random

        player = _controller_of(self.source, context)
        if player is None:
            return
        count = self.count if isinstance(self.count, int) else 0
        if count <= 0 or not player.library:
            return
        revealed: list[GameObject] = []
        for _ in range(count):
            if not player.library:
                break
            obj = player.library.pop()
            revealed.append(obj)
            context.state.fire_event(GameEvent(
                EventType.REVEAL, player_id=player.id, object=obj.name,
                instance_id=obj.instance_id, from_zone="library",
            ))
        lands = [o for o in revealed if o.card.is_land]
        rest = [o for o in revealed if o not in lands]
        placed: list[GameObject] = []
        for land in lands:
            context.engine._put_searched_card(player, land, "battlefield_tapped")
            placed.append(land)
        random.shuffle(rest)
        for o in rest:
            o.zone = Zone.LIBRARY
            player.library.insert(0, o)  # bottom
        # spell mastery
        is_count = sum(
            1 for c in player.graveyard
            if getattr(c.card, "is_instant", False) or getattr(c.card, "is_sorcery", False)
        )
        if is_count >= self._SPELL_MASTERY_MIN:
            for land in placed:
                context.set_tapped(land, tapped=False)


class DescendantsFurySacrificeEffect(GameEffect):
    """Descendants' Fury triggered ability (MEC-72).

    Prompts the controller with an optional choice to sacrifice one of the
    creatures that dealt combat damage to a player.
    """

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        event = context.trigger_event
        contributor_ids = event.get("contributor_ids") if event else []
        candidates = [
            context.state.find_object(iid)
            for iid in contributor_ids
        ]
        candidates = [
            c for c in candidates
            if c is not None and c in context.state.battlefield and c.controller_id == player.id
        ]
        if not candidates:
            return
        context.engine._request_choose_objects(
            player,
            candidates,
            action="sacrifice_for_descendants_fury",
            count=1,
            optional=True,
            prompt="Kreatur für Nachfahrenzorn opfern",
            source=self.source,
        )


class InspectTopChooseEffect(GameEffect):
    """Bounded top-N library inspect and filtered pick (MEC-72).

    Inspects top N cards of the library, offers a filtered choice, and puts
    the rest to rest_destination (Eclipsed Flamekin, Cream of the Crop,
    Cavalier of Thorns).

    ``max_picks_if_teamwork`` (MEC-85, Earth's Mightiest Heroes — "You may
    put a creature card from among them onto the battlefield. If this
    spell was cast using teamwork, put any number of creature cards from
    among them onto the battlefield instead.") overrides ``max_picks``
    (the printed cap, 1) the same override-not-additive way `DealDamage
    Effect.amount_if_teamwork` overrides its own ``amount`` — read here,
    not in `RulesEngine.inspect_top_n_choose` itself, so that method stays
    a plain "how many" knob with no Teamwork knowledge of its own. Unlike
    `TargetSpec.unless_flag` (Cruel Alliance/Too Evil to Stay Dead's own
    RULE 115 target-filter gate), there's no target here to offer early —
    "a creature card from among them" is a library-zone pick made after
    the spell has already fully resolved onto the stack, so reading the
    real, final `GameObject.teamwork_paid` at `apply()` time (like
    `amount_if_teamwork`) is correct, not just convenient.
    """

    def __init__(
        self,
        count: Union[int, str] = 1,
        action: str = "library_to_hand",
        filter: Optional[dict[str, Any]] = None,
        rest_destination: str = "library_bottom_random",
        optional: bool = False,
        prompt: str = "Wähle eine Karte",
        decline_leaves_untouched: bool = False,
        max_picks: Union[int, str] = 1,
        max_picks_if_teamwork: Optional[int] = None,
        source: Optional["GameObject"] = None,
        criteria: Optional[dict[str, Any]] = None,
        else_effects: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(source)
        #: PAR-144: a `models.cards.card_query` dict ("a creature or land card", "a card with
        #: mana value X or less") — named ``criteria`` so `RulesEngine._substitute_x` rewrites its
        #: ``"x"`` mana-value bound like every other criteria-carrying effect's.
        self.criteria = criteria
        #: PAR-144: serialized `EffectSpec` dicts run when nothing was picked ("if you didn't put
        #: a card into your hand this way, draw a card").
        self.else_effects = else_effects
        self.count = count
        self.action = action
        self.filter = filter
        self.rest_destination = rest_destination
        self.optional = optional
        self.prompt = prompt
        self.decline_leaves_untouched = decline_leaves_untouched
        self.max_picks = max_picks
        self.max_picks_if_teamwork = max_picks_if_teamwork

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        player = _controller_of(self.source, context)
        if player is None:
            return
        max_picks = self.max_picks
        if self.max_picks_if_teamwork is not None and bool(getattr(self.source, "teamwork_paid", False)):
            max_picks = self.max_picks_if_teamwork
        count = self._measured(self.count, context, targets)
        criteria = self._resolved_criteria()
        context.engine.inspect_top_n_choose(
            player,
            count=count,
            action=self.action,
            filter_criteria=self.filter,
            rest_destination=self.rest_destination,
            optional=self.optional,
            prompt=self.prompt,
            source=self.source,
            decline_leaves_untouched=self.decline_leaves_untouched,
            max_picks=max_picks,
            criteria=criteria,
            else_specs=self.else_effects,
        )

    def _resolved_criteria(self) -> Optional[dict[str, Any]]:
        """``criteria`` with any mana-value bound `_substitute_x` did not reach bound to the
        source's own announced X — a triggered ability ("when you cast this spell, reveal the
        top X cards … mana value X or less", Genesis Hydra) never had an X of its own."""
        if not self.criteria:
            return None
        resolved = dict(self.criteria)
        for key in ("max_mana_value", "min_mana_value"):
            if resolved.get(key) in ("x", "source_x_paid"):
                resolved[key] = int(getattr(self.source, "x_paid", 0) or 0)
        return resolved


class BlinkEffect(GameEffect):
    """"Exile target permanent, then return it to the battlefield under its
    owner's control" (RULE 400.7 — Ephemerate/Momentary Blink-shaped).

    Distinct from `ReturnFromGraveyardEffect` (a graveyard-only recursion
    family): this targets a *battlefield* permanent. See `RulesEngine.
    blink`'s docstring for why exiling then re-entering is a genuine RULE
    400.7 "new object" rather than a single no-op move.

    ``under_your_control`` is Restoration Angel's own "return that card to
    the battlefield **under your control**" — this effect's controller
    rather than the target's owner (`RulesEngine.blink`'s ``controller``
    param). Default ``False`` is plain blink, always under the owner.
    """

    def __init__(
        self,
        target: Any = None,
        source: Optional["GameObject"] = None,
        target_kind: str = "creature_you_control",
        under_your_control: bool = False,
        creature_filter: Optional[dict] = None,
        optional: bool = False,
        count: int = 1,
        count_max: Optional[int] = None,
        trigger_event_key: Optional[str] = None,
        tapped: bool = False,
    ) -> None:
        super().__init__(source)
        self.target = target
        #: Returns tapped ("…then return them to the battlefield tapped under their owner's control").
        self.tapped = bool(tapped)
        #: ``target_kind="trigger_subject"`` (PAR-123, Gossip's Talent's "exile
        #: **it**, then return it …") — no RULE 115 target; the object that
        #: fired the trigger, read off `GameContext.trigger_event`.
        self._trigger_subject_mode = target_kind == "trigger_subject"
        self.trigger_event_key = trigger_event_key or "instance_id"
        self.target_spec = None if self._trigger_subject_mode else TargetSpec(
            kind=target_kind, creature_filter=creature_filter,
            optional=optional, count=count, count_max=count_max,
        )
        self.under_your_control = under_your_control

    def apply(self, context: GameContext, targets: Optional[list[Any]] = None) -> None:
        if self._trigger_subject_mode:
            obj_id = (context.trigger_event or {}).get(self.trigger_event_key)
            subject = context.state.find_object(obj_id) if obj_id is not None else None
            if subject is not None:
                context.blink(subject)
            return
        chosen = targets if targets else ([self.target] if self.target is not None else [])
        controller = _controller_of(self.source, context) if self.under_your_control else None
        for target in chosen:
            if target is not None:
                context.blink(target, controller=controller, tapped=self.tapped)



register(globals())
