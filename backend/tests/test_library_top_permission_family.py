"""Library-top/impulsive-draw permissions closeout (docs/implementation-state/BACKLOG.md).

Covers `parser/oracle/catalogue/static_handlers.py`'s generic recognition of
the "You may play lands [and cast [noncreature] spells [with mana value N or
greater]] from the top of your library" static — the oracle-text sibling of
the two hand-authored `top_library_permission` catalogue entries (Oracle of
Mul Daya/Glarb, Calamity's Augur) — plus each card's own optional same-line
"If you cast a spell this way, ..." conditional tail: Elsha of the
Infinite's "you may cast it as though it had flash" (`grants_flash`) and
Bolas's Citadel's "pay life equal to its mana value rather than pay its mana
cost" (`life_payment`, a new RULE 118 alternative-cost substitution). Also
covers `segmenter.py`'s new "Play with the top card of your library
revealed." no-op line. The engine-side execution of `grants_flash`/
`life_payment`/`noncreature_only` is covered end-to-end in
`test_top_library.py`; this file is the parser-recognition half.
"""

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


# -- Clause-shape recognition -------------------------------------------------


def test_play_lands_only():
    specs = static_effect_specs("You may play lands from the top of your library.")
    assert specs == [EffectSpec("top_library_permission", {"look": True, "play_lands": True})]


def test_play_lands_and_cast_spells():
    specs = static_effect_specs(
        "You may play lands and cast spells from the top of your library."
    )
    assert specs == [
        EffectSpec("top_library_permission", {"look": True, "play_lands": True, "cast_spells": True})
    ]


def test_mana_value_gate():
    specs = static_effect_specs(
        "You may play lands and cast spells with mana value 4 or greater "
        "from the top of your library."
    )
    assert specs == [
        EffectSpec("top_library_permission", {
            "look": True, "play_lands": True, "cast_spells": True, "min_mana_value": 4,
        })
    ]


def test_cast_spells_only_no_land_permission():
    specs = static_effect_specs("You may cast spells from the top of your library.")
    assert specs == [EffectSpec("top_library_permission", {"look": True, "cast_spells": True})]


def test_noncreature_restriction():
    specs = static_effect_specs("You may cast noncreature spells from the top of your library.")
    assert specs == [
        EffectSpec("top_library_permission", {
            "look": True, "cast_spells": True, "noncreature_only": True,
        })
    ]


def test_flash_conditional_tail():
    specs = static_effect_specs(
        "You may cast noncreature spells from the top of your library. If you cast "
        "a spell this way, you may cast it as though it had flash."
    )
    assert specs == [
        EffectSpec("top_library_permission", {
            "look": True, "cast_spells": True, "noncreature_only": True, "grants_flash": True,
        })
    ]


def test_life_payment_conditional_tail():
    specs = static_effect_specs(
        "You may play lands and cast spells from the top of your library. If you "
        "cast a spell this way, pay life equal to its mana value rather than pay "
        "its mana cost."
    )
    assert specs == [
        EffectSpec("top_library_permission", {
            "look": True, "play_lands": True, "cast_spells": True, "life_payment": True,
        })
    ]


def test_look_at_top_card_any_time_standalone():
    # The look-only sibling (Sphinx of Jwar Isle-shaped, ~57 real cards with
    # no accompanying play/cast grant) — previously a no-op claimed line at
    # the segmenter level, now a real standalone permission.
    specs = static_effect_specs("You may look at the top card of your library any time.")
    assert specs == [EffectSpec("top_library_permission", {"look": True})]


def test_unrecognized_tail_stays_unclaimed():
    # Fail-closed: a conditional tail outside the two known phrasings isn't
    # half-claimed as the bare permission.
    assert static_effect_specs(
        "You may cast spells from the top of your library. If you cast a "
        "spell this way, exile it instead of putting it into your graveyard."
    ) is None


# -- End-to-end coverage on real cards ----------------------------------------


def test_future_sight_is_modeled():
    card = Card(
        id="Future Sight", name="Future Sight", type_line="Enchantment",
        oracle_text=(
            "Play with the top card of your library revealed.\n"
            "You may play lands and cast spells from the top of your library."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0] == EffectSpec(
        "top_library_permission", {"look": True, "play_lands": True, "cast_spells": True}
    )


def test_sphinx_of_jwar_isle_is_modeled():
    # A real card printing *only* the look-only line, no accompanying
    # play/cast-from-top permission — the standalone case this batch closes.
    card = Card(
        id="Sphinx of Jwar Isle", name="Sphinx of Jwar Isle", type_line="Creature — Sphinx",
        is_creature=True, power=5, toughness=5, keywords=["Flying", "Shroud"],
        oracle_text=(
            "Flying\n"
            "Shroud (This creature can't be the target of spells or abilities.)\n"
            "You may look at the top card of your library any time."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0] == EffectSpec("top_library_permission", {"look": True})


def test_elsha_of_the_infinite_is_modeled():
    card = Card(
        id="Elsha of the Infinite", name="Elsha of the Infinite",
        type_line="Legendary Creature — Human Wizard", is_creature=True, power=1, toughness=4,
        keywords=["Prowess"],
        oracle_text=(
            "Prowess (Whenever you cast a noncreature spell, this creature gets "
            "+1/+1 until end of turn.)\n"
            "You may look at the top card of your library any time.\n"
            "You may cast noncreature spells from the top of your library. If you "
            "cast a spell this way, you may cast it as though it had flash."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    # Two real, separately-printed lines now each claim their own spec: the
    # standalone "you may look at the top card ... any time" line (its own
    # `_LOOK_AT_TOP_ANY_TIME_RE` row) *and* the fuller cast-from-top
    # permission just below it — redundant in practice (the fuller grant
    # already implies `look`) but both are real printed clauses, and
    # `active_top_library_grants` ORs any number of simultaneous grants
    # together harmlessly, so both are faithfully claimed rather than one
    # being silently dropped.
    top_library_specs = [
        e for s in result.specs if s.ability_kind == "static" for e in s.effects
        if e.type == "top_library_permission"
    ]
    assert EffectSpec("top_library_permission", {"look": True}) in top_library_specs
    assert EffectSpec("top_library_permission", {
        "look": True, "cast_spells": True, "noncreature_only": True, "grants_flash": True,
    }) in top_library_specs


def test_bolas_citadel_is_modeled():
    card = Card(
        id="Bolas's Citadel", name="Bolas's Citadel", type_line="Legendary Artifact",
        oracle_text=(
            "You may look at the top card of your library any time.\n"
            "You may play lands and cast spells from the top of your library. If "
            "you cast a spell this way, pay life equal to its mana value rather "
            "than pay its mana cost.\n"
            "{T}, Sacrifice ten nonland permanents: Each opponent loses 10 life."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == MODELED, result.unclaimed
    # Same two-real-lines shape as Elsha above.
    top_library_specs = [
        e for s in result.specs if s.ability_kind == "static" for e in s.effects
        if e.type == "top_library_permission"
    ]
    assert EffectSpec("top_library_permission", {"look": True}) in top_library_specs
    assert EffectSpec("top_library_permission", {
        "look": True, "play_lands": True, "cast_spells": True, "life_payment": True,
    }) in top_library_specs


def test_experimental_frenzy_still_unmodeled_on_its_own_separate_restriction():
    # The permission line itself is now claimed; the card as a whole stays
    # UNMODELED because of its own unrelated "can't play from hand"
    # restriction — a different, unmodeled primitive, not a regression.
    card = Card(
        id="Experimental Frenzy", name="Experimental Frenzy", type_line="Enchantment",
        oracle_text=(
            "You may look at the top card of your library any time.\n"
            "You may play lands and cast spells from the top of your library.\n"
            "You can't play lands or cast spells from your hand.\n"
            "{3}{R}: Destroy this enchantment."
        ),
    )
    result = parse_oracle(card)
    assert result.coverage == UNMODELED
    assert "you may play lands and cast spells from the top of your library." not in result.unclaimed
