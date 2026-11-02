"""Singleton batch 2 (worker F): ten hand-authored cards, each executed in a real engine."""

from __future__ import annotations

from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.card_registry import is_registered
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models import Card, GameObject, ManaCost, Zone

#: Enough of every colour that mana never decides the outcome of a test.
_POOL_AMOUNT = 30


def _card(name, type_line, text="", cost="{1}", power=None, toughness=None, **flags):
    is_creature = "creature" in type_line.lower()
    return Card(
        id=name, name=name, type_line=type_line, mana_cost_string=cost,
        converted_mana_cost=ManaCost.parse(cost).converted_mana_cost,
        is_creature=is_creature, is_instant="instant" in type_line.lower(),
        power=power if is_creature else None, toughness=toughness if is_creature else None,
        oracle_text=text, is_legendary="legendary" in type_line.lower(), **flags,
    )


def _bear(name="Bear", power=2, toughness=2, type_line="Creature — Bear"):
    return _card(name, type_line, "", "{1}{G}", power, toughness)


def _engine():
    filler = [_bear(f"Filler {i}", 1, 1) for i in range(30)]
    return GameEngine.new_game(
        [("p1", "Alice", list(filler)), ("p2", "Bob", list(filler))], starting_life=20, starting_hand=0,
    )


def _put(engine, card, controller="p1", tapped=False):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    obj.tapped = tapped
    bind_from_catalogue(obj)
    engine.state.add_to_battlefield(obj)
    return obj


def _to_hand(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.HAND)
    obj.controller_id = controller
    bind_from_catalogue(obj)
    engine.state.player_by_id(controller).hand.append(obj)
    return obj


def _to_graveyard(engine, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.GRAVEYARD)
    obj.controller_id = controller
    engine.state.player_by_id(controller).graveyard.append(obj)
    return obj


def _stack_library(engine, cards, controller="p1"):
    """Replace the top of the library with ``cards`` (first card ends up on top)."""
    library = engine.state.player_by_id(controller).library
    objs = []
    for card in reversed(cards):  # the library's end is its top (`RulesEngine._mill` pops it)
        obj = GameObject(card, owner_id=controller, zone=Zone.LIBRARY)
        obj.controller_id = controller
        objs.append(obj)
    library[-len(objs):] = objs
    return list(reversed(objs))


def _main_phase(engine):
    engine.start()
    while engine.state.current_phase != "precombat_main":
        engine.advance_step()
    player = engine.state.player_by_id("p1")
    for colour in "WUBRGC":
        player.mana_pool.add(colour, _POOL_AMOUNT)
    return player


def _cast(engine, player, obj, **kwargs):
    engine.cast_spell(player, obj, **kwargs)
    engine.resolve_until_stable()


def _answer(engine, option_id=None):
    """Answer the open pending choice (the first option unless ``option_id`` is given), then settle."""
    choice = engine.state.pending_choice
    assert choice is not None, "expected an open choice"
    engine.rules.resolve_choice(str(option_id if option_id is not None else choice["options"][0]["id"]))
    engine.resolve_until_stable()


# --- Crown of Gondor ----------------------------------------------------------------------------------------


_CROWN_TEXT = (
    "Equipped creature gets +1/+1 for each creature you control.\n"
    "When a legendary creature you control enters, if there is no monarch, you become the monarch.\n"
    "Equip {4}. This ability costs {3} less to activate if you're the monarch."
)


def _crown(engine):
    return _put(engine, _card("Crown of Gondor", "Legendary Artifact — Equipment", _CROWN_TEXT, "{3}"))


def test_crown_of_gondor_registered():
    assert is_registered("Crown of Gondor")


def test_crown_of_gondor_anthem_counts_creatures_you_control():
    engine = _engine()
    crown = _crown(engine)
    bear = _put(engine, _bear())
    _put(engine, _bear("Second"))
    _put(engine, _bear("Opposing"), controller="p2")
    crown.attached_to = bear.instance_id
    engine.recompute_continuous_effects()
    assert (bear.power, bear.toughness) == (4, 4)  # 2/2 + one per creature *you* control (two)


def test_crown_of_gondor_legendary_entering_makes_you_monarch_only_if_none():
    engine = _engine()
    _crown(engine)
    player = _main_phase(engine)
    legend = _to_hand(engine, _card("Legend", "Legendary Creature — Elf", "", "{1}", 1, 1))
    _cast(engine, player, legend)
    assert engine.state.monarch_id == "p1"

    engine.state.monarch_id = "p2"  # RULE 725: someone already holds the designation
    second = _to_hand(engine, _card("Second Legend", "Legendary Creature — Elf", "", "{1}", 1, 1))
    _cast(engine, player, second)
    assert engine.state.monarch_id == "p2"


def test_crown_of_gondor_nonlegendary_does_not_trigger():
    engine = _engine()
    _crown(engine)
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _bear("Plain")))
    assert engine.state.monarch_id is None


def test_crown_of_gondor_equip_costs_three_less_for_the_monarch():
    engine = _engine()
    crown = _crown(engine)
    ability = crown.activated_abilities[0]
    cost = lambda: engine._reduced_activation_mana(  # noqa: E731
        crown, ability.cost.mana, ability.cost, activating_player_id="p1")
    assert cost().converted_mana_cost == 4
    engine.state.monarch_id = "p1"
    assert cost().converted_mana_cost == 1
    engine.state.monarch_id = "p2"
    assert cost().converted_mana_cost == 4


# --- Cat Collector ------------------------------------------------------------------------------------------


_CAT_COLLECTOR_TEXT = (
    "When this creature enters, create a Food token. (It's an artifact with \"{2}, {T}, Sacrifice this token: "
    "You gain 3 life.\")\nWhenever you gain life for the first time during each of your turns, create a 1/1 "
    "white Cat creature token."
)


def _tokens(engine, name, controller="p1"):
    return [o for o in engine.state.permanents_controlled_by(controller) if o.is_token and o.name == name]


def test_cat_collector_makes_food_on_entering_and_cat_on_first_life_gain_each_turn():
    engine = _engine()
    player = _main_phase(engine)
    collector = _to_hand(engine, _card("Cat Collector", "Creature — Human Citizen", _CAT_COLLECTOR_TEXT,
                                       "{2}{W}", 2, 2))
    _cast(engine, player, collector)
    assert len(_tokens(engine, "Food")) == 1
    assert _tokens(engine, "Cat") == []

    engine.rules.gain_life(player, 3)
    engine.resolve_until_stable()
    cats = _tokens(engine, "Cat")
    assert len(cats) == 1
    assert (cats[0].power, cats[0].toughness) == (1, 1) and "W" in cats[0].colors

    engine.rules.gain_life(player, 3)  # second gain the same turn: no new Cat
    engine.resolve_until_stable()
    assert len(_tokens(engine, "Cat")) == 1


def test_cat_collector_ignores_life_gained_on_an_opponents_turn():
    engine = _engine()
    player = _main_phase(engine)
    _put(engine, _card("Cat Collector", "Creature — Human Citizen", _CAT_COLLECTOR_TEXT, "{2}{W}", 2, 2))
    while engine.state.active_player.id == "p1":
        engine.advance_step()
    engine.rules.gain_life(player, 2)
    engine.resolve_until_stable()
    assert _tokens(engine, "Cat") == []


# --- Blast-Furnace Hellkite and Champion of Lambholt (combat-scoped statics) ------------------------------


def _advance_to(engine, step):
    while engine.state.current_step != step:
        engine.advance_step()


def _keywords(obj):
    from mtg_analyzer.game import combat

    return combat._obj_keywords(obj)


def test_blast_furnace_hellkite_gives_double_strike_to_creatures_attacking_its_controllers_opponents():
    engine = _engine()
    _put(engine, _card("Blast-Furnace Hellkite", "Creature — Dragon",
                       "Creatures attacking your opponents have double strike.", "{7}{R}{R}", 6, 6))
    ally = _put(engine, _bear("Ally"))
    engine.recompute_continuous_effects()
    assert "double_strike" not in _keywords(ally)  # not attacking yet
    engine.start()
    _advance_to(engine, "declare_attackers")
    engine.declare_attackers(engine.state.player_by_id("p1"), [ally])
    engine.recompute_continuous_effects()
    assert "double_strike" in _keywords(ally)


def test_blast_furnace_hellkite_ignores_creatures_attacking_its_controller():
    engine = _engine()
    _put(engine, _card("Blast-Furnace Hellkite", "Creature — Dragon",
                       "Creatures attacking your opponents have double strike.", "{7}{R}{R}", 6, 6))
    raider = _put(engine, _bear("Raider"), controller="p2")
    engine.start()
    while engine.state.active_player.id != "p2" or engine.state.current_step != "declare_attackers":
        engine.advance_step()
    engine.declare_attackers(engine.state.player_by_id("p2"), [raider])
    engine.recompute_continuous_effects()
    assert "double_strike" not in _keywords(raider)  # it attacks the Hellkite's controller


def _champion(engine):
    return _put(engine, _card(
        "Champion of Lambholt", "Creature — Human Warrior",
        "Creatures with power less than this creature's power can't block creatures you control.\n"
        "Whenever another creature you control enters, put a +1/+1 counter on this creature.",
        "{1}{G}{G}", 1, 1))


def _try_block(engine, blocker, attacker):
    try:
        engine.declare_blockers(engine.state.player_by_id("p2"), [{"blocker": blocker, "attacker": attacker}])
    except ValueError:
        return False
    return True


def test_champion_of_lambholt_weaker_creatures_cannot_block_and_threshold_grows_with_counters():
    engine = _engine()
    champion = _champion(engine)
    attacker = _put(engine, _bear("Attacker"))
    weak = _put(engine, _bear("Weak", 0, 4), controller="p2")
    peer = _put(engine, _bear("Peer", 1, 4), controller="p2")
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _bear("Newcomer")))  # another creature enters: +1/+1 counter
    engine.recompute_continuous_effects()
    assert champion.counters.get("+1/+1") == 1 and champion.power == 2

    _advance_to(engine, "declare_attackers")
    engine.declare_attackers(player, [attacker])
    engine.advance_step()  # declare blockers
    assert not _try_block(engine, weak, attacker)  # power 0 < 2
    assert not _try_block(engine, peer, attacker)  # power 1 < 2: the threshold followed the counter


def test_champion_of_lambholt_equal_power_creature_can_still_block():
    engine = _engine()
    _champion(engine)
    attacker = _put(engine, _bear("Attacker"))
    equal = _put(engine, _bear("Equal", 1, 4), controller="p2")
    weak = _put(engine, _bear("Weak", 0, 4), controller="p2")
    engine.recompute_continuous_effects()
    engine.start()
    _advance_to(engine, "declare_attackers")
    engine.declare_attackers(engine.state.player_by_id("p1"), [attacker])
    engine.advance_step()
    assert not _try_block(engine, weak, attacker)
    assert _try_block(engine, equal, attacker)  # power 1 is not less than the Champion's 1


# --- Black Sun's Twilight -----------------------------------------------------------------------------------


_BLACK_SUN_TEXT = (
    "Up to one target creature gets -X/-X until end of turn. If X is 5 or more, return a creature card with "
    "mana value X or less from your graveyard to the battlefield tapped."
)


def _black_sun(engine):
    return _to_hand(engine, _card("Black Sun's Twilight", "Instant", _BLACK_SUN_TEXT, "{X}{B}"))


def test_black_sun_s_twilight_small_x_only_shrinks_the_target():
    engine = _engine()
    victim = _put(engine, _bear("Victim", 4, 4), controller="p2")
    corpse = _to_graveyard(engine, _card("Corpse", "Creature — Zombie", "", "{2}", 2, 2))
    player = _main_phase(engine)
    _cast(engine, player, _black_sun(engine), targets=[victim], x=3)
    engine.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (1, 1)  # -3/-3 until end of turn
    assert corpse.zone == Zone.GRAVEYARD  # X < 5: no reanimation


def test_black_sun_s_twilight_big_x_reanimates_tapped_creature_within_mana_value():
    engine = _engine()
    victim = _put(engine, _bear("Victim", 3, 3), controller="p2")
    fits = _to_graveyard(engine, _card("Fits", "Creature — Zombie", "", "{4}{B}", 3, 3))
    too_big = _to_graveyard(engine, _card("Too Big", "Creature — Horror", "", "{5}{B}", 6, 6))
    player = _main_phase(engine)
    _cast(engine, player, _black_sun(engine), targets=[victim], x=5)
    assert [o["name"] for o in engine.state.pending_choice["eligible"]] == ["Fits"]  # mana value 6 > X is not offered
    _answer(engine)
    assert victim.zone == Zone.GRAVEYARD  # -5/-5
    assert fits.zone == Zone.BATTLEFIELD and fits.tapped
    assert too_big.zone == Zone.GRAVEYARD  # mana value 6 > X


def test_black_sun_s_twilight_may_choose_no_target():
    engine = _engine()
    bystander = _put(engine, _bear("Bystander", 2, 2), controller="p2")
    player = _main_phase(engine)
    _cast(engine, player, _black_sun(engine), x=2)
    engine.recompute_continuous_effects()
    assert (bystander.power, bystander.toughness) == (2, 2)


# --- Blanchwood Prowler -------------------------------------------------------------------------------------


_PROWLER_TEXT = (
    "When this creature enters, mill three cards. You may put a land card from among the cards milled this way "
    "into your hand. If you don't, put a +1/+1 counter on this creature. (To mill a card, put the top card of "
    "your library into your graveyard.)"
)


def _prowler(engine):
    return _to_hand(engine, _card("Blanchwood Prowler", "Creature — Elemental", _PROWLER_TEXT, "{1}{G}", 2, 2))


def _forest(name="Forest"):
    return _card(name, "Basic Land — Forest", "", "{0}", is_land=True)


def test_blanchwood_prowler_takes_a_milled_land_into_hand_and_skips_the_counter():
    engine = _engine()
    player = _main_phase(engine)
    top = _stack_library(engine, [_bear("A"), _forest("Milled Forest"), _bear("B")])
    prowler = _prowler(engine)
    _cast(engine, player, prowler)
    labels = [o["label"] for o in engine.state.pending_choice["options"]]
    assert any("Milled Forest" in label for label in labels), labels
    assert not any("Bear" in label or label in ("A", "B") for label in labels), labels  # only the land is offered
    _answer(engine, next(o["id"] for o in engine.state.pending_choice["options"] if "Milled Forest" in o["label"]))
    assert top[1].zone == Zone.HAND and top[1] in player.hand
    assert top[0].zone == Zone.GRAVEYARD and top[2].zone == Zone.GRAVEYARD
    assert prowler.counters.get("+1/+1", 0) == 0


def test_blanchwood_prowler_gets_a_counter_when_the_land_is_declined():
    engine = _engine()
    player = _main_phase(engine)
    top = _stack_library(engine, [_forest("Declined"), _bear("A"), _bear("B")])
    prowler = _prowler(engine)
    _cast(engine, player, prowler)
    assert engine.state.pending_choice is not None
    engine.rules.resolve_choice(None)  # decline the "may"
    engine.resolve_until_stable()
    assert top[0].zone == Zone.GRAVEYARD
    assert prowler.counters.get("+1/+1") == 1


def test_blanchwood_prowler_gets_a_counter_when_no_land_is_milled():
    engine = _engine()
    player = _main_phase(engine)
    top = _stack_library(engine, [_bear("A"), _bear("B"), _bear("C")])
    prowler = _prowler(engine)
    _cast(engine, player, prowler)
    assert engine.state.pending_choice is None
    assert all(o.zone == Zone.GRAVEYARD for o in top)
    assert prowler.counters.get("+1/+1") == 1


# --- Chainer, Nightmare Adept -------------------------------------------------------------------------------


_CHAINER_TEXT = (
    "Discard a card: You may cast a creature spell from your graveyard this turn. Activate only once each turn.\n"
    "Whenever a nontoken creature you control enters, if you didn't cast it from your hand, it gains haste until "
    "your next turn."
)


def _chainer(engine):
    return _put(engine, _card("Chainer, Nightmare Adept", "Legendary Creature — Human Minion", _CHAINER_TEXT,
                              "{2}{B}{R}", 3, 2))


def test_chainer_discard_lets_you_cast_a_creature_from_the_graveyard_once_per_turn():
    engine = _engine()
    chainer = _chainer(engine)
    player = _main_phase(engine)
    corpse = _to_graveyard(engine, _bear("Corpse", 2, 2))
    fodder, fodder2 = _to_hand(engine, _bear("Fodder")), _to_hand(engine, _bear("Fodder Two"))
    assert not engine.can_cast(player, corpse)  # no permission yet

    engine.activate_ability(player, chainer, 0, discard_choices=[fodder.instance_id])
    engine.resolve_until_stable()
    assert fodder.zone == Zone.GRAVEYARD  # the cost
    assert engine.can_cast(player, corpse)

    ability = chainer.activated_abilities[0]
    assert not engine.can_activate(player, chainer, ability, discard_choices=[fodder2.instance_id])  # once each turn
    assert fodder2 in player.hand


def test_chainer_gives_haste_to_nontoken_creatures_not_cast_from_hand():
    engine = _engine()
    chainer = _chainer(engine)
    player = _main_phase(engine)
    corpse = _to_graveyard(engine, _bear("Corpse", 2, 2))
    fodder = _to_hand(engine, _bear("Fodder"))
    engine.activate_ability(player, chainer, 0, discard_choices=[fodder.instance_id])
    engine.resolve_until_stable()
    _cast(engine, player, corpse)  # cast from the graveyard
    engine.recompute_continuous_effects()
    assert corpse.zone == Zone.BATTLEFIELD
    assert "haste" in _keywords(corpse)


def test_chainer_gives_no_haste_to_a_creature_cast_from_hand():
    engine = _engine()
    _chainer(engine)
    player = _main_phase(engine)
    from_hand = _to_hand(engine, _bear("From Hand"))
    _cast(engine, player, from_hand)
    engine.recompute_continuous_effects()
    assert from_hand.zone == Zone.BATTLEFIELD
    assert "haste" not in _keywords(from_hand)


# --- Cleaver Skaab ------------------------------------------------------------------------------------------


_SKAAB_TEXT = "{3}, {T}, Sacrifice another Zombie: Create two tokens that are copies of the sacrificed creature."


def _skaab(engine):
    return _put(engine, _card("Cleaver Skaab", "Creature — Zombie Horror", _SKAAB_TEXT, "{3}{U}", 4, 3))


def test_cleaver_skaab_sacrifices_another_zombie_and_makes_two_copies_of_it():
    engine = _engine()
    skaab = _skaab(engine)
    victim = _put(engine, _card("Rotting Zombie", "Creature — Zombie", "", "{1}{B}", 3, 1))
    bystander = _put(engine, _bear("Bystander"))
    player = _main_phase(engine)
    engine.activate_ability(player, skaab, 0, sacrifice_choice=victim.instance_id)
    engine.resolve_until_stable()
    assert victim.zone == Zone.GRAVEYARD and skaab.tapped
    copies = _tokens(engine, "Rotting Zombie")
    assert len(copies) == 2
    assert all((c.power, c.toughness) == (3, 1) and "zombie" in c.card.type_line.lower() for c in copies)
    assert bystander.zone == Zone.BATTLEFIELD


def test_cleaver_skaab_cannot_sacrifice_itself_or_a_non_zombie():
    engine = _engine()
    skaab = _skaab(engine)
    bear = _put(engine, _bear("Bystander"))
    player = _main_phase(engine)
    ability = skaab.activated_abilities[0]
    assert not engine.can_activate(player, skaab, ability, sacrifice_choice=skaab.instance_id)
    assert not engine.can_activate(player, skaab, ability, sacrifice_choice=bear.instance_id)


def test_cleaver_skaab_copies_a_token_zombie_even_though_the_token_ceases_to_exist():
    engine = _engine()
    skaab = _skaab(engine)
    player = _main_phase(engine)
    token = engine.rules.create_token(
        "p1", _card("Zombie", "Token Creature — Zombie", "", "{0}", 2, 2), 1)[0]
    engine.activate_ability(player, skaab, 0, sacrifice_choice=token.instance_id)
    engine.resolve_until_stable()
    zombies = [o for o in engine.state.permanents_controlled_by("p1") if o.is_token and o.name == "Zombie"]
    assert len(zombies) == 2 and token not in zombies


# --- Cool but Rude ------------------------------------------------------------------------------------------


_COOL_BUT_RUDE_TEXT = (
    "(Gain the next level as a sorcery to add its ability.)\n"
    "Whenever you attack, you may discard a card. If you do, draw a card.\n"
    "{1}{R}: Level 2\n"
    "Whenever you discard a card, this Class deals 2 damage to each opponent.\n"
    "{1}{R}: Level 3\n"
    "When this Class becomes level 3, search your library for a card, put it into your hand, shuffle, then "
    "discard a card at random."
)


def _class(engine):
    cls = _put(engine, _card("Cool but Rude", "Enchantment — Class", _COOL_BUT_RUDE_TEXT, "{1}{R}"))
    cls.counters["class_level"] = 1  # RULE 716.3a: a Class enters at level 1
    return cls


def test_cool_but_rude_discard_damage_only_from_level_two():
    engine = _engine()
    cls = _class(engine)
    player = _main_phase(engine)
    opponent = engine.state.player_by_id("p2")
    for card_name in ("First", "Second"):
        _to_hand(engine, _bear(card_name))
    engine.rules.discard(player, 1)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        _answer(engine)
    assert opponent.life == 20  # level 1: no damage

    engine.activate_ability(player, cls, 0)  # {1}{R}: Level 2
    engine.resolve_until_stable()
    assert cls.counters["class_level"] == 2
    engine.rules.discard(player, 1)
    engine.resolve_until_stable()
    if engine.state.pending_choice:
        _answer(engine)
    assert opponent.life == 18  # "Whenever you discard a card, this Class deals 2 damage to each opponent."


def test_cool_but_rude_level_three_tutors_then_discards_at_random():
    engine = _engine()
    cls = _class(engine)
    player = _main_phase(engine)
    cls.counters["class_level"] = 2
    prize = _stack_library(engine, [_card("Prize", "Sorcery", "", "{1}")])[0]
    hand_before = len(player.hand)
    engine.activate_ability(player, cls, 1)  # {1}{R}: Level 3
    engine.resolve_until_stable()
    if engine.state.pending_choice and engine.state.pending_choice.get("kind") == "search":
        _answer(engine, prize.instance_id)
    assert cls.counters["class_level"] == 3
    # One card tutored in, one discarded at random: hand size unchanged, and exactly one card went to the yard.
    assert len(player.hand) == hand_before
    assert prize.zone == Zone.GRAVEYARD  # the only card in hand is the one the random discard picks


# --- Cemetery Desecrator ------------------------------------------------------------------------------------


_DESECRATOR_TEXT = (
    "Menace\nWhen this creature enters or dies, exile another card from a graveyard. When you do, choose one —\n"
    "• Remove X counters from target permanent, where X is the mana value of the exiled card.\n"
    "• Target creature an opponent controls gets -X/-X until end of turn, where X is the mana value of the "
    "exiled card."
)


def _desecrator_card():
    return _card("Cemetery Desecrator", "Creature — Zombie", _DESECRATOR_TEXT, "{4}{B}{B}", 4, 4)


def _choose_mode_and_target(engine, mode_id, target):
    """Answer the reflexive ability's mode choice, then its target choice."""
    assert engine.state.pending_choice["kind"] == "trigger_mode"
    engine.rules.resolve_choice(str(mode_id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice["kind"] == "trigger_target"
    engine.rules.resolve_choice(str(target.instance_id))
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None


def test_cemetery_desecrator_exiles_a_graveyard_card_and_shrinks_by_its_mana_value():
    engine = _engine()
    victim = _put(engine, _bear("Victim", 4, 4), controller="p2")
    fodder = _to_graveyard(engine, _card("Fodder", "Creature — Elf", "", "{2}{G}", 2, 2), "p2")
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _desecrator_card()))
    assert fodder.zone == Zone.EXILE  # the only card in any graveyard
    _choose_mode_and_target(engine, 1, victim)  # "-X/-X", X = 3
    engine.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (1, 1)


def test_cemetery_desecrator_removes_x_counters_from_the_target_permanent():
    engine = _engine()
    ally = _put(engine, _bear("Counter Holder", 2, 2))
    ally.counters["+1/+1"] = 3
    _to_graveyard(engine, _card("Two Drop", "Sorcery", "", "{1}{R}"), "p2")
    player = _main_phase(engine)
    _cast(engine, player, _to_hand(engine, _desecrator_card()))
    _choose_mode_and_target(engine, 0, ally)  # "Remove X counters", X = 2
    assert ally.counters["+1/+1"] == 1


def test_cemetery_desecrator_on_death_exiles_another_card_never_itself():
    engine = _engine()
    desecrator = _put(engine, _desecrator_card())
    victim = _put(engine, _bear("Victim", 3, 3), controller="p2")
    _main_phase(engine)
    engine.rules.put_into_graveyard(desecrator)  # dies with nothing else in a graveyard
    engine.resolve_until_stable()
    assert engine.state.pending_choice is None and desecrator.zone == Zone.GRAVEYARD

    other = _to_graveyard(engine, _card("Other", "Creature — Elf", "", "{1}{G}", 1, 1))
    second = _put(engine, _desecrator_card())
    engine.rules.put_into_graveyard(second)
    engine.resolve_until_stable()
    # Both the dead first copy and "Other" are exile candidates now; a choice is offered, never `second` itself.
    pending = engine.state.pending_choice
    assert pending is not None
    labels = {o["label"] for o in pending["options"]}
    assert "Other" in labels and len(labels) >= 1
    assert all(int(o["id"]) != second.instance_id for o in pending["options"])
    _answer(engine, other.instance_id)
    assert other.zone == Zone.EXILE
    _choose_mode_and_target(engine, 1, victim)  # X = 2
    engine.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (1, 1)
