"""Who an effect acts on — one structured vocabulary for its operands
(ENG-37, `14_` axis 4).

The third of the three vocabularies the effect IR needs, and the last one
missing. `effect_conditions.py` answers **whether** an effect applies,
`effect_amounts.py` answers **how much**, and this answers **to whom**.

Why it exists
-------------
`14_` §1.1 describes the registered effect types as a cross-product of
operation × operands × composition × linkage. ENG-37 built the composition
axis and then measured what was still keeping the 84 fused types alive: it
was this one. A fusion exists because its second part must name what the
first part *produced* — "destroy target permanent, **its controller** gains 4
life", "exile target creature, **its controller** gains life equal to its
power" — and an effect's operand could not name a referent. So the two halves
had to be welded into one class that held the referent in a local variable.
`ExileGainLifeToControllerEffect`'s own docstring said so outright:
"composing two effects here couldn't pass the power along".

The axis had already started filling in by hand, one flag at a time, exactly
the way the condition keys did before ENG-36: `GainLifeEffect.recipient=
"target_controller"`, `DrawCardEffect.player_from_trigger_event`,
`AddPlayerCountersEffect.player_from_target`, `SacrificeEffect.selector=
"each_player"`, `DealDamageEffect.player_selector="active_player"`, plus 174
effects calling `_controller_of(self.source, context)` for the default. Each
is "read *this* participant off *that* thing", written once per effect.

Reading it
----------
An operand is one of:

* ``None`` — the ability's own controller, i.e. what "you" means and what
  those 174 call sites default to;
* a live `Player`/`GameObject` — an already-resolved operand, which is how
  every existing caller passes one, unchanged;
* a **scope** string from `PLAYER_SCOPES` — "each player", "each opponent",
  the active player, the defending player: a set, not a referent;
* a **referent** dict ``{"of": <name>, "as": "controller"|"owner"}`` — the
  same referent axis `effect_conditions.subject_of` resolves, plus the one
  derivation printed cards actually need ("**its** controller"). ``as`` is a
  modifier rather than a doubled set of referent names for the reason ENG-36
  gives for ``not``: "the controller of" applies to every object referent, so
  spelling it as a modifier keeps the referent list from doubling.

Fail-safe, like the other two: an unrecognized scope or referent resolves to
**no players**, so the effect simply doesn't happen to anyone. That is the
same direction an unmodelled condition (never applies) and an unmodelled
amount (zero) take.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from . import effect_conditions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .effects.core import GameContext


#: Scope names that mean a *set* of players rather than a referent. These are
#: the spellings already shipped across `SacrificeEffect.selector`,
#: `MillEffect.player_selector` and `DealDamageEffect.player_selector`; this
#: module recognizes them so an operand can be written one way regardless of
#: which effect reads it.
PLAYER_SCOPES: frozenset[str] = frozenset(
    {
        "controller",  # "you" — the ability's controller
        "you",  # the same thing, as several params already spell it
        "each_player",  # RULE 101.4, APNAP order
        "each_opponent",
        "active_player",  # RULE 502.1's active player, whoever's turn it is
        "defending_player",  # RULE 506.4, only meaningful during combat
    }
)

#: Derivations an operand may apply to a resolved referent. Anything else
#: resolves to nobody.
REFERENT_DERIVATIONS: frozenset[str] = frozenset(
    {"self", "controller", "owner", "host"}
)


def _player_by_id(context: "GameContext", player_id: Optional[str]) -> Any:
    if player_id is None:
        return None
    for player in getattr(context.state, "players", []):
        if player.id == player_id:
            return player
    return None


def _is_player(candidate: Any) -> bool:
    """A `Player` has no ``instance_id``; that absence is what the targeting
    code already uses to tell the two apart. An ability on the stack has none
    either (it is a `StackItem`, keyed by ``stack_id``), but it is not a player:
    its controller is `controller_id` like any object's ("counter target …
    ability. **Its controller** loses life …" — Deny the Witch)."""
    return (
        candidate is not None
        and getattr(candidate, "instance_id", None) is None
        and getattr(candidate, "stack_id", None) is None
    )


def _derive(context: "GameContext", subject: Any, derivation: str) -> Any:
    """Apply ``as`` to a resolved referent — see `REFERENT_DERIVATIONS`."""
    if subject is None or derivation not in REFERENT_DERIVATIONS:
        return None
    if derivation == "self":
        return subject
    if derivation == "host":
        # The permanent an Aura/Equipment/Fortification was attached to. A
        # preceding unattach instruction snapshots this relation because the
        # live ``attached_to`` link is necessarily gone by the time a rider
        # says "that creature" (RULE 608.2c).
        host_id = getattr(subject, "attached_to", None)
        if host_id is None:
            host_id = (getattr(context, "attachment_hosts", {}) or {}).get(
                getattr(subject, "instance_id", None)
            )
        return context.state.find_object(host_id) if host_id is not None else None
    if _is_player(subject):
        # "Its controller", asked of a player, is that player: the printed
        # text never says this, but a referent that resolved to a player
        # rather than an object shouldn't silently become nobody.
        return subject
    key = "controller_id" if derivation == "controller" else "owner_id"
    return _player_by_id(context, getattr(subject, key, None))


def _scope(
    scope: str, context: "GameContext", source: Any, targets: Optional[list[Any]]
) -> list[Any]:
    controller_id = effect_conditions._controller_id(source, context)
    living = list(context.state.living_players())
    if scope in ("controller", "you"):
        player = _player_by_id(context, controller_id)
        return [player] if player is not None else []
    if scope == "each_player":
        return living
    if scope == "each_opponent":
        return [p for p in living if p.id != controller_id]
    if scope == "active_player":
        active = getattr(context.state, "active_player", None)
        return [active] if active is not None else []
    if scope == "defending_player":
        # RULE 506.4 — only answerable once attackers are declared, which is
        # why this can't be a target chosen at cast time.
        from .effects.core import _defending_player_of  # function-scoped: cycle

        defender = _defending_player_of(source, context)
        return [defender] if defender is not None else []
    return []


def players_for(
    operand: Any,
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> list[Any]:
    """The players ``operand`` names — see the module docstring.

    ``None`` means the ability's controller, which is the default 174 effects
    already hard-code; passing an already-resolved `Player` through unchanged
    is what keeps every existing caller working.
    """
    if operand is None:
        return _scope("controller", context, source, targets)
    if _is_player(operand) and not isinstance(operand, (str, dict)):
        return [operand]
    if isinstance(operand, str):
        return _scope(operand, context, source, targets)
    if isinstance(operand, dict):
        subject = effect_conditions.subject_of(
            str(operand.get("of") or "source"), context, source, targets
        )
        derivation = str(operand.get("as") or "controller")
        player = _derive(context, subject, derivation)
        if player is None and subject is None and operand.get("of") == "entering":
            # RULE 608.2h: the event's object is gone (a token that died ceased to
            # exist, RULE 704.5d) — its last known controller/owner is on the event.
            event = getattr(context, "trigger_event", None) or {}
            key = "controller_id" if derivation == "controller" else "owner_id"
            player = _player_by_id(context, event.get(key))
        return [player] if player is not None else []
    return []


def player_for(
    operand: Any,
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> Any:
    """`players_for`, for the common case of a single recipient.

    The first player the operand names, or ``None``. A scope naming several
    (``each_player``) collapses to the first in APNAP order rather than
    raising — a caller that means "each" asks `players_for` instead.
    """
    players = players_for(operand, context, source, targets)
    return players[0] if players else None


def object_for(
    operand: Any,
    context: "GameContext",
    source: Any = None,
    targets: Optional[list[Any]] = None,
) -> Any:
    """The single *object* ``operand`` names — a referent, or a live object
    passed straight through. ``None`` when it names a player or nothing."""
    if operand is None:
        return None
    if isinstance(operand, dict):
        subject = effect_conditions.subject_of(
            str(operand.get("of") or "source"), context, source, targets
        )
        derivation = str(operand.get("as") or "self")
        resolved = _derive(context, subject, derivation)
        return resolved if not _is_player(resolved) else None
    if isinstance(operand, str):
        subject = effect_conditions.subject_of(operand, context, source, targets)
        return subject if not _is_player(subject) else None
    return operand if not _is_player(operand) else None
