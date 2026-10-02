"""PAR-107…114 residue batches, part 8 — single-card shapes closed by widening a row (PAR-107/108): Prison Break's
"with an additional +1/+1 counter" (the same counter as "with a +1/+1 counter"; also Evil Reawakened, Generous Revival,
Rakdos Joins Up), Sister of Silence's typed spell-or-ability counter, and Terisian Mindbreaker's "defending player
mills half their library, rounded up".

Reference: parser/oracle/catalogue/handlers.py, game/targeting.py (`spell_or_ability` + `spell_filter`),
game/effects/stack.py (`MillEffect.selector == "defending_player"`).
"""

from __future__ import annotations

from mtg_analyzer.game import targeting
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.models.game.game_state import StackItem
from mtg_analyzer.parser.oracle.gate import parse_oracle


def _card(name, type_line, text="", **kw):
    creature = "Creature" in type_line
    return Card(
        id=name, name=name, type_line=type_line, oracle_text=text, is_creature=creature,
        is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
        power=2 if creature else None, toughness=2 if creature else None, **kw,
    )


def _engine():
    eng = GameEngine.new_game([("p1", "Alice", []), ("p2", "Bob", [])], starting_life=20, starting_hand=0)
    eng.begin_turn()
    eng.state.current_step = "main1"
    return eng


def _put(eng, card, controller="p1", zone=Zone.BATTLEFIELD):
    obj = GameObject(card, owner_id=controller, zone=zone)
    obj.controller_id = controller
    obj.summoning_sick = False
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        eng.state.add_to_battlefield(obj)
    else:
        eng.state.player_by_id(controller).add_to_zone(obj, zone)
    return obj


def _push_spell(eng, controller, card):
    obj = GameObject(card, owner_id=controller, zone=Zone.STACK)
    eng.state.stack.append(StackItem(kind="spell", controller_id=controller, obj=obj, description=card.name,
                                     effects=[], targets=[]))
    return obj


def test_prison_break_returns_the_creature_with_an_extra_counter():
    text = "Return target creature card from your graveyard to the battlefield with an additional +1/+1 counter on it."
    card = _card("Prison Break", "Sorcery", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    dead = _put(eng, _card("Bear", "Creature — Bear"), zone=Zone.GRAVEYARD)
    spell = _put(eng, card, zone=Zone.HAND)
    eng.cast_spell(p1, spell, targets=[dead])
    eng.resolve_until_stable()
    assert dead.zone == Zone.BATTLEFIELD and dead.counters.get("+1/+1") == 1


def test_sister_of_silence_counters_instants_sorceries_and_abilities_but_not_creature_spells():
    text = "When ~ enters, counter target instant spell, sorcery spell, activated ability, or triggered ability."
    sister_card = _card("Sister of Silence", "Creature — Human Cleric", text)
    result = parse_oracle(sister_card)
    assert result.modeled, result.unclaimed
    eng = _engine()
    sister = _put(eng, sister_card)
    _push_spell(eng, "p2", _card("Bolt", "Instant"))
    _push_spell(eng, "p2", _card("Wrath", "Sorcery"))
    _push_spell(eng, "p2", _card("Bear", "Creature — Bear"))
    eng.state.stack.append(StackItem(kind="ability", controller_id="p2", source=sister, description="Some ability",
                                     effects=[], targets=[]))
    effect = next(e for s in result.specs for e in s.effects if e.type == "counter")
    assert effect.params == {"target_kind": "spell_or_ability", "card_types": ["instant", "sorcery"]}
    from mtg_analyzer.game.binding.core import build_effects

    [built] = build_effects([effect], sister)
    names = {o["name"] for o in targeting.legal_targets(eng.state, "p1", built.target_spec, sister)}
    assert names == {"Bolt", "Wrath", "Some ability"}


def test_terisian_mindbreaker_mills_half_the_defenders_library_rounded_up():
    text = "Whenever ~ attacks, defending player mills half their library, rounded up."
    card = _card("Terisian Mindbreaker", "Creature — Human Wizard", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    for i in range(5):
        p2.library.append(GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"), owner_id="p2", zone=Zone.LIBRARY))
    mind = _put(eng, card)
    eng.state.current_step = "declare_attackers"
    eng.declare_attackers(eng.state.player_by_id("p1"), [{"attacker": mind, "defender": None}])
    eng.resolve_until_stable()
    assert len(p2.library) == 2 and len(p2.graveyard) == 3  # half of 5, rounded up


def test_open_the_vaults_returns_every_players_artifacts_and_enchantments_under_their_owners():
    text = "Return all artifact and enchantment cards from all graveyards to the battlefield under their owners' control."
    card = _card("Open the Vaults", "Sorcery", text)
    assert parse_oracle(card).modeled
    eng = _engine()
    p1 = eng.state.player_by_id("p1")
    mine = _put(eng, _card("My Rock", "Artifact"), zone=Zone.GRAVEYARD)
    theirs = _put(eng, _card("Their Aura", "Enchantment — Aura"), controller="p2", zone=Zone.GRAVEYARD)
    bear = _put(eng, _card("Dead Bear", "Creature — Bear"), controller="p2", zone=Zone.GRAVEYARD)
    spell = _put(eng, card, zone=Zone.HAND)
    eng.cast_spell(p1, spell)
    eng.resolve_until_stable()
    assert mine.zone == Zone.BATTLEFIELD and mine.controller_id == "p1"
    assert theirs.zone == Zone.BATTLEFIELD and theirs.controller_id == "p2"
    assert bear.zone == Zone.GRAVEYARD


def test_all_graveyards_without_owners_control_is_not_claimed():
    card = _card("Probe", "Sorcery", "Return all creature cards from all graveyards to the battlefield.")
    assert not parse_oracle(card).modeled


# --- "If its/that permanent's mana value was N or less, <effect>" after a targeting clause ----------------------


def _sorcery_with_target(eng, name, text, target, mv=2):
    card = _card(name, "Sorcery", text, mana_cost_string="{B}", converted_mana_cost=1)
    assert parse_oracle(card).modeled, parse_oracle(card).unclaimed
    spell = _put(eng, card, zone=Zone.HAND)
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"B": 3})
    eng.cast_spell(p1, spell, targets=[target])
    eng.resolve_until_stable()
    return spell


def _creature(eng, name, mv, controller="p2"):
    return _put(eng, _card(name, "Creature — Bear", converted_mana_cost=mv, mana_cost_string="{%d}" % mv), controller=controller)


def _foods(eng):
    return [o for o in eng.state.battlefield if o.name == "Food"]


def test_the_gate_reads_the_picks_printed_mana_value_even_after_it_left_the_battlefield():
    text = "Destroy target artifact or creature. If its mana value was 4 or less, create a Food token."
    for mv, foods in ((3, 1), (6, 0)):
        eng = _engine()
        target = _creature(eng, f"Bear{mv}", mv)
        _sorcery_with_target(eng, "Tainted Treats", text, target)
        assert target.zone == Zone.GRAVEYARD and len(_foods(eng)) == foods, mv


def test_vindictive_triumph_returns_only_a_cheap_creature_under_your_control():
    text = ("Exile target creature or planeswalker. If that permanent's mana value was 3 or less, return it to the "
            "battlefield tapped under your control. Exile it at the beginning of the next end step.")
    eng = _engine()
    cheap, dear = _creature(eng, "Cheap", 2), _creature(eng, "Dear", 5)
    _sorcery_with_target(eng, "Vindictive Triumph", text, cheap)
    assert cheap.zone == Zone.BATTLEFIELD and cheap.controller_id == "p1" and cheap.tapped
    assert len(eng.state.delayed_triggers) == 1  # "exile it at the beginning of the next end step"
    eng2 = _engine()
    dear = _creature(eng2, "Dear", 5)
    _sorcery_with_target(eng2, "Vindictive Triumph", text, dear)
    assert dear.zone == Zone.EXILE


def test_shattered_ego_puts_the_enchanted_creature_third_from_the_top():
    text = "Enchant creature\n{3}{U}{U}: Put enchanted creature into its owner's library third from the top."
    aura_card = _card("Shattered Ego", "Enchantment — Aura", text)
    assert parse_oracle(aura_card).modeled
    eng = _engine()
    p2 = eng.state.player_by_id("p2")
    deep = [GameObject(Card(id=f"L{i}", name=f"L{i}", type_line="Land"), owner_id="p2", zone=Zone.LIBRARY)
            for i in range(4)]
    for card in deep:
        p2.library.append(card)
    victim = _put(eng, _card("Victim", "Creature — Bear"), controller="p2")
    aura = _put(eng, aura_card)
    aura.attached_to = victim.instance_id
    p1 = eng.state.player_by_id("p1")
    p1.mana_pool.add_many({"U": 5})
    eng.activate_ability(p1, aura, 0)
    eng.resolve_until_stable()
    assert victim.zone == Zone.LIBRARY and p2.library[-3] is victim


def test_temporary_lockdown_exiles_cheap_nonland_permanents_until_it_leaves():
    text = ("When ~ enters, exile each nonland permanent with mana value 2 or less until ~ leaves the battlefield.")
    card = _card("Temporary Lockdown", "Enchantment", text, converted_mana_cost=3, mana_cost_string="{1}{W}{W}")
    assert parse_oracle(card).modeled
    eng = _engine()
    cheap = _put(eng, _card("Cheap", "Creature — Bear", converted_mana_cost=2, mana_cost_string="{1}{G}"), controller="p2")
    mine = _put(eng, _card("Mine", "Creature — Bear", converted_mana_cost=1, mana_cost_string="{G}"))
    dear = _put(eng, _card("Dear", "Creature — Bear", converted_mana_cost=5, mana_cost_string="{4}{G}"), controller="p2")
    land = _put(eng, _card("Forest", "Basic Land — Forest", converted_mana_cost=0), controller="p2")
    prison = _put(eng, card)
    eng.state.fire_event(GameEvent(
        EventType.ENTERS_BATTLEFIELD, instance_id=prison.instance_id, controller_id="p1",
        object_types=["enchantment"], object="Temporary Lockdown"))
    eng.resolve_until_stable()
    assert cheap.zone == Zone.EXILE and mine.zone == Zone.EXILE
    assert dear.zone == Zone.BATTLEFIELD and land.zone == Zone.BATTLEFIELD
    # the enchantment leaves: everything it took comes back under its owner's control
    eng.rules.put_into_graveyard(prison)
    eng.resolve_until_stable()
    assert cheap.zone == Zone.BATTLEFIELD and cheap.controller_id == "p2"
    assert mine.zone == Zone.BATTLEFIELD and mine.controller_id == "p1"
