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
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .catalogue.counters import entry_counters_condition
from .catalogue.keywords import parse_keywords
from .catalogue.kicker_mana import kicker_x_mana_restriction_condition
from .catalogue.lands import tap_clause_condition, tapped_entry_choice_tail
from .catalogue.levels import (
    CLASS_BECOMES_LEVEL_RE,
    LEVEL_UP_LINE_RE,
    PT_LINE_RE,
    split_class_blocks,
    split_leveler_blocks,
)
from .catalogue.modal import (
    CONDITIONAL_MODAL_HEADER_RE, MODAL_HEADER_RE, conditional_modal_override,
    collect_mode_bodies, split_modal_block, split_named_choice_block, split_spree_block,
)
from .catalogue.opening_hand import (
    opening_hand_battlefield_conditional_permission_line,
    opening_hand_battlefield_permission_line,
    opening_hand_graveyard_permission_line,
)
from .catalogue.station import split_station_blocks, station_creature_threshold
from .catalogue.handlers import ACTION_ONCE_PER_TURN_MARKER
from .catalogue.static_handlers import commander_eligibility_line, deck_any_number_line
from .normalize import normalize
from .segmenter import (
    FLASHBACK_DISCOUNT_LINE_RE,
    Segment,
    _peel_optional,
    _TRIGGER_RE,
    parse_effect_body,
    segment_line,
)
from .spec import AbilitySpec, EffectSpec, ParserProvenance, contains_marker, fold_action_limit

MODELED = "MODELED"
UNMODELED = "UNMODELED"
#: Stickers (RULE 123) are a permanent project non-goal — see
#: `docs/implementation-state/DEFERRED.md` — not a "not yet" gap like an ordinary
#: UNMODELED card. Sticker Sheets and cards mentioning them are `NEVER_SUPPORTED`
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
#: `_resume_choose_creature_type`, `GameObject.chosen_type`/`chosen_color`); the
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
#: One/Infesting Radroach) is hand-authored in `card_catalogue`
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
#: _request_pay_energy_then` choice) and the "you get {E}{E}" production
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
#:
#: **Version 29** — the *qualified* combat-restriction family (RULE
#: 508.1a/509.1b), closing `BACKLOG.md`'s "Combat statics" section:
#: (1) **Blocking filters** — "~ can't be blocked by creatures with power 2
#: or less"/"…except by Walls"/"…by more than one creature"/"…except by two
#: or more creatures", plus their resolve-time "…this turn" sibling. These
#: carry a parameter the synthetic flag keywords can't, so they bind to a
#: new ``combat_restriction`` `StaticAbility` (`game/combat.py`'s
#: `COMBAT_RESTRICTIONS`) evaluated at combat time rather than a layer.
#: (2) **Conditional restrictions** — "~ can't attack/block[ or block]
#: unless <condition>", over a closed board/turn-state condition vocabulary
#: (`GameEngine._COMBAT_CONDITIONS`).
#: (3) **"…alone"** — the "can't attack/block alone" restrictions *and* the
#: "whenever ~/a Samurai you control attacks alone" trigger, which needed a
#: new aggregate `EventType.ATTACKS_ALONE` (fired once combat locks in, for
#: the same reason `PLAYER_ATTACKED` is aggregate).
#: (4) **"…unless they're mana abilities"** — the RULE 605.1a carve-out on
#: an activation prohibition.
#: (5) **"Target creature can't block this turn"** — the family's largest
#: half and an ordinary one-shot effect, not a static (`CantBlockEffect` →
#: `GameObject.temp_cant_block`), with N-target and untargeted mass forms.
#:
#: **Version 30** — the three RULE 508/509 families version 29 deliberately
#: left open (`BACKLOG.md`'s "Combat statics" residue):
#: (1) **Combat requirements** (RULE 509.1c/d) — "~ must be blocked if
#: able."/"All creatures able to block ~ do so." as synthetic flag keywords
#: (`"must_be_blocked"`/`"all_must_block"`, the same `grant_keyword` plumbing
#: `"attacks_if_able"` already uses), checked by `GameEngine.
#: _enforce_block_requirements` as the declare-blockers step closes; plus
#: their resolve-time, *pairwise* siblings "target creature blocks ~ this
#: turn if able."/"…can't block ~ this turn." (naming a specific attacker,
#: so they ride `GrantCombatRestrictionEffect`'s new ``restrict_to_source``
#: instead of a bare flag) and "target creature attacks this turn if able."
#: (a plain temporary keyword grant — `combat.has()` already unions in a
#: `temp_keywords` grant, so no new engine code was needed for that one).
#: (2) **Multi-block permissions** (RULE 509.1b) — "~ can block an
#: additional creature each combat."/"~ can block any number of creatures.",
#: a `combat_restriction` param entry (`"extra_blocks"`/`"unlimited_blocks"`)
#: read by the new `GameObject.additional_blocking` list and `game/combat.
#: py`'s `max_blocks_for`/`has_block_capacity` — `GameEngine.can_block`'s old
#: bare "not already blocking" check generalizes to a capacity check, and
#: combat damage (`_split_blocker_damage`) divides a multi-blocker's power
#: evenly across every attacker it's blocking.
#:
#: **Version 31** — the two narrow parser-only gaps version 30's own ToDo
#: entry left open, closing `BACKLOG.md`'s "Combat statics" section
#: entirely:
#: (1) **A count-selector threshold instead of a literal int** — "Creatures
#: with power less than the number of Islands you control can't block ~."
#: (Kraken of the Straits). `object_filter`'s ``_POWER_LT_COUNT_RE`` maps a
#: basic land type to a new ``power_lt_count_selector`` filter key
#: (`combat.matches_object_filter`, threaded a ``state`` param for the first
#: time), resolved fresh at combat time against `continuous.count_selector`'s
#: new ``lands_you_control_of_type_<x>`` entry — scoped to the *attacker's*
#: controller (RULE 613.7c: "you" is always the ability's own source's
#: controller), not the blocker being checked.
#: (2) **A group scope with its own qualifier** — "Each creature you control
#: **with power 4 or greater** can't be blocked by more than one creature."
#: (Challenger Troll/Flopsie, Bumi's Buddy; Delney, Streetwise Lookout
#: combines this with an independent filtered tail in the same sentence).
#: `_QUALIFIED_SUBJECT` gained a trailing qualifier group, and
#: `continuous.group_selector_objects` a ``min_power``/``max_power``/
#: ``min_toughness``/``max_toughness`` per-object narrowing — which is also
#: why `continuous.recompute` now stamps the whole ``combat_restriction``
#: bucket *after* the layer-7 P/T pass instead of before it: a qualifier has
#: to see an anthem that already fired this same recompute, not last pass's
#: stale derived power.
#:
#: v32: "Each land is a <BasicType> in addition to its other land types."
#: (Urborg, Tomb of Yawgmoth/Yavimaya, Cradle of Growth — `static_handlers.
#: _LAND_IS_BASIC_TYPE_RE`, a new `type_change`/``add_subtypes`` clause) plus
#: a reshape of the existing "Nonbasic lands are <BasicType>." handler
#: (Blood Moon/Magus of the Moon) to drop its hand-paired
#: ``grant_mana_ability`` spec in favour of `game/mana_abilities.py`'s
#: generic RULE 305.6 derivation — same ``modeled`` verdict for Blood Moon,
#: but a different `EffectSpec` shape, so cached rows need re-parsing.
#: 33: Class (RULE 716) residual edges — "When this Class becomes level N,
#: <effect>." (`CLASS_BECOMES_LEVEL_RE`) and "When this Class enters, …"/
#: "…dies"/"…attacks"/"…blocks" (`segmenter._SELF_SUBJECT_RE` gaining
#: "class") are both now recognized instead of failing the whole card
#: closed — real cached cards affected: Ranger Class, Rogue Class, Party
#: Dude, Fighter Class, Blacksmith's Talent, Builder's Talent, Hunter's
#: Talent, Intermediate Chirography, Sorcerer/A-Sorcerer Class,
#: Stormchaser's Talent, Does Machines, Alchemist's Talent, Bandit's
#: Talent (the "enters" fix) and Wizard/A-Wizard Class, Monk Class,
#: Artificer Class, Caretaker's Talent, Cleric Class, Cool but Rude,
#: Warlock Class, Builder's Talent again, A-Druid/Druid Class (the
#: "becomes level N" fix) — though most still have a *different*,
#: unrelated unclaimed line (general trigger/effect coverage, independent
#: of this fix) so don't all flip to MODELED outright.
#: "34": Battles (RULE 310). `normalize._SELF_REFERENCE_RE` folds "this
#: battle"/"this Siege" to ``~`` — without it every real battle was
#: UNMODELED on its own ETB line ("When this Siege enters, …"), 0/39 of the
#: cached battle pool. Plus three shared-grammar widenings the battles
#: motivated but that are not battle-specific: RULE 115.4's "any **other**
#: target" (`subgrammars._TARGET_ROWS`, onto the existing ``any`` kind,
#: whose candidate list already excludes the source); "target creature an
#: opponent controls"/"…you don't control" onto the existing
#: ``creature_you_dont_control`` kind, with `_pump_target` widened to accept
#: the controller-scoped creature kinds; and the discard handler gaining
#: "target opponent"/"each player"/"each opponent" subjects — which also
#: fixed a latent bug where "target player discards a card" made the
#: *source's controller* discard, since `_discard` never passed a
#: ``target_kind`` through to `DiscardEffect`. Battle pool: 0 → 12 MODELED.
#:
#: 36 (2026-07-28): RULE 603.1 trigger conditions with a **player** subject —
#: "whenever you scry" / "whenever you surveil" / "whenever you scry or
#: surveil" (`segmenter._PLAYER_TRIGGER_CONDITIONS`, bound through
#: `effect_binder`'s new ``{"subject": "you"}`` scoping). The first subject in
#: this grammar that isn't an object at all: these events name a player, not
#: an acting permanent, so `_TRIGGER_VERBS`' whole instance-id-matching
#: discipline doesn't apply and they get their own table. Deliberately
#: anchored, so "whenever you surveil **for the first time each turn**"
#: (Whispering Snitch) still fails closed rather than over-firing.
#: 37 (2026-07-28): RULE 701.14 **fight** (MEC-1) — "target creature you
#: control fights target creature you don't control", the source's own "~/it
#: fights …", and an Aura host's "enchanted creature fights …", over the new
#: `effects.FightEffect`. Brings `subgrammars.target_macro` (a second,
#: group-renamed `TARGET` so one clause can carry two RULE 115 requirements)
#: and `handlers.EffectHandler.self_subject_only` — the first row gated on
#: *who a bare "it" refers to*, which `segmenter.parse_effect_body` answers
#: only for an unsplit self-subject trigger body.
#: 38 (2026-07-28): MEC-10, the rest of the fight family — *whose* creature
#: fights. A pronoun bound to the previous clause's target
#: (`handlers.EffectHandler.previous_subject_only` +
#: `effects.GameContext.previous_targets`, Epic Confrontation), RULE 109.5's
#: cross-requirement "another target creature" (`TargetSpec.
#: distinct_from_others`, Pit Fight), the "choose target … and target …" pair
#: with "those creatures fight each other" (`effects.ChooseTargetsEffect`),
#: and the one-sided sibling "deals damage equal to its power to …"
#: (`effects.DamageEqualToPowerEffect`, Rabid Bite/Bite Down + the dies-
#: trigger self form). Also adds the "target creature or planeswalker you
#: don't control" `TARGET` row.
#: 39 (2026-07-29): MEC-2 + MEC-3 — three keyword actions that had no
#: primitive and no recognition at all. **Monstrosity** (RULE 701.37):
#: `handlers._monstrosity` over `effects.MonstrosityEffect`/`RulesEngine.
#: monstrosity`, the `BECAME_MONSTROUS` trigger verb (`segmenter.
#: _TRIGGER_VERBS`, so "when ~ enters **or** becomes monstrous" works too),
#: and the RULE 613.6 conditional static "as long as ~ is monstrous, it has
#: <keywords>" (`static_handlers._MONSTROUS_GRANT_RE` → the new
#: ``requires_monstrous`` selector gate). **Adapt** (RULE 701.46) as its own
#: counter-gated effect — its "as long as ~ has a +1/+1 counter" statics
#: needed nothing new, being the layer engine's existing ``min_level``.
#: **Goad** (RULE 701.15): `handlers._goad`/`_goad_previous`/`_goad_selector`
#: over `effects.GoadEffect`, plus the "…and is goaded" Aura/Equipment tail
#: on `_ATTACHED_ANTHEM_RE`/`_ATTACHED_GRANT_RE` binding the new ``goaded``
#: static, which `continuous.recompute` stamps in the same non-RULE-613
#: bucket as the combat restrictions.
#: 40 (2026-07-29): MEC-13 + the general "as long as"/duration machinery.
#: RULE 613.6 conditional statics stop being one selector param per card
#: family and become one whitelisted vocabulary (`game/static_conditions.py`)
#: carried in any static's ``active_if``; `static_handlers.
#: _conditional_static_specs` parses both printed orders ("As long as <cond>,
#: <static>" / "<static> as long as <cond>") by parsing the gate and
#: re-entering with the bare static, so no family needs a conditional variant
#: — which also required the first *self*-scoped anthem/grant rows ("~ gets
#: +2/+2", "~ has trample"), the inner half of nearly every such clause. The
#: three pre-existing gates (``active_player_only``, ``min_level``,
#: ``min_count_selector``) are translated into the same vocabulary rather than
#: evaluated separately. RULE 611 **durations** are the time-bound half
#: (`game/durations.py` + `GameState.floating_statics` +
#: `effects.GrantUntilEffect`), reachable from card text for every duration
#: the turn-scoped ``temp_*`` fields can't express ("until your next turn",
#: "until end of combat"). MEC-13 itself: a combat-permission tail on the
#: grant rows plus the new ``attacks_as_though_no_defender`` restriction.
#: 41 (2026-07-29): PAR-11's tap-then-lock family, closed by *composing* the
#: pieces above rather than by any new primitive — the `previous_subject`
#: pronoun (v38), the ``no_untap`` static (batch 8) and v40's
#: condition-bounded duration had never met. Needed only a handler row and
#: one widening: `segmenter._CREATURE_TARGET_KINDS` now also accepts a
#: land/artifact/permanent antecedent, since "Tap target **land**. **It**
#: doesn't untap …" is the same pronoun with a non-creature referent.
#: 42 (2026-07-29): MEC-12 (goad's four residues) + MEC-14 (the rest of the
#: "as long as" vocabulary), both closed in full. The condition whitelist
#: gained an ``of`` **subject selector** — every ``source_*`` kind can now
#: read the *attached permanent* (RULE 303.4a "as long as enchanted permanent
#: is a creature"/"…is red", ~52 cards) or a floating static's affected one —
#: plus three characteristic kinds (``is_card_type``/``is_color``/
#: ``is_subtype``), an opponent-scoped ``opponent_count`` and
#: ``drawn_cards_at_least``; `_conditional_static_specs` rewrites the inner
#: "it" to the attached subject when the gate named it, so the ordinary
#: `_ATTACHED_*` rows parse the body. RULE 702.94b soulbond finally reaches
#: the already-shipped ``soulbond_pair`` selector ("each of those creatures
#: has …"). Goad: a **dynamic target count** (`TargetSpec.count_selector`,
#: expanded into one gathering round per target by `targeting.expand_counts`)
#: for "for each opponent, goad up to one target creature that player
#: controls" and Death Kiss's "up to X"; a *dynamic* power threshold on a
#: group scope (``power_lt_selector``, Baeloth Barrityl); the
#: ``created_objects`` referent for "**the tokens** are goaded" (with
#: "each player/opponent creates" and "creates a **tapped** …" to reach it);
#: and a ``goaded``/``in_combat`` trigger-subject filter, snapshotted onto
#: the DIES event since RULE 400.7 means the object is already gone.
#: "47" (2026-08-03): the PAR-6..10 batch. PAR-6: RULE 702.16n/p's "This
#: effect doesn't remove ~" exemption on an attached-permanent protection
#: grant (`GameObject._protection_self_exempt`, read by `_attachment_legal`)
#: — plus a "protection from each color" quality fold and a new
#: "protection from creatures of the chosen type" dynamic (Riders of
#: Gavony), the latter found while fixing two other cards' pre-existing,
#: unrelated "protection from the colors of permanents you control"
#: mis-modeling (a computed quality now correctly rejected, not silently
#: stored as a literal string). PAR-7 investigated and re-scoped in
#: BACKLOG.md rather than closed: Emblazoned Golem needs both a Kicker-
#: cost-with-its-own-{X} primitive *and* a novel per-color-capped mana
#: spend restriction, for one card. PAR-8: "Each [<filter>] card in your
#: hand has cycling `<cost>`." (`grant_cycling_to_hand`,
#: `continuous._apply_hand_cycling_grants` — a layer-6 grant reaching the
#: hand zone, which no existing selector touched) — exposed and fixed a
#: real gap where a hand-zone *granted* activated ability was never
#: offered by `legal_actions` at all. PAR-9: a bare, unregistered "Cycling
#: `<cost>`" keyword was already claimed for coverage but bound to no real
#: activated ability (`effect_binder._cycling_activated_ability`), guarded
#: against the type-restricted `<type>cycling` aliasing onto the same slug.
#: PAR-10: "Activate only as a sorcery and only if `<condition>`."/"Activate
#: only if `<condition>`." (`ACTIVATION_CONDITION_MARKER`,
#: `ActivationCost.activation_condition`, checked by `can_activate` via
#: `static_conditions.condition_holds`) plus a new
#: ``cast_instant_or_sorcery_this_turn`` condition kind (picked up for free
#: by the existing "as long as" family); and a same-session discovery while
#: sizing Dread Wanderer — "Return this card from your graveyard to the
#: battlefield[, tapped]" was entirely unrecognized (69+ cache cards),
#: closed generally (`ReturnSelfFromGraveyardToBattlefieldEffect`) along
#: with the `can_activate`/`legal_actions` graveyard-zone activation gap it
#: exposed (a "MODELED but never actually offered" ability, the same
#: anti-pattern PAR-9's Cycling fix caught).
#: "48" (2026-08-03): PAR-7, previously re-scoped rather than closed —
#: Emblazoned Golem. Kicker's own ``{X}`` is now a real announced value
#: (`GameEngine`'s new ``kicker_x`` parameter on `can_cast`/
#: `effective_cast_cost`/`cast_spell`, `max_affordable_kicker_x`,
#: `GameObject.kicker_x_paid`), and its "spend only colored mana on X. No
#: more than one mana of each color may be spent this way." payment
#: restriction is a new general `ManaPool` primitive
#: (`can_pay_distinct_colors`/`pay_distinct_colors`/`clone`, RULE
#: 605.3a-shaped but capped by color-diversity rather than by what the mana
#: is spent on) rather than a card-specific hack — paid as a second step
#: after the printed cost, on whatever the pool has *left*, so the two
#: never double-claim the same mana. `counters.py`'s kicked-gate "enters
#: with N counters" shape now also accepts "X" as the amount
#: (``kicked_x_scale``, resolved against ``kicker_x_paid`` rather than a
#: fixed count or `x_paid`), and a new `catalogue/kicker_mana.py`
#: recognizes the restriction clause — both claimed the same
#: "engine reads the card directly, no spec" way `entry_counters`/
#: tapped-entry already are, since resolution needs live cast-time state a
#: precomputed spec can't carry.
#: "49" (2026-08-03): PAR-16, PAR-17, PAR-14, PAR-15 in one batch.
#: PAR-16: "`<cost>`: Return this card from your graveyard to your hand."
#: (`ReturnSelfFromGraveyardToHandEffect`) and its triggered sibling
#: "Whenever `<event>`, [you may] return this card from your graveyard to
#: your hand." (RULE 113.6a — `TriggeredAbility.functions_from_graveyard`,
#: inferred the same way PAR-10's `graveyard_zone` is, consulted by a new
#: `RulesEngine._collect_graveyard_function_triggers` scan alongside the
#: older mill-only one). PAR-17: a triggered ability's own "if it was
#: kicked, `<effect>`." gate (`_KICKED_CONDITION_RE` widened from "this
#: spell" to also accept "it"), plus two siblings: "if it was kicked
#: **twice**" (RULE 702.34a Multikicker's own count threshold — a new
#: `kicked_at_least` condition) and "if `<this spell|it>` was
#: **bargained**" (the engine already supported this key; only the oracle-
#: text recognizer was missing). An "X" inside a kicked-wrapper's rest
#: clause is rewritten to a new `"kicker_x"` sentinel `RulesEngine.
#: _substitute_x` resolves against `kicker_x_paid` — caught a real bug on
#: the way: the substitution never reached through a `ConditionalEffect`
#: wrapper to its `inner` effect, so this sentinel would have shipped
#: broken (crashed at resolve time) without an execute-level test. PAR-14:
#: RULE 603.2's once-per-turn trigger limiter, in both printed spellings —
#: a trailing "This ability triggers only once each turn." sentence
#: (`TRIGGER_ONCE_PER_TURN_MARKER`) and the inline "…for the first time
#: each turn" condition suffix (stripped once, before any subject-family
#: dispatch, so every trigger family picks it up for free) — both folding
#: into the same `AbilitySpec.trigger["limit"]` flag, consumed by the
#: `TriggeredAbility.once_per_turn`/`_last_triggered_turn` mechanism that
#: already existed (built for Dionus, Elvish Archdruid's granted ability)
#: but had no oracle-text path reaching it. PAR-15: RULE 115.1a's "any
#: number of target `<X>`" — `_MULTI_TARGET_QUANTIFIER` widened with a
#: third alternative alongside literal-N/"up to N", capped at
#: `_ANY_NUMBER_TARGET_CAP` (10, the same convention the one pre-existing
#: hand-authored example already used) rather than a live legal-target
#: count, since the existing round-by-round gathering machinery already
#: stops early or when targets run out; embedded in ~9 existing handler
#: regexes so all of them gain it at once. Plus a genuinely new
#: recognizer, `_DIVIDED_DAMAGE_RE`/`_divided_damage`, for the ticket's own
#: named biggest cluster (RULE 601.2d "deals N/X damage divided as you
#: choose among any number of target(s)/target creatures") — the
#: `DealDamageEffect(divided=True)` engine primitive already existed
#: (Shatterskull Smashing/Fire Covenant, hand-authored) but had no
#: oracle-text recognizer either.
#:
#: v50 (2026-08-04) — PAR-15's residue (four small clusters left after v49):
#: RULE 615's targeted/divided prevention sibling of divided damage
#: (`PreventDamageEffect`'s new `target_kind`/`divided`/`amount_if_kicked`
#: modes + a new `RulesEngine.prevent_damage_to_target` any-target engine
#: primitive); two new `ReturnFromGraveyardEffect` destinations ("on top
#: of your library", already supported; "into your library", modeled as
#: "bottom, then shuffle" via the new `shuffle_after` param);
#: `AddCountersEffect.divided` (a counter pool split across a chosen
#: group, the same shape `DealDamageEffect.divided` already had); and
#: `PumpEffect.target_count` (a new N>=2 mode) + `TapEffect.
#: previous_subject` (mirroring `ReturnToHandEffect`'s pronoun) for "any
#: number of target creatures each get +N/+N … until end of turn.
#: Untap those creatures."
#:
#: Also PAR-13 (dungeon room/plane/scheme effect bodies): 8 of the 9
#: previously-unmodeled dungeon rooms now bind (`game/dungeons.py`'s
#: `room_effect_specs`, same grammar as a card) — `grant_until`'s new P/T
#: route (`_pump_until`, riding the `anthem` static) and its "can't
#: attack/block until `<duration>`" sibling (the synthetic `grant_keyword`
#: flag family's first resolve-time-grant route), widened with two new
#: `_GROUP` phrasings ("creatures your opponents control"/"creatures you
#: don't control"); a whole-clause compound-cost handler (discard + three
#: `choose_objects` sacrifices, Oubliette-shaped); a legendary named token
#: (`CreateTokenEffect.legendary`, `Card.is_legendary` threaded through
#: `synthesize_token_card`); `ImpulsiveDrawEffect`'s first oracle-text
#: route (previously hand-authored-only); a new `DrawRevealCastOneFreeEffect`
#: + `_request_choose_objects`'s new `"cast_free"` action (a hand-zone pick);
#: and a new mass-interactive primitive, `RulesEngine.
#: _request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
#: single-player `_request_pay_cost_then`) plus a new compound
#: `ActivationCost.sacrifice` value (`creature_artifact_or_land`) for
#: "each player loses N life unless they `<pay cost>`." Throne of the Dead
#: Three is the one dungeon room left genuinely unmodeled (a "reveal top
#: N, choose one, place with counters, shuffle the rest back" shape no
#: other cached card needs). Planechase/Archenemy plane/scheme card text
#: (13/309 modeled) remains PAR-12's own indefinite tail, not newly
#: regressed.
#: "52": PLR-11's own deliberately-deferred residue — Gemstone Caverns'
#: conditional/costed/counter-bearing RULE 103.6a battlefield permission
#: and Buried Ogre's graveyard-destination RULE 103.6 permission
#: (`catalogue.opening_hand.pregame_setup_permission`, +2 cards).
#: "53": saved-deck-priority batch (2026-08-04) — cross-referenced every
#: saved deck's card list against the parser gate and closed the five
#: highest-yield SOLO-blocker templates found there: the untargeted mass
#: "destroy/exile all X [with a filter]" board wipe (`catalogue.handlers`'
#: `destroy_all`/`destroy_all_no_regen`/`exile_all`, widening
#: `effects._MASS_DESTROY_SELECTORS` with `"all_lands"`); "[<type> [and
#: <type>]] spells you cast cost {N} less/more to cast"
#: (`static_handlers._SPELL_COST_TAX_YOU_CAST_RE`, widening
#: `continuous._spell_type_matches` to OR a list — and fixing a latent
#: `_CARD_TYPE_ATTRS` gap where "instant"/"sorcery"/"battle" were never
#: matchable by `_has_card_type` at all, unnoticed because every prior
#: caller only ever needed the five permanent-type words); "whenever you
#: cast a/an <type> spell, <effect>" (`segmenter._CAST_SPELL_TRIGGER_RE`, a
#: new trigger-condition recognizer riding the pre-existing `SPELL_CAST`
#: event and `effect_binder`'s `spell_card_types` predicate); "whenever ~
#: or another creature dies, <effect>" (Blood Artist-shaped,
#: `segmenter._SELF_OR_GROUP_SUBJECT_RE`, the main-type sibling of the
#: existing subtype-only `_SELF_OR_GROUP_SUBTYPE_RE`); and "Choose a
#: Background" as a bare RULE 702.124 FLAG keyword (`catalogue.keywords`,
#: inert in-game like Partner — see BACKLOG.md's DB-3 for the deckbuilding
#: half). +107 cards, 0 regressions (`Done_Backend.md`).
#: "54": second saved-deck-priority batch (2026-08-05) — five more
#: templates off the same ranking: "whenever you gain life, <effect>"
#: (`segmenter`'s `_PLAYER_TRIGGER_CONDITIONS`, riding the pre-existing
#: `EventType.LIFE_GAINED`); a general N-way "target artifact, enchantment
#: [, or land]" sibling of the existing 2-way `TARGET` row
#: (`subgrammars._TARGET_ROWS`); "commander creatures you own have
#: '<ability>'" (`continuous`'s new `commander_creatures_you_own` ownership
#: selector + a dedicated `static_handlers` recognizer — also fixed a latent
#: `TypeError: unhashable type: 'list'` crash in `_quoted_ability_grant_
#: effects` on a compound-event inner trigger); "whenever ~ attacks, it gets
#: +N/+N until end of turn" (`catalogue.handlers`'s new `self_subject_only`
#: pump row, the bare-pronoun sibling of the existing `~ gets …` one); and
#: "prevent the next N damage that would be dealt to any target this turn"
#: (the plain single-target sibling of the already-shipped divided-
#: prevention row). +282 cards (cumulative with v53), 0 regressions
#: (`Done_Backend.md`).
#: "55": named (non-P/T) counter kinds for the plain "put a `<kind>`
#: counter on X" shape (RULE 122.1) — `AddCountersEffect.kind` was already
#: a free string; only "spore" recognition was missing
#: (Deathspore Thallid/Elvish Farmer/Feral Thallid-shaped,
#: `catalogue.handlers._add_named_counter`). +13 cards, 0 regressions.
#: "56": deck-first audit batch (2026-08-05) — "Investigate" (RULE 701.19a,
#: an alias onto the already-shipped Clue token, 87+ cards, the case study
#: that motivated PARSER_LONG_TAIL.md's basic-vs-set-specific split) plus
#: the "Hobbits" saved deck's own set (Tales of Middle-earth): "The Ring
#: tempts you" as a resolve-time effect (aliasing the already-existing
#: `TheRingTemptsYouEffect`) and — new engine primitive —
#: `EventType.RING_TEMPTED`, fired by `RulesEngine.the_ring_tempts_you`
#: once the Ring-bearer choice settles, for "whenever the Ring tempts you,
#: `<effect>`" triggers (previously unfireable regardless of parser work,
#: since no event existed at all); "burden" joins `_NAMED_COUNTER_KINDS`
#: (The One Ring). +354 cards cumulative with v55, 0 regressions.
#: "57": closes the "Hobbits" deck's own commander, Frodo, Adventurous
#: Hobbit // Frodo, Sauron's Bane — three new small condition primitives in
#: `effects.ConditionalEffect._condition_holds` (generalized from an
#: if/elif chain, exactly one key ever set, to an AND-fold over every key
#: present — Frodo's own second clause is the first card needing two
#: conditions together, backward compatible since every existing dict
#: still carries one key): `GameState.life_gained_this_turn` (a new
#: per-turn tracker, RULE 119.3), `"is_ring_bearer"` (RULE 701.52a — also
#: closes "if you chose a creature other than ~ as your Ring-bearer" on
#: Aragorn, Company Leader/Faramir, Field Commander/Galadriel of
#: Lothlórien/Gandalf, Friend of the Shire, though each still has an
#: unrelated second unclaimed clause of its own), and
#: `"ring_tempted_at_least"` (RULE 701.51b, `Player.ring_level`
#: threshold). +365 cards cumulative with v56, 0 regressions.
#: "58": "make the Hobbits/Wyleth Equip decks playable" batch (2026-08-05) —
#: the "reveal land" cycle (RULE 614.1's optional interactive sibling to
#: `unless_types`'s deterministic check lands — new `land_tap_condition`
#: kind `reveal_types` + a `land_tapped_reveal` `pending_choice`); the
#: "whenever you gain life, <effect>" *dynamic*-amount family ("that
#: much"/"that many", `LoseLifeEffect`/`AddCountersEffect`/`PumpEffect.
#: amount_from_trigger_event` — plus fixing a latent mis-model risk where
#: the new selfref row could have misread a bare "it" under a *group*-
#: subject trigger as the source, `EffectHandler.self_subject_only` now
#: gates it correctly); `LIFE_GAINED` joining `STEP_BEGIN` as a second
#: player-subject *grantable* trigger event (`continuous.
#: _PLAYER_SUBJECT_GRANTED_EVENTS`) for "equipped/enchanted creature has
#: 'whenever you gain life, …'"; `AttachEffect`'s `target_kind="created"`
#: and `DestroyEffect.exclude_created` (RULE 608.2's "the tokens" referent,
#: `GameContext.created_objects`, on the attaching/excluding side); a new
#: "whenever you sacrifice a Food/Clue/Treasure, <effect>" trigger family
#: (`EventType.SACRIFICE` gaining a `subtypes` payload, mirroring DIES);
#: "if you don't control a Food/Clue/Treasure, <effect>" as a new
#: `ConditionalEffect` key; a mass-destroy `min_power`/`max_power` filter
#: (Dusk // Dawn/Elspeth, Sun's Champion) alongside the pre-existing mana-
#: value/toughness ones; and a `without_card_type` qualifier on creature
#: target/blocking filters ("target **nonartifact** creature", Go for the
#: Throat-shaped). Also fixed a real coverage-badge bug, unrelated to any
#: of the above: `card_registry.is_registered` lacked `specs_for`'s own
#: DFC "//" front-face fallback, so an already-fully-bound split/DFC card
#: registered under its front face alone (Halvar, God of Battle // Sword
#: of the Realms) was wrongly reported UNMODELED. The rest of this batch's
#: ~30 cards were hand-authored in `card_catalogue` (several new
#: general primitives along the way: `AddCountersEffect.x_multiplier`,
#: `ConditionalEffect`'s `source_x_paid_at_least`/
#: `creatures_died_this_turn_at_least`, `LoseLifeEffect.
#: amount_from_life_gained_this_turn`/`amount_from_burden_counters_on_self`,
#: `costs.ActivationCost.sacrifice_count`, `continuous.
#: activation_cost_reduction_for`'s subtype-scoped branch, and the
#: `legendary_creatures_you_control`/`attacking_creatures` `affects`
#: selectors) — see `Done_Backend.md` for the full per-card list and each
#: one's documented simplification. +18 cards to measured parser coverage
#: (the rest were hand-authored, which this ledger doesn't count), 0
#: regressions.
#:
#: Batch 59 (2026-08-05, "make two decks fully playable"): a deck-first
#: audit of the "Keywords Showcase" and "Eliferate" saved decks surfaced a
#: long tail of genuine engine/parser gaps, closed in priority order by
#: real yield rather than by card. New primitives, each reused well past
#: its originating card: RULE 702.90/91 **Infect/Wither** damage
#: conversion (`combat.has_infect`/`has_wither`, `deal_damage`'s poison/
#: -1-1-counter substitution — a pure keyword-recognition gap before this,
#: zero behavior); RULE 702.33b's **kicked override** conditional
#: ("deals N, if kicked deals M *instead*" — `DealDamageEffect.
#: amount_if_kicked`/`CopyPermanentEffect.count_if_kicked`, distinct from
#: the additive shape already shipped); RULE 615's **unscoped Fog** shield
#: (`PreventAllCombatDamageEffect`, +36 cards on one template); RULE
#: 707's bare **copy_permanent** oracle recognition (previously hand-
#: authored only); RULE 119/701.8's **hand-disruption discard** (Duress/
#: Thoughtseize-shaped, `RevealHandChooseDiscardEffect` reusing
#: `_request_choose_objects`'s existing chooser, +63-card family);
#: `RulesEngine.blink`'s **``controller``** param (Restoration Angel's
#: "return under *your* control", not the owner's) — which also surfaced
#: a real latent bug: `creature_you_control`'s `legal_targets` branch
#: never consulted `creature_filter` at all; a **normalize fold** for
#: "Until end of turn, `<body>`." → the far more common trailing form
#: (+124-card upper bound); `without_color`/`without_card_type`/
#: `without_subtype`/`"attacking"` **negative/compound target filters**
#: (Doom Blade's "nonblack", Restoration Angel's "non-Angel", Gnarlroot
#: Trapper's "attacking Elf"); targeted **draws**
#: ("target player draws a card" had been silently making the source's
#: *controller* draw instead); RULE 702.28c's **Cycling trigger**
#: (`EventType.CYCLED`, `ActivationCost.is_cycling`, a graveyard-scoped
#: trigger scan mirroring the existing dies-from-graveyard one — "When you
#: cycle this card" had no event to watch at all, +37-card template) with
#: its own **{X} preservation** (`GameObject.cycling_x_paid`, mirroring
#: Kicker's `kicker_x_paid`); a **card-type-excluding spell-cast trigger**
#: ("whenever you cast a *non*creature spell" — the positive form existed,
#: the negation didn't, +92-card template) and its **creature-subtype**
#: sibling ("…an Elf spell" — `spell_subtype_any` was already a real
#: predicate, just never reachable from oracle text, +181-card template
#: upper bound); RULE 118.3's **pay_cost_then** oracle recognition ("you
#: may pay `<cost>`. If you do, `<effect>`." — the primitive was
#: hand-authored-only, +21-card template) with `_peel_optional`'s
#: existing energy-only double-optional guard widened to any mana cost;
#: three **dynamic-magnitude token/pump** shapes read live off the board
#: or the firing event rather than a fixed int
#: (`CreateTokenEffect.count_from_trigger_event`/Lathril's "create that
#: many", `PumpEffect.amount_from_count_selector`/Craterhoof Behemoth's
#: "+X/+X where X is the number of creatures you control",
#: `PumpEffect.per_recipient_controller_counter`/Phyresis Outbreak's
#: per-recipient poison scaling); and several narrow selector/filter
#: widenings reused by multiple cards each (`creatures_you_control_of_
#: type_<X>` reaching `group_selector_objects` not just `count_selector`,
#: `permanents_you_control`/`other_creatures_you_control` reaching
#: `PumpEffect`/`TapEffect`'s own selector — the latter missing ``src=``
#: entirely, a second latent bug). +239 cards to measured parser coverage,
#: 0 regressions (`scripts/parser_probe.py diff`), full pytest suite green
#: throughout. See `Done_Backend.md` for the per-family narrative.
#:
#: Batch 61 (2026-08-10, MEC-12 third pass — the seven cEDH decks): a
#: mana-ability coverage-*classification* fix (Bloom Tender's "for each
#: color among permanents you control, add one mana of that color" was
#: already fully behavioral via `game/mana_abilities.py`'s ENG-27 selector,
#: just never credited by the gate's mana-ability claim check, which only
#: recognized a line starting with the literal word "add");
#: oracle-text recognition of three RULE 118.7/601.2f cost-reduction
#: shapes the engine already had params for but no parser handler ever
#: claimed — colour-scoped "`<Color>` spells you cast cost `<N>`
#: more/less to cast" (the Medallion cycle/Grand Arbiter Augustin IV),
#: "Spells your opponents cast cost `<N>` more/less to cast" (new
#: `affects="opponents_spells"` branch), and "Activated abilities of
#: `<type>` you control cost `<N>` less to activate[, floor]" (new
#: `card_type` group scope on `continuous.activation_cost_reduction_for`,
#: next to the existing `subtype` one); "[you may c]ast spells this turn
#: as though they had flash" (Emergence Zone — the effect already shipped
#: as `GrantFlashUntilEndOfTurnEffect`, hand-authored-only until now); and
#: a `free_cast_condition` board-count kind, `opponent_spells_cast_this_
#: turn_at_least` (Mindbreak Trap's "if an opponent cast three or more
#: spells this turn, you may pay `{0}` rather than pay this spell's mana
#: cost" — RULE 601.2f's free-cast family, previously boolean-conditions
#: only). +6 cards to measured parser coverage this pass (Bloom Tender,
#: Grand Arbiter Augustin IV, Training Grounds, Emergence Zone — Otawara/
#: Smothering Tithe are hand-authored, which this ledger doesn't count),
#: 0 regressions, full pytest suite green throughout. See
#: `Done_Backend.md` for the full narrative.
#:
#: Batch 62 (2026-08-11, MEC-12 fourth pass — the *rest* of the seven cEDH
#: decks, not just the high-frequency remainder): RULE 603.1's **untyped
#: player-subject cast trigger** ("whenever you/an opponent/a player casts
#: a spell[, `<effect>`]", optionally "with mana value N or less" —
#: `_CAST_SPELL_TRIGGER_PLAIN_RE`/`_CAST_SPELL_TRIGGER_MV_RE`) alongside a
#: new `DealDamageEffect` `"event_player"` selector ("~ deals N damage to
#: **that player**" — the caster, read off the firing `SPELL_CAST` event
#: via the same `_event_player` helper `PayCostThenEffect`'s
#: `payer="event_player"` already uses) — Spellshock/Eidolon of the Great
#: Revel/Pyrostatic Pillar-shaped punishers, no new engine primitive for
#: the trigger condition itself since `effect_binder`'s `{"subject":
#: "group", "controller": ...}` scoping already handles any player-keyed
#: event (proven by Smothering Tithe's `DRAW`-event use last batch);
#: `_EXILE_TOP_PLAY_RE` (impulsive draw, RULE 601.3b) widened to the
#: *leading*-duration word order real cards actually print ("Until the end
#: of your next turn, you may play those cards." — Light Up the Stage's
#: own text, not the trailing form the row was first written against),
#: "that card"/"those cards" pronouns, a singular "the top card", and
#: `count_or_x_of` for "the top x cards" (Commune with Lava) —
#: `ImpulsiveDrawEffect` itself was already fully built (Light Up the
#: Stage was its hand-authored namesake), this was purely a missing
#: recognizer; "search your library for a `<colour>` `<type>` card" (colour
#: dropped, not modeled as its own filter) plus "equipment" added to the
#: searchable-subtype vocabulary (`_type_matches`'s plain type-line
#: substring check already supports any subtype, same reason "Forest"/
#: "Island" work) — Merchant Scroll/Magus of the Order/Shadow-Rite Priest/
#: Steelshaper's Gift/Honored Knight-Captain/Steelshaper Apprentice, and a
#: regex-precedence bug caught along the way (`(?:white|...|green\s+)?`
#: bound `\s+` to only the last alternative, so only "green X" matched by
#: accident). +~28 cards to measured parser coverage this pass, 0
#: regressions, full pytest suite green throughout. See `Done_Backend.md`
#: for the full narrative, including this batch's hand-authored cards
#: (Imperial Recruiter/Recruiter of the Guard on two new `card_query`
#: criteria keys, Wheel of Fortune, Ruination), which this ledger doesn't
#: count.
#: MEC-18/MEC-19 (2026-08-11): MEC-18 generalized `pay_cost_then`'s oracle
#: recognition from two hardcoded shapes to the whole RULE 603.5 "you may
#: <sacrifice/discard/pay-mana/pay-life>. When you do, <effect>." family
#: (`catalogue.handlers._pay_cost_then_general`, `segmenter._PAY_ENERGY_
#: THEN_PEEL_GUARD_RE` widened alongside it so the "you may" isn't eaten by
#: the generic optional-ability peel first). MEC-19 built `EventType.
#: BECOMES_TARGET` (RULE 115/601.2c never reached the event bus before —
#: `RulesEngine.check_ward` is now the general "targets finalized" choke
#: point, still doing ward's own unchanged direct check alongside it) plus
#: `CounterUnlessPayEffect`/`counter_unless_pay` (a thin adapter onto
#: `resolve_ward_effect` for the un-keyworded-Ward-shaped "counter it
#: unless that player pays `<cost>`" cycle) and a new `caster_relation`
#: trigger predicate for "an opponent controls"/"you control". Both
#: PARSER_VERSION bumps land together since MEC-19's own testing turned up
#: real MEC-18-adjacent cost-clause fixes in the same session. See
#: `Done_Backend.md` for the full narrative.
#: MEC-20 (2026-08-11): RULE 601.2f "Expertise" cycle — "you may cast a
#: spell with mana value N/X or less from your hand without paying its
#: mana cost[, where x is the number of attacking creatures]"
#: (`catalogue.handlers._free_cast_from_hand`, `effects.
#: FreeCastFromHandEffect`), plus "veil of time" added to `normalize`'s
#: RULE 207.2c ability-word whitelist (Epistolary Librarian).
#: MEC-24 (2026-08-11): "target instant or sorcery card in your graveyard
#: gains flashback [`<cost>`] until end of turn[. The flashback cost is
#: equal to its mana cost.]" (Recoup/Snapcaster Mage/Slickshot Lockpicker/
#: Sphinx of Forgotten Lore/Katilda and Lier-shaped) —
#: `catalogue.handlers._grant_flashback_target`/`effects.
#: GrantFlashbackToTargetEffect`, a per-graveyard-card marker
#: (`GameState.temp_flashback_grants`) rather than the untargeted "each
#: instant and sorcery card" grant (`grant_graveyard_cast_permission_
#: this_turn`) already claims. `_GRAVEYARD_TYPE_WORD` also gained a bare
#: "sorcery" alternative (Recoup's own "target **sorcery** card") alongside
#: a matching `targeting._GRAVEYARD_TYPE_FILTERS["sorcery"]` entry.
#:
#: 71: MEC-12 seventh pass (2026-08-11) — the untap-cap family widened past
#: lands-only (Static Orb/Winter Moon), Meekstone's group-scoped `no_untap`,
#: a generic RULE 115.4 "change the target" handler (Deflection/Shunt/
#: Swerve/Willbender/Bolt Bend/Redirect Lightning), "you control a creature
#: with power N or greater" as a `control_count` condition, a spell's own
#: "this spell costs {N} less to cast if/for each…" now reaching
#: `static_effect_specs` for instants/sorceries too (not just permanents),
#: and "your opponents can't cast spells during your turn." as a
#: `cast_prohibition` row (Voice of Victory/Dragonlord Dromoka).
#:
#: 72: MEC-12 eighth pass (2026-08-11) — Back to Basics's unconditional
#: nonbasic-land `no_untap` sibling to the untap-cap family; `Return
#: FromGraveyardEffect`/`destroy_mv`'s shared `TargetSpec.max_mana_value`
#: offer-time cap extended to the graveyard-recursion family (Auriok
#: Salvagers, cache-wide Sun Titan/Unearth/Teshar); a new
#: `permanent_you_dont_control` target kind (Assassin's Trophy/Teferi Hero
#: of Dominaria/Kiora the Crashing Wave) plus `SearchLibraryEffect`'s
#: `player="previous_target_controller"` sentinel for "its controller may
#: search…" (also closing Geomancer's Gambit/Ghost Quarter).
#:
#: 73: MEC-12 ninth pass (2026-08-11) — `PhaseOutEffect.previous_subject`
#: for "It phases out." as a previous-clause pronoun (Slip Out the Back),
#: and RULE 118.9's pitch alt_cost family's first oracle-text route
#: (`segmenter._ALT_COST_EXILE_HAND_COLOR_RE` — Snapback/Pyrokinesis/Unmask,
#: previously only reachable via one-at-a-time hand-authoring).
#: 84 (2026-08-12): "You may look at the top card of your library any
#: time." (Sphinx of Jwar Isle/Fblthp, Lost on the Range/Glowcap Lantern/
#: Iron Lad, Diverging Destiny/Vesuvan Drifter-shaped — ~57 real cards) now
#: emits a real `top_library_permission {"look": True}` spec
#: (`catalogue.static_handlers._LOOK_AT_TOP_ANY_TIME_RE`) instead of being
#: claimed as a no-op line — that no-op treatment (still correct for
#: `_PLAY_WITH_TOP_REVEALED_RE`'s always-paired-with-a-play/cast-grant
#: sibling) turned out to be a real gap for the standalone case: `game/
#: top_library.py`'s `may_look_at_top_of_library`/`GameEngine` view redaction
#: (`services/game_session.py`'s ``top_library_visible``) already fully
#: supported a look-only grant, it just never received one from oracle text.
#: No coverage-count change (all 57 were already MODELED) — this is a
#: behavioral reclassification, not a new-coverage bump, hence the version
#: bump on its own rather than folded into a batch with new coverage.
#:
#: 85 (2026-08-12): PAR-18/PAR-19 closed. PAR-18: `CopyPermanentEffect.
#: referent="previous"` (`_copy_permanent_previous`) for "exile up to 1
#: target creature card from a graveyard. Create a token that's a copy of
#: that card" (Ardyn/Anikthea-shaped — the antecedent an earlier clause's
#: own RULE 115 target, `GameContext.previous_targets`, not the ability's
#: source), `_EXILE_FROM_GRAVEYARD_RE` widened to accept "up to N", and
#: `_parse_copy_except_tail` generalizing the bare/not_legendary/add_types
#: "except" rows into one combinable, fail-closed-per-piece grammar
#: (Dedicated Dollmaker-shaped 2+-modifier clauses). PAR-19: the alt-cost
#: pitch family's counted (`exile_hand_card_color_count` — Soul Spike/
#: Sunscour), `not_your_turn`-gated (Force of Virtue), pay-life-combined
#: (Contagion), and discard-zone (`discard_land_type` — the Abolish/
#: Flameshot/Outbreak/Snag basic-land cycle) shapes; and RULE 605.3a's
#: *subtractive* direction (`ManaPool.pool_by_source`/`require_source_
#: kind`, `game/mana_abilities.mana_source_kind_for` — "spend only mana
#: produced by Treasures/basic lands/creatures", Security Rhox/Imperiosaur/
#: Myr Superion), the primitive PAR-19 had previously confirmed-and-
#: deferred as genuinely new before this pass built it.
#:
#: 86 (2026-08-12): MEC-27/MEC-28 closed. MEC-27: `subgrammars.DEVOTION`'s
#: qualifier grammar — "creatures you control with power N or less/
#: greater" and generalized "tapped `<type>`[ and/or `<type>`] you
#: control" — plus the draw/gain-life/lose-life verb families (`DrawCard
#: Effect.amount_from_count_selector`, six new devotion-amount handler
#: rows incl. the "each opponent loses X and you gain X" drain combo); en
#: route, found and fixed a pre-existing bug where "Bobbleheads"/"Shrines"
#: (artifact/enchantment subtypes) were silently guessed as creature
#: subtypes by the `count_subtype` catch-all (`_COUNT_PHRASE_NONCREATURE_
#: SUBTYPE_WORDS` denylist; Charisma/Strength Bobblehead's own counter/
#: token abilities had always resolved to 0). MEC-28: `group_subject`/
#: `previous_selector` threaded through `parse_effect_body`/`match_clause`
#: (Finest Hour's "that creature", Karlach, Fury of Avernus's "They gain
#: `<keyword>`"), RULE 506.4's bare "whenever you attack" trigger
#: (`PLAYER_ATTACKED`), `_EXTRA_COMBAT_PHASE_RE`'s subject-first word
#: order (A-Raiyuu/Raiyuu, Storm's Edge — whose own stale hand-authored
#: catalogue entry, predating the extra-combat-phase primitive, was
#: deleted in favor of the now-complete parser), and the "For Mirrodin!"
#: ability word's reminder-text-only rules text (`gate._expand_ability_
#: word_reminders`, promoted before `normalize` strips parentheticals).
#: MEC-29: `_ANTHEM_RE`/`_GRANT_RE`/`_QUOTED_GRANT_RE`'s new
#: `_ARTIFACT_SUBTYPES`/`_vehicle_scope_params` fallback — a bare
#: "Vehicles [you control]" scope no longer silently mis-parses as a
#: creature-subtype anthem (`catalogue/static_handlers.py`); Balthier and
#: Fran and Tifa, Martial Artist themselves are hand-authored (RULE 702.122
#: Crew and the "one or more creatures … deal combat damage" aggregate
#: quantifier are both singleton phrasings, not new grammar rows), but the
#: anthem fix is a real classification change on its own.
#: ENG-30: RULE 601.2c's "N or M target X" range (`targeting.TargetSpec.
#: count_max`) — `_MULTI_TARGET_QUANTIFIER`'s new range alternative
#: (`catalogue/handlers.py`) reclassifies every "1 or 2 target X" clause
#: that used to fall through unclaimed (tap/return/return-from-graveyard/
#: distribute-counters/damage[-divided/-each]/pump, both P/T and
#: keyword-only, plus a `previous_subject` pump pronoun sibling and a
#: `nonland_permanent` multi-target row); also fixed a dormant bug found
#: alongside it — "up to two target creatures…" pump clauses (Dauntless
#: Onslaught-shaped, unrelated to the range shape) were silently only ever
#: offering one target, since the handler set a "count" key the "pump"
#: `EffectRegistry` factory never read.
#: MEC-31: RULE 702.172a Spree's own block grammar (`catalogue/modal.
#: split_spree_block` — a "spree" header line, its reminder text already
#: gone by the time `normalize` is done, followed by 2+ "+ <cost> — <body>"
#: mode lines) reaches `AbilitySpec.modes["mode_costs"]`, the per-mode-cost
#: sibling of RULE 700.2's uniformly-priced "choose N or more" block.
#: MEC-40: `_destroy_mv`/`_MASS_DESTROY_NOUNS`/`_MASS_DESTROY_NOUNS_
#: SINGULAR` widened with "nonland_permanent" (Abrupt Decay/Culling
#: Ritual-shaped, a plain oversight — the kind already honoured
#: `max_mana_value`); `segmenter._COST_LOOKS_REAL` widened to recognize
#: "exile a/an <type> you control" as a real activation cost (Food Chain's
#: own mana ability, the battlefield-zone sibling of the existing hand-zone
#: "exile this card from your hand" cost sniff).
#: RULE 701.47/48 Amass: a first parser handler for "amass <Type> N"/"amass
#: N" (`catalogue/handlers.py`'s new `amass`/`amass_untyped` rows), reaching
#: the already-shipped `game/effects/core.py` `AmassEffect` (proven only via the
#: hand-authored Orcish Bowmasters entry until now) from real oracle text
#: for the first time. Digit-only counts — `EffectRegistry.register("amass",
#: ...)` forces `int(...)` at bind time, so a literal "x" sentinel (Assault
#: on Osgiliath/Barad-dûr) isn't safe to emit yet; the "its controller
#: amasses..." third-person form (Azog, Moria's Ruin) and every "amass...,
#: where X is..."-scaled count are left unclaimed too, real remaining work.
#: +33 real cards (parser_probe.py diff, full cache, 0 regressed).
#: "98": RULE 702.184a/721 Station — a third "striated text box" card
#: structure alongside Leveler/Class (`catalogue/station.py`'s
#: `split_station_blocks`/`station_creature_threshold`, a new `is_station`
#: dispatch branch here). The reminder line's own real activated ability is
#: bound off Scryfall's `keywords: ["Station"]` entry directly
#: (`effect_binder._station_activated_ability`, mirroring Crew/Saddle's
#: PAR-9/MEC-40-shaped fix), not emitted by this module; this only splits
#: the "N+ |" bracket structure and reuses Leveler/Class's own
#: `min_level`/`level_counter` gate mechanism (confirmed generic — pointed
#: at ``"charge"`` counters) for RULE 721.2a's cumulative per-bracket
#: grants plus RULE 721.2b's "becomes a creature at N+" static (read from
#: the reminder line's own trailing sentence in **raw**, pre-normalize
#: text — the P/T box a real bracket prints turns out not to survive into
#: Scryfall's `oracle_text` at all). Also fixed a real, previously-dormant
#: cache-wide bug this surfaced: `services/scryfall_client.py`'s
#: `vehicle_power`/`vehicle_toughness` capture only ever checked for
#: "Vehicle" in the type line, so every Station Spacecraft's own printed
#: P/T (needed the instant it becomes a creature) was silently dropped —
#: the same shape MEC-29 already fixed once for Vehicle/Crew.
#: "99": `normalize._strip_unregistered_keyword_labels` — generalizes
#: `_ABILITY_WORD_RE`'s fixed 7-word evergreen list to any RULE 207.2c-
#: shaped "Name — <effect>" label, driven by the card's own raw Scryfall
#: `keywords` array rather than a hand-maintained whitelist: any listed
#: string that isn't a registered real RULE 701/702 keyword (checked
#: against `catalogue.keywords.KEYWORDS`) is stripped wherever it appears
#: as a line-leading label, since RULE 207.2c guarantees the label itself
#: never changes what follows. Closes both a real gap in the fixed
#: evergreen list itself (Threshold/Domain/Raid/Heroic/Metalcraft/
#: Magecraft/Morbid/Imprint/Converge/Alliance/Corrupted/Ferocious/
#: Hellbent/Strive/Coven/… — 415 distinct real ability-word/templated-
#: keyword strings found used this way cache-wide) and, the open-ended
#: majority of the win, the one-off *flavor* labels Universes Beyond sets
#: mint per legendary character (Final Fantasy/Marvel/Warhammer 40K/
#: Doctor Who/Fallout — "10,000 Needles", "Omnislash", "Tunnel Snakes
#: Rule!", …) that can never be enumerated by a fixed list at all.
#: +1,449 cards print this shape cache-wide (1,349 previously UNMODELED
#: solely because of the unstripped label — verified via re-parse, not
#: the raw count).
#: "100": PAR-27 — `segmenter.is_keyword_line` now recognises keyword-only
#: lines whose own parameter contains commas, which the token-by-token
#: comma split could never see: a compound keyword cost ("Flashback—{1}{U},
#: Pay 3 life.", "Recover—Pay half your life, rounded up."), a comma-listed
#: Protection-from / Hexproof-from / Enchant restriction, a variable-N
#: NUMBER keyword ("Firebending X, where X is …"), and the labelled
#: "Companion — <deckbuilding restriction>" (inert, like bare Partner). Plus
#: `_is_keyword_token` now accepts the multi-word landwalk variants
#: ("legendary landwalk", "snow forestwalk") and "<type> offering". Pure
#: recognition — no new/changed `AbilitySpec`; the specs still come from
#: `parse_keywords` off Scryfall's `keywords` array. Findings from a
#: full-cache audit of all 195 registered keywords.
#: "101": PAR-28 — the "Keyword — [ability]" families (Boast RULE 702.142,
#: Exhaust RULE 702.177, Power-up, Forecast RULE 702.57, Solved RULE
#: 702.169/719, Max Speed RULE 702.178) now parse to a real activated /
#: triggered / static ability with the keyword's fixed restriction folded
#: on (`segmenter._segment_keyword_labeled_ability`): Boast's attacked-this-
#: turn + once-per-turn gate, Exhaust/Power-up's once-per-game cap,
#: Forecast's from-hand + upkeep-only + once-per-turn, and a
#: `source_solved`/`your_speed_is_max` condition for Solved/Max Speed on
#: whichever shape the body is. Also: RULE 719.3a "To solve — [Condition]"
#: as an end-step trigger (only the `static_conditions`-mapped conditions),
#: "this Case" folded to `~` in `normalize`, and `_KEYWORD_TOKEN_RE`'s `\b`
#: → `(?![a-z0-9])` so "Start Your Engines!"/"For Mirrodin!" keyword lines
#: (trailing `!`) are recognised.
#: "102": PAR-23 — `keywords._resolve` now maps Scryfall's full "Affinity
#: for <quality>" keyword-array name onto the generic `affinity` row (the
#: same "one Scryfall name per variant" shape as the walk/cycling
#: families), so `parse_keywords` emits its `{name, quality}` spec at last;
#: `game/effect_binder` turns that into the real RULE 702.41 cost-reduction
#: static. Recognition-neutral for the gate (the keyword *line* was already
#: claimed by `is_keyword_line`) — the bump is for the new emitted spec.
#: "104": PAR-21 - RULE 701 keyword-action audit. A first parser handler
#: for RULE 701.50 Connive (`catalogue/handlers.py`'s `connive_self_named`
#: / `connive_self_pronoun` rows) reaching the already-shipped `game/
#: effects.py` `ConniveEffect` (proven only via the hand-authored Ledger
#: Shredder entry until now). Only the two source-is-subject phrasings are
#: claimed - "~ connives" and a self-subject trigger's "it/he/she
#: connives"; a pronoun bound to an earlier clause's target, "connive N"
#: (RULE 701.50d) and "connives x" stay UNMODELED (the effect has no
#: target and no count parameter). Same shape for RULE 701.57 Discover
#: (`discover` row): literal `discover <n>` -> the shipped `effects.
#: DiscoverEffect` (Cascade's sibling); "discover X, where X is <selector>"
#: stays UNMODELED. +30 real cards total (parser_probe.py diff, full cache,
#: 0 regressed). The audit's other findings - the RULE 701 keyword actions
#: with no handler at all (Explore, Populate, Detain, Bolster/Support,
#: Vote, Clash, Learn, Incubate, Suspect, Forage, Collect Evidence, the
#: Avatar bending quartet, ...) - are filed as PAR-29 in `BACKLOG.md`,
#: each needing a new engine primitive first.
#: "105": PAR-20 follow-up (1) - RULE 604.3's "~'s power and toughness are
#: each equal to the number of <X>." characteristic-defining P/T gets its
#: first oracle-text handler (`catalogue/static_handlers._PT_CDA_RE` ->
#: `pt_cda` static, `continuous.recompute`'s layer-7a pass, hand-authored
#: only since the Ashaya batch). `<X>` matched against a fixed whitelist of
#: phrases that already have a `continuous.count_selector` (plus a new
#: `cards_in_your_hand` selector): "cards in your hand" / "lands you
#: control" / "cards in your graveyard" / "creatures you control". Any
#: other quantity phrase fails closed. +20 real cards (parser_probe.py
#: diff, full cache, 0 regressed).
#: "106": PAR-29 - RULE 701.44 Explore, a new engine primitive
#: (`RulesEngine.explore` / `effects.ExploreEffect` / `EventType.EXPLORED`
#: / the `explore_bin` "may put the revealed card in your graveyard"
#: choice) with its oracle handlers: "~ explores" / self-subject-trigger
#: "it/he/she explores" / previous-clause "that creature explores" /
#: "target creature [you control] explores" (`catalogue/handlers.py`,
#: same three subject shapes as `_goad`/`_connive`). "explores, then it
#: explores again" (Defossilize) and mass "each Merfolk you control
#: explores" stay UNMODELED. +22 real cards (parser_probe.py diff, full
#: cache, 0 regressed).
#: "107": PAR-29 - RULE 701.36 Populate, a new engine primitive
#: (`RulesEngine.populate` / `effects.PopulateEffect`, on the existing
#: `copy_permanent` token-copy path) with its `populate` `pending_choice`
#: (which creature token to copy when you control more than one) and a
#: single oracle handler for the bare word "populate" (`catalogue/
#: handlers.py`). "Populate X times" (Full Flowering) stays UNMODELED - a
#: dynamic repeat count PopulateEffect can't take yet, and ~9 more cards
#: whose "populate" clause is real but that carry a second unmodeled
#: clause (Determined Iteration's "the token ... gains haste", Ghired's
#: attack trigger, ...) stay UNMODELED too. +14 real cards net
#: (parser_probe.py, full cache, 0 regressed - a bare-word fullmatch
#: handler cannot over-match).
#: "108": PAR-29 - RULE 701.39 Bolster + RULE 701.41 Support, the +1/+1
#: keyword-action pair. Bolster is a new primitive (`RulesEngine.bolster`
#: / `effects.BolsterEffect` + a `bolster` tie-break `pending_choice` for
#: RULE 701.39a's "if two or more creatures are tied for least
#: toughness"); Support needs no effect of its own - "support N" is a
#: parser alias onto the existing `add_counters` "up to N target
#: creatures" multi-target spec (RULE 701.41c's self-exclusion falls out
#: of `targeting`'s plain "creature" kind). Both literal-N only ("bolster
#: X" / "support X" dynamic amounts stay UNMODELED, fail-closed); the
#: `when ~ enters, <kw> N` and `<cost>: <kw> N` wrappers are free from the
#: existing trigger/activated-ability grammar.
#: "109": PAR-29 - RULE 701.60 Suspect (Murders at Karlov Manor), a new
#: designation like goad: `GameObject.is_suspected` + `RulesEngine.suspect`
#: / `remove_suspected` + `effects.SuspectEffect` / `RemoveSuspectedEffect`.
#: RULE 701.60b's menace + can't-block are read off the flag at combat time
#: (`combat.is_suspected`, `has_menace`, `combat_mixin._can_block`), not the
#: layer engine. Handlers: "suspect it" (self / previous-clause), "suspect
#: enchanted creature" (Aura host), "suspect [up to N] target creature[ an
#: opponent controls]", and "all suspected creatures are no longer
#: suspected" (Absolving Lammasu). Conditional "if it's suspected, ..."
#: clauses, "can't become suspected" statics, "suspected creatures you
#: control" selectors and two-colour token bodies stay UNMODELED.
#: "110": PAR-29 - RULE 701.35 Detain (Return to Ravnica), a designation
#: like goad/suspect: `GameObject.detained_by` (per-detainer set, expiring
#: "until your next turn" via the same `begin_turn` sweep goad uses) +
#: `RulesEngine.detain` + `effects.DetainEffect` + `EventType.DETAINED`.
#: RULE 701.35b's three consequences (can't attack, can't block, activated
#: abilities can't be activated) are enforced in `_can_attack` /
#: `can_block` / `can_activate` via `combat.is_detained`. Handlers: "detain
#: [up to one] target creature/nonland permanent an opponent controls" and
#: "detain up to two/three target creatures/nonland permanents your
#: opponents control". "detain each nonland permanent ... with mana value N
#: or less" (Lavinia) and a "with backup or vehicle" filter stay UNMODELED.
#: Also adds a `target nonland permanent an opponent controls` TARGET row.
#: "111": PAR-29 - "Blight N" (Bloomburrow: "put N -1/-1 counters on a
#: creature you control"), the negative sibling of Bolster:
#: `RulesEngine.blight` + a `blight` "which creature" `pending_choice` +
#: `effects.BlightEffect`. Handler covers only the standalone-verb form
#: ("whenever ~ attacks, blight 1"). The cost forms ("{cost}, Blight N:
#: <effect>", "as an additional cost ... blight N") and the "you may blight
#: N. If you do, <effect>" wrapper stay UNMODELED - they need
#: `ActivationCost`/cast-cost integration, tracked in BACKLOG. "blight X"
#: (dynamic amount) also stays UNMODELED, fail-closed.
#: "112": PAR-29 - RULE 701.63 "Endure N" (Bloomburrow): the permanent's
#: controller either puts N +1/+1 counters on it or creates an N/N white
#: Spirit creature token. `RulesEngine.endure` + a modal `endure`
#: `pending_choice` (`_resume_endure`) + `effects.EndureEffect`
#: (self / previous / target subject shapes, mirroring `explore`). The
#: "you may pay {cost}. If you do, it endures N" wrapper (Descendant of
#: Storms) stays UNMODELED - a separate pay-cost-then build. Literal N
#: only ("endures X" fails closed).
#: "113": PAR-29 - RULE 701.70 "Recruit" (Tales of Middle-earth): draw a
#: card, then discard a card; if the discarded card was a nonland card,
#: create a 1/1 white Human Soldier creature token. `RulesEngine.recruit`
#: + a `recruit` "which card to discard" `pending_choice` +
#: `effects.RecruitEffect` (bare "you"-subject). Connive's sibling but its
#: own primitive (token payoff, not a counter on a source). Bare-word
#: handler.
#: "114": PAR-29 "Parser-shaped only" residue, one batch closing seven items
#: at once (BACKLOG.md's PAR-29 entry): Connive widened with a `TargetSpec`/
#: previous-subject subject and RULE 701.50d's dynamic "connives X" (draw X,
#: discard X as one batch, not X separate 1-and-1 cycles); a standalone
#: `PumpEffect.self_multiplier` for RULE 701.10/11 "double"/"triple `<X>`'s
#: power and toughness"; RULE 701.10's "exchange control of X and Y"/
#: "exchange life totals" generalized from Gilded Drake/Oko/Soul Conduit's
#: three narrow shapes to the general self+target/two-explicit-target/N-
#: same-kind-target templates (`ExchangeControlEffect`/
#: `ExchangeLifeTotalsEffect`), plus a new `land_you_dont_control` target
#: kind; Populate's/Endure's dynamic "X times"/"endures X" riding the
#: existing plain `"x"` sentinel `RulesEngine._substitute_x` already
#: resolves on any effect's own amount/count attribute (Full Flowering/
#: Krumar Initiate); Bolster's dynamic "bolster X, where X is `<board
#: count>`" (`BolsterEffect.amount_from_count_selector`) and Support's
#: "support X" (`AddCountersEffect`'s target `count_selector`); Descendant
#: of Storms' "you may pay `<cost>`. If you do, it endures N." via
#: `pay_cost_then_general`'s recursive follow-up parse widened to pass
#: `self_subject=True`; and Deadly Complication's "target suspected
#: creature you control" (`combat.matches_object_filter`'s new
#: ``is_suspected`` key). Two dormant bugs found and fixed along the way:
#: `AddCountersEffect.apply`'s multi-target branch didn't know about
#: `TargetSpec.count_selector` the way `GoadEffect` already did (silently
#: dropped every target past the first for a dynamic-count spec); connive's
#: original implementation would have repeated a full 1-draw/1-discard
#: cycle N times for "connives N" instead of RULE 701.50d's real
#: draw-N-discard-N-as-one-choice shape, caught before shipping by an
#: execute-level test. Agrus Kos's "if it's suspected, exile it. otherwise,
#: suspect it." (a genuine if/else effect primitive), Airtight Alibi's
#: "can't become suspected" (a new static-flag family), and Clandestine
#: Meddler's "whenever 1 or more suspected creatures you control attack"
#: (a designation-aware group trigger filter) are real new-primitive needs
#: this batch found but did not build - flagged in BACKLOG.md rather than
#: silently deferred.
#: "128": ENG-31 - parametric keyword *grants*. A grant of a keyword that
#: carries a number ("gains firebending N until end of turn" - Fire Nation
#: Palace; "creatures you control gain firebending N …" - Sozin's Comet; a
#: token "with firebending N" - Fire Nation Attacks) had no representation:
#: `pump`/`grant_keyword`/`create_token` all carried a flat `keywords:
#: [str]` list. Added a `{name, n}` shape those three effect/static
#: families accept alongside the flat list (`_split_keywords_with_
#: parametric`, `_GRANTABLE_PARAMETRIC_KEYWORDS` = firebending/annihilator/
#: afflict/bushido), stamped onto `GameObject._granted_parametric_keywords`
#: / `temp_parametric_keywords` by `continuous._apply_layer_6_ability`, and
#: `effect_binder.parametric_keyword_triggered_abilities` re-synthesizes
#: the keyword's RULE 702-text triggered ability off the *granted* N every
#: recompute (the printed-keyword path already ran the same builders at
#: bind-on-load). +3 real cards (parser_probe diff, full cache, 0
#: regressed). Fire Nation Cadets / Fire Nation Occupation / Iroh stay
#: UNMODELED on unrelated grammar (a conditional-static "there's a lesson
#: card in your graveyard", a "cast a spell during an opponent's turn"
#: trigger, a "with a counter on it" group filter) - PAR-30.
#: "129": ENG-33 - villainous-choice / vote option-body primitives, three
#: general handlers that also unlock far beyond the villainous cards: (1)
#: "target player/opponent sacrifices [N] [nontoken] <what> [of their
#: choice]" (`_TARGET_PLAYER_EDICT_RE` -> `sacrifice` with the new
#: `SacrificeEffect.target_kind="player"` RULE 115 target - Diabolic /
#: Chainer's / Sudden Edict, ~13 SOLO); (2) an *uncapped* / "noncreature"
#: `free_cast_from_hand` (`FreeCastFromHandEffect.noncreature_only`, cap
#: now optional - Great Intelligence's Plan, Maelstrom Archangel, Yue the
#: Moon Spirit); (3) "you may put a <type> card from your hand onto the
#: battlefield" (`_PUT_FROM_HAND_RE` -> the existing
#: `PutFromHandOntoBattlefieldEffect` - Dr. Eggman, plus the whole Elvish
#: Piper / Quicksilver Amulet / Stoneforge Mystic / Growth Spiral /
#: Sakura-Tribe Scout family, +26). The 4th named primitive, "create a
#: token that's a copy of that card" (The Master), is PAR-18's existing
#: `CopyPermanentEffect(referent="previous")`; the remaining work is the
#: "except it's a 3/3 ..." modifier grammar + the graveyard-exile clause
#: that populates `previous_targets`, a 12-SOLO cluster left to PAR-30.
#: +45 cache cards (parser_probe diff, full cache, 0 regressed).
#: "131": ENG-32 — Waterbend (RULE 701.67). The activated `waterbend {N}:`
#: cost already parsed (the word is noise over a `{N}` mana cost, the
#: Convoke-style helper a documented simplification); this batch is the
#: *bodies* those cards were actually blocked on, all general primitives:
#: "~ / creatures you control ha[s|ve] base power and toughness N/M until
#: end of turn" (`_BASE_PT_UNTIL_EOT_RE` → a resolve-time layer-7b `pt_set`
#: via `grant_until`, with `{X}` resolved in `GrantUntilEffect.apply`);
#: bare "~ / target creature can't be blocked this turn"
#: (`_CANT_BE_BLOCKED_TURN_RE` → `UnblockableEffect`, new self mode);
#: "enchanted creature's owner shuffles it into their library"
#: (`ShuffleSelfIntoLibraryEffect.subject="attached_permanent"`). Plus the
#: *mandatory* "as an additional cost to cast this spell, waterbend {N}"
#: (`AbilitySpec.additional_cost` gains a `waterbend` key; `ActivationCost.
#: help_pay_kind`; the {N} generic folded into `casting_mixin.effective_
#: cast_cost`). +50 cache cards (the can't-be-blocked and base-P/T handlers
#: unlock large non-Waterbend families too — Slip Through Space, Infiltrate,
#: Biomass Mutation, …), 0 regressed. Still UNMODELED and tracked in PAR-30:
#: "waterbend {X}" additional cost (needs {X}-announcement plumbing), "you
#: may waterbend {N}" + "if the additional cost was paid" (a Kicker-shaped
#: optional-additional-cost feature), Ward—Waterbend, Exhaust + Waterbend,
#: the "whenever you waterbend/…" bending-verb trigger (Avatar Aang), and
#: cards blocked on unrelated clauses (Aang Swift Savior's airbend-a-spell,
#: Katara Bending Prodigy's "her" pronoun, Waterbender Ascension's quest
#: counters).
#: "130": ENG-33 follow-up (the "copy of that card" family the ticket's
#: 4th named primitive names) - `_copy_except_modifier` gained a
#: `_COPY_EXCEPT_PT_RE` branch for "except it's [a] <P>/<T> [<colour>]
#: <subtype> [creature] [in addition to its other types]" (the Anikthea /
#: Ardyn / God-Pharaoh's Gift / Hour of Eternity reanimator-token cycle,
#: and Ember Island Production's modal shape). The engine params all
#: already existed except colour: added `Card.as_copy(set_colors=...)` /
#: `RulesEngine.copy_permanent(set_colors=...)` /
#: `CopyPermanentEffect.set_colors`. **Documented simplification:** without
#: "in addition to its other types" the printed clause replaces the
#: copied creature's subtypes; this always appends (tribal-synergy-inexact
#: only). +1 now (Ember Island Production); each remaining cluster card is
#: blocked on its own separate small connector/filter gap ("if you exiled
#: a card this way", "non-aura enchantment card", "exile X target …") -
#: PAR-30.
#: "132": ENG-33 completion — the reanimator-token *connector* the 4th
#: primitive needed. `segmenter._EXILE_THEN_COPY_SENTENCE_RE` matches the
#: whole two-sentence span "Exile [up to N] target <X> card from [a/your]
#: graveyard. [If you do / If you exiled a card this way,] create a token
#: that's a copy of that card[, except <tail>]." at `parse_effect_body`
#: level (before the connector-split loop shatters it into a bare "if you
#: do, create …" half), parsing the exile and the copy independently and
#: requiring the exile to genuinely pick a graveyard card
#: (`_announces_creature_target`) — the RULE 608.2 pronoun
#: `CopyPermanentEffect(referent="previous")` reads back. The reflexive
#: connector needs no `pending_choice` (the copy already no-ops on an empty
#: `previous_targets`). "You may exile …" optionality is peeled and
#: re-folded; `handlers._EXILE_FROM_GRAVEYARD_RE` now also accepts the
#: untargeted "exile **a** creature card from your graveyard" determiner.
#: +1 now (Ardyn, the Usurper); the rest of the cycle each still block on a
#: *separate* filter/quantifier/trailing-sentence gap (non-aura enchantment
#: filter, colour filter, "exile X target …", "It gains haste until end of
#: turn." tail) — PAR-30. 0 regressed.
#: "133": PAR-30 — "Incubate X, where X is `<count>`" dynamic amount
#: (`_incubate_x`/`_INCUBATE_X_RE`). `CreateTokenEffect.extra_counters`
#: gained `count_from_count_selector` (a live `continuous.count_selector`
#: read — "the number of lands you control" / "creature cards in your
#: graveyard", the latter a new selector) and `count_from_trigger_event`
#: ("that spell's mana value"); "incubate X **twice**" is just
#: `create_token`'s own `count=2`. "…where X is its power" / "…that many
#: times" stay UNMODELED, fail-closed. +3 (Glistening Dawn, Blight Titan,
#: Chrome Host Seedshark), 0 regressed.
#: "134": PAR-30 — Earthbend residue. "earthbend X, where X is [twice] the
#: number of `<count>`" (`_earthbend_x`/`_EARTHBEND_X_RE`): `EarthbendEffect`
#: gained `amount_from_count_selector` (live `continuous.count_selector`) +
#: `amount_multiplier` (Bumi's Feast Lecture's "twice"). "earthbend N, then
#: untap **that land**" (Avatar Kyoshi): `earthbend` is now recognised by
#: `segmenter._announces_creature_target` as picking a land, and a new
#: `previous_subject`-only `_TAP_PREVIOUS_SUBJECT_RE` claims "tap/untap that
#: land|permanent|artifact|creature" — which also closed a cluster of
#: "pump/attach/+1+1-counter target creature. Untap that creature." cards.
#: "…where X is that creature's power" stays UNMODELED. +12 (Rockalanche,
#: The Boulder, Bumi's Feast Lecture, Avatar Kyoshi + Savage Surge, Stony
#: Strength, Galadhrim Bow, Stun Sniper, Super Suit, Veteran's Reflexes,
#: Seedcradle Witch, Stabbing Pain), 0 regressed.
#: "135": PAR-30 — three small grammar widenings. (a) "those creatures" /
#: "each of those creatures" alongside "they" as the RULE 115 previous-
#: target-group pronoun (`_PREV_GROUP_SUBJECT`) — Cauldron Haze/of Souls.
#: (b) "each creature you control with a counter on it" group selector
#: (`_GROUP` + `_GROUP_SELECTORS` + `continuous.group_selector_objects`'
#: new `creatures_you_control_with_a_counter`) — Iroh, Dragon of the West
#: (ENG-31 parametric-keyword grant over a group). (c) an optional "during
#: an opponent's turn" qualifier on `_CAST_SPELL_TRIGGER_PLAIN_RE` mapping
#: to the trigger's existing `not_controllers_turn` gate — Fire Nation Occupation
#: + the "flash matters" cluster (Brineborn Cutthroat, Dream Spoilers, Glen
#: Elendra Pranksters, …). +11, 0 regressed. Fire Nation Cadets ("~ has
#: firebending N as long as there's a lesson card in your graveyard") still
#: needs a self-keyword-grant static shape + that condition — PAR-30.
#: "136": PAR-30 — the threaten / "it gains haste" restatement tail. (a) a
#: singular-pronoun previous-subject pump family ("it [also] gets +N/+N …" /
#: "it [also] gains `<kw>` until end of turn" — `_PUMP_PREV_SINGULAR_*_RE`,
#: `previous_subject_only`), the singular sibling of `_PUMP_PREVIOUS_TARGETS_*`.
#: (b) the connector-split loop now *propagates* the previous-subject referent
#: through a clause that itself consumed the pronoun ("untap that creature." →
#: "it gains haste."), so a threaten card's third+ restatement sentence still
#: resolves. (c) `_GAIN_CONTROL_HASTE_TAIL_RE` also accepts "untap that
#: permanent" and a ", and" join. Threaten payoffs (Bloody Betrayal, Infernal
#: Captor, …) + clash "if you win, that creature gets …" (Fistful of Force).
#: "137": PAR-30 — the "[Then] sacrifice / exile <it / that creature / that
#: token / them / those tokens> at the beginning of [the/your] next end step."
#: trailing clause (~100 SOLO cache cards — the single biggest RULE 701-trail
#: sub-cluster). One ungated handler → `create_delayed_trigger` (RULE 603.7,
#: `step="end"`) with a new `capture="previous_or_self"` that bakes in the
#: earlier clause's RULE 115 target (`previous_targets`) or created object
#: (`created_objects`), falling back to the ability's own source for a bare
#: self-subject "sacrifice it" (Brackwater Elemental). +21 (Tidal Wave,
#: Akoum Stonewaker, Dawn of the Dead, In Thrall to the Pit, …), 0 regressed —
#: the rest of the ~100 stay blocked on their own *other* clauses.
#: "138": PAR-30 — threaten-effect antecedent widening. `_gain_control_eot`
#: now takes "another target …", a bare "target artifact", and a "with power
#: N or less/greater" filter (`GainControlUntilEndOfTurnEffect.creature_
#: filter`); a new whole-clause `_GAIN_CONTROL_EOT_PER_OPPONENT_RE` reaches
#: the `count_selector="opponents"` shape (`_goad_per_opponent`'s sibling)
#: over a now-multi-target `GainControlUntilEndOfTurnEffect` (`apply`
#: iterates every chosen target). +6 (Enthralling Victor, Metallic Mastery,
#: Mass Mutiny, Molten Primordial, Smelt-Ward Ignus, Wrangle), 0 regressed.
#: "139": PAR-30 — the pre-daybound Innistrad **werewolf** day/night check
#: (RULE 603.4 intervening-if): "at the beginning of each upkeep, if no
#: spells were cast last turn, transform ~." (front → werewolf) / "…if a
#: player cast 2 or more spells last turn, transform ~." (back → human).
#: Two `parse_effect_body` leading-if handlers → `ConditionalEffect`'s new
#: `no_spells_cast_last_turn` / `two_or_more_spells_cast_last_turn` keys,
#: reading `GameState._last_turn_spell_count` (the same field
#: `apply_day_night_turn_check` / RULE 731.2 already use). +27 — the whole
#: DFC werewolf cycle (Reckless Waif, Kruin Outlaw, Mayor of Avabruck, …),
#: 0 regressed.
#: "140": PAR-30 — the O-Ring / Banisher Priest / Fiend Hunter family, modern
#: one-sentence templating: "exile `<TARGET>` [an opponent controls] until ~
#: leaves the battlefield." `handlers._exile_until_leaves` emits an
#: `ExileEffect(remember=True)` with a new `until_source_leaves` param;
#: `segmenter.segment_line` reads that param and synthesizes the companion
#: `LEAVES_BATTLEFIELD` → `return_linked_exile` ability (a single body parse
#: emits one ability, the return is a second). Both halves' engine
#: primitives pre-existed (MEC-21 / MEC-30 / Skyclave Apparition). +42
#: (Banisher Priest, Banishing Light, Cast Out, Conclave Tribunal, Glass
#: Casket, …), 0 regressed. Old two-sentence O-Ring templating stays open.
#: "141": PAR-30 — `_BECOMES_TARGET_TRIGGER_RE` accepted only "Whenever";
#: the ~19-card Innistrad/Zendikar **Illusion cycle** (Phantasmal Bear,
#: Frost Walker, Skulking Ghost, Gossamer Phantasm, …) prints "**When** ~
#: becomes the target of a spell or ability, sacrifice it." — interchangeable
#: here (a self-sacrifice fires identically either way). One-word regex
#: widen to `when(?:ever)?`. +21, 0 regressed. Engine side (`EventType.
#: BECOMES_TARGET` + `SacrificeSelfEffect`) is MEC-19, unchanged.
#: "142": PAR-30 (Earthbend residue, card 1 of 3) — "Earthbend N. **When you
#: do,** `<effect>`." (Earth Rumble). "earthbend N" is a mandatory keyword
#: action, so RULE 603.3's "when you do" always fires; the two sentences
#: collapse to one plain `[earthbend N, <effect>]` sequence, the same
#: certain-antecedent rationale `_SACRIFICE_THEN_WHEN_YOU_DO_RE` uses.
#: `_EARTHBEND_THEN_WHEN_YOU_DO_RE` in `segmenter`. +1, 0 regressed.
#: "143": PAR-30 (Earthbend residue, card 2 of 3) — "Whenever a **nonland**
#: creature you control dies, earthbend X, where X is **that creature's
#: power**." (Beifong's Bounty Hunters). `_GROUP_SUBJECT_RE` gained an
#: optional `nonland` qualifier → `condition["nonland"]` →
#: `effect_binder._build_group_ok`'s new `want_nonland` (checked against the
#: DIES event's snapshotted `object_types`, same shape as `nontoken`). New
#: `_EARTHBEND_THAT_CREATURES_POWER_RE` handler → `EarthbendEffect.
#: amount_from_trigger_event="power"`, reading the DIES event's RULE 400.7
#: last-known-power snapshot (now stamped by `damage_death_mixin`, mirroring
#: LEAVES_BATTLEFIELD's existing `power=`). +1, 0 regressed.
#: "144": PAR-30 (Airbend residue) — widened `_AIRBEND_RE` for the qualifier
#: set real Avatar cards actually print ("[up to N / any number of] [other /
#: another] target `<X>` [you control]") and added `_AIRBEND_TRIGGER_
#: SUBJECT_RE` ("airbend that creature / it" → `ExileEffect` `target_kind=
#: "trigger_subject"`, MEC-38 — Monk Gyatso's "you may airbend that
#: creature" on a group BECOMES_TARGET trigger). +2 SOLO (Monk Gyatso,
#: Airbender's Reversal); also unblocks the airbend *clause* on Aang
#: Airbending Master / Aang the Last Airbender / Appa Loyal / Appa
#: Steadfast (each still blocked on its own other clauses). "airbend …
#: creature or **spell**" (Aang, Swift Savior — exile off the stack) stays
#: open. 0 regressed.
#: "145": PAR-30 (Airbend residue — cluster closed) — "airbend up to one
#: other target creature **or spell**" (Aang, Swift Savior). `_AIRBEND_RE`
#: gained an `or spell` tail → `target_kind="spell_or_creature"` (the
#: MEC-43 Unsubstantiate targeting union) + a new `ExileEffect.spell_or_
#: permanent` flag: a chosen target that is a live spell on the stack is
#: pulled off it (`RulesEngine.move_spell_off_stack(item, "exile")`, RULE
#: 400.1 — it never resolves) instead of `context.exile`, then the same
#: `_post_exile` recast-permission riders apply. Mirrors `ReturnToHand
#: Effect`'s own `spell_or_permanent`. +1; the Airbend residue cluster is
#: now closed. 0 regressed.
#: "146": PAR-30 — the "Create a token …. **It** gains haste until end of
#: turn." tail. Three small pieces: `segmenter._announces_creature_target`
#: now recognises a `create_token`/`copy_permanent`/`become_copy` spec (the
#: created object is the next clause's "it"); `PumpEffect.previous_subject`
#: falls back to `GameContext.created_objects` when `previous_targets` is
#: empty; the connector-split loop seeds its pronoun chain from the caller's
#: `previous_subject`/`previous_selector` (a two-sentence wrapper passes
#: `previous_subject=True` for a span it knows opens with a referent — the
#: first sub-part must inherit it). Also `_DELAYED_SAC_EXILE_TAIL_RE` gained
#: a `destroy` verb → new `destroy_specific` effect (Old Hob's "destroy it
#: at the beginning of the next end step"). +9 (Harried Dronesmith,
#: God-Pharaoh's Gift, Séance, Mordor on the March, Mardu Charm/Monument,
#: Mogg Cannon, Rebellion of the Flamekin, Salt Road Skirmish), 0 regressed.
#: "147": PAR-30 — Clash (RULE 701.30) win-branch residue, batch 1. Five
#: small pieces: "you clash and win" as a WON_CLASH trigger phrasing
#: (Sylvan Echoes); `_FREE_CAST_FROM_HAND_RE` accepts "…spell from your hand
#: with mana value N or less…" word order (Marvo, Deep Operative);
#: `return_self_to_hand` accepts "return **this card** to its owner's hand"
#: (Ringskipper); the connector-split loop treats a bare `clash` spec as a
#: **referent-transparent** interstitial, so "create 2 tokens. clash. if you
#: win, **those creatures** gain deathtouch …" keeps its pronoun chain
#: (Gilt-Leaf Ambush); `_PUMP_PREV_SINGULAR_PT_RE` accepts "gets **an
#: additional** +N/+N" (Fistful of Force). +5, 0 regressed. ~18 clash cards
#: remain, each on a distinct win-branch body handler.
#: "148": PAR-30 — "{X}-scaled damage" handler + Clash batch 2. `_damage_x`
#: ("~ deals **x** damage to `<target>`", digit-free so no overlap with the
#: `NUMBER` `damage` row) emits `EffectSpec("damage", {"amount": "x"})` —
#: the `"x"` sentinel `RulesEngine._substitute_x` already rewrites off the
#: spell/ability's announced {X}. +20 classic X-burn spells/abilities
#: (Blaze, Devil's Play, Fanning the Flames, Volcanic Geyser, Cinder
#: Elemental, Heat Ray, Pain Kami, Goblin Dynamo, …) **plus** Titan's
#: Revenge (a clash card blocked on its pre-clash "~ deals X damage to any
#: target" clause). Also `_DESTROY_ALL_RE` gained an optional " your
#: opponents control" scope → `opponents_enchantments`/`opponents_artifacts`
#: (`_mass_selector_objects`) — Spring Cleaning's clash win-branch. +21
#: total, 0 regressed.
#: "149": PAR-30 — "**doesn't untap during its controller's next untap
#: step**". New `SkipNextUntapEffect` (`skip_next_untap`) sets `GameObject.
#: skip_next_untap` — RULE 702.19b's own one-time flag, already consumed and
#: cleared in `_step_untap` (built for exert). A pure rider: "Tap X. It
#: doesn't untap …" is the ordinary `[tap, skip_next_untap{previous_
#: subject}]` sequence. Three subject shapes (`target`/prev-subject/self).
#: Also widened `_tap`'s allowed target kinds to the controller-scoped
#: creature kinds so "tap target creature **an opponent controls**"
#: (Chillbringer/Berg Strider &c.) parses at all — that was a standalone
#: gap. **+51** — the whole tap-and-freeze tempo family (Frost Lynx, Frost
#: Titan, Dungeon Geists, Nebelgast Herald, Kor Hookmaster, Barl's Cage,
#: Chandra's Revolution, …) plus Entangling Trap (a clash card). 0 regressed.
#: "150": PAR-30 — "gains **protection from the color of your choice** until
#: end of turn" (RULE 702.16 — Gods Willing / Emerge Unscathed / Feat of
#: Resistance / Redeem the Lost [a clash card]). Engine primitive is Mother
#: of Runes' `GrantProtectionEffect` / `RulesEngine.grant_protection_choice`
#: (the interactive `grant_protection_color` pick → `temp_protections`);
#: only this phrasing's parser recognition was missing. `GrantProtection
#: Effect` gained a self (`target_kind=None`) and a `previous_subject` mode
#: ("~ gains …" / "put a counter on target creature you control. **it**
#: gains …"). +17 (the Sejiri/Shelter cycle, Stave Off, Center Soul, …),
#: 0 regressed.
#: "151": PAR-30 — "**reveal cards from the top of your library until you
#: reveal a `<type>` card. put that card `<onto the battlefield / into your
#: hand>` and the rest `<bottom / graveyard / shuffle>`**". The engine
#: primitive is `RulesEngine.dig_until` / `effects.DigUntilEffect` (the
#: generalized cascade dig, predicate + both destinations parameterized) —
#: only the "reveal until a *type* predicate" recognition was missing.
#: `_REVEAL_UNTIL_TYPE_RE` + a `_DIG_UNTIL_REST_RES` search over the many
#: "put all other cards revealed this way …" / ", then shuffle …" tail
#: spellings. Fails closed on "onto the battlefield **tapped**" (Clifftop
#: Lookout — `dig_until` has no tapped-entry mode). +9 (Recross the Paths
#: [a clash card], Atla Palani, Foster, Evolutionary Leap, Madcap
#: Experiment, Audacious Reshapers, …). 0 regressed.
#: "152": PAR-30 — "**you gain life equal to `<its / that creature's>`
#: `<power / toughness>`**" (~36 SOLO — Bottle Golems / Angelic Chorus /
#: **Weed Strangle** [a clash card] / Brightmare / Tribute to Hunger / …).
#: New `GainLifeEffect.amount_from_subject` string param naming the object +
#: characteristic; three gated parser rows — "its" on a bare-`~` trigger →
#: ``self_*`` (`self_subject_only`), "its" on a group trigger →
#: ``trigger_subject_*`` (`group_subject_only`), "that creature's" after
#: another clause → ``previous_subject_*`` (`previous_subject_only`, RULE
#: 608.2h last-known info). +14, 0 regressed; verified end-to-end.
#: "153": PAR-30 — "**~ [also] deals N damage to that creature's
#: controller**" (~22 SOLO — Consign to the Pit / Blur of Blades / Burn the
#: Impure [previous-subject] · Battle Strain / Dingus Staff / Gimli
#: [group/trigger subject] · **Lash Out** [a clash card]). New
#: `DealDamageEffect.recipient_subject` string (`"<who>_controller"`) —
#: derives the recipient player from `GameContext.previous_targets` (RULE
#: 608.2h last-known controller) or the firing event's own
#: ``instance_id``/``controller_id`` payload; no RULE 115 target of its own,
#: so `target_spec` is `None` and `apply` short-circuits to a direct
#: `deal_damage(player, …)`. Two gated parser rows
#: (`previous_subject_only` / `group_subject_only`). +10, 0 regressed;
#: verified end-to-end.
#: "154": PAR-30 — two small clash win-branch bodies, no general family
#: left in the residue. "**untap all `<basic land subtype>` you control**"
#: (Woodland Guidance) → new `continuous.group_selector_objects`
#: ``lands_you_control_of_type_<x>`` branch + `_is_valid_tap_selector`
#: widen (the land sibling of ``creatures_you_control_of_type_<x>``);
#: "**~ deals N damage to each creature blocking it**" (Fire Juggler, 4
#: cards) → new `DealDamageEffect` ``each_creature_blocking_source``
#: selector (every battlefield creature whose `GameObject.blocking` names
#: this ability's own source). +2, 0 regressed; verified end-to-end.
#: "155": PAR-30 — the Kicker-shaped **optional additional cast cost**
#: primitive (RULE 601.2b): "as an additional cost to cast this spell,
#: **you may** <waterbend {N}/blight N/behold X/sacrifice …>." →
#: `AbilitySpec.additional_cost_optional` + `GameObject.additional_cost_
#: paid`, a second `pay_additional` cast variant offered by
#: `_offer_cast`; and "**if this spell's additional cost was paid**,
#: `<effect>`." → `EffectSpec.condition`'s new ``"additional_cost_paid"``
#: key (`ConditionalEffect`, the generic sibling of ``"bargained"``). The
#: `<who>` flag half of the Waterbend residue's biggest cohesive cluster;
#: per-card bodies (Ruinous Waterbending, Secret of Bloodbending, …) still
#: open. 0 regressed.
#: "156": PAR-30 — "**as long as there's a `<subtype>` card in your
#: graveyard**" (the Avatar: TLA "Lesson" cards) → a new
#: `static_conditions.subtype_in_graveyard` `active_if` kind
#: (`_STATIC_CONDITION_RES` row), plus its trigger intervening-if sibling
#: "**if there's a `<subtype>` card in your graveyard, `<effect>`**" →
#: `ConditionalEffect`'s already-built ``graveyard_has_type`` key
#: (`segmenter._GRAVEYARD_HAS_SUBTYPE_CONDITION_RE`). +4 (Aang A Lot to
#: Learn, First-Time Flyer, Platypus-Bear, Walltop Sentries); Fire Nation
#: Cadets still blocked on the "~ has firebending N" self parametric-grant.
#: 0 regressed.
#: "157": PAR-30 — the **self** parametric-keyword grant static ("~ has
#: firebending N [as long as `<cond>`]", Fire Nation Cadets). ENG-31 built
#: the group/pump/token parametric grants but not the self one;
#: `static_handlers._SELF_GRANT_RE`'s keyword capture widened to accept a
#: trailing digit and routed through `_split_keywords_with_parametric`
#: (only when `_flag_keywords` fails, so the landwalk/flag path is
#: untouched) → `grant_keyword {affects: self, parametric_keywords: [...]}`,
#: which the existing ENG-31 layer-6 machinery already applies. Closes the
#: last lesson-card residue card. 0 regressed.
#: "158": PAR-30 — Katara, Seeking Revenge's two remaining clauses.
#: "**~ gets +P/+T for each `<subtype>` card in your graveyard**" → a self
#: `anthem` scaled by `continuous.count_selector`'s new
#: ``<subtype>_cards_in_your_graveyard`` prefix (a live type-line scan,
#: sibling of `subtype_in_graveyard`); "**`<effect>` unless `<its>`
#: additional cost was paid**" → the negative, suffix form of v155's
#: `additional_cost_paid` `EffectSpec.condition` (checked after the
#: connector split so it binds to its own clause only). Closes Katara. +1,
#: 0 regressed.
#: "159": PAR-30 — the "unless you pay `<cost>`" family. (a) `_UNLESS_COST`
#: (the closed cost vocabulary shared by `_SACRIFICE_UNLESS_PAY_RE` /
#: `_DESTROY_UNLESS_PAY_RE`) gains "**discard N cards**" (a plain count —
#: Avatar of Discord); the typed ("discard a creature card" → silently
#: free) and "at random" variants stay excluded. (b) New
#: `_TAP_UNLESS_PAY_RE` / `_EXILE_UNLESS_PAY_RE` — the tap/exile
#: consequence siblings, modeled via `pay_cost_then` with an empty
#: pay-branch and the tap/exile in ``else_effects`` (Carnophage,
#: Sangrophage, Heavyweight Demolisher, Electrozoa, Apocalypse Demon,
#: Demonlord of Ashmouth, Morgul-Knife Wound's granted form). +8, 0
#: regressed.
#: "160": PAR-30 — Incubate dynamic amount "…where X is **its power**"
#: (`_INCUBATE_X_RE` / `_incubate_x`). A "when ~ dies" trigger; the dying
#: creature's own last-known power is snapshotted on the DIES event
#: (RULE 400.7), so it needs no engine change — reuses
#: `CreateTokenEffect.extra_counters`' existing ``count_from_trigger_
#: event`` key (the same firing-event idiom `EarthbendEffect` uses for
#: "earthbend X, where X is that creature's power"). Bloated Processor,
#: Furnace Gremlin. +2, 0 regressed. "…incubate N that many times"
#: (a search-count repeat — Phyrexian Incubator) stays UNMODELED.
#: "161": PAR-30 — the shared `TARGET` macro gains a "**another target
#: creature you control**" row (RULE 109.5), routed to the engine's
#: existing `other_creature_you_control` kind (source excluded, "you
#: control" scoped, already fully wired in `targeting.py`); `_pump_target`
#: adds it to its pumpable-kind allowlist. +31 — mostly ETB / combat
#: triggers granting a keyword until end of turn (Heavenly Qilin, Duke
#: Ulder Ravengard, Selfless Savior, Void Grafter, …). 0 regressed. The
#: no-"you control" form ("another target creature") stays UNMODELED — its
#: `other_creature` kind is not engine-wired.
#: "162": PAR-30 — Incubate dynamic-amount residue. (a) "Its controller
#: incubates X, where X is **its mana value**" (Excise the Imperfect) →
#: `create_token`'s new ``creators="previous_target_controller"`` +
#: ``extra_counters``' new ``count_from_subject`` (shared
#: `_characteristic_of_subject` helper, now with a ``mana_value`` reading);
#: the plain exile handler also learned the real `nonland_permanent`
#: target kind (bonus: Anguished Unmaking, Utter End). (b) "…where X is
#: the number of creatures **exiled this way**" (Sunfall) → new
#: `GameContext.objects_exiled_this_way` accumulator (sibling of
#: `permanents_destroyed_this_way`, bumped by `context.exile`) read via
#: ``extra_counters``' new ``count_from_context`` key. +4, 0 regressed.
#: Still UNMODELED: "incubate N that many times" (Phyrexian Incubator —
#: search-result count across a `pending_choice` suspension) and
#: "incubate N X times" reading a source's ``x_paid`` (Progenitor Exarch).
#: "163": PAR-30 (Vote residue) — self-excluding mass destroy. New
#: `all_other_creatures` / `other_creatures_you_control` selectors on
#: `effects._mass_selector_objects`; `_DESTROY_ALL_OTHER_RE` claims
#: "destroy all other creatures[ you control]" / "…all creatures other
#: than ~" / "…except [for] ~" (+ optional "can't be regenerated" tail).
#: +1 (Novablast Wurm); also closes Magister of Worth's "destroy all
#: creatures other than ~" vote-branch gap (card still blocked on its
#: other branch). 0 regressed.
#: "164": PAR-30 (Vote residue) — Living Death mass graveyard recursion.
#: `ReturnFromGraveyardEffect.players` ("you" / "each_player") — a mass
#: untargeted return over every matching graveyard card; `_MASS_RETURN_
#: GRAVEYARD_RE` claims "[each player returns / you return] all/each
#: creature card[s] from [their/your] graveyard to the battlefield/hand".
#: `_vote_majority`'s off-stack guard narrowed to spare a `players`-scoped
#: (untargeted) branch. +2 (Empty the Catacombs; Magister of Worth, now
#: both vote branches modeled). 0 regressed.
#: "165": PAR-30 (Vote residue) — `_vote_per_vote` carries a leading
#: "each player / each opponent" subject off segment 0 onto a subject-less
#: later segment split from it by a bare "and" (Capital Punishment —
#: "each opponent sacrifices … for each death vote and discards a card for
#: each taxes vote"). +1, 0 regressed.
#: "166": PAR-30 (Vote residue) — plain "take an extra turn after this one"
#: effect-body handler → the pre-existing ``take_extra_turn`` effect type
#: (`effects.TakeExtraTurnEffect` / `GameState.extra_turns`). Nothing in
#: the parser emitted it before. Closes the modelable half of Plea for
#: Power's vote outcome ("if time gets more votes, take an extra turn …")
#: plus a wide spill of Time Walk / Temporal Manipulation / Capture of
#: Jingzhou / Part the Waterveil / Timestream Navigator &c. Riders on
#: other extra-turn cards ("skip the untap step of that turn", "…you lose
#: the game", "…for each coin that comes up heads") don't fullmatch and
#: stay their own tickets.
#: "167": PAR-30 (Vote residue) — "planeswalk" / "chaos ensues" outcome
#: bodies. Two new no-param effect types (`effects.PlaneswalkEffect` /
#: `ChaosEnsuesEffect`) wrapping `RulesEngine.planeswalk` / the new
#: `trigger_chaos` (factored out of `roll_planar_die`). Closes Path of
#: the Animist / Path of the Enigma (through `_vote_majority`'s body
#: parse) + Plain Walker's standalone "planeswalk" body. Fullmatch-only:
#: "planeswalk to <plane>" / "you may planeswalk" stay UNMODELED. +3.
#: "168": PAR-30 (reanimator-token residue) — "return [up to] X target
#: `<type>` cards from [scope] graveyard to your hand / the battlefield"
#: (Death Denied, Entreat the Dead, Shattered Crypt, Wake the Dead). The
#: count is the spell's announced {X}, read at target-gathering time via
#: `TargetSpec.count_selector="source_x_paid"` (the March of Swirling
#: Mist / Change of Plans idiom); `ReturnFromGraveyardEffect` gained a
#: `count_selector` param + a matching multi-target apply branch. New
#: `_RETURN_FROM_GRAVEYARD_X_RE`/handler.
#: "169": PAR-30 (villainous-choice / reanimator-token residue) — a
#: colour-list creature target on the pump family: "target `<c1>` or
#: `<c2>` creature gets +N/+M / gains `<kw>` until end of turn" (the
#: Weaver cycle — Hate/Rage/Sky/Might/Spirit Weaver, Sootstoke Kindler,
#: Wilderness Hypnotist). `PumpEffect` gained a `colors` param threaded
#: into its `TargetSpec` (`TargetSpec.colors` + `_color_ok` were already
#: wired in `legal_targets`, unused by pump). Dedicated
#: `_PUMP_TARGET_TWO_COLOR_RE`/handler, the `_DAMAGE_TARGET_TWO_COLOR_RE`
#: sibling (the shared `TARGET` macro has no colour slot).
#: "170": PAR-30 — the same colour-list target extended to removal:
#: `_DESTROY_COLOR_ADJ_RE` widened to a "`<c1>` or `<c2>`" adjective +
#: an optional "with `<kw>`" tail (Deathmark, Wallop); new
#: `_EXILE_TARGET_TWO_COLOR_RE`/handler (Celestial Purge). `DestroyEffect`
#: / `ExileEffect` gained a `colors` param threaded into their
#: `TargetSpec` (mirroring `DestroyEffect.color`'s single-letter form).
#: "171": PAR-30 — the colour-list target extended to bounce / put-on-
#: library / graveyard-recursion: `ReturnToHandEffect` /
#: `ReturnToLibraryEffect` / `ReturnFromGraveyardEffect` each gained a
#: `colors` param → `TargetSpec.colors`; three dedicated
#: `_RETURN_*_TWO_COLOR_RE` handlers (Escape Routes, Hunting Drake, Crypt
#: Angel). Same `_two_color_letters` helper, same-colour-twice rejected.
#: "172": PAR-30 — colour-list target: `TapEffect` gained `colors` +
#: `_TAP_TWO_COLOR_RE` ("tap target `<c1>` or `<c2>` creature[ an
#: opponent controls]" — Tidebinder Mage, its "doesn't untap for as long
#: as you control ~" tail already rides the pronoun); new compound
#: `_RETURN_SELF_AND_TWO_COLOR_RE` ("return ~ and target `<c1>` or `<c2>`
#: creature[ you control] to their owner's hand" → two `return_to_hand`
#: specs — Snow Hound). +2.
#: "173": MEC-46 — RULE 701.38 vote outcome bodies that needed new
#: engine primitives. Four handlers on the shared `_VOTE_HEADER_RE`:
#: `_vote_winner_protection` ("~ gains protection from each color with the
#: most votes or tied for most votes" → `_request_vote(winner_specs=...)`
#: + an indefinite RULE 611 self-scoped `grant_protection_static` per
#: leading colour — Council Guardian); `_vote_object` ("vote for a nonland
#: permanent you don't control / a card in your graveyard, exile / return
#: each most-voted" → new `vote_object` spec / `ObjectVoteEffect` /
#: `_request_object_vote` / `vote_object` pending_choice — Council's
#: Judgment, Custodi Squire); `_vote_expropriate` (count-aware
#: `take_extra_turn` per time vote + `per_voter_gain_control` per money
#: vote — Expropriate); `_forced_vote` ("you choose how each player votes
#: this turn" → `set_forced_voter` / `GameState.forced_vote_controller_id`
#: — Illusion of Choice). Plus Galadriel, Elven-Queen: `_add_counters_
#: ring_bearer` ("put a +1/+1 counter on your Ring-bearer" →
#: `AddCountersEffect.ring_bearer`), and a phase-trigger intervening-if
#: `_ANOTHER_SUBTYPE_ENTERED_IF_RE` → `static_conditions`'
#: `another_subtype_entered_this_turn` trigger `active_if`. +6.
#: "174": PAR-30 — colour-list target on a graveyard-card exile. New
#: `_color_word_list` (N-colour generalization of `_two_color_letters`);
#: `_EXILE_FROM_GRAVEYARD_RE` gained an optional `(?P<colors>…)` group →
#: `exile` spec's `colors` → `TargetSpec.colors`, honoured in
#: `targeting.legal_targets`' graveyard-card branch (the `_color_ok` call
#: every battlefield branch already had). Closes Offspring's Revenge. +1.
#: "175": PAR-30 — a combat-state tail on the destroy-colour-adjective
#: handler. `_DESTROY_COLOR_ADJ_RE` gained an optional "…that's attacking
#: or blocking / attacking / blocking" → `creature_filter` boolean;
#: `combat.matches_object_filter` gained `blocking` / `attacking_or_
#: blocking` keys (the siblings of the pre-existing `attacking`). Closes
#: Surge of Righteousness. +1.
#: "176": PAR-30 — RULE 615.6 "the damage can't be prevented" recognition.
#: `DealDamageEffect` gained an `unpreventable` flag (flips `GameState.
#: damage_prevention_disabled` for the span of one `apply()`); the
#: two-colour damage-target regex folds in the rider (Combust). New
#: standalone `_DISABLE_DAMAGE_PREVENTION_RE` → the pre-existing
#: `disable_damage_prevention` effect, previously hand-authored-only
#: (Flaring Pain, Impractical Joke, Unstable Footing, Pyrewood Gearhulk,
#: A-Ready to Rumble). +6.
#: "177": PAR-30 — "create a … creature token that's/are **tapped and
#: attacking**" (RULE 508.4). New `RulesEngine.put_onto_battlefield_
#: attacking` primitive (attack flags + auto-defender + ATTACKS event);
#: `CreateTokenEffect.attacking`; the inline-token regexes
#: (`_TOKEN_TAPPED_ATTACKING` suffix on the plain / "that many" / "create x
#: … where x" rows). +10 — Captain's Claws, Hanweir Garrison, Hero of
#: Bladehold, Skyknight Vanguard, Mardu Ascendancy, Militia's Pride, &c.
#: "178": PAR-30 — "put a `<filter>` creature card from your hand onto the
#: battlefield [tapped and attacking]". `_put_from_hand` gained a
#: creature-subtype filter ("Soldier creature card" → `{"type": …}`,
#: "Angel, Demon, or Dragon creature card" → list) and a colour filter
#: ("blue or red creature card" → `{"color": […]}`), + an optional
#: "…tapped and attacking" tail. `PutFromHandOntoBattlefieldEffect.
#: attacking` → new `"battlefield_attacking"` search destination (enters
#: tapped, then `put_onto_battlefield_attacking`). +7 — Preeminent Captain,
#: Goblin Lackey, Warren Instigator, Mindwrack Liege, Didgeridoo, &c.
#: "179": PAR-30 — "tapped and attacking" cluster, batch 3.
#: `_DELAYED_SAC_EXILE_TAIL_RE` gained an "at end of combat" timing
#: (→ `create_delayed_trigger` step `"end_combat"`) + "the token[s]"
#: subject; new `_CREATED_ENTERS_ATTACKING_RE` segmenter idiom ("Create
#: <token>. The token[s] enter[s] tapped and attacking." stamps the
#: preceding `create_token`/`copy_permanent`); new `_LOOK_TOP_PUT_
#: ATTACKING_RE` → `impulsive_look` with `hit_destination="battlefield_
#: attacking"`; `CopyPermanentEffect` gained `tapped`/`attacking`. +18 —
#: Geist of Saint Traft, Crumbling Colossus, the Basilisk morph cycle,
#: Serpentine/Stone-Tongue Basilisk, Ohran Viper, &c.
#: "180": "When you control no `<basic land type>`, sacrifice ~." (RULE
#: 603.8 state trigger — Bog Serpent / Sea Serpent / Dandân cycle).
#: `_CONTROL_NONE_SACRIFICE_RE` → a `LEAVES_BATTLEFIELD` trigger gated by
#: `effect_binder`'s new `controls_none_of_type` predicate (a live
#: battlefield scan, excluding the just-left permanent per RULE 603.6a).
#: +11.
#: "181": "This spell costs {N} less to cast **if it targets a
#: `<criteria>`**." (RULE 601.2f — Ajani's Response / Knockout Blow /
#: Depower cycle). `cost_reduction` gained `reduce_if_targets` (a criteria
#: dict); `continuous.self_cost_reduction_for` takes the caster's chosen
#: targets and applies the discount only when one matches
#: (`_obj_matches_target_criteria`); `_adjust_cost`/`effective_cast_cost`
#: thread `targets`; `combat.matches_object_filter` grew a `tapped` key.
#: Recognised criteria: card type + tapped / attacking / blocking /
#: colour. +15.
#: "182": PAR-30 — `reduce_if_targets` criteria widened. `_targets_
#: reduction_criteria` now parses the phrase word-by-word: a bare subtype
#: or "X or Y" pair ("a spider", "a mount or vehicle"), a "you control" /
#: "you don't control" scope, "token", "with `<keyword>`", "legendary",
#: and the "a `<x>` spell" stack-target forms. `continuous._obj_matches_
#: target_criteria` grew `legendary` / `is_token` / `controller` handling
#: (via a threaded `caster_id`). +10 — Grow Extra Arms, Mystical Dispute,
#: Out of Air, Price of Fame, Run Over, Savage Stomp, Swampsnare Trap,
#: This Town Ain't Big Enough, Hunter's Mark, Mascot Interception.
#: "183": Strive (MEC-4) recognition when `normalize` has already stripped
#: the "Strive —" label (Scryfall lists it in `keywords` but it's not a
#: registered RULE 701/702 keyword). `_STRIVE_LINE_RE`'s prefix is now
#: optional — one-line fix, the engine (`obj.strive_cost` /
#: `effective_cast_cost`) was already complete. +9 — Aerial Formation,
#: Ajani's Presence, Blinding Flare, Colossal Heroics, Consign to Dust,
#: Cruel Feeding, Desperate Stand, Kiora's Dismissal, Rouse the Mob.
#: "184": "Return it to the battlefield [tapped] under its owner's/your
#: control[ with a +1/+1 counter on it]." (RULE 400.7 self-recursion) — new
#: `_RETURN_SELF_TO_BATTLEFIELD_RE` reaches the pre-existing `ReturnSelfTo
#: BattlefieldEffect` (gained `under_your_control`/`extra_counters`) from
#: two shapes: a granted DIES-trigger continuation via
#: `_quoted_ability_grant_effects` (Feign Death, Undying Malice) and a
#: plain "exile ~, then return it to the battlefield under its owner's
#: control" blink chain (Flicker of Fate, Aethergeode Miner, Changing
#: Loyalty, Flickering Spirit, Fungal Fortitude, Planar Incision). +8.
#: "185": PAR-30 — "tapped and attacking **that player/that opponent**"
#: trailing defender ref on the put-from-hand (`_PUT_FROM_HAND_RE`), look-top
#: (`_LOOK_TOP_PUT_ATTACKING_RE`), inline-create-token (`_TOKEN_TAPPED_
#: ATTACKING`) and "the token enters …" (`_CREATED_ENTERS_ATTACKING_RE`)
#: routes. The named defender is the one the source is already attacking,
#: which `RulesEngine.put_onto_battlefield_attacking` derives from the other
#: attackers, so the phrase is consumed rather than re-modeled. Kaalia of
#: the Vast, The Vast Scrier, Owlbear Cub, Seraphic Greatsword, Soaring
#: Lightbringer.
#: "186": PAR-30 — `_NAMED_COUNTER_KINDS` widened from {spore,burden,quest}
#: with 26 more pure card-text-driven counter kinds (charge, oil, storage,
#: ki, verse, page, plan, soul, fuse, depletion, flood, bounty, brick,
#: study, plague, doom, growth, point, infection, hatchling, pressure,
#: slime, tide, ice, flame, hour) — each verified to have no reader in
#: `game/`. Keyword counters (RULE 122.1e), subsystem counters (age/time/
#: level/loyalty/lore/rad/energy) and replacement counters (stun/shield)
#: stay out — they'd half-model. Still a fail-closed whitelist.
#: "187": Bucket-A cleanup (Commander-legal tail) — `_split_triggered_modal_
#: block` now recognises its trigger wrapper via `segment_line` (the exact
#: grammar an ordinary triggered ability uses) and carries the *whole*
#: trigger dict through, instead of the narrow generic `_trigger_event`/
#: `_trigger_condition` pair. So a modal block driven by "attacks or blocks",
#: "whenever you cast a noncreature spell", "at the beginning of your
#: upkeep/combat", "whenever you cast your second spell each turn", … now
#: parses (Elder Gargaroth, Ojutai Exemplars, Etherwrought Page, Cosmogrand
#: Zenith, Ferocification, Appa Loyal Sky Bison, +2). +8, 0 regressed.
#: "188": PAR-30 "Tapped and attacking" — the per-opponent distributive
#: "**for each opponent**, [you] create a … token[ that's tapped and
#: attacking that opponent]" (Endless Foot Assault, Stampede Surfer). New
#: `CreateTokenEffect.per_opponent`: the controller makes one token per
#: opponent, and with `attacking` each token is put into combat against a
#: *distinct* opponent (RULE 508.4a per token). Parser: a leading
#: `for each opponent, ` group on the inline `create_token` row. +2.
#: "189": PAR-30 "Tapped and attacking" — `_CREATED_ENTERS_ATTACKING_RE`
#: gained a **bare token-name** subject ("create Ragavan, …. Ragavan enters
#: tapped and attacking." — Kari Zev; the name only binds a spec whose
#: `token_name` matches it) and a **`populate`** "before" ("populate. That
#: token enters tapped and attacking." — Ghired). `PopulateEffect` gained
#: `tapped`/`attacking`, threaded to `RulesEngine.populate(enter_state=…)`
#: — applied to the copy in the degenerate paths, carried on the
#: `pending_choice` for the interactive 2+-token one. +2.
#: "190": PAR-30 "Tapped and attacking" — put-from-hand card filters:
#: "with lesser power" (Shadowfax — `PutFromHandOntoBattlefieldEffect.
#: power_less_than_source`, a `max_power` cap vs the source at resolve) and
#: "with mana value X or less … where X is the number of attacking
#: creatures you control" (Kinscaer Sentry — `max_mana_value_selector`,
#: folded into `criteria["max_mana_value"]` via `continuous.count_selector`
#: at resolve). Fixed "with mana value N or less" also accepted. +2.
#: "191": PAR-30 "Tapped and attacking" trail — `_DELAYED_SAC_EXILE_TAIL_RE`
#: gained a **"return `<it/that creature>` to (your|its owner's) hand"** verb
#: alongside sacrifice/exile/destroy → `create_delayed_trigger` with a new
#: `return_specific_to_hand` inner (`ReturnSpecificToHandEffect`, same
#: `.objects` bake-in via `capture="previous_or_self"`). A loan bounced end
#: of turn / at end of combat: Alora, Merry Thief; Ilharg; Zara; and the
#: "when ~ attacks or blocks, return it … at end of combat" Phantom-Whelp
#: cycle. +8.
#: "192": PAR-30 "Tapped and attacking" trail — the qualified attack
#: trigger "whenever ~ attacks **a player who controls N or more lands**"
#: (Owlbear Cub). New `_ATTACKS_DEFENDER_LANDS_RE` keeps it a
#: `{"subject": "self"}` ATTACKS trigger with a `defender_controls_lands_
#: at_least` key, gated in `effect_binder._trigger_condition` off the
#: ATTACKS event's `defending_player_id` (same "gate an event on a live
#: state read" idiom as `controls_none_of_type`). +1.
#: "193": PAR-30 "Tapped and attacking" trail — the `look_top` mid-clause
#: "It gains <keyword> until end of turn." interpose between "…tapped and
#: attacking." and "Put the rest…" (**Winota, Joiner of Forces / A-Winota**).
#: `_LOOK_TOP_PUT_ATTACKING_RE` grew an optional group validated against
#: `_LOOK_TOP_HIT_GRANT_KEYWORDS` (fail-closed); `hit_grant_keywords`
#: threads impulsive_look → `ImpulsiveLookEffect` → `_request_impulsive_look`
#: → `_resume_impulsive_look`, which adds `temp_keywords` to the
#: placed card (RULE 514.2). +2.
#: "194": `normalize` folds a comma-less legendary's **given name** — the
#: single word before " of " in "Kaalia of the Vast" → `~` — where it's a
#: genuine self-reference. Context-gated (`_fold_given_name_prefix`,
#: `_PREFIX_TYPE_BEFORE`/`_PREFIX_TYPE_AFTER`) so a name that doubles as a
#: creature type / keyword ("another **Cleric** you control", "a **Knight**
#: creature token", "gains **fear** until end of turn") keeps that reading.
#: +5 (Kaalia of the Vast, Karlov of the Ghost Council, Beregond of the
#: Guard, Braulios of Pheres Band, Sorin of House Markov).
#: "195": PAR-30 "copy of a named card" — **The Joiner of Cats**. New
#: `create_token_copy_of_named` spec / `CreateNamedCardTokenEffect` makes a
#: token whose copiable values come from a real card resolved by name from
#: the cache (`services.card_lookup`); the handler
#: (`_CREATE_NAMED_CARD_TOKEN_RE` + `_NAMED_CARD_SHAPE_RE`) only fires on a
#: proper-noun name, never "enchanted creature"/"chosen permanent". Plus
#: `impulsive_look` gains `miss_effect_specs` — the `_LOOK_TOP_PUT_ATTACKING_
#: RE` "if you don't put a card onto the battlefield this way, `<body>`."
#: else-branch, run in `_resume_impulsive_look` /
#: `_request_impulsive_look` when nothing is placed. +1.
#: "196": PAR-30 "copy of a named card" body singletons — **The Vast
#: Scrier**. `_request_search` / `PutFromHandOntoBattlefieldEffect` gain
#: `then_specs_if_none` — "if you don't put a card onto the battlefield
#: this way, `<body>`." (here `scry 2`) runs `<body>` when the from-hand
#: pick places nothing (declined in `_resume_search`, or nothing
#: eligible in `_request_search`). `_PUT_FROM_HAND_RE` also records the
#: explicit instruction "if it has any 'whenever ~ attacks' triggers, those
#: trigger" as `trigger_attacks`; ordinary entering-attacking remains silent
#: under RULE 508.3a.
#: +1.
#: "197": PAR-30 "copy of a named card" body singletons — **Living Laser**.
#: New `GameState.cards_discarded_this_turn` (bumped at every `DISCARD_CARD`
#: fire site via `RulesEngine._note_discarded`, reset like `cards_drawn_
#: this_turn`) + `continuous.count_selector("cards_discarded_this_turn")` +
#: `CopyPermanentEffect.count_selector`; `_COPY_SELF_FOR_EACH_RE` handler
#: ("for each card you've discarded this turn, create a token that's a copy
#: of ~[, except the token isn't legendary]"). The "…enter tapped and
#: attacking" / "exile the tokens at the next end step" tails already
#: parsed. +1.
#: "198": PAR-30 "copy of a named card" body singletons — **Sin, Spira's
#: Punishment**. New self-contained `RandomGraveyardExileCopyLoopEffect` /
#: `random_graveyard_exile_copy_loop` — "exile a permanent card from your
#: graveyard at random, then create a tapped token that's a copy of that
#: card. if the exiled card is a land card, repeat this process." (RULE 706
#: `RulesEngine.random_choice` + RULE 707.2 copy, land-keyed loop). +1.
#: "199": PAR-30 "Threaten / 'it gains haste' tails residue" — the
#: `gain_control_until_eot` restatement tail (`_GAIN_CONTROL_HASTE_TAIL_RE`)
#: now recurses a *richer*-than-bare-haste grant sentence ("untap it. it
#: gains trample and haste until end of turn" — Traitorous Blood; "…haste
#: and myriad…" — Firbolg Flutist) through `parse_effect_body` with
#: ``previous_subject`` on, so the existing `pump(previous_subject=True)`
#: keyword-grant handler claims it (no second RULE 115 target). +2.
#: "200": PAR-30 threaten residue — the *leading* "until end of turn, it …"
#: rich restatements: "it gains haste and '<quoted ability>'" (Furnace
#: Reins — `_gain_control_rich_prev_grant` → `grant_until(previous_
#: subject=True)` over `_quoted_ability_grant_effects`), "it becomes a
#: <subtype> in addition to its other types and gains haste" (Loki's
#: Scepter — `type_change` add-subtype), "it has base power and toughness
#: N/N and gains <kws>" (`pt_set` + residual `pump`). `_DAMAGE_TRIGGER_RE`
#: also now accepts "…to a player or battle" (RULE 310, documented
#: simplification). Plus the *opponent-scoped mass* threaten
#: (`_GAIN_CONTROL_MASS_EOT_RE`): "gain control of all <type> [your
#: opponents / target opponent] control[s] until end of turn. untap them.
#: they gain haste …" — `selector="opponents_artifacts"` (Broadcast
#: Takeover) or `GainControlUntilEndOfTurnEffect.mass_of_target_player`
#: (one RULE 115 opponent target, then all their creatures/artifacts).
#: +5 (incl. Beamtown Beatstick / Archpriest of Shadows bycatch).
#: "201": PAR-30 threaten residue — the two card-specific conditional
#: after-tails: "if that creature is a <subtype>, it also gets +N/+M until
#: end of turn" (Goatnap) and "if it's equipped, you may destroy all
#: Equipment attached to that creature" (Awaken the Sleeper), each a
#: `ConditionalEffect` gated on new `previous_target_*` keys
#: (`previous_target_has_subtype` / `_is_equipped` / `_power_at_most`)
#: reading `GameContext.previous_targets`; the destroy runs over a new
#: `equipment_attached_to_previous` mass selector. +2.
#: "202": PAR-30 threaten residue — the *old two-sentence* Oblivion Ring
#: templating: `_return_exiled_card` claims a standalone "return the exiled
#: card[s] to the battlefield under its/their owner's control." LTB line
#: (→ `return_linked_exile`), `_exile` gains an "exile **another** target
#: …" ETB row, and `gate.parse_oracle` stamps `remember=True` onto the
#: companion exile (any card carrying a `return_linked_exile`) so
#: `GameObject.linked_exile_id` is populated. Plus Driftgloom Coyote's
#: "if that creature had power N or less, put a +1/+1 counter on ~."
#: after-tail (`previous_target_power_at_most`). +10 (Oblivion Ring,
#: Journey to Nowhere, Faceless Butcher, Fiend Hunter, Petravark, Petradon,
#: Slithery Stalker, The Princess Takes Flight, Eldrazi Displacer,
#: Driftgloom Coyote).
#: "203": PAR-30 (Threaten / O-Ring trailing items) — RULE 601.2i "When you
#: cast this spell, `<effect>`." recognizer (`_CAST_THIS_SPELL_TRIGGER_RE`
#: in `segmenter`) → `AbilitySpec("triggered", …, trigger={"event":
#: "SPELL_CAST", "condition": {"subject": "self"}})`. The engine side is
#: MEC-43 (`RulesEngine._collect_self_cast_triggers` +
#: `TriggeredAbility.functions_from_stack`, both keyed off exactly that
#: shape) — only the parser recognizer was missing. Body parsed
#: ``self_subject`` so a bare "it" means this spell. +15 (Flayer of
#: Loyalties, the Emerge/Emrakul-brood cycle — Elder Deep-Fiend, Vexing
#: Scuttler, Wretched Gryff …, Artisan of Kozilek, Decimator of the
#: Provinces, World Breaker, Desolation Twin). Also the "enters **or
#: transforms into** ~" compound trigger (Brutal Cathar): new
#: `EventType.TRANSFORMED` (fired by `RulesEngine.transform_permanent`
#: after the flip + rebind), `_SELF_MULTI_EVENT_RE` accepts "transforms
#: into ~" as a verb slot → the existing `event`-list-of-two shape (one
#: `TriggeredAbility` per event, `_SUBJECT_EVENT_KEYS`' default self
#: scoping matches TRANSFORMED's `instance_id`; the face-name gate is
#: implicit — the ability only exists on the object while it's that face).
#: +5 more (Huntmaster of the Fells, Ulrich of the Krallenhorde, Ashling
#: Rekindled, Brigid Clachan's Heart). Also the compound "when ~ enters
#: **and at the beginning of your first main phase**" trigger (Crack in
#: Time — `_ENTERS_AND_MAIN_PHASE_RE`): one self `ENTERS_BATTLEFIELD` spec +
#: one controller-scoped `STEP_BEGIN` (`filter={"step":"main1"}`,
#: `phase_relation="you"`) + the O-Ring companion LEAVES_BATTLEFIELD return.
#: "204": PAR-30 (Threaten / O-Ring trailing items — closed) — the last two
#: singletons. **Call for Aid**: the mass gain-control body's two
#: anti-abuse riders — "you can't sacrifice those creatures this turn"
#: (`GainControlUntilEndOfTurnEffect.mark_no_sacrifice` → `GameObject.cant_
#: be_sacrificed_this_turn`, checked at every sacrifice candidate site,
#: cleared at cleanup) and "you can't attack that player this turn" (new
#: `PreventAttackingPlayerThisTurnEffect` → `GameState.no_attack_pairs_
#: this_turn`, enforced in `GameEngine._can_attack` against the assigned
#: defender). **Shackles of Treachery**: `_DAMAGE_TRIGGER_RE` now accepts a
#: bare "deals damage" (no "to a …" — any damage instance, empty filter),
#: and a new `equipment_attached_to_source` target kind + `_destroy_
#: equipment_attached_to_it` handler cover the granted quoted trigger's
#: "destroy target Equipment attached to it". +2.
#: "205": PAR-30 (Incubate residue — closed) — the plain "incubate N" cards
#: blocked on *unrelated* surrounding grammar. (a) `_counter` gains an
#: optional reflexive "…unless its controller pays {N}. **If they do**,
#: `<effect>`." tail (`CounterSpellEffect.on_pay_effect_specs`, threaded
#: through `RulesEngine.counter_unless_pays` /
#: `_resume_counter_unless_pays`), and "battle" joins the counter-
#: target spell-type list (`_SPELL_TYPE_WORD`, `targeting._spell_matches_
#: filter`) — Assimilate Essence + bonus Don't Make a Sound. (b) new
#: `_IF_PREV_CREATURE_CANT_BLOCK_RE` "if it's a creature, it can't block
#: this turn" — a damage-rider tail gated on the "any target" clause's
#: target being a creature (`CantBlockEffect.previous_subject` +
#: `previous_target_is_creature` `ConditionalEffect` gate) — Searing Barb.
#: (c) new `_CAST_SPELL_TARGETS_PERMANENT_TRIGGER_RE` "whenever you cast a
#: spell that targets one or more permanents" (`SPELL_CAST`'s new
#: ``targets_a_permanent`` flag + ``requires_spell_targets_permanent``
#: predicate) — Tiller of Flesh. +4, 0 regressed. The three remaining
#: singletons (Phyrexian Incubator's "that many times", Progenitor
#: Exarch's "X times", Traumatic Revelation's "if you don't" else-branch)
#: are hand-authored in `card_registry/special_mechanics.py`, not parsed.
#: "206": PAR-30 (Collect Evidence / Forage / Blight residue, sub-cluster a)
#: — reflexive "**When you do**, `<targeted payoff>`." after an optional
#: keyword-action cost (RULE 603.11). `_pay_cost_then_general` no longer
#: rejects a *targeted* follow-up: it emits `pay_cost_then` with a new
#: ``then_trigger`` (the serialized payoff). On payment,
#: `RulesEngine._enqueue_pay_cost_then_trigger` builds a fresh
#: `TriggeredAbility` from those specs and queues it on `pending_triggers`,
#: so the ordinary placement path gathers its RULE 115 target and puts it
#: on the stack — which `effects` (off-stack) never could. Generalises far
#: past Collect Evidence: any "you may pay {cost}/sacrifice/discard/pay
#: life. If you do, `<targeted effect>`" — Surgespanner, Teneb, Bearer of
#: Silence, Sample Collector, Curious Forager, Warren Torchmaster, … +43,
#: 0 regressed.
#: "207": PAR-30 (Collect Evidence / Forage / Blight residue, sub-cluster b)
#: — the exotic `{cost}, collect evidence N: <body>` / `{T}, Blight N:
#: <body>` activated abilities. `segmenter._COST_LOOKS_REAL` gains
#: `collect evidence \d+` / `forage` / `blight \d+` (they're real
#: `costs.parse_activation_cost` fragments but the cost sniff never let the
#: line reach the activated handler). Unblocked bodies: (a)
#: `ExileEffect`'s new ``attached_permanent`` self-mode + `exile_attached`
#: handler ("Exile enchanted creature." — Spiral into Solitude, and a
#: whole Aura family: Dreadful Apathy, Cooped Up, Choking Restraints …);
#: (b) `segmenter._DISCARD_THEN_IF_YOU_DO_RE` collapsing "discard a card.
#: If you do, `<effect>`" (Gristle Glutton's loot); (c)
#: `_EACH_PLAYER_LOSE_LIFE_UNLESS_RE` widened to "each opponent"
#: (`scope="each_opponent"`) and the OR cost form
#: (`EachPlayerPayOrEffect.sacrifice_or_discard` — Polygraph Orb). +13, 0
#: regressed. Hedge Whisperer hand-authored (`GrantUntilEffect.extra_
#: statics` — one target, layer-4 type_change + layer-6 haste). Tenth
#: District Hero (become-legendary-renamed leveler) and Incinerator of the
#: Guilty (dynamic "collect evidence X" + event-player group damage) still
#: need their own primitives — tracked in `BACKLOG.md`.
#: "208": PAR-30 (Collect Evidence / Forage / Blight residue, sub-cluster d)
#: — "As an additional cost to cast this spell, forage [or pay {M}]."
#: (Feed the Cycle). New `_ADDITIONAL_COST_FORAGE_RE` → `additional_cost=
#: {"forage": True}` (`ActivationCost.forage`, already charged by
#: `_can`/`_pay_activation_cost`); the "or pay {M}" alternative is the same
#: documented drop `behold`/`blight` additional costs already make. +1, 0
#: regressed. Conspiracy Unraveler ("you may collect evidence 10 rather
#: than pay the mana cost for spells you cast" — a battlefield permanent
#: granting an alternative cost to *every* spell its controller casts, a
#: cast-path primitive that doesn't exist) stays UNMODELED, tracked in
#: `BACKLOG.md`.
#: "209": MEC-50 — Clash (RULE 701.30) win/otherwise-branch residue, the
#: six primitive-blocked singletons the v147–v154 grammar left. Shared:
#: `GameContext.clashed_opponent` (recorded by `RulesEngine.clash`) as the
#: "that player" referent. New: `RepeatProcessEffect` (Hoarder's Greed,
#: capped loop); `MillEffect.selector="previous_subject_controller"`
#: (Broken Ambitions — the countered spell's owner); `ReturnToHandEffect.
#: to_library_top_if_clash_won` (Whirlpool Whelm — destination override);
#: `GainControlAttachedEffect(recipient)` (Captivating Glance — indefinite
#: control of the Aura's host); `DiscardEffect.previous_subject` (Pulling
#: Teeth — "that player", with a trigger-event fallback that also unlocks
#: the "whenever ~ deals damage to a player, that player discards" family);
#: `SkipNextUntapEffect.subject="clashed_opponent"` (Pollen Lullaby). +34,
#: 0 regressed (the discard family is the bonus). Whole ticket = engine
#: primitives + oracle handlers + version bump, one batch.
#: "210": PAR-30 — Suspect (RULE 701.60) one-off shapes, the four
#: primitive-blocked singletons the PAR-29 keyword trail left. New:
#: `EffectSpec.condition` key ``previous_target_is_suspected`` (Agrus Kos,
#: Spirit of Justice — "if it's suspected, exile it. otherwise, suspect it."
#: as two complementary condition-gated specs, read off the effect's own
#: resolved target); `RemoveSuspectedEffect` gains ``previous_subject`` /
#: ``attached`` / ``optional`` subject shapes (Deadly Complication's "you
#: may have it become no longer suspected." routed through
#: `_request_choose_objects`, action ``"remove_suspected"``); a
#: `subgrammars` target row for "up to one **other** target creature you
#: control" + `_batch_attack_group_filter` / `_any_attacking_matches`
#: ``is_suspected`` (Clandestine Meddler). Airtight Alibi hand-authored
#: (ETB untap + hexproof-EOT + un-suspect on the Aura host; a static +2/+2
#: and a ``cant_become_suspected`` `grant_keyword` slug `RulesEngine.
#: suspect` honours — the only card printing that prohibition). +4, 0
#: regressed.
#: "211": PAR-30 — RULE 701.10 exchange-control residue, the cross-target
#: legality predicates. `ExchangeControlEffect` gains resolve-time
#: ``shares_type`` ("…that share[s] a card/permanent type with it" — Daring
#: Thief, Legerdemain, Role Reversal, Shifting Loyalties) and
#: ``second_not_greater`` (``"mana_value"`` — Puca's Mischief "with equal or
#: lesser mana value"; ``"power"`` — Spawnbroker "with power less than or
#: equal to that creature's power") checks — one more branch on the
#: existing ``exchangeable`` no-op gate, no `legal_targets`/client change
#: (the same documented simplification the different-controllers no-op is).
#: `_exchange_control_two_explicit` / `_exchange_control_multi` regexes gain
#: an optional `_EXCHANGE_XTARGET_TAIL`; new `subgrammars` rows "target
#: nonland permanent you control" and "another/other target permanent";
#: `_EXCHANGE_CONTROL_TARGET_KINDS` widened for the controller-scoped
#: permanent kinds; a dedicated Spawnbroker row (its comparison sits inside
#: the second target phrase). +10 (6 exchange cards + 4 "untap another
#: target permanent" bonus), 0 regressed.
#: "212": PAR-30 — RULE 701.10 exchange-control residue, closed. The
#: twelve remaining bespoke singletons, all hand-authored
#: (`card_registry/special_mechanics.py`) — no new parser recognition, each
#: shape appears on exactly one card. New engine primitives: `TriggeredAbility.
#: controller_from_trigger_event` (RULE 603.1's chooser can differ from the
#: ability's own source's controller — Confusion in the Ranks) +
#: `ExchangeControlEffect(first_target_kind="trigger_subject")` (the entering
#: permanent, read off the firing event, never a RULE 115 target of its own);
#: `permanent_you_neither_own_nor_control` target kind (Conjured Currency);
#: a `nonlegendary` `creature_filter` key + `ActivationCost.not_during_combat`
#: (Djinn of Infinite Deceits); `ExchangeControlEffect.destroy_auras_if_
#: exchanged` (Gauntlets of Chaos) / `.draw_if_neither_controlled` (Modify
#: Memory) — both RULE 701.10c after-effect riders, gated on the exchange
#: attempt's own outcome; `ExchangeLifeTotalsEffect.life_difference_at_most`
#: (Psychic Transfer's pre-effect numeric gate); `TripleExchangeEffect` +
#: `CreateDelayedTriggerEffect`'s new `capture="target_player"` (Mirror
#: Mirror's delayed triple swap — life totals, all permanents, and the three
#: owner-scoped zones); `JuxtaposeEffect` (two greatest-mana-value selection
#: rounds, tie-break simplified to lowest instance id) and
#: `CulturalExchangeEffect` (two chained interactive rounds via a new
#: `_request_choose_objects` action `"gain_control_for"` + payload
#: `control_recipient_id`, "same number" simplified to independent "any
#: number"); `ExchangeControlSpellEffect` (RULE 701.10i — exchanging a
#: permanent for a **spell** still on the stack, Perplexing Chimera's
#: reflexive `self`+that-spell mode and Sudden Substitution's two
#: independent targets) alongside a new reflexive-trigger "you may" pause
#: (`_place_triggers`'s reflexive branch now opens a do/decline choice
#: instead of placing blind when `TriggeredAbility.optional` is set,
#: `RulesEngine._pending_trigger_reflexive_target`); `RulesEngine.
#: enqueue_reflexive_trigger` (refactored out of `_enqueue_pay_cost_then_
#: trigger`, RULE 603.11's "when you do" as a fresh triggered ability with
#: its own real target) + `ExchangeControlThenCopyTokenEffect` (Arteeoh,
#: Dread Scavenger — exchange, then reflexively copy a *third* artifact as
#: a 1/1 green Squirrel, colour addition undocumented/simplified). Also
#: fixed a real `Card.as_copy` bug found by execute-testing Arteeoh: `add_
#: types` naming "creature" never flipped `is_creature`, so a `set_power`/
#: `set_toughness` override on the result tripped `Card.__init__`'s own
#: "power/toughness may only be set on creatures" invariant. The whole
#: **RULE 701.10 exchange-control / exchange-life residue** bullet is now
#: closed (see PARSER_VERSION 211's entry above for the shared cross-target
#: predicates). `tests/test_par30_exchange_control_bespoke.py`.
#: v213 — **Collect Evidence / Forage / Blight activated-body residue**
#: closed (PAR-30). Parser: the Lorwyn "Champion" cycle's mandatory
#: ``behold_exile`` additional cast cost (`segmenter._ADDITIONAL_COST_
#: BEHOLD_EXILE_RE`, `ActivationCost.behold_exile`) + a widened
#: `_RETURN_EXILED_CARD_RE` "to its owner's **hand**" branch
#: (`ReturnLinkedExileEffect(destination=…)`) → Champion of the Clachan
#: and Champions of the Perfect MODELED (the latter's hand-authored
#: stopgap retired); `subject_damages_each_opponent_equal_to_power` (a
#: trigger-subject-sourced "it deals damage equal to its power to each
#: opponent" — Champion of the Path + a 6-card SOLO cluster); a
#: `tap_and_stun` handler ("tap [up to one] target creature and put a
#: stun counter on it" — Champions of the Shoal + a ~15-card cluster,
#: with RULE 122.1c stun-counter skip-untap now enforced engine-side in
#: `RulesEngine.set_tapped`, and `AddCountersEffect.previous_subject`);
#: `_CONDITIONAL_FLASH_IF_BEHOLD_RE` → `conditional_flash={"controller_
#: beholds_subtype": …}` (Molten Exhale); `additional_cost={"behold_two_
#: shared_type": True}` (Celestial Reunion). Engine/hand-authored:
#: Champion of the Weird (`BlightEffect(target_kind="opponent")` — "target
#: opponent blights N"); Tenth District Hero (`type_change` gained a
#: ``legendary`` param, new `source_has_subtype` `EffectSpec.condition`
#: key); Elven Passage (`MayBeholdThenUntapLinkedEffect`); Incinerator of
#: the Guilty (`CollectEvidenceXThenBoardDamageEffect`); Memory Vampire
#: (`MemoryVampireCombatEffect` + a `cast_without_paying` fix: the caster
#: now controls a card cast from another player's graveyard); Conspiracy
#: Unraveler (`granted_alt_cast_cost` static + `continuous.granted_alt_
#: cast_cost_for`, an externally-granted RULE 118.9 alt cost the engine's
#: `alt_cost=True` cast path now scans the battlefield for); Celestial
#: Reunion (`CelestialReunionSearchEffect`). `tests/test_par30_champion_
#: behold_exile.py`, `tests/test_par30_collect_evidence_residue.py`.
#: v214 — **Firebending (RULE ~702.189) grants residue** closed (PAR-30, the
#: last sub-bullet of PAR-29's parser trail): the "whenever you waterbend,
#: earthbend, firebend, or airbend" bending-verb trigger (Avatar Aang).
#: Engine: `EventType.BENT` + `RulesEngine.record_bend` + `GameState.bends_
#: this_turn` (cleared each `begin_turn`), fired from all four bending
#: primitives — `RulesEngine.earthbend`, the waterbend additional-cast-cost
#: payment (RULE 701.67c), `ExileEffect.bend_kind` (airbend — the only
#: parser-visible change: `handlers._airbend`/`_airbend_trigger_subject`
#: now emit `"bend_kind": "airbend"`), and a second `ATTACKS` trigger
#: carrying `effects.RecordBendEffect` on every Firebending creature
#: (`effect_binder._kw_firebending`). `EffectSpec.condition` gained
#: `did_all_bends_this_turn` (the reflexive "then if you've done all four
#: this turn, transform ~"). Avatar Aang is hand-authored (strict
#: singleton, un-parseable reflexive clause). No card's parser verdict
#: changes; +1 covered via hand-authoring. `tests/test_par30_firebending_
#: bending_trail.py`.
#: v215 — PAR-30 **Waterbend (RULE 701.67) residue**, first pass. Three
#: shared parser/engine wins the residue cards (and many others) were
#: blocked on: (1) "Whenever you/an opponent draws their **second** card
#: each turn, …" (`segmenter._DRAW_CARD_TRIGGER_NTH_RE` → the engine's
#: existing `is_nth_draw_this_turn` predicate — Faerie Mastermind's
#: hand-authored shape, now parser-reachable; ~+35, closes The Unagi of
#: Kyoshi Island whose Ward—Waterbend {4} already resolved via the ward
#: text-cost fallback). (2) "[another/other] target permanent you control"
#: → the real `permanent_you_control` target kind, + `_TAP_TARGET_KINDS`
#: (closes North Pole Patrol's "{T}: Untap another target permanent you
#: control"). (3) "up to one **other** target nonland permanent" (a new
#: `_TARGET_ROWS` row — closes Invasion Submersible's ETB). Plus the
#: **waterbend {X}** mandatory additional cost: `_ADDITIONAL_COST_
#: WATERBEND_RE` now matches `{X}` → `{"waterbend": "x"}`, and
#: `legal_actions` surfaces `has_x`/`max_x` off a mandatory variable
#: additional cost (`effective_cast_cost` already folds `mana.with_x(x)`,
#: `x_paid` carries it to the body) — the announcement plumbing Crashing
#: Wave / Foggy Swamp Visions / Waterbender's Restoration need.
#: v216 — PAR-30 **reanimator-token residue**, the graveyard-exile-copy
#: cluster. (1) `non-Aura enchantment card` graveyard target — a new
#: `_GRAVEYARD_TYPE_FILTERS["non_aura_enchantment"]` + its `_GRAVEYARD_
#: TYPE_WORD`/`_graveyard_target_kind` wiring — closes **Anikthea, Hand of
#: Erebos** (the exile→copy segmenter connector + `copy_permanent_previous`
#: already did the rest). (2) `_COPY_EXCEPT_PT_RE` now emits
#: `add_types=["Creature"]` when the "…except it's a N/N `<colour>` `<sub>`
#: **creature** …" clause names the creature type — without it `Card.as_
#: copy` set P/T on a non-creature original (an enchantment card) and
#: tripped `Card.__init__`'s RULE 208.1 invariant. (3) new segmenter span
#: `_EXILE_X_GY_FOR_EACH_CREATE_RE` — "Exile X target creature cards from
#: your graveyard. For each [creature] card exiled this way, `<create>`" —
#: routing the follow-up to `copy_permanent` ``referent="previous_each"``
#: (**Hour of Eternity**) or `create_token` ``count_from_context=
#: "objects_exiled_this_way"`` (**Midnight Ritual**); `CreateTokenEffect`
#: gained that `count_from_context` param (closed whitelist). +3 covered.
#: `tests/test_par30_reanimator_token_residue.py`.
#: v217 — MEC-52 (first sub-item) — **Sauron, the Necromancer**, and a
#: RULE 603.4 intervening-if on delayed triggered abilities.
#: `CreateDelayedTriggerEffect` / `DelayedTrigger` gained a whitelisted
#: ``condition`` dict (`_ALLOWED_CONDITION_KEYS`) re-checked by
#: `_fire_delayed_triggers` when the ability would go on the stack — "…exile
#: that token **unless ~ is your Ring-bearer**". Parser: `_COPY_PERMANENT_
#: PREVIOUS_RE` + the exile→copy connector accept a "tapped and attacking"
#: prefix (`CopyPermanentEffect` already took `tapped`/`attacking`);
#: `_COPY_EXCEPT_PT_RE` accepts a trailing "with `<keyword>`" ("a 3/3 black
#: Wraith with menace" → `extra_temp_keywords`); new when-first
#: `_delayed_sac_exile_when_first` handler ("At the beginning of the next
#: end step, sacrifice/exile `<it>`[ unless ~ is your Ring-bearer]") — the
#: mirror of `_DELAYED_SAC_EXILE_TAIL_RE`, capturing `created_objects`
#: directly for a "that token" subject (not `previous_or_self`, which would
#: bake the earlier graveyard target). +1 covered.
#: `tests/test_mec52_delayed_trigger_condition.py`.
#: v218 — MEC-52 (Davros, Dalek Creator) — `GameState.life_lost_this_turn`,
#: the mirror of `life_gained_this_turn` (bumped at `RulesEngine.lose_life`'s
#: single choke point, reset for every player each `begin_turn`). Feeds a
#: new `ConditionalEffect` key `opponent_lost_life_this_turn_at_least`
#: (segmenter `_OPPONENT_LOST_LIFE_SUFFIX_RE` — the *suffix* "…if an opponent
#: lost N or more life this turn", checked before `match_clause` so the base
#: token clause can't claim it ungated) and
#: `FaceVillainousChoiceEffect.subject_min_life_lost` (`_VILLAINOUS_HEADER_RE`
#: "each opponent **who lost N or more life this turn**"). +1 covered.
#: `tests/test_mec52_davros_life_lost.py`.
#: v219 — MEC-49 (per-turn damage-source attribution). "Whenever a creature
#: **dealt damage by ~ this turn** dies, `<effect>`." (Baron Sengir /
#: Abattoir Ghoul / Blood Cultist / Sengir Vampire family). New
#: `GameState.creatures_damaged_by_source_this_turn` — a per-damaged-object
#: set of source `instance_id`s, recorded by `RulesEngine.deal_damage` for
#: any damage to a creature (combat or not, infect/wither included), reset
#: game-wide each `begin_turn` (the per-source hit-set sibling of
#: `combat_damage_to_players_this_turn`). Segmenter
#: `_DAMAGED_BY_SOURCE_SUBJECT_RE` → a RULE 603.1 group DIES condition with
#: `effect_binder._build_group_ok`'s new `damaged_by_source_this_turn`
#: key (a pure history lookup keyed on this ability's own source, like
#: `crewed_by_self`). +8 covered. `tests/test_mec49_damaged_by_source.py`.
#: v220 — MEC-49 (narrowed) — the *replacement* form. `catalogue/
#: replacements._DIE_TO_EXILE_RE` widened for "if a creature/permanent
#: **dealt damage by ~ this turn** would die[ this turn], exile it/that
#: `<x>` instead" → `die_to_exile` `subject="damaged_by_source_this_turn"`,
#: a new branch in `_die_to_exile_replacement._applies` checking the dying
#: object against `GameState.creatures_damaged_by_source_this_turn` keyed
#: on this ability's source. +4 (Kumano, Master Yamabushi / Kumano's
#: Pupils / Frostwielder / Incendiary Oracle).
#: v221 — MEC-49 body gaps + bycatch. (1) `gain_life_eq_that_group` — "you
#: gain life equal to **that creature's** `<char>`" on a *group* trigger
#: (the wordier sibling of `gain_life_eq_its_group`), + a `toughness=
#: obj.toughness` snapshot on the DIES/LEAVES event and a
#: `_characteristic_of_subject` `trigger_subject` branch that prefers the
#: event's stamped power/toughness (RULE 400.7). (2) the `add_counters`
#: handler accepts "+N/+N" — Baron Sengir's "+2/+2 counter" modeled as N
#: +1/+1 counters (`_counter_kind_and_multiplier`, documented
#: simplification). +8 (Abattoir Ghoul, Baron Sengir, Armor Thrull,
#: Proper Burial, Shield Sphere, Spirit Shackle, Trostani Selesnya's
#: Voice, Experiment Five).
#: v222 — MEC-49 (fully closed) — the Aura-hosted "…dealt damage by
#: **enchanted creature** this turn" variant (Kumano's Blessing).
#: `_DAMAGED_BY_SOURCE_SUBJECT_RE` / `_DIE_TO_EXILE_RE` accept "enchanted
#: creature" as the damage source; `_build_group_ok`'s `via_attached` and
#: `die_to_exile` `subject="damaged_by_attached_this_turn"` resolve it to
#: the Aura's `attached_to`. +1. (Vampiric Embrace still needs a "counter
#: on that creature" body — a dead-on-arrival nonbo, not pursued.)
#: v223 — MEC-48 — the Specialize digital keyword (Alchemy Horizons:
#: Baldur's Gate). `catalogue/keywords.py` gains a `("Specialize", COST)`
#: row (parser recognition of a bare "Specialize {cost}" line);
#: `effect_binder._specialize_activated_ability` binds it to a real
#: sorcery-speed "{cost}, Discard a card" activated ability whose body is
#: `SpecializeEffect` (a persistent `is_specialized` designation +
#: `EventType.SPECIALIZED` — no characteristic swap, the five specialized
#: faces aren't in the card seed); `segmenter._TRIGGER_VERBS` gains
#: "specializes" → `SPECIALIZED`. A "Specialize {cost}. <rider>" line (the
#: cost-reduction / "activate only if" / alternate-zone riders) is held
#: UNMODELED by `_SPECIALIZE_WITH_RIDER_RE` rather than greedily
#: over-claimed. +6 (the bare-cost cards: Gale/Jaheira/Rasaad/Vhal/
#: Viconia/Wilson).
#: v224 — MEC-51 (RULE 720) — "you control target opponent/player during
#: that player's next turn / combat phase" (`catalogue/handlers.py`'s
#: `_CONTROL_PLAYER_RE` → `EffectSpec("control_player", {"scope": …})`).
#: `effects.ControlPlayerEffect` installs a `GameState.TurnControl`;
#: `RulesEngine._advance_turn_controls` runs the `TURN_BEGIN` state machine
#: and `services/game_session.py` routes the controlled seat's decisions,
#: priority and turn-based actions to the controller for the window
#: (`view.acting_as`, hand reveal per RULE 720.2). Cards hand-authored:
#: Mindslaver / Worst Fears / Sorin Markov (−7) / Emrakul, the Promised
#: End / Secret of Bloodbending (combat scope). RULE 720.x carve-outs are a
#: documented simplification.
#: v225 — PAR-40 (RULE 115/601.2c) — "~ deals N damage to target creature
#: with flying / …with power 4 or greater" — the creature-quality target
#: filter `destroy_creature_filter`/`exile_creature_filter` already carried,
#: extended to *damage*. New `damage_creature_filter` handler
#: (`_DAMAGE_CREATURE_FILTER_RE` + `_damage_creature_filter`), registered
#: before the plain `damage` row, reusing `_CREATURE_FILTER_SUFFIX` /
#: `_creature_quality_filter`; `effects.DealDamageEffect` gained a
#: `creature_filter` param threaded into its `TargetSpec`. +19 (Leaf Arrow /
#: Pierce the Sky / Shredding Winds / Collision // Colossus / Centaur Archer
#: / Grapeshot Catapult / Skyway Sniper / Thunderbolt / Tangletrap / …).
#: v226 — PAR-40 (RULE 601.2c) — symmetric mass-damage board wipes: "~
#: deals N damage to each creature and each player" (`each_creature_and_
#: player`) / "… to each creature and each planeswalker"
#: (`each_creature_and_planeswalker`) — two global-scope union selectors
#: `DealDamageEffect` already resolved, added to `_SELECTOR_WORD_MAP` and
#: the `damage_selector` handler's regex alternation (the "and each …"
#: unions first so the bare "each creature" branch can't prefix-match then
#: fail the fullmatch). No engine change. +27 (Cave-In / Fire Tempest /
#: Inferno / Star of Extinction / Storm's Wrath / Pestilence Demon / …).
#: v227 — PAR-40 (RULE 616/701.11) — the "If that creature would die this
#: turn, exile it instead." rider. `segmenter._DIE_TO_EXILE_SENTENCE_RE`
#: splits it off the same way `_NO_REGEN_SENTENCE_RE` handles "It can't be
#: regenerated." — the "before" clause parses on its own, and (only if it
#: announces a creature/permanent target) a `grant_die_to_exile_this_turn`
#: spec with `previous_subject=True` is appended.
#: `GrantDieToExileThisTurnEffect` gained the matching `previous_subject`
#: mode (arms its `WOULD_DIE`->exile replacement on every
#: `GameContext.previous_targets` entry, no RULE 115 target of its own).
#: +12 — Magma Spray / Feed the Flames / Elspeth's Smite / Bleed Dry /
#: Mawloc / Suplex. PAR-40 fully closed.
#: v228 — PAR-43 (RULE 613 layer 7c) — the general "~ gets +P/+T for each
#: <X>" standing self-anthem. `static_handlers._SELF_ANTHEM_FOR_EACH_RE` +
#: `_SELF_ANTHEM_FOR_EACH_SELECTORS` map a whitelist of "for each …"
#: quantities that already have a `continuous.count_selector`
#: (artifacts/creatures/lands/permanents/legendary-creatures/cards-in-hand
#: you control, artifacts-and/or-enchantments, Equipment attached to it,
#: + `<basic land type> you control` → `lands_you_control_of_type_<t>`)
#: onto a self `anthem` with `power_count`/`toughness_count` — the same
#: shape the PAR-30 graveyard-subtype row emits. Any unwired quantity
#: fails closed (an anthem reading an unmodeled count would silently apply
#: +0). +14 — Akiri Line-Slinger / Goblin Gaveleer / the Nim cycle / Earth
#: Servant / Deadeye Plunderers. The Aura form ("enchanted creature gets
#: +P/+T for each …") and the long selector tail stayed open in PAR-43
#: until v379 (below) closed both.
#: v379 — PAR-43 closed: the Aura/Equipment form
#: (`_ATTACHED_ANTHEM_FOR_EACH_RE`, `affects="attached_permanent"` — RULE
#: 613.7c/604.3 already scopes every count to the *affected* creature, so
#: it needed no new engine support) + ~25 new `continuous.count_selector`
#: entries shared by both forms via `_for_each_count_selector` (board-wide
#: Equipment/unscoped Aura/enchantment counts, "other `<X>` you control"
#: self-exclusion incl. per-subtype, opponent-scoped land/untapped/creature/
#: poison counts, a generic "`<kind>` counter on ~" → `source_<kind>_
#: counters` reader, "of its colors", transformed permanents, experience
#: counters, and a few graveyard-filter siblings). +70, zero regressions.
#: v229 — PAR-38 — two self-scoped drawback shapes. (1) "~ deals N damage
#: to **you**" (RULE 109.5): `_SELECTOR_WORD_MAP` + the `damage_selector`
#: regex alternation gain `"you" -> "controller"`, routing to
#: `DealDamageEffect`'s existing `"controller"` selector (Fledgling Djinn /
#: Juzám Djinn / Midnight Reaper / Blade Juggler / Aftershock, +19). (2)
#: "Skip your draw step." — `static_handlers._SKIP_YOUR_STEP_RE` ->
#: `EffectSpec("skip_step", {"step": "draw"})`, the oracle-text route to
#: MEC-38's already-shipped `should_skip_step`/`skipped_steps_for` layer
#: (Symbiotic Deployment / Wild Wasteland / Yawgmoth's Bargain, +3). +22
#: total. PAR-38's upkeep-damage `for each`/`unless you pay` riders stay
#: open.
#: v230 — PAR-42 — the Innistrad "slow land" life cycle: "~ enters tapped
#: unless a player has N or less life." `catalogue/lands.py` gains
#: `_UNLESS_LIFE_RE` → `{"kind": "unless_life", "cmp": "le", "count": N}`;
#: `RulesEngine.enter_land_tapped` + `predict_land_tapped` get the matching
#: deterministic branch (untapped iff *any* living player is at/below the
#: threshold — RULE 614.1 "a player"). +10 (Abandoned Campground / Bleeding
#: Woods / Lakeside Shack / Peculiar Lighthouse / Razortrap Gorge / …, the
#: whole 10-card cycle).
#: v231 — PAR-36 — "Whenever ~ deals damage, you gain that much life." (the
#: pre-lifelink template). `_DAMAGE_TRIGGER_RE` already parsed the
#: condition; only the body was blocked. New `gain_life_from_trigger_
#: amount` handler (`you gain that much life` → `EffectSpec("gain_life",
#: {"amount_from_trigger_event": "amount"})`), and `GainLifeEffect` gains
#: the matching `amount_from_trigger_event` param — the gain sibling of
#: `LoseLifeEffect`/`DealDamageEffect`'s same field, reading the firing
#: DAMAGE event's `amount`. +17 (El-Hajjâj / Exalted Angel / Horned Cheetah
#: / Spirit Link / Vampiric Link / Wall of Hope / …).
#: v232 — PAR-45 — "target opponent loses N life [and you gain N life]" (the
#: Blood Artist / Zulaport Cutthroat drain family). The `lose_life`
#: handler's `who` alternation gains `target opponent` →
#: `EffectSpec("lose_life", {"target_kind": "opponent"})` (the RULE 115
#: opponent-restricted player target, already a valid target kind); the
#: paired "and you gain N life" rides the existing `gain_life` row via the
#: ordinary connector split — no "drain" effect type needed. +34 (A-Blood
#: Artist / Zulaport Chainmage / Bump in the Night / Geralf's Messenger /
#: Vein Ripper / Skymarch Bloodletter / …).
#: v233 — PAR-36 — "…discards a card at random." (RULE 701.8d). New
#: `RulesEngine.discard_random` (uniform pick from hand, no chooser — the
#: random sibling of `discard`/`discard_choice`); `DiscardEffect` gains a
#: `random` param routing every player-resolution branch to it; the
#: `discard` / `that_player_discards` handlers gain an optional "at random"
#: tail. +23 (Hymn to Tourach / Hypnotic Specter / Black Cat / Stupor /
#: Burning Inquiry / Goblin Lore / Bottomless Pit / Gwendlyn Di Corci / …).
#: v234 — PAR-41 — "as an additional cost to cast this spell, exile N
#: [<type>] cards from your graveyard" (RULE 601.2b — Cobbled Lancer /
#: Headless Skaab / Makeshift Mauler / Abhorrent Oculus). `ActivationCost`
#: gains `exile_from_graveyard_filter` alongside the Escape-only
#: `exile_from_graveyard` count; `segmenter._ADDITIONAL_COST_EXILE_
#: GRAVEYARD_RE` + `_additional_cost_dict` emit a single-key
#: `{"exile_from_graveyard": {"count", "type"?}}`; `GameEngine._can_pay_/
#: _pay_additional_cast_cost` gate the cast on the graveyard holding enough
#: matching cards and exile them (auto-picked). The "exile **x** cards"
#: variant stays UNMODELED. +9.
#: v235 — PAR-43 — the single-characteristic CDA: "~'s power is equal to
#: the number of `<X>`" (Ironroot Warlord / Kolaghan Forerunners / Suki,
#: Kyoshi Warrior — printed toughness, live-count power) + the rarer
#: toughness form. `static_handlers._PT_CDA_SINGLE_RE` emits a `pt_cda`
#: spec with only `power_count` (or `toughness_count`); `continuous.
#: recompute`'s 7a pass already applies the two independently, so no
#: engine change. Same `_PT_CDA_SELECTORS` whitelist as `_PT_CDA_RE`. +12.
#: v236 — PAR-33 — "regenerate enchanted/equipped creature" as an Aura's
#: own activated ability (RULE 701.16 / 303 — Regeneration / Gaea's Embrace
#: / Blessing of Leeches / Dark Privilege / Serpent Skin). New
#: `handlers._REGENERATE_ATTACHED_RE` → `EffectSpec("regenerate",
#: {"target_kind": "attached_permanent"})`, routing to `RegenerateEffect`'s
#: pre-existing `attached_permanent` mode (reads `source.attached_to`
#: live). No engine change. +14.
#: v237 — PAR-34 — two static shapes. (1) "Each creature you control with a
#: +1/+1 counter on it has `<keyword>`." (Abzan outlast cycle) —
#: `static_handlers._GROUP_COUNTER_GRANT_RE` → `grant_keyword` scoped to
#: `creatures_you_control` + `has_counter_kind="+1/+1"`; `_SELECTOR_KEYS`
#: gains `has_counter_kind` so `_selectors` threads it into every
#: scope-taking factory (`affected_objects` already filtered on it for
#: MEC-21). (2) The Odyssey-block **Threshold** phrasing: `normalize.
#: _ABILITY_WORD_RE` strips the "Threshold —" label, and
#: `_STATIC_CONDITION_RES` gains the subject-verb "N or more cards are in
#: your graveyard" variant of the existing `control_count` condition. +19.
#: v238 — PAR-42 — RULE 702.43a **Sunburst**: "~ enters with a +1/+1
#: counter on it for each color of mana spent to cast it." (Chamber Sentry
#: / Crystalline Crawler / Woodland Wanderer / Skyrider Elf).
#: `catalogue/counters.py`'s `_SUNBURST_ENTRY_COUNTERS_RE` →
#: `{"colors_spent_scale": True}`; `RulesEngine._apply_entry_counters`
#: multiplies `count` by `len(GameObject.colors_spent_to_cast)` (the
#: frozenset the mana-payment solver already records). +9.
#: v239 — "Players can't gain life." as a standing static (RULE
#: 119.3-adjacent — Forsaken Wastes / Everlasting Torment / Havoc Festival
#: / Leyline of Punishment), plus "Your opponents can't gain life."
#: (Erebos, God of the Dead — `scope="opponents"`) and Sulfuric Vortex /
#: Rain of Gore's replacement-phrased "if a player would gain life, that
#: player gains no life instead". New `prevent_all_life_gain` marker
#: `StaticAbility` (`life_gain_prohibition` layer), consulted by
#: `RulesEngine.gain_life` via `continuous.life_gain_prohibited_for`. The
#: turn-scoped burn-spell rider ("Players can't gain life this turn." —
#: Skullcrack / Call In a Professional) reuses `PreventLifeGainEffect` with
#: a new `recipient="all"`. +7.
#: v240 — PAR-40 — "~ deals N damage to each creature without flying [and
#: each player]." (RULE 601.2c — Earthquake / Fault Line / Tremor / Rolling
#: Temblor ground-sweeper family). New `damage_each_nonflyer` handler +
#: `DealDamageEffect.selector_filter` (a `combat.matches_object_filter`
#: `without_keyword` dict, applied to the `each_creature`/`each_creature_
#: and_player` iteration only — players in a union selector are never
#: filtered). Digit or {X} amount. +19.
#: v241 — "Spells your opponents cast that target ~ cost {N} more to cast."
#: (RULE 601.2f — Icefall Regent / Boreal Elemental / Sphinx of New Prahv).
#: `static_handlers._SPELL_COST_TAX_OPPONENTS_TARGET_RE` → `cost_reduction`
#: with a new `targets_source` param; `continuous.cost_reduction_for` gains
#: a `targets` arg and skips the tax unless the caster's chosen targets
#: include this static's own source (`_adjust_cost` threads it through). +4.
#: v242 — RULE 702.34a's un-keyworded **Heroic** template: "Whenever you
#: cast a spell that targets ~, `<effect>`." (the whole Theros + GRN + LOTR
#: Heroic cycle — Akroan Skyguard / Battlewise Hoplite / Hero of Iroas /
#: Wingsteed Rider / Fabled Hero / Phalanx Leader / Tenth District
#: Legionnaire). `segmenter._CAST_SPELL_TARGETS_SOURCE_TRIGGER_RE` → a
#: `SPELL_CAST` trigger with `requires_spell_targets_source`;
#: `casting_mixin` stamps `target_instance_ids` (a frozenset) on the
#: SPELL_CAST event, and `effect_binder`'s new predicate checks the bound
#: ability's own object is among them. **+37** (coverage crossed 40.0%).
#: v243 — the **Phantom** cycle (Phantom Centaur / Flock / Nantuko /
#: Nishoba / Nomad / Tiger / Wurm): "If damage would be dealt to ~, prevent
#: that damage. Remove a +1/+1 counter from ~." `replacements._PHANTOM_
#: PREVENT_RE` → `prevent_damage` with the new `remove_self_counter`
#: ``rider`` kind (`RulesEngine.apply_prevent_rider` — a fixed count of 1,
#: unscaled by the prevented amount; the 0/0 base + RULE 704.5g SBA
#: finishes them once the last counter goes). +7.
#: v264 — bug report (2026-09-04): "Enchant `<quality>`" now also captures
#: a printed controller qualifier ("... you control" / "... you don't
#: control" / "... an opponent controls", RULE 303.4c) as `keyword.
#: controller` (normalized to "you"/"not_you") instead of discarding it —
#: `targeting.legal_targets`/`RulesEngine._attachment_legal`'s enchant
#: dispatch both now enforce it, closing a real targeting-legality gap
#: (Betrayal's "an opponent controls" restriction let a bot enchant its
#: own creature). No coverage-count change (a keyword's own MODELED/
#: UNMODELED classification is unaffected either way) — the parser's own
#: output shape changed, which is what this lock guards.
#: v265 — PAR-54: ``Choose N. You may choose the same mode more than once.``
#: (the Confluence cycle) is a modal header variant. It sets a ``repeatable``
#: modes flag so the engine offers combinations with replacement rather than
#: the ordinary distinct-mode combinations.
#: v266 — PAR-55: ``Choose N. If <condition>, choose <more> instead.``
#: now emits a closed modal-override IR for kicker/additional-cost, cast-time
#: subtype/commander, delirium, life-total and descend conditions.  Triggered
#: modal headers use the same IR, evaluated at their choice point.
#: v278 — PAR-60 (Secrets of Strixhaven): RULE 702.153 **Magecraft** folds
#: into `segmenter._CAST_SPELL_TRIGGER_RE` via an optional ``(?:or copy )?``
#: — "Magecraft — Whenever you cast or copy an instant or sorcery spell, …"
#: (the ability-word label is already peeled by
#: `normalize._strip_unregistered_keyword_labels`, making the old
#: `_MAGECRAFT_RE` whole-line recognizer unreachable). Only the "cast" half
#: binds (no spell-copy event bus yet). +Archmage Emeritus and the
#: spellslinger "cast or copy" tail.
#: v279 — PAR-60 wave 3: "whenever enchanted/equipped creature **attacks or
#: blocks**, …" (`segmenter._ATTACHED_MULTI_EVENT_RE`) — the two-verb
#: sibling of `_SELF_MULTI_EVENT_RE` for the Aura/Curse cycles: a
#: list-valued `event` on a `{"subject": "attached_permanent"}` condition.
#: +Luminous Wake / Ferocity and the "attacks or blocks, its controller
#: loses N life" tail whose bodies already parse. Engine-side,
#: `LoseLifeEffect.selector="attached_permanent_controller"` was added for
#: the hand-authored Parasitic Impetus.
#: v280 — PAR-60 wave 4: "when ~ dies, [you gain life and] draw cards equal
#: to its power/toughness" (Lifeblood Hydra) and "create a number of tapped
#: Treasure tokens equal to its power" (Goldvein Hydra). New
#: `DrawCardEffect.amount_from_subject` / `CreateTokenEffect.count_from_
#: subject`, both routed through `_characteristic_of_subject` so a DIES
#: trigger reads the RULE 400.7 power/toughness snapshot. +Lifeblood/
#: Goldvein Hydra, Doom Weaver, Gregor.
#: v281 — PAR-60 wave 5 / MEC-77: RULE 508.1g **attack tax** — "Creatures
#: can't attack you unless their controller pays {N} for each creature they
#: control that's attacking you" (Propaganda / Ghostly Prison / Windborn
#: Muse). New `EffectRegistry` ``"attack_tax"`` marker static +
#: `continuous.attack_tax_per_creature_for`, auto-paid in
#: `combat_mixin.declare_attackers`. The {X}-scaled variants (Collective
#: Restraint / Sphere of Safety) stay unclaimed. +3 cache.
#: v288 — MEC-77: RULE 508.1g attack-tax fidelity. The `attack_tax` marker
#: now reads fixed or `{X}` amounts (Sphere of Safety / Collective
#: Restraint), with a count selector and the explicit player-or-planeswalker
#: defender scope Sphere prints. The declaration protocol admits an explicit
#: decline, leaving attackers undeclared and mana unspent.
#: v282 — PAR-60 wave 6: **"target nonbasic land"** target kind
#: (`subgrammars._TARGET_ROWS` + `_SINGLE_TYPE_PERMANENT_KINDS`) — the
#: engine's `targeting.legal_targets` already had a `nonbasic_land` branch;
#: only the parser mapping was missing. New `nonbasic_land_you_dont_control`
#: sibling for the "an opponent controls" form. Plus the "…put it onto the
#: battlefield **tapped**, then shuffle" tail on the Ghost-Quarter
#: controller-searches-basic-land follow-up. +~16 cache (Fulminator Mage /
#: Dust Bowl / Wasteland / Ravenous Baboons / White Orchid Phantom …).
#: v283 — PAR-60 wave 7: RULE 603.3f "1 or more [other] [nontoken] creatures
#: [you control] die" batch-death trigger (`segmenter._BATCH_DIES_TRIGGER_
#: RE`) — modeled as a per-object `DIES` group trigger, **claimed only when
#: the body carries "This ability triggers only once each turn."** so the
#: per-object firing collapses to the correct once-per-turn net. +Morbid
#: Opportunist / Sengir Connoisseur / Vraan / Dramatic Finale / Ghoulish
#: Procession / Homicide Investigator. The un-limited variants (Great Fierce
#: Bee, Vengeful Townsfolk) need a real batch aggregate — stay unclaimed.
#: v284 — PAR-60 wave 8: "a creature **token** you control deals combat
#: damage to a player" — a `(?P<token> token)?` slot on
#: `segmenter._DAMAGE_TRIGGER_RE` -> `condition["is_token"]`, bound by a new
#: positive `want_token` filter in `effect_binder._build_group_ok` (mirror
#: of `want_nontoken`; re-derives the source's token status from the still-
#: live acting object, since the DAMAGE event carries none). +Curiosity
#: Crafter.
#: v285 — PAR-60 wave 9: "**double the number of [+1/+1] counters on**
#: <~ / target creature [you control] / each creature you control / it>"
#: (`handlers._DOUBLE_COUNTERS_RE` → the existing `double_counters_on_
#: target` effect, extended with `mode` (self / target / each_you_control /
#: previous_subject) and an optional `kind` filter). ~27 SOLO: +Primordial
#: Hydra, Kalonian Hydra, Dragonsguard Elite, Growth Curve, Bristly Bill,
#: Invigorating Surge …
#: v286 — PAR-60 wave 10: "**target/each player creates a <named> token**"
#: (`CreateTokenEffect.creators="target"` + a player `target_kind`; existing
#: `each_opponent`/`each_player`) and "**target player draws N cards, then
#: discards M cards**" (`_TARGET_PLAYER_LOOT_RE` — emits the `previous_
#: subject` discard link the bare connector split cannot). Unblocks Prismari
#: Command's last two modal modes.
#: v287 — PAR-60 wave 11: "**target creature [you control] has base power and
#: toughness N/N until end of turn**" — `handlers._BASE_PT_UNTIL_EOT_RE`
#: widened from the ~/creatures-you-control subjects to a RULE 115 target
#: (`grant_until` already resolves the target and scopes the parked layer-7b
#: `pt_set` to those ids). ~59 SOLO: +Quandrix Charm, Creeperhulk-adjacent,
#: Chef's Kiss-adjacent … the compound "loses all abilities and becomes …
#: with base P/T" forms (Turn to Frog, Snakeform, Ovinize) stay open.
#: v289 — PAR-60 wave 13: two small parser widenings. (a) "**[then] you scry
#: N**" as an effect body — `handlers.scry_or_surveil`'s regex gained an
#: optional leading `you ` so a trigger body that spells out the (redundant)
#: subject folds to the same self `scry`/`surveil` EffectSpec (Psychic
#: Impetus, Clockwork Droid). (b) "**<subtype> spells you cast cost {N}
#: less/more to cast**" — `static_handlers`'s `_SPELL_COST_TAX_YOU_CAST_RE`
#: handler routes a single curated creature/Aura/Equipment/Arcane subtype
#: word to ``spell_subtype`` (already resolved by `continuous.cost_reduction_
#: for` via `has_subtype`), fail-closed on groupings ("historic"/"commander").
#: ~17 SOLO — the Banneret/Warchief tribal-discount cycle + Transcendent
#: Envoy [Silverquill deck].
#: v290 — PAR-60 wave 14: "**whenever you cast a <colour> spell, …**" —
#: `segmenter._CAST_SPELL_TRIGGER_RE`'s dispatch gained a colour branch
#: (`_CAST_SPELL_COLOR_WORDS` → `effect_binder`'s existing `cast_of_color`
#: trigger key, the Runaway Steam-Kin predicate). ~11 SOLO + Balefire Liege
#: [Lorehold deck] (Cinder Pyromancer, Emberstrike Duo, …). "colorless"
#: deliberately excluded (membership test, not empty-identity).
#: v291 — PAR-60 wave 15: "**<subject> gets +x/+x [and gains <kw>] until end
#: of turn**" — new `handlers._pump_x` (tried ahead of the digits-only
#: `pump` row) emits the `"x"` power/toughness sentinel that
#: `RulesEngine._substitute_x` already rewrites to `GameObject.x_paid`.
#: Symmetric bare form only — a "where X is <board count>" tail stays
#: fail-closed (a different, `amount_from_count_selector` family). ~6 SOLO:
#: +Tyvar's Stand and Primal Might [Quandrix deck], Untamed Might.
#: v292 — PAR-60 wave 16: "**this spell costs {N} less to cast for each
#: <type> card in your graveyard**" — new `static_handlers._SELF_COST_
#: REDUCTION_GY_RE` emits `affects="self"` + a `per` graveyard-count
#: selector `continuous.count_selector` already resolves (+ a new
#: `instant_or_sorcery_cards_in_your_graveyard` for the one compound).
#: Single-type / "instant and sorcery" only — "cave", "artifact and/or
#: creature", "…in exile and in your graveyard" stay fail-closed. ~7 SOLO
#: (Ghoultree, Molderhulk, Cryptic Serpent, Tolarian Terror, Ore-Scale
#: Guardian, …); narrows Furygale Flocking [Prismari deck] to one clause.
#: v293 — PAR-60 wave 17: '**create a … creature token with "when ~ dies,
#: you gain N life."**' — the STX Pest token's own printed death trigger.
#: The inline-create-token regex gained a quoted-ability tail alternative;
#: `CreateTokenEffect.token_dies_gain_life` binds a `dies`→`gain_life`
#: `TriggeredAbility` onto each token (the triggered-ability sibling of
#: ``grant_self_anthem``). ~5 SOLO (Hunt for Specimens, Professor of
#: Zoomancy, …); narrows Blight Mound / Feral Appetite / Pest Rescuer
#: [Witherbloom deck] to their remaining clauses.
#: v294 — PAR-60 wave 18: a phase trigger's leading RULE 603.4 intervening-if
#: "**if you control no <subtype>[s]** / **if you don't control a <subtype>
#: [creature] token**, …" (`segmenter._YOU_CONTROL_NO_SUBTYPE_IF_RE`,
#: curated `_CONTROL_NO_SUBTYPE_WORDS`) → the trigger's `active_if` as
#: `control_count` `max=0` over `creatures_you_control_of_type_<subtype>`.
#: The "…token" qualifier is a documented simplification. +Ophiomancer and
#: Pest Rescuer [Witherbloom deck]; unwhitelisted words fall through
#: unchanged (Butterbur's "no Food" still routes to its own handler).
#: v296 — MEC-78: RULE 603.3f `CARDS_LEFT_GRAVEYARD` batch event plus the
#: "one or more cards leave your graveyard" trigger grammar (Quintorius,
#: Field Historian). The common zone-removal choke point emits one snapshot
#: per exit or one aggregate for an explicitly simultaneous mass return.
#: v295 — PAR-60 wave 19: "**Attacking <subtype> you control get/have …**"
#: (Blight Mound, Dire Fleet Neckbreaker, Elderfang Venom, Crossway
#: Troublemakers). `static_handlers._scope` strips a leading "attacking"
#: into a new `_Scope.attacking` flag; `_scope_params` folds it into an
#: `attacking_creatures_you_control[_of_type_<subtype>]` `affects` selector,
#: with new matching branches in `continuous`'s anthem resolver (the
#: combat-state sibling of `creatures_you_control_of_type_<subtype>`).
#: +Blight Mound [Witherbloom deck]; narrows Feral Appetite to one clause.
#: v297 — PAR-60 wave 20: "**<creature> deals damage to itself equal to its
#: power**" (Justice Strike / Inner Struggle / Wrack with Madness on a
#: target; Wave of Reckoning / Solar Blaze as an "each creature" mass form).
#: `DamageEqualToPowerEffect` gained a `to_self` flag — the dealer is also
#: the recipient, so no second target, and the "each creature" form has no
#: dealer target at all (every creature reads its *own* power). 9 SOLO
#: cache-wide; +Wave of Reckoning [Lorehold deck].
#: v298 — PAR-60 wave 21: "**you and target opponent each draw N cards**"
#: (Secret Rendezvous, Sky Crier, Loran of the Third Path, Farsight Adept,
#: Flumph, Love Song of Night and Day). A `handlers.py` row emitting two
#: `draw` `EffectSpec`s — one untargeted (the source's controller) and one
#: `target_kind="opponent"` — resolved in that order. 6 SOLO cache-wide;
#: +Secret Rendezvous [Silverquill + Lorehold decks].
#: v299 — ENG-37: `AbilitySpec.validate()` now recurses into **nested**
#: effect specs. `_clamp_params` and `_validate_condition` previously ran
#: only over `self.effects` (depth 0), so `MAX_EFFECT_MAGNITUDE` and the
#: `condition` whitelist were unenforced inside every nested spec list
#: (`then_specs`, `on_pay_effect_specs`, a modal option's own effects, …).
#: Recognition is structural rather than name-keyed, plus a
#: `MAX_SPEC_DEPTH` fail-closed cap. **No parse-behaviour change measured**
#: — no shipped spec nests an out-of-range amount or an unwhitelisted
#: nested condition — but the gate can now reject a spec it used to accept,
#: which is a verdict-affecting change by definition, so the version moves.
#: v300 — ENG-36: the fifteen hand-written condition prefix/suffix peelers in
#: `parse_effect_body` became one rule over `_CONDITION_PREFIXES` /
#: `_CONDITION_SUFFIXES`, and the conditions they emit are now the
#: **structured** `game/effect_conditions.py` vocabulary
#: (``{"kind": "kicked", "min": 1}``) instead of the flat legacy keys
#: (``{"kicked": True}``). **No verdict change**: an A/B of both checkouts
#: over all 38,123 raw-store cards found 0 coverage differences and 0 spec
#: differences beyond the respelling itself (159 cards), each verified equal
#: to what `condition_from_legacy` produces from the old flat form. The
#: version still moves because the emitted spec content differs, which is
#: what this hash exists to notice.
#: v301 — ENG-37: `AbilitySpec` validation now checks the ``condition`` a
#: composition node (`seq`/`if_else`/`optional`/`for_each`/`bind`) carries in
#: its ``params`` — a node *branches* on its gate rather than being gated by
#: it, so the condition does not sit on the spec where `_validate_condition`
#: was already looking. Scoped to those five types, because ``condition`` is
#: not one vocabulary across all params (a `combat_restriction` static's is a
#: combat-time check of its own). **No parse-behaviour change**: this package
#: emits no composition node yet, so no card's verdict can move — but the
#: gate can reject a spec it used to accept, which is the same reasoning that
#: moved the version at v299.
#: v309 — MEC-78: RULE 701.69a Heal. New ``heal`` effect handler
#: (`handlers._HEAL_RE` — "heal all damage from ~ / each creature you
#: control") and a replacement recognizer (`replacements._HEAL_OTHERS_ON_
#: DAMAGE_RE` — Wolverine, Fierce Fighter's "if damage would be dealt to ~,
#: instead that damage is dealt, but all other damage already dealt to him
#: is healed"). `_FIGHT_PRONOUN_RE` widened to accept a personified
#: legendary's "he/she/they fights" (Wolverine, Abomination — the only two
#: cards; neither can mean a player). +1 (Wolverine, Fierce Fighter, now
#: fully MODELED).
#: v308 — MEC-77: RULE 701.42a Meld. New ``meld`` effect handler
#: (`handlers._MELD_BODY_RE` — a meld card's `{cost}:` activated-ability
#: body) and a phase-trigger whole-line recognizer
#: (`segmenter._MELD_TRIGGER_RE` — "at the beginning of <phase>, if you both
#: own and control ~ and a creature named X, exile them, then meld them into
#: Y"), routing to `RulesEngine.meld` / `MeldEffect`. +3 (Gisela, the Broken
#: Blade; Graf Rats; Hanweir Battlements).
#: v307 — MEC-76: RULE 701.29a Fateseal. New ``fateseal`` effect handler
#: (`handlers._fateseal` — "fateseal N" / "you fateseal N"), routing to the
#: new `RollDie`-adjacent `FateSealEffect` / `RulesEngine.fateseal` (scry on
#: an opponent's library, `_look_at_top` now threads a `library_owner`
#: distinct from the chooser). +2 real cards (Spin into Myth, Mesmeric
#: Sliver's quoted grant).
#: v306 — MEC-75: RULE 706 rolling a die. New ``roll_die`` effect handler
#: (`handlers._roll_die` — bare "roll a d20." / "roll a six-sided die." /
#: "roll two d6."), a RULE 706.3a results-table block handler
#: (`gate._split_dice_table_block` — "roll a d20." + "<range> | <effect>"
#: rows, bare or trigger-wrapped, e.g. Contact Other Plane), a
#: "whenever you roll one or more dice" trigger condition → `DICE_ROLLED`
#: (`segmenter._PLAYER_TRIGGER_CONDITIONS`), and the advantage/disadvantage
#: replacement line "if you would roll one or more dice, instead roll that
#: many dice plus one and ignore the lowest/highest roll"
#: (`replacements._ROLL_DICE_MODIFIER_RE` → ``roll_dice_modifier``).
#: v315 - ENG-37 B5: `handlers._reveal_top_conditional` (Goblin Guide's
#: "defending player reveals the top card ... if it's a land card, puts it
#: into their hand") now emits a `seq` of `reveal_top` + an `if_else` on
#: ``{"kind": "is_card_type", "of": "revealed"}`` instead of the retired
#: `reveal_top_conditional_to_hand` fused effect. **No verdict change** -
#: same one card, different spec shape; the version moves because the
#: emitted spec content differs, which is what this hash exists to notice.
#: v316 - ENG-37 B5: `game/effect_conditions.py` gained an `any` combinator
#: (OR) and an `amount_compare` predicate (two `effect_amounts` measurements
#: + an op), and `spec.py` learned to shape-check an `amount_compare`'s
#: `left`/`right` amount specs (`_validate_amount_spec`). No card's verdict
#: moves - this only widens the accepted structured-condition vocabulary -
#: but the parser source hash does, so the version follows.
#: v317 - ENG-37 B5: `effect_amounts` gained a `trigger_event` kind (read a
#: numeric field off `GameContext.trigger_event`, e.g. Counterbalance's
#: "same mana value as the revealed card" vs the SPELL_CAST event), and
#: `spec.py`'s `_AMOUNT_SPEC_FIELDS` learned its `field` key. Vocabulary
#: only - no card's verdict moves - but the parser source hash follows.
#: v355 - PAR-33: attacking-or-blocking targets support exile effects.
#: v356 - PAR-33: Dragon Throne of Tarkir's quoted activated ability grants
#: trample/+X/+X to other creatures, with X read from the host's live power.
#: v357 - PAR-33: combat-qualified creature targets support power-equal
#: damage from quoted activated abilities (Sinstriker's Will).
#: v358 - PAR-33: Kaldra Compleat's quoted combat-damage trigger exiles the
#: damage recipient, including the DAMAGE-event referent resolution.
#: v359 - PAR-33: The Reaver Cleaver's quoted player-or-planeswalker combat
#: damage trigger creates Treasure tokens equal to the damage dealt.
#: v360 - PAR-33: Leyline Immersion's quoted mana grant preserves its
#: any-combination production and spend-only-to-cast-spells restriction.
#: v361 - PAR-33: Glowcap Lantern's attached top-library permission combines
#: with its separately quoted explore-on-attack grant.
#: v363 - PAR-34: generic recursively quoted group/state abilities now cover
#: Sliver grants and Threshold bodies, including owner-relative DIES triggers.
#: v362 - PAR-33: Unquenchable Fury's quoted attack trigger reads the
#: defending player's live hand size for its damage amount.
#: v354 - PAR-33: attacking-or-blocking creature targets work across effects.
#: v353 - PAR-33: quoted grants support counter-scaled combat damage.
#: v352 - PAR-33: quoted grants can follow attached-permanent keywords.
#: v351 - PAR-33: quoted anthem grants can combine a keyword and trigger.
#: v350 - PAR-33: quoted anthem grants can also add a subtype.
#: v349 - PAR-33: quoted grants can untap all lands their controller controls.
#: v348 - PAR-33: quoted attack-alone pumps can count nonland permanents.
#: v347 - PAR-33: quoted grants can add a subtype alongside a spell-cast trigger.
#: v346 - PAR-33: quoted grants can target a Werewolf creature.
#: v345 - PAR-33: quoted cumulative upkeep grants synthesize a live upkeep trigger.
#: v344 - PAR-33: quoted sacrifice grants can use sacrificed toughness.
#: v343 - PAR-33: quoted grants can create X hasty tokens from the host's power.
#: v342 - PAR-33: quoted attack grants can target a defending player's creature.
#: v341 - PAR-33: an attached object can grant two separately quoted abilities.
#: v340 - PAR-33: quoted grants can create hasty self-copy tokens and exile them.
#: v339 - PAR-33: quoted grants now admit unscoped each-upkeep triggers.
#: v338 - PAR-33: quoted damage abilities can tap a colorless damaged target
#: (Pathway Arrows).
#: v337 - PAR-33: quoted damage abilities can have a source-subtype amount
#: override (Sorcerer's Wand).
#: v336 - PAR-33: named Blood tokens are complete token objects and can be
#: created from quoted abilities (Ceremonial Knife).
#: v335 - PAR-33: quoted land abilities can target-pump for each creature
#: their controller has (Friendly Neighborhood).
#: v334 - PAR-33: quoted land abilities can grant their controller a
#: one-shot damage shield (Security Blockade).
#: v333 - PAR-33: quoted land abilities can untap their host during other
#: players' untap steps (Urban Burgeoning).
#: v332 - PAR-33: quoted attack triggers can target another attacking
#: creature (Iconic Shield).
#: v331 - PAR-33: quoted triggered abilities can observe their grantee
#: becoming a spell target (Livewire Lash).
#: v330 - PAR-33: quoted self-scoped static abilities are regranted to their
#: host (Giant's Amulet).
#: v329 - PAR-33: quoted triggered abilities can fire when their grantee
#: attacks alone (Voltaic Whip).
#: v328 - PAR-33: quoted abilities can prevent combat damage to their
#: grantee (Blinding Powder).
#: v327 - PAR-33: quoted activated damage abilities can target the creature
#: blocking their grantee (Arc Spitter).
#: v326 - PAR-33: quoted activated abilities can destroy target Equipment;
#: the target is constrained through the existing Equipment subtype target
#: predicate (Manriki-Gusari).
#: v325 - PAR-33: `UNTAPPED` joins the identity-scoped events that a quoted
#: Aura/Equipment ability can safely regrant (Well Rested).
#: v324 - PAR-33: the pre-keyword fight wording (Predatory Urge's two
#: simultaneous power-damage sentences) emits one atomic `fight` effect.
#: v323 - PAR-33: `sacrifice_unless_attacked` recognizes Instill Furor's
#: objective end-step rider against GameObject.attacked_this_turn.
#: v322 - PAR-33: `sacrifice_unless_pay` recognizes "pay its mana cost" as
#: a live cost of the affected permanent (Pendrell Flux's quoted Aura grant),
#: never the granting Aura's cost.
#: v321 - PAR-33: `handlers.sacrifice_controller` recognizes an ability
#: controller's untargeted "sacrifice a <permanent>" effect body (including
#: Inevitable End's quoted Aura grant) over `SacrificeEffect`'s new
#: controller selector.
#: v320 - PAR-33: `handlers.copy_your_instant_or_sorcery` recognizes Dual
#: Casting's quoted activated ability, including the `spell_you_control`
#: target-legality restriction on the existing `copy_spell` effect.
#: v319 - PAR-33: `handlers.tap_or_untap` recognizes the real one-target,
#: resolution-choice clause "[you may] tap or untap target permanent".  It
#: emits the existing `TapEffect.choose_tap_or_untap` primitive, so quoted
#: Aura/Equipment grants (Ghostly Touch) recurse through the ordinary grant
#: path instead of fail-closing at their inner triggered ability.
#: v318 - ENG-37 B7: `effect_amounts`' `resource` kind gained an `aggregate`
#: ("max"/"min"/"sum" over a `scope`-worth of players) so a `bind` can
#: measure "the greatest number of cards a player discarded this way"
#: (Windfall), and `spec.py`'s `_AMOUNT_SPEC_FIELDS` learned the `aggregate`
#: key. Vocabulary only - no parser handler emits it yet, no card's verdict
#: moves - but the parser source hash follows.
#: v380 — PAR-47 closed: the charge-counter add/spend cluster's residual
#: gaps. `handlers._add_named_counter` (RULE 122.1's named counters) now
#: accepts `COUNT_X` instead of the plain `COUNT`, so an {X}-cost
#: activated ability's own "put X charge counters on ~" (Blast Zone,
#: Ventifact Bottle) is recognized the same way `+1/+1`/`-1/-1` counters
#: already are. `handlers._pump_x` gains the "-x/-x" polarity alongside
#: its existing "+x/+x" — Infused Arrows' "remove X charge counters from
#: ~: target creature gets -X/-X" spend clause, plus the wider {X}-cost
#: removal family it shares no counter connection with at all (Death
#: Wind, Chill Haunting, Slice from the Shadows, Bane of the Living,
#: Necropolis Fiend, Retribution of the Ancients, Skullmane Baku, Taigam,
#: Sidisi's Hand). `handlers._gain_life` now accepts "x" alongside a
#: literal digit ("you gain X life" — Sphinx's Revelation, Death Grasp,
#: Alquist Proft, Overrule, Stream of Life, Swallowing Plague, Vigil for
#: the Lost, Energy Bolt, Oracle of Nectars, Who//What//When//Where//Why),
#: unblocking Battle at the Bridge's own trailing sentence too. Also
#: PAR-51 closed: `Storied` (RULE 702.195, +the Hobbit-Dwarves cluster —
#: Balin/Bifur/Bombur/Dáin/Fíli/Kíli/Ori/Thorin/Óin) recognized as a flag
#: keyword (`keywords.py`) plus its "as long as you have an enduring
#: story" condition (`static_conditions.has_enduring_story`,
#: `Player.has_enduring_story`, `RulesEngine._sba_check_storied`/
#: `get_enduring_story` — the exact Ascend/city's-blessing shape, RULE
#: 702.131). `normalize._fold_given_name_prefix` widened to fold a
#: comma-less legendary's given name before " the " (Kaalia-of-the-Vast's
#: existing " of " sibling), now matched case-sensitively so a common word
#: sharing a name's spelling ("turn" in "until end of turn" for "Turn the
#: Tide", "start" in "Jump-start" for "Start the TARDIS") is never folded
#: — a real self-reference is always printed capitalized. +35, zero
#: regressions (verified via `parser_probe.py diff`).
#: v381 — PAR-53 closed: Party (RULE 700.8/702.129, Zendikar Rising).
#: `continuous.count_selector`'s `"creatures_in_your_party"` branch (the
#: RULE 700.8 bipartite Cleric/Rogue/Warrior/Wizard matcher) existed but
#: was never wired to a parser row — new `_SELF_COST_REDUCTION_PARTY_RE`
#: ("this spell costs `<N>` less to cast for each creature in your
#: party") and `"you have a full party"` → the ordinary `control_count`
#: predicate at `min=4` (no new condition kind: "full" is exactly the cap
#: `creatures_in_your_party` can ever return). Also PAR-56 closed:
#: Teamwork (RULE 702.194) rider grammar beyond the already-shipped modal
#: "choose both instead" override — found and fixed a **dormant bug** in
#: that earlier work: `"teamwork_paid"` was never added to
#: `static_conditions.SUBJECT_FLAGS`, so every "if this spell was cast
#: using teamwork, `<rider>`" card already counted as `MODELED` while its
#: rider silently never fired (`condition_holds`'s fail-closed "flag" gate
#: read as `False` forever) — caught only by an execute-level test, not
#: coverage measurement. Also widened `static_condition`'s shared
#: vocabulary with "this/it was cast using teamwork" so the **generic**
#: trailing "`<effect>`, if/unless `<cond>`" gates recognize it too (a
#: different grammatical shape than the pre-existing leading-prefix row),
#: closing Timeline Inquiry. Also PAR-65 closed: parametric-keyword static
#: grants, starting with Ward `<cost>` (RULE 702.21b) — `continuous.py`'s
#: grant loop already applied `ward_cost` generically to *any*
#: `affected_objects` result; the real gap was every keyword-list regex in
#: this family (`_ATTACHED_ANTHEM_RE`/`_ATTACHED_GRANT_RE`/`_ANTHEM_RE`/
#: `_GRANT_RE`/`_MULTI_PERMANENT_TYPE_GRANT_RE`) using a bare-word
#: character class that couldn't even capture "ward {2}"'s braces/digits,
#: and `_flag_keywords` itself fails closed on any parametric keyword by
#: design. New `_flag_keywords_and_ward` sibling peels "ward `<cost>`" out
#: of a keyword list first (so a list mixing Ward with an ordinary flag
#: keyword still works) and hands the rest to the unmodified
#: `_flag_keywords`. Also PAR-66 closed: "counters removed this way" as a
#: resolve-time amount — new `GameContext.counters_removed_this_way`
#: accumulator (`objects_exiled_this_way`'s counter-removal sibling,
#: bumped by `RemoveCountersEffect`), a new `RemoveCountersEffect.
#: self_only`/`kind` shape ("remove all `<kind>` counters from ~" — no
#: RULE 115 target, one named counter kind so a permanent's *other*
#: counter kinds survive), and two new `AddManaEffect` params
#: (`amount_from_context`, the fixed-colour sibling of the existing
#: `any_amount_from_context` — itself previously reachable only from
#: hand-authored Culling Ritual, now reachable from oracle text too) plus
#: `GainLifeEffect.count_selector="counters_removed_this_way"`. +65 total
#: across this batch, zero regressed.
#: v382 — PAR-68's only genuine parser-classification change: "teamwork"
#: joins `normalize._ABILITY_WORD_RE` (RULE 702.194c's "Teamwork —
#: `<ability>`." label, same reasoning as every other ability-word row —
#: the label carries no rules meaning of its own, RULE 207.2c). Doesn't
#: move any card to MODELED on its own (Sol, Advocate Eternal stays
#: blocked on an unrelated Partner gap), but is a real classification
#: change (one fewer UNCLAIMED clause on that card), so the version still
#: bumps per the ledger's own "reused vs parsed" keying. PAR-68's other
#: four cards (Agent Maria Hill, Virtual Assistant, Helicarrier Strike,
#: Beast Mode) are hand-authored (`game/card_registry/value.py`) —
#: +0 by design, no parser handler was written for any of them (each
#: confirmed a genuine singleton via `parser_probe.py blocked`, no nearby
#: cluster). +0 parser-modeled, +4 hand-authored this batch alongside
#: PAR-67's own +3, zero regressed (`python -m pytest -q`, 100
#: pre-existing unrelated failures unchanged before/after).
#: v383 closes PAR-69 (Doctor's companion, RULE 702.124m — the third
#: partner-ability variant alongside Partner/Choose a Background, same
#: `_TABLE` FLAG row treatment) and PAR-70 (the Mercadian Masques Rebel/
#: Mercenary recruiter tutor chain — `_SEARCH_CRITERIA`'s new `subtype`
#: qualifier maps "a rebel/mercenary permanent card" onto the existing
#: `"search"` `EffectSpec`, no new engine primitive). +3 and +17
#: respectively, +20 total, zero regressed (`parser_probe.py diff`); also
#: fixes a pre-existing, unrelated bug found while proving PAR-70
#: end-to-end: `GameContext._request_search` (`game/effects/core.py`) was
#: missing the `then_specs` param `RulesEngine._request_search` and
#: `SearchLibraryEffect.apply` already had (added by PAR-35..42's
#: `then_specs` plumbing but never threaded through this wrapper), which
#: made *every* search effect routed through an activated/triggered
#: ability or a resolving spell raise `TypeError` — 16 previously-broken
#: tests (`test_search_popular_tutors.py` et al.) now pass.
#: v384 closes PAR-71 — "that spell's mana value" as a resolve-time amount
#: referent, extending the already-shipped `amount_from_trigger_event`/
#: `count_from_trigger_event`/`pt_from_trigger_event` family (every
#: `SPELL_CAST` event already carries `mana_value`) to `PumpEffect`,
#: `GainLifeEffect`/`LoseLifeEffect`, `AddCountersEffect`, and two new
#: fields — `MillEffect.count_from_trigger_event`, `DiscoverEffect.
#: mana_value_from_trigger_event`. +10. A second, genuinely new referent
#: was needed for "Counter target spell. `<effect>`, where X is that
#: spell's mana value." (Hurl into History/Access Denied/Overwhelming
#: Intellect/Spell Swindle): "that spell" there is the *countered* RULE
#: 115 target, not a trigger event — `segmenter._announces_creature_
#: target` gained a `counter`-spec case so the connector-split loop opens
#: `previous_subject_only` rows for it, backed by `DiscoverEffect`'s new
#: `mana_value_from_subject` (`DrawCardEffect.amount_from_subject`/
#: `CreateTokenEffect.count_from_subject` already supported it) reading
#: `effects.core._characteristic_of_subject`'s existing
#: `"previous_subject_mana_value"`. +4, +14 total, zero regressed
#: (`parser_probe.py diff`, full cache). Two real cards print the
#: identical trap and were deliberately left unclaimed rather than
#: guessed: Imp's Mischief and Draining Whelk (see `Done_Backend.md`'s
#: PAR-71 entry). Execute-testing this batch (not just parse verdicts)
#: caught three real bugs, all fixed here: `_characteristic_of_subject`
#: never unwrapped a "spell"-kind `TargetSpec`'s `StackItem` pick to its
#: underlying `GameObject` before reading `.card` (silently measuring 0
#: for every `"previous_subject_mana_value"`/`"previous_subject_power"`/…
#: reading of a targeted *spell*, not just this batch's new use); and the
#: `"discover"`/`"mill"` `EffectRegistry` factory lambdas were never
#: updated to forward the new `DiscoverEffect`/`MillEffect` constructor
#: params this same batch added, so both were silently dropped at bind
#: time despite parsing correctly.
#: v385 closes PAR-72 — Party (RULE 700.8/702.129) generalized from a
#: cost-reduction "per"/"full party" boolean condition (PAR-53) into the
#: general resolve-time `amount_from_count_selector`/`count_selector`
#: family: `continuous.count_selector`'s existing `"creatures_in_your_
#: party"` branch is now read by ten distinct effect-verb templates
#: (mana, counter-tax, +1/+1 counters self/target, pump self/target/
#: multi-target/negative, gain life, token creation, scry, a combined
#: life-drain, damage single/twice/split-to-controller, an inspect-top
#: library dig, and a CDA/anthem pair on the static side). Three
#: primitives gained a param, all pure widening: `GainLifeEffect.
#: count_selector_multiplier` (every prior `count_selector` gain_life
#: shape was 1 life per unit; Shepherd of Heroes prints 2),
#: `ScryEffect.count_from_count_selector`, `InspectTopChooseEffect.
#: count_from_count_selector`/``count_plus`` (Skyclave Plunder's "X is 3
#: plus the number of…"); plus `CounterSpellEffect.unless_pays_extra_
#: selector` (Concerted Defense's dynamic "unless its controller pays {1}
#: plus an additional {1} for each…") and a `segmenter.py` trailing-
#: sentence peel folding "This ability costs {N} less to activate for
#: each…" into the *already-existing*, previously hand-authored-only
#: `ActivationCost.dynamic_reduction` (Seafloor Stalker is the oracle-text
#: route to Eiganjo, Seat of the Empire's own primitive). +22 solo cards
#: plus 2 bonus closures (Stonework Packbeast/Veteran Adventurer print the
#: same self-type-grant line traced for Burakos, Party Leader), +24 total,
#: zero regressed (`parser_probe.py diff`, full cache). Acquisitions
#: Expert was deliberately left UNCLAIMED: its "reveal a number of cards…
#: you choose one" shape has the *hand's owner*, not the caster, choosing
#: which cards get revealed — a genuinely different two-step interactive
#: primitive from `RevealHandChooseDiscardEffect`'s "reveal the whole
#: hand" template, out of this ticket's "generalize an existing amount"
#: scope. Execute-testing (not just parse verdicts) caught one real,
#: previously-latent bug while proving Synchronized Spellcraft's "and X
#: damage to that creature's controller" half: `DealDamageEffect`'s
#: `recipient_subject` resolution path read raw `self.amount` instead of
#: `_amount_for` (the method that actually applies `amount_from_count_
#: selector`/`amount_from_trigger_event`/`amount_if_target_color`), so any
#: of those three silently vanished whenever combined with
#: `recipient_subject` — no shipped card had combined them before now.
#: v386 closes MEC-86 (Prepared, RULE 722.3a), MEC-87 (Horsemanship, RULE
#: 702.31) and MEC-88 (Banding, RULE 702.22) — three PAR-31…PAR-53-cluster
#: tickets that each needed a genuine new engine primitive before any
#: parser handler could be meaningful, filed together under `## MEC` in
#: BACKLOG.md. MEC-86: the engine primitive (`GameObject.prepared`,
#: `RulesEngine.make_prepared`, `BecomePreparedEffect`) and the parser
#: handler for a card's own "~ becomes prepared" trigger body already
#: existed — the whole ticket was one missing dispatch: "~ enters
#: prepared." (no "when…") wasn't routed to it. `gate.py`'s per-line loop
#: now synthesizes the equivalent "when ~ enters, it becomes prepared"
#: trigger for that bare shape (mirroring the Haunt ETB synthesis just
#: above it), closing all 22 solo-blocked cards with zero engine changes.
#: MEC-87: Horsemanship needed real `game/combat.py` wiring (`has_
#: horsemanship`, wired into `can_block` — it had none despite being a
#: recognized RULE 702 keyword) plus five parser handlers: the "can't be
#: blocked by creatures with horsemanship" combat restriction and
#: "destroy/tap target creature with/without horsemanship" filters widen
#: two pre-existing small keyword-filter vocabularies
#: (`static_handlers._FILTER_KEYWORD_WORDS`, `handlers._CREATURE_FILTER_
#: KEYWORD_WORDS`); "~ deals N damage to each creature with/without
#: horsemanship" widens the previously flying-only `damage_each_nonflyer`
#: handler (renamed `damage_each_creature_keyword`) into a small keyword
#: alternation; "tap 1 or 2 target creatures without horsemanship" (Broken
#: Dam) is a new multi-target-plus-creature-filter row; "target creature
#: gets +N/+M and gains horsemanship." (Riding the Dilu Horse, Portal
#: Three Kingdoms' own "this effect lasts indefinitely" reminder — no
#: "until end of turn" tail at all) is a new permanent (``rest_of_game``
#: duration) sibling of `_grant_until`/`_pump_until`, combining an
#: `anthem` static and a `grant_keyword` static under one `GrantUntilEffect`.
#: +30 solo cards, zero regressed.
#: MEC-88: Banding needed the same kind of engine wiring — `has_banding`
#: plus RULE 702.22j's damage-assignment reroute (`game/engine/
#: combat_mixin.py`'s `_assign_blocked_attacker`/new `_assign_blocked_
#: attacker_evenly`: when Banding is involved on either side of a block,
#: the defending player's even-split order replaces the attacker-
#: favouring lethal-first-then-trample order — execute-tested via a real
#: multi-blocker combat, confirmed to actually split evenly rather than
#: just parse). RULE 702.22c's interactive attacking-*band* declaration
#: is explicitly out of scope: no MODELED Commander-legal card exercises
#: it, and "bands with other `<quality>`" collapses to plain Banding
#: throughout (the quality restriction only matters for that undeclared
#: mechanic) — the same simplification `static_handlers._quoted_ability_
#: grant_effects_list`'s new bare `"bands with other .*"` branch and the
#: hand-authored `card_registry.special_mechanics._master_of_the_hunt`
#: (a "create a *named* token, then a follow-up sentence grants it a
#: quoted ability" compound with no existing grammar at all — confirmed a
#: genuinely separate ~60-card family via `parser_probe.py`, well outside
#: this ticket, so hand-authored as the sanctioned singleton escape valve
#: instead) both use. Two more small handlers: `_grant_subtype_target`
#: ("target Bird creature gains banding until end of turn", Soraya the
#: Falconer — the keyword-only sibling of the existing P/T-only `_pump_
#: subtype_target`) and `_lose_banding` (a `remove_keyword`-parked `grant_
#: until`, Shelkin Brownie). +9 solo cards, zero regressed. Four real
#: cards stay UNMODELED, each blocked by its own separate, non-Banding-
#: specific template gap traced and left as documented residue rather
#: than guessed at: Tolaria (a new "activate only during any upkeep step"
#: RULE 602.5d timing-restriction marker, five-file engine wiring);
#: Urza's Avenger (a "your choice of `<kw1>`, `<kw2>`, …" modal keyword-
#: choice grant — a real interactive choice with no existing primitive);
#: Nature's Blessing (an "instruction A, or `<creature>` gains X instead"
#: alternative-effect-body shape); Wall of Caltrops (a board-state
#: conditional trigger counting blockers by creature type). Oddric, Lunar
#: Marquis (an 11-keyword "the same is true for…" quoted-grant cluster
#: shared with the MEC-87 Horsemanship residue) stays [PAR-12] bespoke
#: tail, same as PAR-69's own residue.
#:
#: v387 is PAR-79's first increment — "<Name>/target creature can't be
#: blocked this turn" broad recognition. `UnblockableEffect`/the
#: "unblockable" effect key already existed end to end (ENG-32); this batch
#: is parser recognition only, three widened shapes: a keyword grant plus
#: unblockable in one sentence (`_PUMP_KEYWORD_UNBLOCKABLE_RE`, the
#: keyword-grant sibling of the already-shipped `_PUMP_UNBLOCKABLE_RE`),
#: "another target attacking creature can't be blocked this turn"
#: (`_CANT_BE_BLOCKED_TURN_OTHER_ATTACKER_RE`, the unblockable sibling of
#: `_PUMP_OTHER_ATTACKING_CREATURE_RE`), and an optional "with power N or
#: less/greater" target-power suffix added to both the new handler and the
#: pre-existing bare `_CANT_BE_BLOCKED_TURN_RE` (the same suffix
#: `_GAIN_CONTROL_EOT_RE` already uses). +24, zero regressed
#: (`parser_probe.py diff`). Confirmed via `parser_probe.py blocked "can't
#: be blocked this turn"` that ~81 SOLO cards remain, split across several
#: distinct smaller shapes with no single dominant template left (a
#: delayed-trigger "return that creature to hand" tail on the Alora cycle,
#: an activation-cost-reduction rider, a qualified "except by creatures
#: with `<kw>`" evasion form, a bare-subtype-without-"creature" target, an
#: unrelated conditional-phase-trigger gap that only incidentally shares
#: this search phrase, and "another target legendary creature" needing a
#: `creature_filter` "legendary" key that doesn't exist yet) — see
#: BACKLOG.md's PAR-79 entry for the residual breakdown rather than
#: treating this as closed.
#: v408 is a structural consolidation, not a coverage increment (+0/+0,
#: `parser_probe.py diff`): PAR-79's "another target attacking creature"/
#: "[another ]target legendary creature" rows (`_CANT_BE_BLOCKED_TURN_
#: OTHER_ATTACKER_RE`/`_CANT_BE_BLOCKED_TURN_LEGENDARY_RE`) existed only
#: because `static_handlers.object_filter` didn't yet recognise "attacking"/
#: "legendary" as leading flag words the way `combat.matches_object_filter`
#: already reads them — so it would have mis-guessed "legendary" as a bogus
#: creature *subtype* (a filter that could never match a real creature) had
#: those two rows been deleted outright first. Fixed at the axis instead:
#: `object_filter` now strips a leading "tapped"/"attacking"/"blocking"/
#: "legendary" word itself (`_OBJECT_FILTER_FLAG_WORDS`) and recurses on the
#: remainder, so the two dedicated rows became a strict subset of the
#: general "target `<object-filter phrase>` can't be blocked this turn" row
#: and were deleted. A third instance of `reference/handler-recipe.md`'s
#: "decompose into atomic grammar units" lesson (after PAR-78/v393 and
#: PAR-79/v401) — every other `object_filter` caller (the standing "except
#: by legendary creatures" static, the "unless you control an attacking
#: `<X>`" count) gains the same two words for free.
#: v409 fixes a real, live rules bug found while verifying v408: the
#: `_TARGET_ROWS` row for "target attacking/blocking/tapped/untapped
#: creature" (`subgrammars.py`) collapses onto the bare "creature" kind by
#: design (RULE 115's own precision-loss convention this file already
#: applies elsewhere) — but nothing preserved the discarded qualifier
#: elsewhere, so every generic handler reading `resolve_target_kind` alone
#: (destroy/exile/damage/tap/return_to_hand/pump/connive/add_counters)
#: silently dropped it. Confirmed via `inspect-db` against the real cache:
#: Assassinate ("Destroy target tapped creature") parsed `MODELED` but
#: would destroy *any* creature in an actual game — not a coverage gap, a
#: wrong-resolution bug on an already-`MODELED` card. New sibling function
#: `resolve_target_creature_state_filter` (`subgrammars.py`) extracts the
#: qualifier from the same raw target phrase as a `combat.
#: matches_object_filter` fragment; 8 handler functions (`_destroy`,
#: `_exile`, `_exile_until_leaves`, `_damage`/`_damage_x`, `_tap`,
#: `_return_to_hand`, `_pump_target`'s 13 callers via one shared
#: `_pump_target_creature_filter` helper, `_add_counters_target_params`,
#: `_cant_be_blocked_turn`, `_connive_target`) now merge it into their own
#: `creature_filter`. Two of those regexes (`_pump_subtype_target`/
#: `_grant_subtype_target`) had a second, independent instance of the same
#: root shape — their bare `[a-z]+` "subtype" capture blindly accepted
#: "attacking"/"blocking" as if they were real creature subtypes (a filter
#: that could then never match anything, RULE 115 target-count 0 — worse
#: than Assassinate's over-wide match), now routed through the same
#: function first. `ConniveEffect` (`game/effects/choices_actions.py`)
#: gained a `creature_filter` constructor param and registry forwarding —
#: the one card in this sweep (Raffine, Scheming Seer) needing an actual
#: (small, already-established-shape) engine addition, not just parser
#: wiring. 87 real MODELED-but-wrong cards fixed, 0 coverage change (all 87
#: were already MODELED — this corrects the emitted spec, not the
#: MODELED/UNMODELED verdict), 0 regressed (`parser_probe.py diff`).
#: v414 closes PAR-115's first increment — `14_` S4's own
#: "one part failing discards every sibling" disease, attacked the same
#: incremental way PAR-62 already proved out rather than the ticket's own
#: "rewrite `parse_effect_body`" framing: "`<destroy/exile/counter/return/
#: tap X>`. its controller `<verb>` …" is a *referent*, not a connective —
#: `segmenter._announces_creature_target` already flips `previous_subject=
#: True` after exactly the right antecedent clauses (built across PAR-18/
#: 30/71), and `EffectHandler.previous_subject_only` already gates a row on
#: it, so this only adds the rows themselves: `lose_life`/`gain_life`/
#: `draw` read the referent through `game/effect_operands.py`'s
#: ``{"of": "previous_target", "as": "controller"}`` (the same vocabulary
#: `game/card_catalogue/swords_to_plowshares.py`/`nature_s_claim.py`
#: already spell out by hand for one card each), and `mill` reuses
#: `MillEffect`'s own pre-existing ``selector="previous_subject_controller"``
#: (built for Broken Ambitions, MEC-50). Two amount forms beyond a flat
#: number reuse ENG-37's `bind` node the same way `swords_to_plowshares.py`
#: does: "gains life equal to its mana value" (Illumination), "mills cards
#: equal to that creature's power" (Grisly Spectacle). `DiscardEffect.
#: player` gained the same referent-dict resolution `GainLifeEffect`/
#: `LoseLifeEffect`/`DrawCardEffect` already had via `GameEffect.
#: _operand_player`; `MillEffect` needed no engine change at all. +34, 0
#: regressed (`parser_probe.py diff`), including two cards needing no new
#: grammar at all: Death Bomb (the pre-existing `_NO_REGEN_SENTENCE_RE`
#: "after" tail already threads `previous_subject` through) and Zulaport
#: Duelist (`_announces_creature_target`'s generic `_CREATURE_TARGET_KINDS`
#: scan already covers a `pump` clause's own `target_kind`). The
#: sacrifice-verb, group-subject ("whenever a creature dies, its
#: controller discards…"), attached-permanent ("enchanted creature/land",
#: RULE 303.4c — the referent axis `effect_conditions.subject_of` doesn't
#: resolve yet, only `static_conditions`'s own separate machinery does),
#: and conditional ("if `<X>`, its controller loses…") sibling shapes stay
#: open — real, separately-scoped residue, not attempted this pass; see
#: `BACKLOG.md`'s PAR-115 entry.
#: v415 closes PAR-115's own group-subject residue (PAR-117's first
#: increment): "whenever a `<type>` [you control] `<verb>`, its controller
#: `<verb2>` …" (Poisonbelly Ogre — "whenever another creature enters, its
#: controller loses 1 life."), where "its" is RULE 603.1's own group-subject
#: referent (whichever object satisfied the trigger, a different one every
#: firing) rather than a creature an earlier clause of the same body
#: targeted. `effect_conditions.subject_of("entering", ...)` already
#: resolves it (MEC-28's own `group_subject_only` pronoun gate), so the same
#: ``{"of": "entering", "as": "controller"}`` referent `GainLifeEffect`/
#: `LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect` already read via
#: `_operand_player` works unchanged — this only adds the `group_subject_
#: only`-gated rows, reusing PAR-115's own regexes verbatim, plus one new
#: `MillEffect.selector="trigger_subject_controller"` (`MillEffect` reads
#: its player off a bespoke selector string, not `_operand_player`). +1
#: (Poisonbelly Ogre), 0 regressed (`parser_probe.py diff`). PAR-117's
#: other four sub-shapes (attached-permanent controller, the sacrifice
#: verb, a conditional wrapper, an "unless" cost alternative) and this same
#: group-subject shape's own color-/power-qualified and "attacks you"
#: variants (Bereavement, Kavu Lair, Hissing Miasma, MacCready — each
#: blocked on `_trigger_condition()` returning `None` for that phrasing, a
#: separate RULE 603.1 grammar widening apiece, not this referent) stay
#: open — see `BACKLOG.md`'s PAR-117 entry.
#: v416 closes PAR-117's attached-permanent-controller sub-shape:
#: "whenever enchanted creature/land `<trigger>`, its controller `<verb>`
#: …" (Contaminated Bond/Corrupted Roots/Sinister Possession/Ragged Veins/
#: Visions of Brutality/Chronic Flooding/Fate Foretold/Decomposition) —
#: "its" is RULE 303.4/301.5's *attached host*, a fourth pronoun referent
#: alongside `previous_subject_only`/`group_subject_only`: the trigger
#: *condition itself* already names it (`{"subject": "attached_permanent"}`,
#: `segmenter._ATTACHED_SUBJECT_RE`/`_ATTACHED_MULTI_EVENT_RE`/the
#: ``attached`` groups on `_DAMAGE_TRIGGER_RE`/`_DAMAGE_RECIPIENT_TRIGGER_
#: RE` already recognized every antecedent in this cluster), not a pronoun
#: chain within the effect body — so this closes on a new `handlers.
#: EffectHandler.attached_subject_only` gate, threaded from the trigger
#: condition rather than from a preceding split clause. New `effect_
#: conditions.subject_of("attached", ...)` referent (reading ``source.
#: attached_to``, the resolve-time sibling of `static_conditions._subject`'s
#: existing standing-condition lookup) lets `GainLifeEffect`/`LoseLifeEffect`/
#: `DrawCardEffect`/`DiscardEffect` read it through the same ``{"of":
#: "attached", "as": "controller"}`` operand `_operand_player` already
#: resolves for `previous_target`/`entering` — no per-class plumbing needed;
#: `MillEffect` gets a new `selector="attached_permanent_controller"`, the
#: sibling of `"trigger_subject_controller"` (`LoseLifeEffect.selector` of
#: the same name already existed, built for the hand-authored Parasitic
#: Impetus, PAR-60 wave 3 — this was only ever missing the parser row and
#: the `MillEffect`/`DrawCardEffect` engine reach, not the referent itself).
#: +8, 0 regressed (`parser_probe.py diff`). PAR-117's remaining residue
#: (the sacrifice verb, the conditional wrapper, the "unless" cost
#: alternative, and the group-subject shape's own color-/power-qualified/
#: "attacks you" variants) is unrelated to this referent and stays open —
#: see `BACKLOG.md`'s PAR-117 entry.
#: v417 closes two independent slices of PAR-117's sacrifice-verb residue.
#: (1) "Its controller sacrifices it at the beginning of the next end
#: step." (Celestial Sword/Goblin Ski Patrol) is *not* a fourth referent:
#: RULE 701.17a already makes "sacrifice" inherently self-directed — a
#: permanent's own controller is the only player who can ever sacrifice
#: it — so `SacrificeSpecificEffect.apply` never reads a player at all,
#: only the captured object; "its controller sacrifices it" and a bare
#: "sacrifice it" (PAR-30's `_DELAYED_SAC_EXILE_TAIL_RE`) compile to the
#: identical spec. Closed on recognition alone — an optional "its
#: controller " subject plus third-person "sacrifices/exiles/destroys"
#: conjugation on the existing regex, no engine change. (2) "Its
#: controller sacrifices `<N>` [nontoken] `<what>`[ or `<what2>`] of their
#: choice." (Funeral March — attached-permanent referent; Tainted Aether —
#: group-subject referent) *is* a real widening: `SacrificeEffect.player`
#: had never been routed through `GameEffect._operand_player` the way
#: `GainLifeEffect`/`LoseLifeEffect`/`DrawCardEffect`/`DiscardEffect`/
#: `MillEffect` already are, so the `{"of": …, "as": "controller"}`
#: referent silently fell through to `targets[0] if targets else None`.
#: A second, independent gap surfaced fixing it: `EffectRegistry`'s own
#: `"sacrifice"` factory lambda never forwarded a parsed spec's `player`
#: key to `SacrificeEffect.__init__` at all (unlike its `draw`/`gain_life`/
#: `lose_life`/`discard` siblings, which already do) — the constructor
#: parameter existed and predates this ticket, but no `EffectSpec` could
#: ever reach it. Also adds `"creature_or_land"` to `damage_death_mixin.
#: _matches_permanent_type` (Tainted Aether's own two-word choice — a new
#: whitelisted combination, not a new predicate). +3 (Celestial Sword,
#: Funeral March, Tainted Aether), 0 regressed (`parser_probe.py diff`).
#: Goblin Ski Patrol stays UNMODELED on its own unrelated singleton
#: ("Activate only once and only if you control a snow Mountain." — a
#: reversed clause order plus a "snow `<land type>`" selector neither
#: shared by any other cached card, confirmed via `parser_probe.py
#: blocked`) — left for `singletons.md`. Fade Away/Killing Wave's leading
#: "for each creature, its controller sacrifices …" (RULE 601.2c's
#: unscoped per-object iteration, a different shape from the trailing
#: `_FOR_EACH_SUFFIX_RE` this file already models) and Torment of Venom's
#: compound "unless they sacrifice `<X>` of their choice or discard a
#: card" stay open, unrelated to either closure above — see `BACKLOG.md`'s
#: PAR-117 entry.
#: v418 closes PAR-117's conditional-wrapper residue — "`<effect>`. if
#: `<predicate>`, its controller `<verb>` …". The ticket's own note that
#: this "may fall out for free" once the base `_ITS_CONTROLLER_*` rows
#: existed was wrong: `segmenter._GENERIC_IF_PREFIX_RE`/`_GENERIC_IF_
#: SUFFIX_RE` already peeled the "if …," shape and handed the gated
#: remainder back into `parse_effect_body` with `previous_subject=True`
#: (proven on all 5 named cards — every one still failed, each on an
#: unrecognized *predicate* phrase, not a missing referent). Four new
#: `static_conditions.py` phrase rows, all pointed at `previous_target`
#: instead of the default `source`: "that creature is legendary" (a new
#: `is_legendary` kind — neither `is_card_type` nor `is_subtype` covers a
#: supertype); "that creature was `<color>`[ or `<color2>`]" (Gloomlance) —
#: no new kind, just the already-shipped `is_color` OR'd via the `any`
#: combinator (ENG-36); "that creature wasn't dealt damage this turn"
#: (Faller's Faithful) — a new `was_dealt_damage_this_turn` kind reading
#: `GameObject.damage_marked`, which RULE 514.2 clears only at cleanup, so
#: nonzero marked damage anywhere else in the same turn already means
#: "dealt damage this turn"; and "an `<type>` is destroyed this way"
#: (Acolyte Hybrid) — no new kind, the already-shipped RULE 608.2 `this_
#: way` resolution tally (`GameContext.permanents_destroyed_this_way`)
#: through the generic `amount_compare` context condition, deliberately
#: *not* re-reading `previous_target` (a "destroy up to one" that chose
#: zero targets leaves nothing to type-filter, but the tally already
#: answers "did the destroy happen" directly). +6 (the 4 named cards plus
#: 2 bonus sharing the same two shapes — Gloomwidow's Feast, Smashing
#: Success), 0 regressed (`parser_probe.py diff`). Soul Reap ("…if you've
#: cast another black spell this turn") stays UNMODELED: "another" needs a
#: per-colour, per-turn spell *count* to exclude the resolving spell's own
#: cast, and `GameState.spell_colors_cast_this_turn` is a set (already
#: containing this spell's own colour by the time it resolves), not a
#: count — a real, separate primitive, left open in `BACKLOG.md` rather
#: than guessed at here.
#: v419 closes PAR-117's group-subject colour-qualifier residue —
#: "whenever a `<color>` `<type>` [you control] `<verb>`, …" (Bereavement;
#: the RTR "Denizen" cycle — Court Street/Foundry Street/Sage's Row/Shadow
#: Alley Denizen; Ivy Lane Denizen; Sylvan Anthem; Teysa, Orzhov Scion;
#: Linden, the Steadfast Queen). A single new `color` key on `_GROUP_
#: SUBJECT_RE`/`_group_subject_condition` (segmenter.py) and `effect_
#: binder._build_group_ok` (binding/core.py), checked the same "event
#: snapshot, live-board fallback" way `tword`/`want_nonland` already are.
#: RULE 400.7 means a DIES-shaped condition (Bereavement, Teysa) needs the
#: colour actually snapshotted onto the firing event — added alongside the
#: already-snapshotted `object_types`/`subtypes` in the DIES event's one
#: firing site (`damage_death_mixin.py`) — since a live re-lookup after the
#: object has left the battlefield finds nothing; every other event kind
#: this filter reaches (ENTERS_BATTLEFIELD, ATTACKS) keeps the object
#: around, so the pre-existing live-lookup fallback already covers those.
#: +9, 0 regressed (`parser_probe.py diff`). Dire Undercurrents and Yorvo,
#: Lord of Garenbrig share the same search phrase but stay UNMODELED — the
#: colour condition itself now parses and fires on both, gated behind a
#: separate, unrelated unclaimed clause each ("you may have target player
#: draw a card"; a comparative "if that creature's power is greater than
#: ~'s power" — confirmed via `parser_probe.py card`, neither attempted
#: here). Justice's "a red creature **or spell** deals damage" is a
#: different trigger family entirely (`_DAMAGE_TRIGGER_RE`'s creature-or-
#: spell compound subject), not this one.
#: v420 closes PAR-117's group-subject power-qualifier residue —
#: "whenever a creature with power `<n>` or `<less/greater>` `<verb>`, …"
#: (Kavu Lair — "…enters, its controller draws a card."; the "another
#: creature you control with power 2 or less enters" template several
#: creature-support cards share). No new engine primitive: a "with power
#: `<n>` or `<less/greater>`" fragment already existed in several one-shot
#: target/damage-filter handlers, reused here as a `_GROUP_SUBJECT_RE`
#: qualifier; `effect_binder._build_group_ok` gained `min_power`/`max_power`
#: keys read **live** off the board — unlike the colour axis's DIES-shaped
#: cards (v419), every verb this filter reaches (ENTERS_BATTLEFIELD,
#: ATTACKS) keeps the acting object on the battlefield when the condition
#: is checked, so no RULE 400.7 event snapshot is needed. +17 — far more
#: than the 15-card search phrase this axis was sized against, since the
#: regex widening is general and also reached several bonus cards using the
#: same shape with an unrelated payoff (Garruk's Packleader, Inspiring
#: Commander, Marketwatch Phantom, Mentor of the Meek, Neighborhood
#: Guardian, Outcaster Trailblazer, Paleoloth, Snarling Gorehound, Vicious
#: Clown) — 0 regressed (`parser_probe.py diff`). Six cards sharing the
#: original search phrase stay UNMODELED on their own separate, unrelated
#: clause (confirmed via `parser_probe.py card`, none attempted here):
#: Cavalcade of Calamity/Raid Bombardment's own "the player or planeswalker
#: **that creature is attacking**" referent; Life Finds a Way's "**populate**"
#: keyword action; MacCready, Lamplight Mayor, which needs the still-open
#: "attacks **you**" defending-player axis *as well as* this one; Subira,
#: Tulzidi Caravanner's granted delayed-trigger-from-a-cost-line grammar;
#: and Where Ancients Tread's unrecognized "you may have `<name>` `<effect>`"
#: wrapper.
#: v421 closes PAR-117's group-subject "attacks **you**" residue axis —
#: RULE 506.4's defending-player scope on a group ATTACKS condition
#: (Hissing Miasma). No new engine primitive: the ATTACKS event already
#: carries a `defending_player_id` (read by `attacked_player_lowest_life_
#: predicate`'s trigger-level gate, MEC-28); `_GROUP_SUBJECT_RE`/`_group_
#: subject_condition` (segmenter.py) gained a trailing "you" qualifier and
#: `effect_binder._build_group_ok` a new `attacks_you` key checking that
#: same event field against this ability's own controller. +1, 0 regressed.
#: MacCready, Lamplight Mayor's power-and-attacks-you-qualified second
#: ability now parses (both axes combine independently), but the card stays
#: UNMODELED on its unrelated first ability ("it gains skulk" — a
#: group-subject *self* grant, not an "its controller" referent). Sizing
#: this axis surfaced a much larger sibling shape, deliberately not
#: attempted here: "attacks you **or a planeswalker you control**" (RULE
#: 506.4c, 12 SOLO cards) needs a real new event field first — a
#: planeswalker-kind `combat_defender`'s controller isn't resolved onto the
#: ATTACKS event at all today (`defending_player_id` is `None` for those
#: attacks by construction, not a latent bug) — see `BACKLOG.md`'s PAR-117
#: entry.
#: v422 closes PAR-117's own Essence Sliver residue — a `DAMAGE`-shaped
#: RULE 603.1 group-subject condition ("whenever a `<type/subtype>` [you
#: control] deals [combat ]damage[ to `<recipient>`], its controller
#: `<verb>`", Edric, Spymaster of Trest; the Sliver "combat damage to a
#: player" cycle — Essence/Brood/Synapse Sliver). Two independent parser
#: gaps, both scoped to `_DAMAGE_TRIGGER_RE`'s own dispatch rather than the
#: already-correct shared group-subject machinery: the dispatch never
#: passed `group_subject=True` at all (none of PAR-115/117's own
#: `group_its_controller_*` rows, already shipped for every *other* RULE
#: 603.1 event, were reachable for `DAMAGE`), and the trigger regex's
#: group-subject branch only recognized `_GROUP_TYPE_WORDS`'s closed
#: main-type vocabulary — a creature *subtype* ("a Sliver deals damage")
#: had no route in, unlike the ENTERS/DIES/ATTACKS/BLOCKS family's own
#: `_GROUP_SUBTYPE_SUBJECT_RE` sibling. A third gap, found diagnosing
#: Edric/Synapse Sliver: "its controller **may** `<effect>`" had no
#: composition at all (`_peel_optional` only ever strips a *leading* "you
#: may") — `game/effects/composition.py`'s `OptionalEffect.player` gained a
#: referent-dict mode (the same `{"of": …, "as": "controller"}` vocabulary
#: `GainLifeEffect`/`DrawCardEffect` already read) alongside its existing
#: "you"/"target" strings, and a new `_MID_BODY_ITS_CONTROLLER_MAY_RE`
#: composer (segmenter.py) wraps the same `"optional"` node
#: `_MID_BODY_OPTIONAL_RE`'s plain "you may" already builds. Proving these
#: end to end surfaced two real correctness traps, not just recognition
#: gaps: (1) RULE 603.1's "its controller" both *asks* and, once answered,
#: *acts* — the referent has to survive `OptionalEffect`'s own choice pause
#: and reach the inner body too, not just the question, so
#: `_resume_composite_optional` now restores a minimal synthetic
#: `trigger_event` around the resumed body and a new `_rewrite_optional_
#: referent_actor` (segmenter.py) threads the same referent onto the
#: inner `draw`/`create_token` spec's own actor field (`CreateTokenEffect`
#: gained a `creators="trigger_subject_controller"` value, the `MillEffect.
#: selector` of the same name's sibling). (2) Rakish Heir/Stensia
#: Masquerade's bare "put a +1/+1 counter on **it**" collides, at the
#: `AddCountersEffect` spec level, with an unrelated card naming *itself*
#: under the identical group condition (Malakir Cullblade's own "…dies, put
#: a +1/+1 counter on Malakir Cullblade.", folded to "~") — both compile to
#: the same untargeted spec, so a first cut that rewrote it at bind time
#: (unable to tell which literal word the clause used) silently broke three
#: already-shipped tests before being replaced with a narrowly-matched,
#: `group_subject_only`-gated parser row (`_add_counters_group_subject_it`,
#: matching only the literal "it") tried before the generic self/"~" row.
#: A third, deliberately unclaimed shape: "…deals combat damage to **a
#: creature**, destroy **that creature**…" (Sosuke, Son of Seshiro) needs
#: the damage *recipient* — a referent distinct from both the group subject
#: and a same-resolution `previous_target` that this project doesn't model
#: yet; `delayed_sac_exile_tail`'s generic `previous_or_self` capture would
#: otherwise silently fall back to the ability's own source, so this one
#: recipient shape is refused outright rather than guessed (confirmed via
#: `parser_probe.py diff` staying 0 regressed against the full cache).
#: +18 (Edric, Essence/Brood/Synapse Sliver, Rakish Heir, Stensia
#: Masquerade, and 12 bonus cards sharing the widened subtype/group-subject
#: axis outside this ticket's own search phrase), 0 regressed.
#: v449 opens PAR-119 (composed trigger-head grammar) with its pilot axis, the
#: cast-spell filter: `catalogue/spell_phrase.py` + `catalogue/characteristic_
#: phrase.py` build one `SPELL_CAST` head from shared word tables (multicolored/
#: colorless/legendary/kicked, colour and type alternations, `with mana value|
#: power N or greater|less`, `with <keyword>`, "of the chosen color/type",
#: "from your graveyard / exile / anywhere other than your hand", "you don't
#: own", "that targets a `<filter>` [you control]", "during your/an opponent's
#: turn") instead of one regex + dispatch block per combination. Tried only
#: after every legacy cast row declined, and `when` now reads like `whenever`.
#: +76 (`parser_probe.py diff`), 0 regressed.
#: v450 extends PAR-119's composed head to the object events (enters / dies /
#: attacks / blocks / leaves the battlefield): `catalogue/object_trigger_head.py`
#: reads one subject noun phrase (`characteristic_phrase.parse_object_phrase` —
#: adjectives, card types, the generated `subtype_vocabulary`, colours, `with
#: <qualifier>`, "of the chosen type") × one or two verbs × shared tails, into a
#: `{"subject": "group", "filter": …}` condition the binder reads through
#: `combat.matches_object_filter` (last-known values for a departure, RULE
#: 603.10a). Also splits "when X and whenever Y, Z" into two triggers, and lets a
#: "pay {cost}, then return this card" trigger function from the graveyard. Tried
#: only after the per-adjective regexes decline. The same head also reads
#: "<player> sacrifices/discards <object>" (SACRIFICE / DISCARD_CARD, the object
#: filtered through last-known values) and "<subject> deals [combat|noncombat]
#: damage [to <recipient>]" (DAMAGE; recipient a player, "an opponent", "you" or an
#: object phrase). Audits of the newly claimed cards fixed three pre-existing
#: wrong-but-MODELED shapes: "for each `<counter>` counter on it" under a
#: self-subject trigger now reads the source's last-known counters, a "for each"
#: with a printed magnitude above 1 multiplies instead of replacing it, and the
#: composed group head refuses a bare "it" that would act on the source. +138
#: (`parser_probe.py diff`), 0 regressed.
#: v451 closes the doubler axis of PAR-122: `catalogue/trigger_doubler.py` reads
#: "if a triggered ability of `<subject>` triggers" / "if `<cause>` causes a
#: triggered ability of a permanent you control to trigger" into one
#: `trigger_doubler` spec built from a *subject* (a `matches_object_filter` dict
#: on the doubled permanent, plus "another"/"equipped") and a *cause* (a
#: trigger-shaped dict answered by the binder's own `_trigger_condition`, so "a
#: creature you control attacking" means "whenever a creature you control
#: attacks"), with an `active_if` gate for "as long as …"; the seven hand-authored
#: doublers were migrated onto it and `TriggerDoublerEffect`'s six flat flags
#: retired. The legacy tribal rows now accept only real subtypes (from
#: `subtype_vocabulary`), and the shared grammar reads "commander", "outlaw" and
#: "historic" for what they are — claimed-but-never-firing "subtype" triggers
#: (Keleth, Vial Smasher, Traveling Chocobo's cause) now parse correctly. +19,
#: 0 regressed.
#: v452 opens PAR-120's shared count vocabulary: `catalogue/count_phrase.py` reads a
#: count phrase ("creatures you control", "creature cards in your graveyard", "lands
#: your opponents control", "creatures with different powers") with the shared
#: noun-phrase grammar into a structured `{zone, of, filter, distinct}` selector that
#: `continuous.count_selector` evaluates through `matches_object_filter`. It feeds
#: "for each `<count>`" amounts, the generic "where X is the number of …" / "`<life|
#: cards|damage>` equal to the number of …" bind, and the comparator half of a leading
#: "if" / "as long as" (`control_count`, and the new `opponent_has_more`) — including
#: the open-vocabulary "you control a Wizard / an Ajani planeswalker / three or more
#: Gates" templates the older named row declined. A named condition row that matches but
#: has no reading no longer blocks the count grammar. A bare "on it" is now refused unless
#: it names the source or an announced target, and `bind` amounts are shape-checked like
#: every other measurement. +203 +147, 0 regressed.
#: v453 adds ENG-47's turn history: every fired event is stamped with its turn
#: (`GameEvent.turn`, set by `GameState.fire_event`), `GameState.events_this_turn`
#: walks the log back to the first earlier turn, and a "… this turn" condition —
#: `catalogue/history_phrase.py` reads it as the head of a trigger in the past tense
#: ("a creature you controlled died", "you haven't cast a spell from your hand",
#: "two or more nonland permanents entered the battlefield under your control") — is one
#: `event_this_turn` condition (a trigger-shaped dict, evaluated by the binder's own
#: predicate over the turn's log) instead of a hand-kept tracker per phrase. +47,
#: 0 regressed.
#: v454 is a pure de-duplication (PAR-121, no classification change): the four "`<sacrifice
#: | destroy | tap | exile>` ~ unless you pay `<cost>`" rows became one over the leading
#: verb; the specs of all 489 cards with "unless you" text are byte-identical before and
#: after.
#: v455 fixes two wrong-but-modeled families (PAR-123, PAR-124). Under a group-subject
#: trigger a bare "it"/"that creature" is the object that fired it while "~" is the
#: source, yet both parse to one untargeted spec that acts on the source: the parser now
#: stamps the pronoun reading (`target_kind: "trigger_subject"`, resolved per event by the
#: binder) on `tap`/`return_to_hand`/`exile`/blink and leaves "~" on the source (Cunning
#: Evasion, Grazilaxx and Gossip's Talent acted on themselves; Baloth Prime's "untap this
#: creature" untapped the sacrificed land). And a spell's "whenever … this turn" /
#: "until end of turn, whenever …" is no longer a permanent-shaped trigger no scan ever
#: reaches: it is a `create_turn_trigger` effect whose `TurnScopedTrigger` lives on
#: `GameState` for the turn (RULE 603.7a) — seven claimed cards had been inert. +3.
#: v456 continues PAR-119's composed heads (+119 with v455's, 3 deliberate corrections).
#: Attack batches — "whenever you attack with N or more `<creatures>`", "~ and at least N
#: other creatures attack" (Battalion) — are a count over the whole declaration, so the engine
#: fires `ATTACKERS_DECLARED` (per attacking player, every attacker) when combat locks in and
#: the head is one `attackers_declared` spec (object filter × min/max × other × includes-
#: source). "~ attacks and isn't blocked" reads a new `ATTACKER_UNBLOCKED` event; "attacks
#: while `<state>`" is read as the same clause's "if `<state>`" through the leading-if
#: grammar, "while saddled" as the source's own `requires_saddled`. The block relation — "~
#: blocks a creature with flying", "becomes blocked by …", "blocks or becomes blocked by a
#: non-Wall creature" — reads the creature(s) on the other side (`related_ids` on BLOCKS /
#: BECOMES_BLOCKED) through a `related_filter`, and "destroy that creature at end of combat"
#: under it captures those creatures (`trigger_related`) instead of the source, which the
#: Basilisk cycle would otherwise have destroyed. Player events — "a player cycles a card",
#: "an opponent loses life", "you draw your third card in a turn", "you lose life during your
#: turn" — are one actor-scope × verb × tail grammar (`player_event_head.py`). "whenever A or
#: B" and "when X and at the beginning of Y" split into independent triggers sharing the body
#: like "and whenever" always did (an "or" whose right half carries a tail that qualifies both
#: — "…from anywhere other than your hand" — is refused). Two wrong-but-modeled families
#: found on the way: "`<A>` if `<C>`. Otherwise, `<B>`." attached B to *"you didn't win a
#: clash"* whatever C was (Gravelighter, Stolen Vitality, Unholy Annex, …) — it is now one
#: `if_else` deciding C once, and unclaimed when nothing before it carries a gate — and "If
#: `<C>`, `<A>` and `<B>`." gated only A. Insatiable Appetite, Pippin's Bravery and Lorehold
#: Excavation lose their (wrong) coverage until their else branches are modeled. Bodies
#: reading "that many"/"that creature" off the shared attack event stay unclaimed.
#: v457: under a group trigger "it gets +N/+N [and gains K] until end of turn" pumps the object
#: that fired it (`PumpEffect.trigger_subject`, +13) and a spell's "when you next cast an
#: instant or sorcery spell this turn, copy that spell" is a one-shot turn trigger with
#: `copy_spell` reading the cast event (+7).
#: v458 (ENG-47): "can't be countered this turn" is a rule, not a trigger on the cast —
#: "spells you control can't be countered this turn" (Veil of Summer), "creature spells you
#: cast this turn can't be countered" (Domri) and "the next `<type>` spell you cast this turn
#: can't be countered" (Mistrise Village, Insist, Overmaster) are one `cant_be_countered_this_turn`
#: effect recording an `UncounterableGrant`, so it also covers a spell already on the stack. A
#: turn-long "whenever `<event>` this turn, `<effect>`" is now also a *sentence* of a larger body
#: (after an "if C," gate — Ruinous Waterbending — or a first sentence), not only a whole line.
#: v459 (ENG-47): three more turn-history condition phrases join "gained life"/"card left
#: graveyard" — "you descended this turn" (RULE 700.11, a permanent card reaching your
#: graveyard; a token dying does not count), "you created a token this turn", "you committed a
#: crime this turn" (RULE 700.13, a new `CRIME_COMMITTED` event fired wherever a spell/ability
#: is put on the stack targeting an opponent, their permanent, or a card in their graveyard).
#: A phase trigger's own leading "if `<state>`," now reads through the shared
#: `static_condition` vocabulary generally, not one regex per phrase (Celebration's "if two or
#: more nonland permanents entered the battlefield under your control this turn", the source for
#: most of this version's new coverage). Also folds `GameState.spell_watchers` into the ordinary
#: `create_turn_trigger`/`UncounterableGrant` machinery (Dual Strike's hand-authored entry is
#: retired — it now parses) and retires ~30 per-effect `amount_from_*`/`count_from_*`/
#: `amount_if_*` constructor parameters across draw/discard/mill/scry/gain_life/lose_life/
#: add_counters/pump/create_token/copy_permanent/bolster/earthbend/discover/prevent_damage/
#: taxed_draw in favour of one `effect_amounts` operand per magnitude (`GameEffect._measured`,
#: `game/effects/operands.py`) — no coverage change on its own, but real cards previously wired
#: through a hand-authored fused flag now go through the shared `bind` node instead
#: (Solitude, Doomsday, Final Punishment, Peer into the Abyss, Esper Sentinel, Tavern Brawler,
#: Emiel the Blessed, Burning Curiosity, Rousing Refrain, Jeska's Will, Carpet of Flowers,
#: Rootha, Spoils of Blood).
#: v464 (MEC-99): "you may choose to have it deal damage equal to its power to `<target>`. if
#: you do, it assigns no combat damage this turn." (Gaze of Pain's own turn-scoped trigger
#: body) reuses `effects.DamageEqualToPowerEffect`'s existing subject vocabulary (a new
#: ``"trigger_subject"`` implicit dealer, resolved off `GameContext.trigger_event` the way
#: every other RULE 603.1 group-subject referent already is) plus a widened
#: `PreventCombatDamageDealtEffect` (RULE 510.1e's "assigns no combat damage", previously
#: only reachable as Loafing Giant's own self-only "~" form) — no new engine primitive, only
#: recognition, +1. Fixes a real, previously-unreachable gap along the way:
#: `OptionalEffect.apply` only ever captured the RULE 603.1 referent needed to *resume*
#: correctly (`context.trigger_event`) when the referent was also who gets *asked* ("its
#: controller may …"); a body needing that referent under a plain "you may" (this card's own
#: shape — the controller is asked, but the body still has to act as the attacker) silently
#: resolved against no trigger subject at all once the interactive choice came back. Now
#: captured whenever `context.trigger_event` names one, regardless of who's asked.
#: v475 closes PAR-120's "sum-based counts" item — "creatures you control have
#: total power N or greater/less" as a standing condition (RULE 613.6/603.4)
#: across all four surfaces (leading "if", trigger "while" tail, trailing
#: "if", "activate only if"). No new engine primitive: `continuous.
#: count_selector`'s own `total_power_creatures_you_control` branch already
#: existed (PAR-60), and `static_conditions.py`'s `control_count` kind
#: already calls `count_selector` generically for any selector name — a
#: min/max threshold on a *sum* needs no new condition kind. Two new regex
#: rows: `static_handlers._STATIC_CONDITION_RES` (covers three of the four
#: surfaces) and `handlers._ACTIVATION_CONDITION_RES` (the separate,
#: narrower "activate only if" vocabulary, which doesn't fall back to
#: `static_condition()`). +91, 0 regressed.
#: v476 closes PAR-120's combat-scoped "total power" sibling — "you attacked
#: with creatures with total power N or greater this combat" (the Onslaught-
#: block "Pack tactics" cluster: Gnoll Hunter, Hobgoblin Captain, Intrepid
#: Outlander, Minion of the Mighty, Targ Nar, Demon-Fang Gnoll). Same
#: `control_count` condition kind as v475's board-wide sibling; only
#: `continuous.count_selector` needed a new selector,
#: `total_power_attacking_creatures_you_control`, scoped to `GameObject.
#: attacking` the way `attacking_creatures_you_control` scopes a plain
#: count. The leading "if" on an ATTACKS trigger already falls back to the
#: shared `static_condition()` vocabulary generically, so one new regex row
#: closed the whole cluster at once. +5, 0 regressed.
#: v477 closes PAR-120's mana-symbol sibling of Adamant's own condition —
#: "if `<mana symbol[s]>` was spent to cast it/this spell" (Catharsis,
#: Deceit, Emptiness, Gruul Scrapper, Ogre Savant, Shrieking Grotesque,
#: Steamcore Weird, Tin Street Hooligan, plus 9 bonus cards sharing the same
#: shape outside the original search). No new engine primitive:
#: `GameObject.mana_by_color_spent_to_cast` and the `mana_color_spent_to_
#: cast_at_least` condition kind both already existed (PAR-95, Adamant's own
#: word-form "if at least N `<color>` mana was spent to cast it") — one new
#: regex recognizing the printed-symbol spelling, one or two repeated pips
#: of the *same* colour enforced via a backreference (a mixed pair like
#: "{r}{g}" is a different, unclaimed shape, left open). +17, 0 regressed.
#: v478 recognizes "you control your commander" (RULE 903.4 — the "Loyal"
#: Commander-legends cycle's phase-trigger leading "if"): a new
#: `commanders_you_control` selector on `continuous.count_selector`, read
#: through the same `control_count` condition kind every board-existence
#: check in this ticket has reused. Loyal Apprentice, Loyal Drake, Loyal
#: Guardian, Loyal Subordinate, Skyhunter Strike Force, Tyrant's Familiar.
#: The cycle's "as long as" static form (Angelic Field Marshal and three
#: siblings) needs a separate, unrelated primitive — a self-pump-plus-
#: group-grant compound body `static_effect_specs` doesn't recognize at all
#: yet — left open. +6, 0 regressed.
#: v479 closes PAR-120's "that player has N or fewer/no cards in hand"
#: phase-trigger cluster — "at the beginning of each opponent's/each
#: player's `<step>`, if that player has …, `<effect>`" (Asylum Visitor,
#: Davriel Rogue Shadowmage, Ghirapur Orrery, Hellfire Mongrel, Hollowborn
#: Barghest, Lavaborn Muse, Paupers' Cage, Shrieking Affliction). "That
#: player"/"they" is whoever's step just began (RULE 502.1's active
#: player) — a new `static_conditions.py` kind,
#: `active_player_cards_in_hand_at_most`, since the existing
#: `cards_in_hand_at_most` always reads the ability's own controller, the
#: wrong player for this per-opponent trigger shape. Kept phase-trigger-
#: only (not folded into the shared `static_condition()` table) since an
#: activated ability's own "that player" means something else entirely
#: (Nezumi Shortfang's previously-targeted opponent) — a shared row would
#: have silently misread it. The effect bodies ("they lose N life", "that
#: player draws N cards") needed no new engine primitive at all:
#: `effect_operands.PLAYER_SCOPES`'s existing `"active_player"` scope
#: string already resolves generically through `DrawCardEffect.player`/
#: `LoseLifeEffect.player`. +8, 0 regressed.
#: v480 gives `static_conditions.py`'s own evaluator the `any` (OR)
#: combinator `effect_conditions.py` already had for the resolution-time
#: vocabulary — a static's "as long as …" `active_if` and an "activate only
#: if" gate call `static_conditions.condition_holds` directly, bypassing
#: `effect_conditions.py` entirely, so a `{"kind": "any", ...}` condition
#: had nowhere to be evaluated for either surface no matter how well
#: `static_condition()` recognized the phrase. `static_condition()` also
#: gained a generic "`<A>` or `<B>`" fallback (split on the first " or ",
#: recurse both halves, build the combinator only if both independently
#: resolve — fails closed on a non-disjunctive "or" the same way an
#: unrecognized condition always has). First real use: "you control a
#: desert or there is a desert card in your graveyard" (Desert's Hold, Earth
#: Rumble Wrestlers, Gilded Cerodon, Sidewinder Naga, Solitary Camel,
#: Unquenchable Thirst, Wall of Forgotten Pharaohs, Wretched Camel). +8, 0
#: regressed.
#: v481 closes the real architectural duplication PAR-120 has flagged at
#: each of this session's earlier "activate only if" additions (commander,
#: total power, the desert compound) without ever fixing:
#: `catalogue.handlers._activation_condition_dict` now falls back to
#: `static_handlers.static_condition()` once its own closed table declines,
#: instead of gaining one more hand-copied row per phrase. Every existing
#: row's own kind spelling is preserved exactly (tried first, unchanged),
#: so this is zero behaviour change for an already-shipped card — only a
#: phrase genuinely new to *both* tables reaches the shared vocabulary for
#: the first time. Also fixed a stale test pin
#: (`test_par10_activation_conditions.py`) that had documented "activate
#: only if you control a Plains" as deliberately unrecognized tail work —
#: it now correctly resolves via the shared count-phrase grammar, same as
#: "as long as you control a Plains" already did. +59, 0 regressed.
#: v482 completes PAR-120's P/T-CDA arithmetic: shared amount phrases now
#: cover sums, multipliers, offsets, card-type unions, mana-value aggregates,
#: counters on the source, and the Lhurgoyf "that number plus 1" form.
#: v483 extends PAR-120's shared condition vocabulary with turn histories,
#: opponent poison, Treasure-sourced cast mana, and attacked/died cost counts.
#: v484 finishes PAR-120 batches 2–4 around that vocabulary: the effect-only
#: "the Nth time this ability has resolved this turn" gate (and its "if it's
#: the second time" ladder); one "costs {N} less for each `<count phrase>`"
#: row replacing five per-phrase rows; "that many"/"where X is the number of
#: counters it had" behind a leaving-counter gate; "all creatures you
#: control"; "you control an X and a Y"; X in "put X counters"; "it" after
#: create/manifest re-pointed off the source; devotion spelled as mana
#: symbols and "differently named". Refuses "sacrifice X" costs and "pay {X}.
#: If you do, put X counters", neither of which the engine can charge.
#: v485 is PAR-120 batch 6 plus PAR-128. Batch 6: every "the number of `<word>`
#: you control" emitter reads the shared count grammar (Beacon of Creation,
#: Avenger of Zendikar, Basilisk Gate, Nomads' Assembly … had counted
#: *creatures* typed Forest/land/Gate/creature — always 0); one sentence-wide
#: "where X is" binds both "deals X … and gains X"; the pump-X and bolster-X
#: phrase tables became the shared amount vocabulary; Kutzil's Flanker reaches
#: MEC-84's left-battlefield count. PAR-128: the controller scope and "another"
#: are slots of the shared target grammar, verbs read their kind whitelists
#: through `target_kind_allowed`, "artifact or enchantment" is no longer any
#: permanent, "If `<cond>`, A, then B" gates both halves, and "each player /
#: each opponent / target opponent `<verb>`" is a player-subject slot.
#: 496 (PAR-120): targeted "instead" overrides (magnitude `bind` or a
#: same-target `if_else`), Infusion/Addendum paragraph joins, animate-with-
#: quoted-CDA, Angry Mob's turn-split CDA, and the Addendum / Treasure-
#: activation / "gained N life" conditions.
#: 497 (MEC-98): Alchemy "perpetually gets/gains" — the pump table re-used via
#: an until-end-of-turn rewrite, plus "creature cards in your hand/library/
#: graveyard" subjects (`handlers._perpetual_pump_specs`).
#: 498 (PAR-120 close): first-draw reveal triggers (Primitive Etchings,
#: Rowen), turn-scoped spell cost reductions (Rowan, Scion of War; the "next
#: spell" family), Ochre Jelly's delayed split copy, "for each … counter on
#: ~", and a cost-paid source's "if it had N counters" (Lost Isle Calling).
#: 499 (ENG-48/ENG-49): "you may pay {X}. If you do, put X counters" is claimed
#: again (the choice now announces X); an activated ability's cost is read by
#: `catalogue.cost_text.scan_cost_text` — the grammar `game/costs` charges
#: from — and a line with any unread cost fragment is left unclaimed instead
#: of claimed cheaper than printed. The grammar gained "Sacrifice X/N
#: `<type>s`", "an artifact or creature", typed/random discards, graveyard
#: exiles, "Exile this card from your graveyard" and "Return ~ to its
#: owner's hand".
#: 500 (ENG-51): the cost grammar reads qualified/"another" sacrifices, counters
#: removed from another permanent or of any kind, exert, mill, "discard another
#: card named ~", typed graveyard exiles, qualified tap-others, returning N
#: lands, half your life, "tap enchanted creature"; a text the grammar reads
#: completely counts as a cost even without a symbol the lexical sniff keys
#: on; "`<cost>` or `<cost>`:" becomes two abilities; Springjack Pasture's
#: announced-X mana line is claimed.
#: 501 (PAR-112/PAR-127): a leading "for each `<count phrase>`, `<body>`" iterates
#: objects (the body's "it" is the loop item — Ocelot Pride, Chief Magistrate of
#: Mercadia); count phrases read "that entered this turn"; a multi-sentence phase
#: trigger's leading "if" is the ability's RULE 603.4 intervening-if; "target
#: creature or planeswalker [you don't control]" keeps its planeswalker half.
#: 502 (PAR-119 a): "whenever one / N or more `<objects>` enter / die / leave the
#: battlefield" is a RULE 603.2c batch head (`EVENT_BATCH`) — the per-object
#: `_BATCH_DIES`/`_BATCH_ENTER` rows are gone; "that many" off a counting head binds X;
#: typed "one or more creature cards leave your graveyard".
#: 503 (PAR-119 a): "you discard `<n>` or more [`<type>`] cards" is a DISCARD_CARD batch.
#: 504 (PAR-119 a): "`<n>` or more `<creatures>` deal combat damage to `<a player>`" is a
#: head over the combat-damage aggregate; "ninja or rogue creatures" shares its noun.
#: 505 (PAR-119 c): "`<a card>` is put into `<whose>` graveyard [from `<origin>`]" and its
#: "N or more … are put into" batch — `PUT_INTO_GRAVEYARD`, detected per arrival.
#: 506 (PAR-119 d): "[that player] add(s) one mana of any type that land produced"
#: (`mirror_produced_mana` + player operand), a mana-only `TAPPED_FOR_MANA` body is a RULE
#: 605.1b mana ability on the composed head too, "that land doesn't untap …" = event land.
#: 507 (PAR-119 a): "`<player>` sacrifice(s) 1 or more [other] `<permanents>`" is a SACRIFICE
#: batch (cost payments are one scope); "1 or more players" is an actor.
#: 508 (PAR-119 a): "for each of them, …" under a batch head iterates its matched members.
#: 509 (PAR-119 a): "leave(s) the battlefield without dying" (LEAVES_BATTLEFIELD ``to_zone``),
#: "enter … without being played" (a played land's ``played``), "under an opponent's control".
#: 510 (PAR-119 a): subject qualifiers "goaded", "face-down" (new `matches_object_filter`
#: keys) and "that entered [the battlefield] this turn" in the shared noun-phrase grammar.
#: 511 (PAR-119 migration): the four per-adjective group rows are the composed head,
#: translated to their flat keys (`legacy_condition`); head verbs gained the legacy
#: object events; "put into your graveyard from the battlefield" keeps its owner scope.
#: 512 (PAR-130 a): the "target `<X>` that player controls" slot, antecedent-checked against
#: the trigger head (`_that_player_antecedent_ok`), and a trigger's per-player rounds.
#: 513 (PAR-130 b): a spell's "for each opponent/player" gathers per-player rounds at cast
#: time (`targeting.spell_target_rounds`), "for any number of opponents" (declinable
#: rounds), and the no-duration "gain control of target `<permanent>` [. untap it]".
#: 514 (PAR-130 close): activated-ability per-player rounds; a prior target's player/
#: controller as antecedent; antecedent-gated "that much damage"; generic target-choice
#: announcements and the optional "have it deal" causative normalization.
#: 515 (PAR-131): the legacy cast / damage / damage-recipient / becomes-target / batch-
#: attack / player-event trigger rows are retired onto the composed heads (flat keys →
#: ``spell_filter`` / ``spell_cast_from`` / ``condition.filter``; compound player events
#: as one event list); a self/attached DAMAGE subject's recipient ("to an opponent", "to
#: a creature") is a trigger-level gate; regranted triggers carry the composed keys.
#: 516 (PAR-131 close): a compound "`<A>` or `<B>`" trigger head becomes one ability
#: per head when no event can satisfy both; "is put into exile from the battlefield"
#: (LEAVES_BATTLEFIELD ``to_zone``); "`<phrase>` or a `<phrase>`" noun unions
#: (``any_of``); "with disturb"; "~ or another …" on the DAMAGE head.
#: 552 (PAR-123 close): a group trigger's "it"/"that `<noun>`" is the firing object for *every*
#: effect — a clause no row claims is read through the effect's previous-subject row, its
#: targeted spelling ("destroy it" as "destroy target permanent"), or a second-person spelling
#: run as the object's controller ("its controller creates …"), behind a
#: `trigger_subject_referent`; a payment's "if you do" reads the remembered object; conditions
#: ("if it has flying / was attacking / has a counter"), amounts ("equal to that creature's
#: power", "that many"), counts ("for each creature blocking it", "…shares a creature type with
#: it"), target filters ("with the same mana value", "other than that creature") and "the
#: player or planeswalker it's attacking" name it too; "that card" on a dies trigger; a
#: pronoun after a "~" clause is the source (Fearless Fledgling no longer flies the land).
#: 553 (MEC-106/MEC-107): Gift is a closed parametric keyword with promised/not-promised
#: conditions, cast-decided branch targets, override and suffix forms, plus the give-a-gift
#: player-event head; Expend is a numeric player-event head. Gift's real-card residue also adds
#: multi-target graveyard returns with a mana-value cap, an elliptical target+mass damage clause,
#: and the chosen-pair "the creature you control" counter referent.
#: 554 (MEC-105): temporary flag-keyword loss, including gain/loss and P/T/loss
#: compounds, plus the standing attached-permanent P/T-and-loss form.
#: 555 (PAR-134 + PAR-129, both wrong-but-MODELED fixes): a scope adjective that isn't a creature
#: subtype — state (tapped/untapped/nonattacking), supertype/designation (legendary/nonlegendary/
#: snow/commander), nontoken, multicolored, modified (RULE 700.9), historic (RULE 700.6), a
#: "non<colour/type/subtype>" negation — is a `matches_object_filter` dict (`subgrammars.
#: scope_adjective`) shipped as the static's ``object_filter`` param (and merged into a target /
#: blocker filter) instead of ``subtype: "Tapped"``; a coordinated list ("Ninja and Rogue
#: creatures", "snow and Zombie creatures", "saproling creatures and other treefolk creatures")
#: is an ``any_of``; "Commanders you control" scopes every permanent. A "Keyword — <ability>"
#: line (Exhaust/Power-up/Boast/Max speed/Solved) whose body isn't modeled is UNMODELED instead of
#: an inert keyword-line claim (23 cards lost a real ability). Net: +2 covered (General's
#: Enforcer, Kashi-Tribe Elite), -24 honestly UNMODELED.
#: 556 (MEC-108): RULE 122.1b keyword counters — the thirteen keyword kinds join the named-counter
#: whitelist (single/group "put a flying counter on …", "remove a menace counter from ~"), a
#: compound list ("a +1/+1 counter and a lifelink counter on target creature", one `add_counters`
#: per kind, later ones reading the first's target), "your choice of a … counter or a … counter"
#: (`add_counters.kind_options`, and the as-it-enters `choose_enter_counter`), "enters with a
#: +1/+1 counter and a flying counter" / "…a first strike counter" (`extra_counters`), and
#: "return … to the battlefield with a `<keyword>`/+1/+1 counter on it".
#: 557 (PAR-140): counter-placement residue — "put a `<kind>` counter on **a** creature you control"
#: (`add_counters.choose_one` over a group selector, a recipient choice at resolution); a negated counter
#: condition ("if ~ doesn't have a flying counter on it", "has no +1/+1 counters on it" → `source_counters`
#: ``max: 0``) and a "without a `<kind>` counter on it" group filter (`without_counter_kind`; the mass
#: destroy/exile/return rows' group class now admits "+1/+1"); "it/~/target `<permanent>` becomes a
#: `<subtype/type>` in addition to its other types [until end of turn]" (a `grant_until` over a layer-4
#: `type_change`, permanent = `rest_of_game`); "you may remove a `<kind>` counter from ~/it. When/If you do,
#: …" (`pay_cost_then` whose cost comes off the source, `RulesEngine._source_counter_removal`).
#: 564 (PAR-135 + PAR-121): the named-counter kind is an open axis (`_NAMED_COUNTER_KIND` = any word minus
#: `_RESERVED_COUNTER_KINDS`; `stun`/`shield` are engine-enforced, RULE 122.1c) and an asymmetric "+0/+1" counter
#: is its own kind rather than a +1/+1 (layer 7c); "any target that isn't a `<subtype>`/commander" (a quality-tail
#: slot + `creature_filter` on the `any` pool); "Do this only once each turn." as an *action* limit (a `seq` gated
#: by `action_unused_this_turn`, with an `action_stamp` where the optional action is accepted — `spec.
#: fold_action_limit`); "double its/target creature's power" (`PumpEffect.self_multiplier_stat`, group/attached
#: pronoun rows); additive colours ("a black Zombie in addition to its other colors and types" — a layer-5 `color`
#: static, and `CopyPermanentEffect.add_colors`); "target Equipment" as a target kind and `attach_chosen` from
#: oracle text (chosen or implicit destination); "if it's tapped" after a targeting clause reads that pick, and
#: "tap enchanted creature. … on it" reads the host; "has N or fewer `<kind>` counters" is an upper bound, and the
#: kindless "has four or more counters on it" counts every kind (both used to read "or more" as a counter's name,
#: a condition that never held). PAR-121 consolidated (0 of 39,639 clause readings changed): one verb × subject
#: table, one certain-antecedent connective, one targeted-damage shape, one strict-subset row deleted.
#: 572 (PAR-99): "spells `<you|your opponents>` cast that target `<X>` cost {N} more/less (or an additional N life)
#: to cast" — one row over the targeted-spell tax: ``~`` is ``targets_source``, anything else the ``if_targets``
#: OR-list (``you``, a card type, ``commander``, all scoped by "you control" to the static's controller), the life
#: form is ``cost_reduction.life`` (`continuous.cast_life_tax_for`); `cost_reduction` joined the named-choice
#: static whitelist (Monastery Siege's Dragons).
#: 573 (PAR-111): Exploit as a real mechanic — the keyword's ETB "you may sacrifice a creature" (`ExploitEffect`, the
#: ``exploit`` choose-action) and `EventType.EXPLOITS`, read by the "~ / a creature you control exploits a `<kind>`
#: creature" trigger head (`object_trigger_head._parse_exploit_head`); a *grant* of exploit stays unclaimed
#: (`keywords.UNGRANTABLE_FLAG_KEYWORDS`). "you may have that player lose N life" under a group trigger; "attach it
#: to target legendary creature you control" (the destination's `creature_filter`); "manifest dread, then attach ~ to
#: that creature" (`created_objects` handed across the look-at-two pause).
#: 576 (PAR-104): the Mutagen token (`data/tokens.json` + `_NAMED_TOKEN_WORDS`); a comma list of card types in a cast
#: trigger ("an artifact, instant, or sorcery spell"); Donatello's "those tokens plus a Mutagen token are created
#: instead" (`additional_named_token`, any named token); "a `<named>` token for each +1/+1 counter on it" under a group
#: trigger (the `counters` amount reads the leaving creature's snapshot); and the shared pool "target artifact,
#: enchantment, or creature [with flying / power N or greater]" (`artifact_creature_or_enchantment`, the quality on its
#: creature members only — `TargetFrame.creature_filter_creatures_only`). The unqualified three-type phrase now gets
#: that pool instead of the broad "permanent" (which also offered lands), so the library-put and exile-until-leaves
#: rows that took "permanent" for it (Banishing Stroke, Banishment Decree, Trapped in the Screen) name it too. A
#: "Solved —" / "Max speed —" gate on a *replacement* is its `active_if` (it used to append an activation marker that
#: could not bind — Case of the Pilfered Proof), and a two-event group trigger binds (`_subject_event_key`).
#: 578 (PAR-107…114 run 2): an "either/or" additional cast cost with no mana half (`additional_cost["either"]`,
#: `ActivationCost.either_alt` — Bone Shards, Final Payment, Souls of the Lost) plus a compound single sacrifice type
#: ("a creature or enchantment"/"or land"/"a permanent") and "tap an untapped artifact you control or pay {1}";
#: `reveal_hand_choose_discard` with a pick `count`/`up_to`/`destination` ("look at target player's hand and choose X
#: cards", library top / third from the top); "During turns other than yours, `<static>`" (`not_your_turn`) and its
#: gated self-animation; the Visions flashback discount (`source_in_graveyard`); Magmaquake's "and each planeswalker",
#: Inflame's `damaged_this_turn` group filter and Cinderclasm's kicked "instead" on a mass hit.
#: 579 (PAR-113 kept mana): "add X / that much / N mana in any combination of colors | {R} and/or {G}", "add that much mana
#: of any 1 color" and "add {R} or {G}" (`add_mana` ``"ANY"`` narrowed by ``any_color_choices``; a fixed N is N single
#: picks); "that much" under "whenever one or more creatures you control attack" now measures `ATTACKERS_DECLARED` via a
#: `bind` (it read `PLAYER_ATTACKED`, which carries no amount, so "gain that much life" gained 0), and a group-filtered
#: head of that kind fails closed.
#: 580 (PAR-113): "whenever a player / an opponent attacks [with N or more creatures]" is `ATTACKERS_DECLARED` (once per
#: declaration, not once per defender) with the actor scope (`player_event_head._PLAYER_ATTACKS`); "each of your opponents"
#: is the `each_opponent` damage selector.
#: 581 (PAR-107/108/110 singletons that were one row away): "with an additional +1/+1 counter" on a graveyard return;
#: "counter target instant spell, sorcery spell, activated ability, or triggered ability" (the `spell_or_ability`
#: pool with a spell filter); "defending player mills half their library" (`MillEffect` ``defending_player``);
#: "return all `<types>` cards from all graveyards … under their owners' control"; "If its/that permanent's mana
#: value was N or less, …" after a targeting clause (the printed mana value only — power, toughness and keywords are
#: last-known information), with "return it" bound to that pick (`ReturnSelfToBattlefieldEffect` ``previous_target``);
#: "put enchanted creature into its owner's library third from the top"; and the mass "exile all/each `<group>` until ~
#: leaves the battlefield" (the exile links every card it took, `linked_exile_ids`).
#: 582 (PAR-107/108/110/113 run 3): a body that speaks of "that attacking player" / "they" under a player-attack head
#: runs *as* that player (`trigger_subject_referent` ``acting="event_player"``), with the heads "attacks you / enchanted
#: player / 1 [or more] of your opponents" (`defender_is_*`; Curses, Jolene, Ellie, Everett) and "instead create those
#: tokens plus an additional Treasure" (`additional_named_token` ``only_token``); "a card that has an adventure" as a
#: graveyard-return target, an "as long as you own a card in exile …" condition and a group enters-with-counter filter;
#: "~ deals N damage to each `<group>` and an additional M damage to each `<group>`"; "the number of colors of mana
#: spent to cast this spell"; "lose X life" (also the whole "lose life equal to …" family it unlocked). Bug fixed on
#: the way: in "target player gains 3 life and draws a card" the second verb acted on the controller — it now acts on
#: the player the first clause chose (a verb with no such reading refuses the sentence), and a shared "where X is …"
#: with a sacrificed/greatest term binds both halves.
#: 583 (same batch, second increment): "if {w} was spent to cast this spell" (the hybrid cycle: Firespout, Dawnglow
#: Infusion, Invert the Skies, Unnerving Assault, Revenant Patriarch …), "`<A>` if … and `<N>` damage/life `<B>` if …"
#: (the second conjunct repeats only the amount noun), "you may have target creature get -2/-2" (14 cards),
#: "creatures target player controls get +N/+N" (`PumpEffect` ``group_player``), "`<player>` skips their next untap
#: step / draw step / combat phase" (`SkipNextStepEffect` for another player; a skipped phase skips all its steps),
#: "N damage to any target and M damage to you", and a "plus the number of" sum after "where X is".
#: 584: an enters trigger's "if {W} was spent to cast it" is a true RULE 603.4 intervening-if (`trigger["active_if"]`,
#: checked once at trigger time — Revenant Patriarch no longer asks for a target when white was not spent).
#: 585: Surge (RULE 702.117) is an engine mechanic — "if its / this spell's surge cost was paid" reads
#: `GameObject.surge_cost_paid` as an enters-trigger intervening-if and as a resolving-spell condition
#: (Reckless Bushwhacker, Tyrant of Valakut, Crush of Tentacles; 3 cards).
#: 586: PAR-145 — Sticker Sheets are NEVER_SUPPORTED by their type line,
#: including sheets whose oracle text contains only ticket symbols and stats.
#: 587: the "remove N counters from among …" cost reads a list of types and "other" ("from among other
#: artifacts, creatures, and planeswalkers you control", Tekuthal, Inquiry Dominus) —
#: `ActivationCost.remove_counters_other` + a `a_or_b_or_c` permanent word.
#: 588: "remove N counters from an artifact or creature you control" — the one-holder phrase takes an "or"
#: pair (Moxite Refinery), encoded as the `artifact_or_creature` permanent word.
#: 589: "enters with a number of +1/+1 counters on it equal to the amount of mana spent to cast it"
#: (Kurbis, Harvest Celebrant) -> entry-counters condition ``mana_spent_scale``.
#: 590: "As ~ enters, roll X d6. It enters with a number of +1/+1 counters on it equal to the total of those
#: results." (Neverwinter Hydra) -> entry-counters condition ``roll_x_dice_sides``.
#: 591: "~ enters with a number of +1/+1 counters on it equal to the number of land cards in all graveyards"
#: (Centaur Vinecrasher) -> entry-counters condition ``land_cards_in_graveyards``.
#: 592: PAR-100 active-player phase bodies, plural additional draws, other-player
#: scopes, optional draw/tax, hand-to-library ordering and draw/life prohibitions.
# MEC-110: Empower Jace, including quantities bound by the shared X grammar.
# 595: optional discard-up-to/draw-the-discarded-count shared grammar.
# 596: instant/sorcery storm grants (Prismari and Ral's emblem).
# 606: PAR-128 — separate source-excluded land targets from ordinary land targets.
# 605: MEC-109 — complete Blitz costs, restricted graveyard casts and grants.
# 607: PLAY-ALL — "counter target activated or triggered ability" as its own clause (Sublime Epiphany's mode).
PARSER_VERSION = "607"


def parser_source_hash() -> str:
    """SHA-1 over every front-end `.py` file's path + bytes, sorted for
    determinism.

    Exists so a stale-coverage measurement (`PARSER_LONG_TAIL.md`'s own
    documented failure mode: "measuring twice within one batch... silently
    reuses the first run's rows" when `PARSER_VERSION` isn't bumped) is
    structurally detectable rather than a discipline someone has to
    remember. `test_parser_version_lock.py` pins this hash, for the current
    `PARSER_VERSION`, in the checked-in `PARSER_VERSION.lock` file — any
    front-end edit that changes this hash without a matching lock-file
    update (via `scripts/update_parser_version_lock.py`) fails that test.
    Deliberately *not* used as `PARSER_VERSION` itself: coverage-ledger rows
    are keyed on `PARSER_VERSION` (`services/coverage_db.py`), and a version
    that changes on every edit — including comment-only ones — would
    invalidate all ~34k rows for edits that never touch parse behavior.
    """
    root = Path(__file__).resolve().parent
    files = sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)
    digest = hashlib.sha1()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


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
    #: `card_registry.specs_for` actually binds it for an unregistered
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
    `docs/implementation-state/DEFERRED.md`), not merely deprioritized. A simple
    substring check is deliberate: real sticker cards say "sticker sheet"/
    "sticker" in their own oracle text (there is no other card-text idiom
    that uses the word), so this never needs the segmenter/normalize
    machinery to decide — it's an early exit, not a parsed clause.
    """
    return "sticker" in raw.lower()


#: RULE 207.2c: an *ability word* ("For Mirrodin!") has no rules meaning of
#: its own — the reminder text immediately following it *is* the actual
#: ability, unlike a keyword's reminder text (which merely restates a
#: standing rule the engine already knows). `normalize` unconditionally
#: strips every parenthetical as reminder text (`_REMINDER`), which would
#: silently discard this ability word's entire rules text before the
#: segmenter ever sees it — the same "read it before normalize strips
#: parentheticals" problem `game/dungeons.py`'s room-arrow parsing solves by
#: staying outside this pipeline entirely. "For Mirrodin!" instead only
#: needs its *one* fixed reminder-text body promoted to real, ordinary
#: oracle text (9 SOLO cache cards, MEC-28 — all print the identical
#: wording, RULE 207.2's ability-word reminder text is never
#: card-specific), so it's cheaper to rewrite the raw line in place than to
#: build a second raw-text-reading subsystem for one template: "when this
#: Equipment enters, create a 2/2 red Rebel creature token, then attach
#: this to it." then flows through `normalize`/`segment_line` exactly like
#: any other printed ETB trigger (`handlers._CREATE_TOKEN_AND_ATTACH_RE`
#: already covers the create-and-attach body once it's real text again).
_FOR_MIRRODIN_RE = re.compile(
    r"For Mirrodin! \((?P<reminder>[^()]*)\)", re.IGNORECASE,
)


def _expand_ability_word_reminders(raw: str) -> str:
    """Promote known ability-word reminder text to real oracle text, before
    `normalize` strips every parenthetical (see `_FOR_MIRRODIN_RE`)."""
    return _FOR_MIRRODIN_RE.sub(lambda m: m.group("reminder"), raw)


#: An ability-word paragraph that continues a spell's previous instruction
#: (see `parse_oracle`): only after a sentence end, only a leading "If".
_SPELL_RIDER_PARAGRAPH_RE = re.compile(
    r"(?<=\.)\n(?:Infusion|Addendum) — (?P<rider>If )", re.I,
)


def _is_spell(card: Any) -> bool:
    return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))


def _split_triggered_modal_block(
    lines: list[str], start: int, provenance: ParserProvenance
) -> Optional[tuple[dict[str, Any], bool, bool, bool, bool, int, list[str], int]]:
    """A permanent's modal *triggered* ability: "When ~ enters, choose 1 —"
    on one line, then two or more "• " mode lines (RULE 700.2 wrapped in a
    RULE 603.1 trigger) — the trigger-wrapped sibling of `split_modal_block`
    (a modal *spell*'s bare header). A recognised trigger wrapper and a modal
    header are both required; unlike a plain triggered ability's body, the
    modal header's "effect" is the whole bullet block, not `trig.group("body")`
    itself.

    The trigger wrapper is recognised by segmenting ``"<wrapper>, draw a
    card."`` as an ordinary triggered line and lifting its whole ``trigger``
    dict — the *same* grammar `segment_line` uses, not the narrow generic
    `_trigger_event`/`_trigger_condition` pair — so every cast-spell / damage
    / nth-event / phase-step / combined-event trigger a plain triggered
    ability would claim also drives a modal block (Elder Gargaroth, Ojutai
    Exemplars, Etherwrought Page, Cosmogrand Zenith, …).

    Returns ``(trigger, or_both, or_more, repeatable, exhausted, choose, mode_bodies, next_index)``,
    or ``None`` if ``lines[start]`` isn't this shape at all, its wrapper
    isn't a recognised trigger, or ``choose`` exceeds the number of mode
    lines actually printed — fail-closed, the caller falls back to ordinary
    per-line segmentation.
    """
    trig = _TRIGGER_RE.match(lines[start].strip())
    if trig is None:
        return None
    modal_body = trig.group("body").strip()
    header = MODAL_HEADER_RE.match(modal_body)
    conditional = CONDITIONAL_MODAL_HEADER_RE.match(modal_body)
    if header is None and conditional is None:
        return None
    override = (
        conditional_modal_override(conditional.group("condition"), conditional.group("choice"))
        if conditional is not None else None
    )
    if conditional is not None and override is None:
        return None
    probe = segment_line(
        lines[start].strip()[: trig.start("body")] + "draw a card.",
        allow_spell_effect=False,
        provenance=provenance,
    )
    if not probe.claimed or probe.spec is None or probe.spec.ability_kind != "triggered":
        return None
    trigger = probe.spec.trigger
    if not trigger or trigger.get("event") is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    mode_bodies, next_i = collected
    choose = int((header or conditional).group("n"))
    if choose < 1 or choose > len(mode_bodies):
        return None
    return (
        trigger,
        bool(header and header.group("or_both")),
        bool(header and header.group("or_more")),
        "same mode more than once" in modal_body.lower(),
        bool(header and header.group("exhausted")),
        override,
        choose,
        mode_bodies,
        next_i,
    )


_REFLEXIVE_MODAL_RE = re.compile(
    r"^you may pay (?P<cost>[^.]+)\.\s*when you do,?\s*(?P<header>choose .+)$"
)


#: RULE 706.1 roll header, optionally wrapped in a RULE 603.1 trigger — the
#: line that a RULE 706.3a results table hangs off. ``pre`` is the trigger
#: wrapper ("when ~ enters, " / "whenever ~ attacks, "), lifted the same way
#: `_split_triggered_modal_block` lifts a modal block's wrapper: segment
#: "<pre>draw a card." and take its `trigger` dict.
_DICE_TABLE_HEADER_RE = re.compile(
    r"^(?P<pre>(?:when|whenever|at)\b[^,]*,\s*)?"
    r"roll (?:a|(?P<count>two|three|\d+)) "
    r"(?:d(?P<sides_d>\d+)|(?P<sides_s>\d+)-sided (?:die|dice))\.?$",
    re.IGNORECASE,
)
#: One striation of a RULE 706.3a results table: "1—9 | <effect>",
#: "20 | <effect>", "10+ | <effect>" (`N+` is the single-endpoint form).
#: The `|` separator and em/en-dash range are exactly what `normalize`
#: leaves (see `Contact Other Plane` / `Delina, Wild Mage`).
_DICE_TABLE_ROW_RE = re.compile(
    r"^(?P<lo>\d+)(?:\s*[—–-]\s*(?P<hi>\d+)|(?P<plus>\+))?\s*\|\s*(?P<body>.+?)\.?$",
    re.IGNORECASE,
)
_DICE_TABLE_COUNT_WORDS = {"two": 2, "three": 3}


def _split_dice_table_block(
    lines: list[str], start: int, provenance: ParserProvenance
) -> Optional[tuple[Optional[dict[str, Any]], int, int, list[tuple[int, Optional[int], str]], int]]:
    """A RULE 706 "Roll a d20." instruction followed by one or more
    "<range> | <effect>" results-table rows (RULE 706.3a/706.3b — the roll,
    its table and its modifiers are one ability). Bare or trigger-wrapped;
    the "<cost>: roll …" + table and the "you may roll again" recursion
    (Delina) are deliberately out of scope, falling through to per-line
    dispatch (and staying UNMODELED) rather than being half-claimed.

    Returns ``(trigger, sides, count, rows, next_index)`` where ``rows`` is
    a list of ``(lo, hi_or_None, body_text)`` — ``hi`` ``None`` is the
    ``N+`` open-ended endpoint — or ``None`` if ``lines[start]`` isn't this
    shape, its wrapper isn't a recognised trigger, or a row is malformed
    (fail-closed).
    """
    head = _DICE_TABLE_HEADER_RE.match(lines[start].strip())
    if head is None:
        return None
    # At least one table row must follow, or this is just a bare roll the
    # ordinary effect handler already claims — nothing to do here.
    rows: list[tuple[int, Optional[int], str]] = []
    j = start + 1
    while j < len(lines):
        row = _DICE_TABLE_ROW_RE.match(lines[j].strip())
        if row is None:
            break
        lo = int(row.group("lo"))
        hi = None if row.group("plus") else int(row.group("hi") or lo)
        rows.append((lo, hi, row.group("body").strip()))
        j += 1
    if not rows:
        return None
    trigger: Optional[dict[str, Any]] = None
    pre = head.group("pre")
    if pre:
        probe = segment_line(pre + "draw a card.", allow_spell_effect=False, provenance=provenance)
        if not probe.claimed or probe.spec is None or probe.spec.ability_kind != "triggered":
            return None
        trigger = probe.spec.trigger
        if not trigger or trigger.get("event") is None:
            return None
    count_word = head.group("count")
    count = (
        _DICE_TABLE_COUNT_WORDS.get((count_word or "").lower(), int(count_word))
        if count_word else 1
    )
    sides = int(head.group("sides_d") or head.group("sides_s"))
    return (trigger, sides, count, rows, j)


def _split_reflexive_modal_block(
    lines: list[str], start: int,
) -> Optional[tuple[Optional[dict[str, Any]], str, bool, bool, bool, int, list[str], int]]:
    """Recognise ``You may pay <cost>. When you do, choose N —`` plus bullets.

    This is intentionally a gate-level block wrapper: its payoff is a fresh
    RULE 603.11 triggered ability, so treating it as the ordinary synchronous
    ``pay_cost_then`` clause would choose targets/modes at the wrong time.
    """
    line = lines[start].strip()
    trigger: Optional[dict[str, Any]] = None
    match = _REFLEXIVE_MODAL_RE.match(line)
    if match is None:
        wrapper = _TRIGGER_RE.match(line)
        if wrapper is None:
            return None
        match = _REFLEXIVE_MODAL_RE.match(wrapper.group("body").strip())
        if match is None:
            return None
        probe = segment_line(
            line[: wrapper.start("body")] + "draw a card.",
            allow_spell_effect=False,
            provenance=ParserProvenance(version=PARSER_VERSION, source="reflexive-modal", confidence=1.0),
        )
        if not probe.claimed or probe.spec is None or probe.spec.ability_kind != "triggered":
            return None
        trigger = probe.spec.trigger
    header = MODAL_HEADER_RE.match(match.group("header").strip())
    if header is None:
        return None
    collected = collect_mode_bodies(lines, start + 1)
    if collected is None:
        return None
    bodies, next_i = collected
    choose = int(header.group("n"))
    if choose < 1 or choose > len(bodies):
        return None
    return (
        trigger, match.group("cost").strip(), bool(header.group("or_both")),
        bool(header.group("or_more")), "same mode more than once" in match.group("header").lower(),
        choose, bodies, next_i,
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
#: once per `GameObject` built (`card_registry.specs_for`), so the same
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
        bool(getattr(card, "is_station", False)),
    )


#: Effect types whose static form reads ``active_if`` (`registry._SELECTOR_KEYS` -> the layer
#: engine or a permission module's own gate); a named-choice option built from anything else would
#: apply unconditionally, so the gate fails closed on it instead.
_NAMED_MODE_STATIC_EFFECTS = frozenset({
    "anthem", "grant_keyword", "trigger_doubler", "graveyard_cast_permission",
    "self_graveyard_or_exile_cast_permission", "top_library_permission", "cost_reduction",
})


def _named_mode_gated(spec: AbilitySpec, label: str) -> Optional[AbilitySpec]:
    """``spec`` live only while ``GameObject.chosen_mode`` is ``label`` (None = cannot be gated)."""
    condition = {"kind": "chosen_mode", "mode": label.strip().lower()}
    if spec.ability_kind == "triggered":
        spec.trigger = {**(spec.trigger or {}), "named_mode": condition["mode"]}
        return spec
    if spec.ability_kind == "static" and spec.effects:
        for effect in spec.effects:
            if effect.type not in _NAMED_MODE_STATIC_EFFECTS:
                return None
            existing = effect.params.get("active_if")
            effect.params["active_if"] = (
                {"kind": "all", "conditions": [existing, condition]} if existing else condition
            )
        return spec
    return None


def parse_oracle(card: Any) -> ParseResult:
    """Memoized entry point — see `_parse_oracle_uncached` for the real work.

    Returns a deep copy of the cached `ParseResult` so a caller is always
    free to treat its `AbilitySpec`s as its own (matches
    `card_registry.register`'s "factory returns fresh specs each call"
    contract for the hand-authored registry) even though the parse itself
    now runs at most once per distinct input.
    """
    key = _parse_cache_key(card)
    cached = _PARSE_CACHE.get(key)
    if cached is None:
        cached = _parse_oracle_uncached(card)
        _PARSE_CACHE[key] = cached
    return copy.deepcopy(cached)


#: PAR-130: trigger events whose firing names the player a "that player"
#: target scope resolves to (`targeting.trigger_player_antecedent`). A
#: ``DAMAGE`` head only counts when its recipient filter is a player.
_THAT_PLAYER_EVENTS: frozenset[str] = frozenset({
    "CREATURES_DEALT_COMBAT_DAMAGE_TO_PLAYER", "ATTACKS", "PLAYER_ATTACKED",
    "BECOMES_TARGET", "STEP_BEGIN",
})
#: The head must name that player itself — the event alone isn't enough ("at
#: the beginning of **your** upkeep" is a `STEP_BEGIN` with no other player).
_THAT_PLAYER_HEAD_RE = re.compile(
    r"\b(?:a player|an opponent|each opponent's|each player's|defending player|"
    r"1 of your opponents|an opponent controls)\b"
)
#: …and the body mustn't name another player first, or "that player" is that
#: one instead (a prior "target opponent", a "for each opponent" iteration).
_THAT_PLAYER_BODY_RIVAL_RE = re.compile(r"\b(?:players?|opponents?)\b")


def _that_player_head_ok(event: str, filt: Any, text: str) -> bool:
    """Whether a trigger (``event`` + recipient ``filt``, printed as ``text``)
    names the player a "that player" in its body refers to."""
    before_that = text.lower().split("that player", 1)[0]
    if re.search(
        r"\btarget (?:opponent|player)\b|\btarget [^.]+? (?:an opponent controls|you don'?t control)\b",
        before_that,
    ):
        return True
    player_damage = event == "DAMAGE" and isinstance(filt, dict) and filt.get("is_player")
    if event not in _THAT_PLAYER_EVENTS and not player_damage:
        return False
    head, sep, body = text.lower().partition(", ")
    if not sep or not _THAT_PLAYER_HEAD_RE.search(head):
        return False
    return not _THAT_PLAYER_BODY_RIVAL_RE.search(body.split("that player", 1)[0])


#: `TargetSpec.per_player`'s vocabulary, mirrored here (no `game/` imports).
_PER_PLAYER_SCOPES = ("opponents", "players", "any_opponents")
#: The context a spell/activated ability's effects are walked under: no trigger
#: head names "that player", but per-player rounds and a prior target can.
_SPELL_CONTEXT: tuple[str, Any, str] = ("PRIOR_TARGET", None, "")


def _that_player_tree_ok(node: Any, context: Optional[tuple[str, Any, str]], text: str) -> bool:
    """Walk a spec tree; every ``…_that_player_controls`` kind must sit under
    a trigger whose head names that player. A granted trigger (a dict with
    ``trigger_event`` — `grant_triggered_ability`) is its own context, read
    against the quoted ability text it was parsed from."""
    if isinstance(node, EffectSpec):
        return _that_player_tree_ok(node.params, context, text)
    if isinstance(node, (list, tuple)):
        return all(_that_player_tree_ok(item, context, text) for item in node)
    if not isinstance(node, dict):
        return True
    if isinstance(node.get("trigger_event"), str):
        quoted = re.search(r'"([^"]*)"', text)
        context = (node["trigger_event"], node.get("filter"), quoted.group(1) if quoted else "")
    for key, val in node.items():
        if key.endswith("kind") and isinstance(val, str) and val.endswith("_that_player_controls"):
            if node.get("per_player") in _PER_PLAYER_SCOPES:
                # "for each opponent/player, …" is its own antecedent, but
                # only a triggered ability or a spell (`targeting.
                # spell_target_rounds`) gathers its targets per round.
                if context is None:
                    return False
            elif context is None or not _that_player_head_ok(*context):
                return False
        elif key == "kinds" and isinstance(val, list) and any(
            isinstance(kind, str) and kind.endswith("_that_player_controls") for kind in val
        ):
            if node.get("per_player") in _PER_PLAYER_SCOPES:
                if context is None:
                    return False
            elif context is None or not _that_player_head_ok(*context):
                return False
        elif not _that_player_tree_ok(val, context, text):
            return False
    return True


def _opponents_batch_ok(spec: AbilitySpec) -> bool:
    """MEC-104: "…deals damage to one or more of your opponents" is one trigger per simultaneous
    batch. The combat aggregate dedupes that itself (`binding.core._contributor_condition`); a
    plain per-hit ``DAMAGE`` trigger cannot, so it is only sound with "this ability triggers
    only once each turn" (Molten Lavamancer) — otherwise fail closed."""
    trigger = spec.trigger or {}
    if spec.ability_kind != "triggered" or not trigger.get("opponents_batch"):
        return True
    return trigger.get("event") != "DAMAGE" or bool(trigger.get("limit"))


def _action_limit_ok(spec: AbilitySpec) -> bool:
    """PAR-135: "Do this only once each turn" limits the action a *trigger* offers (`spec.fold_action_limit` turns
    it into a gated `seq` with a stamp). On any other ability kind, or where no stamp can be placed, nothing
    would honour the marker, so it fails closed rather than silently dropping the limit."""
    if spec.ability_kind != "triggered":
        return not contains_marker(spec.effects, ACTION_ONCE_PER_TURN_MARKER)
    return fold_action_limit(spec.effects, ACTION_ONCE_PER_TURN_MARKER, spec.raw_text or "") is not None


_EXILED_CARDS_COLORS_MANA_RE = re.compile(r"add 1 mana of any of the exiled cards' colou?rs")


_TAP_X_COST_RE = re.compile(r"\btap x untapped\b")


def _tap_x_cost_ok(spec: AbilitySpec) -> bool:
    """"Tap X untapped artifacts you control" as a cost has no engine form yet: the cost parser reads the
    X as a count of 1 (`costs.py`'s ``tap_others``), so an ability carrying it would run for a single
    tap whatever its X. Fails closed until X-sized tap costs exist."""
    cost = spec.cost if isinstance(spec.cost, dict) else None
    return not (cost and _TAP_X_COST_RE.search(str(cost.get("text", "")).lower()))


def _dig_x_ok(spec: AbilitySpec) -> bool:
    """A dig's ``x`` count ("look at the top X cards") is the announced {X} of a spell or an activated
    ability. Under a trigger nothing announced an X (the word then means a measured or "where X is"
    amount), so it fails closed instead of reading 0."""
    if spec.ability_kind != "triggered":
        return True
    return not any(
        effect.type == "inspect_top_choose" and effect.params.get("count") == "x"
        for effect in spec.effects
    )


def _that_player_antecedent_ok(spec: AbilitySpec) -> bool:
    """PAR-130: a ``…_that_player_controls`` target is only sound under a
    trigger head that names that player (RULE 603.2's firing event is what
    `targeting.trigger_player_antecedent` reads), or under a "for each
    opponent/player" or after an earlier player/opponent-controlled target.
    Everything else fails closed rather than resolving against the wrong
    player or none."""
    text = spec.raw_text or ""
    context = (
        (_SPELL_CONTEXT[0], _SPELL_CONTEXT[1], text)
        if spec.ability_kind in ("spell_effect", "activated") else None
    )
    if spec.ability_kind == "triggered" and spec.trigger:
        unquoted = re.sub(r'"[^"]*"', '""', text)
        context = (str(spec.trigger.get("event") or ""), spec.trigger.get("filter"), unquoted)
    return _that_player_tree_ok([spec.effects, spec.modes, spec.target], context, text)


#: Numeric payloads a printed "that much" may safely read from a firing
#: event. Keep this parser-side (no ``game/`` import across the boundary).
#: The first increment deliberately admits only event families whose emitted
#: payload is already the exact referenced quantity; sequence-local values
#: such as "counters removed this way" need their own context operand.
_THAT_MUCH_TRIGGER_FIELDS: dict[str, str] = {
    "DAMAGE": "amount",
    "DISCARD": "count",
    "LIFE_GAINED": "amount",
    "LIFE_LOST": "amount",
    "COUNTER": "amount",
}


def _resolve_that_much_tree(node: Any, field: Optional[str]) -> bool:
    """Resolve the private handler sentinel, or reject an unsafe antecedent."""
    if isinstance(node, EffectSpec):
        return _resolve_that_much_tree(node.params, field)
    if isinstance(node, (list, tuple)):
        return all(_resolve_that_much_tree(item, field) for item in node)
    if not isinstance(node, dict):
        return True
    if node.get("amount_from_trigger_event") == "that_much":
        if field is None:
            return False
        node["amount_from_trigger_event"] = field
    return all(_resolve_that_much_tree(value, field) for value in node.values())


def _that_much_antecedent_ok(spec: AbilitySpec) -> bool:
    event = str((spec.trigger or {}).get("event") or "") if spec.ability_kind == "triggered" else ""
    return _resolve_that_much_tree(
        [spec.effects, spec.modes, spec.target], _THAT_MUCH_TRIGGER_FIELDS.get(event)
    )


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
    # RULE 123.2: sheets may contain only ticket symbols/stats or no text.
    type_line = (getattr(card, "type_line", "") or "").strip().casefold()
    if _mentions_stickers(raw) or type_line == "stickers":
        # Fail-closed the same way as an ordinary UNMODELED card (the
        # binder never sees these specs' effects — there are none), but
        # tagged distinctly and with no `unclaimed` seeds so this card
        # never shows up in the processing-list backlog (see
        # `NEVER_SUPPORTED`'s docstring above).
        return ParseResult(specs=list(keyword_specs), coverage=NEVER_SUPPORTED)
    raw = _expand_ability_word_reminders(raw)
    if _is_spell(card):
        # RULE 608.2c: on an instant or sorcery an "Infusion —"/"Addendum —"
        # paragraph is the same spell ability's next instruction, so "that
        # creature"/"… instead" must see the paragraph before it.
        raw = _SPELL_RIDER_PARAGRAPH_RE.sub(r" \g<rider>", raw)
    normalized = normalize(raw, getattr(card, "name", None), getattr(card, "keywords", None))
    if not normalized:
        return ParseResult(specs=list(keyword_specs), coverage=MODELED)

    allow_spell_effect = _is_spell(card)
    is_saga = bool(getattr(card, "is_saga", False))
    is_leveler = bool(getattr(card, "is_leveler", False))
    is_class = bool(getattr(card, "is_class", False))
    is_station = bool(getattr(card, "is_station", False))
    effect_specs: list[AbilitySpec] = []
    unclaimed: list[str] = []
    all_claimed = True

    def _process_line(line: str) -> None:
        nonlocal all_claimed
        # PAR-95 / Adamant — Sundering Stroke's rider changes the preceding
        # divided instruction into one full hit per already selected target.
        # It is deliberately one exact form: a general "instead" rewrite
        # would be unsound for target choice and distribution semantics.
        sundering = re.fullmatch(
            r"~ deals (?P<n>\d+) damage divided as you choose among 1, 2, or 3 targets\. "
            r"if at least (?P<threshold>\d+) red mana was spent to cast this spell, instead ~ deals "
            r"(?P<replacement>\d+) damage to each of those permanents and/or players\.?",
            line, re.I,
        )
        if sundering is not None and sundering.group("n") == sundering.group("replacement"):
            effect_specs.append(AbilitySpec("spell_effect", [EffectSpec("damage", {
                "amount": int(sundering.group("n")), "target_kind": "any", "count": 3,
                "count_max": 3, "optional": True, "divided": True,
                "each_target_if_mana_color_spent": {
                    "color": "R", "threshold": int(sundering.group("threshold")),
                },
            })], raw_text=line, parser=provenance))
            return
        # PAR-59 / RULE 702.55: Haunt cards print either the combined ETB +
        # linked-creature-death trigger or the latter alone.  The ordinary
        # ETB half stays a normal battlefield trigger; the death half is a
        # DIES trigger whose wrapper makes `triggers_mixin` scan the exiled
        # haunter linked to that exact dying creature.
        haunt = re.fullmatch(
            r"when ~ enters or the creature it haunts dies,\s*(?P<body>.+)", line, re.I
        )
        haunt_only = re.fullmatch(
            r"when the creature this card haunts dies,\s*(?P<body>.+)", line, re.I
        )
        if haunt is not None or haunt_only is not None:
            body = (haunt or haunt_only).group("body")
            effects = parse_effect_body(body)
            if effects is None:
                all_claimed = False
                unclaimed.append(line)
                return
            if haunt is not None:
                enter = segment_line(
                    "when ~ enters, " + body, allow_spell_effect=allow_spell_effect,
                    provenance=provenance, is_saga=is_saga,
                )
                if not enter.claimed or enter.spec is None:
                    all_claimed = False
                    unclaimed.append(line)
                    return
                effect_specs.append(enter.spec)
            effect_specs.append(AbilitySpec(
                "triggered",
                [EffectSpec("haunt_linked_death", {
                    "effects": [effect.to_dict() for effect in effects],
                })],
                trigger={"event": "DIES"}, raw_text=line, parser=provenance,
            ))
            return
        # PAR-45: an opponent choice and its entry-counter consequence are
        # two independent pre-entry replacements printed on one line.  Split
        # only this fully-known composition; a generic sentence split would
        # incorrectly claim arbitrary unresolved tails.
        opponent_entry = re.fullmatch(
            r"(?P<choice>as ~ enters, choose an opponent)\.\s*(?P<tail>.+)", line, re.I
        )
        # "Flashback {8}{G}{G}. This spell costs {X} less to cast this way, where X is …" (the Visions cycle): the
        # keyword half is `parse_keywords`'s; the sentence about its own cost is a graveyard-gated cost reduction.
        flashback_discount = FLASHBACK_DISCOUNT_LINE_RE.fullmatch(line)
        if flashback_discount is not None:
            line = flashback_discount.group("discount")
        if opponent_entry is not None:
            choice_seg = segment_line(
                opponent_entry.group("choice"), allow_spell_effect=allow_spell_effect,
                provenance=provenance, is_saga=is_saga,
            )
            if not choice_seg.claimed or choice_seg.spec is None:
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(choice_seg.spec)
            line = opponent_entry.group("tail")
        # PAR-64 / Raid: these are amount replacements for the immediately
        # preceding damage instruction, not independent damage effects. Both
        # printed orders exist (Firecannon Blast / Arrow Storm). Keep the
        # prior target and attach the override to that same effect.
        raid_override = re.fullmatch(
            r"(?:if you attacked this turn, instead )?~ deals (?P<n>\d+) damage"
            r"(?: to that (?:permanent|player)(?: or player)?)?(?P<unpreventable> and the damage can'?t be prevented)?"
            r"(?: instead if you attacked this turn)?\.?",
            line,
            re.I,
        )
        if raid_override is not None and effect_specs:
            previous = effect_specs[-1]
            damages = [effect for effect in previous.effects if effect.type == "damage"]
            if previous.ability_kind == "spell_effect" and len(previous.effects) == len(damages) == 1:
                damages[0].params["amount_if_raid"] = int(raid_override.group("n"))
                if raid_override.group("unpreventable"):
                    damages[0].params["unpreventable"] = True
                return
        # PAR-95 / Adamant's two-line forms.  These riders refer to the
        # immediately preceding spell instruction, so append/modify that
        # same AbilitySpec and retain its target-resolution context instead
        # of creating an independent, incorrectly targeted spell effect.
        adamant = re.fullmatch(
            r"if at least (?P<threshold>\d+) (?P<color>white|blue|black|red|green|colorless) mana was spent "
            r"to cast this spell, (?P<body>.+)\.?,?", line, re.I,
        )
        if adamant is not None and effect_specs:
            previous = effect_specs[-1]
            adamant_body = adamant.group("body").strip().rstrip(".").strip()
            condition = {
                "kind": "mana_color_spent_to_cast_at_least",
                "color": {"white": "W", "blue": "U", "black": "B", "red": "R", "green": "G", "colorless": "C"}[
                    adamant.group("color").lower()
                ],
                "amount": int(adamant.group("threshold")),
            }
            # Searing Barrage: a second damage instruction to the controller
            # of the preceding creature target.
            if re.fullmatch(r"~ deals \d+ damage to that creature'?s controller", adamant_body, re.I):
                n = int(re.search(r"\d+", adamant_body).group())
                if previous.ability_kind == "spell_effect":
                    previous.effects.append(EffectSpec("damage", {
                        "amount": n, "recipient_subject": "previous_subject_controller",
                    }, condition=condition))
                    return
            # Slaying Fire: a magnitude replacement, never a second hit.
            override = re.fullmatch(r"it deals (?P<n>\d+) damage instead", adamant_body, re.I)
            if override is not None:
                damages = [effect for effect in previous.effects if effect.type == "damage"]
                if previous.ability_kind == "spell_effect" and len(previous.effects) == len(damages) == 1:
                    damages[0].params["amount_if_mana_color_spent"] = {
                        "color": condition["color"], "threshold": condition["amount"],
                        "amount": int(override.group("n")),
                    }
                    return
            # Outmuscle: its first target remains the referent after the
            # intervening fight has consumed a second target requirement.
            if re.fullmatch(r"the creature you control gains indestructible until end of turn", adamant_body, re.I):
                if previous.ability_kind == "spell_effect" and len(previous.effects) == 2 and previous.effects[-1].type == "fight":
                    previous.effects.append(EffectSpec("pump", {
                        "keywords": ["indestructible"], "target_group_index": 0,
                    }, condition=condition))
                    return
        # MEC-86 / RULE 722.3a: "~ enters prepared." states the permanent
        # gains the prepared designation as it enters — unlike the
        # tapped-entry/counters checks just below, this *is* an effect
        # (`make_prepared`/`BecomePreparedEffect`, already engine-side and
        # effect-spec-driven, not a raw-text battlefield-entry scan), so it
        # synthesizes the equivalent "when ~ enters, it becomes prepared"
        # trigger — the same idiom the Haunt ETB half above uses — rather
        # than teaching `become_prepared` a second, untriggered entry path.
        # `become_prepared`'s own handler already recognizes the synthesized
        # body verbatim ("it becomes prepared").
        enters_prepared = re.fullmatch(
            r"(?:~|this creature|this permanent) enters prepared\.?", line, re.I
        )
        if enters_prepared is not None:
            enter = segment_line(
                "when ~ enters, it becomes prepared", allow_spell_effect=allow_spell_effect,
                provenance=provenance, is_saga=is_saga,
            )
            if not enter.claimed or enter.spec is None:
                all_claimed = False
                unclaimed.append(line)
                return
            effect_specs.append(enter.spec)
            return
        # RULE 614.1 "enters tapped" clauses are covered by the engine's own
        # tapped-entry machinery (`game/card_registry.land_tap_condition`,
        # resolved by `RulesEngine.enter_land_tapped`), not through an effect
        # spec — claim the line without emitting one, the same way a mana
        # ability's "add {g}" is covered-without-spec in the segmenter.
        if tap_clause_condition(line) is not None:
            # A compound tap-land can additionally make a RULE 601.2b
            # characteristic choice as it enters (the Thriving cycle).  The
            # tapped-entry engine consumes the first sentence; continue with
            # the narrowly extracted second one so its enter replacement is
            # bound too.
            choice_tail = tapped_entry_choice_tail(line)
            if choice_tail is None:
                return
            line = choice_tail
        # RULE 614.1-style "enters with N counters" clauses: same split as
        # tapped-entry above — covered by `game/card_registry.
        # entry_counters` (`RulesEngine`'s battlefield-entry resolution),
        # not an effect spec.
        if entry_counters_condition(line) is not None:
            return
        # RULE 702.33b Kicker's own "{X}" payment restriction ("Spend only
        # colored mana on X. No more than one mana of each color may be
        # spent this way.", PAR-7): same split as the two clauses above —
        # covered by `game/card_registry.kicker_x_mana_restriction`
        # (`GameEngine.can_cast`/`cast_spell`), not an effect spec.
        if kicker_x_mana_restriction_condition(line) is not None:
            return
        # RULE 903.3 "~ can be your commander." — a deck-legality permission
        # with no in-game behavioral effect (see `commander_eligibility_line`'s
        # docstring): claim the line, contribute nothing, same split as the
        # two tapped-entry/counter checks above.
        if commander_eligibility_line(line):
            return
        if deck_any_number_line(line):
            return
        # RULE 103.6a "If this card is in your opening hand, you may begin
        # the game with it on the battlefield." (the Leyline cycle) — a
        # pregame setup permission, not an in-game behavioral effect: same
        # split as the three clauses above, covered by `game/
        # card_registry.opening_hand_battlefield_permission`
        # (`services/game_session.py`'s opening-hand handling), not an
        # effect spec.
        if opening_hand_battlefield_permission_line(line):
            return
        # Gemstone Caverns' conditional/costed/counter-bearing sibling of
        # the clause above, and Buried Ogre's graveyard-destination one —
        # same split, covered by `game/card_registry.
        # pregame_setup_permission` instead.
        if opening_hand_battlefield_conditional_permission_line(line):
            return
        if opening_hand_graveyard_permission_line(line):
            return
        seg: Segment = segment_line(
            line, allow_spell_effect=allow_spell_effect, provenance=provenance, is_saga=is_saga
        )
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
        elif seg.spec is not None:
            effect_specs.append(seg.spec)
            # One printed line can yield 2+ abilities — see
            # `Segment.extra_specs` (RULE 700.2's compact inline modal).
            effect_specs.extend(seg.extra_specs)

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
                # A "*/*" Leveler tier would need a `pt_cda` static (the
                # engine primitive already exists — `game/continuous.py`'s
                # layer-7a pass, shared with e.g. Tarmogoyf) instead of
                # `pt_set`, gated the same `min_level`/`max_level` way. Left
                # unimplemented on purpose, not merely deferred: unlike
                # every other item this module fails closed on, there is no
                # real printed Leveler tier to derive the CDA's actual count
                # selector from (checked against the full ~34k-card Oracle
                # cache — zero matches), so wiring this now would mean
                # *guessing* the selector docs/09's fail-closed discipline
                # exists to prevent. Revisit only if a real card is printed.
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
        header: str, or_both: bool, or_more: bool, repeatable: bool, override: Optional[dict[str, Any]], choose: int, mode_bodies: list[str]
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
                "repeatable": repeatable,
                "override": override,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_named_choice_block(
        labels: list[str], bodies: dict[str, str], header: str
    ) -> None:
        # "As ~ enters, choose A or B. • A — <ability> • B — <ability>" (Siege cycle): the choice is
        # an as-enters replacement stamping `GameObject.chosen_mode`; each option's ability stays an
        # ordinary bound ability, live only while its own label is the stored choice.
        nonlocal all_claimed
        gated: list[AbilitySpec] = []
        unclaimed_before = len(unclaimed)
        for label in labels:
            seg = segment_line(
                bodies[label], allow_spell_effect=False, provenance=provenance, is_saga=False
            )
            option_specs = (
                [_named_mode_gated(spec, label) for spec in [seg.spec, *seg.extra_specs]]
                if seg.claimed and not seg.keyword_line and seg.spec is not None else [None]
            )
            if any(spec is None for spec in option_specs):
                all_claimed = False
                unclaimed.append(f"• {label} — {bodies[label]}")
                continue
            gated.extend(option_specs)
        if len(unclaimed) > unclaimed_before:
            unclaimed.insert(unclaimed_before, header)
            return
        effect_specs.append(AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_named_mode", {"options": [label.title() for label in labels]})],
            raw_text=header, parser=provenance,
        ))
        effect_specs.extend(gated)

    def _process_spree_block(header: str, mode_costs: list[str], mode_bodies: list[str]) -> None:
        nonlocal all_claimed
        # RULE 702.172a: Spree's own block shape — always "choose one or
        # more" (`at_least=True, choose=1`, the same combinatorial offer
        # Farewell's "choose N or more" already drives via `_modal_cast_
        # actions`), but priced per mode rather than once for the whole
        # spell (`mode_costs`, threaded through `AbilitySpec._validate_
        # modes`/`effect_binder._build_mode_entries` into each mode's own
        # `spell_modes[i]["cost"]`, read by `GameEngine._modal_extra_cost`).
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"+ {c} — {b}" for c, b in zip(mode_costs, mode_bodies))
            return
        options, descriptions = parsed
        effect_specs.append(AbilitySpec(
            "spell_effect",
            effects=[],
            modes={
                "at_least": True,
                "choose": 1,
                "options": options,
                "descriptions": descriptions,
                "mode_costs": mode_costs,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_triggered_modal_block(
        header: str,
        trigger: dict[str, Any],
        or_both: bool,
        or_more: bool,
        repeatable: bool,
        exhausted: bool,
        override: Optional[dict[str, Any]],
        choose: int,
        mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        # RULE 700.2 wrapped in a RULE 603.1 trigger — e.g. "When ~ enters
        # the battlefield, choose one — • Mode A. • Mode B.": the chosen
        # mode is picked interactively as the ability is put on the stack
        # (`game/rules_engine.py`'s `trigger_mode` choice), not at cast time
        # like a modal spell. `trigger` is the full dict `segment_line`
        # produced for the wrapper (event may be a list, plus any
        # filter/phase_relation/spell_* keys) — the binder's triggered path
        # already spreads it (`effect_binder` ~L1583).
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
            trigger=trigger,
            modes={
                "or_both": or_both,
                "at_least": or_more,
                "repeatable": repeatable,
                "exhaust_per_turn": exhausted,
                "override": override,
                "choose": choose,
                "options": options,
                "descriptions": descriptions,
            },
            raw_text=header,
            parser=provenance,
        ))

    def _process_dice_table_block(
        header: str,
        trigger: Optional[dict[str, Any]],
        sides: int,
        count: int,
        rows: list[tuple[int, Optional[int], str]],
    ) -> None:
        """Emit one ``roll_die`` spec carrying a RULE 706.3a ``outcomes``
        table — as a triggered ability if ``trigger`` is set, else a bare
        spell/ability effect. Every row body must parse (fail-closed: one
        unclaimed row leaves the whole card UNMODELED)."""
        nonlocal all_claimed
        outcomes: list[dict[str, Any]] = []
        for lo, hi, body in rows:
            body_specs = parse_effect_body(body)
            if body_specs is None:
                all_claimed = False
                unclaimed.append(header)
                unclaimed.extend(f"{lo} | {b}" for _, _, b in rows)
                return
            row_out: dict[str, Any] = {"min": lo, "effects": [s.to_dict() for s in body_specs]}
            if hi is not None:
                row_out["max"] = hi
            outcomes.append(row_out)
        params: dict[str, Any] = {"sides": sides, "outcomes": outcomes}
        if count != 1:
            params["count"] = count
        effect_specs.append(AbilitySpec(
            "triggered" if trigger is not None else "spell_effect",
            [EffectSpec("roll_die", params)],
            trigger=trigger,
            raw_text=header,
            parser=provenance,
        ))

    def _process_reflexive_modal_block(
        header: str, trigger: Optional[dict[str, Any]], cost: str, or_both: bool, or_more: bool,
        repeatable: bool, choose: int, mode_bodies: list[str],
    ) -> None:
        nonlocal all_claimed
        parsed = _parse_mode_options(mode_bodies)
        if parsed is None:
            all_claimed = False
            unclaimed.append(header)
            unclaimed.extend(f"• {body}" for body in mode_bodies)
            return
        options, descriptions = parsed
        payment = EffectSpec("pay_cost_then", {
                "cost": cost,
                "then_trigger_modes": {
                    "or_both": or_both, "at_least": or_more,
                    "repeatable": repeatable, "choose": choose,
                    "options": [[spec.to_dict() for spec in option] for option in options],
                    "descriptions": descriptions,
                },
            })
        effect_specs.append(AbilitySpec(
            "triggered" if trigger is not None else "spell_effect",
            [payment],
            trigger=trigger,
            raw_text=header,
            parser=provenance,
        ))

    def _process_class_body(line: str, level: int) -> None:
        nonlocal all_claimed
        gate = {"min_level": level, "level_counter": "class_level"}
        # RULE 716.4c-adjacent one-shot: "When this Class becomes level N,
        # <effect>." isn't the ordinary "stays active once unlocked" shape
        # every other body line is — checked first since it has its own
        # trigger wrapper the generic per-line dispatch doesn't recognize
        # (`CLASS_BECOMES_LEVEL_RE`'s docstring).
        becomes = CLASS_BECOMES_LEVEL_RE.match(line.strip())
        if becomes is not None:
            n = int(becomes.group("n"))
            if n != level:
                # Printed under a different level's own block than the
                # number it names — not a shape any real card uses; fail
                # closed rather than guess which block "wins".
                all_claimed = False
                unclaimed.append(line)
                return
            body, optional = _peel_optional(becomes.group("body"))
            effects = parse_effect_body(body)
            if effects is None:
                all_claimed = False
                unclaimed.append(line)
                return
            spec = AbilitySpec(
                "triggered",
                effects=effects,
                trigger={"event": "CLASS_LEVEL", "chapter": [n]},
                optional=optional,
                raw_text=line,
                parser=provenance,
            )
            _tag_level_gate(spec, gate, default_affects=None)
            return
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects=None)

    def _process_station_body(line: str, n: int) -> None:
        nonlocal all_claimed
        # RULE 721.2a: cumulative (>= comparison, not a mutually-exclusive
        # tier range the way Leveler's own `min_level`/`max_level` pair is
        # used) — a Station bracket only ever supplies `min_level`, never
        # `max_level`, so reaching a higher threshold doesn't remove a lower
        # one's grant. Reuses the exact same `min_level`/`level_counter`
        # gate mechanism Leveler/Class already established (`continuous.
        # group_selector_objects`/`effect_binder._trigger_condition`, both
        # already generic over which counter kind `level_counter` names —
        # confirmed by reading both consumers rather than assumed), just
        # pointed at ``"charge"`` counters instead of ``"level"``/
        # ``"class_level"``.
        gate = {"min_level": n, "level_counter": "charge"}
        seg = segment_line(line, allow_spell_effect=False, provenance=provenance, is_saga=False)
        if not seg.claimed:
            all_claimed = False
            unclaimed.append(seg.raw)
            return
        if seg.keyword_line:
            # A bracket-scoped keyword line ("Flying, deathtouch" under
            # "8+ |") becomes a charge-counter-gated grant, the same
            # `_process_leveler_body` shape.
            effect_specs.append(_grant_keyword_line_spec(line, "self", gate))
            return
        if seg.spec is not None:
            _tag_level_gate(seg.spec, gate, default_affects="self")

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
    elif is_station:
        # RULE 702.184a/721: the reminder line's own real activated ability
        # is bound directly off Scryfall's `keywords: ["Station"]` entry by
        # `effect_binder._station_activated_ability` (mirroring Crew/Saddle,
        # PAR-9/MEC-40's own "recognized but inert" fix) — not emitted here.
        # This branch only needs to split the "N+ |" bracket structure
        # (`split_station_blocks`); the bare "station" word `normalize()`
        # leaves behind, and every other bracket-less line (RULE 721.4
        # allows one both before *and* after the brackets — see `catalogue.
        # station`'s module docstring), flow through the ordinary per-line
        # dispatch below unchanged.
        ordinary, blocks = split_station_blocks(normalized)
        for line in ordinary:
            _process_line(line)
        for n, body in blocks:
            _process_station_body(body, n)
        # RULE 721.2b: "and is a creature with base power/toughness [P/T]"
        # — confirmed against all 30 cached Station cards that this never
        # appears as a per-bracket P/T box in `oracle_text` at all (Scryfall
        # drops it entirely); the only surviving trace is the reminder
        # line's own "It's an artifact creature at N+." sentence, read from
        # **raw** text since `normalize` has already erased it by now (see
        # `catalogue.station.station_creature_threshold`'s docstring). The
        # P/T itself comes from `Card.vehicle_power`/`vehicle_toughness`
        # (RULE 208.1's general "noncreature permanent's own printed P/T"
        # slot, already populated for Station the same way MEC-29 populated
        # it for Vehicle/Crew — `services/scryfall_client.py`), the same
        # `type_change` static shape `effect_binder._crew_activated_ability`
        # uses for "becomes an artifact creature", just standing (charge-
        # counter-gated) instead of "until end of turn".
        creature_n = station_creature_threshold(raw)
        if creature_n is not None:
            type_change_params: dict[str, Any] = {
                "add_types": ["creature"], "affects": "self",
                "min_level": creature_n, "level_counter": "charge",
            }
            vehicle_power = getattr(card, "vehicle_power", None)
            vehicle_toughness = getattr(card, "vehicle_toughness", None)
            if vehicle_power is not None:
                type_change_params["power"] = vehicle_power
            if vehicle_toughness is not None:
                type_change_params["toughness"] = vehicle_toughness
            effect_specs.append(AbilitySpec(
                "static",
                effects=[EffectSpec("type_change", type_change_params)],
                raw_text=f"it's an artifact creature at {creature_n}+",
                parser=provenance,
            ))
    else:
        lines = [line for line in normalized.split("\n") if line.strip()]
        i = 0
        while i < len(lines):
            reflexive_modal = _split_reflexive_modal_block(lines, i)
            if reflexive_modal is not None:
                trigger, cost, or_both, or_more, repeatable, choose, mode_bodies, next_i = reflexive_modal
                _process_reflexive_modal_block(
                    lines[i], trigger, cost, or_both, or_more, repeatable, choose, mode_bodies,
                )
                i = next_i
                continue
            spree_block = split_spree_block(lines, i) if allow_spell_effect else None
            if spree_block is not None:
                mode_costs, mode_bodies, next_i = spree_block
                _process_spree_block(lines[i], mode_costs, mode_bodies)
                i = next_i
                continue
            block = split_modal_block(lines, i) if allow_spell_effect else None
            if block is not None:
                or_both, or_more, repeatable, override, choose, mode_bodies, next_i = block
                _process_modal_block(lines[i], or_both, or_more, repeatable, override, choose, mode_bodies)
                i = next_i
                continue
            named_choice = split_named_choice_block(lines, i)
            if named_choice is not None:
                nc_labels, nc_bodies, next_i = named_choice
                _process_named_choice_block(nc_labels, nc_bodies, lines[i])
                i = next_i
                continue
            trig_block = _split_triggered_modal_block(lines, i, provenance)
            if trig_block is not None:
                trigger, or_both, or_more, repeatable, exhausted, override, choose, mode_bodies, next_i = trig_block
                _process_triggered_modal_block(
                    lines[i], trigger, or_both, or_more, repeatable, exhausted, override, choose, mode_bodies
                )
                i = next_i
                continue
            dice_table = _split_dice_table_block(lines, i, provenance)
            if dice_table is not None:
                dt_trigger, dt_sides, dt_count, dt_rows, next_i = dice_table
                _process_dice_table_block(lines[i], dt_trigger, dt_sides, dt_count, dt_rows)
                i = next_i
                continue
            _process_line(lines[i])
            i += 1

    # PAR-30 "Threaten … tails residue" — old two-sentence O-Ring linkage.
    # Modern templating ("exile X until ~ leaves the battlefield.") sets
    # ``remember`` on the exile at parse time; the old cycle prints the
    # return as its own separate "When ~ leaves the battlefield, return the
    # exiled card…" line (`_return_exiled_card` → `return_linked_exile`).
    # That effect reads `GameObject.linked_exile_id`, which only an
    # ``ExileEffect(remember=True)`` populates — so, seeing both halves on
    # one card, stamp ``remember`` onto the companion ETB exile here.
    _has_return_linked = any(
        e.type == "return_linked_exile"
        for spec in effect_specs
        for e in spec.effects
    )
    if _has_return_linked:
        # The return half is only ever printed to pair with this card's own
        # exile (ETB for O-Ring, a Saga chapter for The Princess Takes
        # Flight, …), so stamp ``remember`` on every plain targeted exile it
        # has — never a mass ``selector`` exile (a board wipe won't be the
        # one linked card) and never one that already carries ``remember``.
        for spec in effect_specs:
            for e in spec.effects:
                if e.type == "exile" and not e.params.get("selector"):
                    e.params["remember"] = True

    # Pit of Offerings: "{T}: Add one mana of any of the exiled cards' colors." names the cards the
    # ETB's "exile up to three target cards from graveyards" took. The mana line is the
    # `mana_abilities` module's (`imprinted_card_colors`, read off `linked_exile_ids`), so — like the
    # linked-return stamp above — the exile that feeds it must remember what it took.
    if _EXILED_CARDS_COLORS_MANA_RE.search(normalized):
        for spec in effect_specs:
            for e in spec.effects:
                if e.type == "exile" and str(e.params.get("target_kind", "")).startswith("any_graveyard"):
                    e.params["remember"] = True

    for spec in effect_specs:
        if not _that_player_antecedent_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _that_much_antecedent_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _opponents_batch_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _action_limit_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)
        if not _dig_x_ok(spec) or not _tap_x_cost_ok(spec):
            all_claimed = False
            unclaimed.append(spec.raw_text)

    return ParseResult(
        specs=list(keyword_specs) + effect_specs,
        coverage=MODELED if all_claimed else UNMODELED,
        unclaimed=unclaimed,
    )
