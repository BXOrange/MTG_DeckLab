"""PAR-120 — count phrases as structured selectors, and count conditions.

"How many X" was one named branch per phrase in `continuous.count_selector` plus
eleven phrase tables in the parser. `catalogue/count_phrase.py` reads the phrase
with the shared noun-phrase grammar into ``{"zone", "of", "filter", "distinct"}``,
`continuous.count_selector` evaluates it through `matches_object_filter`, and both
"for each `<count>`" amounts and the comparator half of a leading "if" use it.

Parse tests pin the grammar (and that it fails closed); the equivalence test pins
the structured selectors to the legacy named ones they replace; execute tests run
real resolutions and a real conditional static.
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.continuous import count_selector
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.count_phrase import (
    parse_count_condition,
    parse_count_phrase,
)
from mtg_analyzer.parser.oracle.spec import (
    SELECTOR_DISTINCT,
    SELECTOR_SCOPES,
    SELECTOR_ZONES,
    AbilitySpec,
    EffectSpec,
    SpecValidationError,
)

from tests.test_par119_cast_trigger_grammar import _engine
from tests.test_par119_object_trigger_head import _fire_enter, _named

# ---------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase, expected",
    [
        ("creatures you control",
         {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}),
        ("creature you control",
         {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}),
        ("elves you control",
         {"zone": "battlefield", "of": "you", "filter": {"subtype": "elf"}}),
        ("tapped creatures you control",
         {"zone": "battlefield", "of": "you", "filter": {"tapped": True, "card_type": "creature"}}),
        ("nonland permanents your opponents control",
         {"zone": "battlefield", "of": "opponents", "filter": {"without_card_type": "land"}}),
        ("basic lands you control",
         {"zone": "battlefield", "of": "you", "filter": {"basic": True, "card_type": "land"}}),
        ("wizards on the battlefield",
         {"zone": "battlefield", "of": "any", "filter": {"subtype": "wizard"}}),
        ("creature cards in your graveyard",
         {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}}),
        ("cards in your hand", {"zone": "hand", "of": "you"}),
        ("cards in all graveyards", {"zone": "graveyard", "of": "any"}),
        ("creature cards in your opponents' graveyards",
         {"zone": "graveyard", "of": "opponents", "filter": {"card_type": "creature"}}),
        ("creatures you control with different powers",
         {"distinct": "power", "zone": "battlefield", "of": "you",
          "filter": {"card_type": "creature"}}),
    ],
)
def test_count_phrase_parses(phrase, expected):
    assert parse_count_phrase(phrase) == expected


@pytest.mark.parametrize(
    "phrase",
    [
        "frobnicators you control",
        "creatures you control you control",
        "creature cards you control in your graveyard",   # a controller tail contradicts the zone
        "goblin warriors you control",                    # two subtypes are not one object phrase
        "",
    ],
)
def test_count_phrase_fails_closed(phrase):
    assert parse_count_phrase(phrase) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("you control three or more gates",
         {"kind": "control_count", "min": 3,
          "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "gate"}}}),
        ("you control no untapped lands",
         {"kind": "control_count", "max": 0,
          "selector": {"zone": "battlefield", "of": "you",
                       "filter": {"tapped": False, "card_type": "land"}}}),
        ("you control another wolf or werewolf",
         {"kind": "control_count", "min": 1,
          "selector": {"zone": "battlefield", "of": "you",
                       "filter": {"subtype_any": ["wolf", "werewolf"], "not_reference": True}}}),
        ("you control exactly one creature",
         {"kind": "control_count", "min": 1, "max": 1,
          "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}}}),
        ("you control four or fewer lands",
         {"kind": "control_count", "max": 4,
          "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}}}),
        ("you control 2 or more creatures with different powers",
         {"kind": "control_count", "min": 2,
          "selector": {"distinct": "power", "zone": "battlefield", "of": "you",
                       "filter": {"card_type": "creature"}}}),
        ("there are seven or more creature cards in your graveyard",
         {"kind": "control_count", "min": 7,
          "selector": {"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}}}),
        ("there are no cards in your graveyard",
         {"kind": "control_count", "max": 0, "selector": {"zone": "graveyard", "of": "you"}}),
        ("there are fewer than 3 cards in your library",
         {"kind": "control_count", "max": 2, "selector": {"zone": "library", "of": "you"}}),
        ("an opponent controls more lands than you",
         {"kind": "opponent_has_more",
          "selector": {"zone": "battlefield", "of": "you", "filter": {"card_type": "land"}}}),
    ],
)
def test_count_condition_parses(text, expected):
    assert parse_count_condition(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "you control a desert or there is a desert card in your graveyard",  # a compound
        "you control your commander",
        "you control frobnicators",
        "an opponent controls more cards in their graveyard than you",       # only the battlefield
        "there are many creatures",
    ],
)
def test_count_condition_fails_closed(text):
    assert parse_count_condition(text) is None


def test_spec_validation_rejects_a_bad_selector():
    def spec(selector):
        return AbilitySpec("spell_effect", [EffectSpec("bind", {
            "name": "n",
            "amount": {"kind": "count_selector", "selector": selector},
            "effects": [{"type": "draw", "params": {"count": "$n"}}],
        })])

    spec({"zone": "graveyard", "of": "you", "filter": {"card_type": "creature"}}).validate()
    for bad in ({"zone": "mars"}, {"of": "everyone"}, {"frob": 1}, {"filter": "creature"},
                {"distinct": "colour"}):
        with pytest.raises(SpecValidationError):
            spec(bad).validate()


def test_the_spec_vocabularies_match_the_engines():
    assert SELECTOR_ZONES == {"battlefield"} | set(continuous.COUNT_SELECTOR_ZONES)
    assert SELECTOR_DISTINCT == set(continuous._DISTINCT_KEYS)
    assert SELECTOR_SCOPES == {"you", "opponents", "any"}


# ---------------------------------------------------------------------------
# Equivalence with the legacy named selectors these replace
# ---------------------------------------------------------------------------


def _board():
    engine, state = _engine()
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")

    def put(owner, types, zone, colors=(), power=None, toughness=None, tapped=False, name=None):
        # The legacy named selectors read the `Card.is_*` flags, which a type line
        # alone does not set — give them the flags a real card would have.
        card = Card(id=name or types, name=name or types, type_line=types,
                    is_creature="Creature" in types, is_land="Land" in types,
                    is_instant="Instant" in types, is_sorcery="Sorcery" in types,
                    power=power, toughness=toughness, color_identity=set(colors))
        obj = GameObject(card, owner_id=owner, zone=zone)
        obj.controller_id = owner
        obj.tapped = tapped
        player = state.player_by_id(owner)
        if zone == Zone.BATTLEFIELD:
            state.add_to_battlefield(obj)
        elif zone == Zone.GRAVEYARD:
            player.graveyard.append(obj)
        else:
            player.hand.append(obj)
        return obj

    for owner in ("p1", "p2"):
        put(owner, "Creature — Bear", Zone.BATTLEFIELD, "G", 2, 2, name=f"{owner}bear")
        put(owner, "Creature — Elf", Zone.BATTLEFIELD, "G", 1, 1, tapped=True, name=f"{owner}elf")
        put(owner, "Artifact", Zone.BATTLEFIELD, name=f"{owner}rock")
        put(owner, "Enchantment", Zone.BATTLEFIELD, "W", name=f"{owner}ench")
        put(owner, "Basic Land — Forest", Zone.BATTLEFIELD, name=f"{owner}forest")
        put(owner, "Land", Zone.BATTLEFIELD, name=f"{owner}land")
        put(owner, "Creature — Bear", Zone.GRAVEYARD, "G", 2, 2, name=f"{owner}gybear")
        put(owner, "Instant", Zone.GRAVEYARD, "R", name=f"{owner}bolt")
        put(owner, "Artifact — Equipment", Zone.GRAVEYARD, name=f"{owner}gyequip")
        put(owner, "Land", Zone.HAND, name=f"{owner}handland")
        put(owner, "Creature — Bear", Zone.HAND, "G", 2, 2, name=f"{owner}handbear")
    return state


@pytest.mark.parametrize(
    "phrase, legacy",
    [
        ("creatures you control", "creatures_you_control"),
        ("tapped creatures you control", "tapped_creatures_you_control"),
        ("lands you control", "lands_you_control"),
        ("permanents you control", "permanents_you_control"),
        ("nonland permanents you control", "nonland_permanents_you_control"),
        ("artifacts you control", "artifacts_you_control"),
        ("enchantments you control", "enchantments_you_control"),
        ("artifacts your opponents control", "artifacts_opponents_control"),
        ("creatures your opponents control", "creatures_opponents_control"),
        ("cards in your graveyard", "cards_in_your_graveyard"),
        ("creature cards in your graveyard", "creature_cards_in_your_graveyard"),
        ("permanent cards in your graveyard", "permanent_cards_in_your_graveyard"),
        ("creature cards in your opponents' graveyards", "creature_cards_in_your_opponents_graveyards"),
        ("instant or sorcery cards in your graveyard", "instant_or_sorcery_cards_in_your_graveyard"),
        ("cards in your hand", "cards_in_your_hand"),
    ],
)
def test_structured_selector_agrees_with_the_named_one(phrase, legacy):
    state = _board()
    selector = parse_count_phrase(phrase)
    assert selector is not None, phrase
    for player in ("p1", "p2"):
        assert count_selector(state, player, selector) == count_selector(state, player, legacy), (
            f"{phrase!r} for {player}"
        )


# ---------------------------------------------------------------------------
# Real cards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Aerial Assault", "Airborne Aid", "Apothecary Geist", "Archway Angel", "Demonic Rising",
        "Elvish Reclaimer", "Gorilla Titan", "Grim Flowering", "Hour of Revelation",
        "Kessig Cagebreakers", "Loyal Warhound", "Match the Odds", "Mark of the Oni",
        "Nantuko Shaman", "Pulse of the Tangle", "Thran Quarry", "Wildwood Tracker",
    ],
)
def test_real_cards_are_modeled(name):
    assert parse_oracle(_named(name)).modeled is True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _put(state, oracle, name="Source", types="Creature — Bear", owner="p1", **kw):
    is_creature = "Creature" in types
    card = Card(id=name, name=name, type_line=types, oracle_text=oracle, is_creature=is_creature,
                power=2 if is_creature else None, toughness=2 if is_creature else None, **kw)
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def _creature(state, name, types="Creature — Bear", owner="p1", keywords=(), tapped=False):
    card = Card(id=name, name=name, type_line=types, is_creature=True, power=1, toughness=1,
                keywords=list(keywords))
    obj = GameObject(card, owner_id=owner, zone=Zone.BATTLEFIELD)
    obj.controller_id = owner
    obj.tapped = tapped
    state.add_to_battlefield(obj)
    return obj


def _life_change(engine, state, action):
    life = state.player_by_id("p1").life
    action()
    engine.resolve_until_stable()
    return state.player_by_id("p1").life - life


def test_for_each_reads_a_structured_selector_at_resolution():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, you gain 1 life for each creature you control with flying.",
                  types="Creature — Bird")
    _creature(state, "Sparrow", "Creature — Bird", keywords=["Flying"])
    _creature(state, "Hawk", "Creature — Bird", keywords=["Flying"])
    _creature(state, "Bear")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 2
    _creature(state, "Eagle", "Creature — Bird", keywords=["Flying"])
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 3


def test_for_each_counts_cards_in_a_graveyard_and_scales_a_printed_number():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, you gain 2 life for each creature card in your graveyard.")
    p1 = state.player_by_id("p1")
    for i in range(3):
        card = Card(id=f"G{i}", name=f"G{i}", type_line="Creature — Bear", is_creature=True,
                    power=1, toughness=1)
        p1.graveyard.append(GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD))
    p1.graveyard.append(GameObject(Card(id="I", name="I", type_line="Instant"),
                                   owner_id="p1", zone=Zone.GRAVEYARD))
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 6


def test_if_you_control_no_untapped_lands_gates_the_effect():
    engine, state = _engine()
    state.current_step = "main1"
    oracle = "When ~ enters, if you control no untapped lands, you gain 5 life."
    source = _put(state, oracle)
    land = _put(state, "", "Forest", types="Basic Land — Forest")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    land.tapped = True
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 5


def test_another_excludes_the_source_from_the_count():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if you control another Wizard, you gain 3 life.",
                  types="Creature — Wizard")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    _creature(state, "Apprentice", "Creature — Wizard")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 3


def test_a_graveyard_threshold_condition():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if there are three or more creature cards in your graveyard, you gain 4 life.")
    p1 = state.player_by_id("p1")

    def add():
        i = len(p1.graveyard)
        card = Card(id=f"G{i}", name=f"G{i}", type_line="Creature — Bear", is_creature=True,
                    power=1, toughness=1)
        p1.graveyard.append(GameObject(card, owner_id="p1", zone=Zone.GRAVEYARD))

    add(); add()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    add()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 4


def test_an_opponent_controlling_more_is_compared_per_opponent():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if an opponent controls more lands than you, you gain 2 life.")
    _put(state, "", "MyLand", types="Land")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    _put(state, "", "TheirLand1", types="Land", owner="p2")
    _put(state, "", "TheirLand2", types="Land", owner="p2")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 2


def test_a_conditional_static_reads_the_structured_selector_live():
    # "As long as you control another multicolored permanent, this creature gets +1/+1."
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "As long as you control another multicolored permanent, this creature gets +1/+1.",
                  types="Creature — Bear")
    engine.recompute_continuous_effects()
    assert source.power == 2
    _put(state, "", "Gold", types="Artifact", color_identity={"R", "G"})
    engine.recompute_continuous_effects()
    assert source.power == 3


# ---------------------------------------------------------------------------
# "where X is the number of …" and "<life|cards|damage> equal to the number of …"
# ---------------------------------------------------------------------------

from mtg_analyzer.parser.oracle.segmenter import parse_effect_body  # noqa: E402


@pytest.mark.parametrize(
    "body, effect_type, params",
    [
        ("you gain 1 life for each wizard you control.", "bind", None),
        ("each opponent loses x life, where x is the number of creatures with defender you control.",
         "bind", {"amount": "$n"}),
        ("draw x cards, where x is the number of bobbleheads you control.", "bind", {"count": "$n"}),
        ("each opponent loses life equal to the number of creature cards in your graveyard.",
         "bind", {"amount": "$n"}),
    ],
)
def test_where_x_and_equal_to_bind_a_measured_count(body, effect_type, params):
    specs = parse_effect_body(body)
    assert specs is not None and len(specs) == 1 and specs[0].type == effect_type
    if params is not None:
        assert specs[0].params["effects"][0]["params"] == {**specs[0].params["effects"][0]["params"], **params}
    assert specs[0].params["amount"]["kind"] in ("count_selector", "resource")


@pytest.mark.parametrize(
    "body",
    [
        "you gain x life, where x is the number of frobnicators in exile.",      # unknown word
        "you gain x life, where x is the number of creatures you control you control.",
    ],
)
def test_where_x_fails_closed(body):
    assert parse_effect_body(body) is None


def test_an_ambiguous_it_is_not_measured_against_an_empty_referent():
    # "…, where X is the number of age counters on it" in an end-step trigger: "it"
    # is neither a self-subject trigger's source nor an earlier clause's target here,
    # so the counters phrase is refused instead of reading 0 counters off nothing.
    assert parse_effect_body(
        "this enchantment deals x damage divided as you choose among any number of target "
        "creatures, where x is the number of age counters on it."
    ) is None
    # With "~" it is unambiguous.
    assert parse_effect_body(
        "you gain x life, where x is the number of age counters on ~."
    ) is not None


def test_a_targeted_where_x_body_is_offered_a_target_and_measures_at_resolution():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(
        state,
        "When ~ enters, it deals X damage to target creature an opponent controls, "
        "where X is the number of Wizards you control.",
        types="Creature — Wizard",
    )
    _creature(state, "Apprentice", "Creature — Wizard")
    victim = _creature(state, "Victim", owner="p2")
    victim.card.toughness = 9
    _fire_enter(engine, state, source)
    assert state.pending_choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    assert victim.damage_marked == 2
    _creature(state, "Third", "Creature — Wizard")
    _fire_enter(engine, state, source)
    engine.rules.resolve_choice(state.pending_choice["options"][0]["id"])
    engine.resolve_until_stable()
    assert victim.damage_marked == 5


def test_equal_to_the_number_of_cards_in_a_graveyard_gains_that_much_life():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, you gain life equal to the number of creature cards in all graveyards.")
    for owner in ("p1", "p2"):
        card = Card(id=f"D{owner}", name=f"D{owner}", type_line="Creature — Bear", is_creature=True,
                    power=1, toughness=1)
        state.player_by_id(owner).graveyard.append(GameObject(card, owner_id=owner, zone=Zone.GRAVEYARD))
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 2


# ---------------------------------------------------------------------------
# "you control a <Type>" — the open-vocabulary template the old table row refused
# ---------------------------------------------------------------------------


def test_a_named_row_that_declines_still_lets_the_count_grammar_read_the_condition():
    # The older "you control N or more <named thing>" row matches this text and has no
    # reading for "gates" — it must not swallow the clause.
    from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_condition

    assert static_condition("you control 3 or more gates") == {
        "kind": "control_count", "min": 3,
        "selector": {"zone": "battlefield", "of": "you", "filter": {"subtype": "gate"}},
    }


def test_a_planeswalker_type_condition_reads_the_planeswalker_subtype():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "When ~ enters, if you control an Ajani planeswalker, you gain 4 life.")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    _put(state, "", "Ajani, Test", types="Legendary Planeswalker — Ajani")
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 4


def test_a_static_keyword_grant_follows_the_count_live():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(state, "This creature has flying as long as you control a Dragon.")
    engine.recompute_continuous_effects()
    assert "flying" not in {k.lower() for k in source.granted_keywords}
    dragon = _put(state, "", "Drake", types="Creature — Dragon")
    engine.recompute_continuous_effects()
    assert "flying" in {k.lower() for k in source.granted_keywords}
    state.remove_from_battlefield(dragon)
    engine.recompute_continuous_effects()
    assert "flying" not in {k.lower() for k in source.granted_keywords}


def test_distinct_powers_counts_different_values_not_creatures():
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(
        state,
        "When ~ enters, if you control three or more creatures with different powers, you gain 6 life.",
    )
    for name, power in (("A", 1), ("B", 1), ("C", 2)):
        obj = _creature(state, name)
        obj.card.power = power
    engine.recompute_continuous_effects()
    # the source itself has power 2: powers are {1, 2}
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 0
    third = _creature(state, "D")
    third.card.power = 3
    engine.recompute_continuous_effects()
    assert _life_change(engine, state, lambda: _fire_enter(engine, state, source)) == 6


def test_pt_cda_reads_a_structured_selector_live():
    # PAR-120: `_PT_CDA_SELECTORS`' four duplicate rows (cards in your hand /
    # lands you control / cards in your graveyard / creatures you control)
    # retired in favour of the shared `count_phrase` grammar, which now
    # reaches `pt_cda`'s layer-7a pass as a `{zone, of, filter}` dict rather
    # than a named string — `continuous.recompute`'s own `str(p_sel)` call
    # would have silently stringified that dict into a garbage selector name
    # (a real, previously-latent bug this migration surfaced and fixed).
    engine, state = _engine()
    state.current_step = "main1"
    source = _put(
        state, "~'s power and toughness are each equal to the number of Elves you control.",
        types="Creature — Golem",
    )
    engine.recompute_continuous_effects()
    assert (source.power, source.toughness) == (0, 0)
    _put(state, "", "Elf A", types="Creature — Elf")
    _put(state, "", "Elf B", types="Creature — Elf")
    engine.recompute_continuous_effects()
    assert (source.power, source.toughness) == (2, 2)


def test_group_selector_objects_accepts_a_structured_selector():
    # PAR-120 (PARSER_VERSION 473): `group_selector_objects` — the object-
    # returning sibling of `count_selector`, backing `for_each`/`PumpEffect.
    # selector`/every static's own `affects` — reads a structured selector
    # directly now, the same shape `count_selector` already did. Proven
    # against a real board, not just that it doesn't crash: the two forms
    # must pick out the identical objects.
    engine, state = _engine()
    p1 = state.player_by_id("p1")
    p2 = state.player_by_id("p2")
    mine = _creature(state, "Mine")
    _creature(state, "Theirs", owner="p2")
    named = continuous.group_selector_objects(state, "p1", "creatures_you_control")
    structured = continuous.group_selector_objects(
        state, "p1",
        {"zone": "battlefield", "of": "you", "filter": {"card_type": "creature"}},
    )
    assert [o.name for o in named] == [o.name for o in structured] == ["Mine"]
    assert structured[0] is mine

    # A structured selector naming a non-battlefield zone matches nothing —
    # this function is inherently battlefield-scoped (its own docstring),
    # unlike `count_selector`, which reads any zone.
    assert continuous.group_selector_objects(
        state, "p1", {"zone": "hand", "of": "you"},
    ) == []
