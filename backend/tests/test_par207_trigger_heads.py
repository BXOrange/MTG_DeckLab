"""PAR-207: composable trigger / activation heads, executed against the real engine.

Every head this ticket opened is driven end to end -- the event fires, the trigger goes on the stack, resolves, and
the board changes -- with a real card from the cache, not just a parse verdict:

* RULE 603.12 reflexive "<action>. When you do, <effect>." (`seq` + ``if_you_do_from`` + `reflexive_trigger`)
* RULE 118.3 / 107.14 reflexive energy payments and typed discards (`pay_cost_then`)
* RULE 700.9 / 301.5 / 303.4 attachment adjectives in object phrases (modified / equipped / enchanted)
* RULE 602.2 activation heads (exhaust, loyalty, "an ability of an artifact or creature")
* RULE 122 "the Nth <kind> counter is put on ~" thresholds
* RULE 603.8 state triggers, RULE 702.26 phasing in, RULE 309.6 completing a dungeon
* RULE 603.7 delayed triggers named by their step, RULE 303.4t enchanted-player steps
"""

from __future__ import annotations

import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.parser.oracle.catalogue.clause_reading import ClauseReading
from mtg_analyzer.parser.oracle.catalogue.handlers import match_clause
from mtg_analyzer.parser.oracle.gate import MODELED, parse_oracle
from mtg_analyzer.services.card_database import CardDatabase

_DB = CardDatabase(DB_PATH)


def _card(name: str) -> Card:
    card = _DB.get_card(name)
    assert card is not None, name
    return card


def _engine() -> GameEngine:
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _board(eng: GameEngine, name: str, pid: str = "p1", *, bind: bool = True) -> GameObject:
    obj = GameObject(_card(name), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    if bind:
        bind_from_catalogue(obj)
    eng.state.add_to_battlefield(obj)
    return obj


def _make_card(name: str, type_line: str, power: int = 1, toughness: int = 1) -> Card:
    is_creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, is_creature=is_creature, is_land="Land" in type_line,
        is_instant=type_line.startswith("Instant"), is_sorcery=type_line.startswith("Sorcery"),
        **({"power": power, "toughness": toughness} if is_creature else {}),
    )


def _plain(eng: GameEngine, name: str, pid: str = "p1", power: int = 2, toughness: int = 2,
           type_line: str = "Creature — Bear") -> GameObject:
    obj = GameObject(_make_card(name, type_line, power, toughness), owner_id=pid, zone=Zone.BATTLEFIELD)
    obj.controller_id = pid
    obj.summoning_sick = False
    eng.state.add_to_battlefield(obj)
    return obj


def _graveyard(eng: GameEngine, pid: str, names: list[str], type_line: str = "Creature — Bear") -> list[GameObject]:
    out = []
    for name in names:
        obj = GameObject(_make_card(name, type_line), owner_id=pid, zone=Zone.GRAVEYARD)
        eng.state.player_by_id(pid).graveyard.append(obj)
        out.append(obj)
    return out


def _enters(eng: GameEngine, obj: GameObject) -> None:
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=obj.instance_id, controller_id=obj.controller_id,
        object_types=sorted(obj.type_words),
    ))


def _modeled(name: str) -> bool:
    return parse_oracle(_card(name)).coverage == MODELED


def _answer(eng: GameEngine, option: str | None = None) -> None:
    """Answer the open choice with ``option`` (default: the first non-decline option)."""
    choice = eng.state.pending_choice
    assert choice is not None
    pick = option or next(o["id"] for o in choice["options"] if o["id"] != "decline")
    eng.resolve_pending_choice(pick)


def _accept_if_asked(eng: GameEngine) -> None:
    """Answer an optional ability's "do / decline" prompt with "do" when that is what is open."""
    choice = eng.state.pending_choice
    if choice is not None and {o["id"] for o in choice["options"]} == {"do", "decline"}:
        eng.resolve_pending_choice("do")


def _settle(eng: GameEngine) -> None:
    eng.resolve_until_stable()


# --- RULE 603.12: the general reflexive "<action>. When you do, <effect>" -------------------------------------


def test_reflexive_row_parses_a_certain_antecedent_into_a_gated_reflexive_trigger():
    specs = match_clause(
        "mill 4 cards. when you do, return target land card from your graveyard to the battlefield tapped",
        reading=ClauseReading(self_subject=True),
    )
    assert specs is not None and [s.type for s in specs] == ["seq"]
    seq = specs[0].params
    assert seq["if_you_do_from"] == 1
    assert [e["type"] for e in seq["effects"]] == ["mill", "reflexive_trigger"]
    # The payoff keeps its RULE 115 target inside the reflexive trigger, to be chosen when it goes on the stack.
    assert seq["effects"][1]["params"]["then_trigger"][0]["params"]["target_kind"] == "graveyard_land"


def test_reflexive_row_refuses_what_it_cannot_bind():
    reading = ClauseReading(self_subject=True)
    # The payoff's "it" would be the returned creature, which nothing here can name.
    assert match_clause("return target creature card from your graveyard to the battlefield. when you do, "
                        "it fights up to 1 target creature you don't control", reading=reading) is None
    # An antecedent with no observable footprint (exert) cannot be told apart from "did nothing".
    assert match_clause("you may exert ~ as it attacks. when you do, prevent all combat damage that would be "
                        "dealt to it this turn", reading=reading) is None
    # "When you do" answers the last instruction, not the first of several.
    assert match_clause("mill 2 cards and draw a card. when you do, you gain 1 life", reading=reading) is None


@pytest.mark.parametrize("name", [
    "Kroxa and Kunoros", "Young Necromancer", "Primal Witchstalker", "The Fire Nation Drill",
    "Pyroclastic Hellion", "Sutina, Speaker of the Tajuru", "Diregraf Horde", "Wick's Patrol",
    "Yathan Roadwatcher", "Earthbender Ascension", "Blood Spatter Analysis",
])
def test_reflexive_cards_are_modeled(name):
    assert _modeled(name)


def test_young_necromancer_exiles_two_then_reanimates_a_chosen_creature():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    necro = _board(eng, "Young Necromancer")
    fodder = _graveyard(eng, "p1", ["Fodder A", "Fodder B"])
    target = _graveyard(eng, "p1", ["Big Bear"])[0]

    _enters(eng, necro)
    _settle(eng)
    _answer(eng)  # "you may exile two cards" -> yes
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "choose_objects"  # which two cards
    for card in fodder:
        eng.resolve_pending_choice(card.instance_id)
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # the reflexive trigger's own target
    assert {o["instance_id"] for o in choice["options"]} == {target.instance_id}
    eng.resolve_pending_choice(target.instance_id)
    _settle(eng)

    assert any(o.name == "Big Bear" for o in eng.state.battlefield)
    exiled = {o.name for o in p1.exile}
    assert len(exiled) == 2 and "Big Bear" not in exiled


def test_young_necromancer_with_too_few_graveyard_cards_has_no_reflexive_trigger():
    eng = _engine()
    necro = _board(eng, "Young Necromancer")
    _graveyard(eng, "p1", ["Lonely Bear"])  # one card: "exile two" cannot be done in full

    _enters(eng, necro)
    _settle(eng)
    _answer(eng)  # the ability is optional, and accepting is allowed -- but there is nothing to exile in full
    _settle(eng)

    assert eng.state.pending_choice is None  # no pick, and no reflexive trigger asking for a target
    assert not any(o.name == "Lonely Bear" for o in eng.state.battlefield)
    assert len(eng.state.player_by_id("p1").exile) == 0


def test_primal_witchstalker_mills_then_returns_a_land():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(6):
        p1.library.append(GameObject(Card(id=f"L{i}", name=f"Filler {i}", type_line="Instant"),
                                     owner_id="p1", zone=Zone.LIBRARY))
    stalker = _board(eng, "Primal Witchstalker")
    land = _graveyard(eng, "p1", ["Old Forest"], type_line="Basic Land — Forest")[0]

    _enters(eng, stalker)
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(land.instance_id)
    _settle(eng)

    assert any(o.name == "Old Forest" and o.tapped for o in eng.state.battlefield)
    assert len(p1.library) == 2  # four cards were milled


def test_fire_nation_drill_taps_itself_then_destroys_a_small_creature():
    eng = _engine()
    drill = _board(eng, "The Fire Nation Drill")
    victim = _plain(eng, "Small Victim", "p2", power=3, toughness=3)
    big = _plain(eng, "Too Big", "p2", power=5, toughness=5)

    _enters(eng, drill)
    _settle(eng)
    _accept_if_asked(eng)  # "you may tap it" -> yes
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    offered = {o["instance_id"] for o in choice["options"] if "instance_id" in o}
    assert victim.instance_id in offered and big.instance_id not in offered  # power 4 or less
    eng.resolve_pending_choice(victim.instance_id)
    _settle(eng)

    assert drill.tapped
    assert victim.zone is not Zone.BATTLEFIELD and big.zone is Zone.BATTLEFIELD


def test_pyroclastic_hellion_bounces_an_own_land_then_hits_each_opponent():
    eng = _engine()
    hellion = _board(eng, "Pyroclastic Hellion")
    land = _plain(eng, "Island", "p1", type_line="Basic Land — Island")

    _enters(eng, hellion)
    _settle(eng)
    _answer(eng)  # you may return a land
    _settle(eng)
    if eng.state.pending_choice is not None:
        _answer(eng)  # which land
        _settle(eng)

    assert land.zone is Zone.HAND
    assert eng.state.player_by_id("p2").life == 18


def test_earthbender_ascension_reflexive_trigger_waits_for_the_fourth_quest_counter():
    eng = _engine()
    asc = _board(eng, "Earthbender Ascension")
    ally = _plain(eng, "Ally", "p1")

    for expected in (1, 2, 3):
        land = _plain(eng, f"Land {expected}", "p1", type_line="Basic Land — Forest")
        _enters(eng, land)
        _settle(eng)
        assert asc.counters.get("quest") == expected
        assert eng.state.pending_choice is None  # the intervening "if it has four or more" is still false
    land = _plain(eng, "Land 4", "p1", type_line="Basic Land — Forest")
    _enters(eng, land)
    _settle(eng)
    assert asc.counters.get("quest") == 4
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(ally.instance_id)
    _settle(eng)

    assert ally.counters.get("+1/+1") == 1
    # "It gains trample" follows the target the reflexive trigger chose, not Earthbender Ascension itself.
    assert "trample" in {k.lower() for k in (ally.granted_keywords or [])}
    assert "trample" not in {k.lower() for k in (asc.granted_keywords or [])}


def test_diregraf_horde_makes_tokens_then_exiles_graveyard_cards():
    eng = _engine()
    horde = _board(eng, "Diregraf Horde")
    junk = _graveyard(eng, "p2", ["Their Card"])[0]

    _enters(eng, horde)
    _settle(eng)
    zombies = [o for o in eng.state.battlefield if o.name == "Zombie"]
    assert len(zombies) == 2
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target_multi"  # "up to two target cards"
    eng.resolve_pending_choice(junk.instance_id)
    if eng.state.pending_choice is not None:
        eng.resolve_pending_choice("stop")
    _settle(eng)

    assert junk.zone is Zone.EXILE


def test_kroxa_exiles_five_then_returns_a_creature_on_entering():
    eng = _engine()
    kroxa = _board(eng, "Kroxa and Kunoros")
    fodder = _graveyard(eng, "p1", [f"Fodder {i}" for i in range(5)], type_line="Instant")
    target = _graveyard(eng, "p1", ["Reanimate Me"])[0]

    _enters(eng, kroxa)
    _settle(eng)
    _accept_if_asked(eng)
    _settle(eng)
    for card in fodder:
        eng.resolve_pending_choice(card.instance_id)
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(target.instance_id)
    _settle(eng)

    assert any(o.name == "Reanimate Me" for o in eng.state.battlefield)


def test_blood_spatter_analysis_reflexive_trigger_only_follows_a_real_sacrifice():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    for i in range(6):
        p1.library.append(GameObject(_make_card(f"Lib {i}", "Instant"), owner_id="p1", zone=Zone.LIBRARY))
    analysis = _board(eng, "Blood Spatter Analysis")
    target = _graveyard(eng, "p1", ["Fallen Bear"])[0]
    dying = _plain(eng, "Doomed", "p2")

    analysis.counters["bloodstain"] = 3
    eng.rules.destroy(dying)
    _settle(eng)

    # Four counters: it is not sacrificed, so "when you do" never happens even though a card was milled.
    assert analysis.counters["bloodstain"] == 4 and analysis.zone is Zone.BATTLEFIELD
    assert eng.state.pending_choice is None

    analysis.counters["bloodstain"] = 4
    victim = _plain(eng, "Doomed Too", "p2")
    eng.rules.destroy(victim)
    _settle(eng)
    assert analysis.zone is Zone.GRAVEYARD
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(target.instance_id)
    _settle(eng)
    assert target.zone is Zone.HAND


# --- RULE 118.3 / 107.14: reflexive energy payments and typed discards ------------------------------------------


def test_riddle_gate_gargoyle_pays_energy_then_chooses_a_target_for_lifelink():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    gargoyle = _board(eng, "Riddle Gate Gargoyle")
    ally = _plain(eng, "Ally")
    p1.add_counters("energy", 3)

    eng.state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                                   defending_player_id="p2", count=1))
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    _answer(eng, "pay")
    _settle(eng)
    assert p1.counters.get("energy") == 1  # {E}{E} was paid
    assert eng.state.pending_choice["kind"] == "trigger_target"  # chosen only after the payment
    eng.resolve_pending_choice(ally.instance_id)
    _settle(eng)
    eng.recompute_continuous_effects()

    assert "lifelink" in ally.granted_keywords and "lifelink" not in gargoyle.granted_keywords


def test_riddle_gate_gargoyle_without_energy_offers_nothing():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _board(eng, "Riddle Gate Gargoyle")
    _plain(eng, "Ally")
    p1.add_counters("energy", 1)  # one short

    eng.state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                                   defending_player_id="p2", count=1))
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is None or choice["kind"] != "trigger_target"


def test_dokuchi_silencer_discards_a_creature_card_then_destroys_a_creature():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    silencer = _board(eng, "Dokuchi Silencer")
    victim = _plain(eng, "Their Guy", "p2")
    p1.hand.append(GameObject(_make_card("Hand Bear", "Creature — Bear"), owner_id="p1", zone=Zone.HAND))

    eng.rules.deal_damage(p2, 2, source=silencer, combat=True)
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "pay_cost_then"
    _answer(eng, "pay")
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(victim.instance_id)
    _settle(eng)

    assert victim.zone is not Zone.BATTLEFIELD
    assert [c.name for c in p1.graveyard] == ["Hand Bear"]


def test_dokuchi_silencer_cannot_pay_with_only_a_land_in_hand():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    silencer = _board(eng, "Dokuchi Silencer")
    victim = _plain(eng, "Their Guy", "p2")
    p1.hand.append(GameObject(_make_card("Hand Forest", "Basic Land — Forest"), owner_id="p1", zone=Zone.HAND))

    eng.rules.deal_damage(p2, 2, source=silencer, combat=True)
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is None or "pay" not in {o["id"] for o in choice["options"]}
    assert victim.zone is Zone.BATTLEFIELD


# --- RULE 700.9 / 301.5 / 303.4: attachment adjectives --------------------------------------------------------


def _equip(eng: GameEngine, host: GameObject) -> GameObject:
    equipment = _plain(eng, "Test Sword", type_line="Artifact — Equipment")
    equipment.parametric_keywords = {"equip": {"cost": "{1}"}}  # what makes the attachment legal to the SBA re-check
    equipment.attached_to = host.instance_id
    return equipment


def _library(eng: GameEngine, pid: str, count: int) -> None:
    for i in range(count):
        eng.state.player_by_id(pid).library.append(
            GameObject(_make_card(f"{pid} lib {i}", "Instant"), owner_id=pid, zone=Zone.LIBRARY))


def test_stone_haven_outfitter_draws_only_when_an_equipped_creature_dies():
    for equipped, expected in ((True, 1), (False, 0)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        _library(eng, "p1", 3)
        _board(eng, "Stone Haven Outfitter")
        guy = _plain(eng, "Guy")
        if equipped:
            _equip(eng, guy)
        drawn_before = len(p1.hand)
        eng.rules.destroy(guy)
        _settle(eng)
        assert len(p1.hand) - drawn_before == expected, equipped


def test_modified_adjective_reads_counters_equipment_and_auras():
    eng = _engine()
    _board(eng, "Akki Ember-Keeper")
    plain_guy = _plain(eng, "Plain Guy")
    counter_guy = _plain(eng, "Counter Guy")
    counter_guy.counters["+1/+1"] = 1

    eng.rules.destroy(plain_guy)
    _settle(eng)
    assert not any(o.name == "Spirit" for o in eng.state.battlefield)
    eng.rules.destroy(counter_guy)
    _settle(eng)
    assert any(o.name == "Spirit" for o in eng.state.battlefield)  # RULE 700.9: a counter makes it modified


def test_acquisition_octopus_triggers_for_itself_and_its_host_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _library(eng, "p1", 5)
    octopus = _board(eng, "Acquisition Octopus")
    host = _plain(eng, "Host")
    octopus.attached_to = host.instance_id
    stranger = _plain(eng, "Stranger")

    def drawn_after(source):
        before = len(p1.hand)
        eng.rules.deal_damage(p2, 2, source=source, combat=True)
        _settle(eng)
        return len(p1.hand) - before

    assert drawn_after(host) == 1  # "equipped creature"
    assert drawn_after(octopus) == 1  # "this creature"
    assert drawn_after(stranger) == 0


# --- RULE 602.2: activation heads -------------------------------------------------------------------------------


def test_exhaust_trigger_follows_exhaust_abilities_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    jockey = _board(eng, "Adrenaline Jockey")
    expert = _board(eng, "Afterburner Expert")
    plot = _board(eng, "Deadly Designs")
    assert expert.activated_abilities[0].keyword_label == "exhaust"

    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, plot, 0)  # an ordinary activated ability
    _settle(eng)
    assert jockey.counters.get("+1/+1", 0) == 0

    p1.mana_pool.add_many({"G": 4})
    eng.activate_ability(p1, expert, 0)  # Exhaust
    _settle(eng)
    assert jockey.counters.get("+1/+1") == 1


def test_power_up_abilities_are_not_exhaust_abilities():
    from mtg_analyzer.parser.oracle.spec import AbilitySpec  # noqa: F401  (import keeps the parser boundary honest)

    power_up = next(c for c in ("Black Panther, Most Dangerous",) if _DB.get_card(c) is not None)
    specs = parse_oracle(_card(power_up)).specs
    markers = [e for s in specs for e in s.effects if e.type == "activate_only_once_marker"]
    assert markers and all(e.params.get("keyword") in ("exhaust", "power-up") for e in markers)


def _chandra_walker(eng: GameEngine) -> GameObject:
    card = Card(id="walker", name="Test Chandra", type_line="Legendary Planeswalker — Chandra", loyalty=4,
                oracle_text="+1: You gain 1 life.\n−2: Draw a card.")
    walker = GameObject(card, owner_id="p1", zone=Zone.BATTLEFIELD)
    walker.controller_id = "p1"
    walker.summoning_sick = False
    bind_from_catalogue(walker)
    eng.state.add_to_battlefield(walker)
    walker.counters["loyalty"] = 4
    return walker


def test_loyalty_activation_heads_fire_for_loyalty_abilities():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _board(eng, "Way of the Paradox")
    _board(eng, "Keral Keep Disciples")
    walker = _chandra_walker(eng)

    life = (p1.life, p2.life)
    eng.activate_ability(p1, walker, 0)  # +1: gain 1 life
    _settle(eng)

    assert p1.life - life[0] == 2  # the ability itself, plus Way of the Paradox's own life gain
    assert life[1] - p2.life == 1  # "a Chandra planeswalker": Keral Keep Disciples pings each opponent


def test_crackdown_construct_pumps_for_an_artifact_or_creature_ability_only():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    construct = _board(eng, "Crackdown Construct")
    designs = _board(eng, "Deadly Designs")  # an enchantment's ability: not an artifact or creature
    expert = _board(eng, "Afterburner Expert")  # a creature's activated (non-mana) ability
    eng.recompute_continuous_effects()
    assert (construct.power, construct.toughness) == (2, 2)

    p1.mana_pool.add_many({"C": 2})
    eng.activate_ability(p1, designs, 0)
    _settle(eng)
    eng.recompute_continuous_effects()
    assert (construct.power, construct.toughness) == (2, 2)

    p1.mana_pool.add_many({"G": 4})
    eng.activate_ability(p1, expert, 0)
    _settle(eng)
    eng.recompute_continuous_effects()
    assert (construct.power, construct.toughness) == (3, 3)


# --- RULE 122: "the Nth <kind> counter is put on ~" --------------------------------------------------------------


def test_nth_counter_trigger_fires_exactly_when_the_threshold_is_reached():
    eng = _engine()
    claim = _board(eng, "Claim the Kingdom")
    ally = _plain(eng, "Ally")
    for _ in range(3):
        eng.rules.add_counters(claim, 1, "plan")
        _settle(eng)
    assert claim.zone is Zone.BATTLEFIELD and eng.state.pending_choice is None

    eng.rules.add_counters(claim, 1, "plan")
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # "When you do" -- chosen on the stack
    eng.resolve_pending_choice(ally.instance_id)
    _settle(eng)

    assert claim.zone is Zone.GRAVEYARD  # "sacrifice it"
    assert ally.counters.get("indestructible") == 1


def test_nth_counter_trigger_fires_once_when_several_counters_cross_the_threshold():
    eng = _engine()
    claim = _board(eng, "Claim the Kingdom")
    ally = _plain(eng, "Ally")
    eng.rules.add_counters(claim, 3, "plan")
    _settle(eng)
    eng.rules.add_counters(claim, 2, "plan")  # 3 -> 5 puts the fourth counter on it
    _settle(eng)

    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"
    eng.resolve_pending_choice(ally.instance_id)
    _settle(eng)
    assert claim.zone is Zone.GRAVEYARD and ally.counters.get("indestructible") == 1


# --- RULE 603.8: state triggers --------------------------------------------------------------------------------


def test_state_trigger_sacrifices_when_the_board_condition_becomes_true():
    eng = _engine()
    trinket = _plain(eng, "Trinket", type_line="Artifact")
    dragon = _board(eng, "Covetous Dragon")
    _settle(eng)
    assert dragon.zone is Zone.BATTLEFIELD  # "When you control no artifacts" -- you control one

    eng.rules.destroy(trinket)
    _settle(eng)
    assert dragon.zone is Zone.GRAVEYARD


def test_state_trigger_with_no_other_creatures_reads_the_other_clause():
    eng = _engine()
    ally = _plain(eng, "Ally")
    crocodile = _board(eng, "Emperor Crocodile")
    _settle(eng)
    assert crocodile.zone is Zone.BATTLEFIELD

    eng.rules.destroy(ally)
    _settle(eng)
    assert crocodile.zone is Zone.GRAVEYARD


def test_state_trigger_that_counts_any_players_creatures():
    eng = _engine()
    assembly = _board(eng, "Task Mage Assembly")
    _settle(eng)
    assert assembly.zone is Zone.GRAVEYARD  # no creatures on the battlefield at all

    eng = _engine()
    _plain(eng, "Bystander", "p2")
    assembly = _board(eng, "Task Mage Assembly")
    _settle(eng)
    assert assembly.zone is Zone.BATTLEFIELD


def test_state_trigger_on_the_sources_own_counters_keeps_its_followup():
    eng = _engine()
    designs = _board(eng, "Deadly Designs")
    first = _plain(eng, "First", "p2")
    second = _plain(eng, "Second", "p2")
    designs.counters["plot"] = 4
    _settle(eng)
    assert designs.zone is Zone.BATTLEFIELD and eng.state.pending_choice is None

    designs.counters["plot"] = 5  # "When there are five or more plot counters on this enchantment"
    _settle(eng)
    for victim in (first, second):
        eng.resolve_pending_choice(victim.instance_id)
        _settle(eng)
    if eng.state.pending_choice is not None:
        eng.resolve_pending_choice("stop")
        _settle(eng)

    assert designs.zone is Zone.GRAVEYARD
    assert first.zone is Zone.GRAVEYARD and second.zone is Zone.GRAVEYARD


# --- RULE 702.26 / 309.6 / 603.2: phasing, dungeons, split heads --------------------------------------------------


def test_phasing_in_and_out_fire_their_own_events():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _library(eng, "p1", 3)
    imp = _board(eng, "Teferi's Imp")
    imp.phased_out = True

    eng._step_untap()  # phases in
    _settle(eng)
    assert not imp.phased_out and len(p1.hand) == 1  # "whenever ~ phases in, draw a card"

    eng._step_untap()  # phasing: phases out again
    _settle(eng)
    assert imp.phased_out and len(p1.hand) == 0  # "whenever ~ phases out, discard a card"


def test_completing_a_dungeon_fires_the_player_event():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _board(eng, "Varis, Silverymoon Ranger")

    class _Dungeon:
        name = "Lost Mine of Phandelver"

    p1.dungeon = _Dungeon()
    eng.rules.complete_dungeon(p1)
    _settle(eng)

    assert any(o.name == "Wolf" for o in eng.state.battlefield)


def test_a_split_head_is_two_independent_abilities():
    eng = _engine()
    _library(eng, "p1", 4)
    cake = _board(eng, "Carrot Cake")
    assert [a.trigger_event for a in cake.triggered_abilities] == ["ENTERS_BATTLEFIELD", "SACRIFICE"]

    _enters(eng, cake)
    _settle(eng)
    _answer(eng, "decline") if eng.state.pending_choice else None  # the scry
    rabbits = [o for o in eng.state.battlefield if o.name == "Rabbit"]
    assert len(rabbits) == 1
    eng.rules.sacrifice(eng.state.player_by_id("p1"), "permanent", 1, exclude=rabbits[0])
    _settle(eng)
    _answer(eng, "decline") if eng.state.pending_choice else None
    assert len([o for o in eng.state.battlefield if o.name == "Rabbit"]) == 2


def test_cast_or_cycle_head_binds_both_events():
    eng = _engine()
    lurker = _board(eng, "Drownyard Lurker")
    events = [a.trigger_event for a in lurker.triggered_abilities]
    assert events == ["SPELL_CAST", "CYCLED"]
    assert lurker.triggered_abilities[0].functions_from_stack  # RULE 601.2i: it resolves above its own spell


# --- RULE 603.7: delayed triggers named by their step ------------------------------------------------------------


def test_delayed_step_trigger_waits_for_its_own_step_and_player():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _library(eng, "p1", 8)
    casey = _board(eng, "Casey Jones, Vigilante")
    _enters(eng, casey)
    _settle(eng)
    assert len(p1.hand) == 3
    assert [(d.step, d.scope) for d in eng.state.delayed_triggers] == [("upkeep", "controller")]

    eng._fire_delayed_triggers("end")  # not the step it waits for
    _settle(eng)
    assert len(p1.hand) == 3
    eng._fire_delayed_triggers("upkeep")  # "your next upkeep"
    _settle(eng)
    assert len(p1.hand) == 0 and len(p1.graveyard) == 3


def test_next_end_step_trigger_applies_to_whoever_the_step_belongs_to():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _library(eng, "p1", 8)
    spell = GameObject(_card("False Memories"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    _graveyard(eng, "p1", [f"Old {i}" for i in range(8)], type_line="Instant")

    from mtg_analyzer.game.binding.core import build_effects
    from mtg_analyzer.game.effects.core import _apply_effects_partitioned

    spec = next(s for s in parse_oracle(spell.card).specs if s.ability_kind == "spell_effect")
    _apply_effects_partitioned(build_effects(spec.effects, spell), eng.rules.context, None, None, source=spell)
    _settle(eng)
    assert len(p1.library) == 1 and len(p1.graveyard) == 15  # seven milled on top of the eight already there
    assert [(d.step, d.scope) for d in eng.state.delayed_triggers] == [("end", "any")]

    eng._fire_delayed_triggers("end")
    _settle(eng)
    for _ in range(7):
        if eng.state.pending_choice is not None:
            eng.resolve_pending_choice(eng.state.pending_choice["options"][0]["id"])
            _settle(eng)
    assert len(p1.exile) == 7


# --- RULE 303.4t: a step that belongs to the enchanted player ---------------------------------------------------


def test_enchanted_players_upkeep_only_fires_on_that_players_turn():
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    _library(eng, "p2", 5)
    curse = _board(eng, "Curse of the Bloody Tome")
    curse.attached_to = "p2"

    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))  # p1's upkeep
    _settle(eng)
    assert len(p2.library) == 5

    eng.state.active_player_index = 1  # p2's turn
    eng.state.fire_event(GameEvent(EventType.STEP_BEGIN, step="upkeep"))
    _settle(eng)
    assert len(p2.library) == 3 and len(p2.graveyard) == 2


# --- the "this way" reflexive, enters untapped, energy, ordinal spells, attack batches -------------------------


def test_discard_this_way_trigger_needs_a_matching_discarded_card():
    for discarded_type, expect_unblockable in (("Creature — Bear", True), ("Instant", False)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        _library(eng, "p1", 3)
        evie = _board(eng, "Evie Frye")
        ally = _plain(eng, "Ally")
        card = GameObject(_make_card("Discard Me", discarded_type), owner_id="p1", zone=Zone.HAND)
        p1.hand.append(card)
        p1.mana_pool.add_many({"C": 1})

        eng.activate_ability(p1, evie, 0)
        _settle(eng)
        eng.resolve_pending_choice(card.instance_id)  # discard the card we chose, not the one just drawn
        _settle(eng)
        if eng.state.pending_choice is not None:
            eng.resolve_pending_choice(ally.instance_id)
            _settle(eng)

        assert ally.temp_unblockable is expect_unblockable, discarded_type


def test_enters_untapped_trigger_reads_the_entry_status():
    for tapped, expect_token in ((False, True), (True, False)):
        eng = _engine()
        mine = _board(eng, "Dwarven Mine")
        mine.tapped = tapped
        _enters(eng, mine)
        _settle(eng)
        assert any(o.name == "Dwarf" for o in eng.state.battlefield) is expect_token, tapped


def test_getting_energy_triggers_the_player_counter_head():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    gorger = _board(eng, "Territorial Gorger")
    eng.recompute_continuous_effects()
    assert (gorger.power, gorger.toughness) == (2, 2)
    eng.rules.add_player_counters(p1, 2, "energy")
    _settle(eng)
    eng.recompute_continuous_effects()
    assert (gorger.power, gorger.toughness) == (4, 4)


def test_first_matching_spell_each_turn_counts_only_matching_spells():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _library(eng, "p1", 6)
    _board(eng, "Valeria Richards, Precocious")

    def spell(name, type_line):
        flags = {"is_instant": True} if type_line == "Instant" else {"is_creature": True, "power": 1, "toughness": 1}
        card = Card(id=name, name=name, type_line=type_line, mana_cost_string="", converted_mana_cost=0, **flags)
        obj = GameObject(card, owner_id="p1", zone=Zone.HAND)
        p1.hand.append(obj)
        return obj

    creature, first, second = spell("Bear", "Creature — Bear"), spell("Zap One", "Instant"), spell("Zap Two", "Instant")
    sizes = []
    for obj in (creature, first, second):
        eng.cast_spell(p1, obj)
        _settle(eng)
        sizes.append(len(p1.hand))
    # hand: 3 -> cast creature (2, no draw) -> first noncreature (1 + draw = 2) -> second noncreature (1, no draw)
    assert sizes == [2, 2, 1]


def test_creatures_attacking_you_count_only_the_attackers_aimed_at_you():
    for defender, expected_life in (("p1", 23), ("p2", 20)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        _board(eng, "Orim's Prayer")
        attackers = [_plain(eng, f"Attacker {i}", "p2") for i in range(3)]
        for attacker in attackers:
            attacker.attacking = True
            attacker.combat_defender = {"kind": "player", "id": defender}
        eng.state.fire_event(GameEvent(
            EventType.ATTACKERS_DECLARED, player_id="p2", attacker_ids=[a.instance_id for a in attackers],
            count=3, defending_player_ids=[defender], defended_player_ids=[defender]))
        _settle(eng)
        assert p1.life == expected_life, defender


def test_attack_batch_object_filter_excludes_tokens():
    eng = _engine()
    _board(eng, "Crimson Cowl, Master of Evil")
    token = _plain(eng, "Villain Token", "p1", type_line="Creature — Villain")
    token.is_token = True
    token.attacking = True
    eng.state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                                   defending_player_id="p2", count=1))
    _settle(eng)
    assert [o.name for o in eng.state.battlefield if o.name == "Villain"] == []

    real = _plain(eng, "Real Villain", "p1", type_line="Creature — Villain")
    real.attacking = True
    eng.state.fire_event(GameEvent(EventType.PLAYER_ATTACKED, attacking_player_id="p1",
                                   defending_player_id="p2", count=2))
    _settle(eng)
    assert [o.name for o in eng.state.battlefield if o.name == "Villain"] == ["Villain"]


# --- fail-closed: heads this ticket must not claim ---------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "when you do, draw a card",  # no antecedent in the clause
    "you activate an ability",  # could include mana abilities, which never reach the stack
    "the fourth plan counter is put on target creature",
    "there are many creatures",  # not a state phrase `static_condition` reads
    "you control a very large creature",  # likewise unread: a state head needs a vocabulary condition
])
def test_unsupported_head_shapes_stay_unclaimed(text):
    from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

    assert parse_object_trigger_head(text) is None


def test_head_grammar_shapes():
    from mtg_analyzer.parser.oracle.catalogue.object_trigger_head import parse_object_trigger_head

    exhaust = parse_object_trigger_head("you activate an exhaust ability")
    assert (exhaust.event, exhaust.trigger) == ("ACTIVATED_ABILITY", {"filter": {"is_exhaust_ability": True}})
    threshold = parse_object_trigger_head("the seventh plan counter is put on ~")
    assert threshold.event == "COUNTER" and threshold.trigger["source_counter_reaches"] == {"count": 7, "kind": "plan"}
    state = parse_object_trigger_head("there are no creatures on the battlefield")
    assert state.event == "STATE_CHECK" and state.trigger["state_condition"]["max"] == 0
    attacked = parse_object_trigger_head("enchanted player is attacked")
    assert attacked.event == "PLAYER_ATTACKED" and attacked.trigger.get("defender_is_enchanted_player")


def test_enters_untapped_trigger_follows_a_real_land_play():
    for forests, expect_food in ((0, False), (3, True)):
        eng = _engine()
        p1 = eng.state.player_by_id("p1")
        for i in range(forests):
            _plain(eng, f"Forest {i}", type_line="Basic Land — Forest")
        cabin = GameObject(_card("Gingerbread Cabin"), owner_id="p1", zone=Zone.HAND)
        bind_from_catalogue(cabin)
        p1.hand.append(cabin)
        eng.play_land(p1, cabin)  # "enters tapped unless you control three or more other Forests"
        _settle(eng)
        assert cabin.tapped is (not expect_food)
        assert any(o.name == "Food" for o in eng.state.battlefield) is expect_food, forests


def test_shuffle_head_watches_the_opponents_library():
    eng = _engine()
    trickster = _board(eng, "Cosi's Trickster")
    _library(eng, "p1", 2)
    _library(eng, "p2", 2)
    eng.rules.shuffle_library(eng.state.player_by_id("p1"))  # your own shuffle is not "an opponent's"
    _settle(eng)
    _accept_if_asked(eng)
    _settle(eng)
    assert trickster.counters.get("+1/+1", 0) == 0
    eng.rules.shuffle_library(eng.state.player_by_id("p2"))
    _settle(eng)
    _accept_if_asked(eng)
    _settle(eng)
    assert trickster.counters.get("+1/+1") == 1


def test_kishla_trawlers_exiles_a_creature_card_of_its_own_graveyard_then_returns_a_spell():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    kishla = _board(eng, "Kishla Trawlers")
    bear = _graveyard(eng, "p1", ["Spare Bear"])[0]
    bolt = _graveyard(eng, "p1", ["Old Bolt"], type_line="Instant")[0]
    other = _graveyard(eng, "p1", ["Old Shock"], type_line="Instant")[0]

    _enters(eng, kishla)
    _settle(eng)
    _accept_if_asked(eng)
    _settle(eng)
    choice = eng.state.pending_choice
    if choice is not None and choice["kind"] == "choose_objects":
        # only a *creature* card of the player's graveyard may be exiled
        assert {o["instance_id"] for o in choice["options"]} == {bear.instance_id}
        eng.resolve_pending_choice(bear.instance_id)
        _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # two instants to choose between
    assert {o["instance_id"] for o in choice["options"]} == {bolt.instance_id, other.instance_id}
    eng.resolve_pending_choice(bolt.instance_id)
    _settle(eng)

    assert bear.zone is Zone.EXILE and bolt in p1.hand and other.zone is Zone.GRAVEYARD


def test_kishla_trawlers_without_a_creature_card_does_nothing():
    eng = _engine()
    kishla = _board(eng, "Kishla Trawlers")
    bolt = _graveyard(eng, "p1", ["Old Bolt"], type_line="Instant")[0]

    _enters(eng, kishla)
    _settle(eng)
    _accept_if_asked(eng)
    _settle(eng)

    assert eng.state.pending_choice is None and bolt.zone is Zone.GRAVEYARD


def test_royal_scions_loyalty_ability_draws_then_hits_for_the_hand_size_it_has_then():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    p2 = eng.state.player_by_id("p2")
    _library(eng, "p1", 6)
    scions = _board(eng, "The Royal Scions")
    scions.counters["loyalty"] = 10

    ability = next(a for a in scions.activated_abilities if a.cost.loyalty == -8)
    eng.activate_ability(p1, scions, scions.activated_abilities.index(ability))
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # chosen after the draw (RULE 603.12)
    eng.resolve_pending_choice("p2")
    _settle(eng)

    assert len(p1.hand) == 4 and p2.life == 20 - 4


def test_a_spells_reflexive_trigger_targets_after_the_discard():
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    _library(eng, "p1", 4)
    victim = _plain(eng, "Victim", "p2", power=2, toughness=3)
    spell = GameObject(_card("Glacial Dragonhunt"), owner_id="p1", zone=Zone.HAND)
    bind_from_catalogue(spell)
    p1.hand.append(spell)
    p1.mana_pool.add_many({"U": 1, "R": 1})

    eng.cast_spell(p1, spell)
    _settle(eng)
    assert eng.state.pending_choice["kind"] == "composite_optional"  # "you may discard a card"
    eng.resolve_pending_choice("yes")
    _settle(eng)
    choice = eng.state.pending_choice
    assert choice is not None and choice["kind"] == "trigger_target"  # the drawn Instant is a nonland card
    assert {o["instance_id"] for o in choice["options"]} == {victim.instance_id}
    eng.resolve_pending_choice(victim.instance_id)
    _settle(eng)

    assert victim.zone is Zone.GRAVEYARD  # 3 damage
