from __future__ import annotations

from ....parser.oracle.spec import AbilitySpec, EffectSpec
from ...card_registry.core import register


def _ashaya_soul_of_the_wild() -> list[AbilitySpec]:
    """Ashaya's power and toughness are each equal to the number of lands
    you control.
    Nontoken creatures you control are Forest lands in addition to their
    other types. (They're still affected by summoning sickness.)

    — Both clauses are genuinely new ground for the layer engine (MEC-12),
    not reachable by the oracle-text parser today. The first is RULE
    604.3's ordinary characteristic-defining P/T, built on `pt_cda`
    (registered in `effects.py` since an earlier batch but never bound by
    any card until now) reading the already-existing ``"lands_you_control"``
    `continuous.count_selector`. The second is the *reverse* direction of
    every other "X becomes a land" grant this engine has modeled so far — a
    creature gaining the land type, rather than a land gaining the creature
    type — which needed two things: `continuous.affected_objects`'s new
    ``"nontoken_creatures_you_control"`` scope (RULE 108.3's token filter
    applied to the ordinary controller-scoped creature set), and a real,
    general latent bug fix: `GameObject.is_land` had only ever read the
    printed card, never folding in a layer-4 `add_types` grant the way
    `is_creature` already does — so *no* card could ever have made
    something a land this way, regardless of phrasing. Fixed generally
    (mirrors `is_creature`'s own printed-or-added/removed pattern) rather
    than special-cased for this card; Kamahl, Heart of Krosa's own land-to-
    creature direction (this same batch) doesn't depend on it, since
    `is_creature` already had the fix, but any future "a land becomes a
    creature and loses land-ness" or "a creature becomes a land" card now
    reads correctly either way. Once `is_land` is fixed, the Forest subtype
    grant automatically reaches `mana_abilities._derived_basic_mana_
    options`'s existing RULE 305.6 "a land with a basic land type has that
    type's intrinsic mana ability" pass — so a creature Ashaya grants
    Forest to picks up "{T}: Add {G}." with no extra code — and equally
    automatically becomes a legal casualty of land destruction. The
    reminder text's "still affected by summoning sickness" needs no code:
    nothing about gaining an additional type touches `GameObject.
    summoning_sick`.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("pt_cda", {
                "affects": "self",
                "power_count": "lands_you_control", "toughness_count": "lands_you_control",
            })],
        ),
        AbilitySpec(
            "static",
            [EffectSpec("type_change", {
                "affects": "nontoken_creatures_you_control",
                "add_types": ["land"], "add_subtypes": ["Forest"],
            })],
        ),
    ]


register("Ashaya, Soul of the Wild", _ashaya_soul_of_the_wild)
