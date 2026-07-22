"""Step 4: the coverage gate + the front-end entry point (docs/09).

Reference: docs/concepts/09_ORACLE_EFFECT_PARSER.md ("THE COVERAGE GATE: FAIL-CLOSED,
ALL-OR-NOTHING" and "THE FRONT-END PIPELINE"). This is where the pipeline
comes together: `parse_oracle(card)` runs normalise → segment → match over a
card's oracle text and returns the parsed `AbilitySpec`s **plus a coverage
verdict**.

The gate is all-or-nothing: a card is `MODELED` only if *every* ability line
is claimed — a keyword line (accounted for by the keyword catalogue, anchored
on Scryfall's array), a triggered ability, or a resolve-time effect. Any
unclaimed line makes the whole card `UNMODELED`, and its unclaimed lines are
surfaced (the seed of docs/09's processing list). A half-modeled card that
silently resolves *some* of its text is worse than one honestly not modeled,
so the binder only trusts effect specs from a `MODELED` card.

Pure — **no `game/` imports** (front-end security boundary).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Optional

from .catalogue.counters import entry_counters_condition
from .catalogue.keywords import parse_keywords
from .catalogue.lands import tap_clause_condition
from .catalogue.levels import (
    LEVEL_UP_LINE_RE,
    PT_LINE_RE,
    split_class_blocks,
    split_leveler_blocks,
)
from .catalogue.modal import MODAL_HEADER_RE, collect_mode_bodies, split_modal_block
from .catalogue.static_handlers import commander_eligibility_line
from .normalize import normalize
from .segmenter import (
    Segment,
    _TRIGGER_RE,
    _trigger_condition,
    _trigger_event,
    parse_effect_body,
    segment_line,
)
from .spec import AbilitySpec, EffectSpec, ParserProvenance

MODELED = "MODELED"
UNMODELED = "UNMODELED"
#: Stickers (RULE 123) are a permanent project non-goal — see
#: `backend/ToDo_Backend.md` — not a "not yet" gap like an ordinary
#: UNMODELED card. Any card mentioning them is classified `NEVER_SUPPORTED`
#: instead of `UNMODELED` so its unclaimed clauses never surface in the
#: processing-list backlog ranking (they'd otherwise sit there forever,
#: since no handler will ever claim them).
NEVER_SUPPORTED = "NEVER_SUPPORTED"

#: Bumped when the catalogue/pipeline changes shape; stamped on every spec's
#: provenance so a cached parse can be invalidated (docs/09 "Versioning").
#: "3": Batch 1 — self-reference fold ("this creature"→~) + firebreathing /
#: until-EOT activated pumps + sorcery-speed-only activation marker.
#: "4": Batch 2 — combat-restriction family (can't attack/block/be blocked,
#: attacks each combat if able, activated-ability lock), no_untap generalized
#: to attached_permanent, and a self-reference fix in `_NO_UNTAP_RE` (the
#: Batch 1 fold left its old "this <type>" wording dead).
#: "5": Batch 3 — "you control enchanted creature/permanent" (control_change)
#: + Aura/Equipment quoted ability grants ("has \"<ability>\"") for
#: self-scoped ENTERS_BATTLEFIELD/DIES/ATTACKS/BLOCKS triggers, recursively
#: parsed via `segmenter.segment_line` and wrapped as `grant_triggered_
#: ability`. Deliberately excludes activated-ability grants and DAMAGE/
#: phase-scoped triggers (see `static_handlers._GRANTABLE_TRIGGER_EVENTS`).
#: "6": Batch 4 — RULE 207.2c ability-word stripping (Landfall/Constellation/
#: Battalion, `normalize._strip_ability_words`); controller-scoped phase
#: triggers ("at the beginning of your/each opponent's <step>",
#: `AbilitySpec.trigger["phase_relation"]`); self-subject "deals (combat)
#: damage to a player/creature" (`EventType.DAMAGE` + filter); and extending
#: `grant_triggered_ability`/`continuous._granted_trigger_condition` to
#: DAMAGE events, closing Batch 3's deferred quoted-DAMAGE-grant gap.
#: "7": Batch 5 — modal-block cleanup: bare "proliferate" (RULE 701.30, the
#: effect already existed, just had no oracle-text handler); targeted
#: "target player gains/loses N life" (`GainLifeEffect`/`LoseLifeEffect`
#: `target_kind="player"`); and a new "target creature with power/
#: toughness/keyword quality" filter (`targeting.TargetSpec.creature_filter`)
#: for `destroy`/`exile`.
#: "8": Batch 6 — cost-keyword mechanics recognition bugs: `keywords._resolve`
#: generalized to the ``<type>cycling`` family (Plainscycling/Basic
#: landcycling/Wizardcycling/…), mirroring the existing ``<type>walk``
#: generalization; `segmenter`'s keyword-line check gained the alias
#: spellings (`ALIAS_DISPLAYS` — Multikicker/Megamorph/Basic landcycling/
#: Partner with/…) `KEYWORDS` alone never carried, plus a comma-split that
#: only splits before a *new* recognised keyword instead of blindly on every
#: comma (fixes Escape/Ward/Kicker's own compound cost clauses and Partner
#: with's comma-containing name being wrongly read as a second, unrecognized
#: token). Also a new kicked-conditional "enters with N counters" shape
#: (`counters.py`'s ``kicked_gate``/``kicked_scale``, `GameObject.
#: kicker_count`-driven) for "if ~ was kicked, it enters with N counters on
#: it."/"~ enters with N counters on it for each time it was kicked."
#: "9": Batch 7 — RULE 601.2b "as ~ enters, choose a creature type/color"
#: (`static_handlers.enter_choice_specs`, a new `enter_replacement` family
#: alongside "enter as a copy of target X" — `ChooseCreatureTypeReplacement`/
#: `ChooseColorReplacement`, `RulesEngine._offer_enter_choices`/
#: `resolve_enter_choice`, `GameObject.chosen_type`/`chosen_color`); the
#: dynamic "… of the chosen type/color …" anthem/grant tail
#: (`subtype_from_source`/`color_from_source`) and "~ is the chosen type in
#: addition to its other types" (`add_subtypes_from_source`, layer 4); a
#: granted landwalk variant via the plain "have <keyword>" family
#: (`_flag_keywords`, `combat._landwalk_slugs` already reads the raw slug);
#: and the board-wide "all creatures get -N/-N until end of turn" pump group
#: selector (`catalogue.handlers._GROUP`). Also fixed `ParseResult.
#: effect_specs` never including ``enter_replacement`` specs at all — a
#: latent bug since Clever Impersonator's hand-authored entry predates this
#: property (hand-authored specs bypass it), but it would have silently
#: dropped every *oracle-parsed* enter_replacement ability, including this
#: batch's, for an unregistered card.
#: "10": Batch 8 — three "permission" statics that aren't about a
#: permanent's own characteristics: "you may play an additional land on
#: each of your turns" (`extra_land_drop`, `continuous.extra_land_plays_for`
#: — its one-turn resolve-time sibling "…this turn" is a new
#: `catalogue.handlers` row, `extra_land_play`/`ExtraLandPlayEffect`); "you
#: have no maximum hand size" (`no_max_hand_size`, `continuous.
#: has_no_maximum_hand_size`); and "you may choose not to untap ~ during
#: your untap step" (`no_untap_optional`, gated on a new sticky
#: `GameObject.skip_untap` toggle — `GameEngine.set_skip_untap` — since the
#: engine has no mid-untap-step pause to ask fresh each turn).
#: "11": Batch 9 — "exile ~/this saga, then return it to the battlefield
#: transformed under its owner's control" (`exile_return_transformed` —
#: RULE 400.7 + RULE 712.8 combined, a transforming Saga's own final
#: chapter, Fable of the Mirror-Breaker-shaped, or an activated ability's
#: own flip phrased this way instead of a bare "transform ~",
#: Ayara/Clive/Jin-Gitaxias-shaped).
#: "13": Batch 10 — Monarch/Initiative/Emblem (RULE 725/726/114): "you
#: become the monarch"/"you take the initiative" (plain designation grants,
#: `RulesEngine.become_monarch`/`take_initiative`) and "you get an emblem
#: with '<ability>'" (`create_emblem`, the quoted ability recursively
#: parsed into a full nested `AbilitySpec` and bound at resolve time against
#: a synthetic `Emblem` source — `models/emblem.py`). "12" was consumed by a
#: concurrent Batch 9 coverage re-measure before this batch's own code
#: landed, so it's skipped here rather than reused for a different card set.
#: "14": the cross-target-constraints/counters backlog item — "remove up to
#: N counters from target permanent/creature" (Glissa Sunslayer/Heartless
#: Act/Render Inert-shaped chosen-amount `remove_counters`), Innkeeper's
#: Talent's causer-scoped `double_counters` ("if you would put … on a
#: permanent or player"), Mechanized Warfare's compound "a red or artifact
#: source" `additional_damage` filter, and the "N target X controlled by
#: different players/controllers" cross-target constraint on
#: `destroy`/`exile` (Protector of the Wastes-shaped).
#: "19": the Search/tutor & graveyard batch — "exile target player's
#: graveyard"/"exile all cards from target player's graveyard" (Bojuka
#: Bog/Tormod's Crypt-shaped whole-graveyard exile, `exile_target_graveyard`)
#: and "return it to the battlefield transformed under its owner's control"
#: (Bruce Banner-shaped graveyard-sourced forced flip,
#: `return_from_graveyard_transformed`).
#: "20": Stickers (RULE 123) declared a permanent non-goal — any card whose
#: oracle text mentions "sticker" now gets the new `NEVER_SUPPORTED`
#: verdict (`_mentions_stickers`) instead of `UNMODELED`, so it stops
#: contributing unclaimed clauses to the processing-list backlog.
#: "21": RULE 728 Rad counters' oracle-text grammar — "[you/target player/
#: defending player/each player/each opponent] get[s] N/X rad counters",
#: "target player loses all rad counters", and "each opponent gets a
#: number of rad counters equal to its power" (`add_player_counters`/
#: `lose_all_player_counters`/`dies_grants_rad_counters_equal_power`), plus
#: "You gain life rather than lose life from radiation." (`radiation_life_
#: gain`). The "that many"/dynamic-player combat-damage shape (Glowing
#: One/Infesting Radroach) is hand-authored in `ability_catalogue.py`
#: instead — no oracle-text grammar change for that half.
#: "22": Rad-counter deferred-gap closeout batch (Acquired Mutation/Bloatfly
#: Swarm/Contaminated Drink/Harold and Bob/Mariposa Military Base/
#: Nuka-Nuke Launcher/Struggle for Project Purity/The Ghoul, Gunslinger/The
#: Wise Mothman/Vault 12/Vexing Radgull). New `segmenter.py` grammar:
#: "enchanted/equipped creature <verb>" subject (`_ATTACHED_SUBJECT_RE`,
#: `{"subject": "attached_permanent"}`); tribal "a/another/~ or another
#: [nontoken] <subtype>[...] you control <verb>" subjects
#: (`_GROUP_SUBTYPE_SUBJECT_RE`/`_SELF_OR_GROUP_SUBTYPE_RE`, checked *after*
#: the pre-existing exact-main-type `_GROUP_SUBJECT_RE` so a bare "creature"
#: still matches the original, more specific pattern first); "if that
#: player is(n't) you, <rest>" target-based intervening-if
#: (`_TARGET_IS_CONTROLLER_RE`, `condition={"target_is_controller": bool}`);
#: and "~ <verb1> or <verb2>" compound multi-event triggers
#: (`_SELF_MULTI_EVENT_RE`, `trigger["event"]` as a `list[str]`). New
#: `catalogue/handlers.py` grammar: "get half X rad counters, rounded
#: up/down" (`_substitute_x`'s new `"half_x_up"`/`"half_x_down"` sentinels);
#: "create a Treasure/Clue/Food token" (`_create_named_token`); and "draw X
#: cards" (literal-X, `COUNT_X`/`count_or_x_of` widening the pre-existing
#: digit/word-only `draw` grammar). New `catalogue/lands.py` grammar: "you
#: may have this land enter tapped. If you do, you get N rad counters."
#: (`_OPTIONAL_BONUS_RAD_RE`, `{"kind": "optional_bonus_rad"}`). Widened
#: `spec.py` validation: `rad_counters_on_combat_damage`'s `"else"`
#: (`"proliferate"`) and `"kind"` keys; a third `enter_replacement` "named
#: mode" variant (`ChooseNamedModeReplacement`/`GameObject.chosen_mode`)
#: alongside the existing creature-type/color choices; and a new
#: `rad_counters_on_attacked` marker (RULE 506.4 "attacks you with N
#: creatures", `EventType.PLAYER_ATTACKED`, fired once per attacker/
#: defender pair leaving `declare_attackers`, distinct from the
#: once-per-creature `ATTACKS` event).
#: "23": Library-top/impulsive-draw permissions closeout — the generic "You
#: may play lands [and cast [noncreature] spells [with mana value N or
#: greater]] from the top of your library" static (`static_handlers.
#: _TOP_LIBRARY_PERMISSION_RE`/`_TOP_LIBRARY_VERB_PARAMS`, the oracle-text
#: sibling of the two hand-authored `top_library_permission` catalogue
#: entries — Future Sight/Experimental Frenzy-shaped), plus its optional
#: same-line "If you cast a spell this way, ..." conditional tail: "you may
#: cast it as though it had flash" (Elsha of the Infinite, `TopLibrary
#: PermissionEffect.grants_flash`, `top_library.
#: may_cast_flash_from_top_of_library`) or "pay life equal to its mana value
#: rather than pay its mana cost" (Bolas's Citadel, `.life_payment`, a new
#: RULE 118 alternative-cost substitution applied automatically by
#: `GameEngine._top_library_life_payment`, never opt-in). Also a new
#: `noncreature_only` restriction (Elsha's own "noncreature spells" gate,
#: `top_library._grant_permits_cast`) and a "Play with the top card of your
#: library revealed." no-op line (`segmenter._PLAY_WITH_TOP_REVEALED_RE`,
#: mirroring the pre-existing "look at any time" no-op).
#: "25": Replacement-effects batch — RULE 616.1's damage-multiplying family
#: gains oracle-text recognition (`catalogue/replacements.py`):
#: Furnace of Rath/Dictate of the Twin Gods's unscoped "if a source would
#: deal damage..., it deals double that damage instead" and Fiery
#: Emancipation's "triple" sibling (`double_damage`'s new ``multiplier``
#: param), plus Gratuitous Violence's own narrower "a creature you
#: control" phrasing (`double_damage`'s new ``creature_only`` param — also
#: fixing a latent bug: the hand-authored catalogue entry had wrongly
#: required ``combat_only``, a restriction the real printed text has never
#: had). Also new this batch (no coverage-gate impact — these live outside
#: the oracle-effect IR): the one-shot `prevent_damage_shield` family
#: (Riot Control/Thought Lash, hand-authored — `PreventDamageEffect`/
#: `RulesEngine.prevent_damage_to_player`); Lurrus of the Dream-Den's own
#: trailing "exile instead of graveyard" clause
#: (`GraveyardCastPermissionEffect.exile_if_would_be_put_into_graveyard`);
#: two new `game/mana_abilities.py` RULE 605.3a restriction kinds —
#: `chosen_type_spell` (Cavern of Souls/Unclaimed Territory, resolved
#: per-instance off `GameObject.chosen_type` at tap time) and
#: `mana_value_or_x_spell` (Helga, Skittish Seer/Troyan, Gutsy Explorer);
#: and RULE 122's "Pay {E}" activated-ability cost pips
#: (`ActivationCost.pay_energy`, `costs.py` — previously silently
#: discarded).
#: "26": Replacement-effects/mana closeout batch — the rest of the
#: "Replacement effects / mana" ToDo section. New RULE 616.1 replacement
#: families (`catalogue/replacements.py`): life-gain rewrite (Angel of
#: Vitality's additive "plus N", Boon Reflection/Alhammarret's Archive's
#: "twice" — `gain_life_replacement` on a new `EventType.LIFE_GAIN`
#: pre-event routed through `RulesEngine.gain_life`); recipient-scoped
#: +1/+1 counter replacement (Hardened Scales/Conclave Mentor additive,
#: Branching Evolution/Corpsejack Menace double, Kami of Whispered Hopes
#: permanent-scoped — `_double_counters_replacement`'s new `plus`/
#: `multiplier`/`recipient` params + `recipient_controller_id`/`recipient_
#: is_creature` on the COUNTER event); and "if ~ would die, exile it
#: instead" (Gloomshrieker/Corpseweaver Prodigy — `die_to_exile`, a new
#: `EventType.WOULD_DIE` fired by `_move_to_graveyard`). Throne of Eldraine
#: fully MODELED: chosen-colour mana production ("Add N mana of the chosen
#: color", `ManaAbility.color_selector`), a `monocolored_spell`-of-chosen-
#: colour spend restriction, and its second ability's colour-locked
#: activation cost (`ActivationCost.spend_only_chosen_color`, enforced by
#: `GameEngine._chosen_color_locked_cost`). Energy: the resolve-time
#: optional "you may pay {E}{E}. If you do, `<effect>`." (Aether Chaser,
#: `pay_energy_then`/`PayEnergyThenEffect` + interactive `RulesEngine.
#: request_pay_energy_then` choice) and the "you get {E}{E}" production
#: (`get_energy` → the generic `add_player_counters` energy primitive).
#: "27": Triggers/grants closeout batch — the whole "Triggers / grants"
#: ToDo section, seven items. (1) **Group-subject damage triggers**:
#: `_SELF_DAMAGE_TRIGGER_RE` → `_DAMAGE_TRIGGER_RE`, now also claiming
#: "whenever a/an/another `<type>` [you control] deals [combat] damage to a
#: player/creature" (Bident of Thassa/Defiling Daemogoth), with DAMAGE's
#: group-controller key (``source_controller_id``) and `_build_group_ok`'s
#: object key generalized to `_subject_event_key` (``source_id``).
#: The article alternation also gained "an" — every vowel-initial group
#: subject ("an enchantment you control dies") had been failing closed.
#: (2) **"Sacrifice ~ unless you pay `<cost>`."** (45 cards, the biggest
#: remaining upkeep-trigger template) — a real interactive pay-or-lose-it
#: `pending_choice`, built on ward's machinery (`_can_pay_player_cost`/
#: `_pay_player_cost`, generalized out of `resolve_ward_effect`) rather
#: than a second copy; deliberately a *closed* cost vocabulary, since
#: `parse_activation_cost` returns a **free** cost for text it doesn't
#: understand. (3) **Quoted granted phase/upkeep triggers** —
#: ``STEP_BEGIN`` joins `_GRANTABLE_TRIGGER_EVENTS`, with the segmenter's
#: ``phase_relation`` threaded through so `continuous._granted_trigger_
#: condition` resolves "your" against the *granted-to* permanent's
#: controller (Commander's Authority/Clawing Torment). (4) **Aura lifecycle
#: triggers** — RULE 700.4's long "is put into a graveyard from the
#: battlefield" folded to "dies" in `normalize` (which also required
#: `_move_to_graveyard` to stop firing `DIES` for creatures *only*), plus
#: `ReturnToHandEffect`'s self form (Rancor/Flickering Ward) and
#: "enchanted permanent"/"enchanted land" in `_ATTACHED_SUBJECT`.
#: (5) **Standing granted protection** (RULE 702.16) — a real layer-6
#: concept (`grant_protection_static`/`GameObject._granted_protections`),
#: the continuously-re-derived sibling of the resolve-time
#: `temp_protections` grant: Hungry Lynx/Righteous War/Absolute Grace, and
#: the RULE 601.2b dynamic "protection from the chosen color" (Voice of
#: All). (6) **Type grants past the battlefield** (RULE 613.4a) —
#: `continuous._apply_off_battlefield_types`, a dedicated pass over the
#: controller's non-battlefield zones + their spells on the stack, for
#: Arcane Adaptation/Leyline of Transformation's "creature cards you own
#: that aren't on the battlefield" and Ashes of the Fallen's graveyard
#: form; the battlefield half of the same family (Xenograft/Realmwright/
#: Lifecraft Engine) is the new group sibling of `_IS_CHOSEN_TYPE_RE`.
#: (7) **Quoted mana-ability grants** — "Elves you control have '{T}: Add
#: {B}.'" (Tyvar Kell) / "Enchanted land has '{T}: Add 1 mana of any
#: color.'" (Abundant Growth): recognized directly by `static_handlers.
#: _granted_mana_options` rather than the nested `segment_line` parse,
#: since a plain mana ability is claimed-*without*-a-spec by the segmenter.
PARSER_VERSION = "27"


@dataclass
class ParseResult:
    """The front-end's output for one card: specs + a fail-closed coverage verdict."""

    specs: list[AbilitySpec] = field(default_factory=list)
    coverage: str = MODELED
    #: Unclaimed ability lines (template seeds for the processing list, docs/09).
    unclaimed: list[str] = field(default_factory=list)

    @property
    def modeled(self) -> bool:
        return self.coverage == MODELED

    @property
    def never_supported(self) -> bool:
        """RULE 123 Stickers — a permanent non-goal, not an ordinary gap."""
        return self.coverage == NEVER_SUPPORTED

    #: The effect-bearing specs (triggered / spell_effect / activated /
    #: static / replacement / enter_replacement) parsed from text — as
    #: opposed to the keyword specs, which are safe individually. The binder
    #: only trusts these when the whole card is `MODELED`. ``enter_
    #: replacement`` (RULE 601.2b/614.1c/614.12 "as ~ enters" — Card-pool
    #: Batch 7's "choose a creature type/color", `static_handlers.
    #: enter_choice_specs`) was added alongside the other five here so
    #: `ability_catalogue.specs_for` actually binds it for an unregistered
    #: MODELED card, not just keeps it visible on `specs`.
    @property
    def effect_specs(self) -> list[AbilitySpec]:
        return [
            s for s in self.specs
            if s.ability_kind in (
                "triggered", "spell_effect", "activated", "static", "replacement",
                "enter_replacement",
            )
        ]


def _mentions_stickers(raw: str) -> bool:
    """RULE 123 Stickers — declared a permanent non-goal (see
    `backend/ToDo_Backend.md`), not merely deprioritized. A simple
    substring check is deliberate: real sticker cards say "sticker sheet"/
    "sticker" in their own oracle text (there is no other card-text idiom
    that uses the word), so this never needs the segmenter/normalize
    machinery to decide — it's an early exit, not a parsed clause.
    """
    return "sticker" in raw.lower()


def _is_spell(card: Any) -> bool:
    return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))


def _split_triggered_modal_block(
    lines: list[str], start: int
) -> Optional[tuple[str, dict[str, Any], bool, int, list[str], int]]:
    """A permanent's modal *triggered* ability: "When ~ enters, choose 1 —"
    on one line, then two or more "• " mode lines (RULE 700.2 wrapped in a
    RULE 603.1 trigger) — the trigger-wrapped sibling of `split_modal_block`
    (a modal *spell*'s bare header). Both a recognised trigger event/subject
    scope (`_trigger_event`/`_trigger_condition`, the same grammar
    `segment_line` uses for an ordinary triggered ability) and a modal
    header are required; unlike a plain triggered ability's body, the modal
    header's "effect" is the whole bullet block, not `trig.group("body")`
    itself.

    Returns ``(event, condition, or_both, or_more, choose, mode_bodies,
    next_index)``, or ``None`` if ``lines[start]`` isn't this shape at all,
    or ``choose`` exceeds the number of mode lines actually printed —
    fail-closed, the caller falls back to ordinary per-line segmentation.
    """
    trig = _TRIGGER_RE.match(lines[start].strip())
    if trig is None:
        return None
    header = MODAL_HEADER_RE.match(trig.group("body").strip())
    if header is None:
        return None
    event = _trigger_event(trig.group("cond"))
    if event is None:
        return None
    condition = _trigger_condition(trig.group("cond"))
    if condition is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    mode_bodies, next_i = collected
    choose = int(header.group("n"))
    if choose < 1 or choose > len(mode_bodies):
        return None
    return (
        event,
        condition,
        bool(header.group("or_both")),
        bool(header.group("or_more")),
        choose,
        mode_bodies,
        next_i,
    )


def _parse_mode_body(body: str) -> Optional[list[EffectSpec]]:
    """One modal "• " line's effect body → its `EffectSpec`s, or ``None``.

    Tries the bullet as-is first; some cards print an optional mode *name*
    ahead of the effect ("Fight the Current — Return target nonland
    permanent to its owner's hand.", RULE 700.2's "mode text" convention) —
    if the whole bullet doesn't parse and it contains a dash, retry with
    just the text after it.
    """
    effects = parse_effect_body(body)
    if effects is not None:
        return effects
    if " — " in body:
        _, _, rest = body.partition(" — ")
        effects = parse_effect_body(rest.strip())
        if effects is not None:
            return effects
    return None


def _parse_mode_options(
    mode_bodies: list[str],
) -> Optional[tuple[list[list[EffectSpec]], list[str]]]:
    """Each "• " mode body → its `EffectSpec`s, or ``None`` if any one fails
    (fail-closed — a modal block is never half-claimed). Shared by a modal
    spell's and a modal triggered ability's block processing."""
    options: list[list[EffectSpec]] = []
    descriptions: list[str] = []
    for body in mode_bodies:
        effects = _parse_mode_body(body)
        if effects is None:
            return None
        options.append(effects)
        descriptions.append(body)
    return options, descriptions


#: Parse-on-load memoization (docs/09 "parse-on-load / bind-per-game
#: linking"): `parse_oracle` is a pure function of a handful of a card's
#: fields (see `_parse_cache_key`), but re-runs the full normalise →
#: segment → match pipeline from scratch on every call — and it's called
#: once per `GameObject` built (`ability_catalogue.specs_for`), so the same
#: popular card (Sol Ring, Swords to Plowshares, …) gets re-parsed on every
#: copy, every game. Cache the `ParseResult` per distinct input; unbounded
#: is fine here — the key space is the real card pool (tens of thousands),
#: each entry a handful of small dataclasses, and a process's `CardDatabase`
#: already holds every card it has ever loaded in memory anyway (docs/09
#: versioning: bump `PARSER_VERSION` and clear this alongside a pipeline
#: change if a stale entry from a previous version ever mattered — today
#: nothing persists this cache across a process restart, so it never does).
_PARSE_CACHE: dict[tuple[Any, ...], ParseResult] = {}


def _parse_cache_key(card: Any) -> tuple[Any, ...]:
    """Every field `_parse_oracle_uncached`/`parse_keywords` actually reads.

    Content-keyed rather than identity- or name-keyed on purpose: a fixture
    `Card` built fresh per test (or a real card whose row gets refetched
    with updated text) must not collide with a stale cache entry that
    merely shares a name.
    """
    return (
        getattr(card, "name", "") or "",
        getattr(card, "oracle_text", "") or "",
        tuple(getattr(card, "keywords", None) or ()),
        bool(getattr(card, "is_instant", False)),
        bool(getattr(card, "is_sorcery", False)),
        bool(getattr(card, "is_saga", False)),
        bool(getattr(card, "is_leveler", False)),
        bool(getattr(card, "is_class", False)),
    )


def parse_oracle(card: Any) -> ParseResult:
    """Memoized entry point — see `_parse_oracle_uncached` for the real work.

    Returns a deep copy of the cached `ParseResult` so a caller is always
    free to treat its `AbilitySpec`s as its own (matches
    `ability_catalogue.register`'s "factory returns fresh specs each call"
    contract for the hand-authored registry) even though the parse itself
    now runs at most once per distinct input.
    """
    key = _parse_cache_key(card)
    cached = _PARSE_CACHE.get(key)
    if cached is None:
        cached = _parse_oracle_uncached(card)
        _PARSE_CACHE[key] = cached
    return copy.deepcopy(cached)


def _parse_oracle_uncached(card: Any) -> ParseResult:
    """Parse a card's oracle text into `AbilitySpec`s with a coverage verdict.

    Keyword specs come from the keyword catalogue (anchored on Scryfall's
    ``keywords`` array); the remaining lines are normalised, segmented, and run
    through the effect-handler table. A card with no oracle text (a vanilla
    creature) is trivially `MODELED` with no specs.

    A Leveler (RULE 711.4c) or a Class (RULE 716.3) prints a multi-line
    **block** structure ordinary per-line segmentation can't see across —
    each block's body lines only apply while the object's own level/class-
    level counter is in that block's range. `_process_line` is the ordinary
    per-line dispatch this function always used; `_process_leveler_body`/
    `_process_class_body` wrap it to also tag the resulting specs with that
    gating (consumed by `continuous.group_selector_objects` for static specs,
    `effect_binder._trigger_condition` for triggered ones — both via
    `min_level`/`max_level`/`level_counter`).
    """
    provenance = ParserProvenance(version=PARSER_VERSION, source="rule:oracle")
    keyword_specs = parse_keywords(card)

    raw = getattr(card, "oracle_text", "") or ""
    if _mentions_stickers(raw):
        # Fail-closed the same way as an ordinary UNMODELED card (the
        # binder never sees these specs' effects — there are none), but
        # tagged distinctly and with no `unclaimed` seeds so this card
        # never shows up in the processing-list backlog (see
        # `NEVER_SUPPORTED`'s docstring above).
        return ParseResult(specs=list(keyword_specs), coverage=NEVER_SUPPORTED)
    normalized = normalize(raw, getattr(card, "name", None))
    if not normalized:
        return ParseResult(specs=list(keyword_specs), coverage=MODELED)

    allow_spell_effect = _is_spell(card)
    is_saga = bool(getattr(card, "is_saga", False))
    is_leveler = bool(getattr(card, "is_leveler", False))
    is_class = bool(getattr(card, "is_class", False))
    effect_specs: list[AbilitySpec] = []
    unclaimed: list[str] = []
    all_claimed = True

    def _process_line(line: str) -> None:
        nonlocal all_claimed
        # RULE 614.1 "enters tapped" clauses are covered by the engine's own
        # tapped-entry machinery (`game/ability_catalogue.land_tap_condition`,
        # resolved by `RulesEngine.enter_land_tapped`), not through an effect
        # spec — claim the line without emitting one, the same way a mana
        # ability's "add {g}" is covered-without-spec in the segmenter.
        if tap_clause_condition(line) is not None:
            return
        # RULE 614.1-style "enters with N counters" clauses: same split as
        # tapped-entry above — covered by `game/ability_catalogue.
        # entry_counters` (`RulesEngine`'s battlefield-entry resolution),
        # not an effect spec.
        if entry_counters_condition(line) is not None:
            return
        # RULE 903.3 "~ can be your commander." — a deck-legality permission
        # with no in-game behavioral effect (see `commander_eligibility_line`'s
        # docstring): claim the line, contribute nothing, same split as the
        # two tapped-entry/counter checks above.
        if commander_eligibility_line(line):
            return
        seg: Segment = segment_line(
            line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
        )
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
        elif seg.spec is not None:
            effect_specs.append(seg.spec)

    def _tag_level_gate(
        spec: AbilitySpec, gate: dict[str, Any], default_affects: Optional[str]
    ) -> None:
        if spec.ability_kind == "static":
            for effect in spec.effects:
                if default_affects is not None:
                    effect.params.setdefault("affects", default_affects)
                effect.params.update(gate)
            effect_specs.append(spec)
        elif spec.ability_kind == "triggered":
            spec.trigger = {**(spec.trigger or {}), **gate}
            effect_specs.append(spec)
        else:
            effect_specs.append(spec)

    def _grant_keyword_line_spec(line: str, affects: str, gate: dict[str, Any]) -> AbilitySpec:
        keywords = [k.strip() for k in line.split(",") if k.strip()]
        return AbilitySpec(
            "static",
            effects=[EffectSpec("grant_keyword", {"keywords": keywords, "affects": affects, **gate})],
            raw_text=line,
            parser=provenance,
        )

    def _process_leveler_body(line: str, lo: int, hi: Optional[int]) -> None:
        nonlocal all_claimed
        gate = {"min_level": lo, "max_level": hi}
        pt = PT_LINE_RE.match(line.strip())
        if pt is not None:
            power, toughness = pt.group("power"), pt.group("toughness")
            if power == "*" or toughness == "*":
                # CDA-based Leveler P/T isn't modeled (no card in the pool
                # needs it) — fail closed rather than guess.
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(AbilitySpec(
                "static",
                effects=[EffectSpec("pt_set", {
                    "power": int(power), "toughness": int(toughness), "affects": "self", **gate,
                })],
                raw_text=line, parser=provenance,
            ))
            return
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.keyword_line:
            # A tier-scoped keyword line ("Flying, haste" under LEVEL 7+)
            # becomes a level-gated grant, not an unconditional intrinsic
            # keyword — `parse_keywords`'s Leveler cross-check already
            # excludes these from the always-on set for exactly this reason.
            effect_specs.append(_grant_keyword_line_spec(line, "self", gate))
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects="self")

    def _process_modal_block(
        header: str, or_both: bool, or_more: bool, choose: int, mode_bodies: list[str]
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2: a modal spell's own bare header. A permanent's modal
        # *triggered* ability ("When ~ enters, choose one —") is a different
        # shape (the header trails a trigger wrapper) — see
        # `_process_triggered_modal_block` below.
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {b}" for b in mode_bodies)
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "spell_effect",
            effects=[],
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_triggered_modal_block(
        header: str,
        event: str,
        condition: dict[str, Any],
        or_both: bool,
        or_more: bool,
        choose: int,
        mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2 wrapped in a RULE 603.1 trigger — e.g. "When ~ enters
        # the battlefield, choose one — • Mode A. • Mode B.": the chosen
        # mode is picked interactively as the ability is put on the stack
        # (`game/rules_engine.py`'s `trigger_mode` choice), not at cast time
        # like a modal spell.
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {b}" for b in mode_bodies)
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "triggered",
            effects=[],
            trigger={"event": event, "condition": condition},
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_class_body(line: str, level: int) -> None:
        nonlocal all_claimed
        gate = {"min_level": level, "level_counter": "class_level"}
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects=None)

    if is_leveler:
        preamble, blocks = split_leveler_blocks(normalized)
        for line in preamble:
            level_up = LEVEL_UP_LINE_RE.match(line.strip())
            if level_up is not None:
                # RULE 711.4a: the actual "put a level counter on this,
                # sorcery speed only" mechanic — see `LEVEL_UP_LINE_RE`'s
                # docstring for why this can't just fall through to the
                # generic per-line dispatch.
                effect_specs.append(AbilitySpec(
                    "activated",
                    effects=[EffectSpec("add_counters", {"amount": 1, "kind": "level"})],
                    cost={"text": level_up.group("cost"), "sorcery_speed_only": True},
                    raw_text=line, parser=provenance,
                ))
                continue
            _process_line(line)
        for lo, hi, body_lines in blocks:
            for line in body_lines:
                _process_leveler_body(line, lo, hi)
    elif is_class:
        preamble, blocks = split_class_blocks(normalized)
        for line in preamble:
            _process_line(line)
        for level, cost_text, body_lines in blocks:
            # RULE 716.3/716.4c: "<cost>: Level N" is itself a sorcery-speed
            # activated ability, legal only from the level just below it
            # (`GameEngine._can_activate_class_level`) — the header carries
            # no effect body of its own to segment (the effect is "become
            # this level", `ClassLevelEffect`), unlike an ordinary "<cost>:
            # <effect>" line.
            effect_specs.append(AbilitySpec(
                "activated",
                effects=[EffectSpec("class_level", {"level": level})],
                cost={"text": cost_text, "sorcery_speed_only": True, "class_level": level},
                raw_text=f"{cost_text}: level {level}",
                parser=provenance,
            ))
            for line in body_lines:
                _process_class_body(line, level)
    else:
        lines = [line for line in normalized.split("\n") if line.strip()]
        i = 0
        while i < len(lines):
            block = split_modal_block(lines, i) if allow_spell_effect else None
            if block is not None:
                or_both, or_more, choose, mode_bodies, next_i = block
                _process_modal_block(lines[i], or_both, or_more, choose, mode_bodies)
                i = next_i
                continue
            trig_block = _split_triggered_modal_block(lines, i)
            if trig_block is not None:
                event, condition, or_both, or_more, choose, mode_bodies, next_i = trig_block
                _process_triggered_modal_block(
                    lines[i], event, condition, or_both, or_more, choose, mode_bodies
                )
                i = next_i
                continue
            _process_line(lines[i])
            i += 1

    return ParseResult(
        specs=list(keyword_specs) + effect_specs,
        coverage=MODELED if all_claimed else UNMODELED,
        unclaimed=unclaimed,
    )
