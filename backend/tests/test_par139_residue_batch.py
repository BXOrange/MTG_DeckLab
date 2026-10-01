"""PAR-139 — the small verified residue batch.

Closed here (each its own axis, none a one-card row):

* ``extra_etb_counter`` gained a ``filter`` (+ ``other``): "Each [other] `<kind>` you control enters with an
  additional +1/+1 counter on it." (Grumgully, Bramblewood Paragon, Dragonstorm Globe, Sage of Fables, …).
* A trigger *condition* may contain a comma that continues a noun-phrase list — "whenever you discard a
  noncreature, nonland card, draw a card" / "…an island, pirate, or vehicle card, create …" (`_TRIGGER_RE`).
* "~ deals 2 damage to any target. If you're the monarch, it deals 7 damage instead." (Court of Ire): a
  replacement that names no recipient hits the base's own.

Reference: game/continuous.py (`extra_etb_counters_for`), parser/oracle/catalogue/static_handlers.py
(`_extra_etb_counter_specs`), parser/oracle/segmenter.py (`_TRIGGER_RE`, `_resolve_override_referents`).
"""

from __future__ import annotations

import pytest

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.static_handlers import static_effect_specs
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body


def _card(name, type_line="Creature — Bear", oracle_text="", **kw):
    kw.setdefault("converted_mana_cost", 2)
    creature = "Creature" in type_line
    kw.setdefault("power", 2 if creature else None)
    kw.setdefault("toughness", 2 if creature else None)
    return Card(id=name, name=name, type_line=type_line, oracle_text=oracle_text, is_creature=creature, **kw)


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _enter(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    eng.rules._put_searched_card(eng.state.player_by_id(controller), obj, "battlefield")
    return obj


# --- entry counters for the others ------------------------------------------


def test_static_parses_the_others_form():
    [spec] = static_effect_specs("each other warrior creature you control enters with an additional +1/+1 counter on it.")
    assert spec.type == "extra_etb_counter"
    assert spec.params == {"kind": "+1/+1", "count": 1, "filter": {"subtype": "Warrior"}, "other": True}
    [spec] = static_effect_specs("each dragon you control enters with an additional +1/+1 counter on it.")
    assert spec.params["other"] is False and spec.params["filter"] == {"subtype": "Dragon"}
    assert static_effect_specs("each other creature you control enters with a +1/+1 counter on it.") is None


@pytest.mark.parametrize("name", ["Bramblewood Paragon", "Grumgully, the Generous", "Sage of Fables"])
def test_real_cards_are_modeled(name):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    if not DEFAULT_DB_PATH.exists():
        pytest.skip("card cache not present in this environment")
    card = CardDatabase(DEFAULT_DB_PATH).get_card(name)
    if card is None:
        pytest.skip(f"{name!r} not in the local card cache")
    assert parse_oracle(card).modeled


PARAGON = "Each other Warrior creature you control enters with an additional +1/+1 counter on it."


def test_matching_creatures_of_the_controller_enter_with_the_counter():
    eng = _engine()
    paragon = _bf(eng, _card("Paragon", "Creature — Warrior", PARAGON))
    warrior = _enter(eng, _card("Warrior", "Creature — Warrior"))
    assert warrior.plus_one_counters == 1
    assert _enter(eng, _card("Bear", "Creature — Bear")).plus_one_counters == 0  # wrong subtype
    assert _enter(eng, _card("Enemy", "Creature — Warrior"), controller="p2").plus_one_counters == 0
    assert paragon.plus_one_counters == 0  # "other": the source never counts for itself


def test_each_without_other_counts_the_source_when_it_matches():
    eng = _engine()
    globe_text = "Each Dragon you control enters with an additional +1/+1 counter on it."
    source = _bf(eng, _card("Globe", "Artifact", globe_text))
    assert _enter(eng, _card("Whelp", "Creature — Dragon")).plus_one_counters == 1
    assert source.plus_one_counters == 0  # an Artifact is not a Dragon


# --- trigger conditions with a list comma ---------------------------------------


def test_discard_trigger_with_a_comma_in_its_adjective_list_is_modeled():
    for name, text in {
        "Bone Miser": "Whenever you discard a noncreature, nonland card, draw a card.",
        "Mary Read": "Whenever you discard an island, pirate, or vehicle card, create a tapped Treasure token.",
    }.items():
        assert parse_oracle(_card(name, oracle_text=text)).modeled, name


def test_a_body_that_merely_follows_a_comma_is_not_swallowed_into_the_condition():
    # "draw a card" has no list separator: the comma still ends the condition
    result = parse_oracle(_card("Gnat", oracle_text="Whenever ~ attacks, draw a card."))
    assert result.modeled


# --- "instead" with an implicit recipient --------------------------------------


def test_override_without_a_recipient_hits_the_bases_own_target():
    specs = parse_effect_body("~ deals 2 damage to any target. if you're the monarch, it deals 7 damage instead.")
    [bind] = specs
    assert bind.type == "bind"
    assert bind.params["amount"] == {"kind": "if", "condition": {"kind": "is_monarch"}, "then": 7, "otherwise": 2}
    assert bind.params["effects"] == [{"type": "damage", "params": {"amount": "$n", "target_kind": "any"}}]


# --- "its owner shuffles their graveyard into their library" ------------------------------------

EMRAKUL = "When this creature is put into a graveyard from anywhere, its owner shuffles their graveyard into their library."


def test_put_into_graveyard_trigger_shuffles_the_owners_graveyard_in():
    eng = _engine()
    emrakul = _bf(eng, _card("Emrakul", "Creature — Eldrazi", EMRAKUL))
    emrakul.controller_id = "p2"  # stolen: the *owner's* graveyard still shuffles, not the thief's
    owner, thief = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    for name in ("Old A", "Old B"):
        card = GameObject(_card(name, "Sorcery"), owner_id="p1", zone=Zone.GRAVEYARD)
        owner.graveyard.append(card)
    thief_card = GameObject(_card("Thief card", "Sorcery"), owner_id="p2", zone=Zone.GRAVEYARD)
    thief.graveyard.append(thief_card)
    eng.rules.put_into_graveyard(emrakul)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert owner.graveyard == []
    assert sorted(o.name for o in owner.library) == ["Emrakul", "Old A", "Old B"]
    assert thief.graveyard == [thief_card]


# --- "if its madness cost was paid" (RULE 702.35) -----------------------------------------------

SCRABBLER = ("Madness {1}{U}\nWhen this creature enters, if its madness cost was paid, you may return target "
             "creature card from a graveyard to its owner's hand.")


def _scrabbler(eng):
    card = _card("Scrabbler", "Creature — Zombie", SCRABBLER, mana_cost_string="{3}{B}", keywords=["Madness"])
    obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(obj)
    eng.state.player_by_id("p1").add_to_zone(obj, Zone.HAND)
    dead = GameObject(_card("Dead", "Creature — Bear"), owner_id="p2", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p2").graveyard.append(dead)
    return obj, dead


def _answer(eng):
    while eng.state.pending_choice is not None:
        options = eng.state.pending_choice["options"]
        pick = next((o for o in options if o.get("id") not in (None, "decline", "skip")), None)
        eng.rules.resolve_choice(pick["id"] if pick else None)
        eng.resolve_until_stable()


def test_madness_cast_pays_the_flag_and_the_enters_trigger_fires():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj, dead = _scrabbler(eng)
    eng.rules.discard(p1, 1)
    assert obj.zone == Zone.EXILE and obj.madness_exiled
    p1.mana_pool.add("U", 1)
    p1.mana_pool.add("C", 1)
    eng.cast_spell(p1, obj, alt_cost=True)
    assert obj.madness_cost_paid
    eng.resolve_until_stable()
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    _answer(eng)
    assert dead in eng.state.player_by_id("p2").hand  # returned to its owner's hand


def test_hard_cast_does_not_pay_the_madness_flag():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    obj, dead = _scrabbler(eng)
    p1.mana_pool.add_many({"B": 1, "C": 3})
    eng.cast_spell(p1, obj)
    assert not obj.madness_cost_paid
    eng.resolve_until_stable()
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    _answer(eng)
    assert dead in eng.state.player_by_id("p2").graveyard  # the intervening-if was false: nothing returned


# --- "prevent that damage. <rider keyed on the amount prevented>" ------------------------------

HYDRA = ("If damage would be dealt to this creature, prevent that damage. Put a -1/-1 counter on this creature for "
         "each 1 damage prevented this way.")
CAPRIDOR = ("If noncombat damage would be dealt to this creature, prevent that damage. Put a +1/+1 counter on this "
            "creature for each 1 damage prevented this way.")
PURITY = "If noncombat damage would be dealt to you, prevent that damage. You gain life equal to the damage prevented this way."
VIGOR = ("If damage would be dealt to another creature you control, prevent that damage. Put a +1/+1 counter on that "
         "creature for each 1 damage prevented this way.")


def _hit(eng, target, amount, combat=False):
    source = _bf(eng, _card("Zapper", "Creature — Wizard"), controller="p2")
    eng.rules.deal_damage(target, amount, source=source, combat=combat)
    eng.resolve_until_stable()


def test_the_rider_row_parses_each_shape():
    from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs

    [spec] = replacement_clause_specs(
        "if noncombat damage would be dealt to ~, prevent that damage. put a +1/+1 counter on ~ for each 1 damage "
        "prevented this way.")
    assert spec.type == "prevent_damage"
    assert spec.params["rider"] == {"kind": "add_scaled_counters", "on": "self", "counter": "+1/+1"}
    assert spec.params["source_filter"] == {"combat": False}
    [spec] = replacement_clause_specs(
        "if damage would be dealt to another creature you control, prevent that damage. put a +1/+1 counter on that "
        "creature for each 1 damage prevented this way.")
    assert spec.params["rider"]["on"] == "recipient"
    assert spec.params["recipient_filter"] == {"card_type": "creature", "exclude_self": True}
    # "that creature" under a shield for the source itself would name nothing: stays unclaimed
    assert replacement_clause_specs(
        "if damage would be dealt to ~, prevent that damage. put a +1/+1 counter on that creature for each 1 "
        "damage prevented this way.") is None


def test_self_shield_turns_every_prevented_point_into_a_counter():
    eng = _engine()
    hydra = _bf(eng, _card("Hydra", "Creature — Hydra", HYDRA))
    _hit(eng, hydra, 3)
    assert hydra.damage_marked == 0 and hydra.counters.get("-1/-1") == 3


def test_noncombat_only_shield_leaves_combat_damage_alone():
    eng = _engine()
    capridor = _bf(eng, _card("Capridor", "Creature — Beast", CAPRIDOR))
    _hit(eng, capridor, 2)  # noncombat: prevented, +2 counters
    assert capridor.plus_one_counters == 2 and capridor.damage_marked == 0
    _hit(eng, capridor, 1, combat=True)  # combat: goes through
    assert capridor.plus_one_counters == 2 and capridor.damage_marked == 1


def test_purity_gains_life_equal_to_the_damage_prevented():
    eng = _engine()
    _bf(eng, _card("Purity", "Creature — Elemental", PURITY))
    me = eng.state.player_by_id("p1")
    life = me.life
    eng.rules.deal_damage(me, 4, source=_bf(eng, _card("Zapper", "Creature — Wizard"), controller="p2"), combat=False)
    assert me.life == life + 4  # prevented (no loss) and gained 4
    eng.rules.deal_damage(me, 3, source=_bf(eng, _card("Biter", "Creature — Wolf"), controller="p2"), combat=True)
    assert me.life == life + 4 - 3  # combat damage is not Purity's


def test_vigor_puts_the_counters_on_the_creature_that_would_have_been_hit():
    eng = _engine()
    vigor = _bf(eng, _card("Vigor", "Creature — Elemental", VIGOR))
    ally = _bf(eng, _card("Ally"))
    _hit(eng, ally, 3)
    assert ally.plus_one_counters == 3 and ally.damage_marked == 0
    _hit(eng, vigor, 2)  # "another creature": Vigor itself is not shielded, and a 2/2 dies to 2 damage
    assert vigor.zone == Zone.GRAVEYARD and vigor.plus_one_counters == 0


# --- corpse-counter reanimation: "if that creature would leave the battlefield, exile it instead" -----

CATACOMBS = (
    "Put target creature card from a graveyard onto the battlefield under your control with a corpse counter on "
    "it. You take the initiative. If that creature would leave the battlefield, exile it instead of putting it "
    "anywhere else."
)


def test_corpse_reanimation_parses_through_an_interstitial_designation():
    specs = parse_effect_body(CATACOMBS.lower())
    assert [s.type for s in specs] == ["return_from_graveyard", "take_initiative", "exile_instead_of_leaving"]
    assert specs[0].params["extra_counters"] == {"kind": "corpse", "count": 1}


def test_isareth_reflexive_x_reanimation_is_modeled():
    card = _card("Isareth", "Legendary Creature — Vampire", (
        "Deathtouch\nWhenever ~ attacks, you may pay {X}. When you do, return target creature card with mana value X "
        "from your graveyard to the battlefield with a corpse counter on it. If that creature would leave the "
        "battlefield, exile it instead of putting it anywhere else."))
    assert parse_oracle(card).modeled


def test_reanimated_creature_gets_a_corpse_counter_and_is_exiled_instead_of_dying():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    dead = GameObject(_card("Dead", "Creature — Bear"), owner_id="p2", zone=Zone.GRAVEYARD)
    eng.state.player_by_id("p2").graveyard.append(dead)
    spell = GameObject(_card("Catacombs", "Instant", CATACOMBS, converted_mana_cost=0, is_instant=True), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(p1, spell, targets=[dead])
    eng.resolve_until_stable()
    assert dead in eng.state.battlefield and dead.controller_id == "p1"
    assert dead.counters.get("corpse") == 1
    eng.rules.put_into_graveyard(dead)
    assert dead.zone == Zone.EXILE and dead not in p1.graveyard  # exiled, not put anywhere else


def test_exact_mana_value_x_offers_only_the_matching_card():
    from mtg_analyzer.game.effects.registry import EffectRegistry
    from mtg_analyzer.game.targeting import legal_targets

    two = GameObject(_card("Two", "Creature — Bear", converted_mana_cost=2), owner_id="p1", zone=Zone.GRAVEYARD)
    three = GameObject(_card("Three", "Creature — Bear", converted_mana_cost=3), owner_id="p1", zone=Zone.GRAVEYARD)
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p1.graveyard.extend([two, three])
    effect = EffectRegistry.create("return_from_graveyard", {"target_kind": "graveyard_creature", "exact_mana_value": 2})
    offered = legal_targets(eng.state, "p1", effect.target_spec)
    assert [o["name"] for o in offered] == ["Two"]


def test_pay_x_then_reanimate_exactly_mana_value_x_end_to_end():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for name, mv in (("Two", 2), ("Three", 3)):
        p1.graveyard.append(GameObject(_card(name, "Creature — Bear", converted_mana_cost=mv), owner_id="p1",
                                       zone=Zone.GRAVEYARD))
    text = ("You may pay {X}. When you do, return target creature card with mana value X from your graveyard to the "
            "battlefield with a corpse counter on it. If that creature would leave the battlefield, exile it "
            "instead of putting it anywhere else.")
    spell = GameObject(_card("Reflexive", "Instant", text, converted_mana_cost=0, is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"C": 2})
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    eng.rules.resolve_choice("pay_x:2")
    eng.resolve_until_stable()
    offered = [o["label"] for o in eng.state.pending_choice["options"]]
    assert offered == ["Two"]  # the X the payment announced bound the exact-mana-value target
    eng.rules.resolve_choice(eng.state.pending_choice["options"][0]["id"])
    eng.resolve_until_stable()
    two = next(o for o in eng.state.battlefield if o.name == "Two")
    assert two.counters.get("corpse") == 1
    eng.rules.put_into_graveyard(two)
    assert two.zone == Zone.EXILE


# --- madness overrides that read the madness {X} ------------------------------------------------

FLOORBOARDS = (
    "Madness {X}{B}{B}\nCreate three tapped 2/2 black Zombie creature tokens and you gain 3 life. If this spell's "
    "madness cost was paid, instead create X of those tokens and you gain X life."
)


def _madness_card(text, name="Madness Spell"):
    return _card(name, "Sorcery", text, converted_mana_cost=5, mana_cost_string="{3}{B}{B}", keywords=["Madness"],
                 is_sorcery=True)


def test_madness_override_with_x_is_modeled():
    assert parse_oracle(_madness_card(FLOORBOARDS)).modeled


def test_madness_cast_creates_x_tokens_and_a_hard_cast_creates_three():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_madness_card(FLOORBOARDS), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    eng.rules.discard(p1, 1)
    p1.mana_pool.add_many({"B": 2, "C": 4})
    life = p1.life
    eng.cast_spell(p1, spell, x=4, alt_cost=True)
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.name == "Zombie"]) == 4 and p1.life == life + 4

    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_madness_card(FLOORBOARDS), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    p1.mana_pool.add_many({"B": 2, "C": 3})
    life = p1.life
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.name == "Zombie"]) == 3 and p1.life == life + 3


def _welcome(eng, p1):
    from mtg_analyzer.services.card_database import DEFAULT_DB_PATH, CardDatabase

    card = CardDatabase(DEFAULT_DB_PATH).get_card("Welcome to the Fold") if DEFAULT_DB_PATH.exists() else None
    if card is None:
        pytest.skip("Welcome to the Fold not in the local card cache")
    spell = GameObject(card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    return spell


def _toughness_creature(eng, toughness):
    card = _card(f"T{toughness}", "Creature — Bear", toughness=toughness)
    return _bf(eng, card, controller="p2")


def test_welcome_to_the_fold_hard_cast_takes_only_toughness_two_or_less():
    for toughness, stolen in ((2, True), (3, False)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        spell = _welcome(eng, p1)
        target = _toughness_creature(eng, toughness)
        p1.mana_pool.add_many({"U": 2, "C": 2})
        eng.cast_spell(p1, spell, targets=[target])
        eng.resolve_until_stable()
        assert (target.controller_id == "p1") is stolen


def test_welcome_to_the_fold_madness_threshold_is_the_announced_x():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    spell = _welcome(eng, p1)
    target = _toughness_creature(eng, 4)
    eng.rules.discard(p1, 1)
    p1.mana_pool.add_many({"U": 2, "C": 4})
    eng.cast_spell(p1, spell, targets=[target], x=4, alt_cost=True)
    eng.resolve_until_stable()
    assert target.controller_id == "p1"


# --- more prevention shapes: counter-gated self shields, mill/exile riders, a creature's combat damage ---

KNIGHT = ("If damage would be dealt to this creature while it has a +1/+1 counter on it, prevent that damage and "
          "remove a +1/+1 counter from it.")
CONJURANT = ("If damage would be dealt to this creature while it has a +1/+1 counter on it, prevent that damage and "
             "remove that many +1/+1 counters from it.")
ANGEL = "If damage would be dealt to you, prevent that damage and mill twice that many cards."
GLOOM = ("If combat damage would be dealt to this creature, prevent that damage and exile that many cards from the "
         "top of your library.")
IRONSCALE = "If a creature would deal combat damage to this creature, prevent that damage and put a +1/+1 counter on this creature."


@pytest.mark.parametrize("name, text", [
    ("Knight", KNIGHT), ("Conjurant", CONJURANT), ("Angel", ANGEL), ("Gloom", GLOOM), ("Ironscale", IRONSCALE),
])
def test_prevention_shapes_are_modeled(name, text):
    assert parse_oracle(_card(name, "Creature — Knight", text)).modeled


def test_counter_gated_shield_only_exists_while_the_permanent_holds_a_counter():
    eng = _engine()
    knight = _bf(eng, _card("Knight", "Creature — Knight", KNIGHT, power=3, toughness=3))
    eng.rules.add_counters(knight, 2, "+1/+1")
    _hit(eng, knight, 4)  # shielded: one counter paid, no damage
    assert knight.plus_one_counters == 1 and knight.damage_marked == 0
    _hit(eng, knight, 2)
    assert knight.plus_one_counters == 0 and knight.damage_marked == 0
    _hit(eng, knight, 2)  # no counter left: the shield is gone and the damage lands
    assert knight.damage_marked == 2


def test_that_many_counters_are_removed_but_never_more_than_it_holds():
    eng = _engine()
    conj = _bf(eng, _card("Conjurant", "Creature — Construct", CONJURANT, power=3, toughness=3))
    eng.rules.add_counters(conj, 2, "+1/+1")
    _hit(eng, conj, 5)  # prevents 5, removes the 2 it has (not -3)
    assert conj.plus_one_counters == 0 and conj.damage_marked == 0


def test_mill_twice_that_many_and_exile_that_many():
    eng = _engine()
    me = eng.state.player_by_id("p1")
    for i in range(12):
        me.library.append(GameObject(_card(f"L{i}", "Sorcery"), owner_id="p1", zone=Zone.LIBRARY))
    _bf(eng, _card("Angel", "Creature — Angel", ANGEL))
    eng.rules.deal_damage(me, 3, source=_bf(eng, _card("Z", "Creature — Wizard"), controller="p2"), combat=False)
    assert len(me.library) == 12 - 6 and len(me.graveyard) == 6  # milled twice the 3 prevented

    eng = _engine()
    me = eng.state.player_by_id("p1")
    for i in range(6):
        me.library.append(GameObject(_card(f"L{i}", "Sorcery"), owner_id="p1", zone=Zone.LIBRARY))
    surgeon = _bf(eng, _card("Gloom", "Creature — Horror", GLOOM, power=2, toughness=5))
    _hit(eng, surgeon, 2, combat=True)
    assert len(me.library) == 4 and len(me.exile) == 2 and surgeon.damage_marked == 0
    _hit(eng, surgeon, 1, combat=False)  # noncombat is not covered
    assert surgeon.damage_marked == 1


def test_ironscale_only_shields_creature_combat_damage():
    eng = _engine()
    hydra = _bf(eng, _card("Ironscale", "Creature — Hydra", IRONSCALE, power=2, toughness=5))
    _hit(eng, hydra, 3, combat=True)  # the helper's source is a creature
    assert hydra.plus_one_counters == 1 and hydra.damage_marked == 0  # one counter, however much was prevented
    _hit(eng, hydra, 1, combat=False)
    assert hydra.damage_marked == 1


# --- one-shot shields with a rider keyed on the prevented amount -------------------------------

def _cast_shield(eng, text, targets, x=0, mana=None):
    p1 = eng.state.player_by_id("p1")
    spell = GameObject(_card("Shield Spell", "Instant", text, converted_mana_cost=0, is_instant=True),
                       owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.add_to_zone(spell, Zone.HAND)
    if mana:
        p1.mana_pool.add_many(mana)
    eng.cast_spell(p1, spell, targets=targets, x=x)
    eng.resolve_until_stable()


def test_test_of_faith_counts_only_what_the_shield_actually_prevented():
    eng = _engine()
    bear = _bf(eng, _card("Bear", "Creature — Bear", toughness=5))
    _cast_shield(eng, "Prevent the next 3 damage that would be dealt to target creature this turn. For each 1 "
                      "damage prevented this way, put a +1/+1 counter on that creature.", [bear])
    _hit(eng, bear, 2)  # 2 of the 3 prevented
    assert bear.plus_one_counters == 2 and bear.damage_marked == 0
    _hit(eng, bear, 4)  # only the last 1 of the shield is left; 3 land
    assert bear.plus_one_counters == 3 and bear.damage_marked == 3


def test_temper_reads_the_announced_x_and_candles_glow_gains_life():
    eng = _engine()
    bear = _bf(eng, _card("Bear", "Creature — Bear", toughness=9))
    _cast_shield(eng, "Prevent the next X damage that would be dealt to target creature this turn. For each 1 "
                      "damage prevented this way, put a +1/+1 counter on that creature.", [bear], x=4)
    _hit(eng, bear, 6)
    assert bear.plus_one_counters == 4 and bear.damage_marked == 2

    eng = _engine()
    me = eng.state.player_by_id("p1")
    life = me.life
    _cast_shield(eng, "Prevent the next 3 damage that would be dealt to any target this turn. You gain life equal "
                      "to the damage prevented this way.", [me])
    eng.rules.deal_damage(me, 2, source=_bf(eng, _card("Z", "Creature — Wizard"), controller="p2"), combat=False)
    assert me.life == life + 2  # nothing lost, 2 prevented -> 2 gained


def test_phyrexian_vindicator_reflects_the_prevented_damage_through_a_fresh_trigger():
    text = ("If damage would be dealt to this creature, prevent that damage. When damage is prevented this way, "
            "this creature deals that much damage to any other target.")
    assert parse_oracle(_card("Vindicator", "Creature — Phyrexian", text)).modeled
    eng = _engine()
    vind = _bf(eng, _card("Vindicator", "Creature — Phyrexian", text, toughness=4))
    _hit(eng, vind, 3)
    assert vind.damage_marked == 0
    assert eng.state.pending_choice is not None and eng.state.pending_choice["kind"] == "trigger_target"
    eng.rules.resolve_choice("p2")
    eng.resolve_until_stable()
    assert eng.state.player_by_id("p2").life == 20 - 3
