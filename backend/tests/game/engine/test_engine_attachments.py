"""Tests for the rules engine + game engine.

Reference: docs/requirements/02_MVP_USECASES_REVISED.md R2.*/R4.*,
docs/concepts/07_GAME_LOOP_EFFECT_SYSTEM.md, mtg_analyzer/game/.
"""


from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.game.binding.core import bind_from_catalogue


from engine_test_helpers import land, creature, make_engine, obj_on_battlefield


def test_enchant_creature_oracle_text_follows_aura_logic():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura_card = Card(
        id="AuraText",
        name="AuraText",
        type_line="Enchantment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
        oracle_text="Enchant creature",
    )
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(aura, Zone.HAND)
    bind_from_catalogue(aura)

    eng.cast_spell(p1, aura, targets=[host])
    eng.resolve_until_stable()

    assert aura.attached_to == host.instance_id
    assert aura in eng.state.battlefield


def test_enchant_creature_recognised_even_with_other_scryfall_keywords():
    # Scryfall's keywords array can list other keywords (e.g. Flash) while
    # omitting "Enchant" itself — oracle text must still be cross-checked.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura_card = Card(
        id="AuraFlash",
        name="AuraFlash",
        type_line="Enchantment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
        oracle_text="Flash\nEnchant creature",
        keywords=["Flash"],
    )
    aura = GameObject(aura_card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(aura, Zone.HAND)
    bind_from_catalogue(aura)

    eng.cast_spell(p1, aura, targets=[host])
    eng.resolve_until_stable()

    assert aura.attached_to == host.instance_id
    assert aura in eng.state.battlefield


def test_equipment_ability_only_offers_legal_attachment_targets():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    illegal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    options = requirements[0]["options"]
    option_ids = {opt["instance_id"] for opt in options}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids


def test_equipment_spell_enters_the_battlefield_instead_of_the_graveyard():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player
    p1.mana_pool.add_many({"W": 1, "C": 1})

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}{W}",
        converted_mana_cost=2,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    equipment = GameObject(card, owner_id="p1", zone=Zone.HAND)
    p1.add_to_zone(equipment, Zone.HAND)
    bind_from_catalogue(equipment)

    eng.cast_spell(p1, equipment)
    eng.resolve_until_stable()

    assert equipment in eng.state.battlefield
    assert equipment not in p1.graveyard


def test_attached_aura_moves_to_graveyard_when_host_leaves_the_battlefield():
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    aura = GameObject(Card(id="Aura", name="Aura", type_line="Enchantment"), owner_id="p1")
    aura.parametric_keywords = {"enchant": {"quality": "creature"}}
    eng.state.add_to_battlefield(aura)
    eng.rules.attach_to_target(aura, host)

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert aura in p1.graveyard


def test_attached_equipment_stays_on_battlefield_unattached_when_host_leaves():
    # RULE 704.5n: unlike an Aura (704.5m), an Equipment left attached to
    # nothing just becomes unattached — it doesn't go to the graveyard.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    equipment = GameObject(
        Card(id="Equipment", name="Equipment", type_line="Artifact — Equipment"),
        owner_id="p1",
    )
    equipment.parametric_keywords = {"equip": {}}
    eng.state.add_to_battlefield(equipment)
    eng.rules.attach_to_target(equipment, host)

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert equipment in eng.state.battlefield
    assert equipment not in p1.graveyard
    assert equipment.attached_to is None


def test_equip_only_offers_and_attaches_creatures_you_control():
    """RULE 301.5b/702.6a: "target creature you control" — not an opponent's.

    Control matters both when the ability is activated (offer time) and
    when it resolves (`_attachment_legal`), so both are checked here.
    """
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_creature = obj_on_battlefield(eng.state, eng, creature(name="Own"), controller="p1")
    opponents_creature = obj_on_battlefield(
        eng.state, eng, creature(name="Theirs"), controller="p2"
    )

    card = Card(
        id="Equipment",
        name="Equipment",
        type_line="Artifact — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Equip"]
    card.oracle_text = "Equip {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_creature.instance_id in option_ids
    assert opponents_creature.instance_id not in option_ids

    assert eng.rules.attach_to_target(source, own_creature)
    source.attached_to = None
    assert not eng.rules._attachment_legal(source, opponents_creature)


def test_reconfigure_only_offers_creatures_you_control():
    """RULE 702.151a: "another target creature you control" — same restriction."""
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_creature = obj_on_battlefield(eng.state, eng, creature(name="Own"), controller="p1")
    opponents_creature = obj_on_battlefield(
        eng.state, eng, creature(name="Theirs"), controller="p2"
    )

    card = Card(
        id="Reconfigurable",
        name="Reconfigurable",
        type_line="Artifact Creature — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
    )
    card.keywords = ["Reconfigure"]
    card.oracle_text = "Reconfigure {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_creature.instance_id in option_ids
    assert opponents_creature.instance_id not in option_ids


def test_fortify_only_offers_lands_you_control():
    """RULE 702.67a: "target land you control" — same restriction."""
    eng = make_engine([land()], [land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    own_land = obj_on_battlefield(
        eng.state, eng, land(name="Own Mountain", produces="Mountain"), controller="p1"
    )
    opponents_land = obj_on_battlefield(
        eng.state, eng, land(name="Their Mountain", produces="Mountain"), controller="p2"
    )

    card = Card(
        id="Fortification",
        name="Fortification",
        type_line="Artifact — Fortification",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Fortify"]
    card.oracle_text = "Fortify {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}
    assert own_land.instance_id in option_ids
    assert opponents_land.instance_id not in option_ids


def test_reconfigure_ability_only_offers_creature_attachment_targets():
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))
    illegal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))

    card = Card(
        id="Reconfigurable",
        name="Reconfigurable",
        type_line="Artifact Creature — Equipment",
        mana_cost_string="{1}",
        converted_mana_cost=1,
        is_creature=True,
        power=1,
        toughness=1,
    )
    card.keywords = ["Reconfigure"]
    card.oracle_text = "Reconfigure {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids


def test_fortify_ability_only_offers_land_attachment_targets():
    # RULE 702.151b/301.5c: Fortify attaches to a land, not a creature —
    # unlike Equip/Reconfigure above, offering (and resolving) it against
    # any permanent was a real gap until targeting.py/_attachment_legal
    # gained an explicit "fortify" case.
    eng = make_engine([land()], hand=0)
    eng.begin_turn()
    p1 = eng.state.active_player

    legal_host = obj_on_battlefield(eng.state, eng, land(name="Mountain", produces="Mountain"))
    illegal_host = obj_on_battlefield(eng.state, eng, creature(name="Host", cost="{1}"))

    card = Card(
        id="Fortification",
        name="Fortification",
        type_line="Artifact — Fortification",
        mana_cost_string="{1}",
        converted_mana_cost=1,
    )
    card.keywords = ["Fortify"]
    card.oracle_text = "Fortify {2}"
    source = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    source.summoning_sick = False
    eng.state.add_to_battlefield(source)
    bind_from_catalogue(source)

    requirements = eng._ability_target_requirements(p1, source.activated_abilities[0], source)
    option_ids = {opt["instance_id"] for opt in requirements[0]["options"]}

    assert legal_host.instance_id in option_ids
    assert illegal_host.instance_id not in option_ids

    assert eng.rules.attach_to_target(source, legal_host)
    assert source.attached_to == legal_host.instance_id
    source.attached_to = None
    assert not eng.rules._attachment_legal(source, illegal_host)


def test_reconfigure_permanent_stops_being_a_creature_while_attached():
    # RULE 702.151b: attaching a Reconfigure permanent to another creature
    # turns it into a (non-creature) Equipment until it becomes unattached —
    # including automatically, when its host leaves the battlefield.
    eng = make_engine([], hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    p1 = eng.state.active_player

    host = GameObject(creature(name="Host", cost="{1}"), owner_id="p1", zone=Zone.BATTLEFIELD)
    host.summoning_sick = False
    eng.state.add_to_battlefield(host)

    reconfigurable = GameObject(
        creature(name="Reconfigurable", cost="{1}", power=1, toughness=1),
        owner_id="p1",
    )
    reconfigurable.parametric_keywords = {"reconfigure": {"cost": "{2}"}}
    eng.state.add_to_battlefield(reconfigurable)

    eng.recompute_continuous_effects()
    assert reconfigurable.is_creature

    eng.rules.attach_to_target(reconfigurable, host)
    eng.recompute_continuous_effects()
    assert not reconfigurable.is_creature

    eng.rules.destroy(host)
    eng.resolve_until_stable()

    assert reconfigurable in eng.state.battlefield
    assert reconfigurable.attached_to is None
    assert reconfigurable.is_creature
