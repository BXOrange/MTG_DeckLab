from __future__ import annotations

from ....models.game.events import EventType
from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _tyvar_kell() -> list[AbilitySpec]:
    """Elves you control have "{T}: Add {B}."
    +1: Put a +1/+1 counter on up to one target Elf. Untap it. It gains
    deathtouch until end of turn.
    0: Create a 1/1 green Elf Warrior creature token.
    −6: You get an emblem with "Whenever you cast an Elf spell, it gains
    haste until end of turn and you draw two cards."

    — Tyvar Kell. The static mana grant is a layer-6 ability-adding grant
    (RULE 613.7f) — despite CR 612.1's mention of text "granted … by other
    effects", this is *not* layer 3/RULE 612 (see `game/continuous.py`'s
    module docstring); it's the same layer as `grant_keyword`, just
    granting `{"B": 1}` mana production instead of a keyword slug.
    `mana_abilities.mana_options_for` folds it onto whatever the Elf
    already taps for.

    Eliferate deck batch (all three loyalty abilities were previously
    unmodeled — hand-authoring a card wholesale-replaces the parser's own
    output, `specs_for`'s registry-wins precedence, so a static-only entry
    silently dropped them even where the parser alone could already model
    the "0:" ability). "+1:"'s combo body is
    `effects.CounterUntapGrantKeywordEffect` (put a counter, untap, grant a
    keyword — one atomic effect over one shared target, `CounterAndFirst
    StrikeEffect`'s established "avoid a second target prompt" shape,
    generalized with an untap step and a caller-chosen keyword), targeting
    `creature_filter={"subtype": "Elf"}` (any Elf, not just yours — RAW has
    no "you control" on this one). "−6:"'s emblem quotes a genuine nested
    `AbilitySpec` (RULE 114.2, the same shape the oracle-text parser's own
    `_emblem_ability_spec` builds, just constructed directly here since
    there's no card text to recursively parse) combining a new
    `effects.GrantKeywordToTriggerSubjectEffect` ("it gains haste" — RULE
    603.1's "it" pronoun resolves to whatever `SPELL_CAST` event fired the
    trigger) with a plain draw.
    """
    emblem_ability = AbilitySpec(
        "triggered",
        [
            EffectSpec("grant_keyword_to_trigger_subject", {"keyword": "haste"}),
            EffectSpec("draw", {"count": 2}),
        ],
        trigger={
            "event": EventType.SPELL_CAST,
            "condition": {"subject": "group", "subtypes": ["elf"], "controller": "you"},
        },
    )
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec(
                    "grant_mana_ability",
                    {"affects": "creatures_you_control", "subtype": "Elf", "mana": [{"B": 1}]},
                )
            ],
        ),
        AbilitySpec(
            "activated",
            [
                # ENG-37 B4: "Put a +1/+1 counter on up to one target Elf.
                # Untap it. It gains deathtouch until end of turn." — one
                # announced (optional) target on the counter clause; `tap`
                # and `grant_until` reach the same creature through their
                # ``previous_subject`` pronoun, retiring the fused
                # ``counter_untap_grant_keyword``.
                EffectSpec("add_counters", {
                    "kind": "+1/+1", "amount": 1, "target_kind": "creature",
                    "optional": True, "creature_filter": {"subtype": "Elf"},
                }),
                EffectSpec("tap", {"untap": True, "previous_subject": True}),
                EffectSpec("grant_until", {
                    "duration": "end_of_turn", "previous_subject": True,
                    "static": {"type": "grant_keyword", "params": {"keywords": ["deathtouch"]}},
                }),
            ],
            cost={"loyalty": 1},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["G"],
                "subtypes": ["Elf", "Warrior"], "keywords": [], "token_name": "Elf Warrior",
            })],
            cost={"loyalty": 0},
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {"ability": emblem_ability.to_dict()})],
            cost={"loyalty": -6},
        ),
    ]


register("Tyvar Kell", _tyvar_kell)
