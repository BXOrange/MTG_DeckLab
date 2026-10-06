"""Live, whitelisted conditions gating a conditional cast/activation timing
permission — RULE 702.8b's "you may cast this spell as though it had flash
if <condition>" and RULE 606.3's "you may activate this permanent's loyalty
abilities any time you could cast an instant if <condition>" (The Wandering
Emperor-shaped). Bound onto ``obj.conditional_flash`` by
`game/binding/core.py`'s `attach_to_object` from `AbilitySpec.
conditional_flash` (`parser/oracle/spec.py`'s ``ALLOWED_CAST_CONDITION_KEYS``
whitelist — a deliberately separate one from `EffectSpec.condition`'s, which
gates whether an already-resolving *effect* applies rather than a cast/
activation *legality* check).

Checked live off the object each time (never cached), unlike
`obj.granted_keywords` (layer-6, battlefield-only) — this has to work for a
hand-zone spell too, and a turn-scoped condition changes every turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..models.game.game_object import GameObject
    from ..models.game.game_state import GameState


def conditional_flash_holds(
    condition: dict[str, Any],
    obj: "GameObject",
    state: "GameState",
    targets: Optional[list[Any]] = None,
) -> bool:
    """Whether ``obj``'s `conditional_flash` condition holds right now.

    Fails closed on an unrecognized key (defensive — `AbilitySpec.validate`
    already rejects one at bind time).

    ``"targets_a_commander"`` (Timely Ward-shaped, MEC-7) is the one key
    that depends on a choice — RULE 601.2c targets aren't picked until
    *after* the timing-permission check `GameEngine.can_cast` makes this
    call for, so ``targets`` is optional: ``None`` (the offer-time call,
    before the player has chosen anything) answers optimistically — legal to
    *offer* the flash-speed cast whenever a commander is anywhere in play or
    a command zone, since a legal target isn't known yet — while the real
    cast (`_cast_current_face`, which already has the chosen ``targets`` in
    hand) checks the actual choice and enforces it for real. A caster who
    announces flash-speed and then doesn't actually pick a commander target
    has this same call reject the cast at that final checkpoint, matching
    RULE 601.2i's "the game returns to the moment before the illegal cast".
    """
    for key, value in condition.items():
        if key == "unconditional":
            # MEC-44, Necromancy: "You may cast this spell as though it
            # had flash." with no gate at all — the trivially-true member
            # of this whitelist, so a plain flash grant can still reach
            # `can_cast`'s `conditional_flash` check the same way every
            # gated one does.
            if not bool(value):
                return False
        elif key == "entered_this_turn":
            if bool(value) != (obj.turn_entered == state.internal_turn.number):
                return False
        elif key == "controller_beholds_subtype":
            # PAR-30, Molten Exhale: "…flash if you behold a Dragon…" — the
            # caster *could* behold one iff they control a permanent of that
            # subtype or hold a card of it in hand (`RulesEngine.behold`'s
            # own scan order). Documented simplification: the reveal/
            # additional-cost payment isn't separately modeled.
            from . import continuous  # local: avoid the continuous import cycle

            want = str(value).lower()
            try:
                player = state.player_by_id(obj.controller_id)
            except (KeyError, ValueError, AttributeError):
                player = None
            if player is None:
                return False
            on_bf = any(
                o.controller_id == player.id and continuous.has_subtype(o, want)
                for o in state.battlefield
            )
            in_hand = any(continuous.has_subtype(c, want) for c in player.hand)
            if not (on_bf or in_hand):
                return False
        elif key == "targets_a_commander":
            if targets is None:
                has_commander = any(getattr(p, "is_commander", False) for p in state.battlefield) or any(
                    getattr(c, "is_commander", False) for player in state.players for c in player.command
                )
            else:
                has_commander = any(getattr(t, "is_commander", False) for t in targets)
            if bool(value) != has_commander:
                return False
        else:
            return False
    return True


def free_cast_condition_holds(condition: dict[str, Any], obj: "GameObject", state: "GameState") -> bool:
    """Whether ``obj``'s `free_cast_condition` (RULE 601.2f-adjacent
    condition-gated free-cast alternative cost) holds right now — checked
    live off the board, mirroring `conditional_flash_holds`. Also the
    evaluator for `AbilitySpec.alt_cost`'s own ``condition`` key (RULE
    118.9, MEC-15 — Force of Negation/Force of Vigor's "if it's not your
    turn"): both are "is this alternative cost/cast option available right
    now" checks, so they share one whitelist/evaluator rather than two.

    ``"control_commander"``: whether ``obj``'s controller currently controls
    any commander (RULE 903.4 — a `GameObject.is_commander` permanent/card
    in their command zone or on the battlefield). ``"not_your_turn"``/
    ``"your_turn"``: whether it currently is/isn't ``obj``'s controller's
    own turn (RULE 500.7-adjacent) — a card-in-hand-safe read, unlike
    `static_conditions.py`'s identically-named battlefield-only kind.
    ``"opponent_controls_forest_and_you_control_island"``: Submerge's own
    named board-state gate (RULE 205.3i basic land types). Fails closed on
    an unrecognized key.
    """
    controller_id = getattr(obj, "controller_id", None)
    for key, value in condition.items():
        if key == "control_commander":
            player = None
            for p in getattr(state, "players", []):
                if p.id == controller_id:
                    player = p
                    break
            has_commander = False
            if player is not None:
                has_commander = any(getattr(c, "is_commander", False) for c in player.command)
            if not has_commander:
                has_commander = any(
                    getattr(o, "is_commander", False) and o.controller_id == controller_id
                    for o in state.battlefield
                )
            if bool(value) != has_commander:
                return False
        elif key in ("not_your_turn", "your_turn"):
            active = getattr(state, "active_player", None)
            is_yours = active is not None and controller_id is not None and active.id == controller_id
            wants_yours = key == "your_turn"
            if bool(value) != (is_yours == wants_yours):
                return False
        elif key == "opponent_controls_forest_and_you_control_island":
            # Submerge's own gate: true only while *some* opponent controls
            # a Forest and ``obj``'s controller controls an Island — a plain
            # printed-type-line check (RULE 205.3i's basic land types),
            # matching `control_commander`'s "check it live off the board"
            # shape rather than a cached/derived flag.
            battlefield = getattr(state, "battlefield", [])
            you_have_island = any(
                o.controller_id == controller_id and o.is_land
                and "island" in (o.card.type_line or "").lower()
                for o in battlefield
            )
            opp_has_forest = any(
                o.controller_id is not None and o.controller_id != controller_id and o.is_land
                and "forest" in (o.card.type_line or "").lower()
                for o in battlefield
            )
            if bool(value) != (you_have_island and opp_has_forest):
                return False
        elif key == "control_legendary_creature_or_planeswalker":
            # RULE 205.4d: "You may cast a legendary sorcery only if you control a legendary creature
            # or planeswalker." (Urza's Ruinous Blast) — read live off the battlefield, like the
            # sibling `control_commander` gate above.
            has_legend = any(
                o.controller_id == controller_id and getattr(o, "is_legendary", False)
                and (o.is_creature or o.is_planeswalker)
                for o in state.battlefield
            )
            if bool(value) != has_legend:
                return False
        elif key == "own_turn_after":
            # "You can't cast this spell during your first, second, or third turns of the game." (Serra Avenger) —
            # forbidden only while it is the caster's own turn and they have begun at most ``value`` of them.
            active = getattr(state, "active_player", None)
            if active is not None and active.id == controller_id and active.turns_taken <= int(value):
                return False
        elif key == "opponent_lost_life_this_turn":
            # "You can't cast Rakdos unless an opponent lost life this turn." — RULE 119.3, derived from this turn's events.
            lost = getattr(state, "life_lost_this_turn", None) or {}
            if bool(value) != any(
                int(lost.get(p.id, 0) or 0) > 0 for p in getattr(state, "players", []) if p.id != controller_id
            ):
                return False
        elif key == "control_land_type":
            # "If you control a Swamp, you may pay 4 life rather than pay
            # this spell's mana cost." (RULE 118.9, Snuff Out) — the
            # single-player generalization of `opponent_controls_forest_
            # and_you_control_island`'s own "you control a `<land type>`"
            # half, for a plain basic-land-type gate on its own.
            battlefield = getattr(state, "battlefield", [])
            land_type = str(value).lower()
            you_have_type = any(
                o.controller_id == controller_id and o.is_land
                and land_type in (o.card.type_line or "").lower()
                for o in battlefield
            )
            if not you_have_type:
                return False
        elif key == "opponent_spells_cast_this_turn_at_least":
            # Mindbreak Trap-shaped (RULE 601.2f-adjacent, MEC-12): true
            # once *any* opponent has cast at least this many spells this
            # turn — `GameState.spells_cast_this_turn`, the same per-player
            # counter `TaxedDrawEffect`'s Rhystic Study-shaped trigger reads.
            threshold = int(value)
            counts = getattr(state, "spells_cast_this_turn", {}) or {}
            if not any(
                pid != controller_id and count >= threshold for pid, count in counts.items()
            ):
                return False
        elif key == "creatures_attacking_at_least":
            # PAR-19: "If 3 or more creatures are attacking, ..." (Lethargy
            # Trap/Arrow Volley Trap-shaped) — true once *any* number of
            # creatures currently attacking meets the threshold, regardless
            # of controller (RULE 508's attack is already locked in by the
            # time this alt-cost option is checked, so a live `.attacking`
            # scan is exactly RULE 506.4's "declared attackers").
            threshold = int(value)
            battlefield = getattr(state, "battlefield", [])
            attacking = sum(1 for o in battlefield if getattr(o, "attacking", False))
            if attacking < threshold:
                return False
        elif key == "you_attacked_this_turn":
            # Raid (RULE 508.1a): this cannot be inferred from a live
            # `.attacking` scan because the alternative cost can be cast
            # after combat. It is set only for a declaration, not when RULE
            # 508.4 puts a creature onto the battlefield attacking.
            attacked = getattr(state, "players_attacked_this_turn", None) or set()
            if bool(value) != (controller_id in attacked):
                return False
        elif key == "another_spell_cast_this_turn":
            if not isinstance(value, dict) or set(value) not in ({"color"}, {"spell_type"}):
                return False
            if "color" in value:
                counts = getattr(state, "spell_color_cast_counts_this_turn", {}) or {}
                count = (counts.get(controller_id, {}) or {}).get(str(value["color"]).upper(), 0)
            else:
                counts = getattr(state, "spell_type_cast_counts_this_turn", {}) or {}
                count = (counts.get(controller_id, {}) or {}).get(str(value["spell_type"]).lower(), 0)
            if int(count) < 1:
                return False
        else:
            return False
    return True
