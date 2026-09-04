"""Card -> AbilitySpec catalogue entries, part 006 of 016.

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

def _brass_squire() -> list[AbilitySpec]:
    """{T}: Attach target Equipment you control to target creature you
    control.

    — Brass Squire. The seed card for `extra_target_specs`: the thing being
    attached is *itself* a target, which the shipped `AttachEffect` can't
    express (it always attaches its own source). Both requirements are
    gathered one at a time through the ordinary RULE 115.1 machinery and
    arrive at the effect flattened in printed order.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("attach_chosen", {
                "what_kind": "equipment_you_control",
                "to_kind": "creature_you_control",
            })],
            cost={"taps_self": True},
            raw_text="{T}: Lege eine Ziel-Ausrüstung, die du kontrollierst, an eine "
                     "Zielkreatur an, die du kontrollierst.",
        ),
    ]


register("Brass Squire", _brass_squire)


def _halvar_god_of_battle() -> list[AbilitySpec]:
    """Creatures you control that are enchanted or equipped have double
    strike.
    At the beginning of each combat, you may attach target Aura or Equipment
    attached to a creature you control to target creature you control.

    — Halvar, God of Battle. Brass Squire's clause widened to Auras, via the
    new ``attached_aura_or_equipment_you_control`` target kind — narrower
    than a bare "Equipment you control" in both directions: the attachment
    must already be on something, and that host must be yours.

    The static half uses the shipped layer-6 `grant_keyword` with the
    existing "enchanted or equipped" group selector, so it needed nothing
    new. The card is a DFC (// Sword of the Realms); registering the front
    face's own name is enough — `specs_for` falls back to the pre-"//" name.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {
                "affects": "enchanted_or_equipped_creatures_you_control",
                "keywords": ["double strike"],
            })],
            raw_text="Kreaturen, die du kontrollierst und die verzaubert oder "
                     "ausgerüstet sind, haben Doppelschlag.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("attach_chosen", {
                "what_kind": "attached_aura_or_equipment_you_control",
                "to_kind": "creature_you_control",
            })],
            optional=True,
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}},
            raw_text="Zu Beginn jedes Kampfes kannst du eine Ziel-Aura oder "
                     "Ziel-Ausrüstung, die an einer Kreatur unter deiner Kontrolle "
                     "angelegt ist, an eine Zielkreatur anlegen, die du "
                     "kontrollierst.",
        ),
    ]


register("Halvar, God of Battle", _halvar_god_of_battle)


def _archdruids_charm() -> list[AbilitySpec]:
    """Choose one —
    • Search your library for a creature or land card and reveal it. Put it
      onto the battlefield tapped if it's a land card. Otherwise, put it
      into your hand. Then shuffle.
    • Put a +1/+1 counter on target creature you control. It deals damage
      equal to its power to target creature you don't control.
    • Exile target artifact or enchantment.

    — Archdruid's Charm. The second mode is the third user of
    `extra_target_specs`, and has to be one atomic effect for a reason the
    other two don't: the damage is read off the *first* target **after** the
    counter lands (RULE 613's layer pass runs in between — putting the
    counter on first is the entire point), so no separate `DealDamageEffect`
    could ever see the boosted power.

    The first mode's *conditional* destination is `SearchLibraryEffect`'s
    ``destination_if``: unlike the positional ``destinations`` list (which
    is fixed when the search opens — Cultivate's "one tapped, one to hand"),
    this branches on the card the player actually found, which is the only
    way to express "onto the battlefield tapped **if it's a land card**.
    Otherwise, put it into your hand."
    """
    return [
        AbilitySpec(
            "spell_effect",
            [],
            modes={
                "options": [
                    [EffectSpec("search", {
                        "criteria": {"type": ["Creature", "Land"]},
                        "destination": "hand",
                        "destination_if": [
                            {"criteria": {"type": "Land"},
                             "destination": "battlefield_tapped"},
                        ],
                        "count": 1,
                    })],
                    [EffectSpec("counter_then_fightlike_damage", {"counters": 1})],
                    [EffectSpec("exile", {"target_kind": "artifact_or_enchantment"})],
                ],
                "descriptions": [
                    "Durchsuche deine Bibliothek nach einer Kreaturen- oder Landkarte.",
                    "Lege eine +1/+1-Marke auf eine Zielkreatur, die du kontrollierst. "
                    "Sie fügt einer Zielkreatur, die du nicht kontrollierst, Schaden "
                    "in Höhe ihrer Stärke zu.",
                    "Exiliere ein Zielartefakt oder eine Zielverzauberung.",
                ],
            },
            raw_text="Wähle eins — Durchsuche deine Bibliothek nach einer Kreaturen- "
                     "oder Landkarte; oder lege eine +1/+1-Marke auf eine Zielkreatur, "
                     "die du kontrollierst, und sie fügt einer Zielkreatur, die du "
                     "nicht kontrollierst, Schaden in Höhe ihrer Stärke zu; oder "
                     "exiliere ein Zielartefakt oder eine Zielverzauberung.",
        ),
    ]


register("Archdruid's Charm", _archdruids_charm)


def _dauntless_dismantler() -> list[AbilitySpec]:
    """Artifacts your opponents control enter tapped.
    {X}{X}{W}, Sacrifice this creature: Destroy each artifact with mana
    value X.

    — Dauntless Dismantler. The static half was *already* covered by the
    shipped board-wide ``enters_tapped`` static (`continuous.
    enters_tapped_from_static`) — only the activated ability left the card
    unmodeled.

    That ability needed a mass destroy whose **filter** is the ability's own
    announced X rather than a printed constant: the shipped
    `DestroyEffect`'s ``max_mana_value`` is a printed cap, while this is an
    exact match on a value known only at activation. Threaded through the
    same ``"x"`` sentinel `RulesEngine._substitute_x` rewrites for every
    other X-scaled magnitude — including the ``{X}{X}`` cost, which the mana
    model already doubles correctly.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("enters_tapped_static", {
                "affects": "opponents_permanents",
                "card_type": "artifact",
            })],
            raw_text="Artefakte, die deine Gegner kontrollieren, kommen getappt ins "
                     "Spiel.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("destroy_each_with_mana_value", {
                "amount": "x", "card_type": "artifact",
            })],
            cost={"text": "{X}{X}{W}", "sacrifice": "self"},
            raw_text="{X}{X}{W}, Opfere diese Kreatur: Zerstöre jedes Artefakt mit "
                     "Manawert X.",
        ),
    ]


register("Dauntless Dismantler", _dauntless_dismantler)


def _pemmins_aura() -> list[AbilitySpec]:
    """Enchant creature
    {U}: Untap enchanted creature.
    {U}: Enchanted creature gains flying until end of turn.
    {U}: Enchanted creature gains shroud until end of turn.
    {1}: Enchanted creature gets +1/-1 or -1/+1 until end of turn.

    — Pemmin's Aura. The first three lines already parse; the fourth was the
    "inline two-way modal with no bulleted header" the blocker list named —
    "A or B" in a single sentence, which the RULE 700.2 modal grammar (built
    for the bulleted block) doesn't recognize.

    Modeled as **two separate activated abilities**, one per half, rather
    than one ability with a RULE 700.2 mode choice: `modes` is only
    supported on spell/triggered abilities (an *activated* ability has no
    mode-choice window in this engine), and splitting is a faithful model
    anyway — the player's choice of which ability to activate *is* the
    printed choice, made at the same moment, with the same result. That
    keeps the card fully playable without inventing an activation-time mode
    prompt no other card needs.

    The oracle-text front-end now recognizes that shape itself
    (`segmenter._inline_pt_modal_bodies`, which rebuilds "gets A or B" as
    two complete clauses and emits one activated ability each), so this
    entry is no longer load-bearing — it's left registered rather than
    deleted, the same "no harm in both existing side by side" call the
    `top_library_permission` entries document, since the hand-authored
    registry always wins for a registered card and the two agree.
    """
    def pump(power: int, toughness: int) -> EffectSpec:
        """One half of the printed "+1/-1 or -1/+1", acting on whatever the
        Aura is currently attached to (RULE 303.4)."""
        return EffectSpec("pump", {
            "power": power, "toughness": toughness,
            "target_kind": "attached_permanent",
        })

    return [
        AbilitySpec(
            "activated",
            [EffectSpec("tap", {"untap": True, "target_kind": "attached_permanent"})],
            cost={"text": "{U}"},
            raw_text="{U}: Enttappe die verzauberte Kreatur.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["flying"],
                "target_kind": "attached_permanent",
            })],
            cost={"text": "{U}"},
            raw_text="{U}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "Fliegend.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {
                "power": 0, "toughness": 0, "keywords": ["shroud"],
                "target_kind": "attached_permanent",
            })],
            cost={"text": "{U}"},
            raw_text="{U}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "Schutzlosigkeit.",
        ),
        AbilitySpec(
            "activated",
            [pump(1, -1)],
            cost={"text": "{1}"},
            raw_text="{1}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "+1/-1.",
        ),
        AbilitySpec(
            "activated",
            [pump(-1, 1)],
            cost={"text": "{1}"},
            raw_text="{1}: Die verzauberte Kreatur erhält bis zum Ende des Zuges "
                     "-1/+1.",
        ),
    ]


register("Pemmin's Aura", _pemmins_aura)


def _dress_down() -> list[AbilitySpec]:
    """Flash
    When this enchantment enters, draw a card.
    Creatures lose all abilities.
    At the beginning of the end step, sacrifice this enchantment.

    — Dress Down. All three abilities were individually expressible — the
    board-wide ability strip is the shipped ``remove_all_abilities`` layer-6
    static (RULE 613.7f) — but the card was left unregistered, so the
    fail-closed coverage gate gave it nothing. Flash comes from the RULE 702
    keyword catalogue.

    Note the ordering that makes the card work: the ETB draw is a triggered
    ability that goes on the stack *before* the strip is ever consulted, and
    the strip doesn't remove the enchantment's own abilities (it names
    creatures), so the end-step sacrifice still fires.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("draw", {"count": 1})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self"},
            },
            raw_text="Wenn diese Verzauberung ins Spiel kommt, ziehe eine Karte.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("remove_all_abilities", {"affects": "all_creatures"})],
            raw_text="Kreaturen verlieren alle Fähigkeiten.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice_self", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}},
            raw_text="Zu Beginn des Endsegments opfere diese Verzauberung.",
        ),
    ]


register("Dress Down", _dress_down)


def _professor_onyx() -> list[AbilitySpec]:
    """Magecraft — Whenever you cast or copy an instant or sorcery spell,
    each opponent loses 2 life and you gain 2 life.
    +1: You lose 1 life. Look at the top three cards of your library. Put
    one of them into your hand and the rest into your graveyard.
    −3: Each opponent sacrifices a creature with the greatest power among
    creatures that player controls.
    −8: Each opponent may discard a card. If they don't, they lose 3 life.
    Repeat this process six more times.

    — Professor Onyx. Magecraft already parsed; the three loyalty abilities
    are hand-authored here.

    The −3 needed one narrow extension: `SacrificeEffect` gained
    ``greatest_power``, because this is the one place the engine's
    non-interactive "first matching permanent" auto-pick would be actively
    *wrong* rather than merely uninteresting — the card's whole effect is
    that the sacrificing player can't dodge with a spare token. It also
    gained an ``each_opponent`` selector and a registry entry (it had only
    ever been reachable from the annihilator keyword).

    **Documented simplification**: the −8's "each opponent may discard a
    card. If they don't, they lose 3 life. Repeat six more times." is
    modeled as seven rounds of a straight discard-or-lose-3, resolved
    non-interactively (discard if able, else lose the life) rather than as
    seven interactive `pay_cost_then` prompts per opponent — the outcome is
    identical for any opponent with cards, and an empty-handed one loses the
    life either way. Tracked in `docs/implementation-state/BACKLOG.md`.
    """
    return [
        AbilitySpec(
            "activated",
            [
                EffectSpec("lose_life", {"amount": 1, "player": "controller"}),
                EffectSpec("impulsive_look", {
                    "count": 3, "criteria": "", "hit_destination": "hand",
                    "miss_destination": "graveyard", "optional": False,
                }),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Du verlierst 1 Lebenspunkt. Schaue dir die obersten drei "
                     "Karten deiner Bibliothek an. Nimm eine davon auf die Hand und "
                     "lege den Rest auf deinen Friedhof.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("sacrifice", {
                "count": 1, "what": "creature",
                "selector": "each_opponent", "greatest_power": True,
            })],
            cost={"loyalty": -3},
            raw_text="−3: Jeder Gegner opfert eine Kreatur mit der höchsten Stärke "
                     "unter den Kreaturen, die er kontrolliert.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("discard_or_lose_life", {
                "count": 1, "amount": 3, "times": 7, "selector": "each_opponent",
            })],
            cost={"loyalty": -8},
            raw_text="−8: Jeder Gegner kann eine Karte abwerfen. Falls er dies nicht "
                     "tut, verliert er 3 Lebenspunkte. Wiederhole diesen Vorgang "
                     "sechsmal.",
        ),
    ]


register("Professor Onyx", _professor_onyx)


def _tevesh_szat_doom_of_fools() -> list[AbilitySpec]:
    """+2: Create two 0/1 black Thrull creature tokens.
    +1: You may sacrifice another creature or planeswalker. If you do, draw
    two cards, then draw another card if the sacrificed permanent was a
    commander.
    −10: Gain control of all commanders. Put all commanders from the command
    zone onto the battlefield under your control.

    — Tevesh Szat, Doom of Fools. The token and draw halves are shipped
    primitives; only the −10 needed a new one (`gain_control_of_all_
    commanders`), which is a genuinely Commander-specific effect with no
    near-miss anywhere in the engine: RULE 903.3's command-zone-to-
    battlefield move under someone *else's* control, across every player.

    The +1 is the first user of the general `ChooseObjectsEffect`: "you
    **may** sacrifice another creature or planeswalker" is a real choice
    now, and both of its conditional tails ride the chooser's own
    ``then``/``then_if_commander`` follow-ups — the draw only happens "if
    you do", and RULE 903's extra card only when the thing sacrificed was a
    commander, neither of which can be known before the pick is made.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("create_token", {
                "count": 2, "name": "Thrull", "power": 0, "toughness": 1,
                "colors": ["B"], "subtypes": ["Thrull"],
            })],
            cost={"loyalty": 2},
            raw_text="+2: Erzeuge zwei 0/1 schwarze Thrull-Kreaturenspielsteine.",
        ),
        AbilitySpec(
            "activated",
            [
                EffectSpec("choose_objects", {
                    "action": "sacrifice",
                    "what": "creature_or_planeswalker",
                    "count": 1,
                    "optional": True,
                    "exclude_self": True,
                    "prompt": "Tevesh Szat: Wähle eine Kreatur oder einen Planeswalker "
                              "zum Opfern",
                    "then": [{"type": "draw", "params": {"count": 2}}],
                    "then_if_commander": [{"type": "draw", "params": {"count": 1}}],
                }),
            ],
            cost={"loyalty": 1},
            raw_text="+1: Du kannst eine andere Kreatur oder einen anderen Planeswalker "
                     "opfern. Falls du dies tust, ziehe zwei Karten. Falls ein "
                     "Kommandeur auf diese Weise geopfert wurde, ziehe eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_control_of_all_commanders", {})],
            cost={"loyalty": -10},
            raw_text="−10: Erlange die Kontrolle über alle Kommandeure. Bringe alle "
                     "Kommandeure aus der Kommandozone unter deiner Kontrolle ins "
                     "Spiel.",
        ),
    ]


register("Tevesh Szat, Doom of Fools", _tevesh_szat_doom_of_fools)


def _jeska_thrice_reborn() -> list[AbilitySpec]:
    """Jeska enters with a loyalty counter on her for each time you've cast a
    commander from the command zone this game.
    0: Choose target creature. Until your next turn, if that creature would
    deal combat damage to one of your opponents, it deals triple that damage
    to that player instead.
    −X: Jeska deals X damage to each of up to three targets.

    — Jeska, Thrice Reborn. Two of the three lines ride shipped primitives:
    the entry counters read `Player.commander_casts` (already tracked for
    RULE 903.8's commander tax — no new state), and the −X is the shipped
    divided-damage shape with ``count=3``/``optional=True``.

    The 0 is the interesting one: it's a **targeted, duration-bounded damage
    multiplier**, which the shipped RULE 616.1 ``double_damage`` replacement
    family (Furnace of Rath/Fiery Emancipation — standing, board-wide,
    permanent-sourced) could *almost* express. Rather than a new mechanism
    it reuses that family's `multiplier` param with two new scopes the
    family already wanted: a specific source instance, and "combat damage to
    an opponent of the effect's controller" — installed as a turn-scoped
    `ReplacementEffect` on the targeted creature, the same
    `RegenerateEffect`-shaped per-object shield the engine already uses.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("multiply_damage_from_target", {
                "multiplier": 3, "combat_only": True, "to": "opponents",
            })],
            cost={"loyalty": 0},
            raw_text="0: Wähle eine Zielkreatur. Bis zu deinem nächsten Zug fügt sie "
                     "einem deiner Gegner dreifachen Kampfschaden zu.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("damage", {
                "amount": "x", "target_kind": "any", "count": 3,
                "optional": True, "divided": False,
            })],
            cost={"loyalty": "-x"},
            raw_text="−X: Jeska fügt bis zu drei Zielen jeweils X Schaden zu.",
        ),
    ]


register("Jeska, Thrice Reborn", _jeska_thrice_reborn)


def _delver_of_secrets() -> list[AbilitySpec]:
    """At the beginning of each upkeep, look at the top card of your
    library. You may reveal that card. If an instant or sorcery card is
    revealed this way, transform Delver of Secrets.

    — Delver of Secrets. RULE 712's one still-open template
    (`docs/implementation-state/BACKLOG.md` called it out by name): a *conditional*
    transform gated on a library-peek rather than RULE 731's day/night
    spells-cast count. `RevealTopThenTransformEffect` (`game/effects.py`)
    is the new general-purpose primitive — it takes a `models.card_query`
    criteria dict, so any future card sharing this exact template ("look at
    the top card…, if it's a[n] X card, transform ~") reuses it instead of
    a bespoke class. The "reveal" and "may" in the printed text don't
    change any actual decision here (the check is unconditional on what's
    really on top, and there's no consequence to *not* revealing it since
    nothing else looks at it), so both are simplifications with no
    observable difference to a solo player. Fires on every player's
    upkeep, not just its controller's, and reads *its own controller's*
    library regardless of whose upkeep triggered it, exactly like Tangle
    Wire's "each player's upkeep" trigger reads "that player" for its own
    effect.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("reveal_top_then_transform", {
                "criteria": {"type": ["instant", "sorcery"]},
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}},
            raw_text="Zu Beginn eines jeden Versorgungssegments schau dir die oberste "
                     "Karte deiner Bibliothek an. Du kannst diese Karte offenlegen. "
                     "Falls auf diese Weise eine Spontanzauber- oder Hexereikarte "
                     "offengelegt wird, wandle Delver of Secrets um.",
        ),
    ]


register("Delver of Secrets", _delver_of_secrets)


# ---------------------------------------------------------------------------
# MEC-11 — the Enrage stragglers: real cards left UNMODELED after the
# parser's own general "whenever ~ is dealt damage" recognition
# (`parser/oracle/segmenter.py`'s `_DAMAGE_RECIPIENT_TRIGGER_RE`) closed the
# trigger side. Each of these fails on its *effect body*, not the Enrage
# trigger itself — a second, narrower gap per card. Several needed a small
# new primitive (`damage_equal_to_counters`, `AddManaEffect.
# amount_from_trigger_event`, `AddCountersEffect`/`DealDamageEffect`'s
# widened selector vocabulary, the `opponent`/`opponent_or_planeswalker`
# target kinds) rather than being purely bespoke — each documented at its
# own definition in `game/effects.py`/`game/targeting.py`. Every entry below
# also documents its own simplifications inline; none silently drops a
# clause without saying so.
# ---------------------------------------------------------------------------


def _bellowing_aegisaur() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, put a +1/+1 counter
    on each other creature you control.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"selector": "each_other_creature_you_control"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, lege "
                     "eine +1/+1-Marke auf jede andere Kreatur unter deiner Kontrolle.",
        ),
    ]


register("Bellowing Aegisaur", _bellowing_aegisaur)


def _frilled_deathspitter() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 2 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 2, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, fügt sie "
                     "einem Zielgegner oder einem Ziel-Planeswalker 2 Schadenspunkte zu.",
        ),
    ]


register("Frilled Deathspitter", _frilled_deathspitter)


def _sun_crowned_hunters() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, it deals 3 damage
    to target opponent or planeswalker.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 3, "target_kind": "opponent_or_planeswalker"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, fügt sie "
                     "einem Zielgegner oder einem Ziel-Planeswalker 3 Schadenspunkte zu.",
        ),
    ]


register("Sun-Crowned Hunters", _sun_crowned_hunters)


def _indoraptor_the_perfect_hybrid() -> list[AbilitySpec]:
    """Bloodthirst X
    Menace
    Enrage — Whenever Indoraptor is dealt damage, choose an opponent at
    random. Indoraptor deals damage equal to its power to that player
    unless they sacrifice a nontoken creature of their choice.

    Simplified: "at random" becomes an ordinary target choice — a real
    choice instead of randomness has no rules-relevant difference here and
    is never worse for the chosen opponent — and the "unless they
    sacrifice a nontoken creature" escape clause isn't modeled (that would
    need a genuinely new opponent-side interactive "unless" primitive; the
    existing `sacrifice_unless_pay`/`request_pay_cost_then` family is
    always about *this ability's own controller* paying, not an
    opponent). The damage simply always happens. Bloodthirst is bind-on-
    load from the RULE 702 keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage_equal_to_power", {"target_kind": "opponent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Indoraptor Schaden zugefügt bekommt, fügt es "
                     "einem Zielgegner Schaden in Höhe seiner Stärke zu.",
        ),
    ]


register("Indoraptor, the Perfect Hybrid", _indoraptor_the_perfect_hybrid)


def _polyraptor() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, create a token
    that's a copy of this creature.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("copy_permanent", {"target_kind": None})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, erzeuge "
                     "einen Kartenspielstein, der eine Kopie von ihr ist.",
        ),
    ]


register("Polyraptor", _polyraptor)


def _raphael_ninja_destroyer() -> list[AbilitySpec]:
    """Raphael must be blocked if able.
    Enrage — Whenever Raphael is dealt damage, add that much {R}. Until
    end of turn, you don't lose this mana as steps and phases end.

    Simplified: the "you don't lose this mana as steps and phases end"
    persistence isn't modeled — `ManaPool` has no survives-a-step
    mechanism yet, so this mana empties at the current step's end (RULE
    500.4) like any other, rather than lasting the rest of the turn.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("grant_keyword", {"keywords": ["must_be_blocked"], "affects": "self"})],
            raw_text="Raphael muss blocken, falls möglich.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_mana", {"color": "R", "amount_from_trigger_event": "amount"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Raphael Schaden zugefügt bekommt, erzeuge "
                     "entsprechend viel {R}.",
        ),
    ]


register("Raphael, Ninja Destroyer", _raphael_ninja_destroyer)


def _red_hulk() -> list[AbilitySpec]:
    """Reach, trample
    Enrage — Whenever Red Hulk is dealt damage, put a +1/+1 counter on
    him. When you do, he deals damage equal to the number of +1/+1
    counters on him to any other target.

    Simplified: RULE 603.10's "when you do" is really a second, reflexive
    triggered ability off the counter-placement — this engine has no such
    primitive yet, so both halves run as one triggered ability's effect
    list instead (RULE 608.2a resolves a list in printed order, and
    nothing has a window to intervene between them either way in an
    automated engine), which is behaviourally indistinguishable from the
    two-trigger original. Reach/trample are bind-on-load from the RULE 702
    keyword catalogue, not hand-authored here.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("add_counters", {}),
                EffectSpec("damage_equal_to_counters", {"target_kind": "any"}),
            ],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn Red Hulk Schaden zugefügt bekommt, lege eine "
                     "+1/+1-Marke auf ihn. Danach fügt er einem beliebigen anderen Ziel "
                     "Schaden in Höhe der +1/+1-Marken auf ihm zu.",
        ),
    ]


register("Red Hulk", _red_hulk)


def _silverclad_ferocidons() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, each opponent
    sacrifices a permanent of their choice.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("sacrifice", {"selector": "each_opponent", "what": "permanent"})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, opfert "
                     "jeder Gegner eine bleibende Karte seiner Wahl.",
        ),
    ]


register("Silverclad Ferocidons", _silverclad_ferocidons)


def _stalwart_speartail() -> list[AbilitySpec]:
    """Enrage — Whenever Stalwart Speartail is dealt damage, other
    Dinosaurs you control and Dinosaur cards in your hand and library
    perpetually get +1/+1.
    Whenever Stalwart Speartail attacks, Stalwart Speartail deals 1 damage
    to each creature and each planeswalker.

    Simplified: only the second (attacks-trigger) ability is modeled. The
    first is RULE 121's *perpetual* effect shape (a one-time, permanent
    grant that outlives its source and reaches into hand/library, unlike
    an ordinary "as long as ~ is on the battlefield" static) — genuinely
    unsupported by this engine (`GrantUntilEffect`'s duration vocabulary,
    `game/durations.py`, is turn/game-window-scoped, not "forever,
    independent of the source"), so it's left out rather than
    approximated as an always-on static, which would be a meaningfully
    different, strictly *more* powerful card.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("damage", {"amount": 1, "selector": "each_creature_and_planeswalker"})],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "self"}},
            raw_text="Immer wenn Stalwart Speartail angreift, fügt es jeder Kreatur und "
                     "jedem Planeswalker 1 Schadenspunkt zu.",
        ),
    ]


register("Stalwart Speartail", _stalwart_speartail)


def _trapjaw_tyrant() -> list[AbilitySpec]:
    """Enrage — Whenever this creature is dealt damage, exile target
    creature an opponent controls until this creature leaves the
    battlefield.

    The O-Ring-shaped linked-exile pair (`ExileEffect(remember=True)` +
    `ReturnLinkedExileEffect` on the leaves-battlefield trigger, exactly
    `Leonin Relic-Warder`'s pattern) — the modern one-sentence "exile …
    until ~ leaves the battlefield" templating is the same RULE 610.3-style
    linked duration as Leonin's older two-sentence phrasing, just terser.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("exile", {"target_kind": "creature_you_dont_control", "remember": True})],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            raw_text="Enrage — Immer wenn diese Kreatur Schaden zugefügt bekommt, exiliere "
                     "eine Zielkreatur, die ein Gegner kontrolliert, bis diese Kreatur das "
                     "Schlachtfeld verlässt.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("return_linked_exile", {})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, bringe die exilierte "
                     "Karte unter der Kontrolle ihres Besitzers auf das Schlachtfeld zurück.",
        ),
    ]


register("Trapjaw Tyrant", _trapjaw_tyrant)


def _vrondiss_rage_of_ancients() -> list[AbilitySpec]:
    """Enrage — Whenever Vrondiss is dealt damage, you may create a 5/4
    red and green Dragon Spirit creature token with "When this token
    deals damage, sacrifice it."
    Whenever you roll one or more dice, you may have Vrondiss deal 1
    damage to itself.

    Simplified: the created token's own "sacrifice it after it deals
    damage" downside isn't modeled (no quoted-ability-grant support for a
    created token yet — every other quoted-grant primitive in this engine
    targets an *existing* permanent, not a token being created in the same
    breath), so the token created here is strictly a 5/4 vanilla. The
    dice-roll clause is skipped entirely — this engine has no dice-rolling
    subsystem at all.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "token_name": "Dragon Spirit", "power": 5, "toughness": 4,
                "colors": ["R", "G"], "subtypes": ["Dragon", "Spirit"],
            })],
            trigger={"event": "DAMAGE", "condition": {"subject": "self", "recipient": True}},
            optional=True,
            raw_text="Enrage — Immer wenn Vrondiss Schaden zugefügt bekommt, kannst du "
                     "einen 5/4 roten und grünen Drachengeist-Kreaturenspielstein erzeugen.",
        ),
    ]


register("Vrondiss, Rage of Ancients", _vrondiss_rage_of_ancients)


# ---------------------------------------------------------------------------
# "Hobbits" / "Wyleth Equip" saved-deck-priority batch — closing the
# remaining group-attack/group-ETB/conditional-trigger cluster the parser's
# generic grammar doesn't reach yet (RULE 603.3b's "any number of X" is a
# genuine aggregate-once trigger shape, distinct from the per-object group
# condition `effect_binder._build_group_ok` already models; a printed
# "historic"/exact-power-filtered ETB gate; a multi-object sacrifice cost).
# Each entry documents its own specific simplification.
# ---------------------------------------------------------------------------


def _meriadoc_brandybuck() -> list[AbilitySpec]:
    """Whenever one or more Halflings you control attack a player, create
    a Food token.

    Simplified: modeled as "attacks" (any defender), not "attacks a
    player" specifically — the ATTACKS event carries no defender-kind
    payload to filter on. RULE 603.3b's "one or more X" is a genuine
    aggregate-once-per-batch trigger; this engine's group condition instead
    fires once per *qualifying object* (once per attacking Halfling), so
    it's capped at once per turn (`trigger["limit"]`) as the closest
    available approximation — under-fires on a rare second combat the same
    turn, never over-fires on a simultaneous multi-Halfling attack.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ATTACKS,
                "condition": {
                    "subject": "group", "subtypes": ["halfling"],
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
            raw_text="Immer wenn ein oder mehr Halblinge unter deiner Kontrolle einen "
                     "Spieler angreifen, erzeuge einen Nahrungsspielstein.",
        ),
    ]


register("Meriadoc Brandybuck", _meriadoc_brandybuck)


def _merry_warden_of_isengard() -> list[AbilitySpec]:
    """Partner with Pippin, Warden of Isengard.
    Whenever one or more artifacts you control enter, create a 1/1 white
    Soldier creature token with lifelink. This ability triggers only once
    each turn.

    ("Partner with" is bound by the RULE 702 keyword catalogue directly
    off Scryfall's own keyword array — no hand-authoring needed for it.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Soldier"], "keywords": ["lifelink"], "token_name": "Soldier",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "artifact",
                    "controller": "you", "other": False,
                },
                "limit": True,
            },
            raw_text="Immer wenn ein oder mehr Artefakte unter deiner Kontrolle ins Spiel "
                     "kommen, erzeuge einen 1/1 weißen Soldat-Kreaturenspielstein mit "
                     "Lebensverknüpfung. Diese Fähigkeit wird nur einmal pro Zug ausgelöst.",
        ),
    ]


register("Merry, Warden of Isengard", _merry_warden_of_isengard)


def _rosie_cotton_of_south_lane() -> list[AbilitySpec]:
    """When Rosie Cotton enters, create a Food token.
    Whenever you create a token, put a +1/+1 counter on target creature
    you control other than Rosie Cotton.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Rosie Cotton ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"target_kind": "other_creature_you_control"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein erzeugst, lege einen +1/+1-Marker auf "
                     "eine andere Zielkreatur unter deiner Kontrolle.",
        ),
    ]


register("Rosie Cotton of South Lane", _rosie_cotton_of_south_lane)


def _saradoc_master_of_buckland() -> list[AbilitySpec]:
    """Whenever Saradoc or another nontoken creature you control with
    power 2 or less enters, create a 1/1 white Halfling creature token.
    Tap two other untapped Halflings you control: Saradoc gets +2/+0 and
    gains lifelink until end of turn.

    Simplified: the power-2-or-less filter isn't checked (a live per-
    firing power qualifier on a group-ETB condition isn't modeled yet) —
    widened to any nontoken creature entering; the tap cost's pool isn't
    narrowed to exclude Saradoc herself (`costs.ActivationCost.tap_others`
    has no self-exclusion flag), so she could in principle pay her own
    cost. Both are documented over-generosities, not a functional break.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Halfling"], "token_name": "Halfling",
            })],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {"subject": "self_or_group", "type": "creature", "controller": "you", "other": True},
            },
            raw_text="Immer wenn Saradoc oder eine andere nicht-Spielstein-Kreatur unter "
                     "deiner Kontrolle mit Stärke 2 oder weniger ins Spiel kommt, erzeuge "
                     "einen 1/1 weißen Halblinge-Kreaturenspielstein.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("pump", {"power": 2, "toughness": 0, "keywords": ["lifelink"]})],
            cost={"tap_others": (2, "halfling")},
            raw_text="Tappe zwei andere ungetappte Halblinge unter deiner Kontrolle: "
                     "Saradoc erhält +2/+0 und Lebensverknüpfung bis zum Ende des Zuges.",
        ),
    ]


register("Saradoc, Master of Buckland", _saradoc_master_of_buckland)


def _experimental_confectioner() -> list[AbilitySpec]:
    """When this creature enters, create a Food token.
    Whenever you sacrifice a Food, create a 1/1 black Rat creature token
    with "This token can't block."

    Simplified: the created Rat token doesn't carry its own "can't block"
    text — `create_token`'s params have no combat-restriction hook for a
    token being created this same breath (every other combat-restriction
    consumer targets an *existing* permanent).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 1, "power": 1, "toughness": 1, "colors": ["B"],
                "subtypes": ["Rat"], "token_name": "Rat",
            })],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
            raw_text="Immer wenn du eine Nahrung opferst, erzeuge einen 1/1 schwarzen "
                     "Ratte-Kreaturenspielstein (kann nicht blocken).",
        ),
    ]


register("Experimental Confectioner", _experimental_confectioner)


def _rapacious_guest() -> list[AbilitySpec]:
    """Menace
    Whenever one or more creatures you control deal combat damage to a
    player, create a Food token.
    Whenever you sacrifice a Food, put a +1/+1 counter on this creature.
    When this creature leaves the battlefield, target opponent loses life
    equal to its power.

    Simplified: the first trigger is capped at once per turn
    (`trigger["limit"]`) — see Meriadoc Brandybuck's own note on RULE
    603.3b's "any number of X" aggregate-once shape.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.DAMAGE,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": False,
                },
                "filter": {"combat": True, "is_player": True},
                "limit": True,
            },
            raw_text="Immer wenn eine oder mehr Kreaturen unter deiner Kontrolle einem "
                     "Spieler Kampfschaden zufügen, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "sacrifice_type": "food",
            },
            raw_text="Immer wenn du eine Nahrung opferst, lege einen +1/+1-Marker auf "
                     "diese Kreatur.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"target_kind": "player", "amount_from_trigger_event": "power"})],
            trigger={"event": EventType.LEAVES_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn diese Kreatur das Schlachtfeld verlässt, verliert ein Gegner "
                     "deiner Wahl so viel Leben, wie ihre Stärke betrug.",
        ),
    ]


register("Rapacious Guest", _rapacious_guest)


def _mirkwood_bats() -> list[AbilitySpec]:
    """Flying
    Whenever you create or sacrifice a token, each opponent loses 1 life.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "permanent",
                    "controller": "you", "other": False,
                },
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein erzeugst, verliert jeder Gegner 1 Leben.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {"amount": 1, "selector": "each_opponent"})],
            trigger={
                "event": EventType.SACRIFICE,
                "condition": {"subject": "you"},
                "filter": {"is_token": True},
            },
            raw_text="Immer wenn du einen Spielstein opferst, verliert jeder Gegner 1 Leben.",
        ),
    ]


register("Mirkwood Bats", _mirkwood_bats)


def _farmer_cotton() -> list[AbilitySpec]:
    """When Farmer Cotton enters the battlefield, create X 1/1 white
    Halfling creature tokens and X Food tokens, where X is the number of
    Halflings you control.

    The cached oracle text is missing its trailing "where X is …" clause
    (a Scryfall data gap in the local cache) — X is filled in here from
    the card's real printed rules text.
    """
    return [
        AbilitySpec(
            "triggered",
            [
                EffectSpec("create_token", {
                    "power": 1, "toughness": 1, "colors": ["W"], "subtypes": ["Halfling"],
                    "token_name": "Halfling",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
                EffectSpec("create_token", {
                    "token_name": "Food",
                    "count_selector": "creatures_you_control_of_type_halfling",
                }),
            ],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn Farmer Cotton ins Spiel kommt, erzeuge X 1/1 weiße "
                     "Halblinge-Kreaturenspielsteine und X Nahrungsspielsteine, wobei X "
                     "die Anzahl der Halblinge ist, die du kontrollierst.",
        ),
    ]


register("Farmer Cotton", _farmer_cotton)


def _samwise_gamgee() -> list[AbilitySpec]:
    """Whenever another nontoken creature you control enters, create a
    Food token.
    Sacrifice three Foods: Return target historic card from your
    graveyard to your hand. (Artifacts, legendaries, and Sagas are
    historic.)

    Simplified: "historic" isn't a modeled target filter — widened to
    "target card in your graveyard" (`graveyard_card`), the closest
    already-supported graveyard-target shape; likewise "nontoken" isn't
    enforced on a bare main-type group condition (only on a subtype-
    filtered one), so this also fires for a token creature entering.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            trigger={
                "event": EventType.ENTERS_BATTLEFIELD,
                "condition": {
                    "subject": "group", "type": "creature",
                    "controller": "you", "other": True,
                },
            },
            raw_text="Immer wenn eine andere nicht-Spielstein-Kreatur unter deiner "
                     "Kontrolle ins Spiel kommt, erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("return_from_graveyard", {"target_kind": "graveyard_card", "destination": "hand"})],
            cost={"sacrifice_count": (3, "food")},
            raw_text="Opfere drei Nahrungen: Bringe eine Zielkarte aus deinem Friedhof auf "
                     "deine Hand zurück.",
        ),
    ]


register("Samwise Gamgee", _samwise_gamgee)


def _sam_loyal_attendant() -> list[AbilitySpec]:
    """Partner with Frodo, Adventurous Hobbit.
    At the beginning of combat on your turn, create a Food token.
    Activated abilities of Foods you control cost {1} less to activate.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {"count": 1, "token_name": "Food"})],
            # Bug report, 2026-09-04: `GameStep`'s real name for this step
            # (`game/phases.py`) is "begin_combat", not "combat" — the wrong
            # filter value meant this `STEP_BEGIN` event, whose `step` field
            # never carries a bare "combat", could never match, so the Food
            # token silently never got created at all.
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "begin_combat"}, "phase_relation": "you"},
            raw_text="Zu Beginn des Kampfes in deinem Zug erzeuge einen Nahrungsspielstein.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("cost_reduction", {"generic": 1, "scope": "activation", "subtype": "food"})],
            raw_text="Aktivierte Fähigkeiten von Nahrungen unter deiner Kontrolle kosten "
                     "{1} weniger zum Aktivieren.",
        ),
    ]


register("Sam, Loyal Attendant", _sam_loyal_attendant)


def _academy_manufactor() -> list[AbilitySpec]:
    """If you would create a Clue, Food, or Treasure token, instead create
    one of each.
    """
    return [
        AbilitySpec(
            "replacement",
            [EffectSpec("create_one_of_each_named_token", {})],
            raw_text="Falls du einen Hinweis-, Nahrungs- oder Schatzspielstein erzeugen "
                     "würdest, erzeuge stattdessen jeweils einen davon.",
        ),
    ]


register("Academy Manufactor", _academy_manufactor)


def _access_tunnel() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {3}, {T}: Target creature with power 3 or less can't be blocked this
    turn.

    (The mana ability is bound automatically off the printed "{T}: Add
    {C}." text — `game/mana_abilities.py` — so only the second ability
    needs authoring here.)
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("unblockable", {"target_kind": "creature", "creature_filter": {"max_power": 3}})],
            cost={"mana": "{3}", "taps_self": True},
            raw_text="{3}, {T}: Eine Zielkreatur mit Stärke 3 oder weniger kann in diesem "
                     "Zug nicht geblockt werden.",
        ),
    ]


register("Access Tunnel", _access_tunnel)


def _anduril_flame_of_the_west() -> list[AbilitySpec]:
    """Equipped creature gets +3/+1.
    Whenever equipped creature attacks, create two tapped 1/1 white Spirit
    creature tokens with flying. If that creature is legendary, instead
    create two of those tokens that are tapped and attacking.

    Simplified: the "instead tapped and attacking" branch for a legendary
    equipped creature isn't modeled — the tokens always enter merely
    tapped, never already attacking (no primitive yet for a token entering
    mid-combat as an attacker).
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "attached_permanent", "power": 3, "toughness": 1})],
            raw_text="Verzauberte Kreatur erhält +3/+1.",
        ),
        AbilitySpec(
            "triggered",
            [EffectSpec("create_token", {
                "count": 2, "power": 1, "toughness": 1, "colors": ["W"],
                "subtypes": ["Spirit"], "keywords": ["flying"], "token_name": "Spirit", "tapped": True,
            })],
            trigger={"event": EventType.ATTACKS, "condition": {"subject": "attached_permanent"}},
            raw_text="Immer wenn die verzauberte Kreatur angreift, erzeuge zwei getappte "
                     "1/1 weiße Geist-Kreaturenspielsteine mit Fliegen.",
        ),
    ]


register("Andúril, Flame of the West", _anduril_flame_of_the_west)


def _banquet_guests() -> list[AbilitySpec]:
    """Affinity for Foods
    Trample
    This creature enters with twice X +1/+1 counters on it.
    {2}, Sacrifice a Food: This creature gains indestructible until end of
    turn.

    (Affinity/Trample/the sacrifice-a-Food ability already parse on their
    own — only the X-scaled entry counters, which RULE 614.1's oracle-
    derived path can't express, needed hand-authoring.)
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"x_multiplier": 2})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Diese Kreatur kommt mit doppelt X +1/+1-Marken ins Spiel.",
        ),
    ]


register("Banquet Guests", _banquet_guests)


def _bilbo_birthday_celebrant() -> list[AbilitySpec]:
    """If you would gain life, you gain that much life plus 1 instead.
    {2}{W}{B}{G}, {T}, Exile Bilbo: Search your library for any number of
    creature cards, put them onto the battlefield, then shuffle. Activate
    only if you have 111 or more life.

    Simplified: the lifegain-plus-1 replacement and the "111 or more
    life" activation gate aren't modeled (no lifegain-amount replacement/
    activation-condition primitive reaches this exact shape yet); the
    exile-self cost is approximated as sacrifice-self (no battlefield
    "exile this permanent as a cost" primitive exists — only a hand-zone
    one). The tutor-and-mass-reanimate itself is fully modeled.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("search", {
                "criteria": {"type": "Creature"}, "destination": "battlefield",
                "count": 99, "optional": True,
            })],
            cost={"mana": "{2}{W}{B}{G}", "taps_self": True, "sacrifice": "self"},
            raw_text="{2}{W}{B}{G}, {T}, Exiliere Bilbo: Durchsuche deine Bibliothek nach "
                     "einer beliebigen Anzahl Kreaturenkarten, lege sie ins Spiel und "
                     "mische danach.",
        ),
    ]


register("Bilbo, Birthday Celebrant", _bilbo_birthday_celebrant)


def _call_for_unity() -> list[AbilitySpec]:
    """Revolt — At the beginning of your end step, if a permanent left the
    battlefield under your control this turn, put a unity counter on this
    enchantment.
    Creatures you control get +1/+1 for each unity counter on this
    enchantment.

    Simplified: Revolt's own condition ("a permanent left the battlefield
    under your control this turn") isn't modeled — the counter is added
    every end step unconditionally (no "permanent left the battlefield
    this turn" tracker exists yet, unlike `creatures_died_this_turn`).
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("add_counters", {"kind": "unity"})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Revolte — Zu Beginn deines Endsegments lege eine Einheits-Marke auf "
                     "diese Verzauberung.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {
                "affects": "creatures_you_control", "power": 1, "toughness": 1,
                "power_count": "counters_on_self", "toughness_count": "counters_on_self",
                "counter_kind": "unity",
            })],
            raw_text="Kreaturen unter deiner Kontrolle erhalten +1/+1 für jede "
                     "Einheits-Marke auf dieser Verzauberung.",
        ),
    ]


register("Call for Unity", _call_for_unity)


def _call_of_the_ring() -> list[AbilitySpec]:
    """At the beginning of your upkeep, the Ring tempts you.
    Whenever you choose a creature as your Ring-bearer, you may pay 2
    life. If you do, draw a card.

    Simplified: the second ability isn't modeled — no event fires for
    "you choose a creature as your Ring-bearer" yet (RULE 701.52a's
    choice is a `pending_choice`, not a broadcast `GameEvent`), so there's
    nothing to trigger off. The upkeep Ring-tempts-you line (this card's
    real recurring value) is fully modeled.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("the_ring_tempts_you", {})],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "upkeep"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Versorgungssegments verlockt dich der Ring.",
        ),
    ]


register("Call of the Ring", _call_of_the_ring)


def _fell_the_mighty() -> list[AbilitySpec]:
    """Destroy all creatures with power greater than target creature's
    power.

    Simplified: the dynamic threshold (the target creature's own power,
    read fresh at resolution) isn't modeled — widened to a fixed "power 4
    or greater" mass destroy (`min_power`, the same filter Dusk // Dawn
    uses), a reasonable typical-target approximation without a real
    "compare to the resolved target's own characteristic" mass-selector
    primitive.
    """
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 4}})],
            raw_text="Zerstöre alle Kreaturen mit einer größeren Stärke als eine "
                     "Zielkreatur.",
        ),
    ]


register("Fell the Mighty", _fell_the_mighty)


def _flowering_of_the_white_tree() -> list[AbilitySpec]:
    """Legendary creatures you control get +2/+1 and have ward {1}.
    Nonlegendary creatures you control get +1/+1.

    Simplified: the granted "have ward {1}" isn't modeled — the layer-6
    keyword-grant mechanism only carries flag keywords today (ward is
    parametric, a real pre-existing gap: `parser/oracle/catalogue/
    static_handlers._flag_keywords` fails closed on any granted parametric
    keyword). Both anthems (+2/+1 legendary / +1/+1 nonlegendary) are fully
    modeled.
    """
    return [
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "legendary_creatures_you_control", "power": 2, "toughness": 1})],
            raw_text="Legendäre Kreaturen unter deiner Kontrolle erhalten +2/+1.",
        ),
        AbilitySpec(
            "static",
            [EffectSpec("anthem", {"affects": "nonlegendary_creatures_you_control", "power": 1, "toughness": 1})],
            raw_text="Nicht-legendäre Kreaturen unter deiner Kontrolle erhalten +1/+1.",
        ),
    ]


register("Flowering of the White Tree", _flowering_of_the_white_tree)


def _ghost_quarter() -> list[AbilitySpec]:
    """{T}: Add {C}.
    {T}, Sacrifice this land: Destroy target land. Its controller may
    search their library for a basic land card, put it onto the
    battlefield, then shuffle.

    Simplified: the destroyed land's controller getting a compensating
    basic-land fetch isn't modeled (`SearchLibraryEffect` always searches
    *this* ability's own controller's library, not the target's
    controller) — narrowed to the land destruction alone, the card's own
    primary use.
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("destroy", {"target_kind": "permanent"})],
            cost={"taps_self": True, "sacrifice": "self"},
            raw_text="{T}, Opfere dieses Land: Zerstöre ein Zielland.",
        ),
    ]


register("Ghost Quarter", _ghost_quarter)


def _go_for_the_throat() -> list[AbilitySpec]:
    """Destroy target nonartifact creature."""
    return [
        AbilitySpec(
            "spell_effect",
            [EffectSpec("destroy", {"target_kind": "creature", "creature_filter": {"without_card_type": "artifact"}})],
            raw_text="Zerstöre eine Ziel-Nichtartefaktkreatur.",
        ),
    ]


register("Go for the Throat", _go_for_the_throat)


def _gollum_obsessed_stalker() -> list[AbilitySpec]:
    """Skulk (This creature can't be blocked by creatures with greater
    power.)
    At the beginning of your end step, each opponent dealt combat damage
    this game by a creature named Gollum, Obsessed Stalker loses life
    equal to the amount of life you gained this turn.

    Simplified: narrowed to "each opponent loses life equal to the amount
    of life you gained this turn" every end step — the "only an opponent
    this specific creature has ever connected with" scoping isn't tracked
    (no "dealt combat damage by a creature named X, ever" history exists);
    in practice this only differs when Gollum himself hasn't dealt combat
    damage to anyone yet, a narrow early-game window.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("lose_life", {
                "selector": "each_opponent",
                "amount_from_life_gained_this_turn": True,
            })],
            trigger={"event": EventType.STEP_BEGIN, "filter": {"step": "end"}, "phase_relation": "you"},
            raw_text="Zu Beginn deines Endsegments verliert jeder Gegner so viel Leben, "
                     "wie du in diesem Zug an Leben gewonnen hast.",
        ),
    ]


register("Gollum, Obsessed Stalker", _gollum_obsessed_stalker)


def _lembas() -> list[AbilitySpec]:
    """When this artifact enters, scry 1, then draw a card.
    {2}, {T}, Sacrifice this artifact: You gain 3 life.
    When this artifact is put into a graveyard from the battlefield, its
    owner shuffles it into their library.

    Simplified: the dies-trigger self-shuffle isn't modeled (no "return
    self from graveyard" primitive exists for `ReturnFromGraveyardEffect`,
    only a real RULE 115 target pick) — Lembas simply stays in the
    graveyard once it dies, same as an ordinary permanent.
    """
    return [
        AbilitySpec(
            "triggered",
            [EffectSpec("scry", {"count": 1}), EffectSpec("draw", {"count": 1})],
            trigger={"event": EventType.ENTERS_BATTLEFIELD, "condition": {"subject": "self"}},
            raw_text="Wenn dieses Artefakt ins Spiel kommt, prophezeie 1, dann ziehe "
                     "eine Karte.",
        ),
        AbilitySpec(
            "activated",
            [EffectSpec("gain_life", {"amount": 3})],
            cost={"mana": "{2}", "taps_self": True, "sacrifice": "self"},
            raw_text="{2}, {T}, Opfere dieses Artefakt: Du gewinnst 3 Leben.",
        ),
    ]


register("Lembas", _lembas)


def _lobelia_defender_of_bag_end() -> list[AbilitySpec]:
    """When Lobelia enters, look at the top card of each opponent's
    library and exile those cards face down.
    {T}, Sacrifice an artifact: Choose one — Until end of turn, you may
    play a card exiled with Lobelia without paying its mana cost. / Each
    opponent loses 2 life and you gain 2 life.

    Simplified: narrowed to the second mode only (each opponent loses 2
    life, you gain 2 life) — the ETB peek-and-exile plus "play what was
    exiled with ~" free-cast window needs a linked-exile-with-a-play-
    window primitive this engine doesn't have yet (`ExileEffect(remember=
    True)` links to *one* object, not a per-opponent set with its own
    later play permission).
    """
    return [
        AbilitySpec(
            "activated",
            [EffectSpec("lose_life", {"amount": 2, "selector": "each_opponent"}), EffectSpec("gain_life", {"amount": 2})],
            cost={"taps_self": True, "sacrifice": "artifact"},
            raw_text="{T}, Opfere ein Artefakt: Jeder Gegner verliert 2 Leben und du "
                     "gewinnst 2 Leben.",
        ),
    ]


register("Lobelia, Defender of Bag End", _lobelia_defender_of_bag_end)


