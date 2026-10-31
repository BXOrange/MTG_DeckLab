"""PAR-216 axis A: standing prevention and redirection over the shared object phrase (RULE 614.1, 615.1, 616.1).

"Prevent all [combat|noncombat] damage that would be dealt to / by <object>" and "all damage that would be dealt to
<recipient> is dealt to <X> instead" on a permanent are replacement effects. Parse tests pin the spec; execution tests
bind the real card and push real damage events through the replacement loop.
"""
import pytest

from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.game_object import Zone
from mtg_analyzer.parser.oracle import parse_oracle
from mtg_analyzer.parser.oracle.catalogue.replacements import replacement_clause_specs
from tests.support.deck_batch import card, filler, game


def _specs(text):
    specs = replacement_clause_specs(text)
    return None if specs is None else [(s.type, s.params) for s in specs]


def _modeled(name):
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    return parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card(name)).modeled


def _attach(eng, name, host, player="p1"):
    aura = card(eng, name, player=player)
    aura.attached_to = host.instance_id
    eng.recompute_continuous_effects()
    return aura


# --- parse -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("prevent all combat damage that would be dealt to ~",
     [("prevent_damage", {"to": "self", "amount": "all", "source_filter": {"combat": True}})]),
    ("prevent all noncombat damage that would be dealt to equipped creature",
     [("prevent_damage", {"to": "attached_permanent", "amount": "all", "source_filter": {"combat": False}})]),
    ("prevent all damage that would be dealt by enchanted creature",
     [("prevent_damage", {"to": "any", "amount": "all", "source_filter": {"attached": True}})]),
    ("prevent all combat damage that would be dealt to and dealt by enchanted creature",
     [("prevent_damage", {"to": "attached_permanent", "amount": "all", "source_filter": {"combat": True}}),
      ("prevent_damage", {"to": "any", "amount": "all", "source_filter": {"attached": True, "combat": True}})]),
    ("prevent all combat damage that would be dealt to ~ by creatures it's blocking",
     [("prevent_damage", {"to": "self", "amount": "all",
                          "source_filter": {"blocked_by_self": True, "combat": True}})]),
    ("prevent all noncombat damage that would be dealt to you and creatures you control",
     [("prevent_damage", {"recipient_union": ["controller", {"card_type": "creature"}], "amount": "all",
                          "source_filter": {"combat": False}})]),
    ("prevent all damage that ~ would deal to snow creatures",
     [("prevent_damage", {"to": "all_creatures", "recipient_filter": {"snow": True, "card_type": "creature"},
                          "amount": "all", "source_filter": {"self_source": True}})]),
    ("if a source would deal 3 or less damage to ~, prevent that damage",
     [("prevent_damage", {"to": "self", "amount": "all", "source_filter": {"max_amount": 3}})]),
    ("if a creature would deal combat damage to you, prevent 1 of that damage",
     [("prevent_damage", {"to": "controller", "amount": 1,
                          "source_filter": {"object_filter": {"card_type": "creature"}, "combat": True}})]),
    ("all damage that would be dealt to you is dealt to ~ instead",
     [("redirect_damage", {"to": "controller", "redirect_to": "self"})]),
    ("all damage that would be dealt to you by artifacts is dealt to ~ instead",
     [("redirect_damage", {"to": "controller", "redirect_to": "self",
                           "source_filter": {"object_filter": {"card_type": "artifact"}}})]),
    ("all damage that would be dealt to enchanted creature is dealt to its controller instead",
     [("redirect_damage", {"to": "attached_permanent", "redirect_to": "recipient_controller"})]),
])
def test_standing_clause_spec(text, expected):
    assert _specs(text) == expected


@pytest.mark.parametrize("text", [
    "prevent all combat damage that would be dealt to a mystery",              # unknown recipient phrase
    "prevent all damage that would be dealt by creatures that sing loudly",  # unparsed source phrase
    "prevent all damage that would be dealt to ~ by something odd",
    "all damage that would be dealt to you is dealt to target creature instead",  # a target is not a standing slot
])
def test_standing_clause_is_not_over_claimed(text):
    assert _specs(text) is None


@pytest.mark.parametrize("name", [
    "Diamond Weapon", "General's Kabuto", "Magebane Armor", "Muzzle", "Candletrap", "Gaseous Form", "Fog Bank",
    "Wall of Vapor", "Armored Transport", "Crystal Barricade", "Dolmen Gate", "Indentured Oaf", "Callous Giant",
    "Hyperion, Supreme Hero", "Thunderstaff", "Empyrial Archangel", "Pariah", "Palisade Giant", "Treacherous Link",
    "Martyrs of Korlis", "Veteran Bodyguard",
])
def test_cards_are_modeled(name):
    assert _modeled(name)


# --- execution -------------------------------------------------------------------------------------------------------------

def test_aura_prevents_all_damage_dealt_by_its_host_only():
    eng = game(library=0)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    other = filler(eng, "Other", player="p2", power=3, toughness=3)
    bear = filler(eng, "Bear", power=2, toughness=9)
    _attach(eng, "Muzzle", ogre)
    eng.rules.deal_damage(bear, 4, source=ogre)
    assert bear.damage_marked == 0
    eng.rules.deal_damage(bear, 1, source=other)
    assert bear.damage_marked == 1


def test_combat_only_aura_lets_noncombat_damage_through():
    eng = game(library=0)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    bear = filler(eng, "Bear", power=2, toughness=9)
    _attach(eng, "Candletrap", ogre)
    eng.rules.deal_damage(bear, 2, source=ogre, combat=True)
    assert bear.damage_marked == 0
    eng.rules.deal_damage(bear, 1, source=ogre, combat=False)
    assert bear.damage_marked == 1


def test_to_and_dealt_by_aura_shields_both_directions_for_combat_damage_only():
    eng = game(library=0)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=4)
    bear = filler(eng, "Bear", power=2, toughness=9)
    _attach(eng, "Gaseous Form", ogre)
    eng.rules.deal_damage(bear, 2, source=ogre, combat=True)
    eng.rules.deal_damage(ogre, 2, source=bear, combat=True)
    assert (bear.damage_marked, ogre.damage_marked) == (0, 0)
    eng.rules.deal_damage(ogre, 2, source=bear, combat=False)
    assert ogre.damage_marked == 2


def test_blocker_prevents_damage_only_from_the_creature_it_blocks():
    eng = game(library=0)
    wall = card(eng, "Wall of Vapor")
    blocked = filler(eng, "Blocked", player="p2", power=4, toughness=4)
    free = filler(eng, "Free", player="p2", power=4, toughness=4)
    wall.blocking = blocked.instance_id
    eng.rules.deal_damage(wall, 4, source=blocked)
    assert wall.damage_marked == 0
    eng.rules.deal_damage(wall, 1, source=free)
    assert wall.damage_marked == 1


def test_noncombat_shield_covers_your_other_creatures_not_combat_damage():
    eng = game(library=0)
    tajic = card(eng, "Tajic, Legion's Edge")
    mine = filler(eng, "Mine", power=1, toughness=9)
    foe = filler(eng, "Foe", player="p2", power=1, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    eng.rules.deal_damage(mine, 2, source=src, combat=False)
    assert mine.damage_marked == 0
    eng.rules.deal_damage(mine, 2, source=src, combat=True)
    assert mine.damage_marked == 2
    eng.rules.deal_damage(foe, 2, source=src, combat=False)
    assert foe.damage_marked == 2  # not "you control"
    eng.rules.deal_damage(tajic, 2, source=src, combat=False)
    assert tajic.damage_marked == 2  # "other"


def test_damage_threshold_shield_prevents_only_small_hits():
    eng = game(library=0)
    giant = card(eng, "Callous Giant")
    src = filler(eng, "Src", player="p2", power=5, toughness=5)
    eng.rules.deal_damage(giant, 3, source=src)
    assert giant.damage_marked == 0
    eng.rules.deal_damage(giant, 4, source=src)
    assert giant.damage_marked == 4


def test_thunderstaff_trims_one_from_a_creatures_combat_damage_to_you():
    eng = game(library=0)
    card(eng, "Thunderstaff")
    me = eng.state.player_by_id("p1")
    src = filler(eng, "Src", player="p2", power=3, toughness=3)
    life = me.life
    eng.rules.deal_damage(me, 3, source=src, combat=True)
    assert me.life == life - 2


def test_redirect_to_self_moves_damage_to_you_and_other_permanents():
    eng = game(library=0)
    giant = card(eng, "Palisade Giant")
    bear = filler(eng, "Bear", power=2, toughness=2)
    src = filler(eng, "Src", player="p2", power=3, toughness=3)
    me = eng.state.player_by_id("p1")
    life = me.life
    eng.rules.deal_damage(me, 3, source=src)
    eng.rules.deal_damage(bear, 1, source=src)
    eng.rules.deal_damage(giant, 1, source=src)
    assert me.life == life and bear.damage_marked == 0 and giant.damage_marked == 5


def test_aura_redirect_sends_your_damage_to_the_host_and_is_not_a_prevention():
    eng = game(library=0)
    host = filler(eng, "Host", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=3, toughness=3)
    _attach(eng, "Pariah", host)
    me = eng.state.player_by_id("p1")
    life = me.life
    eng.state.damage_prevention_disabled = True  # "can't be prevented" must not stop a redirect (RULE 615 vs 616)
    eng.rules.deal_damage(me, 3, source=src)
    assert me.life == life and host.damage_marked == 3


def test_treacherous_link_sends_the_hosts_damage_to_its_controller():
    eng = game(library=0)
    host = filler(eng, "Host", player="p2", power=2, toughness=9)
    src = filler(eng, "Src", power=3, toughness=3)
    _attach(eng, "Treacherous Link", host)
    foe = eng.state.player_by_id("p2")
    life = foe.life
    eng.rules.deal_damage(host, 3, source=src)
    assert foe.life == life - 3 and host.damage_marked == 0


def test_redirect_only_applies_to_the_named_source_class():
    eng = game(library=0)
    priest = card(eng, "Martyrs of Korlis")
    rock = filler(eng, "Rock", type_line="Artifact", player="p2")
    ogre = filler(eng, "Ogre", player="p2", power=3, toughness=3)
    me = eng.state.player_by_id("p1")
    life = me.life
    eng.rules.deal_damage(me, 2, source=rock)
    assert me.life == life and priest.damage_marked == 2
    eng.rules.deal_damage(me, 2, source=ogre)
    assert me.life == life - 2


def test_chosen_color_aura_prevents_only_damage_from_sources_of_that_color():
    eng = game(library=0)
    host = filler(eng, "Host", power=2, toughness=9)
    red = filler(eng, "Red", player="p2", power=3, toughness=3, mana_cost_string="{R}")
    green = filler(eng, "Green", player="p2", power=3, toughness=3, mana_cost_string="{G}")
    ward = _attach(eng, "Prismatic Ward", host)
    ward.chosen_color = "R"
    eng.rules.deal_damage(host, 3, source=red)
    assert host.damage_marked == 0
    eng.rules.deal_damage(host, 2, source=green)
    assert host.damage_marked == 2
