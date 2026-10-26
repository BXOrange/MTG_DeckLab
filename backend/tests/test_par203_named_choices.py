"""PAR-203 (RULE 608.2d): "Choose a creature type / a color / a card name." made as a spell or ability resolves.

Every shape is executed in the real engine: the choice is opened for the right player, answered, and the clauses
after it read the answer (through the ``$chosen_*`` placeholders `composition._build` resolves).
"""
import pytest

from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase
from mtg_analyzer.config import DB_PATH
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game, main_phase, stack_library


def _modeled(name):
    return parse_oracle(CardDatabase(DB_PATH).get_card(name)).coverage == MODELED


def _creature(eng, name, subtypes, player="p1", power=2, toughness=2):
    return filler(eng, name, type_line=f"Creature — {subtypes}", player=player, power=power, toughness=toughness)


def _pick(value):
    return lambda choice: value


NAMED = (
    "Kindred Dominance", "Kindred Judgment", "Raise the Palisade", "Outbreak", "Crippling Fear",
    "And They Shall Know No Fear", "Harmonized Crescendo", "Luminescent Rain", "Roar of the Crowd",
    "Coordinated Barrage", "Pack's Disdain", "Pol Jamaar, Illusionist", "Orcrist, Goblin-cleaver",
    "For the Ancestors", "Imagecrafter", "Mistform Mutant", "Unnatural Selection", "Standardize",
    "Mistform Wakecaster", "Addle", "Akroma's Blessing", "Reverent Mantra", "Sudden Demise", "Dromar, the Banisher",
    "Rith, the Awakener", "Treva, the Renewer", "Zombie Boa",
)


@pytest.mark.parametrize("name", NAMED)
def test_named_choice_cards_are_fully_modeled(name):
    assert _modeled(name)


def test_choice_is_offered_to_the_controller_with_the_types_in_the_game():
    eng = game()
    _creature(eng, "ElfA", "Elf Druid")
    _creature(eng, "WurmD", "Wurm", player="p2")
    obj = card(eng, "Kindred Dominance", zone=Zone.HAND)
    cast(eng, obj)
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_for_source" and choice["player_id"] == "p1"
    assert {o["id"] for o in choice["options"]} >= {"Elf", "Druid", "Wurm"}
    assert choice["free_text"] is True  # any RULE 205.3m type is legal, not just a suggestion


def test_only_the_chooser_is_offered_the_answers_and_the_choice_survives_a_clone():
    from mtg_analyzer.services.game_session import GameSession

    eng = game()
    _creature(eng, "ElfA", "Elf")
    obj = card(eng, "Kindred Dominance", zone=Zone.HAND)
    cast(eng, obj)
    session = GameSession(eng, require_setup=False)
    assert any(a["type"] == "choose" for a in session.legal_actions("p1"))
    assert session.legal_actions("p2") == []
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("Elf")
    clone.resolve_until_stable()
    assert not clone.state.pending_choice
    # the original is untouched by resolving the clone
    assert eng.state.pending_choice["kind"] == "choose_for_source"


def test_kindred_dominance_destroys_everything_not_of_the_chosen_type():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf Druid")
    goblin = _creature(eng, "GobB", "Goblin")
    their_elf = _creature(eng, "ElfC", "Elf", player="p2")
    wurm = _creature(eng, "WurmD", "Wurm", player="p2")
    cast(eng, card(eng, "Kindred Dominance", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert (elf.zone, their_elf.zone) == (Zone.BATTLEFIELD, Zone.BATTLEFIELD)
    assert (goblin.zone, wurm.zone) == (Zone.GRAVEYARD, Zone.GRAVEYARD)


def test_a_typed_answer_outside_the_suggestions_is_accepted_when_it_is_a_real_creature_type():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf")
    cast(eng, card(eng, "Raise the Palisade", zone=Zone.HAND))
    answer(eng, _pick("Goblin"))  # no Goblin anywhere: legal anyway (RULE 205.3m)
    eng.resolve_until_stable()
    assert elf.zone == Zone.HAND


def test_an_answer_that_is_no_creature_type_falls_back_to_the_first_suggestion():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf")
    wurm = _creature(eng, "WurmD", "Wurm", player="p2")
    cast(eng, card(eng, "Raise the Palisade", zone=Zone.HAND))
    answer(eng, _pick("Island"))
    eng.resolve_until_stable()
    # the first suggestion alphabetically is Elf, so the Wurm is the one that is not of the chosen type
    assert elf.zone == Zone.BATTLEFIELD and wurm.zone == Zone.HAND


def test_outbreak_shrinks_only_creatures_of_the_chosen_type():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf", toughness=1)
    big_elf = _creature(eng, "ElfB", "Elf", toughness=3)
    goblin = _creature(eng, "GobB", "Goblin", toughness=1)
    cast(eng, card(eng, "Outbreak", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert elf.zone == Zone.GRAVEYARD and goblin.zone == Zone.BATTLEFIELD
    assert big_elf.toughness == 2


def test_crippling_fear_hits_the_creatures_that_are_not_of_the_chosen_type():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf", toughness=3)
    goblin = _creature(eng, "GobB", "Goblin", player="p2", toughness=3)
    cast(eng, card(eng, "Crippling Fear", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert (elf.zone, elf.toughness) == (Zone.BATTLEFIELD, 3)
    assert goblin.zone == Zone.GRAVEYARD


def test_and_they_shall_know_no_fear_pumps_only_your_creatures_of_the_chosen_type():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf")
    goblin = _creature(eng, "GobB", "Goblin")
    their_elf = _creature(eng, "ElfC", "Elf", player="p2")
    cast(eng, card(eng, "And They Shall Know No Fear", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert elf.power == 3 and goblin.power == 2 and their_elf.power == 2


def test_counting_spells_read_the_chosen_type():
    eng = game()
    _creature(eng, "ElfA", "Elf")
    _creature(eng, "ElfB", "Elf")
    _creature(eng, "GobB", "Goblin")
    p1 = eng.state.player_by_id("p1")
    life = p1.life
    cast(eng, card(eng, "Luminescent Rain", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert p1.life == life + 4  # 2 life for each of the 2 Elves

    eng = game()
    for i in range(3):
        _creature(eng, f"ElfA{i}", "Elf")
    p1 = eng.state.player_by_id("p1")
    hand = len(p1.hand)
    cast(eng, card(eng, "Harmonized Crescendo", zone=Zone.HAND))
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert len(p1.hand) == hand + 3


def test_targeted_tail_announces_its_target_before_the_choice_and_keeps_it_across_the_pause():
    eng = game()
    for i in range(2):
        _creature(eng, f"ElfA{i}", "Elf")
    victim = _creature(eng, "Victim", "Goblin", player="p2", toughness=2)
    obj = card(eng, "Pack's Disdain", zone=Zone.HAND)
    cast(eng, obj, targets=[victim])
    assert eng.state.pending_choice["kind"] == "choose_for_source"
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD  # -1/-1 for each of the two Elves, then dead


def test_roar_of_the_crowd_deals_damage_equal_to_the_chosen_type_count_to_its_target():
    eng = game()
    for i in range(3):
        _creature(eng, f"ElfA{i}", "Elf")
    p2 = eng.state.player_by_id("p2")
    obj = card(eng, "Roar of the Crowd", zone=Zone.HAND)
    life = p2.life
    cast(eng, obj, targets=[p2])
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert p2.life == life - 3


def test_pol_jamaar_triggered_choice_draws_for_the_chosen_type():
    eng = game()
    _creature(eng, "ElfA", "Elf")
    _creature(eng, "ElfB", "Elf")
    p1 = eng.state.player_by_id("p1")
    hand = len(p1.hand)
    obj = card(eng, "Pol Jamaar, Illusionist", zone=Zone.HAND)
    cast(eng, obj)
    eng.resolve_until_stable()
    answer(eng, _pick("Elf"))
    eng.resolve_until_stable()
    assert len(p1.hand) == hand + 2  # Pol Jamaar itself is an Illusionist: only the two Elves count


def test_for_the_ancestors_takes_cards_of_the_chosen_type_from_the_top_six():
    eng = game()
    elf = card(eng, "Llanowar Elves", zone=Zone.LIBRARY)
    stack_library(eng, "p1", elf)
    obj = card(eng, "For the Ancestors", zone=Zone.HAND)
    cast(eng, obj)
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    answer(eng)
    eng.resolve_until_stable()
    assert elf.zone == Zone.HAND


# ---------------------------------------------------------------------------------------------------- colours

def _colored(eng, name, colors, player="p1", power=2, toughness=2, subtypes="Bear"):
    # printed colours are read off the mana cost (RULE 202.2)
    return filler(eng, name, type_line=f"Creature — {subtypes}", player=player, power=power, toughness=toughness,
                  mana_cost_string="".join("{%s}" % c for c in colors))


def test_color_choice_offers_the_five_colors_to_the_controller():
    eng = game()
    cast(eng, card(eng, "Reverent Mantra", zone=Zone.HAND))
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_for_source" and choice["player_id"] == "p1"
    assert [o["id"] for o in choice["options"]] == ["W", "U", "B", "R", "G"]
    assert not choice.get("free_text")


def test_sudden_demise_hits_only_creatures_of_the_chosen_color():
    eng = game()
    red = _colored(eng, "Red", "R")
    green = _colored(eng, "Green", "G", player="p2")
    obj = card(eng, "Sudden Demise", zone=Zone.HAND)
    main_phase(eng)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many(RICH)
    eng.cast_spell(p1, obj, x=2)
    eng.resolve_until_stable()
    answer(eng, _pick("R"))
    eng.resolve_until_stable()
    assert red.zone == Zone.GRAVEYARD and green.zone == Zone.BATTLEFIELD


def test_reverent_mantra_gives_every_creature_protection_from_the_chosen_color():
    eng = game()
    mine = _colored(eng, "Mine", "W")
    theirs = _colored(eng, "Theirs", "B", player="p2")
    cast(eng, card(eng, "Reverent Mantra", zone=Zone.HAND))
    answer(eng, _pick("R"))
    eng.resolve_until_stable()
    from mtg_analyzer.game.combat import is_protected_from

    red_source = _colored(eng, "RedSource", "R", player="p2")
    assert is_protected_from(mine, red_source) and is_protected_from(theirs, red_source)
    blue_source = _colored(eng, "BlueSource", "U", player="p2")
    assert not is_protected_from(mine, blue_source)


def test_addle_discards_the_card_of_the_chosen_color_the_caster_picks():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    red = filler(eng, "RedCard", type_line="Instant", player="p2", zone=Zone.HAND, mana_cost_string="{R}")
    blue = filler(eng, "BlueCard", type_line="Instant", player="p2", zone=Zone.HAND, mana_cost_string="{U}")
    cast(eng, card(eng, "Addle", zone=Zone.HAND), targets=[p2])
    eng.resolve_pending_choice("R")
    eng.resolve_until_stable()
    answer(eng)
    eng.resolve_until_stable()
    assert red.zone == Zone.GRAVEYARD and blue.zone == Zone.HAND


def test_rith_pays_then_chooses_a_color_and_makes_a_saproling_per_permanent_of_it():
    eng = game()
    rith = card(eng, "Rith, the Awakener")
    _colored(eng, "Black1", "B")
    _colored(eng, "Black2", "B", player="p2")
    _colored(eng, "Blue1", "U")
    main_phase(eng)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"G": 1, "C": 2})
    eng._apply_combat_damage([(eng.state.player_by_id("p2"), 2, rith)])
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    # the choice opens only once the cost is paid (an "if you do" instruction), and is the controller's
    assert eng.state.pending_choice["kind"] == "choose_for_source" and eng.state.pending_choice["player_id"] == "p1"
    eng.resolve_pending_choice("B")
    eng.resolve_until_stable()
    assert len([o for o in eng.state.battlefield if o.name == "Saproling"]) == 2


def test_declining_the_payment_never_opens_the_choice():
    eng = game()
    rith = card(eng, "Rith, the Awakener")
    main_phase(eng)
    eng.state.player_by_id("p1").mana_pool.add_many({"G": 1, "C": 2})
    eng._apply_combat_damage([(eng.state.player_by_id("p2"), 2, rith)])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("decline")
    eng.resolve_until_stable()
    assert eng.state.pending_choice is None
    assert not [o for o in eng.state.battlefield if o.name == "Saproling"]


@pytest.mark.parametrize("blocker_color,dies", (("R", True), ("G", False)))
def test_zombie_boa_destroys_a_blocker_of_the_chosen_color_only(blocker_color, dies):
    from tests.support.deck_batch import attack

    eng = game()
    boa = card(eng, "Zombie Boa")
    eng.state.player_by_id("p1").mana_pool.add_many({"B": 1, "C": 1})
    main_phase(eng)
    eng.activate_ability(eng.state.player_by_id("p1"), boa, 0)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "choose_for_source"
    eng.resolve_pending_choice("R")
    eng.resolve_until_stable()
    blocker = _colored(eng, "Blocker", blocker_color, player="p2", power=0, toughness=9)
    attack(eng, [boa])
    eng.state.current_step = "declare_blockers"
    eng.declare_blockers(eng.state.player_by_id("p2"), [{"blocker": blocker, "attacker": boa}])
    eng.resolve_until_stable()
    assert (blocker.zone == Zone.GRAVEYARD) is dies


# ---------------------------------------------------------------------------------- types as the answer to "that type"

def test_unnatural_selection_replaces_the_creature_types_of_its_target_until_end_of_turn():
    from mtg_analyzer.game import continuous

    eng = game()
    source = card(eng, "Unnatural Selection")
    target = _creature(eng, "Target", "Goblin Warrior", player="p2")
    _creature(eng, "Bulwark", "Wall", player="p2")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    main_phase(eng)
    eng.activate_ability(eng.state.player_by_id("p1"), source, 0, targets=[target])
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_for_source"
    assert "Wall" not in {o["id"] for o in choice["options"]}  # "other than Wall": never offered
    eng.resolve_pending_choice("Wall")  # ... and refused when typed: the first suggestion is used instead
    eng.resolve_until_stable()
    assert source.chosen_type == "Goblin"
    assert not continuous.has_subtype(target, "Wall")


def test_a_legal_typed_answer_replaces_the_types_and_wears_off_at_cleanup():
    from mtg_analyzer.game import continuous

    eng = game()
    source = card(eng, "Unnatural Selection")
    target = _creature(eng, "Target", "Goblin Warrior", player="p2")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    main_phase(eng)
    eng.activate_ability(eng.state.player_by_id("p1"), source, 0, targets=[target])
    eng.resolve_until_stable()
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert continuous.has_subtype(target, "Elf") and not continuous.has_subtype(target, "Goblin")
    eng._step_cleanup()
    assert continuous.has_subtype(target, "Goblin") and not continuous.has_subtype(target, "Elf")


def test_standardize_gives_every_creature_the_chosen_type():
    from mtg_analyzer.game import continuous

    eng = game()
    a = _creature(eng, "A", "Goblin")
    b = _creature(eng, "B", "Wurm", player="p2")
    cast(eng, card(eng, "Standardize", zone=Zone.HAND))
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert all(continuous.has_subtype(o, "Elf") for o in (a, b))
    assert not continuous.has_subtype(a, "Goblin") and not continuous.has_subtype(b, "Wurm")


def test_bloodline_bidding_returns_only_the_chosen_types_cards_from_your_graveyard():
    eng = game()
    elf = _creature(eng, "DeadElf", "Elf")
    goblin = _creature(eng, "DeadGoblin", "Goblin")
    theirs = _creature(eng, "TheirElf", "Elf", player="p2")
    for o in (elf, goblin, theirs):
        eng.rules.destroy(o)
    eng.resolve_until_stable()
    cast(eng, card(eng, "Bloodline Bidding", zone=Zone.HAND))
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert elf.zone == Zone.BATTLEFIELD
    assert goblin.zone == Zone.GRAVEYARD and theirs.zone == Zone.GRAVEYARD


def test_bloodline_shaman_puts_a_hit_into_hand_and_a_miss_into_the_graveyard():
    eng = game()
    shaman = card(eng, "Bloodline Shaman")
    elf = card(eng, "Llanowar Elves", zone=Zone.LIBRARY)
    stack_library(eng, "p1", elf)
    activate(eng, shaman)
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert elf.zone == Zone.HAND

    eng = game()
    shaman = card(eng, "Bloodline Shaman")
    miss = card(eng, "Forest", zone=Zone.LIBRARY)
    stack_library(eng, "p1", miss)
    activate(eng, shaman)
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert miss.zone == Zone.GRAVEYARD


def test_elvish_soultiller_shuffles_the_chosen_types_graveyard_cards_back():
    eng = game()
    soultiller = card(eng, "Elvish Soultiller")
    elf = _creature(eng, "DeadElf", "Elf")
    goblin = _creature(eng, "DeadGoblin", "Goblin")
    eng.rules.destroy(elf)
    eng.rules.destroy(goblin)
    eng.rules.destroy(soultiller)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "choose_for_source"
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    p1 = eng.state.player_by_id("p1")
    assert elf in p1.library and goblin in p1.graveyard
    assert soultiller in p1.library  # it is itself a creature card of the chosen (Elf) type


def test_riptide_shapeshifter_digs_for_the_chosen_type():
    eng = game()
    shifter = card(eng, "Riptide Shapeshifter")
    elf = card(eng, "Llanowar Elves", zone=Zone.LIBRARY)
    stack_library(eng, "p1", elf)
    eng.state.player_by_id("p1").mana_pool.add_many({"U": 2, "C": 2})
    main_phase(eng)
    eng.activate_ability(eng.state.player_by_id("p1"), shifter, 0)
    eng.resolve_until_stable()
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert elf.zone == Zone.BATTLEFIELD


# ------------------------------------------------------------------------------------------------- card names

NAME_CARDS = (
    "Slaughter Games", "Cranial Extraction", "Memoricide", "Stain the Mind", "Lost Legacy", "Unmoored Ego",
    "Ancient Vendetta", "Necromentia", "Thought Hemorrhage", "Dispossess", "Infinite Obliteration", "The Stone Brain",
    "Cabal Therapy", "Brain Pry",
)


@pytest.mark.parametrize("name", NAME_CARDS)
def test_name_choice_cards_are_fully_modeled(name):
    assert _modeled(name)


def _copy(eng, name, player, zone):
    return filler(eng, name, type_line="Instant", player=player, zone=zone)


def _name_spell(eng, spell, name, *, targets, pool=None):
    cast(eng, card(eng, spell, zone=Zone.HAND), targets=targets, pool=pool)
    choice = eng.state.pending_choice
    assert choice["kind"] == "choose_for_source" and choice["player_id"] == "p1" and choice["free_text"] is True
    eng.resolve_pending_choice(name)
    eng.resolve_until_stable()


def test_the_name_choice_suggests_the_names_the_chooser_can_see():
    eng = game()
    _copy(eng, "Fireball", "p2", Zone.GRAVEYARD)
    cast(eng, card(eng, "Slaughter Games", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    names = {o["id"] for o in eng.state.pending_choice["options"]}
    assert "Fireball" in names


def test_slaughter_games_exiles_every_copy_from_graveyard_hand_and_library_then_shuffles():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    copies = [_copy(eng, "Fireball", "p2", z) for z in (Zone.GRAVEYARD, Zone.HAND, Zone.LIBRARY, Zone.LIBRARY)]
    other = _copy(eng, "Shock", "p2", Zone.HAND)
    mine = _copy(eng, "Fireball", "p1", Zone.GRAVEYARD)
    _name_spell(eng, "Slaughter Games", "fireball", targets=[p2])
    assert all(c.zone == Zone.EXILE for c in copies)
    assert other.zone == Zone.HAND and mine.zone == Zone.GRAVEYARD  # only the target player's cards


def test_ancient_vendetta_takes_at_most_four():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    copies = [_copy(eng, "Fireball", "p2", Zone.LIBRARY) for _ in range(6)]
    _name_spell(eng, "Ancient Vendetta", "Fireball", targets=[p2])
    assert sum(1 for c in copies if c.zone == Zone.EXILE) == 4


def test_lost_legacy_draws_a_card_for_each_copy_exiled_from_the_hand():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    _copy(eng, "Fireball", "p2", Zone.HAND)
    _copy(eng, "Fireball", "p2", Zone.HAND)
    _copy(eng, "Fireball", "p2", Zone.GRAVEYARD)
    hand_before = len(p2.hand) - 2
    _name_spell(eng, "Lost Legacy", "Fireball", targets=[p2])
    assert len(p2.hand) == hand_before + 2  # the two copies left; "that player draws" two cards


def test_necromentia_gives_the_target_player_a_zombie_per_hand_copy():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    _copy(eng, "Fireball", "p2", Zone.HAND)
    _copy(eng, "Fireball", "p2", Zone.LIBRARY)
    _name_spell(eng, "Necromentia", "Fireball", targets=[p2])
    zombies = [o for o in eng.state.battlefield if o.name == "Zombie"]
    assert len(zombies) == 1 and zombies[0].controller_id == "p2"


def test_thought_hemorrhage_deals_damage_for_each_revealed_copy_then_exiles_all():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    hand = [_copy(eng, "Fireball", "p2", Zone.HAND) for _ in range(2)]
    gy = _copy(eng, "Fireball", "p2", Zone.GRAVEYARD)
    life = p2.life
    _name_spell(eng, "Thought Hemorrhage", "Fireball", targets=[p2])
    assert p2.life == life - 6
    assert all(c.zone == Zone.EXILE for c in hand + [gy])


def test_cabal_therapy_discards_only_the_named_cards():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    named = [_copy(eng, "Fireball", "p2", Zone.HAND) for _ in range(2)]
    other = _copy(eng, "Shock", "p2", Zone.HAND)
    _name_spell(eng, "Cabal Therapy", "Fireball", targets=[p2])
    assert all(c.zone == Zone.GRAVEYARD for c in named) and other.zone == Zone.HAND


def test_brain_pry_draws_when_the_named_card_is_not_in_hand_and_discards_one_when_it_is():
    eng = game()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    drawn = len(p1.hand)
    _name_spell(eng, "Brain Pry", "Fireball", targets=[p2])
    assert len(p1.hand) == drawn + 1

    eng = game()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    named = [_copy(eng, "Fireball", "p2", Zone.HAND) for _ in range(2)]
    drawn = len(p1.hand)
    _name_spell(eng, "Brain Pry", "Fireball", targets=[p2])
    assert sum(1 for c in named if c.zone == Zone.GRAVEYARD) == 1 and len(p1.hand) == drawn


def test_a_land_is_not_a_legal_answer_to_a_nonland_card_name():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    forest = filler(eng, "Forest", type_line="Basic Land — Forest", player="p2", zone=Zone.HAND)
    _name_spell(eng, "Cranial Extraction", "Forest", targets=[p2])
    assert forest.zone == Zone.HAND  # the answer was refused, so it names nothing


def test_other_than_a_basic_land_card_name_refuses_a_basic_land():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    forest = filler(eng, "Forest", type_line="Basic Land — Forest", player="p2", zone=Zone.HAND)
    _name_spell(eng, "Necromentia", "Forest", targets=[p2])
    assert forest.zone == Zone.HAND


def test_a_name_that_matches_nothing_still_shuffles_and_changes_nothing():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    bystander = _copy(eng, "Shock", "p2", Zone.HAND)
    _name_spell(eng, "Slaughter Games", "Not A Card In This Game", targets=[p2])
    assert bystander.zone == Zone.HAND and eng.state.pending_choice is None


def test_a_pending_name_choice_survives_a_clone_and_names_after_it():
    eng = game()
    p2 = eng.state.player_by_id("p2")
    copy = _copy(eng, "Fireball", "p2", Zone.GRAVEYARD)
    cast(eng, card(eng, "Slaughter Games", zone=Zone.HAND), targets=[p2])
    clone = GameEngine(eng.state.clone())
    clone.resolve_pending_choice("Fireball")
    clone.resolve_until_stable()
    twin = clone.state.find_object(copy.instance_id)
    assert twin.zone == Zone.EXILE and copy.zone == Zone.GRAVEYARD


def test_wood_sage_takes_every_named_card_from_the_top_four_and_mills_the_rest():
    eng = game()
    sage = card(eng, "Wood Sage")
    named = [filler(eng, "Bear", type_line="Creature — Bear", power=2, toughness=2, zone=Zone.LIBRARY) for _ in range(2)]
    other = [filler(eng, "Wolf", type_line="Creature — Wolf", power=2, toughness=2, zone=Zone.LIBRARY) for _ in range(2)]
    stack_library(eng, "p1", *other, *named)
    activate(eng, sage)
    eng.resolve_pending_choice("Bear")
    eng.resolve_until_stable()
    assert all(c.zone == Zone.HAND for c in named) and all(c.zone == Zone.GRAVEYARD for c in other)


def test_desperate_research_exiles_the_rest_of_the_top_seven():
    eng = game()
    named = filler(eng, "Bolt", type_line="Instant", zone=Zone.LIBRARY)
    rest = [filler(eng, f"Rest{i}", type_line="Instant", zone=Zone.LIBRARY) for i in range(6)]
    stack_library(eng, "p1", *rest, named)
    cast(eng, card(eng, "Desperate Research", zone=Zone.HAND))
    eng.resolve_pending_choice("Bolt")
    eng.resolve_until_stable()
    assert named.zone == Zone.HAND and all(c.zone == Zone.EXILE for c in rest)


def test_divining_witch_exiles_six_then_digs_for_the_named_card():
    eng = game()
    witch = card(eng, "Divining Witch")
    target = filler(eng, "Bolt", type_line="Instant", zone=Zone.LIBRARY)
    skipped = [filler(eng, f"Skip{i}", type_line="Instant", zone=Zone.LIBRARY) for i in range(6)]
    between = [filler(eng, f"Mid{i}", type_line="Instant", zone=Zone.LIBRARY) for i in range(2)]
    stack_library(eng, "p1", target, *between, *skipped)
    main_phase(eng)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 1, "C": 1})
    discard = filler(eng, "Fodder", type_line="Instant", zone=Zone.HAND)
    eng.activate_ability(p1, witch, 0)
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "choose_for_source"
    eng.resolve_pending_choice("Bolt")
    eng.resolve_until_stable()
    assert target.zone == Zone.HAND and discard.zone == Zone.GRAVEYARD
    assert all(c.zone == Zone.EXILE for c in skipped + between)


def test_cabal_therapist_chooses_its_target_after_the_sacrifice_and_names_afterwards():
    from tests.support.deck_batch import step

    eng = game()
    card(eng, "Cabal Therapist")
    fodder = filler(eng, "Fodder", type_line="Creature — Bear", power=1, toughness=1)
    named = [filler(eng, "Fireball", type_line="Instant", player="p2", zone=Zone.HAND) for _ in range(2)]
    other = filler(eng, "Shock", type_line="Instant", player="p2", zone=Zone.HAND)
    step(eng, "main1")
    seen = []
    for _ in range(8):
        choice = eng.state.pending_choice
        if choice is None:
            eng.resolve_until_stable()
            choice = eng.state.pending_choice
            if choice is None:
                break
        seen.append(choice["kind"])
        pick = {"pay_cost_then": "pay", "choose_objects": str(fodder.instance_id), "trigger_target": "p2",
                "choose_for_source": "Fireball"}[choice["kind"]]
        eng.resolve_pending_choice(pick)
        eng.resolve_until_stable()
    # RULE 603.12: "when you do" is a reflexive trigger, so its target comes after the sacrifice
    assert seen == ["pay_cost_then", "choose_objects", "trigger_target", "choose_for_source"]
    assert fodder.zone == Zone.GRAVEYARD
    assert all(c.zone == Zone.GRAVEYARD for c in named) and other.zone == Zone.HAND


@pytest.mark.parametrize("spell,targets", (("Kindred Dominance", False), ("Reverent Mantra", False), ("Slaughter Games", True)))
def test_bots_answer_the_choice_through_their_view_and_legal_actions(spell, targets):
    from mtg_analyzer.services.bot_policies.smart import SmartBot
    from mtg_analyzer.services.bots import Bot, GreedyBot
    from mtg_analyzer.services.game_session import GameSession

    for bot_class in (Bot, GreedyBot, SmartBot):
        eng = game()
        _creature(eng, "ElfA", "Elf")
        _creature(eng, "WurmD", "Wurm", player="p2")
        _copy(eng, "Fireball", "p2", Zone.HAND)
        cast(eng, card(eng, spell, zone=Zone.HAND), targets=[eng.state.player_by_id("p2")] if targets else None)
        session = GameSession(eng, require_setup=False)
        assert eng.state.pending_choice["kind"] == "choose_for_source"
        answer_action = bot_class("p1").answer_choice(session.view("p1"), session.legal_actions("p1"))
        session.apply_action(answer_action, "p1")
        session.engine.resolve_until_stable()
        assert session.engine.state.pending_choice is None


def test_the_opponent_sees_only_that_a_choice_is_pending_not_the_suggestions():
    from mtg_analyzer.services.game_session import GameSession

    eng = game()
    filler(eng, "SecretLib", type_line="Instant", zone=Zone.LIBRARY)
    filler(eng, "SecretHand", type_line="Instant", zone=Zone.HAND)
    cast(eng, card(eng, "Slaughter Games", zone=Zone.HAND), targets=[eng.state.player_by_id("p2")])
    session = GameSession(eng, require_setup=False)
    mine = session.view("p1")["state"]["pending_choice"]
    assert {"SecretHand", "SecretLib"} <= {o["id"] for o in mine["options"]}  # the chooser's own cards (RULE 400.2)
    theirs = session.view("p2")["state"]
    assert theirs["pending_choice"] is None and theirs["waiting_on_choice"]["decider_id"] == "p1"


# ----------------------------------------------------------------------------------------------- fail-closed shapes

@pytest.mark.parametrize("name", (
    "Crosis, the Purger",       # "that player" is the combat-damage event's player, gone once the choice resumes
    "Rohirrim Chargers",        # "attached to that creature" is not carried by the generic dig-until row
    "Tsabo's Decree", "Pact of the Serpent", "Peer Pressure", "Kindred Charge",  # shapes with no primitive yet
    "Cursed Scroll", "Mise", "Predict",                                          # reveal-and-compare is not modelled
    "Meddling Mage", "Prismatic Boon", "Searing Rays",
))
def test_shapes_without_a_primitive_stay_unmodeled(name):
    assert not _modeled(name)


@pytest.mark.parametrize("body", (
    "choose a creature type. creatures you control of the chosen type gain flying until end of turn",
    "choose a color. all creatures of that color get -1/-1 until end of turn",
))
def test_a_tail_that_reads_the_chosen_value_is_claimed_as_one_choice_then_one_body(body):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    [spec] = parse_effect_body(body)
    assert spec.type == "seq"
    choose, tail = spec.params["effects"]
    assert choose["type"] == "choose_for_source" and tail["type"] == "seq"


@pytest.mark.parametrize("body", (
    # the choice is never read by the tail: not this shape
    "choose a creature type. draw a card",
    "choose a color. draw a card",
    # an event referent would be gone by the time the tail resumes
    "choose a color. target creature gets +1/+1 until end of turn for each creature of that color that player controls",
))
def test_a_tail_that_never_reads_the_choice_is_left_unclaimed(body):
    from mtg_analyzer.parser.oracle.segmenter import parse_effect_body

    assert parse_effect_body(body) is None


def test_a_pick_left_on_the_object_by_an_earlier_use_never_stands_in_for_this_resolution():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf")
    wurm = _creature(eng, "WurmD", "Wurm", player="p2")
    spell = card(eng, "Raise the Palisade", zone=Zone.HAND)
    spell.chosen_type = "Wurm"  # e.g. a flashed-back spell's previous answer
    cast(eng, spell)
    assert spell.chosen_type is None  # cleared as the choice opens
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert elf.zone == Zone.BATTLEFIELD and wurm.zone == Zone.HAND


def test_a_repeatable_ability_reads_each_new_answer_not_the_previous_one():
    eng = game()
    shaman = card(eng, "Bloodline Shaman")
    elf = card(eng, "Llanowar Elves", zone=Zone.LIBRARY)
    bear = card(eng, "Grizzly Bears", zone=Zone.LIBRARY)
    stack_library(eng, "p1", bear, elf)  # the Elf is on top
    activate(eng, shaman)
    eng.resolve_pending_choice("Elf")
    eng.resolve_until_stable()
    assert elf.zone == Zone.HAND and shaman.chosen_type == "Elf"
    shaman.tapped = False
    activate(eng, shaman)
    eng.resolve_pending_choice("Bear")  # a different answer the second time
    eng.resolve_until_stable()
    assert bear.zone == Zone.HAND and shaman.chosen_type == "Bear"


def test_a_spell_object_carrying_an_old_answer_uses_the_new_one():
    eng = game()
    elf = _creature(eng, "ElfA", "Elf")
    wurm = _creature(eng, "WurmE", "Wurm", player="p2")
    spell = card(eng, "Kindred Dominance", zone=Zone.HAND)
    spell.chosen_type = "Elf"  # what an earlier resolution of this very object (a flashback) left behind
    cast(eng, spell)
    eng.resolve_pending_choice("Wurm")
    eng.resolve_until_stable()
    assert elf.zone == Zone.GRAVEYARD and wurm.zone == Zone.BATTLEFIELD


def test_when_you_do_with_a_wrapped_targeted_body_is_a_reflexive_trigger():
    """`pay_cost_then` read a targeting body only when its first spec named the target; a `bind` wrapper hid it and the
    target was never announced (Go-Shintai, Armix, Tiger-Tribe Hunter). RULE 603.12: the target comes after the payment."""
    from tests.support.deck_batch import step

    eng = game()
    card(eng, "Go-Shintai of Ancient Wars")
    for i in range(2):
        filler(eng, f"Shrine{i}", type_line="Enchantment — Shrine")
    eng.state.player_by_id("p1").mana_pool.add_many({"C": 1})
    p2 = eng.state.player_by_id("p2")
    life = p2.life
    step(eng, "end")
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    eng.resolve_pending_choice("pay")
    eng.resolve_until_stable()
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice("p2")
    eng.resolve_until_stable()
    assert p2.life == life - 3  # itself and two other Shrines
