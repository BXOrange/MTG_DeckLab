"""Execute printed and granted keyword abilities and reveal costs."""
import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from tests.test_par290_restrictions import _bear, _cast_real, _engine, _hand_real, _named, _put, _real


@pytest.mark.parametrize("name", [
    "Afterlife Insurance", "Arcbound Overseer", "Arcus Acolyte", "Blaster, Combat DJ // Blaster, Morale Booster",
    "Calamity of the Titans", "Cayth, Famed Mechanist", "Disaster Radius", "Enduring Sliver",
    "Frenzy Sliver", "Graywater's Fixer", "Hish of the Snake Cult", "Homing Sliver", "Indebted Spirit",
    "Induce Despair", "Niv-Mizzet, Supreme", "Satoru Umezawa", "Sliver Gravemother", "Snake Cult Initiation",
    "Varolz, the Scar-Striped", "Virulent Sliver", "Wire Surgeons", "Young Deathclaws",
])
def test_cards_are_fully_parsed(name):
    parsed = parse_oracle(_named(name))
    assert parsed.modeled, parsed.unclaimed


def test_reveal_cost_uses_the_selected_creatures_mana_value_and_publishes_it():
    eng = _engine()
    spell = _hand_real(eng, "Induce Despair")
    cheap = _hand_real(eng, "Llanowar Elves")
    chosen = _hand_real(eng, "Colossal Dreadmaw")
    target = _put(eng, _bear("Defender", power=8, toughness=8), "p2")
    eng.state.current_step = "main1"
    player = eng.state.active_player
    with pytest.raises(ValueError, match="Choose one eligible"):
        eng.cast_spell(player, spell, targets=[target], hand_card_choices=[spell.instance_id])
    assert spell in player.hand
    eng.cast_spell(player, spell, targets=[target], hand_card_choices=[chosen.instance_id])
    assert chosen in player.hand and cheap in player.hand
    assert any(e.type == EventType.REVEAL and e.get("instance_id") == chosen.instance_id for e in eng.state.event_log)
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert target.toughness == 2


def test_calamity_uses_strict_colorless_creature_threshold():
    eng = _engine()
    spell = _hand_real(eng, "Calamity of the Titans")
    eng.state.active_player.mana_pool.add("C", 2)
    colored = _hand_real(eng, "Llanowar Elves")
    revealed = _hand_real(eng, "Solemn Simulacrum")
    low, same = _real(eng, "Llanowar Elves", "p2"), _real(eng, "Solemn Simulacrum", "p2")
    eng.state.current_step = "main1"
    player = eng.state.active_player
    with pytest.raises(ValueError, match="Choose one eligible"):
        eng.cast_spell(player, spell, hand_card_choices=[colored.instance_id])
    eng.cast_spell(player, spell, hand_card_choices=[revealed.instance_id])
    eng.resolve_until_stable()
    assert low.zone == Zone.EXILE and same.zone == Zone.BATTLEFIELD


def test_printed_and_granted_fabricate_offer_each_choice():
    eng = _engine()
    cayth = _cast_real(eng, "Cayth, Famed Mechanist")
    assert eng.state.pending_choice["kind"] == "fabricate_choice"
    eng.resolve_pending_choice("counters")
    assert cayth.plus_one_counters == 1
    entrant = _cast_real(eng, "Llanowar Elves")
    assert eng.state.pending_choice["kind"] == "fabricate_choice"
    eng.resolve_pending_choice("servos")
    assert entrant.plus_one_counters == 0
    tokens = [obj for obj in eng.state.permanents() if obj.is_token]
    assert len(tokens) == 1 and tokens[0].name == "Servo" and tokens[0].is_artifact


def test_afterlife_death_uses_last_controller_and_creates_flying_spirits():
    eng = _engine()
    creature = _real(eng, "Orzhov Enforcer", "p2")
    eng.rules.put_into_graveyard(creature)
    eng.resolve_until_stable()
    spirit, = eng.state.permanents()
    assert spirit.name == "Spirit" and spirit.controller_id == "p2"
    assert spirit.colors == {"W", "B"} and combat.has(spirit, "flying")


def test_modular_uses_death_counter_snapshot_including_extra_counters():
    eng = _engine()
    worker = _cast_real(eng, "Arcbound Worker")
    host = _real(eng, "Solemn Simulacrum")
    assert worker.plus_one_counters == 1
    eng.rules.add_counters(worker, 2, "+1/+1")
    eng.rules.put_into_graveyard(worker)
    eng.resolve_until_stable()
    if eng.state.pending_choice["kind"] != "modular_choice":
        eng.resolve_pending_choice(str(host.instance_id))
    assert eng.state.pending_choice["kind"] == "modular_choice"
    eng.resolve_pending_choice("counters")
    assert host.plus_one_counters == 3


def test_granted_frenzy_and_poisonous_are_separate_triggers():
    eng = _engine()
    attacker = _real(eng, "Frenzy Sliver")
    _real(eng, "Virulent Sliver")
    attacker.attacking = True
    eng._fire_unblocked_events()
    eng.resolve_until_stable()
    eng.recompute_continuous_effects()
    assert attacker.power == 2
    eng.state.fire_event(GameEvent(EventType.DAMAGE, source_id=attacker.instance_id, combat=True,
                                  is_player=True, target_id="p2", amount=2))
    eng.resolve_until_stable()
    assert eng.state.players[1].poison == 1


@pytest.mark.parametrize("granted", [False, True])
def test_jump_start_pays_chosen_discard_and_exiles_the_spell(granted):
    eng = _engine()
    if granted:
        _real(eng, "Niv-Mizzet, Supreme")
    spell = _hand_real(eng, "Electrolyze" if granted else "Radical Idea")
    draw = _hand_real(eng, "Island")
    keep = _hand_real(eng, "Forest")
    discard = _hand_real(eng, "Plains")
    player = eng.state.active_player
    player.remove_from_zone(spell, Zone.HAND)
    player.add_to_zone(spell, Zone.GRAVEYARD)
    player.remove_from_zone(draw, Zone.HAND)
    player.add_to_zone(draw, Zone.LIBRARY)
    eng.state.current_step = "main1"
    assert eng._graveyard_cast_keyword(spell) == "jump_start"
    eng.cast_spell(player, spell, targets=[eng.state.players[1]] if granted else None,
                   discard_choices=[discard.instance_id])
    assert discard in player.graveyard and keep in player.hand
    eng.resolve_until_stable()
    assert spell in player.exile


def test_encore_assigns_one_hasty_token_to_each_opponent_and_expires():
    eng = _engine(3)
    source = _hand_real(eng, "Sliver Gravemother")
    player = eng.state.active_player
    player.remove_from_zone(source, Zone.HAND)
    player.add_to_zone(source, Zone.GRAVEYARD)
    eng.state.current_step = "main1"
    eng.activate_ability(player, source)
    assert source in player.exile
    eng.resolve_until_stable()
    copies = [obj for obj in eng.state.permanents() if obj.is_token]
    assert {obj.encore_defender_id for obj in copies} == {"p2", "p3"}
    assert len(copies) == 2 and all(combat.has(obj, "haste") for obj in copies)
    eng._fire_delayed_triggers("end")
    eng.resolve_until_stable()
    assert not eng.state.permanents()


def test_granted_typecycling_searches_the_activators_library_not_the_granters():
    eng = _engine()
    _real(eng, "Homing Sliver")
    cyclist = _hand_real(eng, "Virulent Sliver", "p2")
    hit = _hand_real(eng, "Frenzy Sliver", "p2")
    player = eng.state.players[1]
    player.remove_from_zone(hit, Zone.HAND)
    player.add_to_zone(hit, Zone.LIBRARY)
    eng.recompute_continuous_effects()
    eng.activate_ability(player, cyclist)
    assert cyclist in player.graveyard
    eng.resolve_until_stable()
    if eng.state.pending_choice:
        eng.resolve_pending_choice(str(hit.instance_id))
    assert hit in player.hand


def test_granted_outlast_uses_the_printed_activation_and_expires_when_filtered_out():
    eng = _engine()
    _real(eng, "Arcus Acolyte")
    creature = _real(eng, "Llanowar Elves")
    player = eng.state.active_player
    player.mana_pool.add("G", 1)
    eng.state.current_step = "main1"
    ability, = creature._granted_activated_abilities
    assert ability.cost.ability_keyword == "outlast" and ability.cost.sorcery_speed_only
    eng.activate_ability(player, creature)
    eng.resolve_until_stable()
    assert creature.tapped and creature.plus_one_counters == 1
    eng.recompute_continuous_effects()
    assert not creature._granted_activated_abilities


def test_granted_scavenge_exiles_as_cost_and_adds_counters_on_resolution():
    eng = _engine()
    _real(eng, "Varolz, the Scar-Striped")
    source = _hand_real(eng, "Colossal Dreadmaw")
    host = _real(eng, "Llanowar Elves")
    player = eng.state.active_player
    player.remove_from_zone(source, Zone.HAND)
    player.add_to_zone(source, Zone.GRAVEYARD)
    eng.state.current_step = "main1"
    eng.recompute_continuous_effects()
    eng.activate_ability(player, source, targets=[host])
    assert source.zone == Zone.EXILE and host.plus_one_counters == 0
    eng.resolve_until_stable()
    assert host.plus_one_counters == 6
