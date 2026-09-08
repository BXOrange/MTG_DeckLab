"""Face-down spells and permanents (RULE 708) — morph, megamorph, disguise,
manifest and cloak.

A face-down object "has no characteristics other than those listed by the
ability or rules that allowed [it] to be face down" (RULE 708.2): a 2/2
creature with no text, no name, no subtypes and no mana cost — plus ward {2}
for the disguise/cloak variants (RULE 702.168a/701.58a). This engine models
that the same way it already models a double-faced permanent's transform
(`RulesEngine.switch_to_face`): the object's `Card` is swapped for a
synthetic face-down one and its catalogue-derived bindings are cleared, with
the face-up bundle stashed on the object so turning it face up restores
exactly what was there. Everything downstream — the layer engine, combat,
the board view — then reads a 2/2 with no abilities without a single
special case.

The five ways in, and what each allows:

* **Morph** (RULE 702.37) — cast the card face down for {3}; turn it face up
  any time you have priority by paying its printed morph cost.
* **Megamorph** (RULE 702.37b) — morph plus "as this permanent is turned
  face up, put a +1/+1 counter on it". `parser/oracle/catalogue/keywords.py`
  aliases the printed keyword onto ``morph`` (they share a cost shape and a
  rules section), so the +1/+1 half is recognized here off the face-up
  card's own text rather than off a separate keyword slug.
* **Disguise** (RULE 702.168) — morph with ward {2} while face down.
* **Manifest** (RULE 701.40) — put the top card of a library onto the
  battlefield face down; turn it face up by paying its mana cost, but only
  if the card is a creature card (701.40b).
* **Cloak** (RULE 701.58) — manifest with ward {2}.

RULE 701.40c/d and 701.58c/d: a manifested or cloaked card that *also* has
morph/disguise may be turned face up either way, so `turn_face_up_options`
returns a list rather than one cost.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional

from ..models.cards.card import Card

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..models.game.game_object import GameObject

#: The name a face-down object is shown under. RULE 708.2a says it has *no*
#: name; `Card` requires a non-empty one, so this stands in — deliberately a
#: phrase no real card is named, so nothing name-keyed (the hand-authored
#: `game/ability_catalogue.py` registry, a "cards named ~" effect) can match it.
FACE_DOWN_NAME = "Face-down creature"

#: The `Card.id` every synthetic face-down face carries — the frontend keys
#: its card-back rendering off `GameObject.to_dict()`'s ``face_down`` flag,
#: but a stable id keeps image lookups from ever resolving real art.
FACE_DOWN_CARD_ID = "face-down"

#: The ways an object can come to be face down (RULE 702.37/702.168/701.40/
#: 701.58). ``"morph"`` covers megamorph — see the module docstring.
CAST_KINDS: frozenset[str] = frozenset({"morph", "disguise"})
PUT_KINDS: frozenset[str] = frozenset({"manifest", "cloak"})
FACE_DOWN_KINDS: frozenset[str] = CAST_KINDS | PUT_KINDS

#: The kinds whose face-down permanent has ward {2} (RULE 702.168a disguise,
#: RULE 701.58a cloak) — the one characteristic difference between the two
#: pairs of variants.
WARD_KINDS: frozenset[str] = frozenset({"disguise", "cloak"})

#: RULE 702.37a/702.168a: casting a card face down always costs {3},
#: whatever the printed morph/disguise cost is (that one is the *turn face
#: up* cost). An alternative cost, so it replaces the card's own.
FACE_DOWN_CAST_COST = "{3}"

_MEGAMORPH_RE = re.compile(r"\bmegamorph\b", re.I)


def face_down_card(kind: str = "morph") -> Card:
    """The synthetic `Card` a face-down object presents (RULE 708.2a).

    A 2/2 colourless creature with no text, no subtypes and no mana cost.
    ``mana_cost_string`` carries RULE 702.37a's flat {3} *alternative* cost
    so the ordinary cast pipeline (`GameEngine.effective_cast_cost`) prices
    a face-down cast with no special case, while ``converted_mana_cost``
    stays 0 — RULE 708.2a's "no mana cost" means mana value 0, which is
    what every "mana value N or less" check must see.
    """
    return Card(
        id=FACE_DOWN_CARD_ID,
        name=FACE_DOWN_NAME,
        type_line="Creature",
        mana_cost_string=FACE_DOWN_CAST_COST,
        converted_mana_cost=0,
        is_creature=True,
        power=2,
        toughness=2,
        oracle_text="",
        keywords=["Ward"] if kind in WARD_KINDS else [],
    )


def cast_face_down_kind(obj: "GameObject") -> Optional[str]:
    """Which RULE 702.37/702.168 keyword lets ``obj`` be *cast* face down —
    ``"morph"``, ``"disguise"``, or ``None`` for a card with neither.

    Read off the parametric keywords the binder docked (Megamorph aliases
    onto ``morph``, see the module docstring), so a granted morph would work
    the same way a printed one does."""
    params = getattr(obj, "parametric_keywords", None) or {}
    for kind in ("morph", "disguise"):
        if kind in params:
            return kind
    return None


def is_megamorph(card: Card) -> bool:
    """RULE 702.37b: whether ``card``'s morph keyword is printed as
    Megamorph — the variant that adds a +1/+1 counter as the permanent is
    turned face up. The keyword catalogue folds the two spellings onto one
    slug, so the distinction is read back off the printed text here."""
    return bool(_MEGAMORPH_RE.search(card.oracle_text or ""))


def face_up_card(obj: "GameObject") -> Optional[Card]:
    """The real card under a face-down object, or ``None`` if it isn't face
    down. Only its controller may look (RULE 708.5) — enforcing that is the
    session view's job (`services/game_session.py`), not this helper's."""
    snapshot = getattr(obj, "_face_up_snapshot", None)
    if not obj.face_down or not snapshot:
        return None
    return snapshot.get("card")


def turn_face_up_options(obj: "GameObject") -> list[dict[str, Any]]:
    """Every way ``obj``'s controller may turn it face up (RULE 708.7), as
    ``{"kind", "cost", "label", "megamorph"}`` entries — empty when there is
    none (a manifested noncreature, RULE 701.40g).

    * A card with morph/disguise pays that printed cost (RULE 702.37e/
      702.168d) no matter *how* it came to be face down — RULE 701.40c/d and
      701.58c/d say a manifested or cloaked card with morph keeps that route
      alongside its own.
    * A manifested/cloaked card pays its **mana cost**, and only if it is a
      creature card (RULE 701.40b/701.58b).
    """
    from ..models.mana.mana_cost import ManaCost  # function-scoped: models import cost

    card = face_up_card(obj)
    if card is None:
        return []
    options: list[dict[str, Any]] = []
    params = getattr(obj, "_face_up_snapshot", {}).get("parametric_keywords") or {}
    for kind in ("morph", "disguise"):
        cost_text = (params.get(kind) or {}).get("cost")
        if not cost_text:
            continue
        options.append(
            {
                "kind": kind,
                "cost": ManaCost.parse(cost_text),
                "label": cost_text,
                # RULE 702.37b: only the *megamorph* cost being paid adds the
                # counter — turning the same card up via a manifest's mana
                # cost (below) does not.
                "megamorph": kind == "morph" and is_megamorph(card),
            }
        )
    if obj.face_down_kind in PUT_KINDS and card.is_creature and card.mana_cost_string:
        options.append(
            {
                "kind": obj.face_down_kind,
                "cost": ManaCost.parse(card.mana_cost_string),
                "label": card.mana_cost_string,
                "megamorph": False,
            }
        )
    return options
