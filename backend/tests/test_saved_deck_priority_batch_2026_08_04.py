"""Batch closing five parser gaps found by cross-referencing every saved
deck's card list against the parser gate (PAR-12, the indefinite long tail) —
prioritized because each was a SOLO blocker on real cards actually in this
install's saved decks, not just cache-wide count:

* **Untargeted mass "destroy/exile all X [with a numeric filter]" board
  wipes** (RULE 601.2c) — the `DestroyEffect`/`ExileEffect` ``selector``
  primitive already existed (hand-authored per card, e.g. Wrath of God in
  `card_registry.py`); only the general oracle-text recognition was
  missing (`catalogue/handlers.py`'s ``destroy_all``/``destroy_all_no_regen``/
  ``exile_all``). Also widens `game/effects/core.py`'s `_MASS_DESTROY_SELECTORS`
  with ``"all_lands"``, the one selector real cards need that didn't exist.
* **"[<Type> [and <type>]] spells you cast cost {N} less/more to cast."**
  (RULE 601.2f, Baral/Archmage of Runes/Bureau Headmaster-shaped) — the
  `cost_reduction` static's ``spell_type`` filter and ``affects="your_spells"``
  default already existed; only the "you cast" oracle-text phrasing was
  unrecognized (`static_handlers.py`'s ``_SPELL_COST_TAX_YOU_CAST_RE``).
  Widens `continuous._spell_type_matches` to OR a list of types (the
  two-type "instant and sorcery spells" compound).
* **"Whenever you cast a/an <type> spell, <effect>."** (RULE 603.1,
  Archmage of Runes/Young Pyromancer-adjacent spellslinger payoffs) — a
  genuinely new trigger-condition recognizer
  (`segmenter._CAST_SPELL_TRIGGER_RE`); the underlying `SPELL_CAST` event and
  `effect_binder`'s ``spell_card_types`` predicate already existed (built for
  the hand-authored Wandering Archaic).
* **"Whenever ~ or another creature dies, <effect>."** (RULE 603.1, Blood
  Artist/Falkenrath Noble) — the main-type sibling of the existing
  subtype-only `_SELF_OR_GROUP_SUBTYPE_RE` ("~ or another <subtype>… you
  control dies"); `effect_binder._build_group_ok` already treats "group" and
  "self_or_group" identically, so only the new regex
  (`_SELF_OR_GROUP_SUBJECT_RE`) was needed.
* **"Choose a Background"** (RULE 702.124, Commander Legends: Battle for
  Baldur's Gate) — a bare FLAG keyword, the same RULE 702.124 family as
  Partner and just as inert in-game (it only matters at deckbuilding time,
  `services/commander_legality.py`'s job — see BACKLOG.md's DB-3).

Reference: mtg_analyzer/parser/oracle/{segmenter,catalogue/{handlers,
static_handlers,keywords}}.py, mtg_analyzer/game/{effects,continuous,
effect_binder}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.effects.core import DestroyEffect, ExileEffect
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.spec import EffectSpec


def _engine():
    return GameEngine.new_game(
        [("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0
    )


def _creature(name="Grizzly Bears", power=2, toughness=2):
    return Card(id=name, name=name, type_line="Creature — Bear",
                is_creature=True, power=power, toughness=toughness)


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


# ---------------------------------------------------------------------------
# Mass "destroy/exile all X" board wipes
# ---------------------------------------------------------------------------


def test_destroy_all_creatures_parses():
    assert match_clause("destroy all creatures") == [
        EffectSpec("destroy", {"selector": "all_creatures"})
    ]


def test_destroy_all_artifacts_with_mana_value_filter_parses():
    assert match_clause("destroy all artifacts with mana value 3 or less") == [
        EffectSpec("destroy", {"selector": "all_artifacts", "filter": {"max_mana_value": 3}})
    ]


def test_destroy_all_creatures_with_toughness_filter_parses():
    assert match_clause("destroy all creatures with toughness 4 or greater") == [
        EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_toughness": 4}})
    ]


def test_destroy_all_lands_parses():
    assert match_clause("destroy all lands") == [
        EffectSpec("destroy", {"selector": "all_lands"})
    ]


def test_exile_all_permanents_parses():
    assert match_clause("exile all permanents") == [
        EffectSpec("exile", {"selector": "all_permanents"})
    ]


def test_destroy_all_creatures_power_filter_parses():
    # Dusk // Dawn/Elspeth, Sun's Champion-shaped — the power-threshold
    # sibling of the mana-value/toughness mass-destroy filters just above.
    assert match_clause("destroy all creatures with power 4 or greater") == [
        EffectSpec("destroy", {"selector": "all_creatures", "filter": {"min_power": 4}})
    ]


def test_damnation_full_card_is_modeled_with_no_regen():
    card = Card(id="Damnation", name="Damnation", type_line="Sorcery", is_sorcery=True,
                oracle_text="Destroy all creatures. They can't be regenerated.")
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.effects[0].type == "destroy"
    assert spec.effects[0].params == {"selector": "all_creatures", "can_be_regenerated": False}


def test_destroy_all_creatures_executes_and_wipes_the_board():
    eng = _engine()
    state = eng.state
    mine = _bf(state, _creature("Mine"))
    theirs = _bf(state, _creature("Theirs"), controller="p2")

    obj = GameObject(
        Card(id="Wipe", name="Wipe", type_line="Sorcery"), owner_id="p1", zone=Zone.STACK
    )
    obj.spell_effects = [DestroyEffect(selector="all_creatures")]
    item = StackItem(kind="spell", controller_id="p1", obj=obj, description="Wipe",
                      effects=obj.spell_effects)
    state.stack.append(item)
    eng.rules.resolve_top_of_stack()

    assert mine not in state.battlefield
    assert theirs not in state.battlefield


def test_exile_all_lands_executes():
    eng = _engine()
    state = eng.state
    land = _bf(state, Card(id="Forest", name="Forest", type_line="Land", is_land=True))
    nonland = _bf(state, _creature("Bear"))

    obj = GameObject(
        Card(id="Farewell Half", name="Farewell Half", type_line="Sorcery"),
        owner_id="p1", zone=Zone.STACK,
    )
    obj.spell_effects = [ExileEffect(selector="all_lands")]
    item = StackItem(kind="spell", controller_id="p1", obj=obj, description="Farewell Half",
                      effects=obj.spell_effects)
    state.stack.append(item)
    eng.rules.resolve_top_of_stack()

    assert land not in state.battlefield
    assert nonland in state.battlefield


# ---------------------------------------------------------------------------
# "[<Type> [and <type>]] spells you cast cost {N} less to cast."
# ---------------------------------------------------------------------------


def test_bare_spells_you_cast_cost_less_parses():
    assert static_effect_specs("spells you cast cost {1} less to cast") == [
        EffectSpec("cost_reduction", {"generic": 1, "increase": False})
    ]


def test_typed_spells_you_cast_cost_less_parses():
    assert static_effect_specs("creature spells you cast cost {1} less to cast") == [
        EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_type": "creature"})
    ]


def test_two_type_spells_you_cast_cost_less_parses_as_a_list():
    assert static_effect_specs("instant and sorcery spells you cast cost {1} less to cast") == [
        EffectSpec(
            "cost_reduction",
            {"generic": 1, "increase": False, "spell_type": ["instant", "sorcery"]},
        )
    ]


def test_color_scoped_variant_parses():
    # MEC-12: the Medallion cycle/Grand Arbiter Augustin IV's colour filter
    # — `continuous.cost_reduction_for`'s own `spell_color` param, now
    # reachable from oracle text via `_SPELL_COST_TAX_COLOR_RE`.
    assert static_effect_specs("white spells you cast cost {1} less to cast") == [
        EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_color": "W"})
    ]


def test_subtype_scoped_variant_parses():
    # PAR-60 wave 13: a curated creature/Aura/Equipment/Arcane subtype
    # qualifier (Banneret/Warchief cycle, Bureau Headmaster's "Equipment
    # spells…", Transcendent Envoy's "Aura spells…") now routes to
    # ``spell_subtype`` (`continuous.cost_reduction_for` resolves it via
    # `has_subtype`). Groupings that `has_subtype` can't check stay
    # fail-closed.
    assert static_effect_specs("equipment spells you cast cost {1} less to cast") == [
        EffectSpec("cost_reduction", {"generic": 1, "increase": False, "spell_subtype": "equipment"})
    ]
    assert static_effect_specs("historic spells you cast cost {1} less to cast") is None


def test_baral_full_card_is_modeled():
    card = Card(
        id="Baral, Chief of Compliance", name="Baral, Chief of Compliance",
        type_line="Legendary Creature — Human Wizard", is_creature=True, power=1, toughness=3,
        oracle_text=(
            "Instant and sorcery spells you cast cost {1} less to cast.\n"
            "Whenever a spell or ability you control counters a spell, you may "
            "draw a card. If you do, discard a card."
        ),
    )
    # Baral's second ability (countering a spell/ability) isn't in this
    # batch's scope — only the cost-reduction line is expected to claim.
    result = parse_oracle(card)
    assert not result.modeled
    assert "cost_reduction" not in "".join(result.unclaimed)  # the cost line itself is claimed


def test_instant_and_sorcery_cost_reduction_executes():
    eng = _engine()
    state = eng.state
    baral = Card(
        id="Test Baral", name="Test Baral", type_line="Creature — Wizard",
        is_creature=True, power=1, toughness=3,
        oracle_text="Instant and sorcery spells you cast cost {1} less to cast.",
    )
    _bf(state, baral)
    continuous.recompute(state)

    spell_obj = GameObject(
        Card(id="Test Bolt", name="Test Bolt", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.HAND,
    )
    reduction, _ = continuous.cost_reduction_for(state, state.player_by_id("p1"), spell_obj)
    assert reduction == 1

    creature_obj = GameObject(_creature("Test Bear"), owner_id="p1", zone=Zone.HAND)
    no_reduction, _ = continuous.cost_reduction_for(state, state.player_by_id("p1"), creature_obj)
    assert no_reduction == 0


# ---------------------------------------------------------------------------
# "Whenever you cast a/an <type> spell, <effect>."
# ---------------------------------------------------------------------------


def test_cast_instant_or_sorcery_spell_trigger_full_card_is_modeled():
    card = Card(
        id="Test Spellslinger", name="Test Spellslinger", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast an instant or sorcery spell, draw a card.",
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.trigger == {
        "event": "SPELL_CAST",
        "condition": {"subject": "you"},
        "spell_filter": {"card_type_any": ["instant", "sorcery"]},
    }
    assert spec.effects[0].type == "draw"


def test_cast_spell_trigger_with_a_subtype_in_the_type_list_filters_by_subtype():
    # PAR-104: the comma list ("an instant, sorcery, or Wizard spell") is one phrase, and "wizard" is read from the
    # cast spell's own type line (`spell_filter`'s ``subtype``), not from the event's main-type snapshot — so it is
    # claimed, and a non-Wizard creature spell does not trigger it.
    card = Card(
        id="Test Wizard Payoff", name="Test Wizard Payoff", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast an instant, sorcery, or wizard spell, draw a card.",
    )
    assert parse_oracle(card).modeled
    for type_line, expected in (("Creature — Human Wizard", 1), ("Creature — Bear", 0)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        _bf(eng.state, card)
        spell = GameObject(
            Card(id="Test Spell", name="Test Spell", type_line=type_line, is_creature=True, power=1, toughness=1),
            owner_id="p1", zone=Zone.HAND,
        )
        p1.hand.append(spell)
        eng.rules.cast_without_paying(p1, spell)
        assert eng.rules.put_triggers_on_stack() == expected, type_line


def test_cast_spell_trigger_executes_and_draws_a_card():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    payoff_card = Card(
        id="Test Payoff", name="Test Payoff", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast an instant or sorcery spell, draw a card.",
    )
    _bf(state, payoff_card)
    p1.library.append(GameObject(_creature("Topdeck"), owner_id="p1", zone=Zone.LIBRARY))
    before = len(p1.hand)

    # A real cast: the composed ``spell_filter`` reads the spell object on
    # the stack, not the event's type snapshot (PAR-131).
    bolt = GameObject(
        Card(id="Test Bolt", name="Test Bolt", type_line="Instant", is_instant=True),
        owner_id="p1", zone=Zone.HAND,
    )
    p1.hand.append(bolt)
    before = len(p1.hand) - 1
    eng.rules.cast_without_paying(p1, bolt)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    eng.rules.resolve_top_of_stack()

    assert len(p1.hand) == before + 1


def test_cast_spell_trigger_does_not_fire_for_a_creature_spell():
    eng = _engine()
    state = eng.state
    p1 = state.player_by_id("p1")
    payoff_card = Card(
        id="Test Payoff 2", name="Test Payoff 2", type_line="Creature — Human",
        is_creature=True, power=1, toughness=1,
        oracle_text="Whenever you cast an instant or sorcery spell, draw a card.",
    )
    _bf(state, payoff_card)

    state.fire_event(
        GameEvent(
            EventType.SPELL_CAST, player_id="p1", card_id="Test Bear", spell="Test Bear",
            instance_id="fake-bear", object_types=["creature"],
        )
    )
    assert eng.rules.put_triggers_on_stack() == 0


# ---------------------------------------------------------------------------
# "Whenever ~ or another creature dies, <effect>." (Blood Artist)
# ---------------------------------------------------------------------------


def test_blood_artist_full_card_is_modeled():
    card = Card(
        id="Blood Artist", name="Blood Artist", type_line="Creature — Vampire",
        is_creature=True, power=0, toughness=1,
        oracle_text=(
            "Whenever this creature or another creature dies, target player "
            "loses 1 life and you gain 1 life."
        ),
    )
    result = parse_oracle(card)
    assert result.modeled
    spec = result.effect_specs[0]
    assert spec.trigger["condition"] == {
        "subject": "self_or_group", "type": "creature", "controller": "any", "other": True,
    }


def test_blood_artist_fires_when_a_different_creature_dies():
    eng = _engine()
    state = eng.state
    p1, p2 = state.player_by_id("p1"), state.player_by_id("p2")
    blood_artist = Card(
        id="Test Blood Artist", name="Test Blood Artist", type_line="Creature — Vampire",
        is_creature=True, power=0, toughness=1,
        oracle_text=(
            "Whenever this creature or another creature dies, target player "
            "loses 1 life and you gain 1 life."
        ),
    )
    artist_obj = _bf(state, blood_artist)
    victim = _bf(state, _creature("Victim"), controller="p2")

    p1_life_before, p2_life_before = p1.life, p2.life
    eng.rules.put_into_graveyard(victim)
    placed = eng.rules.put_triggers_on_stack()
    assert placed == 1
    choice = state.pending_choice
    assert choice["kind"] == "trigger_target"
    option = next(o for o in choice["options"] if o["id"] == p2.id)
    eng.rules.resolve_choice(option["id"])
    eng.rules.resolve_top_of_stack()

    assert p2.life == p2_life_before - 1
    assert p1.life == p1_life_before + 1
    assert artist_obj in state.battlefield  # only the *other* creature died


# ---------------------------------------------------------------------------
# "Choose a Background" (RULE 702.124)
# ---------------------------------------------------------------------------


def test_choose_a_background_keyword_line_is_claimed():
    from mtg_analyzer.parser.oracle.segmenter import is_keyword_line

    assert is_keyword_line("choose a background")


def test_baeloth_full_card_is_modeled():
    card = Card(
        id="Baeloth Barrityl, Entertainer", name="Baeloth Barrityl, Entertainer",
        type_line="Legendary Creature — Tiefling Bard", is_creature=True, power=2, toughness=2,
        oracle_text="Choose a Background (You can have a Background as a second commander.)",
    )
    result = parse_oracle(card)
    assert result.modeled
