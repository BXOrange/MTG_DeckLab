"""PAR-284 milestone 23: "Choose target opponent(s)." then an amount about "that player" / "those opponents".

The bare announcement is a `choose_targets` (RULE 601.2c) and hands its player(s) on as a `PLAYER` referent with the
`chosen` noun; `where_x._relative_player_amount` then measures the count as the chosen player (``of: target``), summed
over every chosen player for a group (``each_target``, RULE 109.5). Curious Herd, Call the Coppercoats and Officious
Interrogation run on a real engine.
"""
from __future__ import annotations

import pytest

from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle.gate import parse_oracle
from mtg_analyzer.parser.oracle.segmenter import parse_effect_body
from tests.support.deck_batch import answer, card, filler, game

HERD_BODY = "choose target opponent. you create x 3/3 green beast creature tokens, where x is the number of artifacts that player controls"


def _cast(engine, spell, targets):
    from tests.support.deck_batch import cast
    cast(engine, spell, targets=targets)


def _tokens(engine, name):
    return [o for o in engine.state.battlefield if o.is_token and name in o.card.name]


def test_a_chosen_player_amount_binds_as_the_target():
    first, bound = parse_effect_body(HERD_BODY)
    assert first.type == "choose_targets" and first.params["kinds"] == ["opponent"]
    assert bound.params["amount"]["of"] == "target" and "each_target" not in bound.params["amount"]


@pytest.mark.parametrize("name", ["Curious Herd", "Call the Coppercoats", "Officious Interrogation"])
def test_the_choose_target_family_is_modeled(name):
    from tests.support.deck_batch import CardDatabase, DB_PATH
    assert parse_oracle(CardDatabase(DB_PATH).get_card(name)).modeled


@pytest.mark.parametrize("body", [
    # a singular pronoun cannot read a group announcement, nor a plural one a single player
    "choose any number of target opponents. you create x 1/1 white human soldier creature tokens, where x is the number of creatures that player controls",
    "choose target opponent. you create x 1/1 white human soldier creature tokens, where x is the number of creatures those opponents control",
    # the player's own hand / graveyard is not a battlefield count this row reads
    "choose target opponent. you create x 1/1 white human soldier creature tokens, where x is the number of cards in their hand",
])
def test_mismatched_referents_stay_unclaimed(body):
    specs = parse_effect_body(body)
    assert specs is None or not any(s.type == "bind" and s.params["amount"].get("of") == "target" for s in specs)


def test_curious_herd_counts_the_chosen_opponents_artifacts():
    engine = game(players=3)
    herd = card(engine, "Curious Herd", zone=Zone.HAND)
    for i in range(2):
        filler(engine, f"Rock {i}", type_line="Artifact", player="p2")
    filler(engine, "Other Rock", type_line="Artifact", player="p3")  # the other opponent's artifact does not count
    _cast(engine, herd, [engine.state.player_by_id("p2")])
    assert len(_tokens(engine, "Beast")) == 2
    assert all(t.controller_id == "p1" for t in _tokens(engine, "Beast"))


def test_call_the_coppercoats_sums_every_chosen_opponent():
    engine = game(players=3)
    spell = card(engine, "Call the Coppercoats", zone=Zone.HAND)
    for owner, n in (("p2", 2), ("p3", 3)):
        for i in range(n):
            filler(engine, f"Body {owner}{i}", player=owner, power=1, toughness=1)
    filler(engine, "Mine", player="p1", power=1, toughness=1)  # the caster's own creature never counts
    _cast(engine, spell, [engine.state.player_by_id("p2"), engine.state.player_by_id("p3")])
    assert len(_tokens(engine, "Human Soldier")) == 5


def test_call_the_coppercoats_with_one_opponent_counts_only_that_opponent():
    engine = game(players=3)
    spell = card(engine, "Call the Coppercoats", zone=Zone.HAND)
    for i in range(2):
        filler(engine, f"Body p2{i}", player="p2", power=1, toughness=1)
    for i in range(3):
        filler(engine, f"Body p3{i}", player="p3", power=1, toughness=1)
    _cast(engine, spell, [engine.state.player_by_id("p3")])
    assert len(_tokens(engine, "Human Soldier")) == 3


def test_officious_interrogation_investigates_once_per_creature():
    engine = game(players=3)
    spell = card(engine, "Officious Interrogation", zone=Zone.HAND)
    for owner in ("p1", "p2", "p3"):
        filler(engine, f"Body {owner}", player=owner, power=1, toughness=1)
    _cast(engine, spell, [engine.state.player_by_id("p1"), engine.state.player_by_id("p2")])
    assert len(_tokens(engine, "Clue")) == 2


# --- cards that arrived in a named player's graveyard this turn (Cruel Calculations, Wreck Hunter) -----------------------

def test_graveyard_arrival_phrase_reads_one_origin_for_one_player():
    from mtg_analyzer.parser.oracle.catalogue.history_phrase import parse_graveyard_arrival_count
    who, trigger = parse_graveyard_arrival_count(
        "the number of cards that were put into target player's graveyard from their library this turn")
    assert who == "target player" and trigger["filter"] == {"from_zone": "library"}
    who, trigger = parse_graveyard_arrival_count(
        "nonland card in that player's graveyard that was put there from the battlefield this turn")
    assert who == "that player" and trigger["filter"] == {"from_zone": "battlefield"}
    assert trigger["condition"]["filter"] == {"without_card_type": "land"}
    # an origin the log does not pin down, or another owner word, is not read
    assert parse_graveyard_arrival_count("cards put into target player's graveyard from anywhere this turn") is None
    assert parse_graveyard_arrival_count("cards that were put into your graveyard from your library this turn") is None


def test_that_players_graveyard_needs_an_earlier_choice():
    assert parse_effect_body("you create a tapped powerstone token for each nonland card in that player's graveyard "
                             "that was put there from the battlefield this turn") is None


def test_cruel_calculations_draws_for_the_targets_milled_cards_only():
    engine = game(players=3)
    spell = card(engine, "Cruel Calculations", zone=Zone.HAND)
    p1, p2, p3 = (engine.state.player_by_id(pid) for pid in ("p1", "p2", "p3"))
    engine.rules.mill(p2, 3)
    engine.rules.mill(p3, 2)  # another player's milled cards do not count
    hand_before = len(p1.hand)  # the spell itself leaves the hand when it is cast
    _cast(engine, spell, [p2])
    assert len(p1.hand) - hand_before == 3 - 1


def test_wreck_hunter_counts_only_nonland_cards_from_the_battlefield():
    from tests.support.deck_batch import answer, cast
    engine = game(players=3)
    hunter = card(engine, "Wreck Hunter", zone=Zone.HAND)
    p2 = engine.state.player_by_id("p2")
    dying = [filler(engine, f"Dies {i}", player="p2", power=1, toughness=1) for i in range(2)]
    land = filler(engine, "Doomed Land", type_line="Land", player="p2")
    other = filler(engine, "Elsewhere", player="p3", power=1, toughness=1)
    engine.resolve_until_stable()  # the arrival check records each object's zone before it moves (RULE 603.6c)
    for obj in (*dying, land, other):
        engine.rules.destroy(obj)
    engine.rules.mill(p2, 2)  # a mill is not "put there from the battlefield"
    engine.resolve_until_stable()
    cast(engine, hunter)
    answer(engine, lambda choice: "p2")
    engine.resolve_until_stable()
    assert len(_tokens(engine, "Powerstone")) == 2


def test_hoard_hauler_makes_a_treasure_per_artifact_the_damaged_player_controls():
    from tests.support.deck_batch import answer
    engine = game(players=3)
    hauler = card(engine, "Hoard Hauler")
    for i in range(2):
        filler(engine, f"Rock {i}", type_line="Artifact", player="p2")
    filler(engine, "Other Rock", type_line="Artifact", player="p3")  # not the damaged player's
    filler(engine, "My Rock", type_line="Artifact", player="p1")
    engine.resolve_until_stable()
    engine.rules.deal_combat_damage([(engine.state.player_by_id("p2"), 3, hauler)])
    engine.resolve_until_stable()
    answer(engine)
    assert len(_tokens(engine, "Treasure")) == 2


def _soulcaller_options(second_defender_index):
    """Declare Custodi Soulcaller (and a Bear) and return the graveyard cards its trigger offers."""
    engine = game(players=3)
    soulcaller = card(engine, "Custodi Soulcaller")
    bear = filler(engine, "Bear", power=2, toughness=2)
    for mv in (1, 2, 3):
        filler(engine, f"G{mv}", player="p1", mv=mv, power=1, toughness=1, zone=Zone.GRAVEYARD)
    state = engine.state
    state.current_phase, state.current_step = "combat", "declare_attackers"
    defenders = engine.legal_defenders_for(state.active_player)
    engine.declare_attackers(state.active_player, [
        {"attacker": soulcaller, "defender": defenders[0]},
        {"attacker": bear, "defender": defenders[second_defender_index]},
    ])
    engine._fire_player_attacked_events()
    engine.resolve_until_stable()
    return sorted(o["label"] for o in engine.state.pending_choice["options"])


def test_custodi_soulcaller_counts_the_players_attacked_this_combat():
    assert _soulcaller_options(1) == ["G1", "G2"]  # two different players attacked: mana value 2 or less
    assert _soulcaller_options(0) == ["G1"]  # both attackers at one player: mana value 1 or less (RULE 506.1)


# --- the greatest / total value across the battlefield and the graveyard (Skanos, Ambitious Dragonborn) -------------------

def test_two_place_aggregate_is_the_larger_half_for_greatest_and_the_sum_for_total():
    from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_amount_phrase
    greatest = parse_amount_phrase("the greatest power among creatures you control and creature cards in your graveyard")
    assert greatest["combine"] == "max" and [t["zone"] for t in greatest["terms"]] == ["battlefield", "graveyard"]
    total = parse_amount_phrase("the total power of creatures you control and creature cards in your graveyard")
    assert "combine" not in total
    # one half in the wrong place is not read
    assert parse_amount_phrase("the greatest power among creatures you control and creature cards in exile") is None


def test_skanos_pumps_by_the_greatest_other_dragon_on_the_battlefield_or_in_the_graveyard():
    from tests.support.deck_batch import attack
    engine = game(players=2)
    skanos = card(engine, "Skanos Dragonheart")
    skanos.summoning_sick = False
    filler(engine, "Small Dragon", type_line="Creature — Dragon", power=3, toughness=3)
    filler(engine, "Dead Dragon", type_line="Creature — Dragon", power=6, toughness=6, zone=Zone.GRAVEYARD)
    filler(engine, "Dead Bear", type_line="Creature — Bear", power=9, toughness=9, zone=Zone.GRAVEYARD)  # not a Dragon
    base = skanos.power
    attack(engine, [skanos])
    engine.recompute_continuous_effects()
    assert skanos.power - base == 6 and skanos.toughness - skanos.card.toughness == 6


def test_ambitious_dragonborn_enters_with_counters_for_the_greatest_power():
    engine = game(players=2)
    dragonborn = card(engine, "Ambitious Dragonborn", zone=Zone.HAND)
    filler(engine, "Board Bear", power=4, toughness=4)
    filler(engine, "Dead Giant", type_line="Creature — Giant", power=6, toughness=6, zone=Zone.GRAVEYARD)
    from tests.support.deck_batch import cast
    cast(engine, dragonborn)
    assert dragonborn.zone == Zone.BATTLEFIELD and dragonborn.counters.get("+1/+1") == 6


def test_zegana_enters_with_counters_for_the_greatest_power_among_other_creatures_and_draws_for_its_power():
    # a side gain of the enters-with aggregate: no graveyard half, "other creatures you control" only
    from tests.support.deck_batch import answer, cast
    engine = game(players=2)
    zegana = card(engine, "Prime Speaker Zegana", zone=Zone.HAND)
    filler(engine, "Board Bear", power=4, toughness=4)
    filler(engine, "Small Bear", power=1, toughness=1)
    player = engine.state.player_by_id("p1")
    hand_before = len(player.hand)
    cast(engine, zegana)
    answer(engine)
    engine.resolve_until_stable()
    assert zegana.counters.get("+1/+1") == 4
    # the spell left the hand when cast; the enters trigger drew cards equal to Zegana's power (1 + 4 counters)
    assert zegana.power == 5 and len(player.hand) - hand_before == 5 - 1


# --- "You don't lose the game for having 0 or less life" (Lich's Tomb, Transcendence) ---------------------------------

def test_the_life_exemption_is_the_life_only_cant_lose_static():
    from mtg_analyzer.parser.oracle.gate import parse_oracle
    from tests.test_par284_this_way_windows import _card
    result = parse_oracle(_card("Probe", "Artifact", "You don't lose the game for having 0 or less life."))
    assert result.modeled
    [spec] = [s for s in result.specs if s.ability_kind == "static"]
    assert [(e.type, e.params) for e in spec.effects] == [("cant_lose_game", {"reason": "life"})]
    # the conditional form keeps its gate: the exemption applies only while the condition holds
    [gated] = parse_oracle(_card("Probe", "Artifact", "As long as ~ is attached to a creature, you don't lose the game for having 0 or less life.")).specs
    assert gated.effects[0].params["active_if"] == {"kind": "source_attached"}


def test_lichs_tomb_survives_zero_life_but_not_an_empty_library_and_sacrifices_per_life_lost():
    engine = game(players=2)
    player = engine.state.player_by_id("p1")
    tomb = card(engine, "Lich's Tomb")
    extras = [filler(engine, f"Thing {i}", type_line="Artifact") for i in range(3)]
    engine.resolve_until_stable()
    player.life = 2
    engine.rules.lose_life(player, 2)
    engine.resolve_until_stable()
    # sacrifice the other permanents (sacrificing the Tomb itself would end the exemption before the SBA check)
    answer(engine, lambda choice: next(str(o["id"]) for o in choice["options"] if o["label"] != "Lich's Tomb"), limit=24)
    engine.resolve_until_stable()
    assert player.life == 0 and not player.has_lost  # RULE 704.5a is skipped
    assert sum(1 for o in (tomb, *extras) if o.zone == Zone.BATTLEFIELD) == 4 - 2  # a permanent sacrificed per life lost


def test_the_life_exemption_does_not_stop_other_losses():
    engine = game(players=2, library=0)
    player = engine.state.player_by_id("p1")
    card(engine, "Transcendence")
    engine.resolve_until_stable()
    engine.rules.draw_cards(player, 1) if hasattr(engine.rules, "draw_cards") else engine.rules.draw(player, 1)
    engine.resolve_until_stable()
    assert player.has_lost  # RULE 704.5b: drawing from an empty library still loses


def test_transcendence_gains_two_life_per_life_lost_and_loses_at_twenty():
    engine = game(players=2)
    player = engine.state.player_by_id("p1")
    player.life = 5  # below 20 when it enters, or its own "20 or more life" trigger ends the game at once
    card(engine, "Transcendence")
    engine.resolve_until_stable()
    engine.rules.lose_life(player, 3)
    engine.resolve_until_stable()
    assert player.life == 5 - 3 + 2 * 3 and not player.has_lost
    player.life = 19
    engine.rules.gain_life(player, 1)
    engine.resolve_until_stable()
    assert player.has_lost  # "When you have 20 or more life, you lose the game."


# --- "<things> you control and each <things> card in your graveyard" (Moon-Vigil Adherents, Desmond Miles, Gargantuan Leech)

def test_battlefield_and_graveyard_phrase_is_the_sum_of_both_halves():
    from mtg_analyzer.parser.oracle.catalogue.count_phrase import parse_count_phrase
    selector = parse_count_phrase("creature you control and each creature card in your graveyard")
    assert [t["zone"] for t in selector["terms"]] == ["battlefield", "graveyard"] and "combine" not in selector
    # both places must be named, in that order: anything else is not read
    assert parse_count_phrase("creature you control and each creature card in exile") is None
    assert parse_count_phrase("creature card in your graveyard and each creature you control") is None


def test_moon_vigil_adherents_counts_creatures_and_creature_cards_in_the_graveyard():
    engine = game(players=2)
    adherents = card(engine, "Moon-Vigil Adherents")
    filler(engine, "Board Bear", power=1, toughness=1)
    for i in range(3):
        filler(engine, f"Dead {i}", power=1, toughness=1, zone=Zone.GRAVEYARD)
    filler(engine, "Dead Land", type_line="Land", zone=Zone.GRAVEYARD)  # not a creature card
    engine.recompute_continuous_effects()
    # itself and the Bear on the battlefield (2) plus three creature cards in the graveyard
    assert adherents.power == adherents.card.power + 5


def test_desmond_miles_counts_other_assassins_on_the_battlefield_and_in_the_graveyard():
    engine = game(players=2)
    desmond = card(engine, "Desmond Miles")
    filler(engine, "Live Assassin", type_line="Creature — Human Assassin", power=1, toughness=1)
    filler(engine, "Dead Assassin", type_line="Creature — Human Assassin", power=1, toughness=1, zone=Zone.GRAVEYARD)
    filler(engine, "Dead Assassin 2", type_line="Creature — Human Assassin", power=1, toughness=1, zone=Zone.GRAVEYARD)
    engine.recompute_continuous_effects()
    assert desmond.power == desmond.card.power + 3  # not itself


def test_gargantuan_leech_costs_one_less_per_cave_on_the_battlefield_or_in_the_graveyard():
    def attempt(caves_in_play, caves_in_graveyard):
        engine = game(players=2)
        leech = card(engine, "Gargantuan Leech", zone=Zone.HAND)
        for i in range(caves_in_play):
            filler(engine, f"Cave {i}", type_line="Land — Cave")
        for i in range(caves_in_graveyard):
            filler(engine, f"Gone Cave {i}", type_line="Land — Cave", zone=Zone.GRAVEYARD)
        filler(engine, "Plains", type_line="Basic Land — Plains", zone=Zone.GRAVEYARD)  # not a Cave
        player = engine.state.player_by_id("p1")
        engine.state.current_phase, engine.state.current_step = "main", "main1"
        player.mana_pool.add_many({"B": 1, "C": 5})  # {7}{B} less two = {5}{B}
        try:
            engine.cast_spell(player, leech)
        except ValueError:
            return False
        engine.resolve_until_stable()
        return leech.zone == Zone.BATTLEFIELD

    assert attempt(1, 1)  # one Cave in play and one in the graveyard: {1} less each
    assert not attempt(1, 0)  # only one cheaper: {6}{B} is not payable with {5}{B}
    assert not attempt(0, 0)


@pytest.mark.parametrize("phrase, expected", [
    ("twice the number of artifacts that player controls", {"multiply": 2}),
    ("the number of artifacts that player controls minus 1", {"minus": 1, "minimum": 0}),
])
def test_chosen_player_count_retains_arithmetic(phrase, expected):
    specs = parse_effect_body(
        "choose target opponent. you create x 3/3 green beast creature tokens, where x is " + phrase)
    assert specs is not None
    amount = specs[-1].params["amount"]
    assert all(amount[key] == value for key, value in expected.items())
