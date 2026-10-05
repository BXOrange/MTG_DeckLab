"""PAR-109 — the small residue batch of static/activated abilities and mana.

Closed here:

* "Creatures you control **with `<qualifier>`** get +N/+N / have `<keyword | quoted ability>`" — the group anthem,
  keyword-grant and quoted-grant rows (`static_handlers._ANTHEM_RE`/`_GRANT_RE`/`_QUOTED_GRANT_RE`) gained an
  optional qualifier tail (`_QUAL_TAIL`) read back through the shared `object_filter` grammar: keywords (the
  closed `_FILTER_KEYWORD_WORDS`, widened to the common combat keywords), "+1/+1 / `<kind>` counters on them",
  "that are enchanted/equipped", "that entered this turn", "power N or greater", and "with the chosen name"
  (`card_name_from_source`). `combat.matches_object_filter` gained ``enchanted``/``equipped``.

Reference: parser/oracle/catalogue/static_handlers.py, game/combat.py, game/continuous.py (`affected_objects`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import object_filter, static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, oracle_text="", type_line="Creature — Bird", **kw):
    creature = "Creature" in type_line
    kw.setdefault("is_land", "Land" in type_line)
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature,
                converted_mana_cost=2, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    return eng


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _pt(eng, obj):
    eng.recompute_continuous_effects()
    return obj.power, obj.toughness


# --- parse -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "params"), [
    ("creatures you control with flying get +1/+1.",
     {"affects": "creatures_you_control", "object_filter": {"keyword": "flying"}}),
    ("other creatures you control with flying get +1/+0.",
     {"affects": "other_creatures_you_control", "object_filter": {"keyword": "flying"}}),
    ("creatures you control with +1/+1 counters on them have trample.",
     {"affects": "creatures_you_control", "object_filter": {"has_counter_kind": "+1/+1"}}),
    ("creatures you control with counters on them have trample.",
     {"affects": "creatures_you_control", "object_filter": {"has_counter": True}}),
    ("creatures you control that are enchanted get +1/+1.",
     {"affects": "creatures_you_control", "object_filter": {"enchanted": True}}),
    ("creatures you control with the chosen name have haste.",
     {"affects": "creatures_you_control", "card_name_from_source": True}),
    ("creatures you control with power 4 or greater have haste.",
     {"affects": "creatures_you_control", "object_filter": {"min_power": 4}}),
])
def test_group_qualifier_parses(text, params):
    specs = static_effect_specs(text)
    assert specs is not None, text
    for key, value in params.items():
        assert specs[0].params[key] == value, (text, specs[0].params)


@pytest.mark.parametrize("text", [
    "creatures you control with a pet rock get +1/+1.",         # a qualifier outside the vocabulary
    "creatures you control that are blue get +1/+1.",           # "that are <colour>" is not in the tail
    "creatures you control with flying and a hat get +1/+1.",
])
def test_unknown_qualifier_fails_closed(text):
    assert static_effect_specs(text) is None


def test_object_filter_vocabulary_widened():
    assert object_filter("creatures with vigilance") == {"keyword": "vigilance"}
    assert object_filter("creatures with double strike") == {"keyword": "double_strike"}
    assert object_filter("creatures with oil counters on them") == {"has_counter_kind": "oil"}
    assert object_filter("creatures that entered this turn") == {"entered_this_turn": True}


# --- execute: the layer engine honours the qualifier ---------------------------------------------


def test_flying_qualifier_buffs_only_fliers_and_other_excludes_the_source():
    eng = _engine()
    lord = _bf(eng, _card("Drake", "Other creatures you control with flying get +1/+0.", keywords=["Flying"]))
    flier = _bf(eng, _card("Flier", keywords=["Flying"]))
    ground = _bf(eng, _card("Ground"))
    enemy = _bf(eng, _card("Enemy flier", keywords=["Flying"]), controller="p2")
    assert _pt(eng, flier) == (3, 2)
    assert _pt(eng, ground) == (2, 2)
    assert _pt(eng, enemy) == (2, 2)
    assert _pt(eng, lord) == (2, 2)  # "other"


def test_counter_qualifier_grants_the_keyword_only_to_creatures_holding_one():
    eng = _engine()
    _bf(eng, _card("Training", "Creatures you control with +1/+1 counters on them have trample."))
    plain = _bf(eng, _card("Plain"))
    grown = _bf(eng, _card("Grown"))
    eng.rules.add_counters(grown, 1, "+1/+1")
    eng.recompute_continuous_effects()
    assert "trample" in (grown.granted_keywords or set())
    assert "trample" not in (plain.granted_keywords or set())


def test_enchanted_qualifier_needs_an_aura_on_the_creature():
    eng = _engine()
    _bf(eng, _card("Magemark", "Creatures you control that are enchanted get +1/+1.", type_line="Enchantment"))
    bare = _bf(eng, _card("Bare"))
    dressed = _bf(eng, _card("Dressed"))
    aura = _bf(eng, _card("Aura", type_line="Enchantment — Aura"))
    aura.attached_to = dressed.instance_id
    assert _pt(eng, dressed) == (3, 3)
    assert _pt(eng, bare) == (2, 2)


def test_chosen_name_qualifier_reads_the_sources_choice():
    eng = _engine()
    src = _bf(eng, _card("Callout", "Creatures you control with the chosen name have haste.", type_line="Enchantment"))
    a = _bf(eng, _card("Alpha"))
    b = _bf(eng, _card("Beta"))
    src.chosen_card_name = "Alpha"
    eng.recompute_continuous_effects()
    assert "haste" in (a.granted_keywords or set())
    assert "haste" not in (b.granted_keywords or set())


def test_entered_this_turn_qualifier():
    eng = _engine()
    _bf(eng, _card("Leaper", "Creatures you control that entered this turn have double strike.", type_line="Enchantment"))
    new = _bf(eng, _card("New"))
    eng.recompute_continuous_effects()
    assert "double_strike" in (new.granted_keywords or set())
    new.turn_entered = (new.turn_entered or 0) - 1  # it came in on an earlier turn
    eng.recompute_continuous_effects()
    assert "double_strike" not in (new.granted_keywords or set())


# --- "<subtype>s you control get +N/+N until end of turn" (Lathliss, Ran and Shaw) ----------------

def test_plural_subtype_group_pump_parses_and_hits_only_that_subtype():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    [spec] = match_clause("dragons you control get +1/+0 until end of turn")
    assert spec.type == "pump" and spec.params["selector"]["filter"] == {"subtype": "dragon"}
    # a word that is no creature subtype must stay unclaimed rather than become a bogus subtype filter
    assert match_clause("frobnicators you control get +1/+0 until end of turn") is None

    eng = _engine()
    src = _bf(eng, _card("Queen", "{1}{R}: Dragons you control get +1/+0 until end of turn.",
                         type_line="Creature — Dragon"))
    dragon = _bf(eng, _card("Whelp", type_line="Creature — Dragon"))
    other = _bf(eng, _card("Bear", type_line="Creature — Bear"))
    src.controller_id = "p1"
    eng.state.player_by_id("p1").mana_pool.add_many({"R": 1, "C": 1})
    eng.state.current_step = "main1"
    eng.activate_ability(eng.state.player_by_id("p1"), src, 0)
    eng.resolve_until_stable()
    assert _pt(eng, dragon) == (3, 2) and _pt(eng, src) == (3, 2)
    assert _pt(eng, other) == (2, 2)


# --- "equipped creature gets +N/+N and is every creature type" ---------------------------------------

def test_equipped_creature_is_every_creature_type_and_gets_the_bonus():
    eng = _engine()
    axe = _bf(eng, _card("Axe", "Equipped creature gets +3/+0 and is every creature type.",
                         type_line="Artifact — Equipment"))
    bear = _bf(eng, _card("Bear", type_line="Creature — Bear"))
    other = _bf(eng, _card("Other", type_line="Creature — Bear"))
    assert not continuous.has_subtype(bear, "Elf")
    axe.attached_to = bear.instance_id
    assert _pt(eng, bear) == (5, 2)
    assert continuous.has_subtype(bear, "Elf") and continuous.has_subtype(bear, "Zombie")
    assert not continuous.has_subtype(other, "Elf")


# --- "that many plus 1 of each of those kinds of counters" (Winding Constrictor, Doc Samson) -----------

CONSTRICTOR = ("If 1 or more counters would be put on an artifact or creature you control, that many plus 1 of "
               "each of those kinds of counters are put on that permanent instead.\nIf you would get 1 or more "
               "counters, you get that many plus 1 of each of those kinds of counters instead.")
DOC = ("If you would put 1 or more counters on a permanent you control, put that many plus 1 of each of those kinds "
       "of counters on that permanent instead.")


def test_plus_one_of_each_kind_parses_and_is_modeled():
    assert parse_oracle(_card("Constrictor", CONSTRICTOR)).modeled
    assert parse_oracle(_card("Doc", DOC)).modeled


def test_winding_constrictor_raises_every_kind_for_its_controller_only():
    eng = _engine()
    _bf(eng, _card("Constrictor", CONSTRICTOR))
    mine = _bf(eng, _card("Mine"))
    theirs = _bf(eng, _card("Theirs"), controller="p2")
    eng.rules.add_counters(mine, 2, "+1/+1")
    eng.rules.add_counters(mine, 1, "flying")
    eng.rules.add_counters(theirs, 2, "+1/+1")
    assert mine.counters.get("+1/+1") == 3 and mine.counters.get("flying") == 2
    assert theirs.counters.get("+1/+1") == 2
    me, foe = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.rules.add_player_counters(me, 2, "poison")
    eng.rules.add_player_counters(foe, 2, "poison")
    assert me.poison == 3 and foe.poison == 2  # "if you would get counters" — not the opponent


def test_doc_samson_only_boosts_counters_you_put_on_your_permanents():
    eng = _engine()
    doc = _bf(eng, _card("Doc", DOC))
    mine = _bf(eng, _card("Mine"))
    eng.rules.add_counters(mine, 2, "+1/+1", source=doc)
    assert mine.counters.get("+1/+1") == 3
    eng.rules.add_counters(mine, 2, "+1/+1")  # no causing source of yours: not "you would put"
    assert mine.counters.get("+1/+1") == 5


# --- "Untap ~ during each other player's untap step" ---------------------------------------------------

WATERSKIN = "Untap this artifact during each other player's untap step."


def test_untap_during_each_other_players_untap_step():
    eng = _engine()
    skin = _bf(eng, _card("Waterskin", WATERSKIN, type_line="Artifact"))
    plain = _bf(eng, _card("Plain", type_line="Artifact"))
    assert parse_oracle(_card("Waterskin", WATERSKIN, type_line="Artifact")).modeled
    skin.tapped = plain.tapped = True
    eng.state.active_player_index = 1  # p2's untap step
    eng._step_untap()
    assert not skin.tapped  # untapped although it is p1's
    assert plain.tapped      # an ordinary permanent waits for its own controller's untap step


# --- "permanents your opponents control lose hexproof and indestructible until end of turn" (Shadowspear) ---

def test_opponents_permanents_lose_hexproof_and_indestructible_this_turn():
    from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause

    [spec] = match_clause("permanents your opponents control lose hexproof and indestructible until end of turn")
    assert spec.params["removed_keywords"] == ["hexproof", "indestructible"]
    eng = _engine()
    spear = _bf(eng, _card("Spear", "{1}: Permanents your opponents control lose hexproof and indestructible "
                                    "until end of turn.", type_line="Artifact — Equipment"))
    shielded = _bf(eng, _card("Shielded", keywords=["Hexproof", "Indestructible"]), controller="p2")
    mine = _bf(eng, _card("Mine", keywords=["Hexproof"]))
    eng.recompute_continuous_effects()
    assert "hexproof" in combat_keywords(shielded)
    eng.state.player_by_id("p1").mana_pool.add("C", 1)
    eng.state.current_step = "main1"
    eng.activate_ability(eng.state.player_by_id("p1"), spear, 0)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert not {"hexproof", "indestructible"} & combat_keywords(shielded)
    assert "hexproof" in combat_keywords(mine)


def combat_keywords(obj):
    from mtg_analyzer.game.combat import _obj_keywords

    return {str(k).lower() for k in _obj_keywords(obj)}


# --- "You may activate abilities of creatures you control as though those creatures had haste" ---------

def test_summoning_sick_creature_may_tap_for_an_ability_under_the_static():
    elixir = ("You may activate abilities of creatures you control as though those creatures had haste.")
    assert parse_oracle(_card("Elixir", elixir, type_line="Artifact")).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    sick = _bf(eng, _card("Sick", "{T}: You gain 1 life."))
    sick.summoning_sick = True
    other = _bf(eng, _card("Enemy sick", "{T}: You gain 1 life."), controller="p2")
    other.summoning_sick = True
    assert eng._summoning_sick_for_tap(sick)
    _bf(eng, _card("Elixir", elixir, type_line="Artifact"))
    assert not eng._summoning_sick_for_tap(sick)  # creatures *you* control
    assert eng._summoning_sick_for_tap(other)


# --- "Spend only black mana on X." (Crypt Rats, Crimson Hellkite, Consume Spirit) --------------------

CRYPT_RATS = "{X}: This creature deals X damage to each creature and each player. Spend only black mana on X."


def test_spend_only_color_on_x_is_folded_into_the_cost_not_run_as_an_effect():
    assert parse_oracle(_card("Crypt Rats", CRYPT_RATS)).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    rats = _bf(eng, _card("Crypt Rats", CRYPT_RATS, toughness=9))
    assert rats.activated_abilities[0].cost.x_spend_color == "B"
    assert all(type(e).__name__ != "X_SPEND_COLOR" for e in rats.activated_abilities[0].effects)
    eng.state.current_step = "main1"
    p1.mana_pool.add_many({"R": 2, "B": 1})
    # only the single black mana can pay X: X=1 is affordable, X=3 is not (red cannot pay it)
    ability = rats.activated_abilities[0]
    assert eng.can_activate(p1, rats, ability, x=1)
    assert not eng.can_activate(p1, rats, ability, x=3)
    eng.activate_ability(p1, rats, 0, x=1)
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 19 and p1.life == 19
    assert p1.mana_pool.total() == 2  # the two red mana were never touched


def test_spell_line_sets_the_x_colour_restriction_on_the_card():
    text = "Spend only black mana on X.\nConsume Spirit deals X damage to any target and you gain X life."
    assert parse_oracle(_card("Consume Spirit", text, type_line="Sorcery", is_sorcery=True)).modeled
    spell = GameObject(_card("Consume Spirit", text, type_line="Sorcery", is_sorcery=True), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    assert spell.x_spend_color_restriction == "B"


# --- "Basic lands you control have '{T}: Add {C}{C}. Spend this mana only on costs that contain {X}.'" (Nexos) ---

NEXOS = ('Basic lands you control have "{T}: Add {C}{C}. Spend this mana only on costs that contain {X}."')


def test_basic_land_quoted_mana_grant_is_modeled_with_its_restriction():
    from mtg_analyzer.game.mana_abilities import mana_abilities_for

    specs = static_effect_specs(NEXOS.lower())
    assert specs is not None
    params = specs[0].params
    assert params["mana"] == [{"C": 2}] and params["mana_restriction"] == {"kind": "contains_x"}
    assert params["object_filter"] == {"basic": True}

    eng = _engine()
    _bf(eng, _card("Nexos", NEXOS, type_line="Artifact Creature — Construct"))
    forest = _bf(eng, _card("Forest", type_line="Basic Land — Forest"))
    nonbasic = _bf(eng, _card("Tower", type_line="Land"))
    eng.recompute_continuous_effects()
    granted = lambda o: [a for a in mana_abilities_for(o)]  # noqa: E731
    assert any(getattr(a, "restriction", None) for a in granted(forest)) or forest.granted_mana_options
    assert not nonbasic.granted_mana_options


def test_laezel_boosts_counters_on_your_creatures_planeswalkers_and_yourself_only_when_you_cause_them():
    text = ("If you would put 1 or more counters on a creature or planeswalker you control or on yourself, put that "
            "many plus 1 of each of those kinds of counters on that permanent or player instead.")
    assert parse_oracle(_card("Laezel", text)).modeled
    pir = "If 1 or more counters would be put on a permanent your team controls, that many plus 1 of each of those kinds of counters are put on that permanent instead."
    assert parse_oracle(_card("Pir", pir)).modeled
    eng = _engine()
    lz = _bf(eng, _card("Laezel", text))
    mine = _bf(eng, _card("Mine"))
    me = eng.state.player_by_id("p1")
    eng.rules.add_counters(mine, 1, "+1/+1", source=lz)
    assert mine.counters.get("+1/+1") == 2
    eng.rules.add_player_counters(me, 1, "energy", source=lz)
    assert me.counters.get("energy") == 2
    eng.rules.add_player_counters(eng.state.player_by_id("p2"), 1, "energy", source=lz)  # an opponent: not "yourself"
    assert eng.state.player_by_id("p2").counters.get("energy") == 1
