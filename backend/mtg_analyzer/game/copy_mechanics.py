"""RULE 706/707 "becomes a copy of" — the shared mutate/snapshot/restore
primitives used by all three copy mechanisms this engine models:

* the one-shot eager `become_copy` (Clever Impersonator-style ETB copies,
  now wired through true RULE 614.1c/614.12 replacement timing — see
  `RulesEngine._offer_enter_as_copy`),
* the continuous, condition-gated layer-1 copy (Vesuvan Shapeshifter-style
  "as long as untapped" — see `continuous._apply_copy_layer`), and
* the temporary "… until end of turn" copy (Cursed Mirror-style — see
  `RulesEngine.become_copy_until_end_of_turn`).

Free functions rather than `RulesEngine` methods so `game/continuous.py` can
call them without importing `rules_engine` (which already imports
`continuous` at module scope — the reverse import would be circular).
`RulesEngine.become_copy`/`snapshot_face`/`restore_face` are thin delegating
wrappers kept for backward compatibility with existing callers.

RULE 707.2 "copy of a copy": `become_copy` keeps `GameObject._front_card` in
sync with whatever ``obj`` currently is (see its docstring) rather than
leaving it pinned to the object's pristine printed card — the one field
`copy_permanent`/`copy_spell` (`game/rules/copies_mixin.py`) and `become_copy`
itself already read to find a target's *copiable* values (RULE 712.4a's
front-face simplification piggybacks on the same field). All three copy
mechanisms above share this fix automatically: whichever one a target went
through, a *later* copy of that target — by any of the three — sees its
current form rather than reverting to the printed card underneath.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models.card import Card
from ..models.game_object import GameObject

#: The catalogue-derived fields a copy (or a face switch) replaces wholesale
#: — RULE 706.2's "loses its own, gains the copied object's" — captured by
#: `snapshot_face` and restored by `restore_face`.
_FACE_ATTRS: tuple[str, ...] = (
    "spell_effects",
    "triggered_abilities",
    "activated_abilities",
    "static_effects",
    "replacement_effects",
    "enter_as_copy_effects",
    "intrinsic_keywords",
    "parametric_keywords",
)


def snapshot_face(obj: GameObject) -> dict[str, Any]:
    """Capture ``obj``'s current `Card` + catalogue-derived bindings.

    Pairs with `restore_face` to undo a copy/face-switch — used when
    previewing or attempting a modal DFC's un-chosen face (RULE 712.10), and
    to revert a conditional or temporary copy effect once it stops applying.
    Includes ``_front_card`` (see `become_copy`'s matching update) so a
    reverted copy's "current copiable card" bookkeeping is undone along with
    everything else — not just the pre-copy `Card` itself."""
    snapshot: dict[str, Any] = {"card": obj.card, "_front_card": obj._front_card}
    for attr in _FACE_ATTRS:
        value = getattr(obj, attr, None)
        if isinstance(value, set):
            snapshot[attr] = set(value)
        elif isinstance(value, dict):
            snapshot[attr] = dict(value)
        else:
            snapshot[attr] = list(value or [])
    return snapshot


def restore_face(obj: GameObject, snapshot: dict[str, Any]) -> None:
    """Undo a copy/face-switch, restoring exactly what `snapshot_face` saved."""
    for attr, value in snapshot.items():
        setattr(obj, attr, value)


def become_copy(
    obj: GameObject,
    target: GameObject,
    add_types: Optional[list[str]] = None,
    add_subtypes: Optional[list[str]] = None,
    only_types: Optional[list[str]] = None,
    add_keywords: Optional[list[str]] = None,
) -> None:
    """``obj`` itself becomes a copy of ``target`` (RULE 706/707.2).

    Mutates ``obj`` in place: its `Card` is replaced by ``target``'s copiable
    values (RULE 706.2 — name, mana cost, colours, card type/subtypes, rules
    text, P/T, loyalty), and its own catalogue-derived abilities/keywords are
    cleared and rebound from that new card, since a copy gains the copied
    object's abilities rather than keeping its own (RULE 706.2). Everything
    RULE 706.2 *doesn't* cover — instance id, zone, owner, controller,
    counters, tapped state, attachments, summoning sickness — is untouched,
    since none of that lives on `Card`.

    Mirrors `RulesEngine.copy_permanent`'s simplification of always reading
    the *front* face (RULE 712.4a's "currently shown face" nuance isn't
    modeled for either). ``add_types``/``add_subtypes``/``only_types``/
    ``add_keywords`` all pass straight through to `Card.as_copy` — see its
    own docstring for each "except …" clause shape.

    RULE 707.2 "copy of a copy": ``target``'s copiable values are read off
    ``target._front_card`` rather than ``target.card`` directly — normally
    the same thing, but if ``target`` has itself already become a copy (via
    this same function), ``target._front_card`` is what's kept in sync with
    that (see below), so a copy of an already-copied permanent picks up its
    *current* copiable values, not the pristine printed card underneath.
    ``obj._front_card`` is updated the same way once ``obj`` becomes a copy,
    so a *further* copy of ``obj`` sees this copy rather than ``obj``'s own
    original printed card — the chain composes."""
    from .binding.core import bind_from_catalogue  # function-scoped: avoid a cycle

    copiable = getattr(target, "_front_card", target.card)
    obj.card = copiable.as_copy(
        add_types=add_types, add_subtypes=add_subtypes,
        only_types=only_types, add_keywords=add_keywords,
    )
    obj._front_card = obj.card

    # A copy replaces the object's own copiable-derived abilities/keywords
    # wholesale — static/triggered/activated/replacement effects granted
    # by *other* permanents (auras, anthems) live on those objects, not
    # here, so clearing these is exactly RULE 706.2's "loses its own,
    # gains the copied object's" without touching anything external.
    obj.static_effects = []
    obj.triggered_abilities = []
    obj.activated_abilities = []
    obj.replacement_effects = []
    obj.enter_as_copy_effects = []
    obj.spell_effects = []
    obj.intrinsic_keywords = set()
    obj.parametric_keywords = {}
    bind_from_catalogue(obj)

    if obj.card.is_planeswalker and obj.card.loyalty and "loyalty" not in obj.counters:
        obj.counters["loyalty"] = obj.card.loyalty
