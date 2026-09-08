"""Card -> AbilitySpec catalogue entries, part 008 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

def _incubator_token() -> list[AbilitySpec]:
    """{2}: Transform this token. It transforms into a 0/0 Phyrexian
    artifact creature.

    — the Incubate token family (RULE 701.51-adjacent): any Incubate
    producer's `create_token` call names this token "Incubator", and
    `bind_from_catalogue` binds a fresh token's abilities off its own
    name exactly like a real permanent, so this one registration covers
    every one of them. A genuinely permanent (RAW: no "until")
    characteristic change, so `grant_until` at ``duration="rest_of_game"``
    — targeting the token's own source, no RULE 115 target ("this
    token", the same self-acting mode `RegenerateEffect` uses) — animates
    it into a creature via `type_change`'s existing power/toughness
    animation params (0/0 base; its already-present +1/+1 counters do
    the rest) rather than a new primitive.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Phyrexian"],
                        "power": 0, "toughness": 0,
                    },
                },
            })],
            cost={"text": "{2}"},
        ),
    ]


register("Incubator", _incubator_token)


def _malakir_rebirth() -> list[AbilitySpec]:
    """Choose target creature. You lose 2 life. Until end of turn, that
    creature gains "When this creature dies, return it to the battlefield
    tapped under its owner's control."

    — Eliferate deck batch. A single-target spell (the life loss is
    untargeted, so the *grant* carries the one real RULE 115 target): the
    granted ability is `grant_triggered_ability` (RULE 613.7f, the same
    shape `Kaldra Compleat`'s own quoted grant uses) at
    ``duration="end_of_turn"`` rather than a printed permanent's standing
    grant, wrapping the new `return_self_from_graveyard_untargeted` —
    `effects.ReturnSelfFromGraveyardEffect`'s ``obj=None`` fallback to its
    own ``source``, which `continuous.py`'s layer-6 grant machinery binds
    fresh per affected object, so "it" is always whichever creature the
    grant landed on.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("lose_life", {"amount": 2}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "target_kind": "creature",
                    "static": {
                        "type": "grant_triggered_ability",
                        "params": {
                            "trigger_event": EventType.DIES,
                            "grant_effects": [
                                {"type": "return_self_from_graveyard_untargeted",
                                 "params": {"destination": "battlefield", "tapped": True}},
                            ],
                        },
                    },
                }),
            ],
        ),
    ]


register("Malakir Rebirth", _malakir_rebirth)
register("Malakir Rebirth // Malakir Mire", _malakir_rebirth)


def _restless_cottage() -> list[AbilitySpec]:
    """This land enters tapped.
    {T}: Add {B} or {G}.
    {2}{B}{G}: This land becomes a 4/4 black and green Horror creature
    until end of turn. It's still a land.
    Whenever this land attacks, create a Food token and exile up to one
    target card from a graveyard.

    — Eliferate deck batch. "Enters tapped" and the mana ability are both
    oracle-derived/auto-bound, needing no hand-authoring. The animation
    ability reuses the self-targeting `grant_until`/`type_change` shape
    the `Incubator` token's own transform already established (RULE
    613.7c, ``target_kind=None`` — "this land", no RULE 115 target).
    **Documented simplification**: the colour change ("black and green")
    isn't modeled — `type_change`'s layer-4 params have no colour field
    (RULE 613's own layer 5 does colour; no manland in this catalogue sets
    it yet), so the animated creature keeps whatever colour identity the
    land already had (usually colourless).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "end_of_turn", "target_kind": None,
                "static": {
                    "type": "type_change",
                    "params": {
                        "add_types": ["creature"], "add_subtypes": ["Horror"],
                        "power": 4, "toughness": 4,
                    },
                },
            })],
            cost={"text": "{2}{B}{G}"},
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {"count": 1, "token_name": "Food"}),
                EffectSpec("exile", {"target_kind": "any_graveyard_card", "optional": True}),
            ],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Restless Cottage", _restless_cottage)


def _revitalizing_repast() -> list[AbilitySpec]:
    """Put a +1/+1 counter on target creature. It gains indestructible
    until end of turn.

    — Eliferate deck batch. One real target (the counter effect); the
    keyword grant reuses it via `grant_until`'s `previous_subject` pronoun
    idiom rather than declaring a second target of its own.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["indestructible"]}},
                }),
            ],
        ),
    ]


register("Revitalizing Repast", _revitalizing_repast)
register("Revitalizing Repast // Old-Growth Grove", _revitalizing_repast)


# "Champions of the Perfect" was hand-authored (Eliferate deck batch) only
# because "behold an Elf and exile it" as an additional cast cost had no
# `AbilitySpec.additional_cost` vocabulary and the "return the exiled card
# to its owner's hand" trigger had nothing to reference. PAR-30's
# ``behold_exile`` additional cost + `ReturnLinkedExileEffect(destination=
# "hand")` cover both now, and the cast-trigger draw always parsed — so the
# whole card is parser-MODELED and the hand-authored stopgap is retired
# (removing it lets `specs_for` fall through to the oracle front-end). See
# `Done_Backend.md` "Collect Evidence / Forage / Blight".


def _champion_of_the_weird() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, behold a Goblin and exile
    it. (Exile a Goblin you control or a Goblin card from your hand.)
    Pay 1 life, Blight 2: Target opponent blights 2. Activate only as a
    sorcery.
    When this creature leaves the battlefield, return the exiled card to
    its owner's hand.

    — PAR-30 (Collect Evidence / Forage / Blight residue). The
    ``behold_exile`` additional cost + `ReturnLinkedExileEffect(destination=
    "hand")` are the shared Champion-cycle primitive (see `Done_Backend.md`);
    the only genuinely singleton part is the activated body — "target
    opponent **blights** 2", the outward-facing sibling of the "you blight
    N" verb (`BlightEffect(target_kind="opponent")` — the RULE 115 target
    is the player, the -1/-1 counters go on a creature *they* choose to
    control). `Pay 1 life, Blight 2` is a real compound `ActivationCost`
    (`pay_life` + `blight`, the latter auto-picking non-interactively per
    PAR-29), and "Activate only as a sorcery" is ``sorcery_speed_only``.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            additional_cost={"behold_exile": "Goblin"},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("blight", {"amount": 2, "target_kind": "opponent"})],
            cost={
                "text": "Pay 1 life, Blight 2",
                "pay_life": 1, "blight": 2, "sorcery_speed_only": True,
            },
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {"destination": "hand"})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Champion of the Weird", _champion_of_the_weird)


def _tenth_district_hero() -> list[AbilitySpec]:
    """{1}{W}, Collect evidence 2: This creature becomes a Human Detective
    with base power and toughness 4/4 and gains vigilance.
    {2}{W}, Collect evidence 4: If this creature is a Detective, it becomes
    a legendary creature named Mileva, the Stalwart, it has base power and
    toughness 5/5, and it gains "Other creatures you control have
    indestructible."

    — PAR-30 (Collect Evidence / Forage / Blight residue). Both bodies are
    permanent (RAW: no "until") self-transformations, `grant_until` at
    ``duration="rest_of_game"`` scoped to the source (the Incubator-token
    idiom). Level 1: a layer-4 `type_change` (`set_subtypes=["Human",
    "Detective"]`, base 4/4) + a layer-6 vigilance grant. Level 2 is an
    intervening-if on the source's own now-derived Detective subtype
    (``condition={"source_has_subtype": "Detective"}`` — the binder wraps
    the grant in a `ConditionalEffect`): a layer-4 `type_change`
    (``legendary=True`` → `GameObject._granted_legendary`, base 5/5) + a
    layer-6 grant of an *anthem* static onto the Hero itself
    (`grant_keyword` `affects="other_creatures_you_control"`,
    indestructible).

    **Documented simplification:** the literal rename to "Mileva, the
    Stalwart" isn't modeled — `GameObject.name` has no override mechanism,
    building one (layer 1, copy semantics, `to_dict`) is disproportionate to
    one card, and no card in the pool references the name "Mileva". The
    legend rule still applies (``legendary=True``); the Hero simply keeps
    showing its printed name.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "set_subtypes": ["Human", "Detective"],
                    "power": 4, "toughness": 4,
                }},
                "extra_statics": [{"type": "grant_keyword", "params": {
                    "affects": "self", "keywords": ["vigilance"],
                }}],
            })],
            cost={"text": "{1}{W}, Collect evidence 2",
                  "mana": "{1}{W}", "collect_evidence": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("grant_until", {
                "duration": "rest_of_game", "target_kind": None,
                "static": {"type": "type_change", "params": {
                    "legendary": True, "power": 5, "toughness": 5,
                }},
                "extra_statics": [{"type": "grant_keyword", "params": {
                    "affects": "other_creatures_you_control",
                    "keywords": ["indestructible"],
                }}],
            }, condition={"source_has_subtype": "Detective"})],
            cost={"text": "{2}{W}, Collect evidence 4",
                  "mana": "{2}{W}", "collect_evidence": 4},
        ),
    ]


register("Tenth District Hero", _tenth_district_hero)


def _elven_passage() -> list[AbilitySpec]:
    """{T}, Pay 1 life, Sacrifice this land: Search your library for a basic
    land card, put it onto the battlefield tapped, then shuffle. You may
    behold an Elf. If you do, untap that land.

    — PAR-30 (Collect Evidence / Forage / Blight residue). A fetch land
    whose second sentence is a reflexive "behold an Elf → untap the fetched
    land". The `search` effect's ``remember=True`` stamps the found land's
    id onto this ability's own (now-sacrificed) source
    (`GameObject.linked_exile_id`, the O-Ring field); `may_behold_untap_
    linked` reads it back, beholds if able, and untaps it. See that
    effect's docstring for the "you may" auto-take simplification.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("search", {
                    "criteria": {"basic": True},
                    "destination": "battlefield_tapped",
                    "optional": True, "remember": True,
                }),
                EffectSpec("may_behold_untap_linked", {"quality": "Elf"}),
            ],
            cost={"text": "{T}, Pay 1 life, Sacrifice ~",
                  "taps_self": True, "pay_life": 1, "sacrifice": "self"},
        ),
    ]


register("Elven Passage", _elven_passage)


def _incinerator_of_the_guilty() -> list[AbilitySpec]:
    """Flying, trample
    Whenever this creature deals combat damage to a player, you may collect
    evidence X. When you do, this creature deals X damage to each creature
    and planeswalker that player controls.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying/trample
    parse on their own; only the dynamic-X collect-evidence trigger is
    hand-authored (`CollectEvidenceXThenBoardDamageEffect` — see its
    docstring for the "X = maximum available evidence" simplification and
    why the reflexive "when you do" is folded in).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("collect_evidence_x_then_board_damage", {})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Incinerator of the Guilty", _incinerator_of_the_guilty)


def _memory_vampire() -> list[AbilitySpec]:
    """Flying
    Whenever this creature deals combat damage to a player, any number of
    target players each mill that many cards. Then you may collect evidence
    9. When you do, you may cast target nonland card from defending player's
    graveyard without paying its mana cost.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying parses;
    the combat-damage trigger is hand-authored (`MemoryVampireCombatEffect`
    — see its docstring for the multi-target-mill / collect-9 / free-cast
    auto-pick simplifications).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("memory_vampire_combat", {})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Memory Vampire", _memory_vampire)


def _conspiracy_unraveler() -> list[AbilitySpec]:
    """Flying
    You may collect evidence 10 rather than pay the mana cost for spells you
    cast.

    — PAR-30 (Collect Evidence / Forage / Blight residue). Flying parses;
    the RULE 118.9 board-wide alternative-cost grant is the
    `granted_alt_cast_cost` static (`continuous.granted_alt_cast_cost_for`,
    consulted by the engine's ``alt_cost=True`` cast path — `can_cast` /
    `cast_spell` / legal-actions `_offer_cast`). Controller-scoped ("spells
    **you** cast"); the alternative cost is `collect evidence 10`, paid via
    the same `RulesEngine.collect_evidence` primitive PAR-29 built.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "flying"}),
        AbilitySpec(
            "static",
            [EffectSpec("granted_alt_cast_cost", {"collect_evidence": 10})],
        ),
    ]


register("Conspiracy Unraveler", _conspiracy_unraveler)


def _celestial_reunion() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may choose a creature
    type and behold two creatures of that type.
    Search your library for a creature card with mana value X or less,
    reveal it, put it into your hand, then shuffle. If this spell's
    additional cost was paid and the revealed card is the chosen type, put
    that card onto the battlefield instead of putting it into your hand.

    — PAR-30 (Collect Evidence / Forage / Blight residue). The optional
    additional cost is `behold_two_shared_type` (`GameEngine._behold_two_
    shared_type` picks a creature type the caster has two of across their
    battlefield + hand, stamps it on `GameObject.chosen_type`, sets
    `additional_cost_paid`). The body is `celestial_reunion_search` — see
    that effect's docstring for the ``destination_if`` conditional
    destination.
    """
    return [
        AbilitySpec(
            "spell_effect", [],
            additional_cost={"behold_two_shared_type": True},
            additional_cost_optional=True,
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("celestial_reunion_search", {})],
        ),
    ]


register("Celestial Reunion", _celestial_reunion)


def _flourishing_defenses() -> list[AbilitySpec]:
    """Whenever a -1/-1 counter is put on a creature, you may create a 1/1
    green Elf Warrior creature token.

    — Eliferate deck batch. Unscoped (any creature, any controller) —
    filtered straight off the `COUNTER` event's own payload
    (``kind``/``recipient_is_creature``), no "group" subject needed at
    all since there's no controller/identity restriction to check.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "-1/-1", "recipient_is_creature": True},
            },
            optional=True,
        ),
    ]


register("Flourishing Defenses", _flourishing_defenses)


def _formidable_speaker() -> list[AbilitySpec]:
    """When this creature enters, you may discard a card. If you do,
    search your library for a creature card, reveal it, put it into your
    hand, then shuffle.
    {1}, {T}: Untap another target permanent.

    — Eliferate deck batch. The ETB is `pay_cost_then` (RULE 118.3) —
    "discard a card" as the optional payment, the search as its "if you
    do" tail; the reveal step isn't separately modeled, the same
    simplification every tutor in this catalogue already makes.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "Discard a card",
                "effects": [{"type": "search", "params": {"criteria": "Creature", "destination": "hand"}}],
            })],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "permanent"})],
            cost={"text": "{1}, {T}"},
        ),
    ]


register("Formidable Speaker", _formidable_speaker)


def _galadhrim_ambush() -> list[AbilitySpec]:
    """Create X 1/1 green Elf Warrior creature tokens, where X is the
    number of attacking creatures.
    Prevent all combat damage that would be dealt this turn by non-Elf
    creatures.

    — Eliferate deck batch. The token creation already parses on its own
    — reproduced verbatim. The prevention clause is `prevent_all_combat_
    damage`'s new `exclude_subtype` qualifier (RULE 615) — see its
    docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("create_token", {
                    "colors": ["G"], "subtypes": ["Elf", "Warrior"], "keywords": [],
                    "token_name": "Elf Warrior", "power": 1, "toughness": 1,
                    "count_selector": "attacking_creatures",
                }),
                EffectSpec("prevent_all_combat_damage", {"exclude_subtype": "elf"}),
            ],
        ),
    ]


register("Galadhrim Ambush", _galadhrim_ambush)


def _mirrormind_crown() -> list[AbilitySpec]:
    """As long as this Equipment is attached to a creature, the first time
    you would create one or more tokens each turn, you may instead create
    that many tokens that are copies of equipped creature.
    Equip {2}

    — Eliferate deck batch. Equip is a RULE 702 keyword, auto-bound.
    **Documented simplification**: modeled as an ordinary once-per-turn
    trigger that *additionally* creates the copies (`CopyPermanentEffect`'s
    new `attached_permanent` self-mode + `count_from_trigger_event`)
    rather than a true `CREATE_TOKENS` replacement that *redirects*
    (blocks the original tokens and substitutes copies instead) — that
    event's own replacement hook only lets a `ReplacementEffect` rescale
    the *amount*, never swap in a different token identity, and building
    that redirection is real engine plumbing disproportionate to one
    Equipment. The practical difference only matters when a player would
    have preferred *not* getting the original tokens too, which is rare
    for an "instead" upgrade like this one.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {
                "target_kind": "attached_permanent", "count_from_trigger_event": "amount",
            })],
            trigger={
                "event": EventType.CREATE_TOKENS,
                "condition": {"subject": "group", "controller": "you"},
                "limit": True,
                "requires_attached": True,
            },
        ),
    ]


register("Mirrormind Crown", _mirrormind_crown)


def _throne_of_the_god_pharaoh() -> list[AbilitySpec]:
    """At the beginning of your end step, each opponent loses life equal
    to the number of tapped creatures you control.

    — Eliferate deck batch. `LoseLifeEffect`'s new `amount_from_count_
    selector` (the `GainLifeEffect` sibling it never had) reading the new
    `tapped_creatures_you_control` count (`continuous.count_selector`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent", "amount_from_count_selector": "tapped_creatures_you_control",
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "end"},
                "phase_relation": "you",
            },
        ),
    ]


register("Throne of the God-Pharaoh", _throne_of_the_god_pharaoh)


def _trystan_callous_cultivator() -> list[AbilitySpec]:
    """Deathtouch
    Whenever this creature enters or transforms into Trystan, Callous
    Cultivator, mill three cards. Then if there is an Elf card in your
    graveyard, you gain 2 life.
    At the beginning of your first main phase, you may pay {B}. If you do,
    transform Trystan.

    — Eliferate deck batch. Deathtouch is a RULE 702 keyword, auto-bound.
    **Documented simplification**: the "or transforms into ~" half of the
    first trigger isn't modeled — this engine has no `TRANSFORMED` event
    at all yet (a genuinely open engine-primitive gap, not specific to
    this card), so only the ETB half fires; the mill+conditional-lifegain
    body itself is fully modeled (`mill` + `EffectSpec.condition`'s new
    `graveyard_has_type`). The second ability is a plain resolve-time
    `pay_cost_then` (RULE 118.3) wrapping `transform`.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("mill", {"count": 3}),
                EffectSpec("gain_life", {"amount": 2}, condition={"graveyard_has_type": "elf"}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pay_cost_then", {
                "cost": "{B}",
                "effects": [{"type": "transform", "params": {}}],
            })],
            trigger={
                "event": EventType.STEP_BEGIN, "filter": {"step": "main1"},
                "phase_relation": "you",
            },
        ),
    ]


register("Trystan, Callous Cultivator", _trystan_callous_cultivator)
register("Trystan, Callous Cultivator // Trystan, Penitent Culler", _trystan_callous_cultivator)


def _high_perfect_morcant() -> list[AbilitySpec]:
    """Whenever High Perfect Morcant or another Elf you control enters,
    each opponent blights 1. (They each put a -1/-1 counter on a creature
    they control.)
    Tap three untapped Elves you control: Proliferate. Activate only as a
    sorcery.

    — Eliferate deck batch. The activated ability already parses on its
    own — reproduced here verbatim. The ETB trigger is the new
    `each_opponent_counter_own_creature` primitive — see its docstring
    for the documented auto-pick simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("each_opponent_counter_own_creature", {"amount": 1, "kind": "-1/-1"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "subtypes": ["elf"], "controller": "you", "other": True},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("proliferate", {}), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Tap three untapped Elves you control"},
        ),
    ]


register("High Perfect Morcant", _high_perfect_morcant)


def _backdraft_hellkite() -> list[AbilitySpec]:
    """Flying
    Whenever this creature attacks, each instant and sorcery card in your
    graveyard gains flashback until end of turn. The flashback cost is
    equal to its mana cost.

    — Imodane deck batch. Flying is a RULE 702 keyword, auto-bound. The
    grant is the new `grant_graveyard_cast_permission_this_turn` — see
    its docstring for why it's a fresh primitive rather than the existing
    standing `graveyard_cast_permission` (Lurrus-shaped: tied to a
    permanent's continued presence, not turn-scoped).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("grant_graveyard_cast_permission_this_turn", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Backdraft Hellkite", _backdraft_hellkite)


def _blasphemous_act() -> list[AbilitySpec]:
    """This spell costs {1} less to cast for each creature on the
    battlefield.
    Blasphemous Act deals 13 damage to each creature.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. The cost reduction is `cost_reduction`'s existing
    Delve/Affinity-shaped ``per`` count-selector param, just with the new
    unscoped `creatures_on_battlefield` selector instead of the `_you_
    control`-scoped form every existing consumer used.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {
                "affects": "self", "generic": 1, "per": "creatures_on_battlefield",
            })],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 13, "selector": "each_creature"})],
        ),
    ]


register("Blasphemous Act", _blasphemous_act)


def _chain_lightning() -> list[AbilitySpec]:
    """Chain Lightning deals 3 damage to any target. Then that player or
    that permanent's controller may pay {R}{R}. If the player does, they
    may copy this spell and may choose a new target for that copy.

    — Imodane deck batch. **Documented simplification**: the "hot potato"
    copy-chain (control of the copy passes to whichever player just paid,
    who may then trigger *another* copy) isn't modeled — no primitive
    threads a spell copy's "controller" through a resolve-time optional
    payment offered to the *damage recipient* rather than the caster, and
    building one is disproportionate to this one card. Modeled as the
    bare "deals 3 damage to any target."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 3, "target_kind": "any"})],
        ),
    ]


register("Chain Lightning", _chain_lightning)


def _fireblast() -> list[AbilitySpec]:
    """You may sacrifice two Mountains rather than pay this spell's mana
    cost.
    Fireblast deals 4 damage to any target.

    — Imodane deck batch. The damage clause already parses on its own —
    reproduced verbatim. **Documented simplification**: the alternative
    "sacrifice two Mountains instead of paying mana" cost isn't modeled —
    this engine's cost vocabulary has no free-alternative-cost concept
    (RULE 601.2f's own free-cast condition gate is for a fixed condition,
    not a player-chosen cost substitution); the spell is fully castable
    at its normal printed mana cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        ),
    ]


register("Fireblast", _fireblast)


def _frantic_firebolt() -> list[AbilitySpec]:
    """Frantic Firebolt deals X damage to target creature, where X is 2
    plus the number of cards in your graveyard that are instant cards,
    sorcery cards, and/or have an Adventure.

    — Imodane deck batch. `DealDamageEffect`'s new `amount_from_count_
    selector`/`amount_plus_count_selector`, reading the new
    `instant_sorcery_or_adventure_cards_in_your_graveyard` count.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "target_kind": "creature",
                "amount_from_count_selector": "instant_sorcery_or_adventure_cards_in_your_graveyard",
                "amount_plus_count_selector": 2,
            })],
        ),
    ]


register("Frantic Firebolt", _frantic_firebolt)


def _lava_coil() -> list[AbilitySpec]:
    """Lava Coil deals 4 damage to target creature. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. The second clause is the new
    `grant_die_to_exile_this_turn` — see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "creature"}),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
        ),
    ]


register("Lava Coil", _lava_coil)


def _lithomantic_barrage() -> list[AbilitySpec]:
    """This spell can't be countered.
    Lithomantic Barrage deals 1 damage to target creature or planeswalker.
    It deals 5 damage instead if that target is white and/or blue.

    — Imodane deck batch. "Can't be countered" already parses on its own
    — reproduced verbatim. The damage clause is `DealDamageEffect`'s new
    `amount_if_target_color`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("cant_be_countered", {})],
        ),
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": 1, "target_kind": "creature_or_planeswalker",
                "amount_if_target_color": {"amount": 5, "colors": ["W", "U"]},
            })],
        ),
    ]


register("Lithomantic Barrage", _lithomantic_barrage)


def _smite_the_deathless() -> list[AbilitySpec]:
    """Smite the Deathless deals 3 damage to target creature. That
    creature loses indestructible until end of turn. If that creature
    would die this turn, exile it instead.

    — Imodane deck batch. One real target, reused via `grant_until`'s
    `previous_subject` pronoun idiom for both the keyword-removal and the
    die-to-exile grant.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {"amount": 3, "target_kind": "creature"}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "remove_keyword", "params": {"keywords": ["indestructible"]}},
                }),
                EffectSpec("grant_die_to_exile_this_turn", {}),
            ],
        ),
    ]


register("Smite the Deathless", _smite_the_deathless)


def _stonesplitter_bolt() -> list[AbilitySpec]:
    """Bargain
    Stonesplitter Bolt deals X damage to target creature or planeswalker.
    If this spell was bargained, it deals twice X damage to that
    permanent instead.

    — Imodane deck batch. Bargain comes from the RULE 702 keyword
    catalogue automatically. The damage clause is `DealDamageEffect`'s new
    `double_if_bargained`.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "creature_or_planeswalker", "double_if_bargained": True,
            })],
        ),
    ]


register("Stonesplitter Bolt", _stonesplitter_bolt)


def _torch_breath() -> list[AbilitySpec]:
    """This spell costs {2} less to cast if it targets a blue permanent.
    This spell can't be countered.
    Torch Breath deals X damage to target creature or planeswalker.

    — Imodane deck batch. **Documented simplification**: the target-
    dependent cost reduction isn't modeled (RULE 601.2f cost reduction is
    a board-state/count-selector concept everywhere else in this catalogue;
    a reduction keyed off a target chosen *during the same cast* is a
    different, unbuilt timing shape) — the spell is fully castable at its
    normal printed cost.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("cant_be_countered", {}),
                EffectSpec("damage", {"amount": "x", "target_kind": "creature_or_planeswalker"}),
            ],
        ),
    ]


register("Torch Breath", _torch_breath)


def _torch_the_tower() -> list[AbilitySpec]:
    """Bargain
    Torch the Tower deals 2 damage to target creature or planeswalker. If
    this spell was bargained, instead it deals 3 damage to that permanent
    and you scry 1.
    If a permanent dealt damage by Torch the Tower would die this turn,
    exile it instead.

    — Imodane deck batch. Bargain is auto-bound. **Documented
    simplification**: the bargained "and you scry 1" rider isn't modeled
    alongside the amount override (`amount_if_bargained` swaps the number;
    composing it with a *second*, conditional-only-when-bargained effect
    would need `EffectSpec.condition`'s `bargained` key on a *second*
    `scry` effect — omitted here, so a bargained cast deals 3 damage
    without the scry). The die-to-exile clause is the new
    `grant_die_to_exile_this_turn`, unconditional (it applies whichever
    amount was dealt).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("damage", {
                    "amount": 2, "target_kind": "creature_or_planeswalker", "amount_if_bargained": 3,
                }),
                EffectSpec("grant_die_to_exile_this_turn", {"target_kind": None}),
            ],
        ),
    ]


register("Torch the Tower", _torch_the_tower)


def _torch_the_witness() -> list[AbilitySpec]:
    """Torch the Witness deals twice X damage to target creature. If
    excess damage was dealt to that creature this way, investigate.
    (Create a Clue token. It's an artifact with "{2}, Sacrifice this
    token: Draw a card.")

    — Imodane deck batch. The new `damage_then_investigate_if_excess` —
    see its docstring.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage_then_investigate_if_excess", {"target_kind": "creature"})],
        ),
    ]


register("Torch the Witness", _torch_the_witness)


def _voltage_surge() -> list[AbilitySpec]:
    """As an additional cost to cast this spell, you may sacrifice an
    artifact.
    Voltage Surge deals 2 damage to target creature or planeswalker. If
    this spell's additional cost was paid, Voltage Surge deals 4 damage
    instead.

    — Imodane deck batch. **Documented simplification**: the optional
    "you may sacrifice an artifact" additional cost isn't modeled —
    `AbilitySpec.additional_cost`'s closed vocabulary has no *optional*
    sacrifice shape (RULE 702.157's own Bargain keyword is the one
    optional-sacrifice-as-you-cast mechanic this engine has, and this
    card doesn't print it), so building a parallel one-off "may" cost path
    is disproportionate to this one card. Modeled as the unconditional
    base "deals 2 damage" — never the upgraded 4, and never actually
    asking for an artifact.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": 2, "target_kind": "creature_or_planeswalker"})],
        ),
    ]


register("Voltage Surge", _voltage_surge)


def _galvanic_relay() -> list[AbilitySpec]:
    """Exile the top card of your library. During your next turn, you may
    play that card.
    Storm (When you cast this spell, copy it for each spell cast before
    it this turn.)

    — Imodane deck batch. Storm is a RULE 702 keyword, auto-bound. The
    exile clause is the shipped `impulsive_draw` (Light Up the Stage-
    shaped) — "during your next turn" is `same_turn_only=False`'s own
    "until the end of your next turn" window, a superset of the printed
    text rather than a narrower one.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 1})],
        ),
    ]


register("Galvanic Relay", _galvanic_relay)


def _wrenns_resolve() -> list[AbilitySpec]:
    """Exile the top two cards of your library. Until the end of your
    next turn, you may play those cards.

    — Imodane deck batch. The shipped `impulsive_draw`, count=2.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("impulsive_draw", {"count": 2})],
        ),
    ]


register("Wrenn's Resolve", _wrenns_resolve)


def _virtue_of_courage() -> list[AbilitySpec]:
    """Whenever a source you control deals noncombat damage to an
    opponent, you may exile that many cards from the top of your library.
    You may play those cards this turn.

    — Imodane deck batch. `ImpulsiveDrawEffect`'s new `count_from_trigger_
    event` (the firing `DAMAGE` event's own ``amount``), ``same_turn_
    only=True`` for "this turn" rather than "until your next turn". Fixed
    (bug report, 2026-09-04): the recipient half of "you control … to an
    opponent" isn't covered by ``condition``'s ``"group"``/``"controller":
    "you"`` (that only scopes the *source*, not who was hit) — it needs the
    same `requires_damage_to_opponent` predicate (the DAMAGE event's player
    target must be someone other than this ability's own controller) that
    Chandra's Incinerator already established, combined with the DAMAGE
    event's own ``"filter": {"combat": False}`` for "noncombat". The old
    ``"filter": {"is_player": True}`` alone (no opponent check at all)
    let the ability fire — and, via `ImpulsiveDrawEffect`'s own now-fixed
    default-player bug, exile from and grant play permission to a
    *different* player — off the controller's own source dealing combat
    damage, or dealing any damage to themselves.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("impulsive_draw", {
                "count_from_trigger_event": "amount", "same_turn_only": True,
            })],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"combat": False},
                "requires_damage_to_opponent": True,
            },
        ),
    ]


register("Virtue of Courage", _virtue_of_courage)
register("Virtue of Courage // Embereth Blaze", _virtue_of_courage)


def _sunbirds_invocation() -> list[AbilitySpec]:
    """Whenever you cast a spell from your hand, reveal the top X cards of
    your library, where X is that spell's mana value. You may cast a
    spell with mana value X or less from among cards revealed this way
    without paying its mana cost. Put the rest on the bottom of your
    library in a random order.

    — Imodane deck batch. **Documented simplification**: modeled as
    revealing and offering a free cast of only the *top card* of the
    library (not the top X, and without the "mana value X or less"
    filter) — `dig_until`'s existing "reveal until a match, free-cast the
    hit, shuffle/bottom the rest" shape (Tibalt's Trickery/Possibility
    Storm-shaped), reused with an always-true criteria so it stops at
    exactly one card. A criteria keyed to X (the triggering spell's mana
    value) was tried and reverted: `dig_until` reveals cards *until* one
    matches, so on a low X and an unlucky top of library it would dig
    arbitrarily deep — safe for Tibalt's Trickery (nothing shares its
    exact name) but wrong here, where most of a deck's cards have a
    higher mana value than a cheap spell's X. The real card's "look at X
    cards, pick any one of them, mana-value-gated" breadth isn't modeled
    — a genuinely different chooser shape (`dig_until` stops at the first
    match rather than surveying a fixed window) that would need its own
    primitive.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("dig_until", {
                "criteria": "",
                "hit_destination": "cast_free_window",
                "rest_destination": "exile",
            })],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "filter": {"from_hand": True},
            },
        ),
    ]


register("Sunbird's Invocation", _sunbirds_invocation)


def _etali_primal_storm() -> list[AbilitySpec]:
    """Whenever Etali attacks, exile the top card of each player's
    library, then you may cast any number of spells from among those
    cards without paying their mana costs.

    — Imodane deck batch. `exile_top_from_each_player_cast_free` — see its
    docstring. **Bug fixed** (checked against Scryfall's own ruling #5,
    "any cards not cast, including land cards, remain in exile," 2026-09-04):
    the effect used to grant every exiled card — lands included — a
    `grant_free_cast_window_from_exile` permission, and that permission is
    generic enough to also satisfy `GameEngine.can_play_land` (it backs
    cards like Ragavan/Light Up the Stage that genuinely *do* let a found
    land be played) — so an exiled land was wrongly playable as a land.
    The effect now skips the free-cast/-play grant for a land card
    entirely while still exiling it (dead forever, per the ruling).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_from_each_player_cast_free", {})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
        ),
    ]


register("Etali, Primal Storm", _etali_primal_storm)


def _etali_primal_conqueror() -> list[AbilitySpec]:
    """Front face — Etali, Primal Conqueror ({5}{R}{R}, Legendary Creature
    — Elder Dinosaur, 7/7):
    Trample
    When Etali enters, each player exiles cards from the top of their
    library until they exile a nonland card. You may cast any number of
    spells from among the nonland cards exiled this way without paying
    their mana costs.
    {9}{G/P}: Transform Etali. Activate only as a sorcery.

    — checked against Scryfall's own rulings for this card (2026-09-04):
    the whole card had no catalogue entry at all, so it fell back to
    the RULE 702 keyword catalogue's Scryfall-anchored auto-bind alone —
    which would have been actively *wrong* here, not just incomplete.
    Scryfall's *card-level* ``keywords`` array on a transform DFC is the
    union of both faces (this card's is ``["Indestructible", "Transform",
    "Trample"]``), so an unregistered front face would auto-bind the back
    face's own Indestructible too; `remove_keyword` cancels that leak
    explicitly. ("Transform" itself isn't a recognized keyword slug, so it
    parses to nothing either way.) The ETB trigger reuses Etali, Primal
    Storm's `exile_top_from_each_player_cast_free`, widened with
    ``until_nonland=True`` to dig each player's library past any lands to
    the first nonland card (`RulesEngine._exile_top_until`, the same
    "keep exiling past lands" shape cascade/discover already use) instead
    of a fixed single top card — every card exiled along the way,
    including the lands, stays in exile per the ruling; only the nonland
    hit gets a free-cast window. The transform ability is a plain
    `EffectSpec("transform", {})` behind a sorcery-speed Phyrexian-mana
    cost.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec(
            "static",
            [EffectSpec("remove_keyword", {"affects": "self", "keywords": ["indestructible"]})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_top_from_each_player_cast_free", {"until_nonland": True})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("transform", {})],
            cost={"text": "{9}{G/P}", "sorcery_speed_only": True},
        ),
    ]


register("Etali, Primal Conqueror", _etali_primal_conqueror)
register("Etali, Primal Conqueror // Etali, Primal Sickness", _etali_primal_conqueror)


def _etali_primal_sickness() -> list[AbilitySpec]:
    """Back face — Etali, Primal Sickness (Legendary Creature — Phyrexian
    Elder Dinosaur, 11/11):
    Trample, indestructible
    Whenever Etali deals combat damage to a player, they get that many
    poison counters. (A player with ten or more poison counters loses the
    game — a standing rule, not something this ability itself needs to
    enforce; RULE 704's SBA pass already checks poison counters on every
    permission-generating event.)

    — checked against Scryfall's own rulings for this card (2026-09-04).
    `Card.back_face()` carries no keywords array of its own (the same gap
    the Daybound/Nightbound cross-check in `parser.oracle.catalogue.
    keywords.parse_keywords` already works around for other DFCs — see
    `Done_Backend.md`'s Replay-deserializer entry), so Trample/
    Indestructible are hand-authored here rather than left to the RULE 702
    auto-bind, which would otherwise see nothing at all for this face. The
    poison trigger is the new `add_counters_to_trigger_damaged_player`
    (``kind="poison"``) — RULE 603.3d's "they"/"that many" pronouns read
    the firing `DAMAGE` event's own recipient/amount directly, the same
    shape `LoseGameTriggerDamagedPlayerEffect` (Frodo, Sauron's Bane)
    already established for a player-scoped pronoun off that event.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "trample"}),
        AbilitySpec("keyword", [], keyword={"name": "indestructible"}),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters_to_trigger_damaged_player", {"kind": "poison"})],
            trigger={
                "event": EventType.DAMAGE, "condition": {"subject": "self"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Etali, Primal Sickness", _etali_primal_sickness)


def _dual_strike() -> list[AbilitySpec]:
    """When you next cast an instant or sorcery spell with mana value 4
    or less this turn, copy that spell. You may choose new targets for
    the copy.
    Foretell {R}

    — Imodane deck batch. Foretell (RULE 702.166) is a RULE 702 keyword,
    auto-bound. "When you next cast … this turn" is a genuinely new
    primitive, `arm_spell_watcher`/`GameState.spell_watchers` — a one-shot
    watch for the *next* qualifying `SPELL_CAST` this turn, distinct from
    both an ordinary per-firing triggered ability (which only ever fires
    off a matching *object's own* event) and RULE 603.7's fixed-future-
    *step* `CreateDelayedTriggerEffect`. Its `then_specs` tail is the
    already-shipped `copy_spell` (RULE 707.10), applied against the
    just-cast spell's own stack item directly. **Documented
    simplification**: "you may choose new targets for the copy" isn't
    modeled — `CopySpellEffect` already keeps this simplification for
    every other consumer (Reiterate/Dualcaster Mage-shaped), so the copy
    keeps the original's targets.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("arm_spell_watcher", {
                "max_mana_value": 4, "card_types": ["instant", "sorcery"],
                "then_specs": [{"type": "copy_spell", "params": {}}],
            })],
        ),
    ]


register("Dual Strike", _dual_strike)


def _city_on_fire() -> list[AbilitySpec]:
    """Convoke
    If a source you control would deal damage to a permanent or player,
    it deals triple that damage instead.

    — Imodane deck batch. Convoke is a RULE 702 keyword, auto-bound; the
    replacement clause is word-for-word `Fiery Emancipation`'s own
    ``double_damage`` (``multiplier=3``, ``your_sources_only=True``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"multiplier": 3, "your_sources_only": True})],
        ),
    ]


register("City on Fire", _city_on_fire)


def _mana_geyser() -> list[AbilitySpec]:
    """Add {R} for each tapped land your opponents control.

    — Imodane deck batch. `AddManaEffect`'s existing `amount_selector`,
    with the new unscoped-to-opponents `tapped_lands_opponents_control`
    count selector.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("add_mana", {"color": "R", "amount_selector": "tapped_lands_opponents_control"})],
        ),
    ]


register("Mana Geyser", _mana_geyser)


#: Ruby Medallion ("Red spells you cast cost {1} less to cast.") was
#: originally hand-authored here (Imodane deck batch, when `cost_reduction`
#: first gained its `spell_color` filter but the parser had no recognizer
#: for the colour-scoped phrasing yet). `parser/oracle/catalogue/
#: static_handlers.py`'s `_SPELL_COST_TAX_COLOR_RE` now claims the whole
#: Medallion cycle generically — confirmed live: Pearl/Sapphire/Jet/Emerald
#: Medallion all already resolve `coverage=MODELED, hand-authored=False`
#: with the identical `cost_reduction` spec shape. Removed as redundant
#: rather than left as a stale duplicate of what the parser now does on its
#: own (2026-08-27 architecture-efficiency pass, A2/A3/B2).


def _runaway_steam_kin() -> list[AbilitySpec]:
    """Whenever you cast a red spell, if this creature has fewer than
    three +1/+1 counters on it, put a +1/+1 counter on this creature.
    Remove three +1/+1 counters from this creature: Add {R}{R}{R}.

    — Imodane deck batch. The trigger's intervening-if is the new
    ``source_counters_below`` (`effect_binder._trigger_condition`) — the
    counter-count sibling of the shipped ``source_state`` (Mana Vault's
    own "if this artifact is tapped"). The mana ability is a plain
    "remove N counters: add mana" activation cost, recognized directly
    from its printed text by `game/costs.py`'s existing
    `_REMOVE_COUNTERS_RE`.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "+1/+1", "amount": 1, "target_kind": None})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "cast_of_color": "R",
                "source_counters_below": {"kind": "+1/+1", "count": 3},
            },
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("add_mana", {"colors": ["R", "R", "R"]})],
            cost={"text": "Remove three +1/+1 counters from this creature"},
        ),
    ]


register("Runaway Steam-Kin", _runaway_steam_kin)


def _storm_kiln_artist() -> list[AbilitySpec]:
    """This creature gets +1/+0 for each artifact you control.
    Magecraft — Whenever you cast or copy an instant or sorcery spell,
    create a Treasure token.

    — Imodane deck batch. Magecraft already parses on its own —
    reproduced verbatim. The P/T clause is `anthem`'s existing
    ``power_count``, self-scoped, with the existing
    `artifacts_you_control` selector.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "self", "power": 1, "power_count": "artifacts_you_control"})],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Treasure"})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
                "spell_card_types": ["instant", "sorcery"],
            },
        ),
    ]


register("Storm-Kiln Artist", _storm_kiln_artist)


def _koth_fire_of_resistance() -> list[AbilitySpec]:
    """+2: Search your library for a basic Mountain card, reveal it, put
    it into your hand, then shuffle.
    −3: Koth deals damage to target creature equal to the number of
    Mountains you control.
    −7: You get an emblem with "Whenever a Mountain you control enters,
    this emblem deals 4 damage to any target."

    — Imodane deck batch. "+2:" is the generalized search grammar
    (`search`, ``{"basic": True, "type": "Mountain"}``). "−3:" is
    `DealDamageEffect`'s `amount_from_count_selector` (the existing
    `lands_you_control_of_type_mountain`-shaped count already used
    elsewhere for a threshold filter, here as a magnitude instead).
    "−7:" is the quoted-emblem-at-loyalty shape `Tyvar Kell`/`Vraska,
    Golgari Queen` already established — the emblem's own trigger is a
    genuine `ENTERS_BATTLEFIELD` group condition scoped by subtype, no
    different from a permanent's own.
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [EffectSpec("damage", {"amount": 4, "target_kind": "any"})],
        trigger={
            "event": EventType.ENTERS_BATTLEFIELD,
            "condition": {"subject": "group", "subtypes": ["mountain"], "controller": "you"},
        },
    )
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"basic": True, "type": "Mountain"}, "destination": "hand",
            })],
            cost={"loyalty": 2},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {
                "target_kind": "creature", "amount_from_count_selector": "lands_you_control_of_type_mountain",
            })],
            cost={"loyalty": -3},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -7},
        ),
    ]


register("Koth, Fire of Resistance", _koth_fire_of_resistance)


def _stuffy_doll() -> list[AbilitySpec]:
    """Indestructible
    As this creature enters, choose a player.
    Whenever this creature is dealt damage, it deals that much damage to
    the chosen player.
    {T}: This creature deals 1 damage to itself.

    — Imodane deck batch. Indestructible is a RULE 702 keyword, auto-
    bound. The player choice is the new `request_choose_player`
    (`GameObject.chosen_player_id`); the damage-redirect trigger is the
    new `self_as_recipient` trigger subject (the "is dealt damage"
    mirror image of the ordinary source-keyed "self") paired with the
    new `deal_damage_to_chosen_player`, reading the firing event's own
    amount. The activated ability is a plain self-damage.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("request_choose_player", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("deal_damage_to_chosen_player", {})],
            trigger={"event": EventType.DAMAGE, "condition": {"subject": "self_as_recipient"}},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {"amount": 1, "selector": "self"})],
            cost={"text": "{T}"},
        ),
    ]


register("Stuffy Doll", _stuffy_doll)


def _grafted_exoskeleton() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has infect.
    Whenever this Equipment becomes unattached from a permanent,
    sacrifice that permanent.
    Equip {2}

    — Imodane deck batch. The anthem+infect grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: "whenever ~ becomes unattached" isn't modeled —
    this engine has no `attached_to` change event at all yet (every
    detach site — RULE 704.5m/n's illegal-attachment cleanup, a manual
    re-equip — mutates `GameObject.attached_to` directly with no
    broadcast), a genuinely open engine-primitive gap beyond this one
    card, so building it here is disproportionate.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["infect"]}),
            ],
        ),
    ]


register("Grafted Exoskeleton", _grafted_exoskeleton)


def _sword_of_once_and_future() -> list[AbilitySpec]:
    """Equipped creature gets +2/+2 and has protection from blue and
    from black.
    Whenever equipped creature deals combat damage to a player, surveil
    2. Then you may cast an instant or sorcery spell with mana value 2 or
    less from your graveyard without paying its mana cost. If that spell
    would be put into your graveyard, exile it instead.
    Equip {2}

    — Imodane deck batch. The anthem+protection grant and Equip already
    parse on their own — reproduced verbatim. **Documented
    simplification**: only "surveil 2" is modeled — the trailing "cast an
    instant or sorcery spell with mana value 2 or less from your
    graveyard without paying its mana cost" needs a chooser over
    graveyard cards matching a filter, cast *for free*; the shipped
    graveyard-cast machinery covers either half alone (`dig_until`'s
    ``cast_free_window`` operates on the *library*, not the graveyard;
    `GraveyardCastPermissionEffect`'s graveyard permission is always at
    normal mana cost, never free) but not their combination, so building
    that chooser is disproportionate to this one card.
    """
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("grant_protection_static", {
                    "affects": "attached_permanent", "protections": ["blue", "black"],
                }),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("surveil", {"count": 2})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {"subject": "attached_permanent"},
                "filter": {"combat": True, "is_player": True},
            },
        ),
    ]


register("Sword of Once and Future", _sword_of_once_and_future)


def _invasion_of_kaldheim() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, exile all cards from your hand, then draw
    that many cards. Until the end of your next turn, you may play cards
    exiled this way.

    — Imodane deck batch. The RULE 310 battle mechanics (protector
    choice, attackability, defeat/transform cycle) are all engine-level
    and need no hand-authoring. The ETB is the new
    `exile_hand_then_draw_that_many` — see its docstring for the
    documented simplification.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile_hand_then_draw_that_many", {})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Invasion of Kaldheim", _invasion_of_kaldheim)
register("Invasion of Kaldheim // Pyre of the World Tree", _invasion_of_kaldheim)


def _invasion_of_regatha() -> list[AbilitySpec]:
    """(As a Siege enters, choose an opponent to protect it. You and
    others can attack it. When it's defeated, exile it, then cast it
    transformed.)
    When this Siege enters, it deals 4 damage to another target battle
    or opponent and 1 damage to up to one target creature.

    — Imodane deck batch. Two independent targeting effects on one
    trigger, gathered one at a time (`_continue_trigger_multi_target`,
    RULE 603.1) rather than `GameEffect.extra_target_specs` — `damage`
    itself only ever reads a single flat targets list, so the second
    requirement needs its own effect, not a bolt-on second target on the
    first. The new `battle_or_opponent` target kind covers the first.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("damage", {"amount": 4, "target_kind": "battle_or_opponent"}),
                EffectSpec("damage", {"amount": 1, "target_kind": "creature", "optional": True}),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
        ),
    ]


register("Invasion of Regatha", _invasion_of_regatha)
register("Invasion of Regatha // Disciples of the Inferno", _invasion_of_regatha)


def _magda_the_hoardmaster() -> list[AbilitySpec]:
    """Whenever you commit a crime, create a tapped Treasure token. This
    ability triggers only once each turn. (Targeting opponents, anything
    they control, and/or cards in their graveyards is a crime.)
    Sacrifice three Treasures: Create a 4/4 red Scorpion Dragon creature
    token with flying and haste. Activate only as a sorcery.

    — Imodane deck batch. The sacrifice ability already parses on its
    own — reproduced verbatim. **Documented simplification**: "whenever
    you commit a crime" (RULE 701.53 — targeting an opponent, anything
    they control, or a card in their graveyard) isn't modeled — no
    single event unifies "any targeting effect resolving against
    anything opponent-owned" across every effect family in this engine
    (damage, destroy, exile, counter-removal, graveyard recursion, …), so
    the trigger never fires; the treasure-cost payoff still works once
    Treasures exist from any other source.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 4, "toughness": 4, "colors": ["R"],
                "subtypes": ["Scorpion", "Dragon"], "keywords": ["flying", "haste"],
                "token_name": "Scorpion Dragon",
            }), EffectSpec("sorcery_speed_marker", {})],
            cost={"text": "Sacrifice three Treasures"},
        ),
    ]


register("Magda, the Hoardmaster", _magda_the_hoardmaster)


def _birgi_god_of_storytelling() -> list[AbilitySpec]:
    """Whenever you cast a spell, add {R}. Until end of turn, you don't
    lose this mana as steps and phases end.
    Creatures you control can boast twice during each of your turns
    rather than once.

    — Imodane deck batch. **Documented simplification**: modeled as a
    plain "whenever you cast a spell, add {R}" (the mana empties at the
    end of the current step/phase as usual, RULE 500.4 — no primitive
    marks specific floating mana as persisting past that) — no mana
    *ritual* value is lost for a spell cast with priority still to
    follow, only the "bank it for later this turn" upside. "Boast twice"
    isn't modeled at all: RULE 702.161's Boast keyword itself has no
    engine primitive yet (no Boast-printing card is in either deck), so
    there's nothing to double.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"colors": ["R"]})],
            trigger={
                "event": EventType.SPELL_CAST,
                "condition": {"subject": "group", "controller": "you"},
            },
        ),
    ]


register("Birgi, God of Storytelling", _birgi_god_of_storytelling)
register("Birgi, God of Storytelling // Harnfel, Horn of Bounty", _birgi_god_of_storytelling)


def _display_of_power() -> list[AbilitySpec]:
    """This spell can't be copied.
    Copy any number of target instant and/or sorcery spells. You may
    choose new targets for the copies.

    — Imodane deck batch. "Any number of target spells" is the RULE
    601.2c "any number" idiom Fire Covenant's own ``count=10`` UI cap
    already established, applied to `CopySpellEffect`'s ``target_count``
    (new — every prior copy-spell card only ever named one target).
    **Documented simplification**: "This spell can't be copied" (RULE
    707.12) isn't modeled — no spell-copy-immunity primitive exists yet,
    and nothing in either deck tries to copy a spell that's still on the
    stack as a copy target — so it's harmless in practice; "you may
    choose new targets for the copies" is the same already-documented
    MVP `CopySpellEffect` simplification every other copy-spell card in
    this catalogue shares (keeps the original's targets).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("copy_spell", {
                "card_types": ["instant", "sorcery"], "target_count": 10, "optional": True,
            })],
        ),
    ]


register("Display of Power", _display_of_power)


def _gamble() -> list[AbilitySpec]:
    """Search your library for a card, put that card into your hand,
    discard a card at random, then shuffle.

    — Imodane deck batch. **Documented simplification**: "at random"
    becomes an ordinary discard choice — the same simplification
    Indoraptor, the Perfect Hybrid's own "choose an opponent at random"
    already established in this catalogue (a real choice instead of
    randomness has no rules-relevant difference an MVP needs to model).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("search", {"criteria": "", "destination": "hand"}),
                EffectSpec("discard", {"count": 1}),
            ],
        ),
    ]


register("Gamble", _gamble)


def _jayas_immolating_inferno() -> list[AbilitySpec]:
    """(You may cast a legendary sorcery only if you control a legendary
    creature or planeswalker.)
    Jaya's Immolating Inferno deals X damage to each of up to three
    targets.

    — Imodane deck batch. "To each of up to three targets" is
    `DealDamageEffect`'s existing ``count``/``optional`` "up to N
    targets" shape (Volcanic Salvo-shaped), unchanged; X is the spell's
    own announced {X}, substituted the same way every other X-damage
    spell in this catalogue already reads it. **Documented
    simplification**: the Legendary Sorcery casting restriction (control
    a legendary creature or planeswalker) isn't enforced — no card-type-
    supertype casting gate exists in `can_cast` yet — so the spell casts
    like an ordinary sorcery; the damage itself is fully modeled.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("damage", {"amount": "x", "target_kind": "any", "count": 3, "optional": True})],
        ),
    ]


register("Jaya's Immolating Inferno", _jayas_immolating_inferno)


def _avatar_aang() -> list[AbilitySpec]:
    """Flying, firebending 2
    Whenever you waterbend, earthbend, firebend, or airbend, draw a card.
    Then if you've done all four this turn, transform Avatar Aang.

    — PAR-30 ("Firebending grants residue" — the last open sub-bullet of
    that ticket). Flying + Firebending 2 are RULE 702 keywords, auto-bound
    on the front face off `Card.keywords`; the Firebending attack trigger
    now *also* fires `EventType.BENT` (`effect_binder._kw_firebending`
    appends a `RecordBendEffect`), joining the three other bending
    primitives that gained the same event this batch — `RulesEngine.
    earthbend`, the waterbend additional-cast-cost payment (RULE 701.67c),
    and airbend (`ExileEffect.bend_kind`). So the one trigger below reacts
    to all four via `{"subject": "you"}` on `BENT` (the "whenever **you**
    scry/surveil" idiom, `_GROUP_CONTROLLER_EVENT_KEYS["BENT"]`).

    The reflexive "then if you've done all four this turn, transform ~." is
    `EffectSpec.condition`'s new `did_all_bends_this_turn` key — the
    ability controller's `GameState.bends_this_turn` set (cleared each
    `begin_turn`) must cover every entry of `RulesEngine.BEND_KINDS`.
    `transform` with no target flips the source DFC (RULE 712.8); the
    engine rebinds the back face ("Aang, Master of Elements") off its own
    name through the ordinary parser fallback, so nothing here need author
    it.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("draw", {"count": 1}),
                EffectSpec("transform", {}, condition={"did_all_bends_this_turn": True}),
            ],
            trigger={"event": EventType.BENT, "condition": {"subject": "you"}},
        ),
    ]


register("Avatar Aang", _avatar_aang)
register("Avatar Aang // Aang, Master of Elements", _avatar_aang)


