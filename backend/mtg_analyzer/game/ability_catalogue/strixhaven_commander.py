"""Hand-authored Strixhaven Commander card abilities."""

from __future__ import annotations

from ...models.game.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register

# ---------------------------------------------------------------------------
# Lands
# ---------------------------------------------------------------------------


def _fabled_passage() -> list[AbilitySpec]:
    """"{T}, Sacrifice this land: Search your library for a basic land card,
    put it onto the battlefield tapped, then shuffle. Then if you control
    four or more lands, untap that land." — a conditional-untap fetch, the
    Evolving Wilds shape plus the `untap_if_lands_at_least` search param
    (RULE 701.19; the fetched land counts itself in the total)."""
    # "four or more lands" — the trailing-conditional threshold on Fabled
    # Passage; the fetched land has already entered when the test is made.
    FABLED_PASSAGE_LAND_THRESHOLD = 4
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec(
                    "search",
                    {
                        "criteria": {"basic": True},
                        "destination": "battlefield_tapped",
                        "count": 1,
                        "optional": True,
                        "untap_if_lands_at_least": FABLED_PASSAGE_LAND_THRESHOLD,
                    },
                )
            ],
            cost={"text": "{T}, Sacrifice ~"},
        )
    ]


register("Fabled Passage", _fabled_passage)


# ---------------------------------------------------------------------------
# Silverquill — the Impetus Aura cycle (Crimson Vow Commander). Each is
# "Enchant creature" (folds in from the RULE 702.5 keyword catalogue) + a
# "gets +N/+N and is goaded" static + one more clause the parser can't
# claim on its own. See PAR-60.
# ---------------------------------------------------------------------------


def _parasitic_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +2/+2 and is goaded.
    Whenever enchanted creature attacks, its controller loses 2 life and you
    gain 2 life.

    — Parasitic Impetus. The static (`anthem` + `goaded`, both scoped
    ``attached_permanent``) the parser already claims, re-authored here
    because a registered card takes its whole spec set from this file. The
    attack trigger's "its controller" is the enchanted creature (RULE
    303.4c) → `LoseLifeEffect.selector="attached_permanent_controller"`."""
    IMPETUS_DRAIN = 2
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 2, "toughness": 2}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("lose_life", {
                    "amount": IMPETUS_DRAIN, "selector": "attached_permanent_controller",
                }),
                EffectSpec("gain_life", {"amount": IMPETUS_DRAIN}),
            ],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Parasitic Impetus", _parasitic_impetus)


def _martial_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1 and is goaded.
    Whenever enchanted creature attacks, each other creature that's attacking
    one of your opponents gets +1/+1 until end of turn.

    — Martial Impetus. Documented simplification: the parser/engine has no
    "attacking one of *your* opponents" attacker selector, so the temp pump
    is modeled with the existing ``other_attacking_creatures`` group
    selector (every other attacker). Differs only in a multi-opponent game
    where an attacker is swinging at *you* — rare, and the goad on the
    enchanted creature already pushes it away from you anyway."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("pump", {"power": 1, "toughness": 1, "selector": "other_attacking_creatures"})],
            trigger={"event": "ATTACKS", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Martial Impetus", _martial_impetus)


def _ghoulish_impetus() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature gets +1/+1, has deathtouch, and is goaded.
    When enchanted creature dies, return this card to the battlefield at the
    beginning of the next end step.

    — Ghoulish Impetus. The return is a RULE 603.7 delayed trigger armed by
    the enchanted creature's death: at the next end step,
    `return_self_from_graveyard` puts the Aura back (its own "Enchant
    creature" ETB re-attaches it, from the keyword catalogue)."""
    return [
        AbilitySpec(
            "static",
            [
                EffectSpec("anthem", {"affects": "attached_permanent", "power": 1, "toughness": 1}),
                EffectSpec("grant_keyword", {"affects": "attached_permanent", "keywords": ["deathtouch"]}),
                EffectSpec("goaded", {"affects": "attached_permanent"}),
            ],
        ),
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_delayed_trigger", {
                    "step": "end",
                    "scope": "any",
                    "effects": [{"type": "return_self_from_graveyard", "params": {}}],
                    "description": "Ghoulish Impetus: Aura zurückbringen",
                }),
            ],
            trigger={"event": "DIES", "condition": {"subject": "attached_permanent"}},
        ),
    ]


register("Ghoulish Impetus", _ghoulish_impetus)


# ---------------------------------------------------------------------------
# The Charm / Command modal spells (STX). The fail-closed parser claims most
# modes on their own but each spell has one mode built on a family the
# grammar can't yet reach, so the whole "choose N —" block fail-closes.
# Authored wholesale; every mode below is an ordinary parser-shaped
# EffectSpec bar the one noted per card. See PAR-60.
# ---------------------------------------------------------------------------


def _quandrix_command() -> list[AbilitySpec]:
    """Choose two —
    • Return target creature or planeswalker to its owner's hand.
    • Counter target artifact or enchantment spell.
    • Put two +1/+1 counters on target creature.
    • Target player shuffles up to three target cards from their graveyard
      into their library.

    Modes 1-3 are exactly what `match_clause` already emits. Mode 4 is the
    new `ShuffleTargetGraveyardCardsIntoLibraryEffect`
    ("shuffle_target_graveyard_cards_into_library") — the spell's controller
    picks up to three cards in the targeted player's graveyard at
    resolution (RULE 601.2c) and each returns to that player's library,
    which is then shuffled (RULE 701.20). Modeled with a
    `_request_choose_objects` rather than three separate card targets, an
    accepted RULE 115 precision loss."""
    QUANDRIX_COUNTERS = 2
    QUANDRIX_GY_CARD_CAP = 3
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [EffectSpec("return_to_hand", {"target_kind": "creature_or_planeswalker"})],
                    [EffectSpec("counter", {"card_types": ["artifact", "enchantment"]})],
                    [EffectSpec("add_counters", {
                        "count": QUANDRIX_COUNTERS, "kind": "+1/+1", "target_kind": "creature",
                    })],
                    [EffectSpec("shuffle_target_graveyard_cards_into_library", {
                        "count_max": QUANDRIX_GY_CARD_CAP,
                    })],
                ],
                "descriptions": [
                    "Bringe eine Zielkreatur oder einen Zielplaneswalker auf die Hand ihres Besitzers zurück.",
                    "Neutralisiere einen Ziel-Artefakt- oder -Verzauberungszauberspruch.",
                    "Lege zwei +1/+1-Marken auf eine Zielkreatur.",
                    "Ein Zielspieler mischt bis zu drei Zielkarten aus seinem Friedhof in seine Bibliothek.",
                ],
            },
        )
    ]


register("Quandrix Command", _quandrix_command)


def _lorehold_charm() -> list[AbilitySpec]:
    """Choose one —
    • Each opponent sacrifices a nontoken artifact of their choice.
    • Return target artifact or creature card with mana value 2 or less from
      your graveyard to the battlefield.
    • Creatures you control get +1/+1 and gain trample until end of turn.

    Mode 2 is `return_from_graveyard` over the existing
    ``graveyard_artifact_or_creature`` kind with a ``max_mana_value`` cap
    (both already wired in `targeting`). Documented simplification: mode 1's
    "**nontoken**" narrowing isn't expressible on `SacrificeEffect.what`, so
    it sacrifices any artifact — an opponent almost never prefers to feed a
    Treasure/Clue token to it anyway."""
    LOREHOLD_REANIMATE_MV = 2
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 1,
                "options": [
                    [EffectSpec("sacrifice", {
                        "selector": "each_opponent", "what": "artifact", "count": 1,
                    })],
                    [EffectSpec("return_from_graveyard", {
                        "target_kind": "graveyard_artifact_or_creature",
                        "destination": "battlefield",
                        "max_mana_value": LOREHOLD_REANIMATE_MV,
                    })],
                    [EffectSpec("pump", {
                        "power": 1, "toughness": 1, "keywords": ["trample"],
                        "selector": "creatures_you_control",
                    })],
                ],
                "descriptions": [
                    "Jeder Gegner opfert ein Artefakt seiner Wahl.",
                    "Bringe eine Ziel-Artefakt- oder -Kreaturenkarte mit Manawert 2 oder weniger aus deinem Friedhof ins Spiel zurück.",
                    "Kreaturen unter deiner Kontrolle erhalten +1/+1 und Trampelschaden bis zum Ende des Zuges.",
                ],
            },
        )
    ]


register("Lorehold Charm", _lorehold_charm)


def _witherbloom_command() -> list[AbilitySpec]:
    """Choose two —
    • Target player mills three cards, then you return a land card from your
      graveyard to your hand.
    • Destroy target noncreature, nonland permanent with mana value 2 or less.
    • Target creature gets -3/-1 until end of turn.
    • Target opponent loses 2 life and you gain 2 life.

    Mode 1 is a `mill` (targeted player) followed by a `return_from_graveyard`
    of a land to hand — non-targeted on the card, modeled as a
    ``graveyard_land`` target in the controller's own graveyard (accepted
    RULE 115 precision loss). Mode 2 uses the new
    ``noncreature_nonland_permanent`` target kind (`nonland_permanent` minus
    creatures) with a ``max_mana_value`` cap. Modes 3-4 are exactly what
    `match_clause` emits, mode 4 split into its `lose_life` + `gain_life`
    halves."""
    WITHERBLOOM_MILL = 3
    WITHERBLOOM_DESTROY_MV = 2
    WITHERBLOOM_DRAIN = 2
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "choose": 2,
                "options": [
                    [
                        EffectSpec("mill", {"count": WITHERBLOOM_MILL, "target_kind": "player"}),
                        EffectSpec("return_from_graveyard", {
                            "target_kind": "graveyard_land", "destination": "hand",
                        }),
                    ],
                    [EffectSpec("destroy", {
                        "target_kind": "noncreature_nonland_permanent",
                        "max_mana_value": WITHERBLOOM_DESTROY_MV,
                    })],
                    [EffectSpec("pump", {"power": -3, "toughness": -1, "target_kind": "creature"})],
                    [
                        EffectSpec("lose_life", {"amount": WITHERBLOOM_DRAIN, "target_kind": "opponent"}),
                        EffectSpec("gain_life", {"amount": WITHERBLOOM_DRAIN}),
                    ],
                ],
                "descriptions": [
                    "Ein Zielspieler legt drei Karten von seiner Bibliothek in seinen Friedhof, dann bringst du eine Landkarte aus deinem Friedhof auf deine Hand zurück.",
                    "Zerstöre eine bleibende Nichtkreatur-Nichtland-Zielkarte mit Manawert 2 oder weniger.",
                    "Eine Zielkreatur erhält -3/-1 bis zum Ende des Zuges.",
                    "Ein Zielgegner verliert 2 Lebenspunkte und du erhältst 2 Lebenspunkte.",
                ],
            },
        )
    ]


register("Witherbloom Command", _witherbloom_command)
