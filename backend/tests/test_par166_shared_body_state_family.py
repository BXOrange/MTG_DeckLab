"""PAR-166 shared body/state grammar residue: each family is checked at the parse level (including a near-miss that
must stay unclaimed) and executed against a real engine.

Families
  * ``where X is the amount of life you gained/lost this turn`` -- the turn-total count selector as an X source;
  * a standing ``maximum hand size is reduced/increased by N`` (RULE 402.2) -> ``hand_size_modifier``;
  * a standing colour statement (RULE 105.2 / 613.4b) -> layer-5 ``color_change`` for self / attached / group;
  * ``you've cast another spell this turn`` (the cast being asked about never counts itself);
  * ``put a loyalty counter on ~`` (RULE 306.5b) -- a planeswalker's own loyalty;
  * ``target opponent chooses a <type> they control. Destroy/Exile that <type>`` -- an edict that is not a sacrifice.
"""

from __future__ import annotations

from mtg_analyzer.game import continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.gate import MODELED, UNMODELED, parse_oracle


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _card(name, type_line, text, **kw):
    kw.setdefault("converted_mana_cost", 0)
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature,
        power=kw.pop("power", 2 if creature else None), toughness=kw.pop("toughness", 2 if creature else None),
        is_sorcery="Sorcery" in type_line, is_instant="Instant" in type_line, **kw,
    )


def _bf(eng, card, controller="p1"):
    obj = GameObject(card, owner_id=controller, zone=Zone.BATTLEFIELD)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _cast(eng, card, targets=None, controller="p1"):
    player = eng.state.player_by_id(controller)
    spell = GameObject(card, owner_id=controller, zone=Zone.HAND)
    bind_from_catalogue(spell)
    player.add_to_zone(spell, Zone.HAND)
    eng.cast_spell(player, spell, targets=targets or [])
    eng.resolve_until_stable()
    return spell


# --- where X is the amount of life you gained this turn ------------------------------------------------------------


def test_life_gained_x_parses_for_loss_pump_and_tokens():
    for text in (
        "Target opponent loses X life, where X is the amount of life you gained this turn.",
        "Target creature gets -X/-X until end of turn, where X is the amount of life you gained this turn.",
        "Create X 2/2 white Soldier creature tokens, where X is the amount of life you gained this turn.",
    ):
        assert parse_oracle(_card("T", "Sorcery", text)).coverage == MODELED, text


def test_life_gained_x_near_miss_stays_unclaimed():
    # "the amount of life you gained last turn" is not a tracked quantity
    text = "Target opponent loses X life, where X is the amount of life you gained last turn."
    assert parse_oracle(_card("T", "Sorcery", text)).coverage == UNMODELED


def test_life_gained_x_measures_the_turn_total_at_resolution():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.rules.gain_life(p1, 3)
    eng.rules.gain_life(p1, 2)
    card = _card("Snack", "Sorcery", "Target opponent loses X life, where X is the amount of life you gained this turn.")
    _cast(eng, card, targets=[p2])
    assert p2.life == 15 and p1.life == 25


def test_life_gained_x_is_zero_without_gain_and_ignores_the_opponents_gain():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    eng.rules.gain_life(p2, 7)  # an opponent's gain is not "the life you gained"
    card = _card("Snack", "Sorcery", "Target opponent loses X life, where X is the amount of life you gained this turn.")
    _cast(eng, card, targets=[p2])
    assert p2.life == 27


def test_life_gained_x_creates_that_many_tokens():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    eng.rules.gain_life(p1, 3)
    card = _card("Recruits", "Sorcery", "Create X 2/2 white Soldier creature tokens, where X is the amount of life you gained this turn.")
    _cast(eng, card)
    soldiers = [o for o in eng.state.battlefield if o.is_token and o.controller_id == "p1"]
    assert len(soldiers) == 3


# --- maximum hand size ---------------------------------------------------------------------------------------------


def test_hand_size_modifier_parses_all_three_scopes_and_rejects_a_setter():
    for text in (
        "Your maximum hand size is reduced by 3.",
        "Each opponent's maximum hand size is reduced by 1.",
        "Your maximum hand size is increased by 1.",
    ):
        assert parse_oracle(_card("H", "Creature — Bear", text)).coverage == MODELED, text
    # an absolute setter ("is 4") is a different mechanic and must stay unclaimed here
    assert parse_oracle(_card("H", "Creature — Bear", "Your maximum hand size is 4.")).coverage == UNMODELED


def test_hand_size_modifier_applies_to_the_right_player_only():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    _bf(eng, _card("Miser", "Creature — Bear", "Each opponent's maximum hand size is reduced by 2."))
    assert continuous.hand_size_modifier_for(eng.state, p2) == -2
    assert continuous.hand_size_modifier_for(eng.state, p1) == 0
    _bf(eng, _card("Scrollkeeper", "Creature — Bear", "Your maximum hand size is increased by 1."), controller="p2")
    assert continuous.hand_size_modifier_for(eng.state, p2) == -1
    _bf(eng, _card("Eater", "Creature — Bear", "Your maximum hand size is reduced by 3."), controller="p1")
    assert continuous.hand_size_modifier_for(eng.state, p1) == -3


# --- standing colour statements ------------------------------------------------------------------------------------


def test_colour_statement_parses_self_attached_and_group_but_not_a_pronoun_subject():
    assert parse_oracle(_card("S", "Creature — Sphinx", "~ is all colors.")).coverage == MODELED
    assert parse_oracle(_card("G", "Enchantment", "All creatures are black.")).coverage == MODELED
    aura = _card("A", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +3/+1 and is black.")
    assert parse_oracle(aura).coverage == MODELED
    # a statement about a nameless pronoun is not a standing group
    assert parse_oracle(_card("N", "Enchantment", "It is black.")).coverage == UNMODELED


def test_all_colors_and_colorless_replace_the_printed_colours():
    eng = _engine()
    plain = _bf(eng, _card("Plain", "Creature — Bear", "", color_identity=["G"]), controller="p2")
    sphinx = _bf(eng, _card("Sphinx", "Creature — Sphinx", "~ is all colors.", color_identity=["U"]))
    eng.recompute_continuous_effects()
    assert set(sphinx.colors) == {"W", "U", "B", "R", "G"}
    assert set(plain.colors) == {"G"}  # negative control: only the source is recoloured
    _bf(eng, _card("Lens", "Artifact", "All permanents are colorless."))
    eng.recompute_continuous_effects()
    assert not plain.colors and not sphinx.colors


def test_group_colour_statement_recolours_the_group_and_not_other_types():
    eng = _engine()
    bear = _bf(eng, _card("Bear", "Creature — Bear", "", color_identity=["G"]), controller="p2")
    artifact = _bf(eng, _card("Rock", "Artifact", "", color_identity=["R"]), controller="p2")
    _bf(eng, _card("Hour", "Enchantment", "All creatures are black."))
    eng.recompute_continuous_effects()
    assert set(bear.colors) == {"B"}
    assert set(artifact.colors) == {"R"}


# --- "you've cast another spell this turn" -------------------------------------------------------------------------


def test_another_spell_condition_parses_on_a_self_cost_reduction():
    card = _card("Focus", "Sorcery", "This spell costs {2} less to cast if you've cast another spell this turn.\nDraw a card.",
                 mana_cost_string="{3}{U}", converted_mana_cost=4)
    assert parse_oracle(card).coverage == MODELED


def test_another_spell_never_counts_the_spell_itself():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    draw = _card("Slick", "Instant", "Draw a card. If you've cast another spell this turn, draw a card.")
    for _ in range(4):
        p1.library.append(GameObject(_card("Filler", "Creature — Bear", ""), owner_id="p1", zone=Zone.LIBRARY))
    _cast(eng, draw)
    assert len(p1.hand) == 1  # alone: only the unconditional draw
    _cast(eng, _card("Slick2", "Instant", "Draw a card. If you've cast another spell this turn, draw a card."))
    assert len(p1.hand) == 3  # a prior spell this turn: the conditional draw happens


# --- loyalty counters on the source --------------------------------------------------------------------------------


def test_loyalty_counter_on_self_parses_but_a_pronoun_referent_does_not_claim():
    walker = _card("Walker", "Legendary Planeswalker — Ral",
                   "Whenever you cast a noncreature spell, put a loyalty counter on ~.", loyalty=3)
    assert parse_oracle(walker).coverage == MODELED
    # "on it" names the previous target, not the source: must not be read as a self counter
    other = _card("Teyo", "Creature — Wizard",
                  "When ~ enters, target permanent you control gains hexproof until end of turn. "
                  "Put a loyalty counter on it if it's a planeswalker.")
    assert parse_oracle(other).coverage == UNMODELED


def test_loyalty_counter_trigger_adds_to_the_source():
    eng = _engine()
    walker = _bf(eng, _card("Walker", "Legendary Planeswalker — Ral",
                            "Whenever you cast a noncreature spell, put a loyalty counter on ~.", loyalty=3))
    walker.counters["loyalty"] = 3
    before = walker.counters.get("loyalty", 0)
    _cast(eng, _card("Spell", "Instant", "Draw a card."))
    assert walker.counters.get("loyalty", 0) == before + 1
    _cast(eng, _card("Bear", "Creature — Bear", ""))  # a creature spell: negative control
    assert walker.counters.get("loyalty", 0) == before + 1


# --- "target opponent chooses a creature they control. Destroy that creature." -------------------------------------


EDICT = "Target opponent chooses a creature they control. Destroy that creature."


def test_opponent_chooses_then_removal_parses_and_rejects_unknown_followups():
    assert parse_oracle(_card("Edict", "Sorcery", EDICT)).coverage == MODELED
    assert parse_oracle(_card("Edict2", "Sorcery", "Target opponent chooses a land they control. Destroy it.")).coverage == MODELED
    assert parse_oracle(_card("Bad", "Sorcery", "Target opponent chooses a creature they control. Tap that creature.")).coverage == UNMODELED
    # exile is a different removal verb (no `previous_subject` reader on the exile effect): stays unclaimed
    assert parse_oracle(_card("Bad2", "Sorcery", "Target opponent chooses a creature they control. Exile that creature.")).coverage == UNMODELED


def test_opponent_chooses_then_destroys_only_the_chosen_creature():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    mine = _bf(eng, _card("Mine", "Creature — Bear", ""), controller="p1")
    a = _bf(eng, _card("A", "Creature — Bear", ""), controller="p2")
    b = _bf(eng, _card("B", "Creature — Bear", ""), controller="p2")
    _cast(eng, _card("Edict", "Sorcery", EDICT), targets=[p2])
    pending = eng.state.pending_choice
    assert pending is not None and pending["player_id"] == "p2"  # the opponent chooses, not the caster
    eng.resolve_pending_choice(b.instance_id)
    assert b.zone == Zone.GRAVEYARD
    assert a.zone == Zone.BATTLEFIELD and mine.zone == Zone.BATTLEFIELD  # the unchosen and the caster's own survive


def test_opponent_chooses_then_destroys_nothing_without_a_creature_to_choose():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    mine = _bf(eng, _card("Mine", "Creature — Bear", ""), controller="p1")
    _cast(eng, _card("Edict", "Sorcery", EDICT), targets=[p2])
    assert eng.state.pending_choice is None and mine.zone == Zone.BATTLEFIELD


def test_self_cost_reduction_applies_only_after_another_spell_was_cast():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    focus_card = _card("Focus", "Sorcery", "This spell costs {2} less to cast if you've cast another spell this turn.\nDraw a card.",
                       mana_cost_string="{3}{U}", converted_mana_cost=4)
    focus = GameObject(focus_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(focus)
    p1.add_to_zone(focus, Zone.HAND)
    net, _ = continuous.self_cost_reduction_for(focus, eng.state, "p1")
    assert net == 0  # nothing cast yet this turn
    # Resolve a real draw without eliminating the caster and removing Focus.
    p1.add_to_zone(GameObject(_card("Draw filler", "Land", ""), "p1", zone=Zone.LIBRARY), Zone.LIBRARY)
    _cast(eng, _card("Other", "Instant", "Draw a card."))
    assert not p1.has_lost and focus in p1.hand
    net, _ = continuous.self_cost_reduction_for(focus, eng.state, "p1")
    assert net == 2
    # the opponent's spell is not "a spell you've cast"
    eng2 = _engine()
    p1b = eng2.state.player_by_id("p1")
    focus2 = GameObject(focus_card, owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(focus2)
    p1b.add_to_zone(focus2, Zone.HAND)
    p2b = eng2.state.player_by_id("p2")
    p2b.add_to_zone(GameObject(_card("Their draw filler", "Land", ""), "p2", zone=Zone.LIBRARY), Zone.LIBRARY)
    _cast(eng2, _card("Theirs", "Instant", "Draw a card."), controller="p2")
    assert not p2b.has_lost
    net, _ = continuous.self_cost_reduction_for(focus2, eng2.state, "p1")
    assert net == 0


def test_attached_colour_and_pump_statement_recolours_the_host_only():
    eng = _engine()
    host = _bf(eng, _card("Host", "Creature — Bear", "", color_identity=["G"]), controller="p2")
    bystander = _bf(eng, _card("Other", "Creature — Bear", "", color_identity=["G"]), controller="p2")
    aura = _bf(eng, _card("Strength", "Enchantment — Aura", "Enchant creature\nEnchanted creature gets +3/+1 and is black."))
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    assert set(host.colors) == {"B"} and host.power == 5 and host.toughness == 3
    assert set(bystander.colors) == {"G"} and bystander.power == 2


# --- "target player and each creature that player controls" (Urabrask's shape) -------------------------------------

def test_target_player_and_their_creature_group_parses_but_a_target_creature_does_not():
    assert parse_oracle(_card("Wave", "Sorcery", "Wave deals 2 damage to target player and each creature that player controls.")).coverage == MODELED
    # the announced object being a creature (not a player) is a different shape
    assert parse_oracle(_card("Bad", "Sorcery", "Bad deals 2 damage to target creature and each creature that player controls.")).coverage == UNMODELED


def test_target_player_and_their_creatures_all_take_damage_and_the_casters_do_not():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    mine = _bf(eng, _card("Mine", "Creature — Bear", "", toughness=3), controller="p1")
    theirs = _bf(eng, _card("Theirs", "Creature — Bear", "", toughness=3), controller="p2")
    _cast(eng, _card("Wave", "Sorcery", "Wave deals 2 damage to target player and each creature that player controls."), targets=[p2])
    assert p2.life == 18  # the announced player is hit as well as the group
    assert theirs.damage_marked == 2
    assert mine.damage_marked == 0 and p1.life == 20


def test_life_gained_x_shrinks_a_targeted_creature_by_the_turn_total():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    victim = _bf(eng, _card("Victim", "Creature — Bear", "", power=5, toughness=5), controller="p2")
    eng.rules.gain_life(p1, 3)
    card = _card("Thirst", "Instant", "Target creature gets -X/-X until end of turn, where X is the amount of life you gained this turn.")
    _cast(eng, card, targets=[victim])
    eng.recompute_continuous_effects()
    assert victim.power == 2 and victim.toughness == 2


# --- "<player> loses half their life, rounded up/down" (RULE 107.2 / 119.3) ------------------------------------------

_HALF_LIFE_TEXT = {
    "you": "You lose half your life, rounded up.",
    "opp": "Target opponent loses half their life, rounded up.",
}


def test_fractional_life_loss_parses_each_who_but_not_a_stray_referent():
    for text in (
        "You lose half your life, rounded up.",
        "Target opponent loses half their life, rounded down.",
        "Target player loses half their life, rounded up.",
    ):
        assert parse_oracle(_card("T", "Sorcery", text)).coverage == MODELED, text
    # "that player" under a dies trigger names no damaged / defending player: stays unclaimed
    dies = _card("T", "Creature - Zombie", "When Test Thing dies, that player loses half their life, rounded up.")
    assert parse_oracle(dies).coverage == UNMODELED
    # "each player" with no divisor fragment we know is not claimed by this row
    assert parse_oracle(_card("T", "Sorcery", "You lose half your life.")).coverage == UNMODELED


def test_you_lose_half_your_life_rounds_as_printed():
    for rounding, expected_life in (("up", 7), ("down", 8)):
        eng = _engine()
        eng.state.player_by_id("p1").life = 15
        _cast(eng, _card("Bargain", "Sorcery", f"You lose half your life, rounded {rounding}."))
        assert eng.state.player_by_id("p1").life == expected_life, rounding


def test_target_opponent_loses_half_their_life_not_the_casters():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 9, 15
    _cast(eng, _card("Tribute", "Sorcery", _HALF_LIFE_TEXT["opp"]), targets=[p2])
    assert (p1.life, p2.life) == (9, 7)


def test_blood_tribute_gains_only_when_kicked_condition_holds():
    from mtg_analyzer.config import DB_PATH
    from mtg_analyzer.services.card_database import CardDatabase

    assert parse_oracle(CardDatabase(DB_PATH).get_card("Blood Tribute")).modeled
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 10, 20
    _cast(eng, _card("Tribute", "Sorcery", "Target opponent loses half their life, rounded up. "
                     "If this spell was kicked, you gain life equal to the life lost this way."), targets=[p2])
    assert (p1.life, p2.life) == (10, 10)  # not kicked: no gain


def test_each_player_loses_a_third_measures_every_players_own_life():
    from tests.support.deck_batch import card as real_card

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 20, 9
    obj = real_card(eng, "Dire Fleet Ravager", zone=Zone.HAND)
    p1.hand[:] = [o for o in p1.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    eng.state.add_to_battlefield(obj)
    eng.state.fire_event(__import__("mtg_analyzer.models.game.game_state", fromlist=["x"]).GameEvent(
        __import__("mtg_analyzer.models.game.game_state", fromlist=["x"]).EventType.ENTERS_BATTLEFIELD,
        controller_id="p1", instance_id=obj.instance_id, object=obj.name, object_types=sorted(obj.type_words)))
    eng.resolve_until_stable()
    # a third of 20 rounded up = 7 -> 13; a third of 9 = 3 -> 6
    assert (p1.life, p2.life) == (13, 6)


def test_combat_damage_trigger_halves_the_damaged_players_life_only():
    from tests.support.deck_batch import card as real_card

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 20, 15
    virtus = real_card(eng, "Virtus the Veiled")
    eng.rules.deal_damage(p2, 2, source=virtus, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    # 15 - 2 combat damage = 13; half rounded up = 7 lost
    assert (p1.life, p2.life) == (20, 6)


def test_equipment_trigger_halves_the_damaged_player_and_ignores_a_noncombat_hit():
    from tests.support.deck_batch import card as real_card

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p2.life = 20
    spike = real_card(eng, "Quietus Spike")
    host = _bf(eng, _card("Host", "Creature - Human", ""))
    spike.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(p2, 1, source=host, combat=False)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert p2.life == 19
    eng.rules.deal_damage(p2, 1, source=host, combat=True)
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert p2.life == 9  # 18 - ceil(18 / 2)


def test_each_players_upkeep_halves_the_active_players_life_not_the_controllers():
    from tests.support.deck_batch import card as real_card, step

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 20, 15
    real_card(eng, "Havoc Festival")
    eng.state.active_player_index = 1  # p2's turn: the upkeep trigger's "that player" is the active player
    step(eng, "upkeep", player="p2")
    assert (p1.life, p2.life) == (20, 7)


def test_attack_trigger_halves_the_defending_player_not_the_attacker():
    from tests.support.deck_batch import attack

    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 20, 11
    raider = _bf(eng, _card("Raider", "Creature - Human",
                            "Whenever Raider attacks, defending player loses half their life, rounded up."))
    attack(eng, [raider])
    eng.resolve_until_stable()
    assert (p1.life, p2.life) == (20, 5)


def test_batch_combat_damage_trigger_halves_the_player_the_batch_hit():
    eng = _engine()
    p1, p2 = eng.state.player_by_id("p1"), eng.state.player_by_id("p2")
    p1.life, p2.life = 20, 20
    _bf(eng, _card("Watcher", "Creature - Snake",
                   "Whenever one or more Snakes you control deal combat damage to a player, "
                   "that player loses half their life, rounded up."))
    snake = _bf(eng, _card("Snake", "Creature — Snake", "", power=2))
    eng.recompute_continuous_effects()
    eng._apply_combat_damage([(p2, snake.power, snake)])
    eng.rules.put_triggers_on_stack()
    eng.resolve_until_stable()
    assert (p1.life, p2.life) == (20, 9)  # 20 - 2 = 18, half rounded up = 9 lost


def test_where_x_half_the_count_rounds_as_printed_and_binds_every_x_of_the_sentence():
    for rounding, tokens in (("up", 2), ("down", 1)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        for i in range(3):
            dead = GameObject(_card(f"Dead{i}", "Creature — Bear", ""), owner_id="p1", zone=Zone.GRAVEYARD)
            p1.graveyard.append(dead)
        text = f"Create X 2/2 black Zombie creature tokens, where X is half the number of creature cards in your graveyard, rounded {rounding}."
        _cast(eng, _card("Harvest", "Sorcery", text))
        assert len([o for o in eng.state.battlefield if o.name == "Zombie"]) == tokens, rounding
    # one X for the whole sentence: both halves read the same measurement
    shared = _card("Pact", "Sorcery", "You draw x cards and you lose x life, where x is half the number of artifacts you control, rounded down.")
    assert parse_oracle(shared).coverage == MODELED
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(5):
        _bf(eng, _card(f"Relic{i}", "Artifact", ""))
    p1.life = 20
    for i in range(4):
        p1.library.append(GameObject(_card(f"Fodder{i}", "Sorcery", ""), owner_id="p1", zone=Zone.LIBRARY))
    before = len(p1.hand)
    _cast(eng, shared)
    assert (p1.life, len(p1.hand) - before) == (18, 2)
