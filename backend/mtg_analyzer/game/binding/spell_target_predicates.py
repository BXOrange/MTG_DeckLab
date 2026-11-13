"""The cast-trigger "that targets ..." clause as an intervening-if over the `SPELL_CAST` event (PAR-236).

``whenever you cast a spell that targets an opponent or a creature an opponent controls`` (Danitha, Spear of Agony),
``... that targets only a single creature you control`` (Leyline of Resonance) and ``... that targets ~`` read the
spell's chosen targets off the event (`casting_mixin._target_instance_ids` / `_target_player_ids`):

* RULE 601.2c / 115.1: the targets are chosen as the spell is cast, so they are fixed when the trigger checks.
* RULE 603.2: a cast event triggers an ability once, however many of the spell's targets satisfy it (Danitha's ruling).
* "Only": every target is the same single object or player (Leyline of Resonance's ruling: "all the same creature"),
  so the *distinct* targets are counted, not the target slots.

``alternatives`` is the "A or B" of the printed clause: ``{"kind": "player", "relation": "you"|"opponent"}``,
``{"kind": "source"}`` (the ability's own object) or ``{"kind": "object", "filter": {...}, "controller": ...}`` whose
``controller`` is ``"you"``, ``"opponent"`` or ``"not_you"`` relative to the ability's controller.
"""
from __future__ import annotations

from typing import Any, Callable

from ...parser.oracle.catalogue.spell_phrase import SPELL_TARGET_CLAUSE_KEY  # noqa: F401  (re-exported for core.py)


def _object_alternative_hit(alt: dict[str, Any], target: Any, you: Any, state: Any) -> bool:
    from ..combat import matches_object_filter  # function-scoped: combat imports the models

    controller = getattr(target, "controller_id", None)
    wanted = alt.get("controller")
    if wanted == "you" and controller != you:
        return False
    if wanted == "opponent" and (controller is None or controller == you):
        return False
    if wanted == "not_you" and controller == you:
        return False
    return matches_object_filter(target, alt.get("filter") or {}, state=state)


def spell_target_clause_predicate(clause: dict[str, Any], source: Any) -> Callable[[Any, Any], bool]:
    alternatives = list(clause.get("alternatives") or [])
    only = bool(clause.get("only"))

    def _hits(event: Any, context: Any, src=source) -> bool:
        state = getattr(context, "state", None)
        if state is None:
            return False
        you = getattr(src, "controller_id", None)
        object_ids = list(event.get("target_instance_ids") or ())
        player_ids = list(event.get("target_player_ids") or ())
        if only and len(object_ids) + len(player_ids) != 1:
            return False

        def _matches(kind_hit: Callable[[dict[str, Any]], bool]) -> bool:
            return any(kind_hit(alt) for alt in alternatives)

        for player_id in player_ids:
            if _matches(lambda alt, pid=player_id: alt["kind"] == "player" and (
                (pid == you) if alt["relation"] == "you" else (pid != you)
            )):
                return True
        for object_id in object_ids:
            target = state.find_object(object_id)
            if target is None:
                continue
            if _matches(lambda alt, t=target, oid=object_id: (
                oid == getattr(src, "instance_id", None) if alt["kind"] == "source"
                else alt["kind"] == "object" and _object_alternative_hit(alt, t, you, state)
            )):
                return True
        return False

    return _hits
