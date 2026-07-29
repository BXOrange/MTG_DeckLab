"""RULE 613.6 conditional static abilities — one whitelisted vocabulary for
"as long as `<condition>`, …", shared by every static that has a condition.

Why this module exists
----------------------
Conditional statics arrived one card at a time, and each one added its own
parameter to `continuous.group_selector_objects`: ``active_player_only``
("during your turn"), ``min_level``/``max_level`` (a Class/Leveler's own
counters), ``min_count_selector``/``min_count`` (Metalcraft). Each is a
separate ``if`` returning ``[]`` when inactive, and each needed its own key
in `effects._SELECTOR_KEYS`, which is exactly the trap that silently drops a
new selector param. "As long as" is not a rare shape — it leads ~250 clauses
in the card cache, across at least five families (the source's own state, an
attached permanent's characteristics, a board count, the turn, a player's
life/hand) — so the next dozen would have been the next dozen parameters.

This is the single evaluation path instead. A condition is a small clamped
dict ``{"kind": <whitelisted name>, …}`` carried in a static's ``active_if``
param and evaluated **live, every recompute**, against the ability's own
source and controller. It never caches: that is what makes "as long as ~ is
untapped" turn itself off the moment the permanent taps, with no event, no
trigger and no bookkeeping.

``active_if``, not ``condition``, because a ``combat_restriction`` static
already carries a ``condition`` of its own in the same params dict ("~ can't
attack **unless** defending player controls an Island") drawn from the
separate combat-time vocabulary below — one key holding two vocabularies
would make each fail closed on the other's dicts.

The legacy parameters above still work and are still spelled the same way in
every shipped `AbilitySpec` — `condition_from_legacy_params` translates them
into this vocabulary so there is one implementation, not two.

Fail-closed, like every other card-text-derived vocabulary in this package:
an unrecognized ``kind`` (or a malformed param) makes the condition *false*,
so an unmodeled static simply doesn't apply. It never raises, because it runs
inside the layer engine on every recompute.

Not to be confused with:

* `game/condition_query.py` — a *cast/activation legality* gate (RULE 702.8b
  flash, 606.3 loyalty timing), which must work for a card in hand and so
  can't be a battlefield-static concept;
* `parser/oracle/spec.py`'s ``_ALLOWED_CONDITION_KEYS`` — whether an
  already-resolving *one-shot* effect applies (RULE 702.33b "if kicked");
* `GameEngine._combat_condition_met` — "~ can't attack **unless** `<board
  condition>`", evaluated at combat time against a *defending player*, which
  no recompute-time condition can see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:  # models must not be imported at runtime (module boundary)
    from ..models.game_object import GameObject
    from ..models.game_state import GameState


#: Every recognized ``kind``. A condition naming anything else is false.
STATIC_CONDITION_KINDS: frozenset[str] = frozenset(
    {
        # -- The *subject*'s own state (the largest family by card count).
        # Historically these read the ability's own source and are still
        # spelled ``source_*`` in every shipped spec; which object they
        # actually read is now chosen by the condition's ``of`` key (see
        # `CONDITION_SUBJECTS`), defaulting to the source.
        "source_tapped",  # "as long as ~ is tapped"
        "source_untapped",  # "as long as ~ is untapped"
        "source_monstrous",  # RULE 701.37b
        "source_attacking",  # "as long as ~ is attacking"
        "source_blocking",
        "source_paired",  # RULE 702.94b soulbond
        "source_attached",  # "as long as ~ is attached to a creature"
        "source_equipped",  # "as long as ~ is equipped"
        "source_enchanted",  # "as long as ~ is enchanted"
        "source_counters",  # + ``counter``/``min``/``max``
        # "for as long as you control ~" / "…as long as ~ remains on the
        # battlefield" — the lock-down family's own duration (PAR-11): the
        # effect lasts while its *source* is still around, which is not
        # automatic, since a RULE 611 continuous effect otherwise outlives its
        # source (611.2b).
        "source_on_battlefield",
        # -- The subject's *characteristics* (RULE 109.3), as opposed to its
        # state above. Printed almost exclusively about an attached permanent
        # ("as long as enchanted permanent is a creature"/"…is red"/"…is a
        # Vehicle"), i.e. with ``of="attached"`` — but the kinds themselves
        # are subject-agnostic like every other row here.
        "is_card_type",  # + ``card_type``
        "is_color",  # + ``color`` (a WUBRG letter)
        "is_subtype",  # + ``subtype``
        # -- Whose turn it is (RULE 613.6's commonest non-board gate).
        "your_turn",
        "not_your_turn",
        # -- The board.
        "control_count",  # + ``selector``/``min``/``max`` — Metalcraft-shaped
        "control_named",  # + ``name`` — "as long as you control a <card>"
        # "as long as an opponent has N or more cards in their graveyard" —
        # `control_count`'s opponent-scoped sibling: true when *any one*
        # opponent satisfies it, which is what "an opponent" means.
        "opponent_count",  # + ``selector``/``min``/``max``
        # -- The controller's own resources.
        "life_at_least",  # + ``amount``
        "life_at_most",
        "cards_in_hand_at_least",
        "cards_in_hand_at_most",
        "drawn_cards_at_least",  # + ``amount`` — "…you've drawn N cards this turn"
    }
)

#: Which object a condition reads, named by its optional ``of`` key.
#:
#: ``source``   — the ability's own source (the default, and what every
#:                condition meant before this key existed).
#: ``attached`` — the permanent the source is *attached to* (RULE 303.4a's
#:                "enchanted permanent" / 301.5c's "equipped creature"): an
#:                Aura's condition about its host rather than about itself.
#: ``affected`` — the permanent a RULE 611 floating static is aimed at, which
#:                only the caller holding the ability can resolve, so it must
#:                be passed in as ``affected``. A condition naming it in a
#:                plain ``active_if`` (where a group static has *many*
#:                affected objects, so the referent is ambiguous) fails closed.
CONDITION_SUBJECTS: frozenset[str] = frozenset({"source", "attached", "affected"})


def _controller(state: "GameState", controller_id: Optional[str]):
    for player in getattr(state, "players", []):
        if player.id == controller_id:
            return player
    return None


def _attached_to_source(state: "GameState", source: Any) -> list[Any]:
    """Every permanent currently attached *to* ``source`` (RULE 301.5/303.4).

    The inverse of `GameObject.attached_to`, which points the other way; an
    Aura/Equipment knows its host, a host doesn't list its attachments.
    """
    instance_id = getattr(source, "instance_id", None)
    if instance_id is None:
        return []
    return [o for o in state.permanents() if getattr(o, "attached_to", None) == instance_id]


def _counter_count(source: Any, kind: Optional[str]) -> int:
    """``source``'s counters of ``kind`` — or its total across kinds when no
    kind is named ("as long as ~ has three or more counters on it")."""
    counters = getattr(source, "counters", None) or {}
    if kind:
        # +1/+1 counters live in their own field, netted by the layer engine.
        if kind == "+1/+1":
            return int(getattr(source, "plus_one_counters", 0) or 0)
        return int(counters.get(kind, 0) or 0)
    total = sum(int(v or 0) for v in counters.values())
    return total + int(getattr(source, "plus_one_counters", 0) or 0)


def _subject(
    condition: dict[str, Any],
    state: "GameState",
    source: Any,
    affected: Any,
) -> Any:
    """The object this condition talks about — see `CONDITION_SUBJECTS`.

    ``None`` when the referent doesn't exist (an unattached Aura, a floating
    static with no affected object in hand, an unrecognized ``of``), which
    makes every condition below false: the same fail-closed direction as an
    unknown ``kind``.
    """
    of = condition.get("of") or "source"
    if of not in CONDITION_SUBJECTS:
        return None
    if of == "source":
        return source
    if of == "affected":
        return affected
    host_id = getattr(source, "attached_to", None)
    if host_id is None:
        return None
    for obj in state.permanents():
        if getattr(obj, "instance_id", None) == host_id:
            return obj
    return None


def condition_holds(
    condition: Optional[dict[str, Any]],
    state: "GameState",
    source: Any = None,
    controller_id: Optional[str] = None,
    affected: Any = None,
) -> bool:
    """Whether ``condition`` holds right now. No condition = always true.

    ``source`` is the ability's own source (the permanent printing "as long
    as ~ …"), ``controller_id`` the player "you" refers to — for a static
    that's the source's controller, which the caller passes rather than
    re-deriving so a control-change (layer 2) that already resolved this pass
    is honoured. ``affected`` is the single permanent a RULE 611 floating
    static is aimed at, needed only by an ``of="affected"`` condition
    (`durations.is_expired` supplies it; nothing else can).
    """
    if not condition:
        return True
    kind = condition.get("kind")
    if kind not in STATIC_CONDITION_KINDS:
        return False  # fail closed — an unmodeled condition never applies

    # Which object the subject-scoped rows below read: the source itself by
    # default, or an attached host / a floating static's affected permanent.
    subject = _subject(condition, state, source, affected)

    if kind == "source_tapped":
        return bool(getattr(subject, "tapped", False))
    if kind == "source_untapped":
        # A subject that has left the battlefield is neither: an absent
        # subject makes every condition false rather than "untapped".
        return subject is not None and not getattr(subject, "tapped", False)
    if kind == "source_monstrous":
        return bool(getattr(subject, "is_monstrous", False))
    if kind == "source_attacking":
        return bool(getattr(subject, "attacking", False))
    if kind == "source_blocking":
        return getattr(subject, "blocking", None) is not None or bool(
            getattr(subject, "additional_blocking", None)
        )
    if kind == "source_paired":
        return getattr(subject, "paired_with", None) is not None
    if kind == "source_attached":
        return getattr(subject, "attached_to", None) is not None
    if kind in ("source_equipped", "source_enchanted"):
        want_artifact = kind == "source_equipped"
        for attachment in _attached_to_source(state, subject):
            card = getattr(attachment, "card", None)
            is_artifact = bool(getattr(card, "is_artifact", False))
            # "Equipped" means an Equipment is attached; "enchanted", an Aura.
            # Read off the attachment's own card type rather than a subtype
            # string, the same way `continuous._has_card_type` does.
            if is_artifact == want_artifact:
                return True
        return False
    if kind == "source_on_battlefield":
        if subject is None:
            return False
        instance_id = getattr(subject, "instance_id", None)
        return any(o.instance_id == instance_id for o in state.permanents())
    if kind == "source_counters":
        if subject is None:
            return False
        n = _counter_count(subject, condition.get("counter"))
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and n < int(minimum):
            return False
        if maximum is not None and n > int(maximum):
            return False
        return True

    if kind in ("is_card_type", "is_color", "is_subtype"):
        # RULE 109.3 characteristics, read through `continuous`'s own matchers
        # so a *derived* type/colour counts (an animated Vehicle is a creature
        # for "as long as enchanted permanent is a creature") rather than only
        # the printed line. Function-scoped: `continuous` imports this module.
        from .continuous import _has_card_type, _has_color, _has_subtype

        if subject is None:
            return False
        if kind == "is_card_type":
            card_type = condition.get("card_type")
            return bool(card_type) and _has_card_type(subject, str(card_type))
        if kind == "is_color":
            color = condition.get("color")
            return bool(color) and _has_color(subject, [str(color)])
        subtype = condition.get("subtype")
        return bool(subtype) and _has_subtype(subject, str(subtype))

    if kind in ("your_turn", "not_your_turn"):
        active = getattr(state, "active_player", None)
        is_yours = active is not None and controller_id is not None and active.id == controller_id
        return is_yours if kind == "your_turn" else not is_yours

    if kind == "control_count":
        from .continuous import count_selector  # local: continuous imports this module

        selector = condition.get("selector")
        if not selector or controller_id is None:
            return False
        n = count_selector(state, controller_id, str(selector))
        minimum = condition.get("min")
        maximum = condition.get("max")
        if minimum is not None and n < int(minimum):
            return False
        if maximum is not None and n > int(maximum):
            return False
        return True
    if kind == "opponent_count":
        # "As long as **an** opponent has N or more cards in their graveyard"
        # (Blackbloom Rogue) — the same `count_selector` vocabulary as
        # ``control_count``, evaluated once per opponent and satisfied by any
        # one of them. "Each opponent" is a different (and so far unprinted in
        # this shape) reading and is deliberately not modeled.
        from .continuous import count_selector  # local: continuous imports this module

        selector = condition.get("selector")
        if not selector or controller_id is None:
            return False
        minimum = condition.get("min")
        maximum = condition.get("max")
        for other in getattr(state, "players", []):
            if other.id == controller_id:
                continue
            n = count_selector(state, other.id, str(selector))
            if minimum is not None and n < int(minimum):
                continue
            if maximum is not None and n > int(maximum):
                continue
            return True
        return False
    if kind == "control_named":
        # "As long as you control a <specific card>" — matched on name, the
        # only stable identity a parsed condition can carry (an instance id
        # can't exist at parse time). Case-folded, since `normalize`
        # lowercases every clause the parser sees.
        name = str(condition.get("name") or "").strip().lower()
        if not name or controller_id is None:
            return False
        return any(
            (getattr(o, "name", "") or "").strip().lower() == name
            and o.controller_id == controller_id
            for o in state.permanents()
        )

    player = _controller(state, controller_id)
    if player is None:
        return False
    if kind == "life_at_least":
        return int(getattr(player, "life", 0)) >= int(condition.get("amount", 0))
    if kind == "life_at_most":
        return int(getattr(player, "life", 0)) <= int(condition.get("amount", 0))
    if kind == "cards_in_hand_at_least":
        return len(getattr(player, "hand", [])) >= int(condition.get("amount", 0))
    if kind == "cards_in_hand_at_most":
        return len(getattr(player, "hand", [])) <= int(condition.get("amount", 0))
    if kind == "drawn_cards_at_least":
        # "As long as you've drawn two or more cards this turn" (Spinehorn
        # Minotaur-shaped). `GameState.cards_drawn_this_turn` already exists —
        # it is what `continuous`'s ``draw_limit`` permission reads (RULE
        # 616-area "you can't draw more than one card each turn") — and is
        # reset per turn by the same bookkeeping, so this is a read, not a new
        # counter.
        drawn = getattr(state, "cards_drawn_this_turn", None) or {}
        return int(drawn.get(controller_id, 0) or 0) >= int(condition.get("amount", 0))
    return False


def condition_from_legacy_params(params: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The pre-existing per-card gate params → this vocabulary, or ``None``.

    `continuous.group_selector_objects` grew three ad-hoc conditional gates
    before this module existed, and every shipped `AbilitySpec` still spells
    them that way. Rather than rewrite those specs (and the tests pinning
    them), they are translated here so there is exactly one evaluator:

    * ``active_player_only``  → ``your_turn``
    * ``min_level``/``max_level`` (+ ``level_counter``) → ``source_counters``
    * ``min_count_selector``/``min_count``  → ``control_count``

    Returns ``None`` when the params carry no legacy gate at all.
    """
    if params.get("active_player_only"):
        return {"kind": "your_turn"}
    min_level = params.get("min_level")
    max_level = params.get("max_level")
    if min_level is not None or max_level is not None:
        condition: dict[str, Any] = {
            "kind": "source_counters",
            "counter": params.get("level_counter") or "level",
        }
        if min_level is not None:
            condition["min"] = min_level
        if max_level is not None:
            condition["max"] = max_level
        return condition
    selector = params.get("min_count_selector")
    minimum = params.get("min_count")
    if selector is not None and minimum is not None:
        return {"kind": "control_count", "selector": selector, "min": minimum}
    return None


def describe(condition: Optional[dict[str, Any]]) -> str:
    """A terse German label for the board's static-effect trace panel.

    Matches `continuous._describe_combat_restriction`'s register: a few words
    naming the gate, not a sentence.
    """
    if not condition:
        return ""
    kind = str(condition.get("kind", ""))
    # The subject-scoped rows read "solange <X>"; with ``of`` naming something
    # other than the source, say which permanent is meant.
    of = condition.get("of") or "source"
    subject = {"attached": "verzaubertes/ausgerüstetes Objekt", "affected": "betroffen"}.get(of, "")
    prefix = f"solange {subject} " if subject else "solange "
    labels = {
        "source_tapped": "getappt",
        "source_untapped": "ungetappt",
        "source_monstrous": "monströs",
        "source_attacking": "angreifend",
        "source_blocking": "blockend",
        "source_paired": "verbündet",
        "source_attached": "angelegt",
        "source_equipped": "ausgerüstet",
        "source_enchanted": "verzaubert",
    }
    if kind in labels:
        return prefix + labels[kind]
    if kind == "your_turn":
        return "nur in deinem Zug"
    if kind == "not_your_turn":
        return "nur außerhalb deines Zuges"
    if kind == "source_on_battlefield":
        return prefix + "im Spiel"
    if kind == "is_card_type":
        return prefix + f"ein(e) {condition.get('card_type', '')}"
    if kind == "is_color":
        return prefix + f"Farbe {condition.get('color', '')}"
    if kind == "is_subtype":
        return prefix + f"vom Typ {condition.get('subtype', '')}"
    if kind == "source_counters":
        return prefix + f"≥{condition.get('min', 1)} {condition.get('counter', 'Marken')}"
    if kind == "control_count":
        return f"solange ≥{condition.get('min', 1)} {condition.get('selector', '')}"
    if kind == "opponent_count":
        return f"solange Gegner ≥{condition.get('min', 1)} {condition.get('selector', '')}"
    if kind == "control_named":
        return f"solange du {condition.get('name', '')} kontrollierst"
    if kind == "drawn_cards_at_least":
        return f"solange ≥{condition.get('amount', 0)} Karten gezogen"
    if kind.startswith("life_"):
        return f"solange Leben {'≥' if kind.endswith('least') else '≤'}{condition.get('amount', 0)}"
    if kind.startswith("cards_in_hand_"):
        return f"solange Handkarten {'≥' if kind.endswith('least') else '≤'}{condition.get('amount', 0)}"
    return "bedingt"
