"""Per-cost Kicker announcement (RULE 702.33b, 702.33d, 702.33f; ENG-62).

"Kicker [cost 1] and/or [cost 2]" is two kicker costs, each payable at most once, in any
combination (RULE 702.33b, 702.33d); a spell is "kicked" when any was paid, and linked
abilities ask "if it was kicked with its [A] kicker" (RULE 702.33f), which needs *which* costs
were paid, not only how many. The announcement therefore has two shapes:

* an ``int`` N, the long-standing count (Kicker 0/1, Multikicker 0..N). For a card with two
  kicker costs it means *the first N costs in printed order* -- chosen over rejecting it so that a
  count-only caller (an old client, a bot that only knows ``kicked: 1``) still casts such a card
  instead of failing; callers that care which cost use the list;
* a sequence of cost indices (``[0]``, ``[1]``, ``[0, 1]``), each at most once.

The record the cast leaves on the spell is `GameObject.kicker_costs_paid` (a tuple of indices,
beside ``kicker_count`` which stays the number of payments). It is empty for a single-cost
Kicker/Multikicker, whose count already says everything.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional, Sequence, Union

KickerAnnouncement = Union[int, Sequence[int]]

_MANA_SYMBOL_RE = re.compile(r"\{[^}]+\}")


def normalize_cost_text(cost: Any) -> str:
    """A cost spelled canonically ("{2}{U}" regardless of case/spacing) so printed text and a
    parsed condition's ``cost`` compare equal."""
    return "".join(sym.upper() for sym in _MANA_SYMBOL_RE.findall(str(cost or "")))


def kicker_cost_texts(obj: Any) -> list[str]:
    """The printed kicker costs of ``obj`` in printed order -- two for "Kicker A and/or B" (the
    parser's ``costs`` list), otherwise the single ``cost``; empty without a kicker keyword."""
    param = (getattr(obj, "parametric_keywords", None) or {}).get("kicker") or {}
    costs = param.get("costs")
    if isinstance(costs, (list, tuple)) and len(costs) > 1:
        return [str(c) for c in costs]
    return [str(param["cost"])] if param.get("cost") else []


def is_multi_cost(obj: Any) -> bool:
    """Whether ``obj`` prints two separate kicker costs (RULE 702.33b "and/or")."""
    return len(kicker_cost_texts(obj)) > 1


def kicked_count(announced: Optional[KickerAnnouncement]) -> int:
    """How many kicker payments an announcement makes (the value ``kicker_count`` records)."""
    if announced is None:
        return 0
    if isinstance(announced, (list, tuple, set, frozenset)):
        return len(announced)
    return int(announced or 0)


def paid_indices(obj: Any, announced: Optional[KickerAnnouncement]) -> Optional[tuple[int, ...]]:
    """The kicker-cost indices an announcement pays on ``obj``, ascending, or ``None`` when it is
    not a legal announcement for it (an index out of range, a repeated cost -- RULE 702.33d allows
    each of two costs once -- or a list on a card without two costs).

    An ``int`` on a two-cost card pays the first N costs (see the module docstring); on a
    single-cost card it is N payments of the one cost and carries no per-cost record, so the
    result is ``()`` there (the caller reads `kicked_count` for the number).
    """
    costs = kicker_cost_texts(obj)
    if announced is None:
        return ()
    if isinstance(announced, (list, tuple, set, frozenset)):
        chosen = sorted(int(i) for i in announced)
        if len(set(chosen)) != len(chosen):
            return None
        if not chosen:
            return ()
        if len(costs) < 2 or chosen[-1] >= len(costs) or chosen[0] < 0:
            return None
        return tuple(chosen)
    count = int(announced or 0)
    if len(costs) < 2:
        return ()
    if not 0 <= count <= len(costs):
        return None
    return tuple(range(count))


def paid_cost_texts(obj: Any, indices: Iterable[int]) -> list[str]:
    """The printed cost text for each paid index (used to price the announcement exactly)."""
    costs = kicker_cost_texts(obj)
    return [costs[i] for i in indices if 0 <= i < len(costs)]


def was_kicked_with(obj: Any, cost: Any, announced: Optional[KickerAnnouncement] = None) -> bool:
    """RULE 702.33f: whether ``obj`` was kicked with its ``cost`` kicker. ``announced`` overrides
    the stored record while a cast is still being announced. Fails closed: a cost that is not one of
    the object's printed kicker costs is never "paid"."""
    wanted = normalize_cost_text(cost)
    costs = [normalize_cost_text(c) for c in kicker_cost_texts(obj)]
    if not wanted or wanted not in costs:
        return False
    index = costs.index(wanted)
    if announced is not None:
        paid = paid_indices(obj, announced)
        if paid is None:
            return False
        if len(costs) < 2:
            return kicked_count(announced) > 0
        return index in paid
    if len(costs) < 2:
        return int(getattr(obj, "kicker_count", 0) or 0) > 0
    return index in tuple(getattr(obj, "kicker_costs_paid", ()) or ())
