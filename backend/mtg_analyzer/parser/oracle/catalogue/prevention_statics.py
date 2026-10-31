"""Standing damage prevention and redirection over the shared object phrase (PAR-216).

The imperative "prevent all damage that would be dealt to `<recipient>` by `<source>`" and the redirect "all damage that
would be dealt to `<recipient>` is dealt to `<X>` instead" are standing replacement effects on a permanent (RULE 614.1,
615.1, 616.1), not resolve-time grants. `replacements.replacement_clause_specs` owns the closed vocabulary that predates
this module; this one is the open grammar behind it: the recipient and source slots are `parse_object_phrase` object
phrases plus the host references ("enchanted creature", "~"), the combat qualifier is a flag on the damage event, and
the answer is a `prevent_damage` / `redirect_damage` replacement spec (`game/effects/replacements.py`). Anything the
slots do not fully parse returns ``None`` (fail-closed). Pure -- no ``game/`` imports (parser security boundary).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..spec import EffectSpec
from .characteristic_phrase import parse_object_phrase
from .subtype_vocabulary import SUBTYPES

#: The host a standing line may name: the permanent itself, or the one an Aura/Equipment is attached to.
_SELF_WORDS = ("~", "this creature", "this permanent")
_ATTACHED_WORDS = ("enchanted creature", "equipped creature", "enchanted permanent", "equipped permanent")

#: "combat damage" / "noncombat damage" is a property of the damage event (RULE 510.2 vs. anything else).
_COMBAT_WORDS: dict[str, bool] = {"combat ": True, "noncombat ": False}

#: A parsed object-phrase controller word → the standing shield's controller vocabulary.
_SOURCE_CONTROLLERS: dict[str, str] = {"you": "you", "not_you": "opponent"}

_COMBAT_ALT = "|".join(re.escape(w) for w in _COMBAT_WORDS)
_DAMAGE_HEAD = rf"(?P<combat>{_COMBAT_ALT})?damage"

#: "prevent all [combat|noncombat] damage that would be dealt `<tail>`".
_PREVENT_RE = re.compile(rf"prevent all {_DAMAGE_HEAD} that would be dealt (?P<tail>.+)", re.I)
#: "prevent all damage that ~ would deal to `<victims>`" (Indentured Oaf, Goblin Furrier).
_PREVENT_DEALER_RE = re.compile(
    r"prevent all damage that (?P<dealer>~|this creature) would deal to (?P<victims>.+)", re.I,
)
#: "if a source would deal N or less damage to `<recipient>`, prevent that damage" (Callous Giant).
_PREVENT_AT_MOST_RE = re.compile(
    r"if a source would deal (?P<n>\d+) or less damage to (?P<recipient>.+), prevent that damage", re.I,
)
#: "if a source|creature would deal [combat] damage to `<recipient>`, prevent N|all but N of that damage" (Thunderstaff,
#: Hyperion): the amount-trimming sibling of the "prevent all" lines, the damage source named as a singular noun.
_PREVENT_PART_RE = re.compile(
    rf"if (?P<src>a source|a creature) would deal (?P<combat>{_COMBAT_ALT.replace('noncombat ', '')})?damage to "
    r"(?P<recipient>.+), prevent (?P<amount>all but \d+|\d+) of that damage",
    re.I,
)
#: "all [combat] damage that would be dealt to `<recipient>` is dealt to `<new>` instead" (Empyrial Archangel, Pariah).
_REDIRECT_RE = re.compile(
    rf"all {_DAMAGE_HEAD} that would be dealt to (?P<tail>.+?) is dealt to (?P<new>.+?) instead", re.I,
)


def _host_params(word: str) -> Optional[dict[str, Any]]:
    """A host word → the replacement's ``to`` recipient (``None`` when it is not a host)."""
    if word in _SELF_WORDS:
        return {"to": "self"}
    if word in _ATTACHED_WORDS:
        return {"to": "attached_permanent"}
    return None


def _object_filter_entry(phrase: str) -> Optional[dict[str, Any]]:
    """"other attacking soldiers you control" -> the filter of objects *you control* that phrase names, or ``None``."""
    text = phrase.strip()
    exclude_self = text.startswith("other ")
    if exclude_self:
        text = text[len("other "):]
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller != "you":
        return None
    entry = dict(filt)
    if exclude_self:
        entry["exclude_self"] = True
    return entry


def _recipient_params(text: str) -> Optional[dict[str, Any]]:
    """A recipient phrase -> ``to`` / ``recipient_filter`` / ``recipient_union`` (RULE 615.1 "dealt to"), or ``None``."""
    text = text.strip()
    host = _host_params(text)
    if host is not None:
        return host
    union = re.fullmatch(r"you or an? (?P<subtype>[a-z]+) you control", text)
    if union is not None:  # "you or a hero you control" (Hyperion)
        subtype = union.group("subtype")
        return {"recipient_union": ["controller", {"subtype": subtype}]} if subtype in SUBTYPES else None
    if text == "you":
        return {"to": "controller"}
    if text.startswith("you and "):
        entry = _object_filter_entry(text[len("you and "):])
        return None if entry is None else {"recipient_union": ["controller", entry]}
    entry = _object_filter_entry(text)
    return None if entry is None else {"to": "controlled_permanent", "recipient_filter": entry}


def _source_filter(text: str) -> Optional[dict[str, Any]]:
    """A "by `<source>`" phrase -> the standing shield's ``source_filter`` fragment, or ``None``."""
    text = text.strip()
    if text in _ATTACHED_WORDS:
        return {"attached": True}
    if text in _SELF_WORDS:
        return {"self_source": True}
    if text == "creatures it's blocking":
        return {"blocked_by_self": True}
    if text == "creatures blocking it":
        return {"blocking_self": True}
    if text == "unblocked creatures":
        return {"unblocked": True}
    parsed = parse_object_phrase(text, plural=True)
    if parsed is None:
        return None
    filt, controller = parsed
    if controller not in (None, *_SOURCE_CONTROLLERS):
        return None
    result: dict[str, Any] = {"object_filter": filt}
    if controller is not None:
        result["controller"] = _SOURCE_CONTROLLERS[controller]
    return result


def _with_combat(source_filter: dict[str, Any], combat_word: Optional[str]) -> dict[str, Any]:
    if combat_word:
        source_filter["combat"] = _COMBAT_WORDS[combat_word.lower()]
    return source_filter


def _split_by(tail: str) -> tuple[str, Optional[str]]:
    """"you by artifacts" -> ("you", "artifacts"); the recipient never contains " by "."""
    recipient, sep, source = tail.partition(" by ")
    return recipient, (source if sep else None)


def _prevent_spec(params: dict[str, Any], source_filter: dict[str, Any]) -> EffectSpec:
    return EffectSpec("prevent_damage", {**params, "amount": "all", **({"source_filter": source_filter} if source_filter else {})})


def _prevent_tail_specs(combat_word: Optional[str], tail: str) -> Optional[list[EffectSpec]]:
    """The tail of "prevent all [combat] damage that would be dealt `<tail>`"."""
    tail = tail.strip()
    if tail.startswith("to and dealt by "):
        host = tail[len("to and dealt by "):].strip()
        recipient = _host_params(host)
        source = _source_filter(host)
        if recipient is None or source is None:
            return None
        return [
            _prevent_spec(recipient, _with_combat({}, combat_word)),
            _prevent_spec({"to": "any"}, _with_combat(source, combat_word)),
        ]
    if tail.startswith("by "):
        source = _source_filter(tail[len("by "):])
        if source is None:
            return None
        return [_prevent_spec({"to": "any"}, _with_combat(source, combat_word))]
    if not tail.startswith("to "):
        return None
    recipient_text, source_text = _split_by(tail[len("to "):])
    recipient = _recipient_params(recipient_text)
    if recipient is None:
        return None
    source: dict[str, Any] = {}
    if source_text is not None:
        parsed_source = _source_filter(source_text)
        if parsed_source is None:
            return None
        source = parsed_source
    return [_prevent_spec(recipient, _with_combat(source, combat_word))]


def _redirect_target(word: str) -> Optional[str]:
    """What the redirected damage is dealt to instead, read off the shield's own permanent."""
    word = word.strip()
    if word in _SELF_WORDS:
        return "self"
    if word in _ATTACHED_WORDS:
        return "attached_permanent"
    if word in ("its controller", "that creature's controller"):
        return "recipient_controller"
    return None


def prevention_static_specs(text: str) -> Optional[list[EffectSpec]]:
    """Specs for a standing prevent/redirect line (already stripped of its final period), else ``None``."""
    m = _PREVENT_RE.fullmatch(text)
    if m is not None:
        return _prevent_tail_specs(m.group("combat"), m.group("tail"))
    m = _PREVENT_DEALER_RE.fullmatch(text)
    if m is not None:
        victims = parse_object_phrase(m.group("victims").strip(), plural=True)
        if victims is None or victims[1] is not None:
            return None
        return [_prevent_spec(
            {"to": "all_creatures", "recipient_filter": victims[0]}, {"self_source": True},
        )]
    m = _PREVENT_AT_MOST_RE.fullmatch(text)
    if m is not None:
        recipient = _recipient_params(m.group("recipient"))
        if recipient is None:
            return None
        return [_prevent_spec(recipient, {"max_amount": int(m.group("n"))})]
    m = _PREVENT_PART_RE.fullmatch(text)
    if m is not None:
        recipient = _recipient_params(m.group("recipient"))
        if recipient is None:
            return None
        source: dict[str, Any] = {"object_filter": {"card_type": "creature"}} if m.group("src") == "a creature" else {}
        amount_text = m.group("amount")
        amount: Any = {"all_but": int(amount_text[len("all but "):])} if amount_text.startswith("all but ") else int(amount_text)
        spec = _prevent_spec(recipient, _with_combat(source, m.group("combat")))
        spec.params["amount"] = amount
        return [spec]
    m = _REDIRECT_RE.fullmatch(text)
    if m is not None:
        new = _redirect_target(m.group("new"))
        recipient_text, source_text = _split_by(m.group("tail"))
        recipient = _recipient_params(recipient_text)
        if new is None or recipient is None:
            return None
        source: dict[str, Any] = {}
        if source_text is not None:
            parsed_source = _source_filter(source_text)
            if parsed_source is None:
                return None
            source = parsed_source
        source = _with_combat(source, m.group("combat"))
        return [EffectSpec("redirect_damage", {
            **recipient, "redirect_to": new, **({"source_filter": source} if source else {}),
        })]
    return None
