"""Live engine regressions for the Saga, regeneration and static mechanics."""

import pytest

from mtg_analyzer.game import combat
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.game_session import GameSession


def _game():
    engine = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_hand=0)
    engine.begin_turn()
    engine.state.current_step = "main1"
    return engine, *engine.state.players


def _object(engine, player, name, type_line, text="", *, zone=Zone.BATTLEFIELD, **kwargs):
    card = Card(id=name, name=name, type_line=type_line, oracle_text=text, **kwargs)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    obj = GameObject(card, player.id, zone)
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
    else:
        player.add_to_zone(obj, zone)
    return obj


def test_final_chapter_firing_and_resolution_have_distinct_windows():
    engine, player, opponent = _game()
    _object(engine, player, "Chapter Observer", "Enchantment",
            "Whenever the final chapter ability of a Saga you control triggers, you gain 2 life.\n"
            "Whenever the final chapter ability of a Saga you control resolves, you gain 3 life.")
    saga = _object(engine, player, "Two Chapters", "Enchantment — Saga",
                   "I — You gain 1 life.\nII — You gain 4 life.")
    life = player.life
    engine.resolve_until_stable()
    assert player.life == life + 1
    engine.rules.add_counters(saga, 1, "lore")
    assert any(e.type == EventType.SAGA_FINAL_CHAPTER_TRIGGERED for e in engine.state.event_log)
    assert not any(e.type == EventType.SAGA_FINAL_CHAPTER_RESOLVED for e in engine.state.event_log)
    engine.resolve_until_stable()
    assert player.life == life + 10
    assert saga in player.graveyard
    other = _object(engine, opponent, "Opponent Saga", "Enchantment — Saga", "I — You gain 1 life.")
    engine.resolve_until_stable()
    assert player.life == life + 10
    assert other in opponent.graveyard


def test_narci_measures_the_original_saga_after_it_leaves():
    engine, player, opponent = _game()
    _object(engine, player, "Narci, Fable Singer", "Creature — Human Bard",
            "Whenever the final chapter ability of a Saga you control resolves, "
            "each opponent loses X life and you gain X life, where X is that Saga's mana value.",
            is_creature=True, power=3, toughness=3)
    saga = _object(engine, player, "Saga With Cost", "Enchantment — Saga",
                   "I — You gain 1 life.", mana_cost_string="{3}", converted_mana_cost=3)
    engine.rules.exile(saga)
    life, other_life = player.life, opponent.life
    engine.resolve_until_stable()
    assert player.life == life + 4
    assert opponent.life == other_life - 3


@pytest.mark.parametrize("text,reveal_both", [
    ("Players play with their hands revealed.", True),
    ("Your opponents play with their hands revealed.", False),
])
def test_hand_reveal_is_live_and_scoped_for_opponents_and_observers(text, reveal_both):
    engine, player, opponent = _game()
    source = _object(engine, player, "Hand Revelation", "Enchantment", text)
    mine = _object(engine, player, "Mine", "Sorcery", zone=Zone.HAND)
    theirs = _object(engine, opponent, "Theirs", "Sorcery", zone=Zone.HAND)
    _object(engine, opponent, "Library Secret", "Sorcery", zone=Zone.LIBRARY)
    session = GameSession(engine, mode="replay", require_setup=False)
    view = session.observer_view()["state"]
    expected = {theirs.instance_id} | ({mine.instance_id} if reveal_both else set())
    assert {c["instance_id"] for p in view["players"] for c in p["hand"]} == expected
    assert {c["instance_id"] for c in view["known_cards"]} == expected
    assert all(not p["library"] for p in view["players"])
    engine.rules.exile(source)
    view = session.observer_view()["state"]
    assert not view["known_cards"]
    assert all(not p["hand"] for p in view["players"])


def _creature(engine, player, name="Bear", text="", *, subtype="Bear", **kwargs):
    return _object(engine, player, name, f"Creature — {subtype}", text, is_creature=True,
                   power=kwargs.pop("power", 2), toughness=kwargs.pop("toughness", 3), **kwargs)


def test_regeneration_rider_triggers_only_when_its_shield_is_used():
    engine, player, _ = _game()
    golem = _creature(engine, player, "Matopi Golem",
                      "{1}: Regenerate this creature. When it regenerates this way, put a -1/-1 counter on it.")
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, golem, 0)
    engine.resolve_until_stable()
    assert not golem.counters and not golem.tapped
    engine.rules.destroy(golem)
    assert golem.tapped and not golem.counters and golem in engine.state.permanents()
    engine.resolve_until_stable()
    assert golem.counters["-1/-1"] == 1
    engine.rules.destroy(golem)
    assert golem in player.graveyard


def test_regeneration_cost_counts_current_counters_and_adds_one_only_on_use():
    engine, player, _ = _game()
    creature = _creature(
        engine, player, "Skeleton Scavengers",
        "Pay {1} for each +1/+1 counter on this creature: Regenerate this creature. "
        "When it regenerates this way, put a +1/+1 counter on it.",
    )
    creature.add_counters("+1/+1", 2)
    player.mana_pool.add("C", 1)
    with pytest.raises(ValueError):
        engine.activate_ability(player, creature, 0)
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, creature, 0)
    engine.resolve_until_stable()
    assert player.mana_pool.total() == 0
    assert creature.counters["+1/+1"] == 2
    engine.rules.destroy(creature)
    engine.resolve_until_stable()
    assert creature.counters["+1/+1"] == 3


def test_debt_of_loyalty_gains_control_as_the_shield_replaces_destruction():
    engine, player, opponent = _game()
    victim = _creature(engine, opponent)
    debt = _object(engine, player, "Debt of Loyalty", "Instant",
                   "Regenerate target creature. You gain control of that creature if it regenerates this way.",
                   zone=Zone.HAND, is_instant=True)
    engine.cast_spell(player, debt, targets=[victim])
    engine.resolve_until_stable()
    assert victim.controller_id == opponent.id
    engine.rules.destroy(victim)
    assert victim.controller_id == player.id and victim in engine.state.permanents()


def test_sentry_gives_only_the_announced_opponent_a_draw_choice():
    engine, player, opponent = _game()
    sentry = _creature(engine, player, "Soldevi Sentry",
                       "{1}: Choose target opponent. Regenerate this creature. "
                       "When it regenerates this way, that player may draw a card.")
    draw = _object(engine, opponent, "Draw", "Instant", zone=Zone.LIBRARY, is_instant=True)
    player.mana_pool.add("C", 1)
    engine.activate_ability(player, sentry, 0, targets=[opponent])
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None
    engine.rules.destroy(sentry)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == opponent.id
    engine.resolve_pending_choice("yes")
    assert draw in opponent.hand


def test_linked_phasing_keeps_attachments_and_taps_only_the_creature_on_return():
    engine, player, opponent = _game()
    target = _creature(engine, opponent)
    equipment = _object(engine, opponent, "Equipment", "Artifact — Equipment")
    equipment.attached_to = target.instance_id
    source = _object(engine, player, "Oubliette", "Enchantment",
                     "When this enchantment enters, target creature phases out until this enchantment leaves "
                     "the battlefield. Tap that creature as it phases in this way.",
                     zone=Zone.GRAVEYARD)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(target.instance_id))
    engine.resolve_until_stable()
    visit = target.zone_incarnation
    assert target.phased_out and equipment.phased_out
    engine.state.active_player_index = 1
    engine._step_untap()
    assert target.phased_out and equipment.phased_out
    engine.rules.exile(source)
    assert not target.phased_out and not equipment.phased_out
    assert target.tapped and not equipment.tapped
    assert target.zone_incarnation == visit and equipment.attached_to == target.instance_id


def test_out_of_time_counts_only_phased_creatures_then_releases_them_on_last_counter():
    engine, player, opponent = _game()
    first = _creature(engine, player)
    second = _creature(engine, opponent, "Second Bear")
    first.tapped = second.tapped = True
    source = _object(
        engine, player, "Out of Time", "Enchantment",
        "When this enchantment enters, untap all creatures, then those creatures phase out until this "
        "enchantment leaves the battlefield. Put a time counter on this enchantment for each creature "
        "that phased out this way.\nVanishing", zone=Zone.GRAVEYARD, keywords=["Vanishing"],
    )
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    assert first.phased_out and second.phased_out
    assert not first.tapped and not second.tapped
    assert source.counters["time"] == 2
    engine.rules.add_counters(source, -2, "time")
    engine.resolve_until_stable()
    assert source in player.graveyard
    assert not first.phased_out and not second.phased_out


def test_plus_one_counter_history_requires_the_right_kind_actor_and_visit():
    engine, player, opponent = _game()
    kid = _creature(engine, player, "Kid Loki",
                    "Each creature you control that you've put one or more +1/+1 counters on this turn has hexproof.")
    paladin = _creature(engine, player, "Sigardian Paladin",
                        "As long as you've put one or more +1/+1 counters on a creature this turn, "
                        "this creature has trample and lifelink.")
    victim = _creature(engine, player)
    enemy = _creature(engine, opponent, "Enemy Bear")
    engine.rules.add_counters(victim, 1, "charge", source=kid)
    engine.rules.add_counters(victim, 1, "+1/+1", source=enemy)
    engine.recompute_continuous_effects()
    assert not combat.has(victim, "hexproof") and not combat.has(paladin, "trample")
    engine.rules.add_counters(victim, 1, "+1/+1", source=kid)
    engine.recompute_continuous_effects()
    assert combat.has(victim, "hexproof") and combat.has(paladin, "trample")
    engine.rules.put_into_graveyard(victim)
    engine.rules.return_from_graveyard(victim, "battlefield")
    engine.recompute_continuous_effects()
    assert not combat.has(victim, "hexproof") and combat.has(paladin, "trample")


def test_damage_history_follows_battlefield_visit_and_modified_tracks_counters():
    engine, player, opponent = _game()
    dragon = _creature(engine, player, "Palladia-Mors, the Ruiner",
                       "This creature has hexproof as long as it hasn't dealt damage yet.")
    spider = _creature(engine, player, "Skyward Spider",
                       "This creature has flying as long as it's modified.")
    engine.recompute_continuous_effects()
    assert combat.has(dragon, "hexproof")
    assert not combat.has(spider, "flying")
    engine.rules.deal_damage(opponent, 1, source=dragon)
    engine.rules.add_counters(spider, 1, "charge")
    engine.recompute_continuous_effects()
    assert not combat.has(dragon, "hexproof") and combat.has(spider, "flying")
    engine.rules.put_into_graveyard(dragon)
    engine.rules.return_from_graveyard(dragon, "battlefield")
    engine.recompute_continuous_effects()
    assert combat.has(dragon, "hexproof")


def test_library_top_is_public_and_live_for_color_and_type():
    engine, player, opponent = _game()
    nocturnus = _creature(
        engine, player, "Vampire Nocturnus",
        "Play with the top card of your library revealed.\nAs long as the top card of your library is black, "
        "this creature and other Vampire creatures you control get +2/+1 and have flying.",
        subtype="Vampire",
    )
    vampire = _creature(engine, player, "Other Vampire", subtype="Vampire")
    black = _creature(engine, player, "Black Top", mana_cost_string="{B}", zone=Zone.LIBRARY)
    engine.recompute_continuous_effects()
    assert nocturnus.power == vampire.power == 4 and combat.has(vampire, "flying")
    session = GameSession(engine, mode="replay", require_setup=False)
    assert black.instance_id in {c["instance_id"] for c in session.observer_view()["state"]["known_cards"]}
    _object(engine, player, "White Top", "Instant", mana_cost_string="{W}", zone=Zone.LIBRARY)
    engine.recompute_continuous_effects()
    assert nocturnus.power == vampire.power == 2 and not combat.has(vampire, "flying")


def test_common_color_ties_and_own_half_life_are_live():
    engine, player, opponent = _game()
    djinn = _creature(engine, player, "Goham Djinn", "This creature gets -2/-2 as long as black is the most "
                      "common color among all permanents or is tied for most common.",
                      power=5, toughness=5, mana_cost_string="{B}")
    god = _creature(engine, player, "God", "As long as your life total is less than or equal to half your "
                    "starting life total, this creature has indestructible.", mana_cost_string="{W}")
    opponent.life = opponent.starting_life // 2
    engine.recompute_continuous_effects()
    assert djinn.power == 3 and not combat.has(god, "indestructible")
    _creature(engine, opponent, "White Creature", mana_cost_string="{W}")
    player.life = player.starting_life // 2
    engine.recompute_continuous_effects()
    assert djinn.power == 5 and combat.has(god, "indestructible")


def test_group_anthem_reads_each_members_own_colors_counters_and_other_creatures():
    engine, player, _ = _game()
    _creature(engine, player, "Knight of New Alara",
              "Each other multicolored creature you control gets +1/+1 for each of its colors.")
    two = _creature(engine, player, "Two Colors", mana_cost_string="{W}{U}")
    three = _creature(engine, player, "Three Colors", mana_cost_string="{U}{B}{R}", subtype="Skeleton")
    _object(engine, player, "Counter Anthem", "Enchantment",
            "Each creature you control gets +1/+1 for each +1/+1 counter on it.")
    _object(engine, player, "Skeletal Swarming", "Enchantment",
            "Each Skeleton you control has trample, attacks each combat if able, and gets +X/+0, "
            "where X is the number of other Skeletons you control.")
    _creature(engine, player, "Skeleton", subtype="Skeleton")
    two.add_counters("+1/+1", 1)
    engine.recompute_continuous_effects()
    assert two.power == 6
    assert three.power == 6 and three.toughness == 6
    assert combat.has(three, "attacks_if_able")


def test_final_chapter_resolves_only_after_its_optional_instruction():
    engine, player, _ = _game()
    _object(engine, player, "Optional Saga", "Enchantment — Saga", "I — You may draw a card.")
    engine.resolve_until_stable()
    assert engine.state.pending_choice is not None
    assert not any(e.type == EventType.SAGA_FINAL_CHAPTER_RESOLVED for e in engine.state.event_log)
    engine.resolve_pending_choice(None)
    engine.resolve_until_stable()
    assert sum(e.type == EventType.SAGA_FINAL_CHAPTER_RESOLVED for e in engine.state.event_log) == 1


def test_linked_phasing_does_not_start_after_its_source_left():
    engine, player, opponent = _game()
    engine.interactive_priority = True
    target = _creature(engine, opponent)
    source = _object(engine, player, "Oubliette", "Enchantment",
                     "When this enchantment enters, target creature phases out until this enchantment leaves "
                     "the battlefield. Tap that creature as it phases in this way.",
                     zone=Zone.GRAVEYARD)
    engine.rules.return_from_graveyard(source, "battlefield")
    engine.resolve_until_stable()
    engine.resolve_pending_choice(str(target.instance_id))
    engine.rules.exile(source)
    engine.resolve_until_stable()
    assert not target.phased_out and not target.tapped


def test_renown_grants_both_the_keyword_and_mana_ability():
    engine, player, opponent = _game()
    creature = _creature(engine, player, "Honored Hierarch",
                         "Renown 1\nAs long as this creature is renowned, it has vigilance and "
                         '"{T}: Add one mana of any color."', keywords=["Renown"])
    engine.recompute_continuous_effects()
    assert not combat.has(creature, "vigilance")
    engine.rules.deal_damage(opponent, 2, source=creature, combat=True)
    engine.resolve_until_stable()
    assert creature.renowned and combat.has(creature, "vigilance")
    assert any(action["type"] == "tap_for_mana" and action["instance_id"] == creature.instance_id
               for action in engine.legal_actions(player))


def test_bane_declined_draw_uses_the_dying_creatures_last_toughness():
    engine, player, opponent = _game()
    _creature(engine, player, "Bane, Lord of Darkness",
              "Whenever another nontoken creature you control dies, target opponent may have you draw a card. "
              "If they don't, you may put a creature card with equal or lesser toughness from your hand onto the battlefield.")
    dead = _creature(engine, player, "Dies with 3 toughness")
    eligible = _creature(engine, player, "Eligible", zone=Zone.HAND)
    ineligible = _creature(engine, player, "Too tough", zone=Zone.HAND, toughness=4)
    engine.rules.put_into_graveyard(dead)
    engine.resolve_until_stable()
    engine.resolve_pending_choice(opponent.id)
    engine.resolve_until_stable()
    assert engine.state.pending_choice["player_id"] == opponent.id
    engine.resolve_pending_choice(None)
    engine.resolve_until_stable()
    options = {str(option["id"]) for option in engine.state.pending_choice["options"]}
    assert str(eligible.instance_id) in options and str(ineligible.instance_id) not in options
    engine.resolve_pending_choice(str(eligible.instance_id))
    assert eligible in engine.state.battlefield


def test_myrkul_exiles_the_dead_card_and_copies_it_as_enchantment_only():
    engine, player, _ = _game()
    _creature(engine, player, "Myrkul, Lord of Bones",
              "Whenever another nontoken creature you control dies, you may exile it. If you do, create a token "
              "that's a copy of that card, except it's an enchantment and loses all other card types.")
    dead = _object(engine, player, "Bear to Copy", "Legendary Enchantment Creature — Bear Shrine",
                   "{1}: You gain 2 life.", is_creature=True, is_legendary=True, power=2, toughness=3)
    engine.rules.put_into_graveyard(dead)
    engine.resolve_until_stable()
    answer = engine.state.pending_choice["options"][0]["id"]
    engine.resolve_pending_choice(answer)
    engine.resolve_until_stable()
    assert dead in player.exile
    token = next(obj for obj in engine.state.battlefield if obj.is_token)
    assert token.card.type_line == "Legendary Enchantment — Shrine" and not token.is_creature
    assert token.name == dead.name and token.activated_abilities


def test_card_cache_examples_cover_all_seven_mechanics():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    names = (
        "Historian's Boon", "Narci, Fable Singer", "Tom Bombadil",
        "Matopi Golem", "Skeleton Scavengers", "Debt of Loyalty", "Soldevi Sentry",
        "Oubliette", "Out of Time", "The Moment",
        "Revelation", "Wandering Eye", "Seer's Vision", "Telepathy", "Wisedrafter's Will",
        "Sigardian Paladin", "Beast, Erudite Aerialist", "Kid Loki", "Obstinate Gargoyle",
        "Skyward Spider", "Karakyk Guardian", "Palladia-Mors, the Ruiner",
        "Goblin Glory Chaser", "Honored Hierarch",
        "Mul Daya Channelers", "Vampire Nocturnus", "Crown of Convergence",
        "Goham Djinn", "Halam Djinn", "Sulam Djinn", "Zanam Djinn",
        "Bane, Lord of Darkness", "Bhaal, Lord of Murder", "Myrkul, Lord of Bones",
        "Heroes' Podium", "Knight of New Alara", "Clamavus", "Light from Within",
        "Diligent Zookeeper", "Mirror Box", "Takeno, Samurai General", "Skeletal Swarming",
    )
    with CardDatabase(DB_PATH) as db:
        cards = [card for name in names if (card := db.get_card(name))]
    if not cards:
        pytest.skip("example cards absent from local cache")
    failures = {card.name: result.unclaimed for card in cards
                if not (result := parse_oracle(card)).modeled}
    assert not failures


def test_group_anthem_counts_same_names_mana_pips_and_bushido_for_each_creature():
    engine, player, opponent = _game()
    _object(engine, player, "Mirror Box", "Artifact",
            "Each nontoken creature you control gets +1/+1 for each other creature you control "
            "with the same name as that creature.")
    _object(engine, player, "Light from Within", "Enchantment",
            "Each creature you control gets +1/+1 for each white mana symbol in its mana cost.")
    _creature(engine, player, "Takeno, Samurai General",
              "Each other Samurai creature you control gets +1/+1 for each point of bushido it has.",
              subtype="Samurai")
    first = _creature(engine, player, "Matching Name", mana_cost_string="{W}{W/U}",
                      subtype="Samurai", text="Bushido 2", keywords=["Bushido"])
    second = _creature(engine, player, "Matching Name", subtype="Samurai")
    other = _creature(engine, opponent, "Matching Name", subtype="Samurai")
    engine.recompute_continuous_effects()
    assert first.power == 7
    assert second.power == 3
    assert other.power == 2
