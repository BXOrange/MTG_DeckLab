"""Shared sub-grammars — the rule that stops the handler set exploding (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("Factor shared sub-grammars").
"deal 3 damage **to any target**" / "**to target creature**" / "**to target
player**" are *one* damage handler with a reusable TARGET matcher, not three
regexes. This module owns those reusable fragments so every handler shares
them: the TARGET phrase → an engine ``target_kind``, and NUMBER.

Pure regex + data — **no `game/` imports** (front-end security boundary).
The ``target_kind`` strings here mirror `game/targeting.ALLOWED_TARGET_KINDS`
(kept in sync by `tests/test_oracle_handlers.py`), so a handler can drop the
resolved kind straight into an effect's params.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Optional

#: The canonical vocabulary of nouns that name a permanent type/group,
#: singular, concrete types first then the two abstract/negated readings
#: ("permanent" itself, "nonland permanent") — the shared source every
#: consumer of this word list should build on, rather than each
#: independently re-declaring its own copy (docs/09 "Factor shared
#: sub-grammars"). Before this existed, the TARGET rows' own inline N-way
#: alternation below and `catalogue.handlers`'s `_MASS_DESTROY_NOUNS`/
#: `_MASS_DESTROY_NOUNS_SINGULAR` each hand-typed the same five-to-seven
#: words independently. `PERMANENT_TYPE_WORDS[:5]` is just the concrete
#: subset (no card is "targeted" as a bare "permanent" in an N-way list —
#: "target artifact, creature, or permanent" isn't real templating).
#: Deliberately doesn't fold in `_SPELL_TYPE_WORD`'s instant/sorcery pair or
#: `_GRAVEYARD_TYPE_WORD` in `catalogue.handlers` — both mix in spell-only
#: words this vocabulary has no opinion on, and migrating them is left for
#: a future incremental pass rather than attempted here.
PERMANENT_TYPE_WORDS: tuple[str, ...] = (
    "artifact", "creature", "enchantment", "land", "planeswalker",
    "nonland permanent", "permanent",
)
#: The five **printed card types** that name a permanent (RULE 300.1), as a
#: regex alternation for embedding inline — `PERMANENT_TYPE_WORDS[:5]`, i.e.
#: the concrete subset with the two abstract readings ("permanent", "nonland
#: permanent") dropped: those are not card types, so a row that emitted one
#: as a `card_type` selector would build a check that can never hold.
#: PAR-63: replaced the zero-use full-list `PERMANENT_TYPE_WORD` join — no
#: site ever wanted all seven words. Shared by `_TARGET_ROWS`' N-way
#: permanent row below and `static_handlers`' `is_card_type` condition row.
#: The one site that stays hand-rolled is `static_handlers`'
#: `_GRAVEYARD_LIBRARY_ENTRY_PROHIBITION_RE`: it wants four of these (no
#: "land") *plus* the non-card-type "nonland permanent" sentinel, a
#: different member set this alternation deliberately doesn't carry.
CARD_TYPE_WORD_ALT = "|".join(PERMANENT_TYPE_WORDS[:5])

#: RULE 105.1's five colours → their WUBRG symbol. **The** map: PAR-63 found
#: this exact five-entry dict declared eight times across five modules under
#: six different private names (`_COLOR_WORDS`, `_COLOR_LETTERS`,
#: `_COLOR_WORD_TO_LETTER`, `_COLOR_CONDITION_WORDS`, `_DEVOTION_COLOR_WORDS`),
#: which is the cross-module duplication `14_` S5 is about — the colour words
#: are a fact about Magic, not about any one handler family. Import it rather
#: than re-declaring; a variant that needs colourless spells it as
#: ``{**COLOR_LETTERS, "colorless": "C"}`` so the shared part stays shared.
COLOR_LETTERS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}




def pluralize_permanent_type(word: str) -> str:
    """A `PERMANENT_TYPE_WORDS` member, singular → its plural noun phrase.

    Every member pluralizes regularly ("+s" on the head noun — "nonland
    permanent" → "nonland permanents", not an irregular form), so this is a
    plain suffix rule rather than a lookup table.
    """
    return word + "s"


def all_permanent_type_selector(word: str) -> str:
    """A `PERMANENT_TYPE_WORDS` member (singular) → `game/effects/core.py`'s mass
    ``all_<type>`` selector name (`DestroyEffect`/`ExileEffect`'s
    ``selector`` param) — "nonland permanent" → ``"all_nonland_permanents"``.
    """
    return "all_" + pluralize_permanent_type(word).replace(" ", "_")


#: Ordered (regex-fragment, target_kind) rows. **Longest / most specific
#: first** — "target creature or player" must win over "target creature".
#: Each fragment is a self-contained alternative that the TARGET matcher ORs
#: together; the resolved ``kind`` is one of `targeting.ALLOWED_TARGET_KINDS`.
_TARGET_ROWS: list[tuple[str, str]] = [
    # RULE 115.4's "any **other** target" — every target legal for "any
    # target" except the ability's own source. It resolves to the same
    # ``any`` kind because `targeting.legal_targets`'s ``any`` branch
    # *already* excludes the source unconditionally, so the two phrasings
    # genuinely produce the same candidate list in this engine; the row
    # exists so the phrase is claimed at all rather than leaving a card
    # UNMODELED on wording alone. Above "any target" by the file's
    # longest-first convention.
    (r"any other target", "any"),
    (r"any target", "any"),
    (r"target creature or player", "any"),
    (r"target creature, player,? or planeswalker", "any"),
    # "target artifact, creature, planeswalker, or opponent" (PAR-2, Price
    # of Betrayal) — three permanent types unioned with a player. Genuinely
    # wider than ``any`` (which excludes non-creature artifacts, RULE
    # 115.9c), so it gets its own kind rather than collapsing onto ``any``
    # the way the two rows above do.
    (r"target artifact, creature, planeswalker,? or opponent",
     "artifact_creature_planeswalker_or_opponent"),
    # "target creature or planeswalker you don't control" (Bite Down) — the
    # controller-scoped sibling of the bare row just below, and above it by
    # the longest-first convention. PAR-127: both used to drop the
    # planeswalker half onto a ``creature`` kind (83 MODELED cards that could
    # never target a planeswalker); they now name the real two-type unions.
    (r"target creature or planeswalker (?:an opponent controls|you don't control)",
     "creature_or_planeswalker_you_dont_control"),
    (r"target creature or planeswalker", "creature_or_planeswalker"),
    (r"target attacking or blocking creature", "attacking_or_blocking_creature"),
    (r"target (?:attacking|blocking|tapped|untapped) creature", "creature"),
    (r"target werewolf creature", "werewolf_creature"),
    # An ATTACKS trigger's defending player is carried on the event; this is
    # narrower than an arbitrary opponent-controlled creature.
    (r"target creature defending player controls", "creature_defending_player_controls"),
    # "another target creature you control" (RULE 109.5 — the ability's own
    # source is excluded; Duke Ulder Ravengard, Blooming Stinger, Heavenly
    # Qilin). The engine's `other_creature_you_control` kind (targeting.py)
    # already does the exclusion + "you control" scoping + German label;
    # this row just routes the printed phrase there. Above the plain
    # "target creature you control" row so the longer phrase wins. The
    # "other" spelling is the "up to one **other** target creature you
    # control" form (`UP_TO_ONE` consumes the "up to one " prefix, leaving
    # "other target …" here) — Clandestine Meddler's suspect ETB.
    (r"(?:another|other) target creature you control", "other_creature_you_control"),
    # "target creature you control" (RULE 115/603.3c controller-restricted
    # pick, e.g. an Equipment's ETB "attach it to target creature you
    # control") — must sit above the bare "target creature" row below.
    (r"target creature you control", "creature_you_control"),
    # "target creature an opponent controls" / "…you don't control" — the
    # mirror image, onto the already-existing `creature_you_dont_control`
    # kind. Also above the bare "target creature" row.
    (r"target creature (?:an opponent controls|you don't control)", "creature_you_dont_control"),
    # "another target creature" (RULE 109.5 — The Scorpion God's "{1}{B}{R}:
    # Put a -1/-1 counter on another target creature") — "another" adds no
    # distinct engine kind (the bare `creature` pick already excludes the
    # ability's own source, RULE 115.6), exactly like the "another target
    # permanent" → `permanent` row further down.
    (r"(?:another|other) target creature", "creature"),
    (r"target creature", "creature"),
    # "target legendary permanent" (Minamo, School at Water's Edge) — a
    # supertype-filtered pick (RULE 205.4a), above the bare "target
    # permanent" row below so the longer phrase wins.
    (r"target legendary permanent", "legendary_permanent"),
    (r"(?:another |other )?target historic permanent you control", "historic_permanent_you_control"),
    # "target permanent an opponent controls" (Assassin's Trophy/
    # Geomancer's Gambit) — the controller-scoped sibling of the bare
    # "target permanent" row below, mirroring "target creature an opponent
    # controls" → `creature_you_dont_control` above; above that bare row so
    # the longer phrase wins.
    (r"target permanent (?:an opponent controls|you don't control)", "permanent_you_dont_control"),
    # "[another] target permanent you control" (North Pole Patrol's "{T}:
    # Untap another target permanent you control") — the you-control
    # sibling, onto the real `permanent_you_control` engine kind
    # (`targeting.legal_targets`); above the bare row so the longer phrase
    # wins. RULE 109.5's "another" adds no distinct kind (same call as the
    # "another target permanent" row below), it just narrows the offer off
    # the effect's own source.
    (r"(?:another |other )?target permanent you control", "permanent_you_control"),
    (r"target permanent", "permanent"),
    # "target artifact, enchantment, or land" (Acidic Slime) / "target
    # artifact, creature, or land" (Aftershock) / any other 2+ combination of
    # these five permanent-type nouns — the general N-way sibling of the
    # dedicated "target artifact or enchantment" row just below. All map to
    # the same broad ``"permanent"`` kind that row already does (RULE 115's
    # own precision loss this engine accepts here: `targeting.legal_targets`'s
    # ``"permanent"`` branch offers every permanent regardless of type, not
    # just the printed subset — the same simplification the 2-way row below
    # already ships).
    # PAR-128: the two-type unions the engine has a dedicated pool for sit
    # *above* the N-way row — it matches a two-word "X or Y" too, and used to
    # turn Naturalize's "target artifact or enchantment" into any permanent.
    (r"target artifact or enchantment", "artifact_or_enchantment"),
    (r"target (?:artifact or creature|creature or artifact)", "artifact_or_creature"),
    (rf"target (?:{CARD_TYPE_WORD_ALT})"
     rf"(?:, (?:{CARD_TYPE_WORD_ALT}))*"
     rf",? or (?:{CARD_TYPE_WORD_ALT})", "permanent"),
    # "target artifact or enchantment" (Archdruid's Charm) — the dedicated
    # union kind `targeting.legal_targets` already implements, rather than
    # the broad ``"permanent"`` the N-way row above deliberately keeps (RULE
    # 115.1c: the offered pool must actually match the printed noun phrase).
    (r"target artifact or enchantment", "artifact_or_enchantment"),
    # "target artifact"/"target enchantment" (Abrade, Naturalize) — single
    # printed permanent type, RULE 115.1c. Previously collapsed onto the
    # broad ``"permanent"`` kind (any permanent type, not just the printed
    # one) — a real rules bug, not just a precision loss: it let e.g. Abrade
    # "destroy target artifact" target a land. `targeting.legal_targets`
    # already has a dedicated ``"artifact"``/``"enchantment"`` branch for
    # this (the enter-as-copy candidate pool for Copy Artifact/Copy
    # Enchantment reuses it); this row just starts routing the bare single-
    # type phrase there too.
    (r"target artifact", "artifact"),
    (r"target enchantment", "enchantment"),
    # "target Forest" (Arbor Elf) — a specific basic land subtype, above
    # the bare "target land" row so the longer/more specific phrase wins.
    (r"target forest", "forest"),
    # "target creature or land you control" (PAR-124, Vengeant Earth's own
    # animate-either spell) — a type union scoped to the controller, above
    # the bare "target land you control" row so the longer phrase wins;
    # mirrors `creature_or_enchantment_you_control`'s own union shape
    # (targeting.py) but over creature/land instead of creature/enchantment.
    (r"target creature or land you control", "creature_or_land_you_control"),
    # "target land you control" / "target land an opponent controls" (PAR-29
    # — Political Trickery/Vedalken Plotter's own exchange-control targets)
    # — the controller-scoped pair, above the bare "target land" row so the
    # longer phrase wins, mirroring "target creature you control"/"target
    # creature an opponent controls" above.
    (r"target land you control", "land_you_control"),
    (r"target land (?:an opponent controls|you don't control)", "land_you_dont_control"),
    # "target nonbasic land [an opponent controls]" (Fulminator Mage / Dust
    # Bowl / Field of Ruin / Demolition Field / Ravenous Baboons — 21 SOLO
    # blockers) — RULE 205.4 supertype filter. `targeting.legal_targets`
    # already has a fully-implemented ``nonbasic_land`` branch (built for
    # Encroaching Wastes); the controller-scoped ``nonbasic_land_you_dont_
    # control`` mirror is new, matching the `land_you_dont_control` pattern.
    # Above the bare "target land" row so the longer phrase wins.
    (r"target nonbasic land (?:an opponent controls|you don't control)",
     "nonbasic_land_you_dont_control"),
    (r"target nonbasic land", "nonbasic_land"),
    # PAR-98: Siege of Towers' basic-land-subtype target.  This is a land
    # characteristic, not the generic ``target land`` frame.
    (r"target mountain", "mountain"),
    (r"target forest", "forest"),
    # "target land" (Sinkhole) — same RULE 115.1c precision as the artifact/
    # enchantment rows just above.
    (r"target land", "land"),
    # "a land you control" (a bounce-land's "return a land you control to
    # its owner's hand") isn't RULE 115 targeting at all — no "target" word —
    # but is modeled the same controller-restricted way: a choice among the
    # controller's own permanents, narrowed to lands at resolution.
    (r"a land you control", "land_you_control"),
    # "target nonland permanent an opponent controls" / "…you don't
    # control" (Lyev Skyknight/New Prahv Guildmage's detain) — the
    # controller-scoped narrowing, above the bare row so the longer phrase
    # wins, mirroring the "target permanent an opponent controls" pair.
    (r"target nonland permanent (?:an opponent controls|you don't control)",
     "nonland_permanent_you_dont_control"),
    # "target nonland permanent you control" (PAR-30 — Daring Thief / Puca's
    # Mischief exchange-control targets); the controller-scoped sibling,
    # above the bare row so the longer phrase wins.
    (r"(?:another |other )?target nonland permanent you control", "nonland_permanent_you_control"),
    # "[up to one] other target nonland permanent" (RULE 109.5 — Invasion
    # Submersible's ETB); "other" adds no distinct kind, same call as the
    # "another target permanent" row just below.
    (r"(?:another|other) target nonland permanent", "nonland_permanent"),
    (r"target nonland permanent", "nonland_permanent"),
    # "destroy target noncreature permanent" (Bramblecrush, Woodfall Primus — PAR-128):
    # the engine's `noncreature_permanent` pool, lands included (RULE 205.4a).
    (r"target noncreature permanent", "noncreature_permanent"),
    # "another target permanent" (RULE 109.5 — Legerdemain's second
    # exchange-control target; `other_permanent` isn't a distinct engine
    # kind, so it routes to the plain broad ``permanent`` pool like the
    # N-way row above, the same precision this file already accepts there).
    (r"(?:another|other) target permanent", "permanent"),
    (r"target spell", "spell"),
    # The opponent-only sibling is already a real engine pool (built for
    # the Enrage reflection family); keep it distinct from the broader
    # "player or planeswalker" row below so its player half cannot choose
    # the controller.
    (r"target opponent or planeswalker", "opponent_or_planeswalker"),
    (r"target player or planeswalker", "player"),
    (r"target opponent", "player"),
    (r"target player", "player"),
]
#: Deliberately no "each opponent"/"each player" row: RULE 115 targeting
#: always uses the word "target" — "each opponent"/"each player" is a mass
#: *selector* effect, not a target choice, and modeling it as a single
#: chosen "player" target would be wrong (it should hit everyone, not one
#: chosen player). `catalogue.handlers`'s selector-based damage handler
#: (``each_creature``/``each_player``/``each_opponent``) claims those
#: phrases on its own, bypassing TARGET entirely.

#: An optional self-subject prefix a resolve-time effect clause may open
#: with — "~ deals 3 damage…"/"it deals 3 damage…" (a triggered ability's
#: own elided-source subject, English writing "it" for the permanent whose
#: ability this is)/"this creature deals…"/"this land deals…"/"this
#: permanent deals…". Purely cosmetic: the source is already bound at bind
#: time regardless of which word prints, so every consumer just needs it
#: stripped the same way. Was hand-typed identically at many separate call
#: sites in `handlers.py`'s damage family before this existed (docs/09
#: "Factor shared sub-grammars"; PAR-61's port of the `81c3320` prototype).
SELF_SUBJECT_PREFIX = r"(?:(?:~|it|he|she|this creature|this land|this permanent) )?"

#: An optional "up to one "/"up to 1 " prefix (RULE 115.1a) a TARGET phrase
#: may carry — "destroy up to one target creature" is the same choice as
#: "destroy target creature" except zero targets is also legal
#: (`TargetSpec.optional`, `target_is_optional`). Deliberately just N=1: a
#: real "up to two/three/N" multi-target choice needs an interactive
#: multi-select and per-effect application over a *list* of targets — a
#: materially larger feature this grammar doesn't attempt (see
#: `docs/implementation-state/BACKLOG.md`). Exported (not
#: underscore-private) so a handler with its own hand-rolled "return/put
#: target …" grammar (the graveyard-recursion family) can embed it too,
#: without going through the shared `TARGET` alternation.
UP_TO_ONE = r"(?:up to (?:one|1) )?"

#: The TARGET fragment, as an alternation with a named ``target`` group. Used
#: *inside* a handler regex ("deal (\\d+) damage to <TARGET>"), so it is not
#: anchored itself. The optional ``up_to_one`` group sits *outside* ``target``
#: so `resolve_target_kind` keeps seeing exactly the row text it already
#: matches against.
#: PAR-128: the controller scope ("an opponent controls" / "you don't control")
#: is a slot after *any* row, not a row per type × scope. `resolve_target_kind`
#: composes it onto the row's kind through `NOT_YOU_TARGET_KINDS`; a row that
#: already names its own scope still wins (it is tried first, full-match).
NOT_YOU_TAIL = r" (?:an opponent controls|you don't control)"
#: PAR-130: "that player controls" is the same kind of slot, scoped to a
#: player the *trigger head* names (the damaged/attacked/active player, the
#: controller of a targeting spell). The slot itself can't see its antecedent,
#: so `gate` rejects any ability that carries a ``THAT_PLAYER_TARGET_KINDS``
#: kind without such a head (`gate._that_player_antecedent_ok`).
THAT_PLAYER_TAIL = r" that player controls"
#: PAR-128: RULE 109.5's "another"/"other" is the same kind of slot, before any row.
OTHER_PREFIX = r"(?:another|other) "
_TARGET_ALT = (
    f"(?:{OTHER_PREFIX})?"
    "(?:" + "|".join(f"(?:{frag})" for frag, _ in _TARGET_ROWS) + ")"
    f"(?:{NOT_YOU_TAIL}|{THAT_PLAYER_TAIL})?"
)
TARGET = (
    r"(?P<up_to_one>" + UP_TO_ONE + r")"
    r"(?P<target>" + _TARGET_ALT + r")"
)


def target_macro(suffix: str) -> str:
    """`TARGET` with its two group names suffixed (``target_b``/``up_to_one_b``).

    A regex can only name each group once, so a clause with **two**
    independent RULE 115.1 requirements in it — "target creature you control
    fights target creature you don't control" (RULE 701.14) — embeds `TARGET`
    for the first and this for the second. `resolve_target_kind` /
    `target_is_optional` both take the same ``suffix`` to read it back.
    """
    return (
        rf"(?P<up_to_one{suffix}>" + UP_TO_ONE + r")"
        rf"(?P<target{suffix}>" + _TARGET_ALT + r")"
    )

#: Each row's fragment compiled with a full-match anchor, in order, so
#: `resolve_target_kind` can classify a matched target phrase deterministically.
_TARGET_LOOKUP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(frag + r"\Z", re.IGNORECASE), kind) for frag, kind in _TARGET_ROWS
]

#: A small integer literal — after normalisation, spelled-out numbers are
#: already digits (`normalize`), so the grammar only needs to see digits.
NUMBER = r"(?P<n>\d+)"

#: "a"/"an" or a digit, for counts printed either way ("draw a card" /
#: "draw 2 cards"). `count_of` maps a captured group to an int.
COUNT = r"(?P<n>a|an|\d+)"

#: `COUNT`, plus the literal "x" (RULE 107.3c's own announced {X}, already
#: folded to a bare "x" token by `normalize` — "draw X cards", Braingeyser-
#: shaped). Kept as its own fragment rather than widening `COUNT` itself:
#: every existing `COUNT` caller expects a plain int from `count_of`, and
#: auditing each one for whether "x" would even make rules sense there is
#: out of scope for whichever single card motivates this — extend a
#: specific handler to `COUNT_X` (+ `count_or_x_of`) as a real card needs
#: it, the same "generalize the fragment, not blindly the call sites"
#: split `_rad_counter_amount` used before this existed.
COUNT_X = r"(?P<n>a|an|x|\d+)"

#: RULE 202.2f/700.6 "your devotion to <colour>[ and <colour>[ and
#: <colour>]]" (Purphoros/Heliod/Athreos/Karametra-shaped) or one of the five
#: two-colour "wedge" names (Abzan/Jeskai/Mardu/Sultai/Temur — Devoted
#: Abzan/Jeskai/Mardu/Sultai/Temur). One shared fragment feeding every
#: devotion-scaled handler (a static's "isn't a creature" gate, a pump/
#: damage/token/draw amount, …) so each only needs to embed `DEVOTION` once
#: rather than re-deriving the colour/wedge grammar; `devotion_selector`
#: turns a match into `continuous.count_selector`'s ``devotion_to_<key>``
#: name. "Devotion to hybrid" (Blended Twistling — any hybrid pip counts
#: once each, regardless of which two colours it's between, unlike ordinary
#: devotion where a hybrid pip counts toward *both* its colours) is its own
#: ``devotion_to_hybrid`` reading, not a colour/wedge name at all.
#: PAR-63: was its own copy of the five-colour map, in this same file.
_DEVOTION_COLOR_WORDS = COLOR_LETTERS
_DEVOTION_WEDGE_WORDS: frozenset[str] = frozenset({"abzan", "jeskai", "mardu", "sultai", "temur"})
#: RULE 613.7c's much wider "X is the number of `<noun phrase>` you
#: control" family (MEC-12's own count-amount resolver gap — 446 cards
#: solo-blocked on this single template, `parser_probe.py blocked "where x
#: is the number of"`) — folded into the *same* `DEVOTION` fragment (not a
#: sibling constant) so every amount-suffix handler that already embeds
#: `{DEVOTION}` picks up this reading for free, with no per-handler change.
#: Deliberately narrow: only the plain, unqualified noun phrases a
#: `continuous.count_selector` entry already exists for (bare "creatures/
#: permanents/artifacts/lands you control", "attacking creatures[ you
#: control]", "tapped creatures you control", and a single creature-type
#: word), plus — since MEC-27 — two qualified shapes: "creatures you control
#: with power N or less/greater" (Arabella, Abandoned Doll/Dragonhawk,
#: Fate's Tempest/The Boulder, Ready to Rumble) and "tapped `<type>`[ and/or
#: `<type>`] you control" (Aang and Katara/Alibou, Ancient Witness/Lydia
#: Frye — generalizing the old creatures-only tapped row rather than adding
#: a sibling, so "tapped creatures you control" still resolves to the exact
#: `tapped_creatures_you_control` name every existing caller/test already
#: expects). Still fail-closed on anything wider — a toughness qualifier, or
#: a power qualifier on anything but the bare "creatures" word — same as
#: every other row here. The single-word branch is read by the shared count
#: grammar (`subtype_count_selector`), which knows irregular plurals and
#: non-creature subtypes.
_COUNT_PHRASE_BARE_WORDS: frozenset[str] = frozenset(
    {"creatures", "permanents", "artifacts", "lands", "enchantments", "planeswalkers"}
)
#: Two-word compound noun phrases with their own dedicated
#: `continuous.count_selector` entry, rather than the bare-word ``_you_
#: control`` suffix pattern above (Eiganjo, Seat of the Empire/Ghostfire
#: Slice's own printed shapes).
_COUNT_PHRASE_COMPOUNDS: dict[str, str] = {
    "legendary creatures": "legendary_creatures_you_control",
    "multicolored permanents": "multicolored_permanents_you_control",
    "artifacts and/or enchantments": "artifacts_and_or_enchantments_you_control",
}


def _singularize(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 1 else word


DEVOTION = (
    r"(?:"
    r"(?:your devotion to (?:"
    r"(?P<devotion_colors>(?:white|blue|black|red|green)(?: and (?:white|blue|black|red|green)){0,2})"
    r"|(?P<devotion_wedge>abzan|jeskai|mardu|sultai|temur)"
    r"|(?P<devotion_hybrid>hybrid)"
    r"))"
    r"|(?:the number of (?:"
    r"(?P<count_compound>legendary creatures|multicolored permanents|artifacts and/or enchantments) you control"
    r"|(?P<count_power>creatures) you control with power (?P<count_power_n>\d+) or (?P<count_power_cmp>less|greater)"
    r"|(?P<count_bare>creatures|permanents|artifacts|lands|enchantments|planeswalkers) you control"
    r"|(?P<count_attacking>attacking creatures)(?P<count_attacking_yours> you control)?"
    r"|(?P<count_colors_among_permanents>colors among permanents you control)"
    r"|tapped (?P<count_tapped_1>[a-z]+)(?: and/or (?P<count_tapped_2>[a-z]+))? you control"
    r"|(?P<count_died_this_turn>creatures that died this turn)"
    r"|(?P<count_subtype>[a-z]+) you control"
    r"))"
    r")"
)


def devotion_selector(m: "re.Match[str]") -> "Optional[str | dict[str, Any]]":
    """A `DEVOTION` match's groups → `continuous.count_selector`'s name, or
    ``None`` if somehow no group fired. Named for its original, narrower
    devotion-only purpose; also resolves the wider "the number of `<noun
    phrase>` you control" reading the fragment now carries (see `DEVOTION`'s
    own docstring) — kept as one function rather than a sibling, since every
    existing call site already expects one selector-or-None answer.
    """
    if m.groupdict().get("devotion_hybrid"):
        return "devotion_to_hybrid"
    wedge = m.groupdict().get("devotion_wedge")
    if wedge:
        return f"devotion_to_{wedge}"
    colors_text = m.groupdict().get("devotion_colors")
    if colors_text:
        words = colors_text.split(" and ")
        if len(words) == 1:
            return f"devotion_to_{words[0]}"
        letters = sorted(
            {_DEVOTION_COLOR_WORDS[w] for w in words}, key="WUBRG".index
        )
        return f"devotion_to_{''.join(letters).lower()}"
    compound = m.groupdict().get("count_compound")
    if compound:
        return _COUNT_PHRASE_COMPOUNDS.get(compound)
    if m.groupdict().get("count_power"):
        # "the number of creatures you control with power N or less/greater"
        # (MEC-27's own qualifier grammar — Arabella, Abandoned Doll/
        # Dragonhawk, Fate's Tempest/The Boulder, Ready to Rumble) — the
        # count-amount sibling of the many trigger/target/static "creature
        # you control with power N or less" filters elsewhere in this
        # codebase, read live off the same layer-engine `power`.
        op = "le" if m.group("count_power_cmp") == "less" else "ge"
        return f"creatures_you_control_with_power_{op}_{m.group('count_power_n')}"
    bare = m.groupdict().get("count_bare")
    if bare:
        return f"{bare}_you_control"
    if m.groupdict().get("count_attacking"):
        return (
            "attacking_creatures_you_control" if m.groupdict().get("count_attacking_yours")
            else "attacking_creatures"
        )
    if m.groupdict().get("count_colors_among_permanents"):
        return "colors_among_permanents_you_control"
    if m.groupdict().get("count_died_this_turn"):
        return "creatures_died_this_turn"
    tapped1 = m.groupdict().get("count_tapped_1")
    if tapped1:
        # "the number of tapped `<type>`[ and/or `<type>`] you control"
        # (MEC-27's own qualifier grammar — Aang and Katara/Alibou, Ancient
        # Witness/Lydia Frye), generalizing the old creatures-only tapped
        # row: a bare category word maps the same way `count_bare` does, any
        # other single word is read as a creature subtype exactly like
        # `count_subtype` below. "tapped creatures you control" alone still
        # resolves to the exact `tapped_creatures_you_control` name every
        # existing caller/test already expects.
        def _tapped_part(word: str) -> str:
            return word if word in _COUNT_PHRASE_BARE_WORDS else f"type_{_singularize(word)}"

        parts = [_tapped_part(tapped1)]
        tapped2 = m.groupdict().get("count_tapped_2")
        if tapped2:
            parts.append(_tapped_part(tapped2))
        return f"tapped_{'_and_or_'.join(parts)}_you_control"
    subtype = m.groupdict().get("count_subtype")
    if subtype and subtype not in _COUNT_PHRASE_BARE_WORDS:
        # "the number of `<word>` you control": the shared count grammar reads
        # the word — a subtype on any permanent (Gates, Auras, Shrines, Forests),
        # a card type ("lands"), an irregular plural ("Elves") — and refuses a
        # word it doesn't know, rather than guessing a creature type.
        return subtype_count_selector(subtype)
    return None


def subtype_count_selector(word: str) -> Optional[dict[str, Any]]:
    """ "`<word>` you control" → the structured count selector, or ``None``."""
    from .count_phrase import parse_count_phrase  # function-scoped: count_phrase is a sibling grammar

    return parse_count_phrase(f"{word.lower()} you control")


#: PAR-128: a target kind → the same pool scoped to permanents you don't
#: control (`targeting.TARGET_FRAMES`' ``SCOPE_NOT_YOU`` over that kind's type
#: pool; `tests/test_par128_target_scope.py` keeps the two in step — this
#: module can't import `game/`). A kind missing here has no scoped engine
#: kind, so its scoped phrase stays unclaimed.
NOT_YOU_TARGET_KINDS: dict[str, str] = {
    "creature": "creature_you_dont_control",
    "permanent": "permanent_you_dont_control",
    "nonland_permanent": "nonland_permanent_you_dont_control",
    "land": "land_you_dont_control",
    "nonbasic_land": "nonbasic_land_you_dont_control",
    "artifact": "artifact_you_dont_control",
    "enchantment": "enchantment_you_dont_control",
    "artifact_or_enchantment": "artifact_or_enchantment_you_dont_control",
    "artifact_or_creature": "artifact_or_creature_you_dont_control",
    "creature_or_planeswalker": "creature_or_planeswalker_you_dont_control",
}
#: PAR-130: a target kind → the same pool scoped to "that player"
#: (`targeting.TARGET_FRAMES`' ``SCOPE_THAT_PLAYER`` rows). Same contract as
#: `NOT_YOU_TARGET_KINDS`: a kind missing here stays unclaimed.
THAT_PLAYER_TARGET_KINDS: dict[str, str] = {
    base: f"{base}_that_player_controls" for base in (
        "creature", "creature_or_planeswalker", "permanent", "nonland_permanent", "land",
        "nonbasic_land", "artifact", "enchantment", "artifact_or_enchantment",
        "artifact_or_creature",
    )
}
#: PAR-128: kinds whose engine pool already leaves out the ability's own source
#: (`targeting.TARGET_FRAMES`' ``exclude_source``, and the plain ``creature``/
#: ``permanent`` branches), so "another target `<X>`" is the same kind. A kind
#: that includes its source has an "other" sibling here or fails closed.
SOURCE_EXCLUDED_TARGET_KINDS: frozenset[str] = frozenset({
    "creature", "permanent", "nonland_permanent", "artifact", "enchantment", "land",
    "nonbasic_land", "artifact_or_creature", "artifact_or_enchantment",
    "attacking_or_blocking_creature", "permanent_you_control", "permanent_you_dont_control",
    "nonland_permanent_you_control", "nonland_permanent_you_dont_control",
    "other_creature_you_control", "creature_or_planeswalker",
})
OTHER_TARGET_KINDS: dict[str, str] = {"creature_you_control": "other_creature_you_control"}
#: A controller-/"another"-scoped kind → the unscoped kind whose pool it
#: narrows (RULE 109.5/115.1). A verb that can act on the unscoped kind can act
#: on any narrowing of it, so `target_kind_allowed` reads a verb's whitelist
#: through this instead of every verb listing every scope.
SCOPED_TARGET_BASE: dict[str, str] = {
    **{scoped: base for base, scoped in NOT_YOU_TARGET_KINDS.items()},
    **{scoped: base for base, scoped in THAT_PLAYER_TARGET_KINDS.items()},
    "creature_you_control": "creature",
    "other_creature_you_control": "creature",
    "permanent_you_control": "permanent",
    "nonland_permanent_you_control": "nonland_permanent",
    "land_you_control": "land",
    "artifact_or_creature_you_control": "artifact_or_creature",
    # a type union is a narrowing of "any permanent"
    "artifact_or_enchantment": "permanent",
    "artifact_or_creature": "permanent",
    "creature_or_planeswalker": "permanent",
    # PAR-128: "noncreature permanent" narrows "any permanent" by a type exclusion.
    "noncreature_permanent": "permanent",
}


def target_kind_allowed(kind: Optional[str], allowed: "Iterable[str]") -> bool:
    """Whether a verb whose whitelist is ``allowed`` can take a ``kind`` target —
    the kind itself, or a scoped narrowing of an allowed kind."""
    if kind is None:
        return False
    allowed = allowed if isinstance(allowed, (set, frozenset, dict)) else tuple(allowed)
    while kind is not None:
        if kind in allowed:
            return True
        kind = SCOPED_TARGET_BASE.get(kind)
    return False


def resolve_target_kind(phrase: str) -> Optional[str]:
    """Classify a matched TARGET ``phrase`` into an engine ``target_kind``.

    Returns ``None`` if it matches no row (fail-closed: an unrecognised target
    leaves the clause unclaimed rather than guessing ``"any"``).
    """
    text = phrase.strip()
    for pattern, kind in _TARGET_LOOKUP:
        if pattern.match(text):
            return kind
    tail = re.search(NOT_YOU_TAIL + r"\Z", text, re.IGNORECASE)
    if tail is not None:
        base = resolve_target_kind(text[: tail.start()])
        return NOT_YOU_TARGET_KINDS.get(base) if base is not None else None
    tail = re.search(THAT_PLAYER_TAIL + r"\Z", text, re.IGNORECASE)
    if tail is not None:
        base = resolve_target_kind(text[: tail.start()])
        return THAT_PLAYER_TARGET_KINDS.get(base) if base is not None else None
    other = re.match(OTHER_PREFIX, text, re.IGNORECASE)
    if other is not None:
        base = resolve_target_kind(text[other.end():])
        if base in SOURCE_EXCLUDED_TARGET_KINDS:
            return base
        return OTHER_TARGET_KINDS.get(base) if base is not None else None
    return None


#: "target attacking/blocking/tapped/untapped creature" (RULE 508/509's
#: combat-state qualifiers) is a real, separate filter axis
#: `resolve_target_kind` doesn't carry — the `_TARGET_ROWS` row for it
#: deliberately collapses all four onto the bare ``"creature"`` kind (this
#: file's existing "target `<state>` creature" → `creature` precision-loss
#: convention, matching how "target attacking or blocking creature" already
#: collapses too), so a caller that needs the qualifier reads it from the
#: same raw phrase via this sibling function and merges it into whatever
#: `creature_filter` it already builds. The four words map straight onto
#: `combat.matches_object_filter`'s own existing boolean keys — "untapped"
#: is ``{"tapped": False}``, the negative of the printed ``"tapped"`` key,
#: not a fifth key of its own. Found auditing PAR-79's own "target legendary
#: creature" fix: the identical shape existed here too (Assassinate's
#: "Destroy target tapped creature" silently destroyed *any* creature,
#: confirmed via `inspect-db` against the real cache — a live rules bug, not
#: a coverage gap), just one layer up from where that fix landed.
_TARGET_COMBAT_STATE_RE = re.compile(
    r"(?:" + OTHER_PREFIX + r")?target (attacking|blocking|tapped|untapped) creature(?:" + NOT_YOU_TAIL + r")?",
    re.IGNORECASE,
)


#: PAR-134: scope adjectives that name a characteristic other than a creature
#: subtype → the `combat.matches_object_filter` fragment they mean. A word
#: here must never reach the ``subtype`` param: ``_has_subtype`` would then
#: look for a creature type nobody has and the static would silently affect
#: nothing (or, for a negation, everything).
SCOPE_ADJECTIVES: dict[str, dict] = {
    "tapped": {"tapped": True},
    "untapped": {"tapped": False},
    "legendary": {"legendary": True},
    "nonlegendary": {"nonlegendary": True},
    "nontoken": {"nontoken": True},
    "multicolored": {"multicolored": True},
    "colorless": {"colorless": True},
    "snow": {"snow": True},
    "modified": {"modified": True},
    "nonattacking": {"attacking": False},
    "commander": {"is_commander": True},
    # RULE 700.6: legendary supertype, artifact card type or Saga subtype.
    "historic": {"any_of": [{"legendary": True}, {"card_type": "artifact"}, {"subtype": "Saga"}]},
}

#: Card types a "non<type>" adjective may negate (RULE 205.2a).
_NEGATABLE_CARD_TYPES: frozenset[str] = frozenset(
    {"artifact", "creature", "enchantment", "land", "planeswalker", "battle", "instant", "sorcery"}
)

#: "non<word>" / "non-<word>" — the negation of a colour, card type or subtype.
_NON_WORD_RE = re.compile(r"non-?(?P<word>[a-z]+)")


def scope_adjective(word: str) -> Optional[dict]:
    """The filter fragment for one scope adjective (PAR-134), else ``None``."""
    if word in SCOPE_ADJECTIVES:
        return copy.deepcopy(SCOPE_ADJECTIVES[word])  # callers merge into their own dict
    m = _NON_WORD_RE.fullmatch(word)
    if m is None:
        return None
    negated = m.group("word")
    if negated in COLOR_LETTERS:
        return {"without_color": [COLOR_LETTERS[negated]]}
    if negated in _NEGATABLE_CARD_TYPES:
        return {"without_card_type": negated}
    return {"without_subtype": negated.capitalize()}  # "non-Wall", "nonhuman"


_TARGET_ADJECTIVE_RE = re.compile(
    r"(?:" + OTHER_PREFIX + r")?target ([a-z-]+) creature(?:" + NOT_YOU_TAIL + r")?",
    re.IGNORECASE,
)


def resolve_target_creature_state_filter(phrase: str) -> Optional[dict]:
    """"target `<state>` creature" → a `combat.matches_object_filter`
    fragment (``{"attacking": True}``/``{"tapped": False}``/…), or ``None``
    if ``phrase`` carries no such qualifier. Call alongside
    `resolve_target_kind` on the same raw text and merge the result into
    the caller's own ``creature_filter``.
    """
    m = _TARGET_COMBAT_STATE_RE.fullmatch(phrase.strip())
    if m is None:
        # PAR-134: the same shape for a supertype/designation/negation adjective
        # ("target legendary creature", "target nonattacking creature",
        # "target multicolored creature") — `scope_adjective`'s vocabulary, so a
        # caller that falls back to "the word is a subtype" never guesses it.
        m = _TARGET_ADJECTIVE_RE.fullmatch(phrase.strip())
        return None if m is None else scope_adjective(m.group(1).lower())
    word = m.group(1).lower()
    return {"tapped": word != "untapped"} if word in ("tapped", "untapped") else {word: True}


def target_is_optional(m: "re.Match[str]", suffix: str = "") -> bool:
    """Whether a `TARGET`-bearing match carries an "up to one" prefix.

    Every handler regex built with `{TARGET}` gets the ``up_to_one`` group
    for free, so this is safe to call on any such match. ``suffix`` reads a
    second requirement embedded via `target_macro`.
    """
    return bool(m.group(f"up_to_one{suffix}"))


def count_of(token: str) -> int:
    """A captured `COUNT`/`NUMBER` token → its integer value ("a"/"an" → 1)."""
    token = token.strip().lower()
    if token in ("a", "an"):
        return 1
    return int(token)


def count_or_x_of(token: str) -> "int | str":
    """A captured `COUNT_X` token → its integer value, or the ``"x"``
    sentinel `RulesEngine._substitute_x` resolves against the spell/
    ability's actually-announced {X} at resolve time."""
    return "x" if token.strip().lower() == "x" else count_of(token)


#: WUBRG colour words → letters, for the old-templating "target blue
#: permanent"/"counter target spell if it's blue" color-hoser family (Red
#: Elemental Blast/Pyroblast-shaped, RULE 105) — a card either bakes the
#: adjective into the target noun phrase or tacks a trailing "if it's
#: <color>" clause onto the whole ability; both are the same restriction,
#: just templated differently across Magic's history. Shared by the counter
#: family's `SPELL_TARGET` (an inline adjective) and any handler that wants
#: the trailing-clause form via `IF_COLOR_SUFFIX`/`split_target_color`.
#: Public alias — a handler that needs to build its own "target [color]
#: <noun>" alternation (the `TARGET` macro's fixed rows have no color slot)
#: can reuse this word list rather than re-declaring it.
COLOR_WORD_ALT = r"white|blue|black|red|green"
_COLOR_ALT = COLOR_WORD_ALT
_COLOR_LETTERS = COLOR_LETTERS


def resolve_color_word(word: Optional[str]) -> Optional[str]:
    """A colour word ("blue") → its WUBRG letter, or ``None`` for anything else."""
    if not word:
        return None
    return _COLOR_LETTERS.get(word.strip().lower())


#: An optional trailing "if it's <color>" clause (the Pyroblast/Red
#: Elemental Blast old-templating variant of a colour restriction) — embed
#: at the end of a handler's own regex; the match exposes it as the
#: ``cond_color`` group.
IF_COLOR_SUFFIX = rf"(?: if it'?s (?P<cond_color>{_COLOR_ALT}))?"


# --- "counter target <filter> spell" (RULE 601.2c/115) ----------------------
# The counter family's own target grammar: unlike the generic `TARGET` rows
# above (one fixed `target_kind` per row), a countered *spell* can carry a
# structured filter — "noncreature", a card-type list ("instant or sorcery"),
# and/or "with mana value N" — so this is a dedicated companion grammar
# rather than another `_TARGET_ROWS` entry (docs/09 "Factor shared
# sub-grammars"; only `catalogue.handlers`'s counter handler needs it today).

#: Card-type words a spell-target filter may name (nonland types only — a
#: land is never a spell). "battle" is here for "counter target creature or
#: battle spell" (Assimilate Essence) — a battle *is* castable, so a battle
#: spell is a legal thing to filter for. Kept in sync with `game/targeting.
#: _spell_matches_filter`'s ``type_checks`` keys by `tests/test_counter_family.py`.
_SPELL_TYPE_WORD = r"(?:artifact|battle|creature|enchantment|instant|planeswalker|sorcery)"
#: An "or"/comma-separated list of 1+ type words: "creature", "instant or
#: sorcery", "artifact, creature, or planeswalker".
_SPELL_TYPE_LIST = (
    rf"{_SPELL_TYPE_WORD}(?:,\s*{_SPELL_TYPE_WORD})*(?:,?\s+or\s+{_SPELL_TYPE_WORD})?"
)

#: PAR-74: "target **spirit or arcane** spell" (Hisoka's Defiance) — a
#: creature-subtype-or-"Arcane" OR filter, not a main card type
#: (`_SPELL_TYPE_WORD` deliberately excludes subtypes — no real card's
#: "target `<type>` spell" filter needed one until now). A small curated
#: whitelist, same fail-closed discipline as `segmenter._CAST_SPELL_
#: SUBTYPE_WORDS`' own "arcane" special case (RULE 702.15's Kamigawa
#: instant/sorcery subtype has no creature-type meaning of its own, so it's
#: listed separately from the real creature-subtype words rather than
#: folded into one open vocabulary).
_SPELL_SUBTYPE_WORD = r"(?:spirit|arcane)"
_SPELL_SUBTYPE_LIST = (
    rf"{_SPELL_SUBTYPE_WORD}(?:,\s*{_SPELL_SUBTYPE_WORD})*(?:,?\s+or\s+{_SPELL_SUBTYPE_WORD})?"
)
#: The bare "target [noncreature|<type list>] spell [with mana value N]"
#: phrase, unanchored (embedded inside a handler's own regex via `SPELL_
#: TARGET`) — never both ``noncreature`` and ``types`` (no real card prints
#: both), so a handler only needs to check whichever group is set.
_SPELL_TARGET_BODY = (
    r"target "
    rf"(?:(?P<color>{_COLOR_ALT})\s+)?"
    r"(?:(?P<noncreature>noncreature)\s+)?"
    rf"(?:(?P<subtypes>{_SPELL_SUBTYPE_LIST})\s+|(?P<types>{_SPELL_TYPE_LIST})\s+)?"
    r"spell"
    r"(?:\s+with mana value (?P<mv>\d+))?"
    # PAR-128: the controller scope slot — "counter target spell **you don't control**".
    r"(?P<scope> (?:you don'?t control|an opponent controls|your opponents control))?"
)
#: The same phrase captured under a ``target`` group, for embedding inline in
#: a handler regex the way `TARGET` is (e.g. ``counter {SPELL_TARGET}``).
SPELL_TARGET = rf"(?P<target>{_SPELL_TARGET_BODY})"
_SPELL_TARGET_LOOKUP = re.compile(_SPELL_TARGET_BODY + r"\Z", re.IGNORECASE)


def resolve_spell_filter(phrase: str) -> Optional[dict[str, Any]]:
    """Classify a matched `SPELL_TARGET` ``phrase`` into a `TargetSpec.
    spell_filter`-shaped dict, or ``None`` if it matches no recognised shape
    (fail-closed, mirroring `resolve_target_kind`).

    A bare "target spell" resolves to ``{}`` (no filter, still a legal —
    just unfiltered — countable target).
    """
    m = _SPELL_TARGET_LOOKUP.match(phrase.strip())
    if m is None:
        return None
    filt: dict[str, Any] = {}
    if m.group("color"):
        filt["color"] = resolve_color_word(m.group("color"))
    if m.group("noncreature"):
        filt["noncreature"] = True
    if m.group("types"):
        # ", or " (the Oxford-comma joiner before the last item) must split as
        # one separator — trying the plain "," alternative first would leave
        # a stray "or " glued onto the final type word.
        types = [t for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("types")) if t]
        filt["card_types"] = types
    if m.group("subtypes"):
        subtypes = [t for t in re.split(r",\s*or\s+|,\s*|\s+or\s+", m.group("subtypes")) if t]
        filt["subtype_any"] = subtypes
    if m.group("mv"):
        filt["mana_value"] = int(m.group("mv"))
    if m.group("scope"):
        filt["target_kind"] = "spell_you_dont_control"
    return filt


#: "This spell can't be countered." / "~ can't be countered." (RULE 118-area).
#: The literal phrasing is identical whether the clause is an instant/
#: sorcery's own resolve-time body (`catalogue.handlers`) or a permanent's
#: standing line (`catalogue.static_handlers`) — both claim it with this one
#: pattern so the two front-end paths agree on the same `EffectSpec`.
CANT_BE_COUNTERED_RE: re.Pattern[str] = re.compile(
    r"(?:this spell|~) can't be countered", re.IGNORECASE
)
