"""PAR-216 axis B: one-shot prevention shields over the shared object phrase (RULE 615.1, 615.7).

"Prevent all combat damage that would be dealt to and dealt by that creature this turn", "prevent all damage target
creature would deal this turn", "prevent all [combat] damage that would be dealt this turn by <sources>" and "prevent all
damage a source of your choice would deal this turn": parse tests pin the specs, execution tests resolve the real cards
and check what the shield actually stops and when it expires.
"""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from tests.support.deck_batch import RICH, activate, answer, card, cast, filler, game


def _parse(text, type_line="Instant"):
    c = Card(id="x", name="Probe Card", type_line=type_line, oracle_text=text, is_instant="Instant" in type_line,
             is_creature="Creature" in type_line)
    return parse_oracle(c)


def _effects(result):
    return [(e["type"], e["params"]) for s in result.specs for e in s.to_dict()["effects"]]


def _modeled(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    return parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def _fund(eng, player="p1"):
    eng.state.player_by_id(player).mana_pool.add_many(RICH)


# --- parse -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,effect", [
    ("Prevent all combat damage that would be dealt to and dealt by target creature this turn.",
     ("prevent_damage_shield", {"amount": "all", "combat_only": True, "and_dealt_by": True, "target_kind": "creature"})),
    ("Prevent all damage target creature would deal this turn.",
     ("prevent_damage_from_target", {"target_kind": "creature"})),
    ("Prevent all damage target instant or sorcery spell would deal this turn.",
     ("prevent_damage_from_target", {"target_kind": "spell", "spell_filter": {"card_types": ["instant", "sorcery"]}})),
    ("Prevent all damage target spell would deal this turn. You gain life equal to the damage prevented this way.",
     ("prevent_damage_from_target",
      {"target_kind": "spell", "rider": {"kind": "gain_life", "recipient": "you"}})),
    ("Prevent all combat damage that would be dealt this turn by creatures with power 3 or less.",
     ("prevent_damage_shield", {"amount": "all", "by_sources_only": True, "combat_only": True,
                                "source_filter": {"object_filter": {"card_type": "creature", "max_power": 3}}})),
    ("Prevent all damage that black sources and red sources would deal this turn.",
     ("prevent_damage_shield", {"amount": "all", "by_sources_only": True, "source_filter": {
         "object_filter": {"any_of": [{"color": "B"}, {"color": "R"}]}}})),
    ("Prevent all damage a source of your choice would deal this turn.",
     ("request_prevent_damage_source", {"amount": "all", "recipient": "any"})),
    ("Prevent all damage a red source of your choice would deal this turn.",
     ("request_prevent_damage_source", {"amount": "all", "recipient": "any", "source_filter": {"color": "R"}})),
    ("Prevent all damage a source of your choice would deal to you this turn.",
     ("request_prevent_damage_source", {"amount": "all"})),
])
def test_one_shot_clause_spec(text, effect):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    assert _effects(result)[0] == effect


@pytest.mark.parametrize("text", [
    "Prevent all damage creatures with no +1/+1 counters on them would deal this turn.",  # unparsed source phrase
    "Prevent all damage target mystery would deal this turn.",
    "Prevent all combat damage that would be dealt to and dealt by those creatures this turn.",
])
def test_one_shot_clause_is_not_over_claimed(text):
    assert not _parse(text).modeled


@pytest.mark.parametrize("name", [
    "Maze of Ith", "Ebony Horse", "Elvish Scout", "Fog Bank", "Urborg Phantom", "Deftblade Elite", "Hallow",
    "Shieldmage Elder", "Hidden Retreat", "Pay No Heed", "Rith's Charm", "Auriok Replica", "Burrenton Forge-Tender",
    "Fog of War", "Obscuring Haze", "Snag", "Tanglesap", "Hunter's Ambush", "Haze Frog", "Luminesce",
])
def test_cards_are_modeled(name):
    assert _modeled(name)


# --- execution -------------------------------------------------------------------------------------------------------------

def test_maze_of_ith_stops_combat_damage_both_ways_but_not_other_damage():
    eng = game(library=0)
    maze = card(eng, "Maze of Ith")
    attacker = filler(eng, "Attacker", player="p2", power=5, toughness=5)
    attacker.attacking = True
    bystander = filler(eng, "Bystander", power=2, toughness=9)
    _fund(eng)
    activate(eng, maze, 0, targets=[attacker])
    eng.rules.deal_damage(bystander, 5, source=attacker, combat=True)   # dealt BY the attacker
    eng.rules.deal_damage(attacker, 2, source=bystander, combat=True)   # dealt TO the attacker
    assert (bystander.damage_marked, attacker.damage_marked) == (0, 0)
    eng.rules.deal_damage(bystander, 1, source=attacker, combat=False)  # noncombat is not covered
    assert bystander.damage_marked == 1


def test_to_and_dealt_by_shield_expires_at_end_of_turn():
    eng = game(library=0)
    maze = card(eng, "Maze of Ith")
    attacker = filler(eng, "Attacker", player="p2", power=5, toughness=9)
    attacker.attacking = True
    victim = filler(eng, "Victim", power=1, toughness=9)
    _fund(eng)
    activate(eng, maze, 0, targets=[attacker])
    assert attacker.temp_prevent_combat_damage_dealt
    while eng.state.current_step != "cleanup":
        eng.advance_step()
    eng.advance_step()
    eng.resolve_until_stable()
    assert not attacker.temp_prevent_combat_damage_dealt
    eng.rules.deal_damage(victim, 3, source=attacker, combat=True)
    assert victim.damage_marked == 3


def test_fog_bank_style_self_shield_is_the_creature_itself():
    eng = game(library=0)
    phantom = card(eng, "Urborg Phantom")
    foe = filler(eng, "Foe", player="p2", power=3, toughness=3)
    _fund(eng)
    activate(eng, phantom, 0)
    eng.rules.deal_damage(phantom, 3, source=foe, combat=True)
    eng.rules.deal_damage(foe, 2, source=phantom, combat=True)
    assert (phantom.damage_marked, foe.damage_marked) == (0, 0)


def test_noncombat_damage_from_a_chosen_creature_is_prevented_for_the_turn():
    eng = game(library=0)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    me = eng.state.player_by_id("p1")
    snare = filler(eng, "Probe Snare", type_line="Instant", zone=Zone.HAND,
                   oracle_text="Prevent all damage target creature would deal this turn.")
    cast(eng, snare, targets=[ogre])
    answer(eng)
    life = me.life
    eng.rules.deal_damage(me, 4, source=ogre)
    eng.rules.deal_damage(me, 2, source=ogre, combat=True)
    assert me.life == life


def test_class_shield_stops_only_matching_sources_and_only_combat_damage():
    eng = game(library=0)
    spell = card(eng, "Fog of War", zone=Zone.HAND)
    small = filler(eng, "Small", player="p2", power=3, toughness=3)
    big = filler(eng, "Big", player="p2", power=4, toughness=4)
    victim = filler(eng, "Victim", power=1, toughness=20)
    cast(eng, spell)
    eng.rules.deal_damage(victim, 3, source=small, combat=True)
    assert victim.damage_marked == 0
    eng.rules.deal_damage(victim, 4, source=big, combat=True)
    assert victim.damage_marked == 4
    eng.rules.deal_damage(victim, 3, source=small, combat=False)
    assert victim.damage_marked == 7


def test_other_creatures_shield_excludes_its_own_source():
    eng = game(library=0)
    other = filler(eng, "Other", player="p2", power=3, toughness=3)
    victim = filler(eng, "Victim", power=1, toughness=20)
    frog = card(eng, "Haze Frog", zone=Zone.HAND)
    cast(eng, frog)  # "When ~ enters, prevent all combat damage that other creatures would deal this turn."
    frog = next(o for o in eng.state.battlefield if o.name == "Haze Frog")
    eng.rules.deal_damage(victim, 3, source=other, combat=True)
    assert victim.damage_marked == 0
    eng.rules.deal_damage(victim, 2, source=frog, combat=True)
    assert victim.damage_marked == 2  # "other": the Frog's own combat damage is not covered


def test_union_of_colors_shield_stops_both_colors():
    eng = game(library=0)
    spell = card(eng, "Luminesce", zone=Zone.HAND)
    red = filler(eng, "Red", player="p2", power=2, toughness=2, mana_cost_string="{R}")
    black = filler(eng, "Black", player="p2", power=2, toughness=2, mana_cost_string="{B}")
    green = filler(eng, "Green", player="p2", power=2, toughness=2, mana_cost_string="{G}")
    victim = filler(eng, "Victim", power=1, toughness=20)
    cast(eng, spell)
    eng.rules.deal_damage(victim, 2, source=red)
    eng.rules.deal_damage(victim, 2, source=black)
    assert victim.damage_marked == 0
    eng.rules.deal_damage(victim, 2, source=green)
    assert victim.damage_marked == 2


def test_chosen_source_shield_covers_only_that_source():
    eng = game(library=0)
    spell = card(eng, "Pay No Heed", zone=Zone.HAND)
    a = filler(eng, "A", player="p2", power=5, toughness=5)
    c = filler(eng, "C", player="p2", power=5, toughness=5)
    victim = filler(eng, "Victim", power=2, toughness=9)
    cast(eng, spell)
    answer(eng, pick=lambda choice: next(str(o["id"]) for o in choice["options"] if str(a.instance_id) == str(o["id"])))
    eng.rules.deal_damage(victim, 3, source=a)
    eng.rules.deal_damage(victim, 3, source=a)
    assert victim.damage_marked == 0
    eng.rules.deal_damage(victim, 3, source=c)
    assert victim.damage_marked == 3


# --- recipients: creature classes, "you", players and planeswalkers ---------------------------------------------------------

@pytest.mark.parametrize("text,params", [
    ("Prevent all damage that would be dealt this turn to creatures you control.",
     {"amount": "all", "recipient_creatures_scope": "you_control",
      "recipient_filter": {"object_filter": {"card_type": "creature"}}}),
    ("Prevent all combat damage that would be dealt this turn to dogs you control.",
     {"amount": "all", "recipient_creatures_scope": "you_control",
      "recipient_filter": {"object_filter": {"subtype": "dog"}}, "source_filter": {"combat": True}}),
    ("Prevent all combat damage that would be dealt to you this turn.", None),   # the older unqualified row's
    ("Prevent all noncombat damage that would be dealt to you and planeswalkers you control this turn.",
     {"amount": "all", "source_filter": {"combat": False}, "recipient_scope": "planeswalkers"}),
    ("Prevent the next 1 combat damage that would be dealt to you this turn.",
     {"amount": 1, "source_filter": {"combat": True}}),
    ("Prevent the next 2 damage that would be dealt to target player or planeswalker this turn.",
     {"amount": 2, "target_kind": "player_or_planeswalker"}),
])
def test_recipient_shield_spec(text, params):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    if params is not None:
        assert _effects(result)[0] == ("prevent_damage_shield", params)


def test_land_subtype_recipient_is_not_a_creature_class():
    assert not _parse("Prevent all damage that would be dealt this turn to forests you control.").modeled


def test_creature_class_shield_covers_only_that_class_and_controller():
    eng = game(library=0)
    spell = card(eng, "Divine Light", zone=Zone.HAND)
    mine = filler(eng, "Mine", power=1, toughness=9)
    theirs = filler(eng, "Theirs", player="p2", power=1, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    cast(eng, spell)
    eng.rules.deal_damage(mine, 3, source=src)
    eng.rules.deal_damage(theirs, 3, source=src)
    assert (mine.damage_marked, theirs.damage_marked) == (0, 3)


def test_combat_only_shield_to_you_lets_noncombat_damage_through():
    eng = game(library=0)
    spell = card(eng, "Druid's Deliverance", zone=Zone.HAND)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell)
    eng.rules.deal_damage(me, 4, source=src, combat=True)
    assert me.life == life
    eng.rules.deal_damage(me, 2, source=src, combat=False)
    assert me.life == life - 2


def test_budgeted_combat_shield_runs_out():
    eng = game(library=0)
    griffin = card(eng, "Decorated Griffin")
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    me = eng.state.player_by_id("p1")
    life = me.life
    _fund(eng)
    activate(eng, griffin, 0)
    eng.rules.deal_damage(me, 3, source=src, combat=True)
    assert me.life == life - 2  # 1 prevented
    eng.rules.deal_damage(me, 1, source=src, combat=False)
    assert me.life == life - 3
