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
from .catalogue.lands import tap_clause_condition
from .catalogue.levels import (
    CLASS_BECOMES_LEVEL_RE,
    LEVEL_UP_LINE_RE,
    PT_LINE_RE,
    split_class_blocks,
    split_leveler_blocks,
)
from .catalogue.modal import MODAL_HEADER_RE, collect_mode_bodies, split_modal_block, split_spree_block
from .catalogue.opening_hand import (
    opening_hand_battlefield_conditional_permission_line,
    opening_hand_battlefield_permission_line,
    opening_hand_graveyard_permission_line,
)
from .catalogue.station import split_station_blocks, station_creature_threshold
from .catalogue.static_handlers import commander_eligibility_line
from .normalize import normalize
from .segmenter import (
    Segment,
    _peel_optional,
    _TRIGGER_RE,
    parse_effect_body,
    segment_line,
)
from .spec import AbilitySpec, EffectSpec, ParserProvenance

MODELED = "MODELED"
UNMODELED = "UNMODELED"
#: Stickers (RULE 123) are a permanent project non-goal — see
#: `docs/implementation-state/BACKLOG.md` — not a "not yet" gap like an ordinary
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
#: + `request_choose_objects`'s new `"cast_free"` action (a hand-zone pick);
#: and a new mass-interactive primitive, `RulesEngine.
#: request_each_player_pay_or` (RULE 101.4 APNAP, chained off the existing
#: single-player `request_pay_cost_then`) plus a new compound
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
#: of the above: `ability_catalogue.is_registered` lacked `specs_for`'s own
#: DFC "//" front-face fallback, so an already-fully-bound split/DFC card
#: registered under its front face alone (Halvar, God of Battle // Sword
#: of the Realms) was wrongly reported UNMODELED. The rest of this batch's
#: ~30 cards were hand-authored in `ability_catalogue.py` (several new
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
#: `request_choose_objects`'s existing chooser, +63-card family);
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
#: the already-shipped `game/effects.py` `AmassEffect` (proven only via the
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
#: `pending_choice` (`resolve_endure_choice`) + `effects.EndureEffect`
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
#: most votes or tied for most votes" → `request_vote(winner_specs=...)`
#: + an indefinite RULE 611 self-scoped `grant_protection_static` per
#: leading colour — Council Guardian); `_vote_object` ("vote for a nonland
#: permanent you don't control / a card in your graveyard, exile / return
#: each most-voted" → new `vote_object` spec / `ObjectVoteEffect` /
#: `request_object_vote` / `vote_object` pending_choice — Council's
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
#: threads impulsive_look → `ImpulsiveLookEffect` → `request_impulsive_look`
#: → `resolve_impulsive_look_choice`, which adds `temp_keywords` to the
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
#: else-branch, run in `resolve_impulsive_look_choice` /
#: `request_impulsive_look` when nothing is placed. +1.
#: "196": PAR-30 "copy of a named card" body singletons — **The Vast
#: Scrier**. `request_search` / `PutFromHandOntoBattlefieldEffect` gain
#: `then_specs_if_none` — "if you don't put a card onto the battlefield
#: this way, `<body>`." (here `scry 2`) runs `<body>` when the from-hand
#: pick places nothing (declined in `resolve_search_choice`, or nothing
#: eligible in `request_search`). `_PUT_FROM_HAND_RE` also consumes the
#: reminder "if it has any 'whenever ~ attacks' triggers, those trigger"
#: (a no-op — `put_onto_battlefield_attacking` re-fires ATTACKS already).
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
#: `resolve_counter_unless_pays_choice`), and "battle" joins the counter-
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
#: are hand-authored in `ability_catalogue/entries_016.py`, not parsed.
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
#: `request_choose_objects`, action ``"remove_suspected"``); a
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
#: (`ability_catalogue/entries_016.py`) — no new parser recognition, each
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
#: `request_choose_objects` action `"gain_control_for"` + payload
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
#: +P/+T for each …") and the long selector tail stay open in PAR-43.
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
PARSER_VERSION = "230"


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
    `docs/implementation-state/BACKLOG.md`), not merely deprioritized. A simple
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


def _is_spell(card: Any) -> bool:
    return bool(getattr(card, "is_instant", False) or getattr(card, "is_sorcery", False))


def _split_triggered_modal_block(
    lines: list[str], start: int, provenance: ParserProvenance
) -> Optional[tuple[dict[str, Any], bool, bool, int, list[str], int]]:
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

    Returns ``(trigger, or_both, or_more, choose, mode_bodies, next_index)``,
    or ``None`` if ``lines[start]`` isn't this shape at all, its wrapper
    isn't a recognised trigger, or ``choose`` exceeds the number of mode
    lines actually printed — fail-closed, the caller falls back to ordinary
    per-line segmentation.
    """
    trig = _TRIGGER_RE.match(lines[start].strip())
    if trig is None:
        return None
    header = MODAL_HEADER_RE.match(trig.group("body").strip())
    if header is None:
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
    choose = int(header.group("n"))
    if choose < 1 or choose > len(mode_bodies):
        return None
    return (
        trigger,
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
        bool(getattr(card, "is_station", False)),
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
    raw = _expand_ability_word_reminders(raw)
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
        # RULE 702.33b Kicker's own "{X}" payment restriction ("Spend only
        # colored mana on X. No more than one mana of each color may be
        # spent this way.", PAR-7): same split as the two clauses above —
        # covered by `game/ability_catalogue.kicker_x_mana_restriction`
        # (`GameEngine.can_cast`/`cast_spell`), not an effect spec.
        if kicker_x_mana_restriction_condition(line) is not None:
            return
        # RULE 903.3 "~ can be your commander." — a deck-legality permission
        # with no in-game behavioral effect (see `commander_eligibility_line`'s
        # docstring): claim the line, contribute nothing, same split as the
        # two tapped-entry/counter checks above.
        if commander_eligibility_line(line):
            return
        # RULE 103.6a "If this card is in your opening hand, you may begin
        # the game with it on the battlefield." (the Leyline cycle) — a
        # pregame setup permission, not an in-game behavioral effect: same
        # split as the three clauses above, covered by `game/
        # ability_catalogue.opening_hand_battlefield_permission`
        # (`services/game_session.py`'s opening-hand handling), not an
        # effect spec.
        if opening_hand_battlefield_permission_line(line):
            return
        # Gemstone Caverns' conditional/costed/counter-bearing sibling of
        # the clause above, and Buried Ogre's graveyard-destination one —
        # same split, covered by `game/ability_catalogue.
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
            spree_block = split_spree_block(lines, i) if allow_spell_effect else None
            if spree_block is not None:
                mode_costs, mode_bodies, next_i = spree_block
                _process_spree_block(lines[i], mode_costs, mode_bodies)
                i = next_i
                continue
            block = split_modal_block(lines, i) if allow_spell_effect else None
            if block is not None:
                or_both, or_more, choose, mode_bodies, next_i = block
                _process_modal_block(lines[i], or_both, or_more, choose, mode_bodies)
                i = next_i
                continue
            trig_block = _split_triggered_modal_block(lines, i, provenance)
            if trig_block is not None:
                trigger, or_both, or_more, choose, mode_bodies, next_i = trig_block
                _process_triggered_modal_block(
                    lines[i], trigger, or_both, or_more, choose, mode_bodies
                )
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

    return ParseResult(
        specs=list(keyword_specs) + effect_specs,
        coverage=MODELED if all_claimed else UNMODELED,
        unclaimed=unclaimed,
    )
