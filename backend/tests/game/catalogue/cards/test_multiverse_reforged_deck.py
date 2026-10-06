"""Gameplay regressions for Multiverse Reforged."""
import pytest

from mtg_analyzer.config import DB_PATH
from mtg_analyzer.game import combat, continuous
from mtg_analyzer.game.binding.core import bind_from_catalogue
from mtg_analyzer.game.game_engine import GameEngine
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.models.game.events import EventType, GameEvent
from mtg_analyzer.models.game.game_object import GameObject, Zone
from mtg_analyzer.services.card_database import CardDatabase


def _game(players=2, library=10):
    forest = CardDatabase(DB_PATH).get_card("Forest")
    engine = GameEngine.new_game([(f"p{i+1}", str(i), [forest] * library) for i in range(players)],
                                 starting_hand=0, starting_life=20)
    engine.advance_step()
    return engine


def _card(engine, name, player="p1", zone=Zone.BATTLEFIELD):
    card = CardDatabase(DB_PATH).get_card(name)
    if name == 'Ginger, Queen of Sweets':
        card = Card(id='ginger', name=name, type_line='Legendary Artifact Creature — Food Noble',
                    is_creature=True, power=6, toughness=4, mana_cost_string='{6}',
                    oracle_text="When Ginger enters, you become the monarch.\n{2}, {T}, Sacrifice Ginger: You gain 6 life.\n"
                                "At the beginning of each upkeep, if you're the monarch, create a Gingerbrute token.")
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _filler(engine, name="Filler", type_line="Creature", player="p1", mv=0, power=None, toughness=None,
            zone=Zone.BATTLEFIELD, **kw):
    card = Card(id=name, name=name, type_line=type_line, converted_mana_cost=mv,
                is_creature="Creature" in type_line, is_land="Land" in type_line,
                is_instant="Instant" in type_line, is_sorcery="Sorcery" in type_line,
                power=power, toughness=toughness, mana_cost_string=kw.pop("mana_cost_string", "{%d}" % mv if mv else ""),
                mana_cost={"generic": mv} if mv else {}, **kw)
    obj = GameObject(card, owner_id=player, zone=zone)
    obj.controller_id = player
    bind_from_catalogue(obj)
    if zone == Zone.BATTLEFIELD:
        engine.state.add_to_battlefield(obj)
        obj.summoning_sick = False
        engine.recompute_continuous_effects()
    else:
        engine.state.player_by_id(player).add_to_zone(obj, zone)
    return obj


def _cast(engine, card, pool, targets=None, groups=None, **kw):
    p = engine.state.player_by_id(card.controller_id)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    p.mana_pool.add_many(pool)
    engine.cast_spell(p, card, targets=targets, target_groups=groups, **kw)
    engine.resolve_until_stable()


def _activate(engine, source, index=0, targets=None, player="p1", **kw):
    p = engine.state.player_by_id(player)
    engine.state.current_phase = "main"
    engine.state.current_step = "main1"
    engine.activate_ability(p, source, index, targets=targets, **kw)
    engine.resolve_until_stable()


def _named(engine, name, player="p1"):
    return [o for o in engine.state.battlefield if o.name == name and o.controller_id == player]


def _answer(engine, pick=None, limit=12):
    """Answer pending choices: ``pick(choice)`` returns an option id (default the first option)."""
    for _ in range(limit):
        choice = engine.state.pending_choice
        if choice is None:
            return
        options = choice.get("options") or []
        answer = pick(choice) if pick is not None else None
        if answer is None:
            answer = str(options[0]["id"]) if options else "decline"
        engine.resolve_pending_choice(answer)


def _enter(engine, obj):
    engine.state.fire_event(GameEvent(EventType.ENTERS_BATTLEFIELD, controller_id=obj.controller_id,
                                      instance_id=obj.instance_id, object=obj.name,
                                      object_types=sorted(obj.type_words)))
    engine.resolve_until_stable()


def _step(engine, step, player="p1"):
    engine.state.current_step = step
    engine._fire_delayed_triggers(step)
    engine.state.fire_event(GameEvent(EventType.STEP_BEGIN, step=step, player_id=player, controller_id=player))
    engine.resolve_until_stable()


def _put_on_battlefield(engine, name, player="p1"):
    """Cast-free entry: the card enters the battlefield and its enters trigger fires."""
    obj = _card(engine, name, player, zone=Zone.HAND)
    p = engine.state.player_by_id(player)
    p.hand[:] = [o for o in p.hand if o is not obj]
    obj.zone = Zone.BATTLEFIELD
    engine.state.add_to_battlefield(obj)
    obj.summoning_sick = False
    _enter(engine, obj)
    return obj


#: A pool that pays for any of the deck's spells — the tests below care what resolves, not how it was paid for.
RICH = {"W": 5, "U": 5, "B": 5, "R": 5, "G": 5, "C": 15}







def test_brainsurge_controller_chooses_two_cards_and_their_order_off_turn():
    e = _game()
    e.state.active_player_index = 1
    spell = _card(e, 'Brainsurge', zone=Zone.HAND)
    kept = _filler(e, 'Keep', 'Instant', zone=Zone.HAND)
    first = _filler(e, 'First', 'Instant', zone=Zone.HAND)
    last = _filler(e, 'Last', 'Instant', zone=Zone.HAND)
    _cast(e, spell, RICH)
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice(str(first.instance_id))
    e.resolve_pending_choice(str(last.instance_id))
    p = e.state.player_by_id('p1')
    assert [o.name for o in p.library[-2:]] == ['First', 'Last']
    assert kept in p.hand and len(p.hand) == 5
    assert not e.state.player_by_id('p2').hand


def test_kher_keep_creates_the_printed_kobold():
    e = _game()
    land = _card(e, 'Kher Keep')
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    index = 0
    _activate(e, land, index)
    token = _named(e, 'Kobolds of Kher Keep')[0]
    assert (token.power, token.toughness) == (0, 1)
    assert continuous._has_subtype(token, 'Kobold') and token.colors == {'R'}
    assert land.tapped


def test_ginger_monarch_upkeep_and_sacrifice():
    e = _game()
    ginger = _put_on_battlefield(e, 'Ginger, Queen of Sweets')
    assert e.state.monarch_id == 'p1'
    e.state.active_player_index = 1
    _step(e, 'upkeep', 'p2')
    brute = _named(e, 'Gingerbrute')[0]
    assert brute.is_token and (brute.power, brute.toughness) == (1, 1)
    assert 'haste' in combat._obj_keywords(brute)
    assert len(brute.activated_abilities) >= 2
    e.state.monarch_id = 'p2'
    _step(e, 'upkeep', 'p2')
    assert len(_named(e, 'Gingerbrute')) == 1
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    before = e.state.player_by_id('p1').life
    _activate(e, ginger)
    assert ginger.zone == Zone.GRAVEYARD
    assert e.state.player_by_id('p1').life == before + 6


def test_restless_anchorage_animates_attacks_and_cleans_up():
    e = _game()
    land = _card(e, 'Restless Anchorage')
    e.state.player_by_id('p1').mana_pool.add_many(RICH)
    index = 0
    _activate(e, land, index)
    e.recompute_continuous_effects()
    assert land.is_creature and land.is_land and (land.power, land.toughness) == (2, 3)
    assert set(land.colors) == {'W', 'U'}
    assert 'flying' in combat._obj_keywords(land)
    land.tapped = False
    e.state.current_phase, e.state.current_step = 'combat', 'declare_attackers'
    e.declare_attackers(e.state.player_by_id('p1'), [
        {'attacker': land, 'defender': e.state.player_by_id('p2')}])
    e.resolve_until_stable()
    assert _named(e, 'Map')
    e.state.current_step = 'cleanup'
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert not land.is_creature and 'flying' not in combat._obj_keywords(land)
    assert not land._derived_colors


@pytest.mark.parametrize('x', [0, 4, 5])
def test_white_suns_twilight_x_and_created_token_exemption(x):
    e = _game()
    spell = _card(e, "White Sun's Twilight", zone=Zone.HAND)
    ours = _filler(e, 'Ours', power=2, toughness=2)
    theirs = _filler(e, 'Theirs', player='p2', power=2, toughness=2)
    _cast(e, spell, RICH, x=x)
    p = e.state.player_by_id('p1')
    assert p.life == 20 + x
    mites = _named(e, 'Phyrexian Mite')
    assert len(mites) == x
    for token in mites:
        assert "artifact" in token.type_words and (token.power, token.toughness) == (1, 1)
        assert token.parametric_keywords.get('toxic') == {'n': 1}
        assert 'cant_block' in combat._obj_keywords(token)
    assert (ours.zone == Zone.GRAVEYARD) == (x >= 5)
    assert (theirs.zone == Zone.GRAVEYARD) == (x >= 5)


def test_archfiend_doubles_each_opponents_own_loss_and_prohibits_their_gains():
    e = _game(players=3)
    _card(e, 'Archfiend of Despair')
    p1, p2, p3 = e.state.players
    e.rules.lose_life(p2, 3)
    e.rules.lose_life(p3, 5)
    e.rules.gain_life(p1, 2)
    e.rules.gain_life(p2, 7)
    e.rules.gain_life(p3, 7)
    assert (p1.life, p2.life, p3.life) == (22, 17, 15)
    _step(e, 'end', 'p2')
    assert (p1.life, p2.life, p3.life) == (22, 14, 10)


def test_archon_opponent_chooses_sacrifice_then_discard_before_controller_draw():
    e = _game(players=3)
    p1, p2, p3 = e.state.players
    victim = _filler(e, 'Victim', player='p2', power=2, toughness=2)
    spared = _filler(e, 'Spared', player='p2', power=2, toughness=2)
    discarded = _filler(e, 'Discard', 'Instant', player='p2', zone=Zone.HAND)
    _filler(e, 'Keep in hand', 'Instant', player='p2', zone=Zone.HAND)
    archon = _put_on_battlefield(e, 'Archon of Cruelty')
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert e.state.pending_choice['player_id'] == 'p2'
    assert p1.life == 20 and not p1.hand
    e.resolve_pending_choice(str(victim.instance_id))
    assert e.state.pending_choice['player_id'] == 'p2'
    e.resolve_pending_choice(str(discarded.instance_id))
    e.resolve_until_stable()
    assert victim.zone == discarded.zone == Zone.GRAVEYARD
    assert spared.zone == Zone.BATTLEFIELD
    assert (p1.life, p2.life, p3.life) == (23, 17, 20)
    assert len(p1.hand) == 1
    assert archon.zone == Zone.BATTLEFIELD


def test_archon_without_creatures_still_discards_and_loses_life():
    e = _game()
    _put_on_battlefield(e, 'Archon of Cruelty')
    e.resolve_pending_choice('p2')
    e.resolve_until_stable()
    assert not e.state.pending_choice
    assert e.state.player_by_id('p1').life == 23
    assert e.state.player_by_id('p2').life == 17


def test_niv_optional_life_payment_uses_the_amount_of_that_life_gain():
    e = _game()
    niv = _filler(e, 'Niv-Mizzet, Ghost Counsel', 'Legendary Creature — Spirit Dragon',
                  power=6, toughness=6, oracle_text='Flying', keywords=['Flying'])
    p = e.state.player_by_id('p1')
    e.rules.gain_life(p, 3)
    e.resolve_until_stable()
    assert e.state.pending_choice['player_id'] == 'p1'
    _answer(e)
    assert p.life == 20 and len(p.hand) == 3
    e.rules.gain_life(p, 2)
    e.resolve_until_stable()
    e.resolve_pending_choice('decline')
    assert p.life == 22 and len(p.hand) == 3
    _activate(e, niv)
    _answer(e)
    assert p.life == 22 and len(p.hand) == 4
    assert e.state.player_by_id('p2').life == 19


def _fatehold(e):
    return _filler(e, 'Fatehold Charm', 'Instant', zone=Zone.HAND, mana_cost_string='{W}{U}')


def test_fatehold_draw_and_empower_creates_then_increments_jace():
    e = _game()
    _cast(e, _fatehold(e), RICH, mode=[0])
    _answer(e)
    p = e.state.player_by_id('p1')
    assert len(p.hand) == 1
    jace = _named(e, 'Jace')[0]
    assert jace.is_planeswalker and jace.counters['loyalty'] == 2
    assert len(jace.activated_abilities) == 2
    _cast(e, _fatehold(e), RICH, mode=[0])
    _answer(e)
    assert jace.counters['loyalty'] == 4 and len(_named(e, 'Jace')) == 1


def test_fatehold_bounces_a_creature():
    e = _game()
    victim = _filler(e, 'Victim', player='p2', power=2, toughness=2)
    _cast(e, _fatehold(e), RICH, targets=[victim], mode=[1])
    assert victim.zone == Zone.HAND
    assert not e.state.player_by_id('p1').hand


def test_fatehold_pumps_only_our_creatures_until_cleanup():
    e = _game()
    ours = _filler(e, 'Ours', power=2, toughness=2)
    theirs = _filler(e, 'Theirs', player='p2', power=2, toughness=2)
    _cast(e, _fatehold(e), RICH, mode=[2])
    e.recompute_continuous_effects()
    assert (ours.power, ours.toughness) == (3, 4)
    assert (theirs.power, theirs.toughness) == (2, 2)
    e._step_cleanup()
    e.recompute_continuous_effects()
    assert (ours.power, ours.toughness) == (2, 2)


def test_fatehold_returns_a_spell_without_countering_it():
    e = _game()
    p2 = e.state.player_by_id('p2')
    spell = _filler(e, 'Response', 'Instant', player='p2', zone=Zone.HAND,
                    oracle_text='Draw a card.')
    e.state.current_phase, e.state.current_step = 'main', 'main1'
    e.cast_spell(p2, spell)
    item = e.state.stack[-1]
    _cast(e, _fatehold(e), RICH, targets=[item], mode=[1])
    assert spell.zone == Zone.HAND and spell in p2.hand
    assert len(p2.hand) == 1 and not e.state.stack


def _avacyn(e):
    return _filler(e, 'Avacyn, Angel of Horror', 'Legendary Creature — Angel', power=6, toughness=6,
                   oracle_text='Flying, deathtouch', keywords=['Flying', 'Deathtouch'])


def test_avacyn_returns_an_owned_opponents_creature_under_trigger_controllers_control():
    e = _game()
    avacyn = _avacyn(e)
    creature = _filler(e, 'Borrowed', player='p2', power=2, toughness=2)
    creature.controller_id = 'p1'
    e.rules.destroy(creature)
    e.resolve_until_stable()
    assert creature.zone == Zone.GRAVEYARD
    assert len(e.state.delayed_triggers) == 1
    avacyn.controller_id = 'p2'
    _step(e, 'end', 'p2')
    assert creature.zone == Zone.BATTLEFIELD and creature.controller_id == 'p1'


def test_avacyn_returns_itself_after_death():
    e = _game()
    avacyn = _avacyn(e)
    e.rules.destroy(avacyn)
    e.resolve_until_stable()
    assert avacyn.zone == Zone.GRAVEYARD
    _step(e, 'end')
    assert avacyn.zone == Zone.BATTLEFIELD


def test_avacyn_ignores_tokens_and_cards_that_changed_graveyard_incarnation():
    e = _game()
    _avacyn(e)
    token = _filler(e, 'Token', power=2, toughness=2)
    token.is_token = True
    creature = _filler(e, 'Other', power=2, toughness=2)
    e.rules.destroy(token)
    e.resolve_until_stable()
    assert not e.state.delayed_triggers
    e.rules.destroy(creature)
    e.resolve_until_stable()
    assert len(e.state.delayed_triggers) == 1
    e.rules.return_from_graveyard(creature)
    e.rules.destroy(creature)
    e.resolve_until_stable()
    # Two delayed triggers exist, but only the second still names this card.
    assert len(e.state.delayed_triggers) == 2
    e.state.delayed_triggers.pop()
    _step(e, 'end')
    assert creature.zone == Zone.GRAVEYARD


def test_fact_or_fiction_opponent_divides_and_controller_chooses():
    e = _game()
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Revealed {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    p1, p2 = e.state.players
    initial_library = list(p1.library)
    _cast(e, spell, RICH)
    assert e.state.pending_choice['player_id'] == 'p2'
    assert p1.library == initial_library
    e.resolve_pending_choice(str(cards[0].instance_id))
    e.resolve_pending_choice(str(cards[3].instance_id))
    e.resolve_pending_choice('decline')
    assert e.state.pending_choice['player_id'] == 'p1'
    e.resolve_pending_choice('first')
    assert set(p1.hand) == {cards[0], cards[3]}
    assert all(o in p1.graveyard for o in (cards[1], cards[2], cards[4], spell))
    assert len(p1.library) == 10 and not p2.hand
    assert not any(ev.type == EventType.DRAW for ev in e.state.events_this_turn())


@pytest.mark.parametrize('take', ['first', 'second'])
def test_fact_or_fiction_empty_pile_is_a_real_choice(take):
    e = _game(library=2)
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    p1 = e.state.player_by_id('p1')
    cards = list(p1.library)
    _cast(e, spell, RICH)
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice(take)
    assert len(p1.hand) == (0 if take == 'first' else 2)
    assert all(o.zone == (Zone.GRAVEYARD if take == 'first' else Zone.HAND) for o in cards)


def test_fact_or_fiction_choose_divider_and_reject_nonrevealed_card():
    e = _game(players=3)
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    bottom = e.state.player_by_id('p1').library[0]
    _cast(e, spell, RICH)
    assert e.state.pending_choice['kind'] == 'choose_pile_divider'
    e.resolve_pending_choice('p3')
    assert e.state.pending_choice['player_id'] == 'p3'
    with pytest.raises(ValueError, match='revealed card'):
        e.resolve_pending_choice(str(bottom.instance_id))
    assert e.state.pending_choice['player_id'] == 'p3'
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice('second')
    assert len(e.state.player_by_id('p1').hand) == 5


def _darksteel(e, zone=Zone.BATTLEFIELD):
    return _filler(e, 'Darksteel Angel', 'Artifact Creature — Angel', power=4, toughness=4, mv=9,
                   zone=zone, keywords=['Flying', 'Indestructible'], oracle_text=(
                       "Flying, indestructible\nYou can't lose the game and your opponents can't win the game.\n"
                       "Creatures you control can't have -1/-1 counters put on them."))


def test_darksteel_angel_prohibits_only_negative_counters_on_our_creatures():
    e = _game()
    angel = _darksteel(e)
    ours = _filler(e, 'Ours', power=4, toughness=4)
    theirs = _filler(e, 'Theirs', player='p2', power=4, toughness=4)
    artifact = _filler(e, 'Artifact', 'Artifact')
    for obj in (angel, ours, theirs, artifact):
        e.rules.add_counters(obj, 1, '-1/-1')
    assert angel.counters.get('-1/-1', 0) == ours.counters.get('-1/-1', 0) == 0
    assert theirs.counters['-1/-1'] == artifact.counters['-1/-1'] == 1
    e.rules.add_counters(ours, 1, '+1/+1')
    assert ours.counters['+1/+1'] == 1
    # Prohibiting placement doesn't prevent removal of existing counters.
    ours.add_counters('-1/-1', 2)
    e.rules.add_counters(ours, -1, '-1/-1')
    assert ours.counters['-1/-1'] == 1
    e.rules.exile(angel)
    e.rules.add_counters(ours, 1, '-1/-1')
    assert ours.counters['-1/-1'] == 2


def test_darksteel_prohibition_applies_to_entry_counters_including_itself():
    e = _game()
    angel = _darksteel(e, Zone.HAND)
    angel.entry_bonus_counters = {'-1/-1': 2}
    _cast(e, angel, RICH)
    assert angel.counters.get('-1/-1', 0) == 0
    creature = _filler(e, 'Entrant', power=4, toughness=4, zone=Zone.HAND,
                       oracle_text='This creature enters with two -1/-1 counters on it.')
    _cast(e, creature, RICH)
    assert creature.counters.get('-1/-1', 0) == 0
    enemy = _filler(e, 'Enemy entrant', player='p2', power=4, toughness=4, zone=Zone.HAND,
                    oracle_text='This creature enters with two -1/-1 counters on it.')
    e.state.active_player_index = 1
    _cast(e, enemy, RICH)
    assert enemy.counters['-1/-1'] == 2


def test_darksteel_angel_prevents_loss_and_opponents_alternate_wins():
    e = _game()
    angel = _darksteel(e)
    p1, p2 = e.state.players
    p1.life = 0
    e.resolve_until_stable()
    assert not p1.has_lost
    e.rules.player_wins(p2)
    assert not p1.has_lost and not e.state.game_over
    assert combat.has(angel, 'flying') and combat.has(angel, 'indestructible')
    e.rules.exile(angel)
    e.resolve_until_stable()
    assert p1.has_lost


def test_skrelvs_hive_upkeep_and_live_corrupted_toxic_filter():
    e = _game(players=3)
    _card(e, "Skrelv's Hive")
    other = _filler(e, 'Ordinary', power=2, toughness=2)
    enemy = _filler(e, 'Enemy', player='p2', power=2, toughness=2, oracle_text='Toxic 1')
    e.state.active_player_index = 1
    _step(e, 'upkeep', 'p2')
    assert not _named(e, 'Phyrexian Mite')
    e.state.active_player_index = 0
    _step(e, 'upkeep')
    mite = _named(e, 'Phyrexian Mite')[0]
    assert e.state.player_by_id('p1').life == 19 and combat.has(mite, 'toxic')
    assert 'cant_block' in combat._obj_keywords(mite)
    assert not combat.has(mite, 'lifelink')
    e.state.player_by_id('p3').poison = 3
    e.recompute_continuous_effects()
    assert combat.has(mite, 'lifelink')
    assert not combat.has(other, 'lifelink') and not combat.has(enemy, 'lifelink')
    e.state.player_by_id('p3').poison = 2
    e.recompute_continuous_effects()
    assert not combat.has(mite, 'lifelink')


def test_fact_or_fiction_graveyard_pile_honors_exile_replacement():
    e = _game()
    _card(e, 'Rest in Peace')
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Pile card {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    _cast(e, spell, RICH)
    e.resolve_pending_choice(str(cards[1].instance_id))
    e.resolve_pending_choice('decline')
    e.resolve_pending_choice('first')
    assert cards[1].zone == Zone.HAND
    assert all(o.zone == Zone.EXILE for o in cards if o is not cards[1])
    assert all(o not in e.state.player_by_id('p1').library for o in cards)


def test_fact_or_fiction_choice_survives_session_rewind():
    from mtg_analyzer.services.game_session import GameSession
    e = _game()
    spell = _card(e, 'Fact or Fiction', zone=Zone.HAND)
    cards = [_filler(e, f'Undo card {i}', 'Instant', zone=Zone.LIBRARY) for i in range(5)]
    _cast(e, spell, RICH)
    session = GameSession(e)
    action = {'type': 'choose', 'option_id': str(cards[2].instance_id)}
    session.apply_action(action, actor_id='p2')
    assert e.state.pending_choice['first_ids'] == [cards[2].instance_id]
    session.rewind()
    e = session.engine
    assert e.state.pending_choice['first_ids'] == []
    session.apply_action(action, actor_id='p2')
    session.apply_action({'type': 'decline'}, actor_id='p2')
    session.apply_action({'type': 'choose', 'option_id': 'first'}, actor_id='p1')
    assert [o.name for o in e.state.player_by_id('p1').hand] == ['Undo card 2']
    assert len(e.state.player_by_id('p1').library) == 10
