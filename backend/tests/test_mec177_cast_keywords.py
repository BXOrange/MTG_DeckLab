from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.support.deck_batch import card, filler, game, main_phase


def test_spectacle_uses_opponents_life_loss_to_offer_the_alternative_cost():
    eng = game()
    main_phase(eng)
    player, opponent = eng.state.players
    spell = card(eng, "Skewer the Critics", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("R", 1)
    eng.rules.lose_life(player, 1)
    assert not eng.can_cast(player, spell, alt_cost=True)
    eng.rules.lose_life(opponent, 1)
    assert eng.can_cast(player, spell, alt_cost=True)
    eng.cast_spell(player, spell, alt_cost=True, targets=[opponent])
    eng.resolve_until_stable()
    assert opponent.life == 16 and spell.zone == Zone.GRAVEYARD


def test_freerunning_uses_combat_damage_source_characteristics_at_the_time_of_damage():
    eng = game()
    main_phase(eng)
    player, opponent = eng.state.players
    spell = card(eng, "Eagle Vision", zone=Zone.HAND)
    assassin = filler(eng, "Assassin", type_line="Creature — Assassin", power=1, toughness=1)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 2)
    eng.rules.deal_damage(opponent, 1, source=assassin)
    assert not eng.can_cast(player, spell, alt_cost=True)
    eng.rules.deal_damage(opponent, 1, source=assassin, combat=True)
    eng.rules.destroy(assassin)
    assert eng.can_cast(player, spell, alt_cost=True)
    eng.cast_spell(player, spell, alt_cost=True)
    eng.resolve_until_stable()
    assert len(player.hand) == 3


def test_prowl_matches_the_spell_creature_type_and_fires_its_paid_enters_trigger():
    eng = game()
    main_phase(eng)
    player, opponent = eng.state.players
    spell = card(eng, "Latchkey Faerie", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    bystander = filler(eng, "Zombie", type_line="Creature — Zombie", power=1, toughness=1)
    rogue = filler(eng, "Rogue", type_line="Creature — Human Rogue", power=1, toughness=1)
    player.mana_pool.add("U", 3)
    eng.rules.deal_damage(opponent, 1, source=bystander, combat=True)
    assert not eng.can_cast(player, spell, alt_cost=True)
    eng.rules.deal_damage(opponent, 1, source=rogue, combat=True)
    eng.cast_spell(player, spell, alt_cost=True)
    eng.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and len(player.hand) == 1


def test_impending_enters_with_time_counters_and_becomes_a_creature_when_the_last_leaves():
    from mtg_analyzer.models.game.events import EventType, GameEvent

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Overlord of the Mistmoors", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("W", 4)
    eng.cast_spell(player, spell, alt_cost=True)
    eng.resolve_until_stable()
    assert spell.zone == Zone.BATTLEFIELD and not spell.is_creature
    assert spell.counters["time"] == 4
    for remaining in (3, 2, 1, 0):
        eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="end"))
        eng.resolve_until_stable()
        assert spell.counters.get("time", 0) == remaining
        assert spell.is_creature == (remaining == 0)


def test_casualty_only_accepts_creatures_meeting_the_power_threshold():
    import pytest

    eng = game()
    main_phase(eng)
    player, opponent = eng.state.players
    spell = card(eng, "Make Disappear", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    token = filler(eng, "Eligible creature", power=1, toughness=1)
    bystander = filler(eng, "Zero power", power=0, toughness=1)
    target = card(eng, "Opt", player="p2", zone=Zone.HAND)
    opponent.mana_pool.add("U", 1)
    eng.cast_spell(opponent, target)
    player.mana_pool.add("U", 2)
    with pytest.raises(ValueError):
        eng.cast_spell(player, spell, targets=[target], pay_additional=True, sacrifice_choices=[bystander.instance_id])
    assert token.zone == bystander.zone == Zone.BATTLEFIELD and spell.zone == Zone.HAND
    eng.cast_spell(player, spell, targets=[target], pay_additional=True, sacrifice_choices=[token.instance_id])
    assert token.zone == Zone.GRAVEYARD and bystander.zone == Zone.BATTLEFIELD
    eng.resolve_until_stable()
    if eng.state.pending_choice and eng.state.pending_choice["kind"] == "copy_targets":
        eng.resolve_pending_choice("keep")
    from mtg_analyzer.models.game.events import EventType

    assert any(event.type == EventType.SPELL_COPIED for event in eng.state.events_this_turn())


def test_transfigure_sacrifices_and_searches_only_for_a_creature_with_its_mana_value():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    permanent = card(eng, "Fleshwrither")
    assert parse_oracle(permanent.card).modeled
    match = filler(eng, "Same value", mv=4, power=2, toughness=2, zone=Zone.LIBRARY)
    miss = filler(eng, "Different value", mv=3, power=2, toughness=2, zone=Zone.LIBRARY)
    player.mana_pool.add("B", 3)
    eng.activate_ability(player, permanent)
    eng.resolve_until_stable()
    assert permanent.zone == Zone.GRAVEYARD
    options = eng.state.pending_choice["options"]
    assert any(o.get("instance_id") == match.instance_id for o in options)
    assert all(o.get("instance_id") != miss.instance_id for o in options)
    eng.resolve_pending_choice(str(match.instance_id))
    assert match.zone == Zone.BATTLEFIELD


def test_squad_can_be_paid_twice_and_creates_two_copies():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Vanguard Suppressor", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 10)
    eng.cast_spell(player, spell, kicked=2)
    eng.resolve_until_stable()
    assert spell.squad_count == 2 and spell.kicker_count == 0
    copies = [obj for obj in eng.state.battlefield if obj.is_token and obj.name == spell.name]
    assert len(copies) == 2


def test_squad_dash_discards_the_chosen_cards_as_a_repeatable_cost():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Thrill-Kill Disciple", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    saved, first, second = [filler(eng, name, zone=Zone.HAND) for name in ("Keep", "First", "Second")]
    player.mana_pool.add("R", 6)
    action = next(a for a in eng.legal_actions(player) if a["type"] == "cast_spell"
                  and a.get("instance_id") == spell.instance_id)
    assert action["max_kicker"] == 3
    assert not eng.can_cast(player, spell, kicked=2, discard_choices=[first.instance_id] * 2)
    eng.cast_spell(player, spell, kicked=2, discard_choices=[first.instance_id, second.instance_id])
    assert first.zone == second.zone == Zone.GRAVEYARD and saved.zone == Zone.HAND
    eng.resolve_until_stable()
    assert sum(obj.is_token and obj.name == spell.name for obj in eng.state.battlefield) == 2


def test_squad_dash_can_exile_eight_distinct_graveyard_cards_for_two_copies():
    import pytest

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Ruthless Radrat", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    materials = [filler(eng, f"Material {i}", zone=Zone.GRAVEYARD) for i in range(9)]
    player.mana_pool.add("B", 3)
    action = next(a for a in eng.legal_actions(player) if a["type"] == "cast_spell"
                  and a.get("instance_id") == spell.instance_id)
    assert action["max_kicker"] == 2
    with pytest.raises(ValueError):
        eng.cast_spell(player, spell, kicked=2, graveyard_exile_choices=[materials[0].instance_id] * 8)
    assert all(obj.zone == Zone.GRAVEYARD for obj in materials)
    eng.cast_spell(player, spell, kicked=2, graveyard_exile_choices=[obj.instance_id for obj in materials[1:]])
    assert materials[0].zone == Zone.GRAVEYARD and all(obj.zone == Zone.EXILE for obj in materials[1:])
    eng.resolve_until_stable()
    assert sum(obj.is_token and obj.name == spell.name for obj in eng.state.battlefield) == 2


def test_web_slinging_only_returns_a_tapped_creature_for_the_alternative_cost():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Amazing Spider-Girl", zone=Zone.HAND)
    returned = filler(eng, "Tapped creature", power=1, toughness=1)
    bystander = filler(eng, "Untapped creature", power=1, toughness=1)
    returned.tapped = True
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("W", 3)
    assert eng.can_cast(player, spell, alt_cost=True)
    eng.cast_spell(player, spell, alt_cost=True, alt_cost_choices=[returned.instance_id])
    eng.resolve_until_stable()
    assert returned.zone == Zone.HAND and bystander.zone == Zone.BATTLEFIELD
    assert spell.zone == Zone.BATTLEFIELD and player.mana_pool.total() == 0


def test_sneak_casts_during_declared_blockers_and_keeps_the_returned_creatures_defender():
    from tests.support.star_trek import advance_to

    eng = game()
    player, opponent = eng.state.players
    spell = card(eng, "Foot Ninjas", zone=Zone.HAND)
    attacker = filler(eng, "Attacker", power=2, toughness=2)
    assert parse_oracle(spell.card).modeled
    advance_to(eng, "declare_attackers")
    eng.declare_attackers(player, [attacker])
    eng.advance_step()
    assert eng.state.current_step == "declare_blockers"
    player.mana_pool.add("W", 4)
    assert not eng.can_cast(player, spell, alt_cost=True)
    eng.declare_blockers(opponent, [])
    defender = dict(attacker.combat_defender)
    eng.cast_spell(player, spell, alt_cost=True, alt_cost_choices=[attacker.instance_id])
    eng.resolve_until_stable()
    assert attacker.zone == Zone.HAND
    assert spell.zone == Zone.BATTLEFIELD and spell.tapped and spell.attacking
    assert spell.combat_defender == defender


def test_prototype_uses_alternative_characteristics_until_it_leaves_the_battlefield():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Blitz Automaton", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("R", 3)
    assert not eng.can_cast(player, spell)
    assert any(a.get("face") == "prototype" for a in eng.legal_actions(player)
               if a.get("instance_id") == spell.instance_id)
    eng.cast_spell(player, spell, face="prototype")
    assert spell.mana_value == 3 and spell.colors == {"R"}
    eng.resolve_until_stable()
    assert (spell.power, spell.toughness) == (3, 2)
    eng.rules.destroy(spell)
    assert spell.zone == Zone.GRAVEYARD and spell.mana_value == 7 and not spell.colors


def test_overload_replaces_targets_with_each_eligible_permanent():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Vandalblast", zone=Zone.HAND)
    own = filler(eng, "Your artifact", type_line="Artifact")
    foes = [filler(eng, f"Opposing artifact {i}", type_line="Artifact", player="p2") for i in range(2)]
    player.mana_pool.add("R", 5)
    offers = [a for a in eng.legal_actions(player) if a.get("instance_id") == spell.instance_id]
    overloaded = next(a for a in offers if a.get("face") == "overload")
    assert not overloaded.get("requires_target") and overloaded["cost_label"] == "{4}{R}"
    eng.cast_spell(player, spell, face="overload")
    assert spell.mana_value == 1
    eng.resolve_until_stable()
    assert own.zone == Zone.BATTLEFIELD and all(obj.zone == Zone.GRAVEYARD for obj in foes)
    assert spell.zone == Zone.GRAVEYARD and "Overload" in spell.card.oracle_text


def test_cipher_exiles_the_card_and_offers_a_copy_on_the_encoded_creatures_combat_damage():
    eng = game()
    main_phase(eng)
    player, opponent = eng.state.players
    spell = card(eng, "Last Thoughts", zone=Zone.HAND)
    creature = filler(eng, "Encode host", power=2, toughness=2)
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 4)
    eng.cast_spell(player, spell)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "cipher_encode"
    eng.resolve_pending_choice(str(creature.instance_id))
    assert spell.zone == Zone.EXILE
    eng.rules.deal_damage(opponent, 2, source=creature, combat=True)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "play_during_resolution"
    copy = next(obj for obj in player.exile if getattr(obj, "is_copy", False))
    eng.play_resolution_card(player, copy)
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE and eng.state.pending_choice is None
    assert len(player.hand) == 2


def test_aura_swap_exchanges_auras_and_attaches_the_incoming_aura_to_the_same_host():
    from tests.support.deck_batch import cast

    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    aura = card(eng, "Arcanum Wings", zone=Zone.HAND)
    other = card(eng, "Spider Umbra", zone=Zone.HAND)
    host = filler(eng, "Enchanted creature", power=2, toughness=2)
    assert parse_oracle(aura.card).modeled
    cast(eng, aura, targets=[host], pool={"U": 2})
    player.mana_pool.add("U", 3)
    eng.activate_ability(player, aura)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "aura_swap"
    eng.resolve_pending_choice(str(other.instance_id))
    assert aura.zone == Zone.HAND and other.zone == Zone.BATTLEFIELD
    assert other.attached_to == host.instance_id


def test_awaken_adds_only_the_paid_casts_land_target_and_animates_that_land():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Clutch of Currents", zone=Zone.HAND)
    enemy = filler(eng, "Enemy creature", player="p2", power=2, toughness=2)
    land = card(eng, "Island")
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 5)
    offers = [a for a in eng.legal_actions(player) if a.get("instance_id") == spell.instance_id]
    assert len(next(a for a in offers if not a.get("alt_cost"))["targets"]) == 1
    assert len(next(a for a in offers if a.get("alt_cost"))["targets"]) == 2
    eng.cast_spell(player, spell, alt_cost=True, target_groups=[[enemy], [land]])
    eng.resolve_until_stable()
    assert enemy.zone == Zone.HAND
    assert land.is_land and land.is_creature and land.has_subtype("elemental")
    assert land.power == land.toughness == 3 and land.counters["+1/+1"] == 3


def test_harmonize_taps_a_chosen_creature_to_reduce_the_generic_cost_and_exiles_the_spell():
    eng = game()
    main_phase(eng)
    player = eng.state.players[0]
    spell = card(eng, "Unending Whisper", zone=Zone.GRAVEYARD)
    creature = filler(eng, "Harmonizer", power=5, toughness=5)
    bystander = filler(eng, "Already tapped", power=8, toughness=8)
    bystander.tapped = True
    assert parse_oracle(spell.card).modeled
    player.mana_pool.add("U", 1)
    eng.cast_spell(player, spell)
    choice = eng.state.pending_choice
    assert choice["kind"] == "harmonize_payment"
    assert str(bystander.instance_id) not in {o["id"] for o in choice["options"]}
    eng.resolve_pending_choice(str(creature.instance_id))
    assert creature.tapped and spell.zone == Zone.STACK
    eng.resolve_until_stable()
    assert spell.zone == Zone.EXILE and len(player.hand) == 1


def test_assist_locks_the_cost_and_allows_another_player_to_pay_only_generic_mana():
    eng = game(players=3)
    main_phase(eng)
    caster, helper, bystander = eng.state.players
    spell = card(eng, "Play of the Game", zone=Zone.HAND)
    assert parse_oracle(spell.card).modeled
    caster.mana_pool.add("W", 2)
    helper.mana_pool.add("C", 7)
    bystander.mana_pool.add("C", 2)
    assert any(a.get("face") == "assist" for a in eng.legal_actions(caster)
               if a.get("instance_id") == spell.instance_id)
    eng.cast_spell(caster, spell, face="assist")
    assert eng.state.pending_choice["kind"] == "assist_select"
    eng.resolve_pending_choice(helper.id)
    assert eng.state.pending_choice["player_id"] == helper.id
    eng.resolve_pending_choice("continue")
    assert eng.state.pending_choice["player_id"] == caster.id
    eng.resolve_pending_choice("continue")
    assert eng.state.pending_choice["player_id"] == helper.id
    assert {o["id"] for o in eng.state.pending_choice["options"]} == {"6", "decline"}
    eng.resolve_pending_choice("6")
    assert spell.zone == Zone.STACK
    assert caster.mana_pool.total() == 0
    assert helper.mana_pool.total() == 1 and bystander.mana_pool.total() == 2


def test_assist_can_pay_the_generic_cost_from_announced_x():
    eng = game(players=3)
    main_phase(eng)
    caster, helper, target = eng.state.players
    spell = card(eng, "Gang Up", zone=Zone.HAND)
    creature = filler(eng, "Threat", player=target.id, type_line="Creature — Bear", power=3, toughness=3)
    caster.mana_pool.add("B", 1)
    helper.mana_pool.add("C", 3)
    action = next(a for a in eng.legal_actions(caster) if a.get("face") == "assist")
    assert (action["min_x"], action["max_x"]) == (1, 3)
    assert not action.get("locked") and action["targets"][0]["options"][0]["minimum_x"] == 3
    eng.cast_spell(caster, spell, face="assist", x=3, targets=[creature])
    for answer in (helper.id, "continue", "continue", "3"):
        eng.resolve_pending_choice(answer)
    assert spell.zone == Zone.STACK and spell.mana_spent_to_cast == 4
    eng.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD
