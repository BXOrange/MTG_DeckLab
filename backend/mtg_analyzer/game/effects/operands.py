"""One amount operand for every magnitude an effect measures (ENG-47 b).

An effect's magnitude — how much damage, how many cards, how big a pump — used to be a
parameter per *measurement* per effect: ``amount_from_trigger_event``, ``count_from_count_selector``,
``amount_from_subject``, ``amount_if_kicked``, … some seventy of them across twenty effect types,
each with its own ``__init__`` argument and its own branch in ``apply``, repeated for the next
effect that wanted the same reading. `effect_amounts` is the one vocabulary that reads a number
(a board count, a characteristic of a referent, a field of the firing event, a conditional
``if``); an effect now takes **one** such operand, in the parameter that already held its
magnitude (``amount`` / ``count`` / ``power`` / ``toughness``), and measures it when it resolves
(`GameEffect._measured`).

The ``amount_from_*`` / ``count_from_*`` / ``amount_if_*`` keys survive only as *spelling* — the
parser and ~two hundred hand-authored cards write them. `lower` rewrites them into the operand
when the registry builds the effect, so the engine has one path and the IR is unchanged. A spec
carrying two such keys for one magnitude keeps the first in each rule's list (the order the
effect's own override chain checked them in).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

Params = dict[str, Any]

#: Referent names a legacy ``"<who>_<char>"`` string (``self_power``, ``previous_subject_mana_value``,
#: ``trigger_subject_toughness``) maps to in `effect_conditions.subject_of`.
_SUBJECT_WHO = ("self", "previous_subject", "trigger_subject")


def subject_reading(spec: str) -> dict[str, Any]:
    """``"trigger_subject_power"`` → the ``characteristic`` operand it names."""
    characteristic = "mana_value" if spec.endswith("_mana_value") else spec.rpartition("_")[2]
    who = spec[: -(len(characteristic) + 1)]
    return {"kind": "characteristic", "characteristic": characteristic, "of": who}


def event_field(field: str) -> dict[str, Any]:
    return {"kind": "trigger_event", "field": str(field)}


def counted(selector: "str | dict[str, Any]", **modifiers: Any) -> dict[str, Any]:
    # A structured PAR-120 selector (``{"zone", "of", "filter"}``) passes through as-is.
    selector = selector if isinstance(selector, dict) else str(selector)
    return {"kind": "count_selector", "selector": selector, **modifiers}


#: One rewrite: ``(legacy key, magnitude param it feeds, builder(value, params) → operand)``.
Rewrite = tuple[str, str, Callable[[Any, Params], Optional[dict[str, Any]]]]

_RULES: dict[str, list[Rewrite]] = {}


def rule(effect_type: str, *rewrites: Rewrite) -> None:
    _RULES.setdefault(effect_type, []).extend(rewrites)


def lower(effect_type: str, params: Optional[Params]) -> Params:
    """``params`` with every legacy measurement key of ``effect_type`` rewritten into the one
    operand its magnitude parameter now takes (the first key present wins per parameter)."""
    params = params or {}
    rewrites = _RULES.get(effect_type)
    if not rewrites or not any(key in params for key, _, _ in rewrites):
        return params
    lowered = dict(params)
    fed: set[str] = set()
    for key, target, build in rewrites:
        if key not in lowered:
            continue
        value = lowered.pop(key)
        if target in fed or value is None or value is False:
            continue
        operand = build(value, lowered)
        if operand is not None:
            lowered[target] = operand
            fed.add(target)
    return lowered


# -- draw ---------------------------------------------------------------------------------------

rule(
    "draw",
    ("count_from_trigger_event", "count", lambda v, p: event_field(v)),
    ("count_from_trigger_event_counter", "count",
     lambda v, p: {"kind": "trigger_event_counter", "counter": str(v)}),
    ("amount_from_count_selector", "count", lambda v, p: counted(v)),
    ("amount_from_subject", "count", lambda v, p: subject_reading(str(v))),
)


# -- one-line "that many" families: the count is a field of the firing event -----------------------

for _effect in ("discard", "mill", "impulsive_draw"):
    rule(_effect, ("count_from_trigger_event", "count", lambda v, p: event_field(v)))


# -- life ---------------------------------------------------------------------------------------

rule(
    "gain_life",
    ("amount_from_trigger_event", "amount", lambda v, p: event_field(v)),
    ("amount_from_subject", "amount", lambda v, p: subject_reading(str(v))),
)
rule(
    "lose_life",
    ("amount_from_trigger_event", "amount", lambda v, p: event_field(v)),
    ("amount_from_count_selector", "amount", lambda v, p: counted(v)),
    # "…for each spell they've cast this turn": the printed number times the casting player's count.
    ("amount_from_spells_cast_this_turn", "amount",
     lambda v, p: {"kind": "spells_cast_this_turn", "of": "event_player", "multiply": int(p.get("amount", 1) or 1)}),
)


# -- scry / look / connive ---------------------------------------------------------------------------

rule("scry", ("count_from_count_selector", "count", lambda v, p: counted(v)))
rule(
    "inspect_top_choose",
    # "3 plus the number of creatures in your party": the printed addend rides on the operand.
    ("count_from_count_selector", "count",
     lambda v, p: counted(v, **({"plus": int(p["count_plus"])} if p.get("count_plus") else {}))),
)
rule(
    "connive",
    ("times_from_trigger_event", "times", lambda v, p: event_field(v)),
    ("times_from_count_selector", "times", lambda v, p: counted(v)),
)


# -- counters ----------------------------------------------------------------------------------------

#: RULE 700.8: a full party is four members, the most the party count can reach.
FULL_PARTY = {"kind": "control_count", "selector": "creatures_in_your_party", "min": 4}


def _if(condition: dict[str, Any], then: Any, otherwise: Any) -> dict[str, Any]:
    """The override every "…instead" card prints: ``then`` when ``condition`` holds, else the printed
    ``otherwise`` (itself a number or an operand)."""
    return {"kind": "if", "condition": condition, "then": then, "otherwise": otherwise}


def _base(p: Params, *names: str, default: Any = 0) -> Any:
    for name in names:
        if name in p:
            return p[name]
    return default


rule(
    "add_counters",
    ("amount_from_trigger_event", "amount", lambda v, p: event_field(v)),
    ("amount_from_count_selector", "amount", lambda v, p: counted(v)),
    ("x_multiplier", "amount", lambda v, p: {"kind": "x_paid", "multiply": int(v)}),
    ("amount_if_full_party", "amount",
     lambda v, p: _if(FULL_PARTY, int(v), _base(p, "amount", "count", default=1))),
)


# -- bolster / earthbend / reveal --------------------------------------------------------------------

rule("bolster", ("amount_from_count_selector", "amount", lambda v, p: counted(v)))
rule(
    "earthbend",
    ("amount_from_trigger_event", "amount", lambda v, p: event_field(v)),
    # "twice the number of …": the printed multiplier rides on the count.
    ("amount_from_count_selector", "amount",
     lambda v, p: counted(v, **({"multiply": int(p["amount_multiplier"])} if int(p.get("amount_multiplier", 1) or 1) != 1 else {}))),
)
rule("reveal_top_then_creature_and_or_land_battlefield",
     ("amount_from_trigger_event", "amount", lambda v, p: event_field(v)))

rule(
    "discover",
    ("mana_value_from_trigger_event", "mana_value", lambda v, p: event_field(v)),
    ("mana_value_from_subject", "mana_value", lambda v, p: subject_reading(str(v))),
)

rule(
    "prevent_damage_shield",
    ("amount_if_kicked", "amount",
     lambda v, p: _if({"kind": "kicked", "min": 1}, v, p.get("amount", "all"))),
)

rule(
    "pump",
    ("amount_from_trigger_event", "dynamic_amount", lambda v, p: event_field(v)),
    ("amount_from_count_selector", "dynamic_amount",
     lambda v, p: counted(v, **({"multiply": -1} if p.get("amount_from_count_selector_negative") else {}))),
)

rule(
    "create_token",
    ("pt_from_trigger_event", "pt_amount", lambda v, p: event_field(v)),
    ("count_from_trigger_event", "count", lambda v, p: event_field(v)),
    ("count_from_trigger_event_counter", "count",
     lambda v, p: {"kind": "trigger_event_counter", "counter": str(v)}),
    ("count_from_subject", "count", lambda v, p: subject_reading(str(v))),
    ("count_from_context", "count", lambda v, p: {"kind": "this_way", "tally": str(v)}),
    ("x_multiplier", "count", lambda v, p: {"kind": "x_paid", "multiply": int(v)}),
)

rule(
    "copy_permanent",
    ("count_if_kicked", "count", lambda v, p: _if({"kind": "kicked", "min": 1}, v, p.get("count", 1))),
    ("count_from_trigger_event", "count", lambda v, p: event_field(v)),
)
