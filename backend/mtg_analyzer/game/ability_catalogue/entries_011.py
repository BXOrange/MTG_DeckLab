"""Card -> AbilitySpec catalogue entries, part 011 of 016.

Mechanically split, in original file order, from the single flat
`ability_catalogue.py` module (now `core.py` for the shared registry
infrastructure + this package's `entries_NNN.py` files for the actual
per-card factories). Boundaries are purely positional -- not organized
by mechanic or card type -- see `__init__.py` for the full picture.
"""

from __future__ import annotations

from ...models.events import EventType
from ...parser.oracle.spec import AbilitySpec, EffectSpec

from .core import register
from .families import register_family

def _mystic_sanctuary() -> list[AbilitySpec]:
    """({T}: Add {U}.)
    This land enters tapped unless you control three or more other
    Islands.
    When this land enters untapped, you may put target instant or
    sorcery card from your graveyard on top of your library.

    — Mystic Sanctuary. Its enters-tapped clause needed a new `lands.py`
    ``unless_count`` variant (a specific land *type*, "other Islands",
    rather than any other land or every basic — the "Sanctuary" cycle);
    the ETB trigger needed the new `EffectSpec.condition` key
    ``source_entered_untapped`` (RULE 614.1's own settled-before-ETB
    ordering) and `ReturnToLibraryEffect`'s existing ``graveyard_instant_
    or_sorcery`` target kind.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("return_to_library", {
                "target_kind": "graveyard_instant_or_sorcery", "position": "top", "optional": True,
            }, condition={"source_entered_untapped": True})],
            trigger={"event": "ENTERS_BATTLEFIELD", "condition": {"subject": "self"}},
            raw_text="When this land enters untapped, you may put target "
                     "instant or sorcery card from your graveyard on top "
                     "of your library.",
        ),
    ]


register("Mystic Sanctuary", _mystic_sanctuary)


# ---------------------------------------------------------------------------
# MEC-30: carding the standing `prevent_damage` replacement family — the
# irregular/compound cards a generic parser regex can't cleanly cover (see
# `parser/oracle/catalogue/replacements.py` for the regular Sphere/Urza's
# Armor/Shield of the Realm shapes this doesn't repeat).
# ---------------------------------------------------------------------------


def _swans_of_bryn_argoll() -> list[AbilitySpec]:
    """Flying
    If a source would deal damage to this creature, prevent that damage.
    The source's controller draws cards equal to the damage prevented this
    way.

    — Flying is the ordinary RULE 702 keyword fold-in (unaffected by this
    registration). The prevention is a plain `"prevent_damage"` replacement
    (``to="self"``, ``amount="all"``) with the new ``rider`` param —
    ``{"kind": "draw_cards", "recipient": "source_controller"}`` fires
    `RulesEngine.apply_prevent_rider`'s draw once the *actual* prevented
    amount is known, off whichever source dealt the damage (not this
    creature's own controller).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "self", "amount": "all",
                "rider": {"kind": "draw_cards", "recipient": "source_controller"},
            })],
            raw_text="Falls eine Quelle dieser Kreatur Schaden zufügen würde, "
                     "verhindere diesen Schaden. Die beherrschende Spielerin "
                     "oder der beherrschende Spieler dieser Quelle zieht so "
                     "viele Karten, wie Schaden auf diese Weise verhindert wurde.",
        ),
    ]


register("Swans of Bryn Argoll", _swans_of_bryn_argoll)


def _hostility() -> list[AbilitySpec]:
    """Haste
    If a spell you control would deal damage to an opponent, prevent that
    damage. Create a 3/1 red Elemental Shaman creature token with haste for
    each 1 damage prevented this way.
    When Hostility is put into a graveyard from anywhere, shuffle it into
    its owner's library.

    — Haste is the ordinary keyword fold-in. The prevention/token half is a
    ``"prevent_damage"`` replacement: ``to="opponent_player"`` (any player
    other than this permanent's controller — the new recipient kind, no
    real card needed it before), ``source_filter={"is_spell": True,
    "controller": "you"}`` (RULE 609.7a — reuses the DAMAGE event's own
    precomputed ``source_is_instant_or_sorcery`` flag as "is a spell", the
    same stand-in `_additional_damage_replacement`'s own "artifact" check
    already leans on for a source characteristic the event has no dedicated
    flag for), and the new ``rider={"kind": "create_tokens_scaled", ...}``.

    The graveyard-to-library shuffle trigger ("put into a graveyard from
    **anywhere**") is a real, separate RULE 400.7-adjacent primitive this
    engine has no "shuffle just this one card back into its owner's
    library on death" shape for yet (`shuffle_graveyard_into_library`
    shuffles the *whole* graveyard) — left as a documented simplification
    rather than blocking the card's own headline mechanic on it.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "opponent_player",
                "source_filter": {"is_spell": True, "controller": "you"},
                "amount": "all",
                "rider": {
                    "kind": "create_tokens_scaled",
                    "recipient": "you",
                    "token": {
                        "token_name": "Elemental Shaman", "power": 3, "toughness": 1,
                        "colors": ["R"], "subtypes": ["Elemental", "Shaman"], "keywords": ["haste"],
                    },
                },
            })],
            raw_text="Falls ein Zauberspruch, den du kontrollierst, einer "
                     "gegnerischen Person Schaden zufügen würde, verhindere "
                     "diesen Schaden. Erzeuge für je 1 auf diese Weise "
                     "verhinderten Schaden einen 3/1 roten Elementarwesen-"
                     "Schamane-Kreaturenspielstein mit Hast.",
        ),
    ]


register("Hostility", _hostility)


def _gisela_blade_of_goldnight() -> list[AbilitySpec]:
    """Flying, first strike
    If a source would deal damage to an opponent or a permanent an
    opponent controls, that source deals double that damage to that
    player or permanent instead.
    If a source would deal damage to you or a permanent you control,
    prevent half that damage, rounded up.

    — Flying/first strike are the ordinary keyword fold-in. The two
    replacements are independent and both fire off *any* source
    (unqualified), one already-shipped (`double_damage`, opponent-scoped
    via ``to_opponent_only``), one new (`prevent_damage`'s
    ``recipient_union=["controller", {}]`` — "you or a permanent you
    control", an empty filter dict matching any controlled permanent —
    and ``amount={"half": "up"}``).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("double_damage", {"to_opponent_only": True})],
            raw_text="Falls eine Quelle einer gegnerischen Person oder einem "
                     "bleibenden Kartenbild, das eine gegnerische Person "
                     "kontrolliert, Schaden zufügen würde, fügt diese Quelle "
                     "stattdessen den doppelten Schaden zu.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": {"half": "up"},
            })],
            raw_text="Falls eine Quelle dir oder einem bleibenden Kartenbild, "
                     "das du kontrollierst, Schaden zufügen würde, verhindere "
                     "die Hälfte dieses Schadens, aufgerundet.",
        ),
    ]


register("Gisela, Blade of Goldnight", _gisela_blade_of_goldnight)


# ---------------------------------------------------------------------------
# Circle of Protection cycle: "{N}: The next time a <qualifier> source of
# your choice would deal damage to you this turn, prevent that damage." —
# same `RequestPreventDamageSourceEffect` template (`RulesEngine.request_
# choose_objects`'s interactive "choose a source" pick over every
# battlefield permanent matching `source_filter`, then a `RulesEngine.
# prevent_damage_to_player`-shaped shield scoped to whichever one gets
# picked; repeatable — nothing marks the ability itself once-per-turn,
# matching the real printed text) across all seven members, differing only
# in `source_filter`, one member's own cost (Artifacts is {2} where the
# rest of the cycle is {1}), and the (German) `raw_text`. Also see the
# Rune of Protection cycle below (same `register_family` helper, see
# `families.py`) and Story Circle/Prismatic Circle/Circle of Solace
# further down, which reuse this exact shield shape but pick their colour
# interactively at ETB (RULE 601.2b) rather than printing it, and so
# aren't a fit for this templating.
# ---------------------------------------------------------------------------

register_family(
    ability_kind="activated",
    effect_type="request_prevent_damage_source",
    base_params={"amount": "all"},
    base_cost={"mana": "{1}"},
    entries=[
        ("Circle of Protection: Red", {"source_filter": {"color": "R"}},
         "{1}: Verhindere den nächsten Schaden, den eine rote Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Circle of Protection: White", {"source_filter": {"color": "W"}},
         "{1}: Verhindere den nächsten Schaden, den eine weiße Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Circle of Protection: Black", {"source_filter": {"color": "B"}},
         "{1}: Verhindere den nächsten Schaden, den eine schwarze Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Circle of Protection: Blue", {"source_filter": {"color": "U"}},
         "{1}: Verhindere den nächsten Schaden, den eine blaue Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Circle of Protection: Green", {"source_filter": {"color": "G"}},
         "{1}: Verhindere den nächsten Schaden, den eine grüne Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        # `source_filter={"card_type": "artifact"}` — the same generic
        # type-word check `combat.matches_object_filter`'s `card_type` key
        # already uses for "destroy target **artifact** creature"-shaped
        # filters. This member costs {2}, not the cycle's usual {1}.
        ("Circle of Protection: Artifacts",
         {"source_filter": {"card_type": "artifact"}, "cost": {"mana": "{2}"}},
         "{2}: Verhindere den nächsten Schaden, den eine Artefaktquelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        # `source_filter={"card_type": "creature", "keyword": "shadow"}`.
        ("Circle of Protection: Shadow",
         {"source_filter": {"card_type": "creature", "keyword": "shadow"}},
         "{1}: Verhindere den nächsten Schaden, den eine Kreatur deiner "
         "Wahl mit Schatten dir in diesem Zug zufügen würde."),
    ],
)


def _deflecting_palm() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. If damage is prevented this way, Deflecting
    Palm deals that much damage to that source's controller.

    — An instant, so the same `RequestPreventDamageSourceEffect` as Circle
    of Protection's activated ability, unqualified (``source_filter=None``
    — "a source of your choice" with no colour/type restriction) and
    carrying the new ``rider={"kind": "deal_damage_to_source_controller"}``,
    which `RulesEngine.apply_prevent_rider` fires with the real prevented
    amount once the chosen source's damage is actually stopped.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Falls auf "
                     "diese Weise Schaden verhindert wird, fügt Ablenkende "
                     "Handfläche diesen Schaden der beherrschenden Person "
                     "dieser Quelle zu.",
        ),
    ]


register("Deflecting Palm", _deflecting_palm)


# ---------------------------------------------------------------------------
# Rune of Protection cycle: same `RequestPreventDamageSourceEffect` shield
# shape as the Circle of Protection cycle above, cheaper and repeatable per
# activation but at a flat {W} instead of the Circles' generic mana, and
# every member also prints Cycling {2} — the ordinary keyword fold-in
# (PAR-9 — recognized-but-inert became real behaviour independently of this
# registration), so it's not part of this `register_family` call
# at all. Seven members this cycle (White/Blue/Black/Red/Green/Artifacts/
# Lands — note "Lands", not a "Shadow" sibling the way Circle of Protection
# has one), all sharing the one {W} cost, so no member needs a `"cost"`
# override.
# ---------------------------------------------------------------------------

register_family(
    ability_kind="activated",
    effect_type="request_prevent_damage_source",
    base_params={"amount": "all"},
    base_cost={"mana": "{W}"},
    entries=[
        ("Rune of Protection: White", {"source_filter": {"color": "W"}},
         "{W}: Verhindere den nächsten Schaden, den eine weiße Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Blue", {"source_filter": {"color": "U"}},
         "{W}: Verhindere den nächsten Schaden, den eine blaue Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Black", {"source_filter": {"color": "B"}},
         "{W}: Verhindere den nächsten Schaden, den eine schwarze Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Red", {"source_filter": {"color": "R"}},
         "{W}: Verhindere den nächsten Schaden, den eine rote Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Green", {"source_filter": {"color": "G"}},
         "{W}: Verhindere den nächsten Schaden, den eine grüne Quelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Artifacts",
         {"source_filter": {"card_type": "artifact"}},
         "{W}: Verhindere den nächsten Schaden, den eine Artefaktquelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
        ("Rune of Protection: Lands",
         {"source_filter": {"card_type": "land"}},
         "{W}: Verhindere den nächsten Schaden, den eine Landquelle "
         "deiner Wahl dir in diesem Zug zufügen würde."),
    ],
)


def _greater_realm_of_preservation() -> list[AbilitySpec]:
    """{1}{W}: The next time a black or red source of your choice would deal
    damage to you this turn, prevent that damage.

    — ``source_filter={"color_any": ["B", "R"]}`` (MEC-30's new multi-colour
    filter key, ``color``'s "any of" sibling).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_any": ["B", "R"]}, "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten Schaden, den eine "
                     "schwarze oder rote Quelle deiner Wahl dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Greater Realm of Preservation", _greater_realm_of_preservation)


def _story_circle() -> list[AbilitySpec]:
    """As this enchantment enters, choose a color.
    {W}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — The ETB colour choice is the ordinary ``choose_color_on_enter``
    replacement (Utopia Sprawl's own precedent, stamping `GameObject.
    chosen_color`); the shield reads it back dynamically via MEC-30's new
    ``source_filter={"color_from_source": True}`` key rather than a literal
    colour baked in at parse time — `RequestPreventDamageSourceEffect.apply`
    passes its own source as `matches_object_filter`'s ``reference``
    specifically so this (and Prismatic Circle's identical shape) can read
    it.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "eine Farbe.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl der gewählten Farbe dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Story Circle", _story_circle)


def _prismatic_circle() -> list[AbilitySpec]:
    """Cumulative upkeep {1}
    As this enchantment enters, choose a color.
    {1}: The next time a source of your choice of the chosen color would
    deal damage to you this turn, prevent that damage.

    — Cumulative upkeep is the ordinary RULE 702.24 keyword fold-in
    (MEC-16, unaffected by this registration). The rest is Story Circle's
    own shape at a cheaper activation cost.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_color_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "eine Farbe.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color_from_source": True}, "amount": "all",
            })],
            cost={"mana": "{1}"},
            raw_text="{1}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl der gewählten Farbe dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Prismatic Circle", _prismatic_circle)


def _circle_of_solace() -> list[AbilitySpec]:
    """As this enchantment enters, choose a creature type.
    {1}{W}: The next time a creature of the chosen type would deal damage
    to you this turn, prevent that damage.

    — The ETB creature-type choice is the ordinary ``choose_creature_type_
    on_enter`` replacement (Adaptive Automaton's own precedent, stamping
    `GameObject.chosen_type`); the shield reads it back via MEC-30's new
    ``source_filter={"card_type": "creature", "subtype_from_source": True}``.
    """
    return [
        AbilitySpec(
            "enter_replacement",
            [EffectSpec("choose_creature_type_on_enter", {})],
            raw_text="Während diese Verzauberung ins Spiel kommt, wähle "
                     "einen Kreaturtyp.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"card_type": "creature", "subtype_from_source": True},
                "amount": "all",
            })],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten Schaden, den eine "
                     "Kreatur des gewählten Typs dir in diesem Zug zufügen "
                     "würde.",
        ),
    ]


register("Circle of Solace", _circle_of_solace)


def _circle_of_despair() -> list[AbilitySpec]:
    """{1}, Sacrifice a creature: The next time a source of your choice
    would deal damage to any target this turn, prevent that damage.

    — ``target_kind="any"`` routes the shield's recipient through ordinary
    RULE 115 targeting instead of this effect's own controller — the
    already-designed "any target" branch `RequestPreventDamageSourceEffect`
    was built with (see its docstring), first actually used here.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "{1}, Sacrifice a creature"},
            raw_text="{1}, Opfere eine Kreatur: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl einem beliebigen "
                     "Ziel in diesem Zug zufügen würde.",
        ),
    ]


register("Circle of Despair", _circle_of_despair)


def _martyrs_cause() -> list[AbilitySpec]:
    """Sacrifice a creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice a creature"},
            raw_text="Opfere eine Kreatur: Verhindere den nächsten Schaden, "
                     "den eine Quelle deiner Wahl einem beliebigen Ziel in "
                     "diesem Zug zufügen würde.",
        ),
    ]


register("Martyr's Cause", _martyrs_cause)


def _sanctum_guardian() -> list[AbilitySpec]:
    """Sacrifice this creature: The next time a source of your choice would
    deal damage to any target this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
            raw_text="Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl einem beliebigen "
                     "Ziel in diesem Zug zufügen würde.",
        ),
    ]


register("Sanctum Guardian", _sanctum_guardian)


def _righteous_aura() -> list[AbilitySpec]:
    """{W}, Pay 2 life: The next time a source of your choice would deal
    damage to you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{W}, Pay 2 life"},
            raw_text="{W}, Bezahle 2 Leben: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl dir in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Righteous Aura", _righteous_aura)


def _haazda_shield_mate() -> list[AbilitySpec]:
    """At the beginning of your upkeep, sacrifice this creature unless you
    pay {W}{W}.
    {W}: The next time a source of your choice would deal damage to you
    this turn, prevent that damage.

    — The upkeep clause is the general RULE 701.17 ``sacrifice_unless_pay``
    interactive pay-or-lose-it choice (already shipped for Arcades Sabboth/
    Breeding Pit/Child of Gaea); registering this card for its own
    prevent-damage clause (still `UNMODELED` by the parser) would otherwise
    silently drop the upkeep clause too — `specs_for` trusts a registered
    card's specs wholesale — so it's authored alongside rather than left
    to the parser it can no longer reach.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_unless_pay", {"cost": "{W}{W}"})],
            trigger={
                "event": "STEP_BEGIN", "filter": {"step": "upkeep"},
                "phase_relation": "you",
            },
            raw_text="Zu Beginn deines Versorgungssegments opfere diese "
                     "Kreatur, außer du bezahlst {W}{W}.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"mana": "{W}"},
            raw_text="{W}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Haazda Shield Mate", _haazda_shield_mate)


def _charm_peddler() -> list[AbilitySpec]:
    """{W}, {T}, Discard a card: The next time a source of your choice would
    deal damage to target creature this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "creature", "amount": "all",
            })],
            cost={"text": "{W}, {T}, Discard a card"},
            raw_text="{W}, {T}, Wirf eine Karte ab: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl einer "
                     "Zielkreatur in diesem Zug zufügen würde.",
        ),
    ]


register("Charm Peddler", _charm_peddler)


def _cho_arrim_alchemist() -> list[AbilitySpec]:
    """{1}{W}{W}, {T}, Discard a card: The next time a source of your choice
    would deal damage to you this turn, prevent that damage. You gain life
    equal to the damage prevented this way.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            cost={"text": "{1}{W}{W}, {T}, Discard a card"},
            raw_text="{1}{W}{W}, {T}, Wirf eine Karte ab: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl dir in "
                     "diesem Zug zufügen würde. Du erhältst so viele "
                     "Lebenspunkte dazu, wie Schaden auf diese Weise "
                     "verhindert wurde.",
        ),
    ]


register("Cho-Arrim Alchemist", _cho_arrim_alchemist)


def _reverse_damage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Du "
                     "erhältst so viele Lebenspunkte dazu, wie Schaden auf "
                     "diese Weise verhindert wurde.",
        ),
    ]


register("Reverse Damage", _reverse_damage)


def _intervention_pact() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. You gain life equal to the damage prevented
    this way.
    At the beginning of your next upkeep, pay {1}{W}{W}. If you don't, you
    lose the game.

    — The delayed pay-or-lose clause is Pact of Negation's own template
    (``create_delayed_trigger``/``pay_cost_then``); see that entry's
    docstring for why it needed no new primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("request_prevent_damage_source", {
                    "amount": "all",
                    "rider": {"kind": "gain_life", "recipient": "you"},
                }),
                EffectSpec("create_delayed_trigger", {
                    "step": "upkeep",
                    "scope": "controller",
                    "description": "Interventionspakt: {1}{W}{W} bezahlen "
                                    "oder das Spiel verlieren",
                    "effects": [{
                        "type": "pay_cost_then",
                        "params": {
                            "cost": "{1}{W}{W}",
                            "effects": [],
                            "else_effects": [{"type": "lose_game", "params": {}}],
                        },
                    }],
                }),
            ],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Du "
                     "erhältst so viele Lebenspunkte dazu, wie Schaden auf "
                     "diese Weise verhindert wurde. Zu Beginn deines "
                     "nächsten Versorgungssegments bezahle {1}{W}{W}. "
                     "Falls du dies nicht tust, verlierst du das Spiel.",
        ),
    ]


register("Intervention Pact", _intervention_pact)


def _new_way_forward() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you this
    turn, prevent that damage. When damage is prevented this way, New Way
    Forward deals that much damage to that source's controller and you
    draw that many cards.

    — Two independent riders off the same prevented amount
    (``rider`` as a list — MEC-30's new list form of `RulesEngine.
    apply_prevent_rider`, first real card to need it).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "amount": "all",
                "rider": [
                    {"kind": "deal_damage_to_source_controller"},
                    {"kind": "draw_cards", "recipient": "you"},
                ],
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde. Falls "
                     "auf diese Weise Schaden verhindert wird, fügt Neuer "
                     "Weg nach vorn diesen Schaden der beherrschenden "
                     "Person dieser Quelle zu und du ziehst so viele "
                     "Karten.",
        ),
    ]


register("New Way Forward", _new_way_forward)


def _awe_strike() -> list[AbilitySpec]:
    """The next time target creature would deal damage this turn, prevent
    that damage. You gain life equal to the damage prevented this way.

    — `PreventDamageFromTargetEffect`'s own targeted, no-chooser-needed
    shape (Dazzling Reflection's own life-gain half is a separate,
    not-yet-built "gain life equal to a target's power" primitive — left
    open, see `BACKLOG.md`'s `MEC-30`).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("prevent_damage_from_target", {
                "target_kind": "creature",
                "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you"},
            })],
            raw_text="Verhindere den nächsten Schaden, den die "
                     "Zielkreatur in diesem Zug zufügen würde. Du erhältst "
                     "so viele Lebenspunkte dazu, wie Schaden auf diese "
                     "Weise verhindert wurde.",
        ),
    ]


register("Awe Strike", _awe_strike)


def _pentagram_of_the_ages() -> list[AbilitySpec]:
    """{4}, {T}: The next time a source of your choice would deal damage to
    you this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            cost={"text": "{4}, {T}"},
            raw_text="{4}, {T}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Pentagram of the Ages", _pentagram_of_the_ages)


def _pilgrim_of_justice() -> list[AbilitySpec]:
    """Protection from red
    {W}, Sacrifice this creature: The next time a red source of your choice
    would deal damage this turn, prevent that damage.

    — Protection is the ordinary RULE 702 keyword fold-in (unaffected by
    this registration). The card's own text omits "to you" (an older,
    pre-templating-standardization printing) — read the same way this
    repo's Penance/Seasoned Tactician entries do, as protecting the
    activating player.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "R"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
            raw_text="{W}, Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine rote Quelle deiner Wahl in diesem "
                     "Zug zufügen würde.",
        ),
    ]


register("Pilgrim of Justice", _pilgrim_of_justice)


def _pilgrim_of_virtue() -> list[AbilitySpec]:
    """Protection from black
    {W}, Sacrifice this creature: The next time a black source of your
    choice would deal damage this turn, prevent that damage.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "source_filter": {"color": "B"}, "amount": "all",
            })],
            cost={"text": "{W}, Sacrifice ~"},
            raw_text="{W}, Opfere diese Kreatur: Verhindere den nächsten "
                     "Schaden, den eine schwarze Quelle deiner Wahl in "
                     "diesem Zug zufügen würde.",
        ),
    ]


register("Pilgrim of Virtue", _pilgrim_of_virtue)


def _invulnerability() -> list[AbilitySpec]:
    """Buyback {3}
    The next time a source of your choice would deal damage to you this
    turn, prevent that damage.

    — Buyback is the ordinary RULE 702.24-adjacent keyword fold-in
    (unaffected by this registration).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {"amount": "all"})],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir in diesem Zug zufügen würde.",
        ),
    ]


register("Invulnerability", _invulnerability)


def _rem_karolus_stalwart_slayer() -> list[AbilitySpec]:
    """Flying, haste
    If a spell would deal damage to you or another permanent you control,
    prevent that damage.
    If a spell would deal damage to an opponent or a permanent an opponent
    controls, it deals that much damage plus 1 instead.

    — Flying/haste are the ordinary keyword fold-in. The prevent half is
    already fully expressible: ``source_filter={"is_spell": True}`` +
    ``recipient_union=["controller", {"exclude_self": True}]`` (Temple
    Altisaur's own "another `<X>` you control" idiom, unfiltered here since
    "another permanent" has no type restriction). The bonus-damage half
    needed one new param on `_additional_damage_replacement` — ``is_spell``,
    mirroring the check its own `_prevent_damage_replacement` sibling
    already had for the exact same event field (MEC-30).
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {"exclude_self": True}],
                "amount": "all", "source_filter": {"is_spell": True},
            })],
            raw_text="Falls ein Zauberspruch dir oder einem anderen "
                     "bleibenden Kartenbild, das du kontrollierst, Schaden "
                     "zufügen würde, verhindere diesen Schaden.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("additional_damage", {
                "amount": 1, "to_opponent_only": True, "is_spell": True,
            })],
            raw_text="Falls ein Zauberspruch einer gegnerischen Person "
                     "oder einem bleibenden Kartenbild, das eine "
                     "gegnerische Person kontrolliert, Schaden zufügen "
                     "würde, fügt er stattdessen so viel Schaden plus 1 zu.",
        ),
    ]


register("Rem Karolus, Stalwart Slayer", _rem_karolus_stalwart_slayer)


def _hedron_field_purists() -> list[AbilitySpec]:
    """Level up {2}{W}
    LEVEL 1-4  1/4
    If a source would deal damage to you or a creature you control,
    prevent 1 of that damage.
    LEVEL 5+  2/5
    If a source would deal damage to you or a creature you control,
    prevent 2 of that damage.

    — Level up itself and the level-banded P/T (1/4 vs. 2/5) are the
    ordinary structural RULE 711 Leveler handling (`Card.is_leveler`,
    independent of catalogue registration, the same way a DFC's transform
    is structural rather than per-card). Only the prevent-damage bands
    needed writing: two `prevent_damage` specs gated by `active_if`'s
    already-shipped `source_counters` kind (RULE 613.6, `game/static_
    conditions.py`), the exact shape already execute-tested synthetically
    in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 1,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 1, "max": 4},
            })],
            raw_text="LEVEL 1-4: Falls eine Quelle dir oder einer Kreatur, "
                     "die du kontrollierst, Schaden zufügen würde, "
                     "verhindere 1 dieses Schadens.",
        ),
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "recipient_union": ["controller", {}], "amount": 2,
                "active_if": {"kind": "source_counters", "counter": "level", "min": 5},
            })],
            raw_text="LEVEL 5+: Falls eine Quelle dir oder einer Kreatur, "
                     "die du kontrollierst, Schaden zufügen würde, "
                     "verhindere 2 dieses Schadens.",
        ),
    ]


register("Hedron-Field Purists", _hedron_field_purists)


def _battletide_alchemist() -> list[AbilitySpec]:
    """If a source would deal damage to a player, you may prevent X of that
    damage, where X is the number of Clerics you control.

    — **Documented simplification**: modeled as an unconditional (always
    applied) prevention rather than a real "you may" — no replacement-level
    optional-choice primitive exists in this engine, and building one is
    not justified for this single card (see `BACKLOG.md`'s `MEC-30`).
    ``amount_count_selector="creatures_you_control_of_type_cleric"`` is the
    same generic count-selector key Shield of the Avatar already uses for
    its own unscoped "number of creatures you control" form.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "any_player",
                "amount_count_selector": "creatures_you_control_of_type_cleric",
            })],
            raw_text="Falls eine Quelle einer spielenden Person Schaden "
                     "zufügen würde, verhinderst du X dieses Schadens, "
                     "wobei X die Anzahl der Kleriker ist, die du "
                     "kontrollierst. (Vereinfachung: nicht optional.)",
        ),
    ]


register("Battletide Alchemist", _battletide_alchemist)


def _nine_lives() -> list[AbilitySpec]:
    """Hexproof
    If a source would deal damage to you, prevent that damage and put an
    incarnation counter on this enchantment.
    When there are nine or more incarnation counters on this enchantment,
    exile it.
    When this enchantment leaves the battlefield, you lose the game.

    — Hexproof is the ordinary keyword fold-in. The prevent clause is a
    plain shield with the already-shipped `add_self_counter` rider. RULE
    603.8's "when there are N or more counters" state trigger — the one
    piece the ticket had marked as needing a genuine new subsystem — turned
    out not to: since incarnation counters only ever arrive one at a time
    via this card's own rider, an ordinary `EventType.COUNTER` self-subject
    trigger (Flourishing Defenses' own precedent) gated by the new
    `source_counters_at_least` trigger-condition key (MEC-30, the mirror of
    the already-shipped `source_counters_below`) is exactly rules-equivalent
    to a real state trigger for this card — checked fresh every time a
    counter lands, which is the only time the count could newly cross 9.
    The "leaves the battlefield" clause is the four-times-precedented
    `EventType.LEAVES_BATTLEFIELD`/``condition={"subject": "self"}`` shape.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("prevent_damage", {
                "to": "controller", "amount": "all",
                "rider": {"kind": "add_self_counter", "counter": "incarnation"},
            })],
            raw_text="Falls eine Quelle dir Schaden zufügen würde, "
                     "verhindere diesen Schaden und lege eine "
                     "Inkarnationsmarke auf dieses Verzauberung.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": None})],
            trigger={
                "event": EventType.COUNTER,
                "filter": {"kind": "incarnation"},
                "condition": {"subject": "self"},
                "source_counters_at_least": {"count": 9, "kind": "incarnation"},
            },
            raw_text="Wenn neun oder mehr Inkarnationsmarken auf dieser "
                     "Verzauberung liegen, exiliere sie.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_game", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Verzauberung das Spielfeld verlässt, "
                     "verlierst du das Spiel.",
        ),
    ]


register("Nine Lives", _nine_lives)


def _insult_injury() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn, it deals double that damage instead.

    — MEC-30's one real new mechanism: `disable_damage_prevention` flips a
    turn-scoped `GameState` flag that `RulesEngine._run_replacement_loop`
    checks generically against every replacement's new `prevents_damage`
    marker; `grant_damage_multiplier_this_turn` is the spell-cast sibling
    of the standing `double_damage` replacement (Furnace of Rath-shaped),
    filed on the caster's own `player_effects` since a resolved sorcery has
    no permanent to attach a standing shield to. Unscoped by recipient —
    "a source you control" doubles damage to *anyone*, no `to_opponent_
    only`, unlike Isengard Unleashed's own qualified sibling.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {"multiplier": 2}),
            ],
            raw_text="Schaden kann in diesem Zug nicht verhindert werden. "
                     "Falls eine Quelle, die du kontrollierst, in diesem "
                     "Zug Schaden zufügen würde, fügt sie stattdessen den "
                     "doppelten Schaden zu.",
        ),
    ]


register("Insult // Injury", _insult_injury)


def _isengard_unleashed() -> list[AbilitySpec]:
    """Damage can't be prevented this turn. If a source you control would
    deal damage this turn to an opponent or a permanent an opponent
    controls, it deals triple that damage instead.
    Flashback {4}{R}{R}{R}

    — Flashback is the ordinary keyword fold-in. Same shape as Insult //
    Injury, ``multiplier=3`` and ``to_opponent_only=True`` for the
    qualified recipient side.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("disable_damage_prevention", {}),
                EffectSpec("grant_damage_multiplier_this_turn", {
                    "multiplier": 3, "to_opponent_only": True,
                }),
            ],
            raw_text="Schaden kann in diesem Zug nicht verhindert werden. "
                     "Falls eine Quelle, die du kontrollierst, in diesem "
                     "Zug einer gegnerischen Person oder einem bleibenden "
                     "Kartenbild, das eine gegnerische Person kontrolliert, "
                     "Schaden zufügen würde, fügt sie stattdessen den "
                     "dreifachen Schaden zu.",
        ),
    ]


register("Isengard Unleashed", _isengard_unleashed)


def _ajani_steadfast() -> list[AbilitySpec]:
    """+1: Until end of turn, up to one target creature gets +1/+1 and
    gains first strike, vigilance, and lifelink.
    −2: Put a +1/+1 counter on each creature you control and a loyalty
    counter on each other planeswalker you control.
    −7: You get an emblem with "If a source would deal damage to you or a
    planeswalker you control, prevent all but 1 of that damage."

    — All three loyalty abilities are `UNCLAIMED` by the parser (not just
    the emblem the ticket had originally scoped) — `specs_for` trusts a
    registered card's specs wholesale, so all three need writing, the same
    Haazda Shield Mate lesson from Pass 2. +1 is an ordinary "up to one
    target" `pump` (The Wandering Emperor's own idiom). −2 is two
    `add_counters` specs in one ability — `selector="each_creature_you_
    control"` (already shipped) and the new `"each_other_planeswalker_you_
    control"` (MEC-30, `continuous.group_selector_objects`'s planeswalker-
    scoped sibling of ``other_creatures_you_control``). −7's emblem is the
    exact `prevent_damage` shape already execute-tested synthetically via
    the Hyperion test in `test_prevent_damage_family.py`.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "target_kind": "creature", "optional": True,
                "power": 1, "toughness": 1,
                "keywords": ["first strike", "vigilance", "lifelink"],
            })],
            cost={"loyalty": 1},
            raw_text="+1: Bis zum Ende des Zuges erhält bis zu eine "
                     "Zielkreatur +1/+1 und Erstschlag, Wachsamkeit und "
                     "Lebensverknüpfung.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("add_counters", {"selector": "each_creature_you_control"}),
                EffectSpec("add_counters", {
                    "selector": "each_other_planeswalker_you_control", "kind": "loyalty",
                }),
            ],
            cost={"loyalty": -2},
            raw_text="−2: Lege eine +1/+1-Marke auf jede Kreatur, die du "
                     "kontrollierst, und eine Loyalitätsmarke auf jeden "
                     "anderen Planeswalker, den du kontrollierst.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("create_emblem", {
                "ability": {
                    "ability_kind": "replacement",
                    "effects": [{
                        "type": "prevent_damage",
                        "params": {
                            "recipient_union": ["controller", {"card_type": "planeswalker"}],
                            "amount": {"all_but": 1},
                        },
                    }],
                },
            })],
            cost={"loyalty": -7},
            raw_text="−7: Du erhältst ein Emblem mit \"Falls eine Quelle "
                     "dir oder einem Planeswalker, den du kontrollierst, "
                     "Schaden zufügen würde, verhindere alles bis auf 1 "
                     "dieses Schadens.\"",
        ),
    ]


register("Ajani Steadfast", _ajani_steadfast)


def _kithkin_armor() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature can't be blocked by creatures with power 3 or
    greater.
    Sacrifice this Aura: The next time a source of your choice would deal
    damage to enchanted creature this turn, prevent that damage.

    — The Enchant keyword and the block restriction are *both* real parser
    output (confirmed via `parse_oracle` on the clause in isolation — only
    the shield clause is `UNCLAIMED`), so registering this card means
    replicating them by hand too, not just the shield — the same Haazda
    Shield Mate lesson: `specs_for` trusts a registered card wholesale. The
    shield needed a new small param on `RequestPreventDamageSourceEffect`:
    ``recipient="attached_permanent"`` (MEC-30) — Family B's own sibling of
    Family A's already-shipped ``to="attached_permanent"``, reading
    ``self.source.attached_to`` instead of the caster/an RULE 115 target.
    Read at *resolution* time, after the sacrifice cost has already moved
    this Aura to the graveyard — safe because this engine doesn't clear
    `GameObject.attached_to` on a zone change (the same "the object's last
    known state survives its own move" convention `LoseLifeEffect.amount_
    from_trigger_event`'s own docstring documents for RULE 400.7).
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"},
                     raw_text="Verzaubere Kreatur"),
        AbilitySpec(
            "static",
            [EffectSpec("combat_restriction", {
                "kind": "cant_be_blocked_by", "filter": {"min_power": 3},
                "affects": "attached_permanent",
            })],
            raw_text="Die verzauberte Kreatur kann nicht von Kreaturen mit "
                     "Stärke 3 oder mehr geblockt werden.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "attached_permanent", "amount": "all",
            })],
            cost={"text": "Sacrifice ~"},
            raw_text="Opfere diese Verzauberung: Verhindere den nächsten "
                     "Schaden, den eine Quelle deiner Wahl der verzauberten "
                     "Kreatur in diesem Zug zufügen würde.",
        ),
    ]


register("Kithkin Armor", _kithkin_armor)


def _shadowbane() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to you
    and/or creatures you control this turn, prevent that damage. If damage
    from a black source is prevented this way, you gain that much life.

    — ``recipient="you_and_creatures_you_control"`` (MEC-30) — the one-shot
    chooser's own new dynamic-recipient-set shape (`RulesEngine.prevent_
    damage_to_player_and_their_creatures`), the Family B sibling of Family
    A's `recipient_union`. ``rider={"if_source_color": "B", ...}`` (also
    MEC-30) gates the life-gain follow-up on the *watched source's* own
    colour — unlike every other rider kind, this one only sometimes fires.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "recipient": "you_and_creatures_you_control", "amount": "all",
                "rider": {"kind": "gain_life", "recipient": "you", "if_source_color": "B"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl dir und/oder Kreaturen, die du "
                     "kontrollierst, in diesem Zug zufügen würde. Falls auf "
                     "diese Weise Schaden einer schwarzen Quelle verhindert "
                     "wird, erhältst du so viele Lebenspunkte dazu.",
        ),
    ]


register("Shadowbane", _shadowbane)


def _honorable_passage() -> list[AbilitySpec]:
    """The next time a source of your choice would deal damage to any
    target this turn, prevent that damage. If damage from a red source is
    prevented this way, Honorable Passage deals that much damage to the
    source's controller.

    — ``target_kind="any"`` (already shipped, Circle of Despair's own
    shape). ``rider={"if_source_color": "R", ...}`` (MEC-30) — same
    source-colour-gated rider as Shadowbane, different kind.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("request_prevent_damage_source", {
                "target_kind": "any", "amount": "all",
                "rider": {"kind": "deal_damage_to_source_controller", "if_source_color": "R"},
            })],
            raw_text="Verhindere den nächsten Schaden, den eine Quelle "
                     "deiner Wahl einem beliebigen Ziel in diesem Zug "
                     "zufügen würde. Falls auf diese Weise Schaden einer "
                     "roten Quelle verhindert wird, fügt Ehrenhafter "
                     "Übergang diesen Schaden der beherrschenden Person "
                     "dieser Quelle zu.",
        ),
    ]


register("Honorable Passage", _honorable_passage)


def _dazzling_reflection() -> list[AbilitySpec]:
    """You gain life equal to target creature's power. The next time that
    creature would deal damage this turn, prevent that damage.

    — `GainLifeEffect`'s new `amount_from_target_power` flag (MEC-30), the
    life-gain sibling of `DealDamageEffect.amount_from_target_count_
    selector`, reads the *same* target `prevent_damage_from_target`'s own
    ``target_kind="creature"`` gathers — only one real RULE 115 target
    requirement in this whole ability, so `_apply_effects_partitioned`
    hands both effects the same resolved list (RULE 608.2).
    """
    return [
        AbilitySpec(
            "spell_effect",
            [
                EffectSpec("gain_life", {"amount_from_target_power": True}),
                EffectSpec("prevent_damage_from_target", {"target_kind": "creature", "amount": "all"}),
            ],
            raw_text="Du erhältst so viele Lebenspunkte dazu, wie die "
                     "Stärke der Zielkreatur beträgt. Verhindere den "
                     "nächsten Schaden, den diese Kreatur in diesem Zug "
                     "zufügen würde.",
        ),
    ]


register("Dazzling Reflection", _dazzling_reflection)


def _samite_blessing() -> list[AbilitySpec]:
    """Enchant creature
    Enchanted creature has "{T}: The next time a source of your choice
    would deal damage to target creature this turn, prevent that damage."

    — The already-shipped RULE 613/RULE 714.2c layer-6 "grant an activated
    ability, affects=attached_permanent" static (Umbral Mantle/Squirrel
    Nest/Deadeye Navigator's own shape) — the granted ability's own effects
    get their `source` set to the *host* creature at grant time, so
    `request_prevent_damage_source`'s chooser/recipient resolution
    (defaulting to the host's own controller) behaves exactly like a real
    printed ability of the host's, no new primitive needed.
    """
    return [
        AbilitySpec("keyword", [], keyword={"name": "enchant", "quality": "creature"},
                     raw_text="Verzaubere Kreatur"),
        AbilitySpec(
            "static",
            [EffectSpec("grant_activated_ability", {
                "affects": "attached_permanent",
                "cost": {"text": "{T}"},
                "grant_effects": [{
                    "type": "request_prevent_damage_source",
                    "params": {"target_kind": "creature", "amount": "all"},
                }],
            })],
            raw_text="Die verzauberte Kreatur hat „{T}: Verhindere den "
                     "nächsten Schaden, den eine Quelle deiner Wahl einer "
                     "Zielkreatur in diesem Zug zufügen würde.“",
        ),
    ]


register("Samite Blessing", _samite_blessing)


def _opal_eye_kondas_yojimbo() -> list[AbilitySpec]:
    """Defender
    Bushido 1
    {T}: The next time a source of your choice would deal damage this
    turn, that damage is dealt to Opal-Eye instead.
    {1}{W}: Prevent the next 1 damage that would be dealt to Opal-Eye this
    turn.

    — Defender/Bushido are the ordinary keyword fold-in. The first
    activated ability is RULE 616.1c *redirection*, not prevention —
    `RequestPreventDamageSourceEffect` doesn't fit at all, hence the new
    `RequestRedirectDamageSourceEffect`/`RulesEngine.redirect_damage_from_
    source` (MEC-30), reusing the exact chooser plumbing (`request_choose_
    objects`'s new `"remember_source_redirect"` action) with a rewritten
    recipient instead of a reduced amount — deliberately not marked
    `prevents_damage`, since RULE 615's "damage can't be prevented this
    turn" has no bearing on a redirect. The second ability is the ordinary
    already-shipped `prevent_damage_shield`, just needing one new small
    flag — `self_only=True` — since "damage to `<this permanent>`" has no
    existing recipient shape (the untargeted default always protects the
    *controller*, not the object itself).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("request_redirect_damage_source", {"amount": "all"})],
            cost={"text": "{T}"},
            raw_text="{T}: Verhindere den nächsten Schaden, den eine "
                     "Quelle deiner Wahl in diesem Zug zufügen würde, "
                     "indem er stattdessen Opal-Eye zugefügt wird.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("prevent_damage_shield", {"amount": 1, "self_only": True})],
            cost={"mana": "{1}{W}"},
            raw_text="{1}{W}: Verhindere den nächsten 1 Schadenspunkt, der "
                     "Opal-Eye in diesem Zug zugefügt werden würde.",
        ),
    ]


register("Opal-Eye, Konda's Yojimbo", _opal_eye_kondas_yojimbo)


