"""ENG-34 — the atom inventory: this engine's instruction set architecture.

Design: [docs/concepts/14_PARSER_GRAMMAR_DESIGN.md] stage S0. Evidence:
[docs/concepts/13_ORACLE_PARSER_GRAMMAR_REVIEW.md].

`13_` established that the parser enumerates whole-clause shapes over an IR
with no composition node, while the operation vocabulary underneath is
closed and small — 130 distinct operations, the top 50 covering 94.9% of the
corpus, against 21,194 whole-clause skeletons that are 93.1% singletons. The
conclusion that follows is that `EffectRegistry`'s registered types and
`RulesEngine`'s public methods are not that many *different things*: they
are a partially-filled cross-product of four independent axes (operation ×
operands × composition × linkage), written out by hand because axis 3 does
not exist.

**This module is that factoring, made machine-checkable.** It is pure data
plus queries — it imports nothing from the engine at module load and
changes no behaviour. Its job is to be *wrong loudly*:
`tests/test_isa_inventory.py` asserts every registered effect type carries a
classification and every classification names a registered type, so adding
an effect type without deciding what it is fails the suite rather than
quietly growing the enumeration `13_`'s standing gate forbids growing.

Four things live here:

- **`INSTRUCTIONS`** — the ISA proper, derived from the Comprehensive Rules
  (RULE 701's keyword actions, plus the zone-change / damage / counter /
  life / mana operations the rules use without naming as keywords), each
  with the CR rule that defines it and its **argument frame**.
- **`ROLES`** — the frame vocabulary, one shared list for parser and engine.
- **`EFFECT_TYPES`** — every registered type, classified *instruction* /
  *continuation pair* / *fusion* / *alias* / *one-card special* against
  that ISA.
- **`OPERATORS`** — the composition operators ENG-37 proposes, each
  justified by the fusions it retires. Per `14_` S0c an operator with no
  fusions behind it is not yet justified, and the test enforces that.

The **fusion** list is the load-bearing output. A fusion is two instructions
welded into one registered type because the IR cannot sequence them; the
engine states the problem itself, in `LivingWeaponEffect`:

    "there's no vocabulary for whatever the previous effect just made — an
    atomic effect class per verb pair was the only alternative."

That list is ENG-37's backlog: every composite operator has to name the
fusions it kills, and closing ENG-37 means those types are gone.

**Classification precedence.** Several types answer to more than one label
(a one-card special that is also a fusion, say). They are classified by
which axis *retires* them, most-specific first::

    CONTINUATION > FUSION > ALIAS > INSTRUCTION > SPECIAL

so ENG-35 sweeps every type that blocks on a player choice and ENG-37
sweeps every type that only exists because two instructions could not be
sequenced, regardless of how card-specific either happens to be. `SPECIAL`
is therefore a genuine residue — "not decomposable into the ISA today" —
rather than a synonym for "named after a card".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# --- axis 2: the shared role vocabulary ------------------------------------

#: The argument-frame roles an instruction's operands are drawn from
#: (`14_` §2 axis 2). One vocabulary for both sides of the pipeline: the
#: parser fills a frame, the engine reads one. `13_` §5.6b observed 11,532
#: distinct operand shapes against ~130 operations precisely because no such
#: vocabulary was declared — every handler invented its own param names.
#:
#: Deliberately six and no more. A role earns its place by being an operand
#: the *rules* distinguish, not by being a param some handler happens to
#: take: RULE 701's keyword actions are written as "<agent> <verb>s
#: <patient>", zone changes (RULE 400.7) name a source and a destination,
#: RULE 107 supplies the amount, and RULE 611 supplies the duration of a
#: continuous effect a resolving instruction creates.
ROLE_AGENT = "agent"
ROLE_PATIENT = "patient"
ROLE_SOURCE_ZONE = "source_zone"
ROLE_DEST_ZONE = "dest_zone"
ROLE_AMOUNT = "amount"
ROLE_DURATION = "duration"

ROLES: tuple[str, ...] = (
    ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE,
    ROLE_DEST_ZONE, ROLE_AMOUNT, ROLE_DURATION,
)


@dataclass(frozen=True)
class Instruction:
    """One operation in the ISA: a name, the CR rule defining it, a frame.

    ``frame`` is the ordered subset of `ROLES` this operation takes. It is
    the *declared* frame — what the rules give the operation — not a survey
    of what today's handlers happen to pass, which is the 11,532-shape mess
    it exists to replace.
    """

    name: str
    #: The Comprehensive Rules passage defining this operation, as the bare
    #: number this repo's ``RULE <n>`` comments use.
    rule: str
    frame: tuple[str, ...]
    note: str = ""


def _ins(name: str, rule: str, *frame: str, note: str = "") -> Instruction:
    return Instruction(name=name, rule=rule, frame=tuple(frame), note=note)


#: The ISA. RULE 701's keyword actions are the spine (701.2–701.70, read off
#: the CR text itself rather than off this engine's method list, so the diff
#: between the two is meaningful); the rest are the operations the rules use
#: constantly without calling them keyword actions — damage (RULE 120),
#: drawing (RULE 121), counters (RULE 122), life (RULE 119), mana (RULE
#: 106), the zone change itself (RULE 400.7), copying (RULE 707), and the
#: randomizers (RULE 705/706).
#:
#: ``create_continuous_effect`` is the one entry that is not a rules verb: it
#: is how a *resolving* instruction (a pump spell, an "until end of turn"
#: keyword grant) creates a RULE 611 continuous effect. It carries a
#: duration and is genuinely part of the instruction stream, which is what
#: separates it from a RULE 613 static ability — those never enter the
#: instruction stream at all (`14_` §1.1) and are deliberately absent here.
INSTRUCTIONS: dict[str, Instruction] = {
    i.name: i for i in (
        # --- RULE 701 keyword actions, in CR order ----------------------
        _ins("activate", "701.2", ROLE_AGENT, ROLE_PATIENT),
        _ins("attach", "701.3", ROLE_AGENT, ROLE_PATIENT),
        _ins("behold", "701.4", ROLE_AGENT, ROLE_PATIENT),
        _ins("cast", "701.5", ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE),
        _ins("counter", "701.6", ROLE_AGENT, ROLE_PATIENT),
        _ins("create", "701.7", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT,
             note="create a token; the patient is the token's descriptor"),
        _ins("destroy", "701.8", ROLE_AGENT, ROLE_PATIENT),
        _ins("discard", "701.9", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("double", "701.10", ROLE_AGENT, ROLE_PATIENT),
        _ins("triple", "701.11", ROLE_AGENT, ROLE_PATIENT),
        _ins("exchange", "701.12", ROLE_AGENT, ROLE_PATIENT),
        _ins("exile", "701.13", ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE),
        _ins("fight", "701.14", ROLE_AGENT, ROLE_PATIENT),
        _ins("goad", "701.15", ROLE_AGENT, ROLE_PATIENT, ROLE_DURATION),
        _ins("investigate", "701.16", ROLE_AGENT, ROLE_AMOUNT),
        _ins("mill", "701.17", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("play", "701.18", ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE),
        _ins("regenerate", "701.19", ROLE_AGENT, ROLE_PATIENT),
        _ins("reveal", "701.20", ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE),
        _ins("sacrifice", "701.21", ROLE_AGENT, ROLE_PATIENT),
        _ins("scry", "701.22", ROLE_AGENT, ROLE_AMOUNT),
        _ins("search", "701.23", ROLE_AGENT, ROLE_PATIENT, ROLE_SOURCE_ZONE),
        _ins("shuffle", "701.24", ROLE_AGENT, ROLE_SOURCE_ZONE),
        _ins("surveil", "701.25", ROLE_AGENT, ROLE_AMOUNT),
        _ins("tap", "701.26", ROLE_AGENT, ROLE_PATIENT),
        _ins("untap", "701.26", ROLE_AGENT, ROLE_PATIENT),
        _ins("transform", "701.27", ROLE_AGENT, ROLE_PATIENT),
        _ins("convert", "701.28", ROLE_AGENT, ROLE_PATIENT),
        _ins("fateseal", "701.29", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("clash", "701.30", ROLE_AGENT, ROLE_PATIENT),
        _ins("planeswalk", "701.31", ROLE_AGENT),
        _ins("set_in_motion", "701.32", ROLE_AGENT, ROLE_PATIENT),
        _ins("abandon", "701.33", ROLE_AGENT, ROLE_PATIENT),
        _ins("proliferate", "701.34", ROLE_AGENT),
        _ins("detain", "701.35", ROLE_AGENT, ROLE_PATIENT),
        _ins("populate", "701.36", ROLE_AGENT),
        _ins("monstrosity", "701.37", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("vote", "701.38", ROLE_AGENT, ROLE_PATIENT),
        _ins("bolster", "701.39", ROLE_AGENT, ROLE_AMOUNT),
        _ins("manifest", "701.40", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("support", "701.41", ROLE_AGENT, ROLE_AMOUNT),
        _ins("meld", "701.42", ROLE_AGENT, ROLE_PATIENT),
        _ins("exert", "701.43", ROLE_AGENT, ROLE_PATIENT),
        _ins("explore", "701.44", ROLE_AGENT, ROLE_PATIENT),
        _ins("assemble", "701.45", ROLE_AGENT, ROLE_PATIENT),
        _ins("adapt", "701.46", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("amass", "701.47", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("learn", "701.48", ROLE_AGENT),
        _ins("venture", "701.49", ROLE_AGENT),
        _ins("connive", "701.50", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("open_attraction", "701.51", ROLE_AGENT),
        _ins("roll_to_visit_attractions", "701.52", ROLE_AGENT),
        _ins("incubate", "701.53", ROLE_AGENT, ROLE_AMOUNT),
        _ins("ring_tempts_you", "701.54", ROLE_AGENT),
        _ins("face_villainous_choice", "701.55", ROLE_AGENT, ROLE_PATIENT),
        _ins("time_travel", "701.56", ROLE_AGENT),
        _ins("discover", "701.57", ROLE_AGENT, ROLE_AMOUNT),
        _ins("cloak", "701.58", ROLE_AGENT, ROLE_PATIENT),
        _ins("collect_evidence", "701.59", ROLE_AGENT, ROLE_AMOUNT),
        _ins("suspect", "701.60", ROLE_AGENT, ROLE_PATIENT),
        _ins("forage", "701.61", ROLE_AGENT),
        _ins("manifest_dread", "701.62", ROLE_AGENT),
        _ins("endure", "701.63", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("harness", "701.64", ROLE_AGENT, ROLE_PATIENT),
        _ins("airbend", "701.65", ROLE_AGENT, ROLE_PATIENT),
        _ins("earthbend", "701.66", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("waterbend", "701.67", ROLE_AGENT, ROLE_AMOUNT),
        _ins("blight", "701.68", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("heal", "701.69", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("recruit", "701.70", ROLE_AGENT),

        # --- operations the rules use without naming as keyword actions --
        _ins("deal_damage", "120", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("prevent_damage", "615", ROLE_PATIENT, ROLE_AMOUNT, ROLE_DURATION),
        _ins("redirect_damage", "616", ROLE_PATIENT, ROLE_AMOUNT),
        _ins("draw", "121", ROLE_AGENT, ROLE_AMOUNT),
        _ins("gain_life", "119.3", ROLE_AGENT, ROLE_AMOUNT),
        _ins("lose_life", "119.4", ROLE_AGENT, ROLE_AMOUNT),
        _ins("set_life", "119.5", ROLE_AGENT, ROLE_AMOUNT),
        _ins("put_counter", "122.2", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("remove_counter", "122.2", ROLE_AGENT, ROLE_PATIENT, ROLE_AMOUNT),
        _ins("move_counter", "122.2", ROLE_PATIENT, ROLE_AMOUNT),
        _ins("add_mana", "106.1", ROLE_AGENT, ROLE_AMOUNT),
        _ins("pay_cost", "118", ROLE_AGENT, ROLE_AMOUNT),
        _ins("move_object", "400.7", ROLE_PATIENT, ROLE_SOURCE_ZONE, ROLE_DEST_ZONE,
             note="the general zone change every zone-specific instruction "
                  "above is a rules-named special case of"),
        _ins("copy_object", "707", ROLE_AGENT, ROLE_PATIENT),
        _ins("gain_control", "609.4", ROLE_AGENT, ROLE_PATIENT, ROLE_DURATION),
        _ins("flip_coin", "705", ROLE_AGENT),
        _ins("roll_die", "706", ROLE_AGENT, ROLE_AMOUNT),
        _ins("win_game", "104.2", ROLE_AGENT),
        _ins("lose_game", "104.3", ROLE_AGENT),
        _ins("take_extra_turn", "500.7", ROLE_AGENT, ROLE_AMOUNT),
        _ins("end_the_turn", "724", ROLE_AGENT),
        _ins("skip_step", "500.8", ROLE_AGENT, ROLE_PATIENT),
        _ins("create_continuous_effect", "611", ROLE_PATIENT, ROLE_DURATION,
             note="a resolving instruction creating a RULE 611 continuous "
                  "effect (pump, an until-end-of-turn keyword grant). NOT a "
                  "RULE 613 static ability — those never enter the "
                  "instruction stream at all, see 14_ §1.1."),
        _ins("become_monarch", "725", ROLE_AGENT),
        _ins("take_initiative", "726", ROLE_AGENT),
        _ins("control_player", "723", ROLE_AGENT, ROLE_PATIENT, ROLE_DURATION),
        _ins("ascend", "702.131", ROLE_AGENT,
             note="get the city's blessing"),
        _ins("set_status", "110.6", ROLE_PATIENT,
             note="the designation/status markers that are not their own "
                  "RULE 701 keyword action — saddled, solved, prepared, "
                  "un-suspected, a recorded bend"),
        _ins("level_up", "711", ROLE_PATIENT, ROLE_AMOUNT,
             note="Leveler (RULE 711) and Class (RULE 716) level counters"),
        _ins("create_delayed_trigger", "603.7", ROLE_AGENT, ROLE_PATIENT,
             ROLE_DURATION),
        _ins("add_phase", "500.8", ROLE_AGENT, ROLE_PATIENT),
        _ins("imprint", "702.61", ROLE_AGENT, ROLE_PATIENT),
        _ins("mutate", "702.140", ROLE_AGENT, ROLE_PATIENT),
        _ins("phase_out", "702.26", ROLE_AGENT, ROLE_PATIENT),
        _ins("chaos_ensues", "901.15", ROLE_AGENT,
             note="Planechase (RULE 901) — the chaos ability of the face-up "
                  "plane. Sibling of planeswalk/set_in_motion/abandon, which "
                  "the CR does list under RULE 701."),
        _ins("choose", "601.2b", ROLE_AGENT, ROLE_PATIENT,
             note="the continuation point: the instruction stream suspends "
                  "here and resumes with the answer. ENG-35's subject."),
    )
}


# --- axis 3: the composition operators (ENG-37 / `14_` S3) -----------------

#: The nesting nodes ENG-37 adds to `EffectSpec`. Named here rather than in
#: `spec.py` because `14_` S0c makes the justification a property of *this*
#: inventory: an operator is warranted only by the fusions it retires, and
#: `tests/test_isa_inventory.py` fails an operator that names none.
OP_SEQ = "seq"
OP_IF_ELSE = "if_else"
OP_OPTIONAL = "optional"
OP_FOR_EACH = "for_each"
OP_BIND = "bind"

OPERATORS: tuple[str, ...] = (OP_SEQ, OP_IF_ELSE, OP_OPTIONAL, OP_FOR_EACH, OP_BIND)


class Classification(str, Enum):
    """What a registered effect type *is*, relative to the ISA.

    Five of these are `14_` S0a's own vocabulary. Two more —
    `STATIC` and `REPLACEMENT` — are a finding of doing the
    classification rather than a departure from it: `14_` §1.1 rules both
    out of the instruction stream on purpose (a RULE 613 static is a
    continuously re-derived constraint, a RULE 614 replacement is event
    middleware), so forcing either into "instruction" would put ~4,000
    lines of grammar in the wrong layer — the exact mistake §1.1 exists to
    prevent. They are recorded as what they are and excluded from the ISA
    coverage assertions.
    """

    #: A one-to-one realisation of an `INSTRUCTIONS` entry.
    INSTRUCTION = "instruction"
    #: Blocks on a player choice: a `request_*`/`resolve_*_choice` pair, or
    #: a type that opens a `pending_choice`. **ENG-35's backlog.**
    CONTINUATION = "continuation_pair"
    #: Two or more instructions welded into one type because the IR cannot
    #: sequence them. **ENG-37's backlog** — each names the operator that
    #: retires it.
    FUSION = "fusion"
    #: The same instruction as another entry, differing only on an operand
    #: (a narrower patient, a duration, a referent). Axis 1 × axis 2, spelled
    #: out as a new row.
    ALIAS = "alias"
    #: Bespoke: not decomposable into today's ISA. The honest residue.
    SPECIAL = "one_card_special"
    #: RULE 613 constraint, outside the instruction stream (`14_` §1.1).
    STATIC = "static"
    #: RULE 614/616 event middleware, outside the instruction stream.
    REPLACEMENT = "replacement"
    #: **Axis 3 itself** (ENG-37). `14_` §1.1 describes the effect types as a
    #: cross-product of operation × operands × composition × linkage and
    #: observes that the composition axis does not exist — which is exactly
    #: why `FUSION` has 84 members. These five types *are* that axis
    #: (`game/effects/composition.py`), so they are neither instructions nor
    #: fusions of instructions: they are what a fusion decomposes *into*.
    COMPOSITION = "composition"


@dataclass(frozen=True)
class TypeEntry:
    """One registered effect type's place in the factoring."""

    type_name: str
    classification: Classification
    #: For INSTRUCTION/ALIAS: the `INSTRUCTIONS` key it realises.
    instruction: Optional[str] = None
    #: For FUSION: the instructions it welds, in the order it runs them.
    parts: tuple[str, ...] = ()
    #: For FUSION: which `OPERATORS` entry retires it.
    operator: Optional[str] = None
    note: str = ""


# --- the classification tables ---------------------------------------------
#
# Source data, grouped by classification. `EFFECT_TYPES` is assembled from
# these at import; the tables are the readable, editable form. Adding a type
# to `EffectRegistry` without adding it to exactly one of these fails
# `tests/test_isa_inventory.py`.

#: INSTRUCTION — type name -> the ISA operation it realises one-to-one.
_INSTRUCTION_TYPES: dict[str, str] = {
    "adapt": "adapt",
    "add_counters": "put_counter",
    "add_mana": "add_mana",
    "amass": "amass",
    "attach": "attach",
    "become_copy_permanent": "copy_object",
    "become_monarch": "become_monarch",
    "blight": "blight",
    "bolster": "bolster",
    "chaos_ensues": "chaos_ensues",
    "clash": "clash",
    "class_level": "level_up",
    "coin_flip": "flip_coin",
    "collect_evidence": "collect_evidence",
    "connive": "connive",
    "control_change": "gain_control",
    "control_player": "control_player",
    "counter": "counter",
    "create_delayed_trigger": "create_delayed_trigger",
    "create_token": "create",
    "damage": "deal_damage",
    "destroy": "destroy",
    "detain": "detain",
    "discard": "discard",
    "discover": "discover",
    "draw": "draw",
    "earthbend": "earthbend",
    "end_the_turn": "end_the_turn",
    "endure": "endure",
    "exchange_control": "exchange",
    "exile": "exile",
    "explore": "explore",
    "extra_combat_phase": "add_phase",
    "fight": "fight",
    "forage": "forage",
    "gain_life": "gain_life",
    "get_city_blessing": "ascend",
    "goad": "goad",
    "grant_keyword": "create_continuous_effect",
    "imprint": "imprint",
    "learn": "learn",
    "lose_game": "lose_game",
    "lose_life": "lose_life",
    "manifest": "manifest",
    "manifest_dread": "manifest_dread",
    "mill": "mill",
    "monstrosity": "monstrosity",
    "move_counters": "move_counter",
    "mutate": "mutate",
    "phase_out": "phase_out",
    "planeswalk": "planeswalk",
    "populate": "populate",
    "proliferate": "proliferate",
    "recruit": "recruit",
    "regenerate": "regenerate",
    "remove_counters": "remove_counter",
    "sacrifice": "sacrifice",
    "scry": "scry",
    "search": "search",
    "set_life": "set_life",
    "shuffle": "shuffle",
    "skip_step": "skip_step",
    "surveil": "surveil",
    "suspect": "suspect",
    "take_extra_turn": "take_extra_turn",
    "take_initiative": "take_initiative",
    "tap": "tap",
    "the_ring_tempts_you": "ring_tempts_you",
    "time_travel": "time_travel",
    "transform": "transform",
    "untap_self": "untap",
    "venture": "venture",
    "vote": "vote",
    "win_game": "win_game",
}

#: ALIAS — type name -> the ISA operation it is a narrowed/renamed form of.
#: These are axis 1 × axis 2: the same operation with a different operand
#: (a specific patient, a duration, a referent), spelled out as its own
#: registry row because the frame is not expressible. `create_continuous_
#: effect` dominates for the same reason: every "gains <keyword> until end
#: of turn" grant is one operation with a different keyword operand.
_ALIAS_TYPES: dict[str, str] = {
    "add_counters_to_trigger_damaged_player": "put_counter",
    "add_player_counters": "put_counter",
    "attach_triggering_permanent": "attach",
    "attacker_creates_attacking_token": "create",
    "become_copy_until_eot": "copy_object",
    "become_prepared": "set_status",
    "become_saddled": "set_status",
    "become_solved": "set_status",
    "bounce_own_land_from_trigger": "move_object",
    "cant_block_this_turn": "create_continuous_effect",
    "cast_exiled_face_down": "cast",
    "cast_target_elemental_from_graveyard_free": "cast",
    "cheat_creature_from_hand": "move_object",
    "combat_restriction_this_turn": "create_continuous_effect",
    "copy_ability": "copy_object",
    "counter_ability": "counter",
    "copy_imprinted_card": "copy_object",
    "copy_permanent": "copy_object",
    "copy_spell": "copy_object",
    "create_emblem": "create",
    "create_token_for_linked_exile": "create",
    # ENG-37 re-derivation: not a `create`+`copy_object` weld. The "copy" is
    # the token's printed descriptor, resolved from a clamped card-*name*
    # string (parser data), never RULE 707 `copy_object` operating on a live
    # game object — that is `create_token_copy_of_linked_exile`, which stays a
    # fusion. This is `create` with a copy-descriptor operand.
    "create_token_copy_of_named": "create",
    "damage_equal_to_counters": "deal_damage",
    "damage_equal_to_power": "deal_damage",
    "damage_life_floor": "deal_damage",
    "deal_damage_to_chosen_player": "deal_damage",
    "destroy_each_with_mana_value": "destroy",
    "destroy_specific": "destroy",
    "dig_until": "reveal",
    "double_counters_on_target": "double",
    "draw_cards_discarded_delta": "draw",
    "draw_controlled_chosen_creature_type": "draw",
    "draw_each_player_with_creature_power": "draw",
    # ENG-37 re-derivation: a one-"part" fusion (`("draw",), if_else`) is not
    # a weld — it is one `draw` gated on a live board comparison ("its power
    # greater than each other creature's"), the same shape as the three
    # dynamically-scoped `draw_*` aliases above. The bespoke gate is a
    # condition operand, not a second instruction.
    "draw_if_trigger_object_greatest_power": "draw",
    "draw_per_attached_aura_controller": "draw",
    "each_creature_you_control_damages_each_opponent": "deal_damage",
    "each_opponent_counter_own_creature": "put_counter",
    "exchange_control_spell": "exchange",
    "exchange_life_total_with_toughness": "exchange",
    "exchange_life_totals": "exchange",
    "exile_all_graveyards": "exile",
    "exile_any_number_you_control": "exile",
    "exile_library": "exile",
    "exile_own_graveyard_card_mana_value_x": "exile",
    "exile_specific": "exile",
    "exile_target_graveyard": "exile",
    "exile_top_of_library": "exile",
    "exile_trigger_damaged_creature": "exile",
    "exile_until_duplicate_name": "exile",
    "free_cast_from_hand": "cast",
    "gain_control_attached": "gain_control",
    "gain_control_by_source": "gain_control",
    "gain_control_of_all_commanders": "gain_control",
    "gain_control_of_spell": "gain_control",
    "gain_control_until_eot": "gain_control",
    "gain_target_activated_abilities": "create_continuous_effect",
    "grant_activated_ability": "create_continuous_effect",
    "grant_borrowed_activated_ability": "create_continuous_effect",
    "grant_cant_be_countered": "create_continuous_effect",
    "grant_cant_be_target_of_spell_color": "create_continuous_effect",
    "grant_cant_lose_this_turn": "create_continuous_effect",
    "grant_cycling_to_hand": "create_continuous_effect",
    "grant_damage_multiplier_this_turn": "create_continuous_effect",
    "grant_die_to_exile_this_turn": "create_continuous_effect",
    "grant_escape": "create_continuous_effect",
    "grant_evoke": "create_continuous_effect",
    "grant_flash_until_eot": "create_continuous_effect",
    "grant_flashback_to_target": "create_continuous_effect",
    "grant_graveyard_cast_permission_this_turn": "create_continuous_effect",
    "grant_keyword_to_trigger_subject": "create_continuous_effect",
    "grant_keywords_to_chosen_type_until_eot": "create_continuous_effect",
    "grant_life_for_mana_pip": "create_continuous_effect",
    "grant_mana_ability": "create_continuous_effect",
    "grant_protection": "create_continuous_effect",
    "grant_retrace": "create_continuous_effect",
    "grant_self_activated_ability": "create_continuous_effect",
    "grant_skip_extra_turns": "create_continuous_effect",
    "grant_static_ability": "create_continuous_effect",
    "grant_triggered_ability": "create_continuous_effect",
    "grant_until": "create_continuous_effect",
    "graveyard_play_permission_this_turn": "create_continuous_effect",
    "graveyard_to_library_bottom_random": "move_object",
    "haunt_linked_death": "create_delayed_trigger",
    "install_temporary_player_trigger": "create_delayed_trigger",
    "look_at_cards": "reveal",
    "lose_all_player_counters": "remove_counter",
    "lose_game_trigger_damaged_player": "lose_game",
    "mark_cant_be_countered": "create_continuous_effect",
    "mark_your_spells_on_stack_cant_be_countered": "create_continuous_effect",
    "mill_until_creature": "mill",
    "move_all_plus_one_counters_from_self": "move_counter",
    "phase_out_all_you_control": "phase_out",
    "prevent_all_combat_damage": "prevent_damage",
    "prevent_attacking_player_this_turn": "create_continuous_effect",
    "prevent_damage_from_target": "prevent_damage",
    "prevent_damage_shield": "prevent_damage",
    "pt_set": "create_continuous_effect",
    "pt_switch": "create_continuous_effect",
    "pump": "create_continuous_effect",
    "put_commander_into_hand": "move_object",
    "put_equal_or_lesser_mv_from_hand": "move_object",
    "put_from_hand_onto_battlefield": "move_object",
    "put_hand_cards_on_top": "move_object",
    "put_self_onto_battlefield_from_hand": "move_object",
    "radiation_life_gain": "gain_life",
    "record_bend": "set_status",
    "regain_control_of_owned_creatures": "gain_control",
    "remove_all_abilities": "create_continuous_effect",
    "remove_keyword": "create_continuous_effect",
    "remove_suspected": "set_status",
    "return_all_exiled_with": "move_object",
    "return_chosen_creature_type_from_graveyard": "move_object",
    "return_creatures_by_power_parity": "move_object",
    "return_dying_subject_to_battlefield": "move_object",
    "return_from_graveyard": "move_object",
    "return_linked_exile": "move_object",
    "return_self_from_graveyard": "move_object",
    "return_self_from_graveyard_to_hand": "move_object",
    "return_self_from_graveyard_untargeted": "move_object",
    "return_self_to_battlefield": "move_object",
    "return_shared_type_permanent": "move_object",
    "return_specific_to_hand": "move_object",
    "return_to_hand": "move_object",
    "return_to_library": "move_object",
    "return_uncast_exiled": "move_object",
    # ENG-37 batch 3 (`14_` S3, B8): one atomic engine primitive each,
    # untargeted + always-self, despite a multi-part `parts` tuple — the same
    # "welds only on paper" case as the shuffle family. The rules-salient
    # action is a RULE 712.8 transform (a permanent ends up as its other
    # face); the exile / graveyard round-trip is the *mechanism* that yields a
    # fresh RULE 400.7 object, an operand of `transform` rather than a second
    # instruction. `reveal_top_then_transform` is a `transform` gated on a
    # library-top `criteria` check with no "else" branch — a condition
    # operand, exactly like `draw_if_trigger_object_greatest_power` → `draw`
    # (batch 2). (`dies_return_as_enchantment` / `return_dies_as_new_permanent`
    # / `put_hand_card_on_bottom_then_draw` were checked the same way and stay
    # fusions: the first appends a type-setting static to the *returned*
    # object, the second builds a synthetic card and can take a RULE 115
    # target, the third is a genuine move-then-draw.)
    "exile_return_transformed": "transform",
    "return_from_graveyard_transformed": "transform",
    "reveal_top_then_transform": "transform",
    "reveal_until": "reveal",
    "sacrifice_attached_permanent": "sacrifice",
    "sacrifice_permanents_per_counter": "sacrifice",
    "sacrifice_self": "sacrifice",
    "sacrifice_specific": "sacrifice",
    "set_copy_target": "copy_object",
    "set_forced_voter": "vote",
    # ENG-37 re-derivation: RULE 701.24 shuffle already subsumes moving the
    # cards in — "shuffle <X> into <a> library" is one atomic action, not a
    # `move_object`+`shuffle` weld. `shuffle_self_into_library` is the Aura/
    # self form; `shuffle_graveyard_into_library` the whole-graveyard form
    # (Paradigm Shift). Both read as one instruction with a ``subject``
    # operand. (`shuffle_target_graveyard_cards_into_library` is *not* here —
    # it opens a RULE 601.2c pick, so it is continuation-shaped, not an alias.)
    "shuffle_graveyard_into_library": "shuffle",
    "shuffle_self_into_library": "shuffle",
    "skip_next_untap": "skip_step",
    "skip_untap_step": "skip_step",
    "subject_damages_each_opponent_equal_to_power": "deal_damage",
    "tap_matching_lands": "tap",
    "tap_permanents_per_counter": "tap",
    "target_player_counter_each_creature": "put_counter",
    "text_change": "create_continuous_effect",
    "top_up_player_counter": "put_counter",
    "transform_named_tokens": "transform",
    "type_change": "create_continuous_effect",
    "unblockable": "create_continuous_effect",
}

#: FUSION — type name -> (the instructions it welds, the operator that
#: retires it). **This is ENG-37's backlog.** Every entry here exists only
#: because `EffectSpec` has no node for the composition in the third field;
#: closing ENG-37 means deleting these registry rows, not reimplementing
#: them.
_FUSION_TYPES: dict[str, tuple[tuple[str, ...], str]] = {
    "add_counter_first_strike": (("put_counter", "create_continuous_effect"), OP_SEQ),
    "blink": (("exile", "move_object"), OP_SEQ),
    "cast_graveyard_instant_sorcery_free_exile": (("cast", "exile"), OP_SEQ),
    "collect_evidence_x_then_board_damage": (("collect_evidence", "deal_damage"), OP_SEQ),
    "conditional_copy": (("copy_object", "copy_object"), OP_IF_ELSE),
    "copy_attachments_onto_last_created": (("copy_object", "attach"), OP_BIND),
    "copy_self_controlled_by_previous_target": (("copy_object", "gain_control"), OP_BIND),
    "copy_self_if_cast_from_graveyard": (("copy_object", "copy_object"), OP_IF_ELSE),
    "copy_spell_and_bounce": (("copy_object", "move_object"), OP_SEQ),
    "counter_create_token": (("counter", "create"), OP_SEQ),
    "counter_then_fightlike_damage": (("counter", "deal_damage"), OP_SEQ),
    "counter_untap_grant_keyword": (("counter", "untap", "create_continuous_effect"), OP_SEQ),
    "create_attached_aura_token": (("create", "attach"), OP_SEQ),
    "create_token_copy_of_linked_exile": (("create", "copy_object"), OP_BIND),
    "create_token_may_attach_equipment": (("create", "attach"), OP_OPTIONAL),
    "create_tokens_per_counter_among_target_player_creatures": (("create",), OP_FOR_EACH),
    "damage_and_drain_capped": (("deal_damage", "gain_life"), OP_SEQ),
    "damage_then_investigate_if_excess": (("deal_damage", "investigate"), OP_IF_ELSE),
    "destroy_artifacts_enchantments_then_counters": (("destroy", "put_counter"), OP_SEQ),
    "destroy_controller_may_search_basic_land": (("destroy", "search"), OP_OPTIONAL),
    "destroy_create_token": (("destroy", "create"), OP_SEQ),
    "destroy_exile_then_controller_reveal_creature": (("destroy", "exile", "reveal"), OP_SEQ),
    "dies_return_as_enchantment": (("create_delayed_trigger", "move_object"), OP_SEQ),
    "discard_up_to_then_draw_that_many": (("discard", "draw"), OP_BIND),
    "draw_lose_life_counter_removed_delta": (("draw", "lose_life"), OP_BIND),
    "draw_mill_if_discarded": (("draw", "mill"), OP_IF_ELSE),
    "draw_reveal_cast_one_free": (("draw", "reveal", "cast"), OP_SEQ),
    "each_player_counter_then_protection": (("put_counter", "create_continuous_effect"), OP_FOR_EACH),
    "each_player_exile_from_graveyard_then_counters": (("exile", "put_counter"), OP_FOR_EACH),
    "exchange_control_then_copy_token": (("exchange", "copy_object"), OP_SEQ),
    "exchange_control_then_energy_sacrifice": (("exchange", "pay_cost", "sacrifice"), OP_SEQ),
    "exile_cast_spell_into_imprint_pool": (("exile", "imprint"), OP_SEQ),
    "exile_controller_searches_basic_land": (("exile", "search"), OP_SEQ),
    "exile_create_token": (("exile", "create"), OP_SEQ),
    "exile_discount_cost": (("exile", "create_continuous_effect"), OP_SEQ),
    "exile_graveyard_card_counter_if_permanent": (("exile", "put_counter"), OP_IF_ELSE),
    "exile_graveyard_creatures_gain_life": (("exile", "gain_life"), OP_BIND),
    "exile_hand_then_draw_that_many": (("exile", "draw"), OP_BIND),
    "exile_opponents_graveyards_impulsive_cast": (("exile", "cast"), OP_SEQ),
    "exile_then_reveal_greater_mana_value": (("exile", "reveal"), OP_SEQ),
    "exile_top_from_each_player_cast_free": (("exile", "cast"), OP_FOR_EACH),
    "exile_top_then_damage_by_mv": (("exile", "deal_damage"), OP_BIND),
    "exile_top_then_grant_conditional_cast": (("exile", "create_continuous_effect"), OP_SEQ),
    "exile_triggering_discard_may_play_this_turn": (("exile", "create_continuous_effect"), OP_SEQ),
    "haunt": (("exile", "create_delayed_trigger"), OP_SEQ),
    "impulsive_draw": (("exile", "create_continuous_effect"), OP_SEQ),
    "mill_then_damage_each_opponent_by_mv": (("mill", "deal_damage"), OP_BIND),
    "owner_draw_others_lose_per_dying_counter": (("draw", "lose_life"), OP_FOR_EACH),
    "pay_life_equal_to_opponents_combat_damaged_draw_that_many": (("pay_cost", "draw"), OP_BIND),
    "put_hand_card_on_bottom_then_draw": (("move_object", "draw"), OP_SEQ),
    "remove_counters_from_among_then_draw_lose_life": (("remove_counter", "draw", "lose_life"), OP_SEQ),
    "return_creature_grant_indestructible": (("move_object", "create_continuous_effect"), OP_SEQ),
    "return_dies_as_new_permanent": (("create_delayed_trigger", "move_object"), OP_SEQ),
    "return_to_hand_draw_if_controlled": (("move_object", "draw"), OP_IF_ELSE),
    "return_to_library_then_dig_shared_type": (("move_object", "search"), OP_SEQ),
    "return_top_graveyard_creature_with_haste": (("move_object", "create_continuous_effect"), OP_SEQ),
    "reveal_top_conditional_to_hand": (("reveal", "move_object"), OP_IF_ELSE),
    "reveal_top_then_counter_if_mv_match": (("reveal", "counter"), OP_IF_ELSE),
    "reveal_top_then_creature_and_or_land_battlefield": (("reveal", "move_object"), OP_SEQ),
    "reveal_top_then_free_cast_if_mv_match": (("reveal", "cast"), OP_IF_ELSE),
    "reveal_top_then_land_battlefield_or_draw": (("reveal", "move_object", "draw"), OP_IF_ELSE),
    "reveal_top_then_maybe_battlefield_if_land_or_cheap_creature": (("reveal", "move_object"), OP_IF_ELSE),
    "reveal_top_then_take_and_lose_life": (("reveal", "move_object", "lose_life"), OP_SEQ),
    "sacrifice_any_number_draw_lose_scaled": (("sacrifice", "draw", "lose_life"), OP_BIND),
    "sacrifice_count_draw_lose": (("sacrifice", "draw", "lose_life"), OP_BIND),
    "shuffle_target_graveyard_cards_into_library": (("move_object", "shuffle"), OP_SEQ),
    "shuffle_target_into_library_reveal_top": (("move_object", "shuffle", "reveal"), OP_SEQ),
    "target_player_draw_lose_life": (("draw", "lose_life"), OP_SEQ),
    "taxed_draw": (("pay_cost", "draw"), OP_SEQ),
    "unattach_tap_indestructible": (("attach", "tap", "create_continuous_effect"), OP_SEQ),
    "wheel": (("discard", "draw"), OP_BIND),
    "wheel_of_fortune": (("discard", "draw"), OP_BIND),
    "windfall": (("discard", "draw"), OP_BIND),
}

#: CONTINUATION — every type that suspends on a player answer. **ENG-35's
#: backlog.** Value is the CR rule the choice comes from, so the sweep can
#: be checked against the rules rather than against a naming convention.
_CONTINUATION_TYPES: dict[str, str] = {
    "all_players_decline_or": "118.3",
    "attach_chosen": "601.2b",
    "cascade": "702.85",
    "change_target": "115.4",
    "choose_basic_land_type_on_enter": "601.2b",
    "choose_card_name_on_enter": "601.2b",
    "choose_color_on_enter": "601.2b",
    "choose_creature_type_on_enter": "601.2b",
    "choose_named_mode": "700.2",
    "choose_number_on_enter": "601.2b",
    "choose_objects": "601.2b",
    "choose_permanent": "601.2b",
    "choose_source_coinflip": "705",
    "choose_targets": "601.2c",
    "choose_void_counter_card": "601.2b",
    "counter_unless_pay": "118.3",
    "cumulative_upkeep": "702.23",
    "currency_converter_cash_out": "601.2b",
    "currency_converter_resolve": "601.2b",
    "dance_with_calamity": "601.2b",
    "destroy_unless_pay": "118.3",
    "discard_or_lose_life": "701.9",
    "each_player_pay_or": "118.3",
    "enter_as_copy": "614.1c",
    "face_villainous_choice": "701.55",
    "immoral_bargain": "601.2b",
    "immoral_bargain_destroy": "601.2b",
    "impulsive_look": "601.2b",
    "inspect_top_choose": "601.2b",
    "intuition_search": "701.23",
    "land_or_free_cast": "601.2b",
    "look_top_keep_one_on_top": "601.2b",
    "look_top_pay_life_loop": "118.3",
    "look_top_select": "601.2b",
    "may_behold_untap_linked": "701.4",
    "may_discard_then_draw_mill": "601.2b",
    "may_exile_source_then": "118.3",
    "name_card_then": "701.20",
    "pay_cost_then": "118.3",
    "pay_cost_then_previous_mv": "118.3",
    "pay_energy_then": "122",
    "peek_top_land_battlefield_tapped": "601.2b",
    "peek_top_land_or_hand": "601.2b",
    "remove_counter_or_sacrifice": "118.3",
    "repeat_process": "601.2b",
    "_request_choose_creature_type_grant": "601.2b",
    "_request_choose_player": "601.2b",
    "request_prevent_damage_source": "615",
    "request_redirect_damage_source": "616",
    "reveal_hand_choose_discard": "701.9",
    "reveal_top_hand_lose_life_loop": "601.2b",
    "sacrifice_unless_pay": "701.17",
    "scroll_rack_exile": "601.2b",
    "scroll_rack_finish": "601.2b",
    "slithermuse": "601.2b",
    "sylvan_library": "118.3",
    "transmute_artifact": "118.3",
    "vote_object": "701.38",
    "word_of_command": "723",
}

#: STATIC — RULE 613 constraints. Registered because `StaticAbility` builds
#: through the same registry, but outside the instruction stream entirely
#: (`14_` §1.1): they are continuously re-derived by `continuous.recompute`,
#: never executed. Composition operators do not apply to them.
_STATIC_TYPES: frozenset[str] = frozenset({
    "activation_prohibition", "anthem", "attack_tax", "cant_attack_defender",
    "cant_be_countered", "cast_limit", "cast_prohibition", "color_change",
    "combat_restriction", "cost_reduction", "cost_restriction",
    "damage_cant_be_prevented", "disable_damage_prevention", "draw_limit",
    "extra_land_drop", "extra_land_play", "flash_permission",
    "free_cast_permission", "goaded", "grant_any_color_for_activation",
    "grant_protection_static", "grant_search_limited_to_top_n",
    "grant_search_prohibited", "granted_alt_cast_cost",
    "graveyard_cast_permission", "graveyard_library_cast_prohibition",
    "graveyard_library_entry_prohibition", "hand_size_modifier",
    "ignore_legend_rule", "no_max_hand_size", "no_max_hand_size_rest_of_game",
    "no_untap", "no_untap_optional", "player_cast_restriction", "pt_cda",
    "self_graveyard_or_exile_cast_permission", "set_max_life_total",
    "sorcery_speed_only", "top_library_permission", "trigger_prohibition",
    "untap_cap",
})

#: REPLACEMENT — RULE 614/616 event middleware. Also outside the instruction
#: stream (`14_` §1.1): a replacement rewrites an event before it happens
#: rather than sequencing instructions, which is why `14_` §8 leaves open
#: whether these get their own operators (`instead`, `rather than`) instead
#: of reusing the branch node.
_REPLACEMENT_TYPES: frozenset[str] = frozenset({
    "dungeon_room_trigger_doubler", "enters_tapped_static", "extra_etb_counter",
    "global_wither", "graveyard_redirect", "graveyard_redirect_to_exile_this_turn",
    "mana_multiplier", "mana_type_override", "mirror_produced_mana",
    "multiply_damage_from_target", "prevent_all_life_gain", "prevent_life_gain",
    "search_redirect", "trigger_doubler", "uncast_creature_entry_exile",
    "void_counter_redirect",
})

#: SPECIAL — the honest residue: types that do not decompose into today's
#: ISA. Value names the card (or family) each was written for. This list
#: shrinking is a better health signal than coverage moving.
_SPECIAL_TYPES: dict[str, str] = {
    "abstract_performance": "Abstract Performance",
    "advanced_reconstruction_l1": "Advanced Reconstruction",
    "animists_awakening": "Animist's Awakening",
    "arm_spell_watcher": "Arm (equipment-trigger watcher)",
    "back_from_the_brink": "Back from the Brink",
    "base0_combat_damage_fractal": "Fractal (base 0/0 combat damage)",
    "become_aura": "Licid family",
    "brudiclad_become_copies": "Brudiclad, Telchor Engineer",
    "brudiclad_combat": "Brudiclad, Telchor Engineer",
    "budget_dig_onto_battlefield": "Budget-constrained dig",
    "celestial_reunion_search": "Celestial Reunion",
    "cultural_exchange": "Cultural Exchange",
    "cultural_exchange_round2": "Cultural Exchange",
    "descendants_fury_sacrifice": "Descendants' Fury",
    "specialize": "Specialize (Duskmourn) — parked, see DEFERRED.md",
    "double_cast_x": "X-doubling cast family",
    "expressive_iteration": "Expressive Iteration",
    "expressive_iteration_exile_step": "Expressive Iteration",
    "expressive_iteration_finish": "Expressive Iteration",
    "expropriate_gain_control": "Expropriate",
    "gift_of_immortality_dies": "Gift of Immortality",
    "hofri_ghostforge_dies": "Hofri Ghostforge",
    "intermediate_chirography_l3": "Intermediate Chirography",
    "juxtapose": "Juxtapose",
    "kindred_summons": "Kindred Summons",
    "legendary_spell_free_dig": "Legendary-spell dig family",
    "licid_become_aura": "Licid family",
    "licid_revert": "Licid family",
    "memory_vampire_combat": "Memory Vampire",
    "mirrorwing_copy": "Mirrorwing Dragon",
    "mutual_reveal_compare_mana_value": "mutual-reveal comparison family",
    "nils_end_step_counters": "Nils, Discipline Enforcer",
    "ojer_kaslem_land_pick": "Ojer Kaslem, Deepest Growth",
    "oversimplify": "Oversimplify",
    "plargg_and_nassari": "Plargg and Nassari",
    "random_graveyard_exile_copy_loop": "random graveyard-copy loop family",
    "redoubled_stormsinger_copies": "Redoubled Stormsinger",
    "scramble_spell": "Scrambleverse family",
    "surge_to_victory": "Surge to Victory",
    "tragic_arrogance": "Tragic Arrogance",
    "triple_exchange": "three-way exchange family",
    "zimone_all_questioning_end_step": "Zimone, All-Questioning",
}


#: COMPOSITION — axis 3's own types (ENG-37), one per `OPERATORS` entry.
#: Registered in `game/effects/composition.py`; each retires the `_FUSION_
#: TYPES` rows naming its operator (`fusions_retired_by`).
_COMPOSITION_TYPES: dict[str, str] = {
    "seq": OP_SEQ,
    "if_else": OP_IF_ELSE,
    "optional": OP_OPTIONAL,
    "for_each": OP_FOR_EACH,
    "bind": OP_BIND,
}


def _build_effect_types() -> dict[str, TypeEntry]:
    """Assemble `EFFECT_TYPES` from the tables above.

    Raises on a type classified twice — the tables are meant to partition,
    and a duplicate would silently pick one label under the precedence rule
    instead of surfacing the disagreement.
    """
    out: dict[str, TypeEntry] = {}

    def _add(entry: TypeEntry) -> None:
        if entry.type_name in out:
            raise ValueError(
                f"effect type {entry.type_name!r} is classified twice: "
                f"{out[entry.type_name].classification.value} and "
                f"{entry.classification.value}"
            )
        out[entry.type_name] = entry

    for name, instruction in _INSTRUCTION_TYPES.items():
        _add(TypeEntry(name, Classification.INSTRUCTION, instruction=instruction))
    for name, instruction in _ALIAS_TYPES.items():
        _add(TypeEntry(name, Classification.ALIAS, instruction=instruction))
    for name, (parts, operator) in _FUSION_TYPES.items():
        _add(TypeEntry(name, Classification.FUSION, parts=parts, operator=operator))
    for name, rule in _CONTINUATION_TYPES.items():
        _add(TypeEntry(name, Classification.CONTINUATION, note=f"RULE {rule}"))
    for name in sorted(_STATIC_TYPES):
        _add(TypeEntry(name, Classification.STATIC))
    for name in sorted(_REPLACEMENT_TYPES):
        _add(TypeEntry(name, Classification.REPLACEMENT))
    for name, operator in _COMPOSITION_TYPES.items():
        _add(TypeEntry(name, Classification.COMPOSITION, operator=operator))
    for name, card in _SPECIAL_TYPES.items():
        _add(TypeEntry(name, Classification.SPECIAL, note=card))
    return out


#: Every registered effect type, classified. Keyed by the `EffectRegistry`
#: type string.
EFFECT_TYPES: dict[str, TypeEntry] = _build_effect_types()


#: `13_` §5.6(b)'s operation ranking, re-derived by `scripts/isa_report.py
#: --corpus` against the coverage ledger at PARSER_VERSION 298 (51,288 atoms
#: decomposed out of 25,896 unclaimed clauses; 81.9% invoke a known
#: operation; 83 distinct operations occur; **these 50 carry 99.5% of them**).
#:
#: Frozen here as data because it is **ENG-34's exit criterion** — "every
#: top-50 corpus operation has a named instruction with a frame" — and
#: `tests/test_isa_inventory.py` has to be able to check it without the
#: ledger, which is a developer artifact rather than a committed fixture.
#: Re-derive with the script (and update this list) after a coverage run.
#:
#: This is also `14_`'s **cheap-exit checkpoint**: the design says S0b is
#: where the whole atom/composition programme can still be abandoned cheaply
#: if operand frames turn out not to canonicalize. They do — all 50 map onto
#: a single framed instruction, and the head of the distribution
#: (`choose`, `gain_control`, `create_continuous_effect`, `put_counter`,
#: `cast`) is exactly the shape `14_` predicted.
TOP_CORPUS_OPERATIONS: tuple[str, ...] = (
    "choose",
    "gain_control",
    "create_continuous_effect",
    "put_counter",
    "cast",
    "deal_damage",
    "exile",
    "create",
    "sacrifice",
    "move_object",
    "end_the_turn",
    "draw",
    "reveal",
    "counter",
    "gain_life",
    "destroy",
    "activate",
    "discard",
    "shuffle",
    "lose_life",
    "search",
    "untap",
    "tap",
    "pay_cost",
    "play",
    "remove_counter",
    "mill",
    "prevent_damage",
    "copy_object",
    "roll_die",
    "phase_out",
    "attach",
    "add_mana",
    "scry",
    "regenerate",
    "double",
    "flip_coin",
    "win_game",
    "transform",
    "fight",
    "goad",
    "vote",
    "surveil",
    "move_counter",
    "investigate",
    "manifest",
    "proliferate",
    "amass",
    "take_extra_turn",
    "skip_step",
)

# --- queries ---------------------------------------------------------------

def classification_of(effect_type: str) -> Optional[Classification]:
    """The classification of one registered effect type, or None."""
    entry = EFFECT_TYPES.get(effect_type)
    return entry.classification if entry else None


def types_classified(classification: Classification) -> tuple[str, ...]:
    """Every effect type carrying ``classification``, sorted."""
    return tuple(sorted(
        name for name, e in EFFECT_TYPES.items()
        if e.classification is classification
    ))


def fusions_retired_by(operator: str) -> tuple[str, ...]:
    """The fusion types ``operator`` retires — ENG-37's per-operator exit.

    `14_` S0c: an operator with nothing here is not yet justified.
    """
    return tuple(sorted(
        name for name, e in EFFECT_TYPES.items()
        if e.classification is Classification.FUSION and e.operator == operator
    ))


def instruction_histogram() -> dict[str, int]:
    """How many registered types collapse onto each ISA instruction.

    The tall bars are where axis 2 is doing the work a declared frame
    should: every "gains <keyword> until end of turn" is one operation
    wearing a different operand.
    """
    counts: dict[str, int] = {}
    for entry in EFFECT_TYPES.values():
        for name in ((entry.instruction,) if entry.instruction else entry.parts):
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
