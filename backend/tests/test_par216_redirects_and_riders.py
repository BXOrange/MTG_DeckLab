"""PAR-216 axis C: one-shot redirects, excess damage, prevented-damage riders and "can't be prevented" (RULE 120.4a, 603.7,
614.1, 615.12, 616.1).

Parse tests pin the specs and the refusals; execution tests resolve the real cards against the real engine.
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


def _run_to_end_step(eng):
    for _ in range(40):
        if eng.state.current_step == "end" and not eng.state.delayed_triggers:
            return
        eng.advance_step()
        eng.resolve_until_stable()


# --- parse -----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,params", [
    ("The next 1 damage that would be dealt to ~ this turn is dealt to target creature instead.",
     {"amount": 1, "protected": "self", "recipient": "target", "target_kind": "creature"}),
    ("The next 2 damage that would be dealt to target white creature this turn is dealt to ~ instead.",
     {"amount": 2, "protected": "target", "recipient": "self", "target_kind": "creature", "creature_filter": {"color": "W"}}),
    ("The next time damage would be dealt to ~ this turn, that damage is dealt to any target instead.",
     {"amount": "all", "protected": "self", "recipient": "target", "target_kind": "any", "once": True}),
    ("All combat damage that would be dealt to you this turn is dealt to target attacking creature instead.",
     {"amount": "all", "protected": "you", "recipient": "target", "target_kind": "creature", "combat_only": True,
      "creature_filter": {"attacking": True}}),
    ("All combat damage that would be dealt to you by unblocked creatures this turn is dealt to ~ instead.",
     {"amount": "all", "protected": "you", "recipient": "self", "combat_only": True,
      "source_filter": {"unblocked": True}}),
])
def test_redirect_clause_spec(text, params):
    result = _parse(text)
    assert result.modeled, result.unclaimed
    assert _effects(result)[0] == ("redirect_damage_shield", params)


@pytest.mark.parametrize("text", [
    # two announced targets must be different objects ("another")
    "The next 1 damage that would be dealt to target creature this turn is dealt to target creature instead.",
    # a pronoun with no referent
    "All damage that would be dealt to it this turn is dealt to target creature instead.",
    "The next 1 damage that would be dealt to a mystery this turn is dealt to ~ instead.",
])
def test_redirect_clause_is_not_over_claimed(text):
    assert not _parse(text).modeled


def test_excess_damage_and_unpreventable_riders_parse():
    excess = _parse("~ deals 5 damage to target creature. Excess damage is dealt to that creature's controller instead.",
                    "Instant")
    assert excess.modeled and _effects(excess)[0][1]["excess_to_controller"] is True
    quiet = _parse("~ deals 4 damage to target creature. The damage can't be prevented.")
    assert quiet.modeled and _effects(quiet)[0][1]["unpreventable"] is True
    # a divided or non-creature damage clause is not "that creature"
    assert not _parse("~ deals 5 damage to any target. Excess damage is dealt to that creature's controller instead.").modeled


@pytest.mark.parametrize("name", [
    "Flame Spill", "Pigment Storm", "Pinpoint Avalanche", "Zealous Inquisitor", "Zhalfirin Crusader",
    "Mirrorwood Treefolk", "Glarecaster", "Daughter of Autumn", "Hazduhr the Abbot", "Vassal's Duty", "Ward of Piety",
    "Sivvi's Valor", "Turn the Tables", "Saving Grace", "Kjeldoran Royal Guard", "Comeuppance", "Brace for Impact",
    "Sacred Boon", "Scars of the Veteran", "Healing Grace", "Leyline of Punishment", "Sunspine Lynx",
])
def test_cards_are_modeled(name):
    assert _modeled(name)


# --- execution: redirects ------------------------------------------------------------------------------------------------

def test_redirect_budget_splits_a_larger_hit():
    eng = game(library=0)
    elder = card(eng, "Hazduhr the Abbot")
    white = filler(eng, "White", power=2, toughness=9, mana_cost_string="{W}")
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    _fund(eng)
    activate(eng, elder, 0, targets=[white], x=3)
    eng.rules.deal_damage(white, 2, source=src)
    eng.rules.deal_damage(white, 4, source=src)  # 1 left in the budget, 3 land on the protected creature
    assert (white.damage_marked, elder.damage_marked) == (3, 3)


def test_next_time_redirect_moves_one_whole_event_then_ends():
    eng = game(library=0)
    tree = card(eng, "Mirrorwood Treefolk")
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    foe = eng.state.player_by_id("p2")
    life = foe.life
    _fund(eng)
    activate(eng, tree, 0, targets=[foe])
    eng.rules.deal_damage(tree, 3, source=src)
    eng.rules.deal_damage(tree, 2, source=src)
    assert foe.life == life - 3 and tree.damage_marked == 2


def test_redirect_to_a_target_creature_keeps_the_original_for_the_remainder():
    eng = game(library=0)
    inq = card(eng, "Zealous Inquisitor")
    bear = filler(eng, "Bear", power=2, toughness=9)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    _fund(eng)
    activate(eng, inq, 0, targets=[bear])
    eng.rules.deal_damage(inq, 3, source=src)
    assert (inq.damage_marked, bear.damage_marked) == (2, 1)


def test_combat_only_redirect_sends_combat_damage_to_the_attacker():
    eng = game(library=0)
    spell = card(eng, "Turn the Tables", zone=Zone.HAND)
    atk = filler(eng, "Atk", player="p2", power=4, toughness=9)
    atk.attacking = True
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell, targets=[atk])
    eng.rules.deal_damage(me, 3, source=atk, combat=True)
    eng.rules.deal_damage(me, 2, source=atk, combat=False)
    assert me.life == life - 2 and atk.damage_marked == 3


def test_unblocked_redirect_ignores_blocked_attackers():
    eng = game(library=0)
    guard = card(eng, "Kjeldoran Royal Guard")
    free = filler(eng, "Free", player="p2", power=5, toughness=5)
    free.attacking = True
    stopped = filler(eng, "Stopped", player="p2", power=3, toughness=5)
    stopped.attacking = True
    stopped.blocked_by = [999]
    me = eng.state.player_by_id("p1")
    life = me.life
    _fund(eng)
    activate(eng, guard, 0)
    eng.rules.deal_damage(me, 5, source=free, combat=True)
    eng.rules.deal_damage(me, 3, source=stopped, combat=True)
    assert me.life == life - 3 and guard.damage_marked == 5


# --- execution: riders ---------------------------------------------------------------------------------------------------

def test_flame_spill_sends_only_the_excess_to_the_controller():
    eng = game(library=0)
    spell = card(eng, "Flame Spill", zone=Zone.HAND)
    bear = filler(eng, "Bear", player="p2", power=2, toughness=2)
    foe = eng.state.player_by_id("p2")
    life = foe.life
    cast(eng, spell, targets=[bear])
    assert bear.zone == Zone.GRAVEYARD and foe.life == life - 2


def test_excess_counts_damage_already_marked():
    eng = game(library=0)
    spell = card(eng, "Pigment Storm", zone=Zone.HAND)
    bear = filler(eng, "Bear", player="p2", power=2, toughness=6)
    bear.damage_marked = 4
    foe = eng.state.player_by_id("p2")
    life = foe.life
    cast(eng, spell, targets=[bear])
    assert foe.life == life - 3  # 5 damage, 2 left to lethal


def test_comeuppance_punishes_by_source_type():
    eng = game(library=0)
    spell = card(eng, "Comeuppance", zone=Zone.HAND)
    ogre = filler(eng, "Ogre", player="p2", power=4, toughness=9)
    rock = filler(eng, "Rock", type_line="Artifact", player="p2")
    mine = filler(eng, "Mine", power=1, toughness=9)
    me = eng.state.player_by_id("p1")
    foe = eng.state.player_by_id("p2")
    life, foe_life = me.life, foe.life
    cast(eng, spell)
    eng.rules.deal_damage(me, 3, source=ogre)
    eng.rules.deal_damage(me, 2, source=rock)
    assert me.life == life
    assert ogre.damage_marked == 3 and foe.life == foe_life - 2
    eng.rules.deal_damage(mine, 1, source=ogre)  # creatures are not "you and planeswalkers you control"
    assert mine.damage_marked == 1


def test_brace_for_impact_puts_a_counter_for_each_point_prevented():
    eng = game(library=0)
    spell = card(eng, "Brace for Impact", zone=Zone.HAND)
    bear = filler(eng, "Bear", power=2, toughness=2, mana_cost_string="{W}{U}")
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    cast(eng, spell, targets=[bear])
    eng.rules.deal_damage(bear, 3, source=src)
    assert bear.damage_marked == 0 and bear.plus_one_counters == 3


def test_sacred_boon_counters_arrive_at_the_next_end_step():
    eng = game(library=0)
    spell = card(eng, "Sacred Boon", zone=Zone.HAND)
    bear = filler(eng, "Bear", power=2, toughness=2)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    cast(eng, spell, targets=[bear])
    eng.rules.deal_damage(bear, 2, source=src)
    assert bear.damage_marked == 0 and not bear.counters.get("+0/+1")
    _run_to_end_step(eng)
    assert bear.counters.get("+0/+1") == 2


def test_scars_of_the_veteran_gives_nothing_for_a_player():
    eng = game(library=0)
    spell = card(eng, "Scars of the Veteran", zone=Zone.HAND)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    me = eng.state.player_by_id("p1")
    life = me.life
    cast(eng, spell, targets=[me])
    eng.rules.deal_damage(me, 5, source=src)
    assert me.life == life
    _run_to_end_step(eng)  # "if it's a creature": nothing happens for a player


# --- execution: "can't be prevented" --------------------------------------------------------------------------------------

def test_leyline_of_punishment_switches_prevention_off():
    eng = game(library=0)
    src = filler(eng, "Src", player="p2", power=4, toughness=4)
    bear = filler(eng, "Bear", power=2, toughness=9)
    muzzle = card(eng, "Muzzle")
    muzzle.attached_to = src.instance_id
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(bear, 2, source=src)
    assert bear.damage_marked == 0
    card(eng, "Leyline of Punishment")
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(bear, 2, source=src)
    assert bear.damage_marked == 2


@pytest.mark.parametrize("text,params", [
    ("Damage that would be dealt by ~ can't be prevented.", {"source": "self"}),
    ("Combat damage can't be prevented.", {"combat_only": True}),
    ("Combat damage that would be dealt by creatures you control can't be prevented.",
     {"combat_only": True, "source": "your_creatures"}),
    ("Damage can't be prevented.", {}),
])
def test_unpreventable_static_scopes_parse(text, params):
    result = _parse(text, "Creature")
    assert result.modeled, result.unclaimed
    assert _effects(result) == [("damage_cant_be_prevented", params)]


def test_unpreventable_source_is_scoped_to_its_own_permanent():
    eng = game(library=0)
    brute = card(eng, "Excruciator")
    other = filler(eng, "Other", player="p1", power=3, toughness=3)
    victim = filler(eng, "Victim", player="p2", power=1, toughness=20)
    for source in (brute, other):
        shield = card(eng, "Muzzle", player="p2")  # "prevent all damage dealt by enchanted creature"
        shield.attached_to = source.instance_id
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(victim, 3, source=brute)
    assert victim.damage_marked == 3  # Excruciator's damage can't be prevented
    eng.rules.deal_damage(victim, 3, source=other)
    assert victim.damage_marked == 3  # any other source is still prevented


def test_combat_scope_leaves_noncombat_prevention_alone():
    eng = game(library=0)
    card(eng, "Frenzied Baloth")
    src = filler(eng, "Src", player="p2", power=3, toughness=3)
    victim = filler(eng, "Victim", power=1, toughness=20)
    muzzle = card(eng, "Muzzle")
    muzzle.attached_to = src.instance_id
    eng.recompute_continuous_effects()
    eng.rules.deal_damage(victim, 2, source=src, combat=False)
    assert victim.damage_marked == 0
    eng.rules.deal_damage(victim, 2, source=src, combat=True)
    assert victim.damage_marked == 2
