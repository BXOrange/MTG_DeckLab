"""Replacement-effect factories and their secure registry."""
from __future__ import annotations

from .core import GameEffect, ReplacementEffect
from ._runtime import install, register

install(globals())

def _prevent_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A standing damage-prevention shield (RULE 615/616.1) — the *permanent*
    sibling of `PreventDamageEffect`'s one-shot spell grant (registered
    separately as ``"prevent_damage_shield"``, Riot Control/Thought Lash;
    unrelated despite the shared name prefix).

    ``to`` selects the recipient, read off the effect's own source: ``"self"``
    (the source permanent itself), ``"controller"`` (its controller — a
    player), ``"any_player"`` (any player at all — Battletide Alchemist),
    ``"opponent_player"`` (any player who isn't the controller — Hostility's
    "an opponent"), ``"attached_permanent"`` (an Aura/Equipment's own host —
    Shield of the Realm/Avatar), or ``"controlled_permanent"`` (any permanent this
    effect's controller controls, optionally narrowed by ``recipient_filter``
    — a `combat.matches_object_filter`-shaped dict, e.g. Daunting Defender's
    ``{"subtype": "cleric"}``, Djeru's ``{"card_type": "planeswalker"}``,
    Temple Altisaur's ``{"subtype": "dinosaur", "exclude_self": True}`` for
    "**another** Dinosaur" — ``exclude_self`` resolves to a
    ``without_instance_id`` filter against the shield's own source at match
    time, since that id isn't known until bind time). ``recipient_union`` (a
    list of ``"controller"``/``"any_player"``/filter-dict entries) is the
    "you or a `<X>` you control" shape (Hyperion/Ajani Steadfast's emblem) —
    matches if *any* entry matches; a filter-dict entry always means "a
    controlled permanent matching this filter", the same as
    ``"controlled_permanent"`` above.

    ``source_filter`` narrows *who's dealing* the damage — ``color`` (a
    single WUBRG letter, checked against the event's own precomputed
    ``source_colors``), ``card_type`` (looked up fresh off the source object
    via `GameState.find_object`, mirroring `_additional_damage_replacement`'s
    own "artifact" check — the event carries no type flag of its own),
    ``is_creature``/``is_spell`` (the event's own ``source_is_creature``/
    ``source_is_instant_or_sorcery`` — RULE 609.7a: a resolving instant/
    sorcery *is* "a spell" for this purpose), and ``controller`` (``"you"``/
    ``"opponent"``, against the event's own ``source_controller_id``).

    ``amount`` is an ``int`` (prevent up to that much — ``dealt - amount``
    survives), the string ``"all"`` (fully prevented), ``{"all_but": N}``
    (Temple Altisaur/Hyperion/Ajani's emblem — only ``N`` survives), or
    ``{"half": "up"|"down"}`` (Gisela's "prevent half, rounded up"; Dark
    Sphere's "rounded down"). ``amount_count_selector`` resolves the ``int``
    amount live via `continuous.count_selector` instead (Shield of the
    Avatar/Battletide Alchemist's "X is the number of creatures/Clerics you
    control").

    ``rider`` (``{"kind": ..., "recipient": ...}``) fires a follow-up off the
    *actual* prevented amount once it's known — see
    `RulesEngine.apply_prevent_rider` (Swans of Bryn Argoll/Hostility-shaped
    "…and `<X>` this way").

    Consulted through the same `RulesEngine.apply_replacements` path
    `deal_damage` already runs, so it needs no new plumbing.
    """
    amount = params.get("amount", "all")
    amount_count_selector = params.get("amount_count_selector")
    to = params.get("to", "self")
    recipient_filter = params.get("recipient_filter")
    recipient_union = params.get("recipient_union")
    source_filter = params.get("source_filter")
    rider = params.get("rider")
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "prevent damage")),
    )
    #: MEC-30: marks this as a prevention-shaped effect for "damage can't be
    #: prevented this turn" (Insult // Injury/Isengard Unleashed) to filter
    #: out generically — distinct from `damage_prevention_shield` (which
    #: means "sweep me at cleanup, I'm one-turn-only" and would be *wrong*
    #: to set here: this factory also builds Family A's standing, permanent
    #: shields and Absorb's structural one, none of which expire after one
    #: turn). Covers Absorb for free — `effect_binder.attach_to_object`'s
    #: Absorb branch reuses this exact factory.
    effect.prevents_damage = True

    def _controlled_permanent_matches(
        filt: Optional[dict], event: GameEvent, context: GameContext, src: Any,
    ) -> bool:
        if event.get("is_player") or src is None:
            return False
        target_obj = context.state.find_object(event.get("target_id"))
        if target_obj is None or target_obj.controller_id != src.controller_id:
            return False
        from .. import combat  # local: avoid the combat<->effects import cycle

        resolved_filt = dict(filt or {})
        if resolved_filt.pop("exclude_self", False):
            resolved_filt["without_instance_id"] = src.instance_id
        return combat.matches_object_filter(target_obj, resolved_filt)

    def _recipient_entry_matches(entry: Any, event: GameEvent, context: GameContext, src: Any) -> bool:
        if entry == "controller":
            return bool(event.get("is_player")) and src is not None and event.get("target_id") == src.controller_id
        if entry == "any_player":
            return bool(event.get("is_player"))
        if entry == "opponent_player":
            return (
                bool(event.get("is_player")) and src is not None
                and event.get("target_id") != src.controller_id
            )
        return _controlled_permanent_matches(entry, event, context, src)

    def _recipient_matches(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if recipient_union is not None:
            return any(_recipient_entry_matches(e, event, context, src) for e in recipient_union)
        if to == "self":
            return (
                not event.get("is_player") and src is not None
                and event.get("target_id") == src.instance_id
            )
        if to == "attached_permanent":
            host_id = getattr(src, "attached_to", None)
            return (
                not event.get("is_player") and host_id is not None
                and event.get("target_id") == host_id
            )
        if to == "controlled_permanent":
            return _controlled_permanent_matches(recipient_filter, event, context, src)
        # PAR-78: "Prevent all damage that would be dealt to creatures[ you
        # control]." (Bubble Matrix/Inner Sanctum/Iroas/Emmara Tandris) —
        # every creature (``"all_creatures"``) or only this shield's
        # controller's own (``"creatures_you_control"``), optionally
        # narrowed further by ``recipient_filter`` (a `combat.
        # matches_object_filter`-shaped dict, e.g. Iroas' ``{"attacking":
        # True}``, Emmara's ``{"token": True}``). Distinct from
        # ``"controlled_permanent"`` above, which has no creature-only
        # reading in `matches_object_filter`'s own vocabulary.
        if to in ("all_creatures", "creatures_you_control"):
            if event.get("is_player"):
                return False
            target_obj = context.state.find_object(event.get("target_id"))
            if target_obj is None or not target_obj.is_creature:
                return False
            if to == "creatures_you_control" and (
                src is None or target_obj.controller_id != src.controller_id
            ):
                return False
            if not recipient_filter:
                return True
            from .. import combat  # local: avoid the combat<->effects import cycle

            return combat.matches_object_filter(target_obj, recipient_filter)
        if to in ("any_player", "opponent_player"):
            return _recipient_entry_matches(to, event, context, src)
        if to == "any":
            return True
        return _recipient_entry_matches("controller", event, context, src)  # "controller", the default

    def _source_matches(event: GameEvent, context: GameContext) -> bool:
        if not source_filter:
            return True
        src = effect.source
        color = source_filter.get("color")
        if color is not None and color not in (event.get("source_colors") or ()):
            return False
        # "…by sources of the chosen color." (Prismatic Ward, PAR-78) — the
        # standing sibling of `combat.matches_object_filter`'s own
        # ``color_from_source`` (Story Circle/Prismatic Circle's identical
        # RULE 601.2b ETB colour pick, read live off this shield's own
        # source rather than a literal colour baked in at parse time).
        if source_filter.get("color_from_source"):
            chosen = getattr(src, "chosen_color", None)
            if not chosen or chosen not in (event.get("source_colors") or ()):
                return False
        card_type = source_filter.get("card_type")
        if card_type is not None:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is None or not bool(getattr(src_obj.card, f"is_{card_type}", False)):
                return False
        if source_filter.get("is_creature") and not event.get("source_is_creature"):
            return False
        # PAR-139: "if noncombat damage would be dealt to …" (Purity, Stormwild Capridor) — the event's
        # own ``combat`` flag, which `RulesEngine.deal_damage` stamps on every DAMAGE event.
        if "combat" in source_filter and bool(event.get("combat")) != bool(source_filter["combat"]):
            return False
        if source_filter.get("is_spell") and not event.get("source_is_instant_or_sorcery"):
            return False
        # PAR-78: "…by deserts."/"…by creatures with first strike."/"…by
        # enchanted creatures." — a subtype/keyword/enchanted source filter,
        # alongside the pre-existing ``card_type``/``is_creature`` checks
        # above.
        subtype = source_filter.get("subtype")
        keyword = source_filter.get("keyword")
        enchanted = source_filter.get("enchanted")
        if subtype is not None or keyword is not None or enchanted:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is None:
                return False
            if subtype is not None and subtype.lower() not in (src_obj.card.type_line or "").lower():
                return False
            if keyword is not None:
                from .. import combat  # local: avoid the combat<->effects import cycle

                if not combat.has(src_obj, keyword):
                    return False
            if enchanted and not any(
                o.attached_to == src_obj.instance_id and "aura" in o.card.type_line.lower()
                for o in context.state.permanents()
            ):
                return False
        controller = source_filter.get("controller")
        if controller is not None:
            shield_controller_id = getattr(src, "controller_id", None)
            if shield_controller_id is None:
                return False
            if controller == "opponent" and event.get("source_controller_id") == shield_controller_id:
                return False
            if controller == "you" and event.get("source_controller_id") != shield_controller_id:
                return False
        return True

    def _survives(dealt: int, src: Any, context: GameContext) -> int:
        if amount_count_selector:
            from .. import continuous  # local: avoid the continuous<->effects import cycle

            n = continuous.count_selector(
                context.state, getattr(src, "controller_id", None), amount_count_selector, source=src
            )
            return max(0, dealt - n)
        if isinstance(amount, dict):
            if "all_but" in amount:
                return min(dealt, int(amount["all_but"]))
            if "half" in amount:
                # "rounded up" prevents the larger half, so survives is the
                # floor; "rounded down" prevents the smaller half, so
                # survives is the ceiling.
                return dealt // 2 if amount["half"] == "up" else (dealt + 1) // 2
            return dealt
        if amount == "all":
            return 0
        return max(0, dealt - int(amount))

    #: PAR-139: "if damage would be dealt to ~ **while it has a +1/+1 counter on it**, prevent that damage and
    #: remove …" (Oathsworn Knight, Undergrowth Champion, Ugin's Conjurant) — the shield only exists while its
    #: own permanent holds a counter of this kind.
    requires_counter = params.get("requires_counter")

    def _applies(event: GameEvent, context: GameContext) -> bool:
        if requires_counter and not (getattr(effect.source, "counters", None) or {}).get(str(requires_counter)) and not (
            str(requires_counter) == "+1/+1" and getattr(effect.source, "plus_one_counters", 0)
        ):
            return False
        return _recipient_matches(event, context) and _source_matches(event, context)

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        survives = _survives(dealt, effect.source, context)
        prevented = dealt - survives
        if rider is not None and prevented > 0:
            context.engine.apply_prevent_rider(
                rider, prevented, event, getattr(effect.source, "controller_id", None),
                shield_source=effect.source,
            )
        if survives <= 0:
            return None  # fully prevented — the event doesn't happen
        return event.copy_with(amount=survives)

    effect.replacement_fn = replace
    #: RULE 616.1e (MEC-30 fourth pass): `can_replace` must reflect the
    #: card's real printed condition, not just "same event type" — without
    #: this, Gisela's two unrelated replacements (one scoped to opponents,
    #: one to her own side) both reported "applicable" for *every* damage
    #: event, opening a pointless ordering choice each time only one of them
    #: could ever actually do anything.
    effect.condition = _applies
    return effect


def _prevent_damage_convert_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Prevent damage to the source while it has >=1 ``remove_kind`` counter,
    remove up to that many (capped by how many it actually has), then grant
    ``grant_kind`` counters equal to however many were actually removed
    (RULE 615/616 compound shield — Bloatfly Swarm: "If damage would be dealt
    to this creature while it has a +1/+1 counter on it, prevent that
    damage, remove that many +1/+1 counters from it, then give each player a
    rad counter for each +1/+1 counter removed this way").

    "That many" ties the removed-counter count to the damage amount that
    would have been dealt (not a flat number), so this can't be expressed as
    a plain `_prevent_damage_replacement` + a separate one-shot — the removal
    and the grant both need the *actual* damage amount, known only inside
    the replacement itself. ``to`` is always ``"self"`` in practice (the
    only real card needing this protects only its own source); ``grant_
    selector`` reuses `AddPlayerCountersEffect`'s vocabulary (``"each_
    player"``/``"each_opponent"``), read live off `context.state.players`
    rather than through that effect class, since this fires mid-replacement
    (before any stack item exists to carry an `EffectSpec`).
    """
    remove_kind = str(params.get("remove_kind", "+1/+1"))
    grant_kind = str(params.get("grant_kind", "rad"))
    grant_selector = str(params.get("grant_selector", "each_player"))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        description=str(params.get("description", "")),
    )
    effect.prevents_damage = True  # MEC-30: "damage can't be prevented" filter

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("is_player") or event.get("target_id") != src.instance_id:
            return False
        # "…while it has a +1/+1 counter on it" — literally part of the
        # printed condition, not just a value-based no-op.
        return src.counters.get(remove_kind, 0) > 0

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        current = src.counters.get(remove_kind, 0)
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        removed = min(current, dealt)
        context.engine.add_counters(src, -removed, remove_kind)
        for player in context.state.players:
            if grant_selector == "each_opponent" and player.id == src.controller_id:
                continue
            context.engine.add_player_counters(player, removed, grant_kind, source=src)
        return None  # fully prevented (RULE 614.5 — the damage never happens)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Multiplies damage that would be dealt (RULE 614/616), e.g. Furnace of
    Rath/Dictate of the Twin Gods ("if a source would deal damage, it deals
    double that damage instead" — unscoped), Gratuitous Violence ("a
    *creature* you control", ``creature_only``+``your_sources_only``, no
    combat restriction despite the name), or Fiery Emancipation ("a source
    you control", ``multiplier=3``).

    ``combat_only``/``your_sources_only``/``creature_only`` scope the
    effect; ``your_sources_only`` reads the *replacement's own source's*
    controller (``effect.source``, set at bind time) against the damage
    event's ``source_controller_id`` — so it needs the object it's attached
    to on the battlefield to know whose damage counts as "yours".
    ``multiplier`` defaults to 2 (every real "double" card); Fiery
    Emancipation's "triple" is the only real 3.

    ``to_opponent_only`` (MEC-30, Gisela, Blade of Goldnight's own "…deals
    damage to an opponent or a permanent an opponent controls…", paired
    with a separate ``prevent_damage`` replacement for the "you or a
    permanent you control" mirror) scopes the *recipient* side instead —
    mirrors `_additional_damage_replacement`'s own identically-named/-shaped
    param exactly (the *source* qualifiers, on the other hand, stay
    separate concepts: `_additional_damage_replacement`'s ``colors``/
    ``types`` narrow which sources trigger the bonus, orthogonal to which
    recipients count).
    """
    combat_only = bool(params.get("combat_only", False))
    your_sources_only = bool(params.get("your_sources_only", False))
    creature_only = bool(params.get("creature_only", False))
    to_opponent_only = bool(params.get("to_opponent_only", False))
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,  # replaced below once `effect` exists
        # Left empty by default so `bind_ability` falls back to the card's
        # own (German) `raw_text` for the RULE 616.1 ordering-choice label —
        # only an explicit `description` param overrides that.
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        if combat_only and not event.get("combat"):
            return False
        if creature_only and not event.get("source_is_creature"):
            return False
        if your_sources_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if to_opponent_only:
            src = effect.source
            if src is None:
                return False
            if event.get("is_player"):
                if event.get("target_id") == src.controller_id:
                    return False
            else:
                target_obj = context.state.find_object(event.get("target_id"))
                if target_obj is not None and target_obj.controller_id == src.controller_id:
                    return False
        return True

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt * multiplier)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _additional_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Damage that would be dealt is increased by a flat ``amount`` instead
    (RULE 614/616), e.g. Torbran, Thane of Red Fell ("if a red source you
    control would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 2 instead").

    ``your_sources_only`` mirrors `_double_damage_replacement`; ``color``
    (a single RULE 105 letter, e.g. ``"R"``) further restricts to a damage
    source whose printed `Card.color_identity` includes it — a pragmatic
    stand-in for "is that color" (color identity, not true colour, per
    docs/Reference's existing simplifications elsewhere in this engine).
    ``to_opponent_only`` restricts the *target* side ("to an opponent or a
    permanent an opponent controls") to whoever isn't this effect's own
    source's controller — the only notion of "opponent" a 2-player
    goldfish/Replay board has.

    ``colors``/``types`` (Mechanized Warfare's "a red **or** artifact
    source") generalize ``color`` to an OR-combined compound source filter:
    a source qualifies if it matches *any* listed colour (``event``'s own
    ``source_colors``, same as plain ``color``) or *any* listed type word
    (currently only ``"artifact"`` — looked up fresh off the source object's
    printed card via ``event``'s ``source_id``, since `GameEvent.DAMAGE`
    carries no type flag of its own the way it carries ``source_colors``;
    extend the word list here as a real card needs one, mirroring
    `targeting`'s own "extend as needed" precedent). A single legacy
    ``color`` is still accepted standalone (kept for existing callers/tests);
    when either ``colors`` or ``types`` is given, ``color`` is ignored.
    """
    bonus = int(params.get("amount", 0))
    your_sources_only = bool(params.get("your_sources_only", False))
    to_opponent_only = bool(params.get("to_opponent_only", False))
    colors = list(params.get("colors") or ([params["color"]] if params.get("color") else []))
    types = list(params.get("types") or [])
    is_spell = bool(params.get("is_spell", False))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _source_matches(event: GameEvent, context: GameContext) -> bool:
        # "If a **spell** would deal damage…" (Rem Karolus, Stalwart
        # Slayer, MEC-30) — RULE 609.7a: a resolving instant/sorcery is
        # "a spell" for this purpose, the event's own precomputed flag
        # `_prevent_damage_replacement`'s own ``is_spell`` check already
        # reads for the exact same phrase on this card's paired prevention
        # clause.
        if is_spell and not event.get("source_is_instant_or_sorcery"):
            return False
        if not colors and not types:
            return True
        if colors and any(c in (event.get("source_colors") or ()) for c in colors):
            return True
        if types:
            source_id = event.get("source_id")
            src_obj = context.state.find_object(source_id) if source_id is not None else None
            if src_obj is not None:
                for type_word in types:
                    if type_word == "artifact" and bool(src_obj.card.is_artifact):
                        return True
        return False

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if your_sources_only:
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if to_opponent_only:
            if src is None:
                return False
            if event.get("is_player"):
                if event.get("target_id") == src.controller_id:
                    return False
            else:
                target_obj = context.state.find_object(event.get("target_id"))
                if target_obj is not None and target_obj.controller_id == src.controller_id:
                    return False
        return _source_matches(event, context)

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        dealt = int(event.get("amount", 0) or 0)
        if dealt <= 0:
            return event
        return event.copy_with(amount=dealt + bonus)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _damage_floor_from_source_power_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a red source you control would deal an amount of noncombat
    damage less than ~'s power to an opponent, that source deals damage
    equal to ~'s power instead." (Ojer Axonil, Deepest Might) —
    `_additional_damage_replacement`'s floor-shaped sibling: unlike a flat
    bonus, the *threshold and the replacement amount are the same live
    value* (this ability's own source's current power, RULE 613.1), read
    fresh every firing rather than baked in at bind time.
    """
    colors = list(params.get("colors") or ([params["color"]] if params.get("color") else []))
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("source_controller_id") != src.controller_id:
            return False
        if event.get("combat"):
            return False
        if colors and not any(c in (event.get("source_colors") or ()) for c in colors):
            return False
        if event.get("is_player"):
            if event.get("target_id") == src.controller_id:
                return False
        else:
            target_obj = context.state.find_object(event.get("target_id"))
            if target_obj is None or target_obj.controller_id == src.controller_id:
                return False
        # "…damage less than ~'s power" — the threshold comparison is the
        # printed condition itself, not an incidental no-op.
        threshold = int(getattr(src, "power", 0) or 0)
        dealt = int(event.get("amount", 0) or 0)
        return 0 < dealt < threshold

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        threshold = int(getattr(effect.source, "power", 0) or 0)
        return event.copy_with(amount=threshold)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_counters_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Counters that would be placed are doubled instead (RULE 122/614/616),
    e.g. Doubling Season's counter clause: "if an effect would put one or
    more counters on a permanent you control, it puts twice that many
    instead" — deliberately *not* scoped by ``kind`` (omitted, every kind is
    doubled) unless ``kind`` narrows it to one (``"+1/+1"``, ``"loyalty"``, …).

    ``your_effects_only`` (Innkeeper's Talent's "if **you** would put one or
    more counters on a permanent or player, put twice that many… instead")
    is a *different* scoping axis from Doubling Season's own real wording —
    Doubling Season reads the counters' **recipient**'s controller (handled
    by whatever `condition`/binder scoping wraps this replacement, not this
    function), while this flag reads who's **causing** the placement: it
    only doubles a `RulesEngine.add_counters`/`add_player_counters` call
    that named this effect's own source as its ``source`` (via the event's
    ``source_controller_id``, mirroring `_additional_damage_replacement`'s
    ``your_sources_only``) — irrespective of whose permanent or player ends
    up with the counters, which is exactly why the same unscoped
    `EventType.COUNTER` handling below already covers "or player" for free
    once a caller (`RulesEngine.add_player_counters`) fires that event for a
    player recipient too.

    ``plus`` (default ``None``) switches from the multiplicative "twice that
    many" to the *additive* "that many plus N" shape (Hardened Scales/
    Conclave Mentor's "that many plus one +1/+1 counters", RULE 616.1);
    ``multiplier`` (default 2) is the "twice"/"triple" factor otherwise.
    ``recipient`` scopes by the counters' recipient rather than the causer:
    ``"creature_you_control"`` (Branching Evolution/Corpsejack Menace/
    Hardened Scales — a creature this effect's source controls) or
    ``"permanent_you_control"`` (Kami of Whispered Hopes — any permanent);
    read off the event's ``recipient_controller_id``/``recipient_is_
    creature`` against ``effect.source``'s controller.
    """
    kind_filter = params.get("kind")
    your_effects_only = bool(params.get("your_effects_only", False))
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    recipient = params.get("recipient")
    effect = ReplacementEffect(
        event_type=EventType.COUNTER,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        if kind_filter and event.get("kind") != kind_filter:
            return False
        if your_effects_only:
            src = effect.source
            if src is None or event.get("source_controller_id") != src.controller_id:
                return False
        if recipient == "creature":
            # "…put on **a creature**" (Primal Vigor) — any creature, whoever
            # controls it: the recipient-kind test alone, no controller scope.
            if event.get("is_player") or not event.get("recipient_is_creature"):
                return False
        elif recipient is not None:
            src = effect.source
            if src is None or event.get("recipient_controller_id") != src.controller_id:
                return False
            # PAR-109: "…a creature or planeswalker you control or on yourself" (Lae'zel): a permanent of
            # this controller's or the controller themself.
            if recipient == "creature_planeswalker_or_you":
                return bool(
                    event.get("is_player") or event.get("recipient_is_creature") or event.get("recipient_is_planeswalker")
                )
            # PAR-109: a permanent-scoped recipient is never a player ("a permanent you control" is not "you").
            if recipient != "you_player" and event.get("is_player"):
                return False
            if recipient == "you_player" and not event.get("is_player"):
                return False
            if recipient == "creature_you_control" and not event.get("recipient_is_creature"):
                return False
            if recipient == "artifact_or_creature_you_control" and not (
                event.get("recipient_is_creature") or event.get("recipient_is_artifact")
            ):
                return False
        return True

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _roll_dice_modifier_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """RULE 706.3-adjacent advantage / disadvantage: "If you would roll one
    or more dice, instead roll that many dice plus one and ignore the lowest
    roll." (Pixie Guide / Barbarian Class / Wilhelt-adjacent) and its
    mirror "…plus one and ignore the highest roll." (Wet Sock / Grim
    Wanderer-adjacent). Rewrites the pre-roll `EventType.ROLL_DICE` event
    that `RulesEngine.roll_die` fires: bumps ``count`` by ``plus`` and adds
    ``ignore_lowest``/``ignore_highest``. Scoped to the *rolling* player
    being this effect's own controller — RULE 706's "if **you** would roll"
    (no in-scope card grants the advantage to an opponent).

    RULE 614.5 (one application per event) is enforced by the replacement
    loop's identity tracking, so two Pixie Guides stack to "plus two, ignore
    the two lowest" without either re-triggering on its own rewritten event.
    """
    plus = int(params.get("plus", 1))
    ignore_lowest = int(params.get("ignore_lowest", 0))
    ignore_highest = int(params.get("ignore_highest", 0))
    effect = ReplacementEffect(
        event_type=EventType.ROLL_DICE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        return src is not None and event.get("player_id") == src.controller_id

    def replace(event: GameEvent, _context: GameContext) -> Optional[GameEvent]:
        return event.copy_with(
            count=int(event.get("count", 1)) + plus,
            ignore_lowest=int(event.get("ignore_lowest", 0)) + ignore_lowest,
            ignore_highest=int(event.get("ignore_highest", 0)) + ignore_highest,
        )

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _heal_others_on_damage_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """RULE 701.69a + Wolverine, Fierce Fighter: "If damage would be dealt
    to ~, instead that damage is dealt, but all other damage already dealt
    to him is healed." The damage itself is unchanged (returned as-is); the
    *side effect* is that every point of damage already marked on the source
    is removed the instant before this new hit lands (`_finish` then marks
    only the new amount, so the permanent's effective toughness for
    lethality is measured against the latest hit alone).

    Scoped to damage whose recipient is this effect's own source, and RULE
    614.5 one-application-per-event so a multi-source damage step heals
    once per hit, not in a loop.
    """
    effect = ReplacementEffect(
        event_type=EventType.DAMAGE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        return (
            src is not None
            and not event.get("is_player")
            and event.get("target_id") == src.instance_id
        )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        if effect.source is not None:
            context.engine.heal(effect.source)  # "all other damage … is healed"
        return event  # "that damage is dealt" — unchanged

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _draw_exile_face_up_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a player would draw a card, that player exiles that card face up
    instead. Each player may play lands and cast spells from among cards
    they exiled with ~ this turn." (Uba Mask, MEC-43) — unscoped (every
    player's every draw), fired per-card since `RulesEngine._single_draw`
    is the choke point every draw (including a multi-draw's own per-card
    loop) already funnels through.

    Consumes the `EventType.DRAW` event (returns ``None``) and performs the
    zone move itself as a side effect — the same "the fn *is* the effect,
    not just a rewrite" shape `_die_to_exile_replacement` uses — since
    there's no sensible rewritten *draw* event to hand back (the card never
    reaches hand at all). Grants `GameState.temp_play_permissions` the
    instant the card lands in exile, the same "castable/playable from
    exile this turn" marker `RulesEngine.grant_free_cast_window_from_exile`
    already uses, so both the land-play and the cast-legality checks pick
    it up with no new permission channel needed. An empty library is left
    to the ordinary draw-from-empty loss path (RULE 104.3c) rather than
    redirected — nothing exists yet to exile.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        player_id = event.get("player_id")
        try:
            player = context.state.player_by_id(player_id)
        except (KeyError, ValueError):
            return event
        if not player.library:
            return event  # empty library: let the normal draw-loss path see it
        obj = player.library.pop()
        obj.zone = Zone.EXILE
        player.exile.append(obj)
        context.state.temp_play_permissions[obj.instance_id] = context.state.internal_turn.number
        return None  # event consumed — the card never reaches hand

    effect.replacement_fn = replace
    return effect


def _die_to_exile_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If ~ would die, exile it instead" (RULE 616.1) — redirects a
    creature's battlefield→graveyard move to exile. Modeled like
    regeneration's shield: the fn performs the exile as a side effect and
    returns ``None`` to consume the `EventType.WOULD_DIE` event, so
    `RulesEngine._move_to_graveyard` skips the graveyard move.

    ``subject`` scopes which creatures it covers, read off the event's
    ``target_id``/``controller_id`` against ``effect.source``:
    ``"self"`` (Gloomshrieker — only the source itself), ``"you_control"``
    (a creature its controller controls), ``"opponents_control"``
    (Corpseweaver Prodigy — a creature an opponent controls), ``"any"``, or
    ``"damaged_by_source_this_turn"`` (MEC-49 — "if a creature/permanent
    dealt damage by ~ this turn would die, exile it instead" — Baron
    Sengir's back-face family: the dying object's id must be in
    `GameState.creatures_damaged_by_source_this_turn` keyed under this
    ability's own source).
    """
    subject = params.get("subject", "self")
    nontoken_only = bool(params.get("nontoken_only", False))
    #: "…instead exile that card **and create a 2/2 black Zombie creature token**" (Kalitas, Traitor of Ghet) —
    #: a token description (power/toughness/colors/subtypes/token_name) the source's controller creates.
    token = dict(params["create_token"]) if isinstance(params.get("create_token"), dict) else None
    effect = ReplacementEffect(
        event_type=EventType.WOULD_DIE,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        controller_id = event.get("controller_id")
        target_id = event.get("target_id")
        if nontoken_only:
            dying = _context.state.find_object(target_id)
            if dying is None or getattr(dying, "is_token", False):
                return False  # a token is not "that card" and would just cease to exist
        if subject == "self":
            return src is not None and target_id == getattr(src, "instance_id", None)
        if subject == "you_control":
            return src is not None and controller_id == src.controller_id
        if subject == "opponents_control":
            return src is not None and controller_id not in (None, src.controller_id)
        if subject in ("damaged_by_source_this_turn", "damaged_by_attached_this_turn"):
            if src is None:
                return False
            source_id = getattr(src, "instance_id", None)
            if subject == "damaged_by_attached_this_turn":
                # "…dealt damage by **enchanted creature**" (Kumano's
                # Blessing) — the source is this Aura's host.
                source_id = getattr(src, "attached_to", None)
            return source_id is not None and source_id in (
                _context.state.creatures_damaged_by_source_this_turn.get(target_id, ())
            )
        return True  # "any"

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        obj = context.state.find_object(event.get("target_id"))
        if obj is None:
            return event  # already gone — let the normal path no-op
        context.engine.exile(obj)
        if token is not None and effect.source is not None:
            from ...services.token_database import synthesize_token_card  # avoid a services↔effects cycle

            card = synthesize_token_card(
                str(token.get("token_name") or "Token"), power=token.get("power"), toughness=token.get("toughness"),
                colors=list(token.get("colors", [])), subtypes=list(token.get("subtypes", [])),
                keywords=list(token.get("keywords", [])),
            )
            context.create_token(effect.source.controller_id, card, 1)
        return None  # event consumed; the graveyard move is replaced by exile

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _discard_to_battlefield_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a spell or ability an opponent controls causes you to discard this
    card, put it onto the battlefield [with N +1/+1 counters] instead of
    putting it into your graveyard." (MEC-102 — Loxodon Smiter/Obstinate
    Baloth/Nullhide Ferox/Dodecapod) — a self-only RULE 614.1 replacement on
    `EventType.WOULD_DISCARD` (MEC-101's own pre-move pseudo-event, fired by
    `RulesEngine.discard`/`discard_specific`/`discard_random` just before the
    hand→graveyard move).

    Unlike every other entry in this file, this one is never reached through
    `RulesEngine._all_replacement_effects()` (battlefield-only by design,
    RULE 616's ordinary replacement pool) — the card carrying this ability
    is, by definition, still in hand at the moment its own discard would
    happen, so nothing would ever find it there. `draw_discard_mixin.
    _maybe_discard_to_battlefield` checks the discarded object's own
    `GameObject.replacement_effects` directly instead — bound at creation
    time regardless of zone, the same way `triggered_abilities` already is —
    mirroring the self-contained shape `_maybe_madness` already uses for the
    identical "an object's own printed ability intercepts its own discard"
    problem (RULE 702.35a).

    ``counters`` (Dodecapod's own "with two +1/+1 counters") stamps that
    many +1/+1 counters before the object is spliced onto the battlefield —
    present in the same event that puts it there, the convention
    `GameState.add_to_battlefield` already uses for a Saga/Class/Battle/
    planeswalker's own starting counters.
    """
    counters = int(params.get("counters", 0) or 0)
    effect = ReplacementEffect(
        event_type=EventType.WOULD_DISCARD,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("instance_id") != getattr(src, "instance_id", None):
            return False
        cause_controller_id = event.get("cause_controller_id")
        return cause_controller_id is not None and cause_controller_id != src.controller_id

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called — see `_die_to_exile_
        # replacement`'s identical comment just below.
        obj = effect.source
        if obj is None:
            return event
        player = context.state.player_by_id(obj.owner_id)
        # `RulesEngine.discard` has already popped `obj` off `player.hand`
        # by the time it fires `WOULD_DISCARD` (only `obj.zone` itself is
        # still "hand"); `discard_specific`/`discard_random` haven't yet —
        # same dual calling convention `_maybe_madness` already handles.
        if obj in player.hand:
            player.remove_from_zone(obj, Zone.HAND)
        if counters:
            obj.counters["+1/+1"] = obj.counters.get("+1/+1", 0) + counters
        context.state.add_to_battlefield(obj)
        context.state.fire_event(
            GameEvent(
                EventType.ENTERS_BATTLEFIELD,
                from_zone=Zone.HAND.value,
                controller_id=obj.controller_id,
                object=obj.name,
                instance_id=obj.instance_id,
                object_types=sorted(obj.type_words),
            )
        )
        return None  # event consumed — the graveyard move is replaced

    effect.replacement_fn = replace
    effect.condition = _applies
    return effect


def _gain_life_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """A life gain is rewritten instead (RULE 119.3/616.1) — the *additive*
    "you gain that much life plus N instead" (Angel of Vitality, ``plus``)
    or the *multiplicative* "you gain twice that much life instead" (Boon
    Reflection/Alhammarret's Archive/Rhox Faithmender, ``multiplier``,
    default 2). Always scoped to the effect's own controller ("if **you**
    would gain life"), read off the `EventType.LIFE_GAIN` event's
    ``player_id`` against ``effect.source``'s controller — every real card
    with this clause is a permanent whose controller is the gaining player.
    """
    plus = params.get("plus")
    multiplier = int(params.get("multiplier", 2))
    effect = ReplacementEffect(
        event_type=EventType.LIFE_GAIN,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        return src is not None and event.get("player_id") == src.controller_id

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        new_amount = amount + int(plus) if plus is not None else amount * multiplier
        return event.copy_with(amount=new_amount)

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _double_tokens_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """Tokens that would be created under *this effect's controller* are
    doubled instead (RULE 111.5/614/616) — Doubling Season's/Parallel
    Lives' token clause: "if an effect would create one or more tokens
    under your control, it creates twice that many instead". Unlike the
    counter clause above this *is* controller-scoped in the real text.

    ``multiplier`` defaults to 2 (every real "double" card); Ojer Taq,
    Deepest Foundation's "three times that many" is the only real 3,
    mirroring `_double_damage_replacement`'s own ``multiplier`` param.
    """
    multiplier = int(params.get("multiplier", 2) or 2)
    #: "If one or more tokens would be created" with no "under your control"
    #: (Primal Vigor) doubles every player's tokens, not just this source's.
    any_controller = bool(params.get("any_controller", False))
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        if any_controller:
            return True
        src = effect.source
        return src is not None and event.get("controller_id") == src.controller_id

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        amount = int(event.get("amount", 0) or 0)
        if amount <= 0:
            return event
        return event.copy_with(
            amount=amount * multiplier,
            additional_tokens=[{**batch, "amount": batch["amount"] * multiplier}
                               for batch in event.get("additional_tokens", [])],
        )

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _additional_creature_tokens_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """RULE 614/616: add one creature token for each token in this creation.

    Keep the batch in the original event so later doublers apply once to all
    tokens, and an earlier doubler's increased amount is counted correctly.
    """
    effect = ReplacementEffect(EventType.CREATE_TOKENS, lambda event, context: event)

    def applies(event, context):
        return (effect.source is not None
                and event.get("controller_id") == effect.source.controller_id
                and event.get("amount", 0) > 0)

    def replace(event, context):
        batches = list(event.get("additional_tokens", []))
        count = event.get("amount", 0) + sum(batch["amount"] for batch in batches)
        batches.append({"amount": count, "definition": dict(params)})
        return event.copy_with(additional_tokens=batches)

    effect.condition, effect.replacement_fn = applies, replace
    return effect


#: The named-token vocabulary `_create_one_of_each_named_token_replacement`/
#: `_additional_named_token_replacement` build from — same closed
#: Treasure/Clue/Food set `parser.oracle.catalogue.handlers._NAMED_TOKEN_
#: WORDS` trusts (`services/token_database.py`'s curated `TokenDatabase`,
#: so the extra token keeps its own real activated ability).
_NAMED_TOKEN_DISPLAY_NAMES: tuple[str, ...] = ("Clue", "Food", "Treasure")


def _create_one_of_each_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would create a Clue, Food, or Treasure token, instead create
    one of each." (Academy Manufactor) — the original creation goes through
    unmodified (RULE 616 doesn't need to touch ``amount`` here), and the
    *other two* named tokens are created as a side effect alongside it.

    A side-effect `context.create_token` call is itself a new CREATE_TOKENS
    event this same replacement would otherwise see again — the ``_busy``
    re-entrancy guard on the `ReplacementEffect` instance is what stops that
    from looping (a Clue's own creation, made *by* this replacement, must
    not re-trigger it a second time).
    """
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return False
        if effect._busy:  # type: ignore[attr-defined]
            return False
        return event.get("token_name") in _NAMED_TOKEN_DISPLAY_NAMES

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        token_name = event.get("token_name")
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ...services.token_database import default_token_database

            db = default_token_database()
            for name in _NAMED_TOKEN_DISPLAY_NAMES:
                if name == token_name:
                    continue
                card = db.get_token(name)
                if card is not None:
                    context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _substitute_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would create a Fish token, create a 3/3 blue Shark creature token instead." (Fisher's Talent) —
    a creation of the token named ``from_token`` under this effect's controller becomes a creation of ``to``
    (a token definition: ``token_name``/``power``/``toughness``/``colors``/``subtypes``/``keywords``) instead,
    the same amount. ``min_level`` gates it on the source Class's level (RULE 716, ``counters["class_level"]``).
    Replacements chain (RULE 616.1): the event now names the substitute, so a second effect that replaces *that*
    token (Shark → Octopus) applies to it in turn.
    """
    from_token = str(params.get("from_token", ""))
    to = dict(params.get("to") or {})
    min_level = int(params.get("min_level", 0) or 0)
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return False
        if min_level and int((getattr(src, "counters", None) or {}).get("class_level", 1) or 1) < min_level:
            return False
        return bool(to) and event.get("token_name") == from_token

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        return event.copy_with(token_name=to.get("token_name", from_token), token_definition=dict(to))

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _additional_named_token_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If one or more tokens would be created under your control, those
    tokens plus an additional Food token are created instead." (Peregrin
    Took) — ``token_name`` (default "Food") names the extra token; every
    token creation under this effect's controller gets one more of it
    alongside, guarded by the same ``_busy`` re-entrancy flag `_create_
    one_of_each_named_token_replacement` uses (the extra token's own
    creation must not trigger *another* extra token).
    """
    extra_name = str(params.get("token_name", "Food"))
    #: Xorn/Jolene: only a creation of this named token gets the extra one (``None`` = any token).
    only_token = params.get("only_token")
    effect = ReplacementEffect(
        event_type=EventType.CREATE_TOKENS,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )
    effect._busy = False  # type: ignore[attr-defined]

    def _applies(event: GameEvent, _context: GameContext) -> bool:
        src = effect.source
        if src is None or event.get("controller_id") != src.controller_id:
            return False
        if only_token is not None and event.get("token_name") != only_token:
            return False
        return not effect._busy  # type: ignore[attr-defined]

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        src = effect.source
        effect._busy = True  # type: ignore[attr-defined]
        try:
            from ...services.token_database import default_token_database

            card = default_token_database().get_token(extra_name)
            if card is not None:
                context.create_token(src.controller_id, card, 1)
        finally:
            effect._busy = False  # type: ignore[attr-defined]
        return event

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _win_instead_of_empty_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If you would draw a card while your library has no cards in it, you
    win the game instead." (Jace, Wielder of Mysteries/Laboratory Maniac,
    RULE 104.3a-adjacent alternative win condition) — intercepts the DRAW
    event for this effect's own source's controller: if their library is
    already empty, the draw is replaced with an outright win (`RulesEngine.
    player_wins`) and cancelled (returns ``None`` — RULE 614.5, the draw
    itself never happens, so the ordinary "drew from an empty library ⇒
    loses" state-based action never gets a chance to fire either). A draw
    with cards still in the library passes through unchanged.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        controller_id = getattr(src, "controller_id", None)
        if controller_id is None or event.get("player_id") != controller_id:
            return False
        try:
            player = context.state.player_by_id(controller_id)
        except Exception:
            return False
        # "…while your library has no cards in it" — the printed condition
        # itself, not an incidental no-op.
        return not player.library

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        # `_applies` is already checked by `can_replace()` (`effect.condition`
        # below) before `replace()` is ever called in this pass.
        player = context.state.player_by_id(getattr(effect.source, "controller_id"))
        context.engine.player_wins(player)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _split_multi_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If an opponent would draw two or more cards, instead you and that
    player each draw a card." (Alms Collector, MEC-32, RULE 616.1) —
    intercepts `EventType.DRAW_INSTRUCTION` (`RulesEngine.draw`'s own
    aggregate event, fired once per ``draw()`` call before it's split into
    individual per-card `EventType.DRAW` events) rather than the ordinary
    per-card event every other draw replacement in this file reads: the
    "two or more" test is about the whole attempted instruction, which no
    per-card event can see. ``min_count`` (default 2) is the printed
    threshold. The whole original instruction is cancelled (returns
    ``None``) and replaced by exactly one fresh, un-doubled `draw()` call
    for each player — so neither resulting draw's own count ever reaches
    ``min_count`` again, and this doesn't re-trigger itself.
    """
    min_count = int(params.get("min_count", 2))
    effect = ReplacementEffect(
        event_type=EventType.DRAW_INSTRUCTION,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None:
            return False
        opponent_id = event.get("player_id")
        if opponent_id is None or opponent_id == src.controller_id:
            return False
        return event.get("count", 1) >= min_count

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        opponent = context.state.player_by_id(event.get("player_id"))
        controller = context.state.player_by_id(src.controller_id)
        context.draw(opponent, 1)
        context.draw(controller, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _steal_non_first_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If an opponent would draw a card except the first one they draw in
    each of their draw steps, instead that player skips that draw and you
    draw a card." (Notion Thief, MEC-32, RULE 616.1) — the per-card sibling
    of Alms Collector's instruction-level replacement above: reads the
    ordinary per-card `EventType.DRAW` event's own ``first_in_draw_step``
    flag (`RulesEngine._single_draw`, computed live off the new
    `GameState.first_draw_done_this_step` per-player tracker reset each
    time a player's own draw step begins, `game/engine/turn_loop_mixin.py`'s
    `_run_step`) rather than re-deriving position from `cards_drawn_this_
    turn`, since a draw from an unrelated spell elsewhere in the same turn
    must not count as "the step's own first draw."
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None:
            return False
        opponent_id = event.get("player_id")
        if opponent_id is None or opponent_id == src.controller_id:
            return False
        return not event.get("first_in_draw_step")

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        controller = context.state.player_by_id(effect.source.controller_id)
        context.draw(controller, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _discard_instead_of_non_first_draw_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"If a player would draw a card except the first one they draw in
    each of their draw steps, that player discards a card instead. If the
    player discards a card this way, they draw a card. If the player
    doesn't discard a card this way, they mill a card." (Chains of
    Mephistopheles, MEC-32, RULE 616.1) — reads the same ``first_in_draw_
    step`` flag `_steal_non_first_draw_replacement` reads, but applies
    table-wide (no opponent/you scoping at all, unlike Notion Thief) and
    its own compensating draw is a fresh `RulesEngine.draw` call that can
    (and, per the printed card, should) be replaced by this same effect
    again if the affected player's hand still has a card to discard —
    RULE 616.1f's "repeat this process until there are no more applicable
    replacement effects" loop terminates naturally once their hand empties
    (each recursive discard strictly shrinks it), at which point the
    "doesn't discard this way" branch mills instead of drawing. The
    discard itself is the engine's ordinary non-interactive `RulesEngine.
    discard` (auto-chosen, no chooser in MVP) — the same documented
    simplification every other untargeted discard in this engine already
    uses, not something new to this card.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        return not event.get("first_in_draw_step")

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        player = context.state.player_by_id(event.get("player_id"))
        if player.hand:
            context.discard(player, 1, cause=effect.source)
            context.draw(player, 1)
        else:
            context.mill(player, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


def _first_draw_look_two_replacement(params: dict[str, Any]) -> ReplacementEffect:
    """"The first time you would draw a card each turn, instead look at the
    top two cards of your library. Put one of them into your graveyard and
    the other back on top of your library. Then draw a card." (Scion of
    Halaster, PAR-32/MEC-57) — unlike `_steal_non_first_draw_replacement`'s
    ``first_in_draw_step`` (reset every *draw step*), this gates on a new
    per-*turn* `GameState.first_draw_replaced_this_turn` tracker (cleared in
    `begin_turn`, so it resets every game turn regardless of whose turn it
    is — this ability's own controller can draw off an instant-speed effect
    on someone else's turn too), since the printed text says "each turn",
    not "each draw step".

    Which of the two looked-at cards is binned is a genuine choice on the
    printed card; modeled non-interactively (always the *second* card,
    keeping the top card in place) — the same "auto-chosen, no chooser in
    MVP" simplification `_discard_instead_of_non_first_draw_replacement`'s
    own docstring already documents for an untargeted discard. Consumes the
    original `DRAW` event (returns ``None``, same as every other per-card
    draw replacement in this file) and performs the look/bin/draw itself.
    Marks the turn tracker *before* issuing its own compensating draw, so
    that draw — like every other draw the rest of this turn — is correctly
    not replaced again.
    """
    effect = ReplacementEffect(
        event_type=EventType.DRAW,
        replacement_fn=lambda e, c: e,
        description=str(params.get("description", "")),
    )

    def _applies(event: GameEvent, context: GameContext) -> bool:
        src = effect.source
        if src is None:
            return False
        if event.get("player_id") != src.controller_id:
            return False
        return src.controller_id not in context.state.first_draw_replaced_this_turn

    def replace(event: GameEvent, context: GameContext) -> Optional[GameEvent]:
        src = effect.source
        state = context.state
        player = state.player_by_id(src.controller_id)
        state.first_draw_replaced_this_turn.add(player.id)
        library = player.library  # bottom-first; library[-1] is the top card
        if len(library) >= 2:
            binned = library.pop(-2)
            binned.zone = Zone.GRAVEYARD
            player.graveyard.append(binned)
            context.engine._flag_commander_zone_choice(binned)  # RULE 903.9a
        context.draw(player, 1)
        return None

    effect.replacement_fn = replace
    effect.condition = _applies  # RULE 616.1e — see _prevent_damage_replacement
    return effect


class ReplacementRegistry:
    """Maps a whitelisted replacement-type name to a `ReplacementEffect` factory.

    The replacement analogue of `EffectRegistry` (docs/09 security boundary):
    the binder turns a ``replacement`` `AbilitySpec` into behaviour only through
    a name registered here, so nothing derived from card text becomes an
    arbitrary callable."""

    _factories: dict[str, Callable[[dict[str, Any]], ReplacementEffect]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[[dict[str, Any]], ReplacementEffect]) -> None:
        cls._factories[name] = factory

    @classmethod
    def create(cls, name: str, params: Optional[dict[str, Any]] = None) -> ReplacementEffect:
        if name not in cls._factories:
            raise ValueError(f"unknown replacement type: {name!r}")
        return cls._factories[name](params or {})

    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._factories


ReplacementRegistry.register("prevent_damage", _prevent_damage_replacement)
ReplacementRegistry.register("prevent_damage_convert_counters", _prevent_damage_convert_counters_replacement)
ReplacementRegistry.register("double_damage", _double_damage_replacement)
ReplacementRegistry.register("additional_damage", _additional_damage_replacement)
ReplacementRegistry.register("damage_floor_from_source_power", _damage_floor_from_source_power_replacement)
ReplacementRegistry.register("double_counters", _double_counters_replacement)
ReplacementRegistry.register("roll_dice_modifier", _roll_dice_modifier_replacement)
ReplacementRegistry.register("heal_others_on_damage", _heal_others_on_damage_replacement)
ReplacementRegistry.register("gain_life_replacement", _gain_life_replacement)
ReplacementRegistry.register("die_to_exile", _die_to_exile_replacement)
ReplacementRegistry.register("draw_exile_face_up", _draw_exile_face_up_replacement)
ReplacementRegistry.register("double_tokens", _double_tokens_replacement)
ReplacementRegistry.register("additional_creature_tokens", _additional_creature_tokens_replacement)
ReplacementRegistry.register("create_one_of_each_named_token", _create_one_of_each_named_token_replacement)
ReplacementRegistry.register("additional_named_token", _additional_named_token_replacement)
ReplacementRegistry.register("substitute_token", _substitute_token_replacement)
ReplacementRegistry.register("win_instead_of_empty_draw", _win_instead_of_empty_draw_replacement)
ReplacementRegistry.register("split_multi_draw", _split_multi_draw_replacement)
ReplacementRegistry.register("steal_non_first_draw", _steal_non_first_draw_replacement)
ReplacementRegistry.register("discard_instead_of_non_first_draw", _discard_instead_of_non_first_draw_replacement)
ReplacementRegistry.register("first_draw_look_two", _first_draw_look_two_replacement)
ReplacementRegistry.register("discard_to_battlefield", _discard_to_battlefield_replacement)

register(globals())
