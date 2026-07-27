"""Batch 7 (docs/implementation-state/BACKLOG.md):
"choose-a-type-as-enters + scoped lords" — RULE 601.2b's "as ~ enters,
choose a creature type/color" plus the dynamic "… of the chosen type/color
…" anthem/grant tail and "~ is the chosen type in addition to its other
types" (Adaptive Automaton/Ward Sliver/A-Thran Portal-shaped).

New primitive: RULE 601.2b's choice happens *as the permanent enters*, not
via a triggered ability, so it's modeled as a second `enter_replacement`
family alongside the existing "enter as a copy of target X" one
(`ChooseCreatureTypeReplacement`/`ChooseColorReplacement`,
`GameObject.enter_choice_effects`, `RulesEngine._offer_enter_choices`/
`resolve_enter_choice`) — offered interactively before battlefield entry,
stamping `GameObject.chosen_type`/`chosen_color`, which `game/continuous.py`
reads back every recompute via the ``subtype_from_source``/
``color_from_source``/``add_subtypes_from_source`` selector params (so a
blink/new-object-identity re-derive is automatic, no special-casing needed
beyond `reset_as_new_object` clearing the two fields — RULE 400.7).

Also folded in, since the plan's interleaved edge case flagged it (memory:
static-lord-anthem-gap) and the engine already supports it end-to-end
(`combat._landwalk_slugs` reads any ``granted_keywords`` entry ending in
"walk" directly): granting a landwalk *variant* via the plain "X have
<keyword>" anthem/grant family (`_flag_keywords`), previously fail-closed
since landwalk is parametric-shaped and every other grantable keyword here
is a bare flag. And, since it fell out of the same "all creatures" group
selector this batch's dynamic-scope regex work touches: "all creatures get
-N/-N until end of turn." (Infest/Blight Grenade-shaped mass removal) — the
`_GROUP`/`_GROUP_SELECTORS` pump-family vocabulary only had "creatures you
control"/"other creatures you control" before, never the board-wide form.

Each family is tested at the parse level (`parse_oracle`, MODELED) **and**
executed against a real engine, per the project's "parse-only verification
has masked real runtime bugs" lesson — the interactive choice especially,
since a wrong `pending_choice`/continuation wire-up wouldn't show up in a
parse-only check at all.

Reference: mtg_analyzer/parser/oracle/catalogue/static_handlers.py,
mtg_analyzer/game/{effects,effect_binder,rules_engine,game_engine,continuous}.py.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.effect_binder import bind_from_catalogue
from mtg_analyzer.models.card import Card
from mtg_analyzer.models.game_object import GameObject, Zone
from mtg_analyzer.models.game_state import GameState
from mtg_analyzer.models.mana_cost import ManaCost
from mtg_analyzer.models.player import Player
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.game.rules_engine import RulesEngine
from mtg_analyzer.parser.oracle.gate import UNMODELED, parse_oracle


def _permanent(name, oracle_text, type_line="Artifact"):
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text)


def _creature(name, oracle_text="", power=2, toughness=2, type_line="Creature — Bear"):
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=oracle_text,
        is_creature=True, power=power, toughness=toughness,
    )


def _rules():
    p1 = Player(id="p1", life=20)
    p2 = Player(id="p2", life=20)
    state = GameState(players=[p1, p2])
    engine = RulesEngine(state)
    return engine, state, p1, p2


def _bf(state, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    state.add_to_battlefield(obj)
    return obj


def make_engine(p1_cards, p2_cards=None, life=20, hand=0):
    libs = [("p1", "Alice", list(p1_cards))]
    if p2_cards is not None:
        libs.append(("p2", "Bob", list(p2_cards)))
    return GameEngine.new_game(libs, starting_life=life, starting_hand=hand)


def artifact_permanent(name, cost="{2}", oracle_text=""):
    return Card(
        id=name, name=name, type_line="Artifact", oracle_text=oracle_text,
        mana_cost_string=cost, converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
    )


# ---------------------------------------------------------------------------
# Parse-side coverage
# ---------------------------------------------------------------------------


def test_adaptive_automaton_is_fully_modeled():
    card = _permanent(
        "Adaptive Automaton",
        "As Adaptive Automaton enters, choose a creature type.\n"
        "Other creatures you control of the chosen type get +1/+1.",
    )
    result = parse_oracle(card)
    assert result.coverage != UNMODELED
    assert result.unclaimed == []


def test_choose_a_creature_type_alone_is_modeled_as_enter_replacement():
    card = _permanent("Type Chooser", "As ~ enters, choose a creature type.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    [spec] = [s for s in result.specs if s.ability_kind == "enter_replacement"]
    assert spec.effects[0].type == "choose_creature_type_on_enter"


def test_choose_a_color_alone_is_modeled_as_enter_replacement():
    card = _permanent("Color Chooser", "As ~ enters, choose a color.")
    result = parse_oracle(card)
    assert result.unclaimed == []
    [spec] = [s for s in result.specs if s.ability_kind == "enter_replacement"]
    assert spec.effects[0].type == "choose_color_on_enter"


def test_caged_sun_shaped_chosen_color_anthem_is_modeled():
    card = _permanent(
        "Chosen Color Anthem",
        "As ~ enters, choose a color.\nCreatures you control of the chosen color get +1/+1.",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].params["color_from_source"] is True


def test_a_thran_portal_shaped_self_type_change_is_modeled():
    card = _permanent(
        "Chosen Type Land",
        "As ~ enters, choose a creature type.\n~ is the chosen type in addition to its other types.",
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "type_change"
    assert static.effects[0].params == {"affects": "self", "add_subtypes_from_source": True}


def test_granted_landwalk_variant_via_plain_have_clause_is_modeled():
    card = _permanent("Forest Grantor", "All creatures have forestwalk.", type_line="Enchantment")
    result = parse_oracle(card)
    assert result.unclaimed == []
    static = next(s for s in result.specs if s.ability_kind == "static")
    assert static.effects[0].type == "grant_keyword"
    assert static.effects[0].params["keywords"] == ["forestwalk"]


def test_bare_landwalk_with_no_type_stays_unclaimed():
    # Fail-closed: never printed on a real card, and the grant mechanism has
    # nowhere to source a land-type parameter from.
    card = _permanent("Bad Grantor", "All creatures have landwalk.", type_line="Enchantment")
    assert parse_oracle(card).coverage == UNMODELED


def test_all_creatures_mass_removal_spell_is_modeled():
    card = Card(
        id="Infest", name="Infest", type_line="Sorcery",
        oracle_text="All creatures get -2/-2 until end of turn.",
        mana_cost_string="{1}{B}", converted_mana_cost=2, is_sorcery=True,
    )
    result = parse_oracle(card)
    assert result.unclaimed == []
    spell = next(s for s in result.specs if s.ability_kind == "spell_effect")
    assert spell.effects[0].params["selector"] == "all_creatures"
    assert (spell.effects[0].params["power"], spell.effects[0].params["toughness"]) == (-2, -2)


# ---------------------------------------------------------------------------
# Execute-side: the chosen-type/color dynamic anthem, off a pre-set choice
# ---------------------------------------------------------------------------


def test_chosen_type_anthem_boosts_only_matching_creatures_and_updates_live():
    engine, state, p1, p2 = _rules()
    lord = _bf(
        state,
        _permanent(
            "Adaptive Automaton",
            "As Adaptive Automaton enters, choose a creature type.\n"
            "Other creatures you control of the chosen type get +1/+1.",
        ),
    )
    goblin = _bf(state, _creature("Goblin Guy", type_line="Creature — Goblin"))
    elf = _bf(state, _creature("Elf Guy", type_line="Creature — Elf"))

    lord.chosen_type = "Goblin"
    continuous.recompute(state)
    assert (goblin.power, goblin.toughness) == (3, 3)
    assert (elf.power, elf.toughness) == (2, 2)

    # Live re-derive: changing the stored choice changes the board next pass,
    # same as any other layer-6/7 static — nothing is baked in at bind time.
    lord.chosen_type = "Elf"
    continuous.recompute(state)
    assert (goblin.power, goblin.toughness) == (2, 2)
    assert (elf.power, elf.toughness) == (3, 3)


def test_chosen_type_anthem_with_no_choice_made_yet_boosts_nothing():
    engine, state, p1, p2 = _rules()
    lord = _bf(
        state,
        _permanent(
            "Adaptive Automaton",
            "As Adaptive Automaton enters, choose a creature type.\n"
            "Other creatures you control of the chosen type get +1/+1.",
        ),
    )
    goblin = _bf(state, _creature("Goblin Guy", type_line="Creature — Goblin"))
    assert lord.chosen_type is None
    continuous.recompute(state)
    assert (goblin.power, goblin.toughness) == (2, 2)


def test_chosen_color_anthem_boosts_only_matching_creatures():
    engine, state, p1, p2 = _rules()
    lord = _bf(
        state,
        _permanent(
            "Caged Sun Shaped",
            "As ~ enters, choose a color.\nCreatures you control of the chosen color get +1/+1.",
        ),
    )
    red = _bf(state, _creature("Red Guy", type_line="Creature — Bear", oracle_text=""))
    red.card.color_identity = {"R"}
    blue = _bf(state, _creature("Blue Guy", type_line="Creature — Bear"))
    blue.card.color_identity = {"U"}

    lord.chosen_color = "R"
    continuous.recompute(state)
    assert (red.power, red.toughness) == (3, 3)
    assert (blue.power, blue.toughness) == (2, 2)


def test_is_the_chosen_type_self_grant_is_live_and_reverts_with_the_choice():
    engine, state, p1, p2 = _rules()
    portal = _bf(
        state,
        _permanent(
            "Chosen Type Land",
            "As ~ enters, choose a creature type.\n"
            "~ is the chosen type in addition to its other types.",
            type_line="Land",
        ),
    )
    assert not continuous.has_subtype(portal, "Goblin")  # no choice made yet

    portal.chosen_type = "Goblin"
    continuous.recompute(state)
    assert continuous.has_subtype(portal, "Goblin")
    assert not continuous.has_subtype(portal, "Elf")

    # Live re-derive, same as the anthem/grant selectors: nothing is baked
    # in at bind time, so changing the stored choice changes layer 4 too.
    portal.chosen_type = "Elf"
    continuous.recompute(state)
    assert continuous.has_subtype(portal, "Elf")
    assert not continuous.has_subtype(portal, "Goblin")


def test_all_creatures_mass_pump_selector_applies_board_wide():
    engine, state, p1, p2 = _rules()
    a = _bf(state, _creature("A"))
    b = _bf(state, _creature("B", type_line="Creature — Bear"), controller="p2")
    from mtg_analyzer.game.effects import PumpEffect

    PumpEffect(power=-2, toughness=-2, selector="all_creatures", source=a).apply(engine.context)
    assert (a.temp_power, a.temp_toughness) == (-2, -2)
    assert (b.temp_power, b.temp_toughness) == (-2, -2)


def test_granted_landwalk_variant_is_recognised_by_combat():
    from mtg_analyzer.game import combat

    engine, state, p1, p2 = _rules()
    grantor = _bf(
        state, _permanent("Forest Grantor", "All creatures have forestwalk.", type_line="Enchantment")
    )
    bear = _bf(state, _creature("Bear"))
    continuous.recompute(state)
    assert combat.landwalk_subtypes(bear) == frozenset({"forest"})


# ---------------------------------------------------------------------------
# Execute-side: the interactive "as ~ enters, choose a …" pick, end to end
# ---------------------------------------------------------------------------


def test_choose_creature_type_end_to_end_via_cast_opens_and_resolves_choice():
    card = artifact_permanent(
        "Adaptive Automaton",
        cost="{3}",
        oracle_text=(
            "As Adaptive Automaton enters, choose a creature type.\n"
            "Other creatures you control of the chosen type get +1/+1."
        ),
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 3})

    # A Goblin in play so "Goblin" is one of the offered options.
    goblin_obj = GameObject(
        Card(id="Goblin", name="Goblin", type_line="Creature — Goblin", is_creature=True,
             power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    goblin_obj.summoning_sick = False
    eng.state.add_to_battlefield(goblin_obj)

    automaton = p1.hand[0]
    bind_from_catalogue(automaton)
    eng.cast_spell(p1, automaton)
    eng.resolve_until_stable()

    pending = eng.state.pending_choice
    assert pending and pending["kind"] == "choose_creature_type"
    assert automaton not in eng.state.battlefield  # paused before entering
    assert any(o["id"] == "Goblin" for o in pending["options"])

    eng.resolve_pending_choice("Goblin")

    assert automaton in eng.state.battlefield
    assert automaton.chosen_type == "Goblin"
    assert (goblin_obj.power, goblin_obj.toughness) == (2, 2)


def test_choose_creature_type_with_missing_answer_defaults_to_first_option():
    card = artifact_permanent(
        "Type Chooser", cost="{1}", oracle_text="As ~ enters, choose a creature type."
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})

    bear_obj = GameObject(
        Card(id="Bear", name="Bear", type_line="Creature — Bear", is_creature=True,
             power=1, toughness=1),
        owner_id="p1", zone=Zone.BATTLEFIELD,
    )
    bear_obj.summoning_sick = False
    eng.state.add_to_battlefield(bear_obj)

    chooser = p1.hand[0]
    bind_from_catalogue(chooser)
    eng.cast_spell(p1, chooser)
    eng.resolve_until_stable()

    assert eng.state.pending_choice["kind"] == "choose_creature_type"
    eng.resolve_pending_choice(None)  # no answer — mandatory choice still resolves

    assert chooser in eng.state.battlefield
    assert chooser.chosen_type == "Bear"  # only option on the board, so it's "first"


def test_choose_creature_type_with_no_creatures_anywhere_does_not_pause():
    card = artifact_permanent(
        "Type Chooser", cost="{1}", oracle_text="As ~ enters, choose a creature type."
    )
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})

    chooser = p1.hand[0]
    bind_from_catalogue(chooser)
    eng.cast_spell(p1, chooser)
    eng.resolve_until_stable()

    assert eng.state.pending_choice is None
    assert chooser in eng.state.battlefield
    assert chooser.chosen_type is None


def test_choose_color_end_to_end_via_cast():
    card = artifact_permanent("Color Chooser", cost="{1}", oracle_text="As ~ enters, choose a color.")
    eng = make_engine([card], hand=1)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"C": 1})

    chooser = p1.hand[0]
    bind_from_catalogue(chooser)
    eng.cast_spell(p1, chooser)
    eng.resolve_until_stable()

    assert eng.state.pending_choice["kind"] == "choose_color"
    eng.resolve_pending_choice("U")

    assert chooser in eng.state.battlefield
    assert chooser.chosen_color == "U"


def test_new_object_identity_forgets_the_chosen_type():
    # RULE 400.7: a new object hasn't made the choice yet either.
    card = _creature("Something", type_line="Creature — Bear")
    obj = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    obj.chosen_type = "Goblin"
    obj.chosen_color = "R"
    obj.reset_as_new_object()
    assert obj.chosen_type is None
    assert obj.chosen_color is None
