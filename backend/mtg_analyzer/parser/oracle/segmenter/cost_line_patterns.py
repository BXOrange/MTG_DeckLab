"""Segmenter: cost line patterns (split from `segmenter.py` by PAR-172's method, ENG-59)."""

from __future__ import annotations

import re
from typing import Any, Optional
from ..catalogue.sacrifice_clause import read_sacrifice_clause
from ..spec import MODIFIED_CREATURE_WORD, additional_cost_sacrifice_word_ok
from ..catalogue.subgrammars import COLOR_WORD_ALT

#: PAR-277, RULE 608.2c / 110.2: "Gain control of target nonland permanent an opponent controls. **That opponent**
#: draws 3 cards." (Rules of Acquisition) -- "that opponent" is the player who controlled the permanent before the
#: change (`former_controller`), not a target and not the permanent's controller now.
GAIN_CONTROL_THEN_FORMER_DRAWS_RE = re.compile(
    r"^(?P<before>gain control of target [^.]+? an opponent controls)\.\s*"
    r"that opponent draws (?P<count>a|\d+) cards?\.?$",
    re.IGNORECASE | re.DOTALL,
)

#: "Sacrifice it. **When you do,** `<effect>`." (RULE 603.3's "when you do"
#: sub-trigger, Maestros Theater/Bant Panorama's cousin cycle-shaped) —
#: deliberately narrow, not a general "you may X. When you do, Y." handler:
#: RULE 603.3's own "when you do" only fires *if* the triggering action
#: happened, which for an unconditional "Sacrifice it." antecedent (no
#: "may") is a certainty, so the two clauses collapse to one plain sequence
#: with no interactive branch needed. The 200+ cache hits on "you may
#: `<action>`. When you do, `<effect>`." are a real, much bigger family
#: (RULE 603.3's genuine optional-then-branch shape, needing its own
#: pending_choice) deliberately NOT attempted here — this regex only matches
#: when the clause immediately before "When you do,"/"If you do," is exactly
#: a bare self-sacrifice, so it can never misfire onto one of those.
#:
#: PAR-74: the "**If** you do," connector (Dreamcatcher: "You may sacrifice
#: ~. If you do, draw a card.") collapses the exact same way as "When you
#: do,": by the time `parse_effect_body` sees this clause, the *outer*
#: "you may" has already been peeled off the whole triggered ability
#: (`optional=True` on the `AbilitySpec`, at the cast-trigger dispatch
#: site) — so what's left here, "sacrifice ~. if/when you do, `<effect>`.",
#: is itself an unconditional antecedent once the ability has already been
#: accepted, same as the plain "Sacrifice it." shape this row was built
#: for. RULE 603.3 and 603.4's own "if"/"when" reflexive triggers are a real
#: distinction elsewhere, but not one this already-certain antecedent can
#: ever make observable.
_SACRIFICE_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>sacrifice (?:it|this \w+|~))\.\s*(?:when|if) you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-74: "[You may] exile ~. If you do, return it to the battlefield under
#: its owner's control at the beginning of the next end step." (Hikari,
#: Twilight Guardian) — the exile-zone sibling of
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE`'s own collapse: once the outer "you may"
#: has already been peeled off the whole triggered ability, a bare
#: self-exile is just as certain as a bare self-sacrifice (RULE 400, no
#: failure state), so "if you do" reduces the same way to one plain
#: sequence — an `ExileEffect(remember=True)` linking the exiled object onto
#: this ability's own source (`GameObject.linked_exile_id`, the O-Ring-
#: shaped mechanism `ReturnLinkedExileEffect` already reads), plus a RULE
#: 603.7 delayed trigger (`create_delayed_trigger`, ``step="end"``,
#: ``scope="any"`` — "the next end step" isn't controller-scoped) that fires
#: it at the named step. Narrow to exactly this destination/timing (no
#: "tapped"/"under your control" variant seen yet) rather than a general
#: "exile ~, delayed-return" grammar no other card has needed.
EXILE_SELF_THEN_DELAYED_RETURN_RE = re.compile(
    r"^(?P<before>exile (?:it|this \w+|~))\.\s*(?:when|if) you do, "
    r"return it to the battlefield under its owner'?s control "
    r"at the beginning of the next end step$",
    re.IGNORECASE | re.DOTALL,
)

#: "Earthbend N. **When you do,** `<effect>`." (RULE 701.66 + RULE 603.3's
#: "when you do" sub-trigger — Earth Rumble). Same collapse rationale as
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE`: "earthbend N" is a mandatory keyword
#: action (no "may"), so RULE 603.3's "when you do" is a certainty and the
#: two sentences reduce to one plain sequence — `[earthbend N, <effect>]` —
#: with no interactive branch. Narrow: only when the clause immediately
#: before "When you do," is exactly `earthbend N`, so it can never misfire
#: onto the genuine optional "you may `<action>`. When you do, …" family.
_EARTHBEND_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>earthbend \d+)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: RULE 706 + 603.11: "Roll a d20. When you do, <payoff where X is the
#: result>." The roll is mandatory, but its payoff is nevertheless a fresh
#: reflexive trigger: Ancient Bronze Dragon's targets must be chosen after
#: its controller knows X. ``RollDieEffect`` owns the deferred trigger; this
#: parser layer only folds the two printed sentences into ``then_trigger``.
ROLL_DIE_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>roll (?:a |an |\d+ )?(?:d\d+|\d+-sided die(?:s)?))\.\s*"
    r"when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: "Discard a card. **If you do,** `<effect>`." (Gristle Glutton's
#: `{T}, Blight 1:` loot body, and the wider mandatory-discard-then-draw
#: family). Same collapse rationale as the two above — a plain "discard a
#: card" antecedent all but always succeeds, so the "if you do" gate
#: reduces to a sequence `[discard, <effect>]`. **Documented
#: simplification:** the one case it *can* fail (an empty hand) isn't
#: modeled. Narrow: the clause before "if you do," must be exactly a bare
#: mandatory discard, so it never misfires onto the optional
#: "you may discard …. If you do, …" family (`_pay_cost_then_or_else`).
_DISCARD_THEN_IF_YOU_DO_RE = re.compile(
    r"^(?P<before>discard (?:a card|\d+ cards?|your hand))\.\s*(?:if|when) you do,?\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

# A completed action and its reflexive payoff have separate announcements.
ACTION_THEN_WHEN_YOU_DO_RE = re.compile(
    r'^(?P<before>(?:exile|create) (?:"[^"]*"|[^."])+?)\.\s*when you do,\s*(?P<after>.+)$',
    re.IGNORECASE | re.DOTALL,
)

#: PAR-164: "You may exile `<it / ~>`. **When you do,** `<effect>`." — a dies trigger's source is already a card in
#: its owner's graveyard (RULE 400.7), so the optional exile is the antecedent and the effect is RULE 603.12's
#: reflexive trigger, whose target is chosen only after the exile happened. Unlike the certain-antecedent rows
#: above, the "may" is *kept* (the exile is the choice), so `PAY_ENERGY_THEN_PEEL_GUARD_RE` leaves it un-peeled and
#: this row lowers the pair onto `may_exile_source_then` (Greenwarden of Murasa / Undead Butler's primitive).
MAY_EXILE_SELF_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^you may exile (?:it|that card|~)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-284 milestone 22: "Exile `<it / ~>`. **When you do,** `<effect>`." -- the mandatory sibling of the row above (Glissa's
#: Retriever): the dying source is exiled for certain (RULE 603.12), then the payoff is the reflexive trigger whose targets
#: are chosen with the source already gone from the graveyard. Lowers onto `may_exile_source_then` with ``required``.
EXILE_SELF_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^exile (?:it|that card|~)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-121: the rows above whose antecedent is **certain** — a sacrifice of the source, an earthbend, a bare
#: mandatory discard — share one body: parse the antecedent, require the spec type it must produce, then the
#: "when/if you do" sentence is just the next clause (`with_after_tail`). Each entry is ``(regex, the antecedent
#: spec type it must yield)``; a row's own connective wording stays in its regex, since it is what keeps a
#: *may* antecedent ("you may discard a card. If you do, …" — `_pay_cost_then_or_else`) from collapsing.
#: The antecedents start with different verbs, so the order is immaterial.
CERTAIN_ANTECEDENT_ROWS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (_SACRIFICE_THEN_WHEN_YOU_DO_RE, "sacrifice_self"),
    (_EARTHBEND_THEN_WHEN_YOU_DO_RE, "earthbend"),
    (_DISCARD_THEN_IF_YOU_DO_RE, "discard"),
)

#: PAR-79 eighth increment: a *preceding* sentence in front of
#: `catalogue.effect_rows.pump_stats._DELAYED_SAC_EXILE_WHEN_FIRST_RE`'s own "at the
#: beginning of the next end step, sacrifice/exile/return `<it>`[. if you
#: do, `<effect>`]." shape (the Alora, Cheerful `<X>` cycle's own
#: unblockable-target sentence ahead of the delayed return). Deliberately
#: loose — it only has to find the split point; `match_clause` re-validates
#: the ``delayed`` half against the real handler, so a wrong split just
#: fails closed rather than misparsing anything. ``before`` is non-greedy
#: so it stops at the *first* such delayed clause, matching how a real
#: card only ever prints one.
PREFIXED_DELAYED_SAC_EXILE_RE = re.compile(
    r"^(?P<before>.+?)\.\s*(?P<delayed>at the beginning of (?:the|your) next end step, "
    r"(?:sacrifice|exile|return)\b.+)$",
    re.IGNORECASE | re.DOTALL,
)

# PAR-98: the tail-form sibling is attached to an activated ability after
# an ordinary target effect (Wings of Hubris / Goblin Sappers).  As above,
# the catalogue handler validates the tail itself; this only protects the
# two-sentence composition from the generic connector splitter.
PREFIXED_DELAYED_TAIL_RE = re.compile(
    r"^(?P<before>.+?)\.\s*(?P<delayed>(?:then )?(?:its controller )?"
    r"(?:sacrifice|exile|destroy)\b.+?"
    r"(?:at the beginning of (?:the|your) next end step|at end of combat))$",
    re.IGNORECASE | re.DOTALL,
)

FROM_AMONG_THEM_RE = re.compile(r"\bfrom among them\b", re.IGNORECASE)

MILL_LAND_THIS_WAY_RE = re.compile(
    r"^(?P<before>mill (?:a|\d+) cards?)\.\s*if a land card was milled this way,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-254: "Mill N cards. You may put/exile `<card filter>` from among the cards milled this way [into your hand]. If you
#: don't, `<effect>`." / "... If you do, `<effect>`." -- the optional pick is one `choose_objects` over the mill's own
#: cards, and the connective rides it: "if you do" is its ``then`` (RULE 608.2c, the picked card is "that card"), "if you
#: don't" its ``else_effects`` (RULE 608.2d: also true when no card of the mill qualifies, or the player declines).
#: ``before`` may be "each player mills N cards" (Shadow Kin); the choice sentence is parsed by the ordinary
#: "from among the milled cards" row, so the filter vocabulary is the shared `parse_object_phrase`.
MILL_CHOOSE_FROM_MILLED_RE = re.compile(
    r"^(?P<before>(?:each player )?mills? (?:a|\d+) cards?)\.\s*"
    r"(?P<choice>you may (?:put|exile) [^.]+? from among the cards milled this way(?: into your hand)?)\.\s*"
    r"if you (?P<branch>don'?t|do),\s*(?P<after>[^.]+?)\.?$",
    re.IGNORECASE | re.DOTALL,
)

COUNTER_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>put a \+1/\+1 counter on ~)\.\s*when you do,\s*(?P<after>.+)$",
    re.IGNORECASE | re.DOTALL,
)

REFLEXIVE_TAP_PEEL_RE = re.compile(
    r"^(?:you may )?(?P<rest>tap another untapped merfolk you control\.\s*when you do,.+)$",
    re.IGNORECASE | re.DOTALL,
)

TAP_THEN_WHEN_YOU_DO_RE = re.compile(
    r"^(?P<before>tap another untapped [a-z]+ you control)\.\s*when you do,\s*(?P<after>return target creature card with mana value \d+ or less from your graveyard to the battlefield)\.?$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-18/ENG-33: "Exile [up to N] target <X> card from [a/your] graveyard.
#: [If you do / If you exiled a card this way,] create a token that's a copy
#: of **that card**[, except <tail>]." — the reanimator-token cycle (Ardyn,
#: Anikthea, Séance, God-Pharaoh's Gift, Sauron the Necromancer, Sin,
#: Soul Separator &c.). Two sentences that are one instruction: the exiled
#: card *is* the pronoun antecedent (RULE 608.2 — `GameContext.
#: previous_targets`) the copy clause reads back, so — same
#: `parse_effect_body`-level idiom as `LOOK_TOP_SELECT_RE` /
#: `_SACRIFICE_THEN_WHEN_YOU_DO_RE` — the whole span is matched here before
#: the connector-split loop shatters it into a bare "if you do, create …"
#: half no handler claims. The reflexive "if you do" / "if you exiled …
#: this way" connector needs no `pending_choice`: `CopyPermanentEffect
#: (referent="previous")` already no-ops when `previous_targets` is empty,
#: which is exactly the state the connector gates on. Deliberately narrow —
#: the ``after`` group is anchored on "create a … token that's a copy of
#: that card" (an effect that is safe to run unconditionally because it
#: self-gates on the antecedent), never a general reflexive-clause stripper.
EXILE_THEN_COPY_SENTENCE_RE = re.compile(
    r"^(?P<before>(?:you may )?exile .+?graveyard[^.]*?)\.\s*"
    r"(?:(?:if you do|if you exiled (?:a|up to \w+|\w+) cards?(?: this way)?)"
    r"(?: this way)?,\s*)?"
    r"(?P<after>create a (?:tapped and attacking |tapped |attacking )?"
    r"token that'?s a copy of (?:that card|it).*)$",
    re.IGNORECASE | re.DOTALL,
)

#: PAR-30 reanimator-token residue — the *X-count "for each card exiled this
#: way"* sibling of `EXILE_THEN_COPY_SENTENCE_RE`: "Exile X target creature
#: cards from your graveyard. For each [creature] card exiled this way,
#: `<create clause>`." (Hour of Eternity — a copy token; Midnight Ritual — a
#: plain inline token). The exile is a many-target RULE 107.3 {X} pick
#: (`count_selector="source_x_paid"`, the same one Foggy Swamp Visions'
#: waterbend-X exile uses); the follow-up scales off it — one copy of *each*
#: exiled card (`copy_permanent` ``referent="previous_each"``) or N inline
#: tokens (`create_token` ``count_from_context="objects_exiled_this_way"``).
EXILE_X_GY_FOR_EACH_CREATE_RE = re.compile(
    r"^exile x target creature cards from your graveyard\.\s*"
    r"for each (?:creature )?card exiled this way,\s*"
    r"(?P<create>create .+)$",
    re.IGNORECASE | re.DOTALL,
)

#: RULE 601.2b/604.3's additional-cost line: "As an additional cost to cast
#: this spell, <cost>." — instants/sorceries only (gated by
#: ``allow_spell_effect`` at the call site below, same as a bare imperative).
#: The wrapper is recognised here; the "<cost>" clause itself is a small
#: closed vocabulary (`additional_cost_dict`) — anything outside it leaves
#: the whole line unclaimed (fail-closed), never a guessed/partial cost.
ADDITIONAL_COST_LINE_RE = re.compile(
    r"^as an additional cost to cast this spell,\s*(?P<cost>.+?)\.?\s*$", re.IGNORECASE
)
#: Bite Down on Crime — an optional collect-evidence additional cost followed
#: by the spell's own conditional discount.  These are two distinct ability
#: records: the cost must be offered during casting, while the static
#: reduction must be visible before mana is paid (RULE 601.2f).
COLLECT_EVIDENCE_COST_REDUCTION_RE = re.compile(
    r"^as an additional cost to cast this spell,\s*you may collect evidence (?P<evidence>\d+)\.\s*"
    r"this spell costs \{(?P<reduction>\d+)\} less to cast if evidence was collected\.?$",
    re.IGNORECASE,
)
_ADDITIONAL_COST_SACRIFICE_RE = re.compile(
    r"^sacrifice an?\s+(creature|artifact|land)$", re.IGNORECASE
)
_ADDITIONAL_COST_SACRIFICE_OR_MANA_RE = re.compile(
    r"^sacrifice a (?P<what>creature) or pay (?P<mana>(?:\{[^{}]+\})+)$",
    re.IGNORECASE,
)
#: "sacrifice an artifact or creature" (RULE 601.2b — Deadly Dispute/Costly
#: Plunder-shaped, the single most-repeated compound sacrifice cost in the
#: cache) — the two-way sibling of `misc_mixin._matches_permanent_type`'s
#: existing ``"creature_artifact_or_land"``/``"creature_or_planeswalker"``
#: sentinels, same idiom: a fixed compound word `costs.parse_activation_cost`
#: reads verbatim (never a general N-way list — RAW only prints a handful of
#: real combinations, so each earns its own sentinel rather than a generic
#: parser).
_ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE = re.compile(
    r"^sacrifice an? (?:artifact or creature|creature or artifact)$", re.IGNORECASE
)
#: PAR-225 / RULE 601.2b: "return a `<type>` you control to its owner's hand" as a mandatory additional cast cost
#: (Familiar's Ruse, Deprive, Devour in Flames, Disappearing Act, Fear of Isolation). A fixed main-type word only: a
#: colour / subtype restriction or a count (RULE 601.2b "return X Swamps") has no picker shape and stays unclaimed.
_ADDITIONAL_COST_RETURN_RE = re.compile(
    r"^return an? (?P<type>creature|land|permanent|artifact|enchantment) you control to its owner's hand$", re.IGNORECASE
)
_ADDITIONAL_COST_DISCARD_RE = re.compile(r"^discard\s+(?P<n>an?|x)\s+cards?$", re.IGNORECASE)
#: RULE 601.2b: "exile N [<type>] cards from your graveyard" as an
#: additional cast cost (Cobbled Lancer / Headless Skaab / Makeshift Mauler
#: — "exile a creature card …"; Abhorrent Oculus — "exile 6 cards …"). A
#: hard gate, no "or pay {N}" alternative here. ``type`` is a single main-
#: type word ("creature" is the only one real cards print in this shape).
_ADDITIONAL_COST_EXILE_GRAVEYARD_RE = re.compile(
    r"^exile\s+(?P<n>an?|x|\d+)\s+(?P<type>creature\s+|instant or sorcery\s+)?cards?\s+from your graveyard$",
    re.IGNORECASE,
)
_ADDITIONAL_COST_PAY_LIFE_RE = re.compile(r"^pay\s+(x|\d+)\s+life$", re.IGNORECASE)
#: "pay N life or pay `<cost>`" (Redirect Lightning) — RULE 601.2b's
#: alternative-additional-cost shape has no `AbilitySpec.additional_cost`
#: representation yet (that field is a single fixed cost, never a
#: player-facing choice between two). **Documented simplification**: only
#: the life-payment alternative is modeled (`{"pay_life": N}`), the same
#: idiom Force of Will's dropped pitch-cost alternative uses elsewhere in
#: this codebase — a real card here always ends up paying the life, never
#: offered the cheaper mana option.
_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE = re.compile(
    r"^pay\s+(x|\d+)\s+life or pay\s+\{[^}]+\}$", re.IGNORECASE
)
#: RULE 701.4a (Behold, PAR-29 — Tarkir: Dragonstorm): "behold a `<type>`
#: [or pay {N}]" as an additional cast cost (Caustic Exhale/Lys Alana
#: Dignitary/Silvergill Mentor/Kinsbaile Aspirant). The type word is a
#: creature type for every real card. **Documented simplification**: the
#: "or pay {N}" mana alternative is dropped (same idiom as
#: `_ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE` just above) — a spell is beheld
#: for if a matching permanent/hand card exists and casts regardless. A
#: trailing "and exile it." (the Champion cycle) deliberately fails this
#: anchor — it is `_ADDITIONAL_COST_BEHOLD_EXILE_RE`'s shape instead.
_ADDITIONAL_COST_BEHOLD_RE = re.compile(
    r"^behold an?\s+(?P<q>[a-z][a-z'-]*)(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: RULE 701.4a (Behold, PAR-30 — the Lorwyn "Champion" cycle reflavoured,
#: Champion of the Clachan/Path/Weird, Champions of the Perfect/Shoal):
#: "behold a `<type>` and exile it." as a *mandatory* additional cast cost
#: (no "or pay {N}" alternative — unlike `_ADDITIONAL_COST_BEHOLD_RE`, this
#: one blocks casting when unpayable). The exiled card is given back by the
#: card's own "when ~ leaves the battlefield, return the exiled card to its
#: owner's hand" trigger.
_ADDITIONAL_COST_BEHOLD_EXILE_RE = re.compile(
    r"^behold an?\s+(?P<q>[a-z][a-z'-]*)\s+and exile it$", re.IGNORECASE
)
#: RULE 701.68 (Blight, PAR-29 — Bloomburrow): "blight N [or pay {M}]" as
#: an additional cast cost (Bogslither's Embrace/Wild Unraveling). Same
#: documented "or pay {M}" drop as `_ADDITIONAL_COST_BEHOLD_RE`.
_ADDITIONAL_COST_BLIGHT_RE = re.compile(
    r"^blight\s+(?P<n>\d+)(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: ENG-32 (RULE 701.67, Avatar: TLA): "as an additional cost to cast this
#: spell, waterbend {N}." — a fixed {N} generic mana cost folded into the
#: spell's total (`casting_mixin.effective_cast_cost`). PAR-30: "waterbend
#: {X}" (Crashing Wave / Foggy Swamp Visions / Waterbender's Restoration)
#: now matches too — `{"waterbend": "x"}`, folded with the announced X
#: (`legal_actions` surfaces `has_x` off a mandatory variable additional
#: cost, `effective_cast_cost` folds `mana.with_x(x)`, `x_paid` carries it
#: to the body). "you may waterbend {N}" (a Kicker-shaped *optional*
#: additional cost) is `_ADDITIONAL_COST_OPTIONAL_RE`'s job, not this one.
_ADDITIONAL_COST_WATERBEND_RE = re.compile(
    r"^waterbend\s+\{(?P<n>\d+|x)\}$", re.IGNORECASE
)
#: RULE 701.61 (Forage, PAR-29 — Bloomburrow): "as an additional cost to
#: cast this spell, forage [or pay {M}]." (Feed the Cycle). Same documented
#: "or pay {M}" drop as `_ADDITIONAL_COST_BEHOLD_RE`/`_BLIGHT_RE` — the
#: spell forages if it can and casts regardless. `ActivationCost.forage`
#: (already charged by `_can`/`_pay_activation_cost`).
_ADDITIONAL_COST_FORAGE_RE = re.compile(
    r"^forage(?:\s+or pay\s+(?:\{[^}]+\})+)?$", re.IGNORECASE
)
#: PAR-30 / RULE 601.2b: the *optional* additional-cost prefix — "as an
#: additional cost to cast this spell, **you may** <cost>." (Katara Seeking
#: Revenge, Ruinous Waterbending, Burning Curiosity, Graven Archfiend, …).
#: Stripped before `additional_cost_dict`, and flagged onto
#: `AbilitySpec.additional_cost_optional` so the cost is offered as its own
#: cast variant (`game/engine/legal_actions_mixin._offer_cast`) and its
#: being paid recorded on `GameObject.additional_cost_paid`.
ADDITIONAL_COST_OPTIONAL_PREFIX_RE = re.compile(r"^you may\s+(?P<cost>.+)$", re.IGNORECASE)

#: RULE 601.2f-adjacent: "If you control a commander, you may cast this
#: spell without paying its mana cost." (Deadly Rollick/Deflecting Swat/
#: Fierce Guardianship-shaped) — a standalone line, own oracle-text sentence
#: from the spell's actual effect, mirroring the additional-cost line's
#: wrapper shape above (recognized whole, produces its own spec carrying no
#: effects). Only "control a commander" is recognized today — any other
#: condition on this exact template leaves the whole line unclaimed
#: (fail-closed), matching `AbilitySpec.free_cast_condition`'s whitelist.
FREE_CAST_IF_COMMANDER_RE = re.compile(
    r"^if you control a commander,\s*you may cast this spell without paying its mana cost\.?\s*$",
    re.IGNORECASE,
)
FREE_CAST_IF_ANOTHER_COLOR_RE = re.compile(
    r"^if you'?ve cast another (?P<color>white|blue|black|red|green) spell this turn,\s*"
    r"you may cast this spell without paying its mana cost\.?\s*$", re.IGNORECASE,
)
CAST_ONLY_IF_ANOTHER_COLOR_RE = re.compile(
    r"^cast this spell only if you'?ve cast another "
    r"(?P<color>white|blue|black|red|green) spell this turn\.?$", re.IGNORECASE,
)

#: "If an opponent cast three or more spells this turn, you may pay {0}
#: rather than pay this spell's mana cost." (Mindbreak Trap-shaped RULE
#: 702's "Trap" template, MEC-12) — a differently-worded but functionally
#: identical `free_cast_condition` alternative (paying ``{0}`` is paying
#: nothing), gated by a *board-count* condition instead of
#: `FREE_CAST_IF_COMMANDER_RE`'s boolean one — `AbilitySpec.
#: free_cast_condition`'s ``opponent_spells_cast_this_turn_at_least`` key.
FREE_CAST_IF_OPPONENT_SPELLS_RE = re.compile(
    r"^if an opponent cast (?P<n>\d+) or more spells this turn,\s*"
    r"you may pay \{0\} rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: "If an opponent controls a Forest and you control an Island, you may
#: cast this spell without paying its mana cost." (Submerge — the one real
#: card printing this exact compound board-state gate) — a fixed named
#: condition rather than a generic "opponent controls type X and you
#: control type Y" combinator, same idiom as `FREE_CAST_IF_COMMANDER_RE`'s
#: own single boolean flag (`AbilitySpec.free_cast_condition`'s
#: ``opponent_controls_forest_and_you_control_island`` key).
FREE_CAST_IF_OPPONENT_FOREST_YOU_ISLAND_RE = re.compile(
    r"^if an opponent controls a forest and you control an island,\s*"
    r"you may cast this spell without paying its mana cost\.?\s*$",
    re.IGNORECASE,
)

#: RULE 702.8b: "You may cast this spell as though it had flash if it
#: targets a commander." (Timely Ward-shaped, MEC-7) — the same standalone-
#: line wrapper shape as `FREE_CAST_IF_COMMANDER_RE` just above, but a
#: *timing* permission (`AbilitySpec.conditional_flash`) rather than a
#: *cost* one (`free_cast_condition`). Only "targets a commander" is
#: recognized today, matching `ALLOWED_CAST_CONDITION_KEYS`'s whitelist.
CONDITIONAL_FLASH_IF_TARGETS_COMMANDER_RE = re.compile(
    r"^you may cast this spell as though it had flash if it targets a commander\.?\s*$",
    re.IGNORECASE,
)
#: PAR-30, Molten Exhale: "You may cast this spell as though it had flash if
#: you behold a `<type>` as an additional cost to cast it." →
#: `conditional_flash={"controller_beholds_subtype": "<type>"}` (the caster
#: could behold one). The type word is a creature type for every real card.
CONDITIONAL_FLASH_IF_BEHOLD_RE = re.compile(
    r"^you may cast this spell as though it had flash if you behold an?\s+"
    r"(?P<q>[a-z][a-z'-]*) as an additional cost to cast it\.?\s*$",
    re.IGNORECASE,
)
#: PAR-226, RULE 702.8b: the board-state forms of a spell's own timing permission --
#: "You may cast this spell as though it had flash if you control a Human." / "If you control a creature with power
#: 4 or greater, you may cast this spell as though it had flash." / "As long as you control a Spirit, you may cast ..."
#: / "This spell has flash as long as you control a Merfolk." The condition text goes through `static_condition`
#: (an unparsed condition leaves the line unclaimed) and rides in `conditional_flash["active_if"]`.
CONDITIONAL_FLASH_IF_TARGETS_OWN_PERMANENT_RE = re.compile(
    r"^you may cast this spell as though it had flash if it targets a permanent you control\.?\s*$",
    re.IGNORECASE,
)
CONDITIONAL_FLASH_STATE_RES: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^you may cast this spell as though it had flash if (?P<cond>.+?)\.?$",
        r"^(?:if|as long as) (?P<cond>.+?), you may cast this spell as though it had flash\.?$",
        r"^(?:this spell|~) has flash as long as (?P<cond>.+?)\.?$",
    )
)
#: PAR-35's deliberately narrow Mercadian-Masques combat window.
DECLARE_ATTACKERS_IF_ATTACKED_RE = re.compile(
    r"^cast this spell only during the declare attackers step and only if you've been "
    r"attacked this step\.?$", re.IGNORECASE,
)
#: RULE 506.8b-c: combat-local points plus explicit turn ownership.
COMBAT_CAST_ONLY_RE = re.compile(
    r"^cast this spell only (?P<window>during combat|during the declare blockers step)"
    r"(?: on (?P<turn>your|an opponent's) turn)?"
    r"(?: (?P<point>before|after) blockers are declared)?\.?$", re.IGNORECASE,
)
BEFORE_BLOCKERS_CAST_ONLY_RE = re.compile(
    r"^cast this spell only (?:before combat or during combat )?before blockers are declared\.?$",
    re.IGNORECASE,
)

#: PAR-35: paid Flash, where the mana applies only outside a normal sorcery
#: window (enforced by ``GameEngine.effective_cast_cost``).
CONDITIONAL_FLASH_FOR_EXTRA_MANA_RE = re.compile(
    r"^you may cast this spell as though it had flash if you pay (?P<cost>(?:\{[^{}]+\})+) "
    r"more to cast it\.?$", re.IGNORECASE,
)
#: PAR-35's common Necromancy-style rider.  The delayed trigger primitives
#: already exist; this gives their exact recurring wording a parser route.
FLASH_THEN_CLEANUP_SAC_RE = re.compile(
    r"^you may cast this spell as though it had flash\. if you cast it any time a sorcery "
    r"couldn't have been cast, the controller of the permanent it becomes sacrifices it at "
    r"the beginning of the next cleanup step\.?$", re.IGNORECASE,
)

#: "Strive — This spell costs `<cost>` more to cast for each target beyond
#: the first." (MEC-4) — not a RULE 702 keyword (no CR entry defines it, see
#: `AbilitySpec.strive_cost`'s docstring), so it's recognized as its own
#: standalone-line template here rather than through `keywords.py`'s
#: numbered catalogue. ``<cost>`` is a run of brace-delimited symbols, same
#: shape `_STRIVE_COST_RE` (`parser/oracle/spec.py`) validates.
STRIVE_LINE_RE = re.compile(
    # `normalize._strip_unregistered_keyword_labels` removes the "Strive —"
    # label before this runs (Scryfall lists "Strive" in the card's
    # ``keywords`` but it's not a registered RULE 701/702 keyword), so the
    # prefix is optional here — the sentence is unambiguous on its own.
    r"^(?:strive\s*[—-]\s*)?this spell costs (?P<cost>(?:\{[^{}]+\})+) more to cast "
    r"for each target beyond the first\.?\s*$",
    re.IGNORECASE,
)

#: RULE 118.9's "pitch" alternative cost: "You may exile a `<color>` card
#: from your hand rather than pay this spell's mana cost." (MEC-15 — the
#: Force of Will cycle/Misdirection/Pyrokinesis/Snapback/Unmask-shaped
#: family, previously only reachable one card at a time via `ability_
#: catalogue.py`'s `alt_cost={"exile_hand_card_color": …}` — this is the
#: same shape's first oracle-text route). Same standalone-line treatment as
#: every other `alt_cost`/`free_cast_condition` row above.
ALT_COST_EXILE_HAND_COLOR_RE = re.compile(
    rf"^you may exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: RULE 118.9's other three "pitch"-family shapes (MEC-12's own diagnosed
#: remaining gap, past the "exile a colored card" one above): "You may
#: sacrifice a `<permanent type>` rather than pay this spell's mana cost."
#: (Downhill Charge's "a Mountain") — a bare subtype word, `AbilitySpec.
#: alt_cost`'s ``sacrifice`` key (reused verbatim from the ordinary-cost
#: field, `_matches_sacrifice_type`'s own subtype fallback now recognizes
#: it rather than the old "any permanent" catch-all).
ALT_COST_SACRIFICE_TYPE_RE = re.compile(
    r"^you may sacrifice an? (?P<what>[a-z]+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "…a nontoken `<color>` creature…" (Flare of Denial) — a qualifier beyond
#: a bare type word, so it's a `combat.matches_object_filter`-shaped dict
#: (``sacrifice_filter``) instead of the plain ``sacrifice`` word above.
ALT_COST_SACRIFICE_NONTOKEN_COLOR_CREATURE_RE = re.compile(
    rf"^you may sacrifice a nontoken (?P<color>{COLOR_WORD_ALT}) creature "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may return `<N>` `<Type>`s you control to their owner's hand rather than pay this spell's mana cost." (Gush's
#: two Islands, Thwart's three) -- `AbilitySpec.alt_cost`'s ``return_to_hand_count`` key, the count-generalized
#: sibling of the singular ``return_to_hand`` below. The normalizer has already folded the count word to a digit.
ALT_COST_RETURN_TWO_RE = re.compile(
    r"^you may return (?P<count>\d+) (?P<subtype>[a-z]+)s you control to their owner'?s hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may return an `<Type>` you control to its owner's hand rather than pay this spell's mana cost." (Daze, Tidal
#: Bore) -- the singular form, `AbilitySpec.alt_cost`'s ``return_to_hand`` key (a subtype word).
ALT_COST_RETURN_ONE_RE = re.compile(
    r"^you may return an? (?P<subtype>[a-z]+) you control to its owner'?s hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If you control a `<land type>`, you may pay `<N>` life rather than pay
#: this spell's mana cost." (Snuff Out) — a *board-state-conditioned*
#: pay-life, unlike the already-shipped unconditional Phyrexian-mana-style
#: `pay_life`: `AbilitySpec.alt_cost`'s own ``condition`` key (already
#: used for ``not_your_turn``) gains `condition_query.
#: free_cast_condition_holds`'s new ``control_land_type`` kind.
ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may pay (?P<n>\d+) life "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: RULE 118.9's plain, unconditional form — "You may pay `<mana>` rather
#: than pay this spell's mana cost." (the Bringer cycle — five-color
#: {W}{U}{B}{R}{G} — among others) is a genuinely *different fixed cost*,
#: not "no cost" (`free_cast_condition`'s job) — `AbilitySpec.alt_cost`'s
#: own ``mana`` key, newly wired into `GameEngine._can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost` (previously unread: `alt_cost=True` always routed
#: through `RulesEngine.cast_without_paying`, which skips mana entirely).
#: The generic unconditional form remains immediately below; the Raid form
#: now has its own earlier, condition-preserving rule.
#: "Raid — If you attacked this turn, you may pay `<mana>` rather than pay
#: this spell's mana cost." (Admiral's Order) — declaration history, not a
#: live attacker count: the condition remains true after combat ends.
ALT_COST_PAY_MANA_IF_YOU_ATTACKED_RE = re.compile(
    r"^if you attacked this turn, you may pay (?P<mana>(?:\{[^{}]+\})+) "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

ALT_COST_PAY_MANA_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-19: "If `<N>` or more creatures are attacking, you may pay `<cost>`
#: rather than pay this spell's mana cost." (Lethargy Trap/Arrow Volley
#: Trap — RULE 702's "Trap" template) — a board-*count* gate on the plain
#: mana-payment alt_cost above, the combat-count sibling of
#: `ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE`'s land-type gate on a life
#: payment; shares that row's ``condition`` key idiom
#: (`AbilitySpec.alt_cost`'s new ``creatures_attacking_at_least``).
ALT_COST_PAY_MANA_IF_ATTACKING_RE = re.compile(
    r"^if (?P<n>\d+) or more creatures are attacking, you may pay "
    r"(?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-283: the general Trap form -- "If <condition>, you may pay <cost> rather than pay this spell's mana cost." -- whose
#: condition is read by the shared `static_condition` table (Archive/Baloth Cage/Lavaball/Needlebite/Nemesis/Ricochet ... Trap),
#: after the closed rows above have declined it.
ALT_COST_PAY_MANA_IF_CONDITION_RE = re.compile(
    r"^if (?P<cond>.+?), you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-283: "If it's your turn, you may sacrifice a Mountain rather than pay this spell's mana cost." (Mine Collapse):
#: `ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE`'s sibling with the turn gate (`free_cast_condition`'s ``your_turn`` key).
ALT_COST_SACRIFICE_IF_YOUR_TURN_RE = re.compile(
    r"^if it'?s your turn, you may sacrifice an? (?P<what>[a-z]+) rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: PAR-283: the trailing-condition spelling -- "You may pay {B} rather than pay this spell's mana cost if there are
#: thirteen or more creatures on the battlefield." (Blasphemous Edict); the condition is the shared `static_condition`'s.
ALT_COST_PAY_MANA_TRAILING_IF_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost if (?P<cond>.+?)\.?\s*$",
    re.IGNORECASE,
)

#: Snuff Out's own sibling shapes (MEC-12's "broader gaps" — the compound
#: "board condition gates a non-mana alt_cost" family, same ``condition``
#: key `ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE` already carries, just paired
#: with ``sacrifice``/``tap_others`` instead of ``pay_life``). "If you
#: control a `<land type>`, you may sacrifice a creature rather than pay
#: this spell's mana cost." (Dark Triumph).
ALT_COST_SACRIFICE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may sacrifice an? (?P<what>[a-z]+) "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If you control a `<land type>`, you may tap an untapped creature you
#: control rather than pay this spell's mana cost." (Angelic Favor) —
#: `AbilitySpec.alt_cost`'s ``tap_others`` key (RULE 602.1's "Tap N
#: untapped `<type>`s you control", reused verbatim from the ordinary-cost
#: field — `GameEngine._tap_others_pool` now also matches a bare main type
#: like "creature", not just a subtype).
ALT_COST_TAP_CREATURE_IF_CONTROL_LAND_RE = re.compile(
    r"^if you control an? (?P<land>[a-z]+), you may tap an? untapped creature you control "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may pay `<cost>` and return a basic land you control to its owner's
#: hand rather than pay this spell's mana cost." (the Borderpost cycle) —
#: ``mana``+``return_to_hand_count`` combined in one `alt_cost` dict; both
#: keys are independently checked/paid already (`_can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost`), so no new payment logic, just the new
#: ``"basic land"`` qualifier `GameEngine._return_to_hand_count_pool` reads.
ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) and return a basic land you control "
    r"to its owner'?s hand rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may sacrifice `<N>` `<land type>`s rather than pay this spell's
#: mana cost." (the Odyssey/Judgment "Mountain-cycle"-shaped family) —
#: `AbilitySpec.alt_cost`'s ``sacrifice_count`` key, the count-generalized
#: sibling of the already-shipped singular ``sacrifice``.
ALT_COST_SACRIFICE_COUNT_RE = re.compile(
    # An optional colour word before the type ("three black creatures", Delraich) is the cost's permanent phrase
    # `<colour>_<type>` (`continuous.matches_permanent_word`); an optional "pay N life and" leads Demon of Death's Gate.
    rf"^you may (?:pay (?P<life>\d+) life and )?sacrifice (?P<n>\d+) (?P<color>(?:{COLOR_WORD_ALT}) )?(?P<subtype>[a-z]+)s "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)

#: PAR-19's own "pitch" residue, all three shapes real cards print past the
#: singular `ALT_COST_EXILE_HAND_COLOR_RE`/plain
#: `ALT_COST_PAY_LIFE_IF_CONTROL_LAND_RE` rows above:
#:
#: "You may exile 2 `<color>` cards from your hand rather than pay this
#: spell's mana cost." (Soul Spike/Sunscour/Allosaurus Rider/Commandeer/
#: Fury of the Horde-shaped) — `AbilitySpec.alt_cost`'s new
#: ``exile_hand_card_color_count`` key, the counted sibling of the already-
#: shipped singular ``exile_hand_card_color`` (same singular/counted split
#: `return_to_hand`/`return_to_hand_count` and `sacrifice`/`sacrifice_count`
#: already use twice in this family). Only "2" is a real cache-wide
#: printing today, same "widen the alternation, not the shape" note
#: `ALT_COST_RETURN_TWO_RE` carries.
ALT_COST_EXILE_HAND_COLOR_COUNT_RE = re.compile(
    rf"^you may exile 2 (?P<color>{COLOR_WORD_ALT}) cards from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "If it's not your turn, you may exile a `<color>` card from your hand
#: rather than pay this spell's mana cost." (Force of Virtue/Force of
#: Despair/Force of Rage — the wider Force cycle past the four MEC-15
#: hand-authored ones) — the singular ``exile_hand_card_color`` gated by
#: the same ``not_your_turn`` `condition` key Force of Negation/Vigor's own
#: hand-authored entries already use, now reachable straight from oracle
#: text instead of needing a catalogue entry per card.
ALT_COST_EXILE_HAND_COLOR_IF_NOT_YOUR_TURN_RE = re.compile(
    rf"^if it'?s not your turn, you may exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may pay 1 life and exile a `<color>` card from your hand rather
#: than pay this spell's mana cost." (Contagion/Force of Rowan) — ``pay_life``
#: + ``exile_hand_card_color`` combined in one `alt_cost` dict; both keys
#: are already independently checked/paid (`_can_pay_alt_cast_cost`/
#: `_pay_alt_cast_cost`), so no new payment logic, the same "combine two
#: already-wired keys" idiom `ALT_COST_PAY_MANA_AND_RETURN_BASIC_LAND_RE`
#: uses for ``mana``+``return_to_hand_count``.
ALT_COST_PAY_LIFE_AND_EXILE_HAND_COLOR_RE = re.compile(
    rf"^you may pay (?P<n>\d+) life and exile an? (?P<color>{COLOR_WORD_ALT}) card from your hand "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: "You may discard a `<basic land type>` card rather than pay this spell's
#: mana cost." (Abolish/Flameshot/Outbreak/Snag — the "Pitch" basic-land
#: cycle) — `AbilitySpec.alt_cost`'s new ``discard_land_type`` key, the
#: discard-zone sibling of ``exile_hand_card_color``.
ALT_COST_DISCARD_LAND_TYPE_RE = re.compile(
    r"^you may discard an? (?P<land>plains|island|swamp|mountain|forest) card "
    r"rather than pay this spell'?s mana cost\.?\s*$",
    re.IGNORECASE,
)
#: PAR-19's own genuinely new primitive: "You may pay `<cost>` rather than
#: pay this spell's mana cost. Spend only mana produced by Treasures to
#: cast it this way." (Security Rhox/A-Security Rhox) — the plain
#: unconditional mana alt-cost (`ALT_COST_PAY_MANA_RE`'s own shape) plus a
#: *source-kind* restriction on that specific payment, both sentences on
#: one oracle-text line so one row claims the whole thing (mirrors
#: `ALT_COST_PAY_MANA_IF_ATTACKING_RE`'s "two sentences, one row" idiom).
#: `AbilitySpec.alt_cost`'s new ``mana_source_kind`` key
#: (`ManaPool.pool_by_source`, `game/mana_abilities.MANA_SOURCE_KINDS`) —
#: real cards print only "Treasures" here.
ALT_COST_PAY_MANA_IF_TREASURE_RE = re.compile(
    r"^you may pay (?P<mana>(?:\{[^{}]+\})+) rather than pay this spell'?s mana cost\. "
    r"spend only mana produced by (?P<kind>treasures) to cast it this way\.?\s*$",
    re.IGNORECASE,
)
#: RULE 605.3a's *other* direction, as the spell's own standing restriction
#: rather than an alternative payment at all — "Spend only mana produced by
#: basic lands/creatures to cast this spell." (Imperiosaur/Myr Superion).
#: `AbilitySpec.cast_mana_source_restriction`, not `alt_cost` — these two
#: cards print no alternative cost whatsoever, just a qualifier on their
#: ordinary printed mana cost.
CAST_MANA_SOURCE_RESTRICTION_RE = re.compile(
    r"^spend only mana produced by (?P<kind>basic lands|creatures) to cast this spell\.?\s*$",
    re.IGNORECASE,
)


#: "`<cost>` or pay {N}" / "pay {N} or `<cost>`" (RULE 601.2b — Lightning Axe "discard a card or pay {5}", Annihilating
#: Glare "pay {4} or sacrifice an artifact or creature", Soaring Stoneglider "exile 2 cards from your graveyard or pay
#: {1}{W}", Daring Buccaneer "reveal a Pirate card from your hand or pay {2}"): the caster picks one branch when
#: casting — the mana by default, the other cost as the `pay_additional` variant (`additional_cost["or_mana"]`).
_ADDITIONAL_COST_OR_MANA_RE = re.compile(
    r"^(?:(?P<cost_first>.+?) or pay (?P<mana_first>(?:\{[^{}]+\})+)"
    r"|pay (?P<mana_second>(?:\{[^{}]+\})+) or (?P<cost_second>.+))$",
    re.IGNORECASE,
)
_OR_MANA_SACRIFICE_PHRASES: dict[str, str] = {
    "creature": "creature", "artifact": "artifact", "land": "land",
    "artifact or creature": "artifact_or_creature", "creature or artifact": "artifact_or_creature",
    "creature or planeswalker": "creature_or_planeswalker", "creature or enchantment": "creature_or_enchantment",
    "creature or land": "creature_or_land", "permanent": "permanent",
}
_ADDITIONAL_COST_TAP_UNTAPPED_RE = re.compile(r"^tap an untapped (?P<what>artifact|creature|land) you control$", re.IGNORECASE)
_ADDITIONAL_COST_OR_MANA_SACRIFICE_RE = re.compile(r"^sacrifice an? (?P<what>.+)$", re.IGNORECASE)
_ADDITIONAL_COST_PAY_N_LIFE_RE = re.compile(r"^pay (?P<n>\d+) life$", re.IGNORECASE)
_ADDITIONAL_COST_REVEAL_FROM_HAND_RE = re.compile(
    r"^reveal an? (?P<type>[a-z]+) card from your hand$", re.IGNORECASE
)


#: RULE 701.17 / 601.2b: "sacrifice a <qualified permanent>" as a cast cost (Fatal Grudge's nonland permanent,
#: Ultimate Nullification's legendary creature, Savage Order's "creature with power 4 or greater") -- the shared
#: `sacrifice_clause` grammar (adjectives, types, "with power N or greater"), one object, read in full: any word outside
#: its vocabulary leaves the line unclaimed instead of charging a cheaper cost than printed. "modified creature" is
#: RULE 700.9's state word, read by the engine's own `modified_creature` sacrifice type.


def _qualified_sacrifice_word(text: str, phrase: str) -> Optional[str]:
    if phrase == "modified creature":
        return MODIFIED_CREATURE_WORD
    clause = read_sacrifice_clause(text)
    if clause is None or clause.end != len(text) or len(clause.items) != 1:
        return None
    (item,) = clause.items
    if item.kind != "object" or item.count != 1 or item.word.startswith("other_"):
        return None
    # The spec validates the word against the same closed vocabulary; a subtype word ("a goblin") is outside it.
    return item.word if additional_cost_sacrifice_word_ok(item.word) else None


def _or_mana_inner_cost(text: str) -> Optional[dict[str, Any]]:
    """The non-mana half of an "… or pay {N}" additional cost — a closed vocabulary of single costs."""
    text = text.strip().lower()
    if re.fullmatch(r"discard a card", text):
        return {"discard": 1}
    life = _ADDITIONAL_COST_PAY_N_LIFE_RE.match(text)
    if life is not None:
        return {"pay_life": int(life.group("n"))}
    sac = _ADDITIONAL_COST_OR_MANA_SACRIFICE_RE.match(text)
    if sac is not None:
        phrase = sac.group("what").strip()
        word = _OR_MANA_SACRIFICE_PHRASES.get(phrase) or _qualified_sacrifice_word(text, phrase)
        return None if word is None else {"sacrifice": word}
    reveal = _ADDITIONAL_COST_REVEAL_FROM_HAND_RE.match(text)
    if reveal is not None:
        return {"reveal_from_hand": reveal.group("type")}
    tap = _ADDITIONAL_COST_TAP_UNTAPPED_RE.match(text)
    if tap is not None:
        return {"tap_others": [1, tap.group("what")]}
    exile_gy = _ADDITIONAL_COST_EXILE_GRAVEYARD_RE.match(text)
    if exile_gy is not None and not exile_gy.group("type") and exile_gy.group("n").isdigit():
        return {"exile_from_graveyard": {"count": int(exile_gy.group("n"))}}
    return None


def additional_cost_dict(text: str) -> Optional[dict[str, Any]]:
    """One additional-cost clause's closed vocabulary → its dict, or ``None``.

    Matches `AbilitySpec.additional_cost`'s shape exactly: ``{"sacrifice":
    "creature"|"artifact"|"land"|"artifact_or_creature"}``, ``{"discard": 1|"x"}``, or
    ``{"pay_life": N|"x"}``, or ``{"collect_evidence": N}``.
    """
    text = text.strip().lower()
    random_discard = re.fullmatch(r"discard (an?|x|\d+) cards? at random", text)
    if random_discard:
        n = random_discard[1]
        return {"discard": {"count": "x" if n == "x" else 1 if n in ("a", "an") else int(n), "random": True}}
    fraction = re.fullmatch(r"sacrifice half the lands you control, rounded (up|down)", text)
    if fraction:
        return {"sacrifice_fraction": {"divisor": 2, "round_up": fraction[1] == "up", "what": "land"}}
    returned = _ADDITIONAL_COST_RETURN_RE.match(text)
    if returned is not None:
        return {"return_pick": returned.group("type").lower()}
    collect_evidence = re.fullmatch(r"collect evidence (?P<n>\d+)", text)
    if collect_evidence is not None:
        return {"collect_evidence": int(collect_evidence.group("n"))}
    sac_or_mana = _ADDITIONAL_COST_SACRIFICE_OR_MANA_RE.match(text)
    if sac_or_mana is not None:
        return {"sacrifice_or_mana": {
            "sacrifice": sac_or_mana.group("what"), "mana": sac_or_mana.group("mana"),
        }}
    or_mana = _ADDITIONAL_COST_OR_MANA_RE.match(text)
    if or_mana is not None:
        inner = _or_mana_inner_cost(or_mana.group("cost_first") or or_mana.group("cost_second"))
        if inner is not None:
            return {"or_mana": {"cost": inner, "mana": or_mana.group("mana_first") or or_mana.group("mana_second")}}
    if _ADDITIONAL_COST_SACRIFICE_ARTIFACT_OR_CREATURE_RE.match(text):
        return {"sacrifice": "artifact_or_creature"}
    sac = _ADDITIONAL_COST_SACRIFICE_RE.match(text)
    if sac is not None:
        return {"sacrifice": sac.group(1)}
    # "sacrifice a creature or enchantment" (Final Flare) — a single compound-type sacrifice, tried before the
    # "<A> or <B>" split below so its own " or " isn't read as a branch point.
    compound = _ADDITIONAL_COST_OR_MANA_SACRIFICE_RE.match(text)
    if compound is not None:
        inner = _or_mana_inner_cost(text)
        if inner is not None:
            return inner
    # "<cost A> or <cost B>" with no mana half (Bone Shards): the first " or " that leaves two valid single costs.
    for match in re.finditer(r" or ", text):
        first, second = _or_mana_inner_cost(text[:match.start()]), _or_mana_inner_cost(text[match.end():])
        if first is not None and second is not None:
            return {"either": [first, second]}
    discard = _ADDITIONAL_COST_DISCARD_RE.match(text)
    if discard:
        return {"discard": "x" if discard.group("n").lower() == "x" else 1}
    exile_gy = _ADDITIONAL_COST_EXILE_GRAVEYARD_RE.match(text)
    if exile_gy is not None:
        n = exile_gy.group("n").lower()
        # Single-key dict (RULE 601.2b `AbilitySpec.additional_cost` shape),
        # value structured as ``{"count", "type"?}``.
        value: dict[str, Any] = {"count": "x" if n == "x" else 1 if n in ("a", "an") else int(n)}
        if exile_gy.group("type"):
            # MEC-145 (Draconic Intervention): the either-type word `_graveyard_exile_cost_candidates` already splits.
            value["type"] = exile_gy.group("type").strip().replace(" ", "_")
        return {"exile_from_graveyard": value}
    life = _ADDITIONAL_COST_PAY_LIFE_RE.match(text)
    if life is not None:
        amount = life.group(1)
        return {"pay_life": "x" if amount.lower() == "x" else int(amount)}
    life_or_mana = _ADDITIONAL_COST_PAY_LIFE_OR_MANA_RE.match(text)
    if life_or_mana is not None:
        amount = life_or_mana.group(1)
        return {"pay_life": "x" if amount.lower() == "x" else int(amount)}
    beh_exile = _ADDITIONAL_COST_BEHOLD_EXILE_RE.match(text)
    if beh_exile is not None:
        return {"behold_exile": beh_exile.group("q").strip()}
    beh = _ADDITIONAL_COST_BEHOLD_RE.match(text)
    if beh is not None:
        return {"behold": beh.group("q").strip()}
    blt = _ADDITIONAL_COST_BLIGHT_RE.match(text)
    if blt is not None:
        return {"blight": int(blt.group("n"))}
    wtr = _ADDITIONAL_COST_WATERBEND_RE.match(text)
    if wtr is not None:
        n = wtr.group("n").lower()
        return {"waterbend": "x" if n == "x" else int(n)}
    if _ADDITIONAL_COST_FORAGE_RE.match(text):
        return {"forage": True}
    return None
