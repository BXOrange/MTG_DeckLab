"""RULE 707 "becomes a copy of" — the shared mutate/snapshot/restore
primitives used by all three copy mechanisms this engine models:

* the one-shot eager `become_copy` (Clever Impersonator-style ETB copies,
  now wired through true RULE 614.1c/614.12 replacement timing — see
  `RulesEngine._offer_enter_as_copy`),
* the continuous, condition-gated layer-1 copy (Vesuvan Shapeshifter-style
  "as long as untapped" — see `continuous._apply_copy_layer`), and
* temporary copies ending at cleanup or the next end step. Ordered layers
  preserve later copies when an earlier duration expires.

Free functions rather than `RulesEngine` methods so `game/continuous.py` can
call them without importing `rules_engine` (which already imports
`continuous` at module scope — the reverse import would be circular).
`RulesEngine.become_copy`/`snapshot_face`/`restore_face` are thin delegating
wrappers kept for backward compatibility with existing callers.

RULE 707.2 "copy of a copy": `become_copy` keeps `GameObject._front_card` in
sync with whatever ``obj`` currently is (see its docstring) rather than
leaving it pinned to the object's pristine printed card — the one field
`copy_permanent`/`copy_spell` (`game/rules/copies_mixin.py`) and `become_copy`
itself already read to find a target's *copiable* values (RULE 713.1a's
front-face simplification piggybacks on the same field). All three copy
mechanisms above share this fix automatically: whichever one a target went
through, a *later* copy of that target — by any of the three — sees its
current form rather than reverting to the printed card underneath.
"""

from __future__ import annotations

from typing import Any, Optional

from ..models.cards.card import VALID_COLORS, Card
from ..models.cards.card_colors import COLOR_OVERRIDE_ATTR, with_color_override
from ..models.game.game_object import GameObject

#: The catalogue-derived fields a copy (or a face switch) replaces wholesale
#: — RULE 707.2's "loses its own, gains the copied object's" — captured by
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


def resolving_ability(item: Any) -> Any:
    """The triggered/activated ability a stack ``item`` is resolving (RULE 113.1), or ``None``. A reflexive "when you
    do" trigger (RULE 603.12) names the ability that created it as its ``parent_ability``: "this ability" in its text
    is still the card's printed ability, not the one-off reflexive object."""
    for effect in getattr(item, "effects", None) or []:
        if hasattr(effect, "description") and hasattr(effect, "source"):
            return getattr(effect, "parent_ability", None) or effect
    return None


def this_ability_only(obj: GameObject, ability: Any, ability_key: Optional[str] = None) -> list[list]:
    """RULE 707.9a: "…except it has this ability" keeps the one ability that is resolving, not every ability ``obj``
    has now — an earlier copy's would otherwise leak into the next one. Returns the (triggered, static, activated,
    replacement) lists to keep after the copy. ``ability`` is matched by identity first; a stale object (the copy
    already rebuilt its abilities while a second trigger of the same printing waited on the stack) is matched by the
    printed line it was built from (``printed_line``), then by ``ability_key``. A parsed card's abilities all share the
    card's whole text as their description, so a description alone cannot tell them apart. With none of them known
    (a direct apply outside a stack item) everything is kept."""
    lists = [list(obj.triggered_abilities), list(obj.static_effects),
             list(obj.activated_abilities), list(obj.replacement_effects)]
    if ability is not None and any(a is ability for group in lists for a in group):
        return [[a for a in group if a is ability] for group in lists]
    line = getattr(ability, "printed_line", "")
    if line and any(a.printed_line == line for group in lists for a in group):
        return [[a for a in group if a.printed_line == line] for group in lists]
    if ability_key is None:
        return lists
    return [[a for a in group if getattr(a, "description", None) == ability_key] for group in lists]


def keep_as_copiable(obj: GameObject, own: list[list]) -> tuple[list[str], list[list]]:
    """RULE 707.9a: "it has this ability" makes the ability part of the copy's *copiable values* (a Clone copying the
    copy gets it too). Splits the abilities `this_ability_only` chose into the oracle lines to store on the new
    `Card` (``add_ability_lines``, re-bound with the copy's own source) and whatever cannot be re-bound from a
    line (hand-authored or keyword-derived: no ``printed_line``, or a line that does not parse on its own), which the
    caller still re-adds as bound objects through `restore_own_abilities`."""
    from .card_registry.core import granted_line_specs  # function-scoped: the registry imports the binder

    lines: list[str] = []
    leftover: list[list] = [[], [], [], []]
    for index, group in enumerate(own):
        for ability in group:
            line = getattr(ability, "printed_line", "")
            if line and granted_line_specs(obj.card, line):
                if line not in lines:
                    lines.append(line)
            else:
                leftover[index].append(ability)
    return lines, leftover


def restore_own_abilities(obj: GameObject, own: list[list]) -> None:
    """Re-add the abilities `this_ability_only` set aside, after the copy replaced the object's own."""
    obj.triggered_abilities.extend(own[0])
    obj.static_effects.extend(own[1])
    obj.activated_abilities.extend(own[2])
    obj.replacement_effects.extend(own[3])


def become_copy(
    obj: GameObject,
    target: GameObject,
    add_types: Optional[list[str]] = None,
    add_subtypes: Optional[list[str]] = None,
    only_types: Optional[list[str]] = None,
    add_keywords: Optional[list[str]] = None,
    not_legendary: bool = False,
    set_colors: Optional[list[str]] = None,
    duration: Optional[str] = None,
    add_ability_lines: Optional[list[str]] = None,
) -> None:
    """``obj`` itself becomes a copy of ``target`` (RULE 707.2).

    Mutates ``obj`` in place: its `Card` is replaced by ``target``'s copiable
    values (RULE 707.2 — name, mana cost, colours, card type/subtypes, rules
    text, P/T, loyalty), and its own catalogue-derived abilities/keywords are
    cleared and rebound from that new card, since a copy gains the copied
    object's abilities rather than keeping its own (RULE 707.2). Everything
    RULE 707.2 *doesn't* cover — instance id, zone, owner, controller,
    counters, tapped state, attachments, summoning sickness — is untouched,
    since none of that lives on `Card`.

    Mirrors `RulesEngine.copy_permanent`'s simplification of always reading
    the *front* face (RULE 713.1a's "currently shown face" nuance isn't
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

    if duration is not None or obj._duration_copy_layers:
        obj._duration_copy_layers.append({'duration': duration, 'base': snapshot_face(obj)})

    # RULE 400.7: a copied permanent returns with its own printed abilities.
    # Preserve this first face across repeated copies; snapshots do not change
    # the physical printing identity used for player-observed printed facts.
    if obj._copy_zone_base is None:
        obj._copy_zone_base = snapshot_face(obj)
    copiable = getattr(target, "_front_card", target.card)
    obj.card = copiable.as_copy(
        add_types=add_types, add_subtypes=add_subtypes,
        only_types=only_types, add_keywords=add_keywords, not_legendary=not_legendary,
        set_colors=set_colors, add_ability_lines=add_ability_lines,
    )
    # RULE 707.9b: "except it's <colour>" overrides the copied mana-cost colours; a plain copy of an
    # already colour-overridden object keeps that override (as_copy rebuilds the Card without it).
    inherited = getattr(copiable, COLOR_OVERRIDE_ATTR, None)
    if set_colors is not None:
        with_color_override(obj.card, [c for c in set_colors if c in VALID_COLORS])
    elif inherited is not None:
        with_color_override(obj.card, inherited)
    obj._front_card = obj.card

    # A copy replaces the object's own copiable-derived abilities/keywords
    # wholesale — static/triggered/activated/replacement effects granted
    # by *other* permanents (auras, anthems) live on those objects, not
    # here, so clearing these is exactly RULE 707.2's "loses its own,
    # gains the copied object's" without touching anything external.
    obj.static_effects = []
    obj.triggered_abilities = []
    obj.activated_abilities = []
    obj.replacement_effects = []
    obj.enter_as_copy_effects = []
    obj.spell_effects = []
    obj.intrinsic_keywords = set()
    obj.intrinsic_keyword_instances = {}
    obj.parametric_keywords = {}
    bind_from_catalogue(obj)

    # RULE 306.5b / 707.2: copying characteristics adds no counters.
    # As-entry copies receive starting loyalty through the entry pipeline.


def expire_copies(state, window: str) -> bool:
    """End timed copy layers without removing a later permanent or timed copy."""
    duration = {'cleanup': 'end_of_turn', 'end_step': 'next_end_step'}.get(window)
    changed = False
    for obj in state.battlefield:
        layers = obj._duration_copy_layers
        index = 0
        while index < len(layers):
            layer = layers[index]
            from types import SimpleNamespace
            from .durations import is_expired
            expired = (is_expired(SimpleNamespace(duration=layer['duration'],
                duration_data=layer['duration_data'], source=state.find_object(layer.get('source_id')),
                object_ids=layer.get('object_ids', [])), state, window) if 'duration_data' in layer
                else duration is not None and layer['duration'] == duration)
            if not expired:
                index += 1
                continue
            # RULE 613.7: newer copy effects still win. If the removed
            # layer is underneath one, update what that newer layer reveals
            # when it ends, rather than changing the current face.
            if index + 1 < len(layers):
                layers[index + 1]['base'] = layer['base']
            else:
                restore_face(obj, layer['base'])
            layers.pop(index)
            changed = True
        if layers and all(layer['duration'] is None for layer in layers):
            layers.clear()
    return changed
