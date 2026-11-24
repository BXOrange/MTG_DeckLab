from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.deck_batch import activate, card, cast, filler, game


def test_reinforce_discards_from_hand_to_put_counters_on_an_opponents_creature():
    eng = game()
    player = eng.state.players[0]
    reinforce = card(eng, "Burrenton Bombardier", zone=Zone.HAND)
    creature = filler(eng, "Target", player="p2", power=2, toughness=2)
    assert parse_oracle(reinforce.card).modeled
    player.mana_pool.add("W", 3)
    activate(eng, reinforce, targets=[creature])
    assert reinforce.zone == Zone.GRAVEYARD
    assert creature.counters["+1/+1"] == 2


def test_umbra_armor_replaces_destruction_that_cannot_be_regenerated():
    eng = game()
    creature = filler(eng, "Enchanted", power=2, toughness=2)
    aura = card(eng, "Spider Umbra", zone=Zone.HAND)
    assert parse_oracle(aura.card).modeled
    cast(eng, aura, targets=[creature])
    assert aura.attached_to == creature.instance_id
    creature.damage_marked = 1
    eng.rules.destroy(creature, can_be_regenerated=False)
    assert aura.zone == Zone.GRAVEYARD
    assert creature.zone == Zone.BATTLEFIELD and creature.damage_marked == 0


def test_umbra_armor_and_shield_offer_the_affected_player_a_choice():
    eng = game()
    creature = filler(eng, "Enchanted", player="p2", power=2, toughness=2)
    aura = card(eng, "Spider Umbra", zone=Zone.HAND)
    cast(eng, aura, targets=[creature])
    creature.counters["shield"] = 1
    eng.rules.destroy(creature)
    choice = eng.state.pending_choice
    assert choice["kind"] == "replacement_order" and choice["player_id"] == "p2"
    option = next(o for o in choice["options"] if "Umbra armor" in o["label"])
    eng.resolve_pending_choice(option["id"])
    assert aura.zone == Zone.GRAVEYARD and creature.zone == Zone.BATTLEFIELD
    assert creature.counters["shield"] == 1


def test_recover_can_return_the_spell_or_exile_it_for_nonpayment():
    eng = game()
    player = eng.state.players[0]
    spell = card(eng, "Grim Harvest", zone=Zone.GRAVEYARD)
    assert parse_oracle(spell.card).modeled
    victim = filler(eng, "First victim", power=2, toughness=2)
    player.mana_pool.add("B", 3)
    eng.rules.destroy(victim)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    assert spell.zone == Zone.HAND
    eng.rules.discard_specific(spell)
    eng.rules.destroy(filler(eng, "Second victim", power=2, toughness=2))
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE


def test_aftermath_back_half_is_only_castable_from_graveyard_and_exiles_if_countered():
    from tests.support.deck_batch import main_phase

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Dusk // Dawn", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("W", 5)
    assert not eng.can_cast(player, spell, face="back")
    eng.rules.discard_specific(spell)
    assert not eng.can_cast(player, spell)
    actions = [a for a in eng.legal_actions(player) if a.get("instance_id") == spell.instance_id]
    assert any(a.get("cast_from_graveyard") == "aftermath" and a.get("face") == "back" for a in actions)
    item = eng.cast_spell(player, spell, face="back")
    assert spell.name == "Dawn"
    eng.rules.counter_spell(item)
    assert spell.zone == Zone.EXILE and spell.card.back_name == "Dawn"


def test_disturb_casts_back_face_from_graveyard_and_exiles_it_if_destroyed():
    from tests.support.deck_batch import main_phase

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Baithook Angler", zone=Zone.GRAVEYARD)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 2)
    assert not eng.can_cast(player, spell)
    assert any(a.get("face") == "disturb" for a in eng.legal_actions(player)
               if a.get("instance_id") == spell.instance_id)
    eng.cast_spell(player, spell, face="disturb")
    assert spell.name == "Hook-Haunt Drifter" and spell.transformed
    eng.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and spell.transformed
    eng.rules.destroy(spell)
    assert spell.zone == Zone.EXILE and spell.card.back_name == "Hook-Haunt Drifter" and not spell.transformed


def test_craft_can_pay_with_a_graveyard_card_and_returns_the_source_transformed():
    from mtg_analyzer.game.linked_exile import linked_cards
    from tests.support.deck_batch import main_phase

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    source = card(eng, "Tithing Blade")
    material = filler(eng, "Material", power=2, toughness=2, zone=Zone.GRAVEYARD)
    assert parse_oracle(source.card).modeled
    player.mana_pool.add("B", 5)
    craft_index = next(i for i, ability in enumerate(source.activated_abilities) if ability.keyword_label == "craft")
    eng.activate_ability(player, source, craft_index)
    assert eng.state.pending_choice["kind"] == "craft_materials"
    eng.resolve_pending_choice(str(material.instance_id))
    eng.resolve_pending_choice("done")
    assert source.zone == material.zone == Zone.EXILE
    eng.resolve_until_stable()
    assert source.zone == Zone.BATTLEFIELD and source.name == "Consuming Sepulcher"
    assert linked_cards(eng.state, source) == [material]
