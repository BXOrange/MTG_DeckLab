"""PAR-154: named 'choose target creature. When that creature dies this turn, …' cards (real engine, real cards)."""
from mtg_analyzer.config import DB_PATH
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from tests.support.deck_batch import card, cast, filler, game


def _modeled(name):
    return parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


def test_time_to_feed_is_modeled():
    assert _modeled("Time to Feed")


def test_time_to_feed_fight_kills_the_creature_and_gains_life():
    engine = game()
    spell = card(engine, "Time to Feed", zone=Zone.HAND)
    mine = filler(engine, "Mine", power=3, toughness=3)
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=3)
    cast(engine, spell, groups=[[theirs], [mine]])
    assert theirs.zone == Zone.GRAVEYARD
    assert mine.damage_marked == 1
    assert engine.state.player_by_id("p1").life == 23


def test_time_to_feed_gains_nothing_if_the_creature_survives():
    engine = game()
    spell = card(engine, "Time to Feed", zone=Zone.HAND)
    mine = filler(engine, "Mine", power=2, toughness=3)
    theirs = filler(engine, "Theirs", player="p2", power=1, toughness=3)
    cast(engine, spell, groups=[[theirs], [mine]])
    assert theirs.zone == Zone.BATTLEFIELD
    assert engine.state.player_by_id("p1").life == 20


def _library_creature(engine, name, mv, player="p1"):
    return filler(engine, name, type_line="Creature — Bear", player=player, mv=mv, power=1, toughness=1, zone=Zone.LIBRARY)


def _kill(engine, victim):
    engine.rules.destroy(victim)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()


def test_rushed_rebirth_is_modeled():
    assert _modeled("Rushed Rebirth")


def test_rushed_rebirth_searches_only_lesser_mana_values_and_enters_tapped():
    from tests.support.deck_batch import answer

    engine = game()
    spell = card(engine, "Rushed Rebirth", zone=Zone.HAND)
    victim = filler(engine, "Victim", player="p2", mv=3, power=1, toughness=1)
    same = _library_creature(engine, "SameMV", 3)
    less = _library_creature(engine, "LessMV", 2)
    cast(engine, spell, targets=[victim])
    _kill(engine, victim)
    options = [str(o.get("label")) for o in (engine.state.pending_choice or {}).get("options", [])]
    assert any("LessMV" in o for o in options)
    assert not any("SameMV" in o for o in options)
    answer(engine)
    assert less.zone == Zone.BATTLEFIELD and less.tapped
    assert same.zone == Zone.LIBRARY


def test_rushed_rebirth_does_nothing_if_the_creature_does_not_die():
    engine = game()
    spell = card(engine, "Rushed Rebirth", zone=Zone.HAND)
    victim = filler(engine, "Victim", player="p2", mv=3, power=1, toughness=1)
    less = _library_creature(engine, "LessMV", 2)
    cast(engine, spell, targets=[victim])
    assert engine.state.pending_choice is None
    assert less.zone == Zone.LIBRARY


def test_reincarnation_is_modeled():
    assert _modeled("Reincarnation")


def test_reincarnation_returns_a_creature_card_to_the_dead_creatures_owner():
    from tests.support.deck_batch import answer, pick_label

    engine = game()
    spell = card(engine, "Reincarnation", zone=Zone.HAND)
    victim = filler(engine, "Victim", player="p2", power=1, toughness=1)
    # The pick is p1's (Reincarnation's controller) but the card comes back for p2, the victim's owner.
    other = filler(engine, "Other", type_line="Creature — Bear", player="p2", power=2, toughness=2, zone=Zone.GRAVEYARD)
    mine = filler(engine, "Mine", type_line="Creature — Bear", player="p1", power=2, toughness=2, zone=Zone.GRAVEYARD)
    cast(engine, spell, targets=[victim])
    _kill(engine, victim)
    options = [str(o.get("label")) for o in (engine.state.pending_choice or {}).get("options", [])]
    assert any("Other" in o for o in options) and any("Victim" in o for o in options)
    assert not any("Mine" in o for o in options)
    assert engine.state.pending_choice["player_id"] == "p1"
    answer(engine, pick_label("Other"))
    assert other.zone == Zone.BATTLEFIELD and other.controller_id == "p2"
    assert mine.zone == Zone.GRAVEYARD


def test_sandals_of_abdallah_is_modeled():
    assert _modeled("Sandals of Abdallah")


def test_sandals_are_destroyed_when_the_chosen_creature_dies_this_turn():
    from tests.support.deck_batch import activate

    engine = game()
    sandals = card(engine, "Sandals of Abdallah")
    victim = filler(engine, "Victim", power=1, toughness=1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(engine, sandals, targets=[victim])
    assert "islandwalk" in {str(k).lower() for k in victim.granted_keywords}
    _kill(engine, victim)
    assert sandals.zone == Zone.GRAVEYARD


def test_sandals_that_were_blinked_are_a_new_object_and_survive():
    from tests.support.deck_batch import activate

    engine = game()
    sandals = card(engine, "Sandals of Abdallah")
    victim = filler(engine, "Victim", power=1, toughness=1)
    engine.state.player_by_id("p1").mana_pool.add_many({"C": 2})
    activate(engine, sandals, targets=[victim])
    engine.rules.blink(sandals)  # RULE 400.7: it comes back as a new object
    _kill(engine, victim)
    assert sandals.zone == Zone.BATTLEFIELD


def test_initiate_of_blood_and_goka_are_both_modeled():
    card_ = CardDatabase(DB_PATH).get_card("Initiate of Blood")
    assert card_.is_flip and card_.flip_face().name == "Goka the Unjust"
    assert parse_oracle(card_).modeled


def _initiate_and_wounded_victim(toughness=2):
    from tests.support.deck_batch import activate

    engine = game()
    initiate = card(engine, "Initiate of Blood")
    victim = filler(engine, "Victim", player="p2", power=1, toughness=toughness)
    engine.rules.deal_damage(victim, 1, None)  # "was dealt damage this turn" (RULE 120)
    activate(engine, initiate, targets=[victim])
    return engine, initiate, victim


def test_initiate_of_blood_flips_when_its_target_dies_this_turn():
    engine, initiate, victim = _initiate_and_wounded_victim()
    assert victim.zone == Zone.GRAVEYARD
    assert initiate.flipped and initiate.name == "Goka the Unjust"
    engine.recompute_continuous_effects()
    assert (initiate.power, initiate.toughness) == (4, 4)
    assert initiate.card.is_legendary
    assert initiate.mana_value == 4  # RULE 710.1c: the mana cost does not change
    assert [e.amount for e in initiate.activated_abilities[0].effects] == [4]  # Goka's ability, not the Initiate's


def test_initiate_of_blood_stays_unflipped_while_its_target_survives():
    engine, initiate, victim = _initiate_and_wounded_victim(toughness=5)
    assert victim.zone == Zone.BATTLEFIELD
    assert not initiate.flipped and initiate.name.startswith("Initiate of Blood")
    _kill(engine, victim)  # it dies later this turn
    assert initiate.flipped


def test_initiate_of_blood_can_only_target_a_creature_dealt_damage_this_turn():
    from mtg_analyzer.game.targeting import legal_targets

    engine = game()
    initiate = card(engine, "Initiate of Blood")
    fresh = filler(engine, "Fresh", player="p2", power=1, toughness=3)
    hurt = filler(engine, "Hurt", player="p2", power=1, toughness=3)
    engine.rules.deal_damage(hurt, 1, None)
    ability = initiate.activated_abilities[0]
    spec = ability.effects[0].target_spec
    legal = {d["instance_id"] for d in legal_targets(engine.state, "p1", spec, initiate)}
    assert hurt.instance_id in legal and fresh.instance_id not in legal


def test_a_flipped_permanent_forgets_the_flip_when_it_changes_zones():
    engine, initiate, _ = _initiate_and_wounded_victim()
    assert initiate.flipped
    engine.rules.blink(initiate)
    assert not initiate.flipped and initiate.name.startswith("Initiate of Blood")
    # The front's ability is back: its 1 damage plus the delayed "flip ~" trigger Goka's ability lacks.
    assert [e.amount for e in initiate.activated_abilities[0].effects[:1]] == [1]
    assert len(initiate.activated_abilities[0].effects) == 2


def test_a_blinked_initiate_is_not_flipped_by_the_old_objects_trigger():
    from tests.support.deck_batch import activate

    engine = game()
    initiate = card(engine, "Initiate of Blood")
    victim = filler(engine, "Victim", player="p2", power=1, toughness=5)
    engine.rules.deal_damage(victim, 1, None)
    activate(engine, initiate, targets=[victim])
    engine.rules.blink(initiate)
    _kill(engine, victim)
    assert not initiate.flipped


def test_bushi_tenderfoot_flips_into_kenzo_with_its_own_keywords_only():
    engine = game()
    bushi = card(engine, "Bushi Tenderfoot")
    victim = filler(engine, "Victim", player="p2", power=1, toughness=2)
    engine.recompute_continuous_effects()
    assert "Double strike" not in {str(k) for k in bushi.card.keywords}  # Kenzo's keyword, not the front's
    engine.rules.deal_damage(victim, 1, bushi)
    engine.rules.deal_damage(victim, 1, bushi)
    engine.rules.put_triggers_on_stack()
    engine.resolve_until_stable()
    assert bushi.flipped and bushi.name == "Kenzo the Hardhearted"
    assert {str(k).lower() for k in bushi.card.keywords} >= {"double strike", "bushido"}


def test_a_flip_card_replays_flipped():
    from mtg_analyzer.services.replay import build_replay_engine, serialize_replay

    engine, initiate, _ = _initiate_and_wounded_victim()
    from tests.test_replay import _FakeLoader

    rebuilt = build_replay_engine(
        serialize_replay(engine.state), _FakeLoader({initiate._front_card.name: initiate._front_card}),
    )
    again = next(o for o in rebuilt.state.battlefield if o.name == "Goka the Unjust")
    assert again.flipped
