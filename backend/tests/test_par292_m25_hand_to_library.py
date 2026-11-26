"""PAR-292 M25, RULE 401.4 / 608.2c / 603.4: "put N cards from your hand on top of / on the bottom of your library".

Real cards on a real GameEngine: the draw-then-put loots (Riverwise Augur, Sawtooth Loon, Survivor of the Unseen), the
"may ... if you do, draw" exchange (Fire Prophecy), the gated bottom (Errand-Rider of Gondor, "you don't control a
legendary creature") and a bot answering the pick from its own view and legal actions."""
import pytest

from mtg_analyzer.parser.oracle.catalogue.clause_hooks import match_clause
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import RICH, activate as _activate, answer, card, cast, filler, game, put_on_battlefield
from tests.test_par292_dynamic_search_qualities import _modeled

CLAIMED = (
    "Cavalier of Gales", "Gustha Ebbasdotter", "Riverwise Augur", "Sawtooth Loon", "Survivor of the Unseen",
    "Conch Horn", "Enter the Infinite", "Amass the Components", "Fire Prophecy", "Manhole Missile",
    "Errand-Rider of Gondor",
)


def activate(eng, source, **kw):
    eng.state.player_by_id("p1").mana_pool.add_many(RICH)  # the tests care what resolves, not how it was paid for
    _activate(eng, source, **kw)


@pytest.mark.parametrize("name", CLAIMED)
def test_claimed_cards_are_modeled(name):
    assert _modeled(name)


@pytest.mark.parametrize("text", [
    "put a card from your hand into your graveyard",       # a different destination
    "put two cards from your hand on the third from the top of your library",
])
def test_other_shapes_stay_unclaimed(text):
    assert match_clause(text) is None


def test_riverwise_augur_draws_three_then_puts_two_on_top_in_the_chosen_order():
    eng = game(library=6)
    p = eng.state.player_by_id("p1")
    put_on_battlefield(eng, "Riverwise Augur")
    assert eng.state.pending_choice["kind"] == "choose_objects"
    assert eng.state.pending_choice["player_id"] == "p1"
    assert len(p.hand) == 3
    first, second = p.hand[0], p.hand[1]
    eng.resolve_pending_choice(first.instance_id)
    assert eng.state.pending_choice is not None  # the order is the pick order (RULE 401.4)
    eng.resolve_pending_choice(second.instance_id)
    assert eng.state.pending_choice is None
    assert p.library[-2:] == [first, second]  # the last pick ends on top
    assert len(p.hand) == 1 and len(p.library) == 6 - 3 + 2


def test_sawtooth_loon_puts_two_on_the_bottom_in_the_chosen_order():
    eng = game(library=6)
    p = eng.state.player_by_id("p1")
    put_on_battlefield(eng, "Sawtooth Loon")
    # The bounce trigger returns the Loon itself, the draw-two trigger then fills the hand to three.
    for _ in range(4):
        choice = eng.state.pending_choice
        if choice is None:
            break
        if choice.get("kind") == "choose_objects" and "unter die Bibliothek" in str(choice.get("prompt")):
            picks = [o["id"] for o in choice["options"]][:2]
            eng.resolve_pending_choice(picks[0])
            eng.resolve_pending_choice(picks[1])
            assert [str(p.library[1].instance_id), str(p.library[0].instance_id)] == [str(picks[0]), str(picks[1])]
            break
        eng.resolve_pending_choice(str(choice["options"][0]["id"]))
    assert eng.state.pending_choice is None
    assert len(p.hand) == 1 and len(p.library) == 6 - 2 + 2


def test_survivor_of_the_unseen_puts_one_card_on_top():
    eng = game(library=5)
    p = eng.state.player_by_id("p1")
    surv = card(eng, "Survivor of the Unseen")
    activate(eng, surv)
    answer(eng)
    assert len(p.hand) == 1 and len(p.library) == 5 - 2 + 1
    assert p.library[-1].zone == Zone.LIBRARY


def test_an_empty_hand_and_an_empty_library_do_nothing_and_do_not_crash():
    eng = game(library=0)
    p = eng.state.player_by_id("p1")
    surv = card(eng, "Survivor of the Unseen")
    activate(eng, surv)
    answer(eng)
    assert eng.state.pending_choice is None and not p.hand and not p.library


def test_an_empty_hand_asks_nothing_for_the_bottom_either():
    eng = game(library=6)
    eng.rules.put_hand_cards_on_top(eng.state.player_by_id("p1"), 2, "bottom")
    assert eng.state.pending_choice is None


def test_bottom_pick_of_all_cards_still_asks_for_the_order():
    eng = game(library=3)
    p = eng.state.player_by_id("p1")
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    objs = []
    for i in range(2):
        o = GameObject(Card(id=f"c{i}", name=f"C{i}", type_line="Instant", is_instant=True), owner_id="p1", zone=Zone.HAND)
        p.add_to_zone(o, Zone.HAND)
        objs.append(o)
    eng.rules.put_hand_cards_on_top(p, 2, "bottom")
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice(objs[1].instance_id)
    eng.resolve_pending_choice(objs[0].instance_id)
    assert p.library[:2] == [objs[0], objs[1]]  # the last pick lies lowest
    assert not p.hand


def test_fire_prophecy_exchange_draws_only_if_a_card_was_put_back():
    eng = game(library=5)
    p = eng.state.player_by_id("p1")
    target = filler(eng, "Bear", type_line="Creature", power=2, toughness=5, player="p2")
    keep = filler(eng, "Hand card", type_line="Sorcery", zone=Zone.HAND)
    spell = card(eng, "Fire Prophecy", zone=Zone.HAND)
    cast(eng, spell, targets=[target])
    answer(eng)  # may: yes, then the only hand card goes to the bottom
    assert keep in p.library and p.library[0] is keep
    assert len(p.hand) == 1  # drew a replacement
    assert target.damage_marked == 3 or target not in eng.state.battlefield


def test_fire_prophecy_declined_keeps_hand_and_does_not_draw():
    eng = game(library=5)
    p = eng.state.player_by_id("p1")
    target = filler(eng, "Bear", type_line="Creature", power=2, toughness=5, player="p2")
    keep = filler(eng, "Hand card", type_line="Sorcery", zone=Zone.HAND)
    spell = card(eng, "Fire Prophecy", zone=Zone.HAND)
    cast(eng, spell, targets=[target])
    assert eng.state.pending_choice is not None
    eng.resolve_pending_choice("decline")
    answer(eng)
    assert keep in p.hand and len(p.hand) == 1 and len(p.library) == 5


@pytest.mark.parametrize("legend,expect_bottom", [(False, True), (True, False)])
def test_errand_rider_bottoms_a_card_only_without_a_legendary_creature(legend, expect_bottom):
    eng = game(library=5)
    p = eng.state.player_by_id("p1")
    if legend:
        filler(eng, "Legend", type_line="Legendary Creature — Human", power=1, toughness=1)
    put_on_battlefield(eng, "Errand-Rider of Gondor")
    answer(eng)
    assert len(p.hand) == (0 if expect_bottom else 1)
    assert len(p.library) == (5 if expect_bottom else 4)


def test_a_bot_answers_the_hand_pick_from_its_own_view_and_legal_actions():
    from mtg_analyzer.services.bots import create_bot
    from mtg_analyzer.services.game_session import GameSessionManager

    session = GameSessionManager().create_multiplayer(
        [{"player_id": p, "name": p, "library": []} for p in ("p1", "p2")], mulligan_style="none", keep_history=False,
    )
    eng = session.engine
    me = eng.state.active_player.id
    p = eng.state.player_by_id(me)
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    for i in range(3):
        g = GameObject(Card(id=f"h{i}", name=f"H{i}", type_line="Instant", is_instant=True), owner_id=me, zone=Zone.HAND)
        p.add_to_zone(g, Zone.HAND)
    eng.rules.put_hand_cards_on_top(p, 2, "top")
    choice = eng.state.pending_choice
    assert choice and choice["player_id"] == me
    other = next(x.id for x in eng.state.players if x.id != me)
    assert not [a for a in session.legal_actions(perspective=other) if a["type"] == "choose"]
    actions = session.legal_actions(perspective=me)
    assert actions
    action = create_bot("greedy", me).decide(session.view(perspective=me), actions)
    session.apply_action(action, actor_id=me)
    assert eng.state.pending_choice is None or eng.state.pending_choice["player_id"] == me


# ---- reveal any number of <quality> cards in your hand (RULE 701.20a) -------------------------------------------

REVEAL_CLAIMED = (
    "Brine Seer", "Cinder Seer", "Jasmine Seer", "Nightshade Seer", "Scent of Brine", "Scent of Cinder",
    "Scent of Jasmine", "Scent of Nightshade", "Rofellos's Gift", "Scent of Ivy",
)


@pytest.mark.parametrize("name", REVEAL_CLAIMED)
def test_reveal_any_number_cards_are_modeled(name):
    assert _modeled(name)


def _hand_cards(eng, *names_colors, player="p1"):
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    p = eng.state.player_by_id(player)
    out = []
    for i, (kind, colors) in enumerate(names_colors):
        c = Card(id=f"{kind}{i}", name=f"{kind} {i}", type_line=kind, mana_cost_string="".join("{%s}" % c for c in colors), color_identity=set(colors),
                 mana_cost={c: 1 for c in colors},
                 is_creature="Creature" in kind, is_instant="Instant" in kind)
        o = GameObject(c, owner_id=player, zone=Zone.HAND)
        p.add_to_zone(o, Zone.HAND)
        out.append(o)
    return out


def _reveal_all_matching(eng, picks):
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "choose_objects" and choice["player_id"] == "p1"
    for iid in picks:
        eng.resolve_pending_choice(iid)
    if eng.state.pending_choice is not None:
        eng.resolve_pending_choice("decline")  # "any number": stop here


def test_jasmine_seer_offers_only_white_cards_and_gains_two_life_per_card():
    eng = game(library=4)
    p = eng.state.player_by_id("p1")
    white = _hand_cards(eng, ("Instant", "W"), ("Instant", "W"), ("Instant", "U"), ("Instant", "R"))
    seer = card(eng, "Jasmine Seer")
    activate(eng, seer)
    choice = eng.state.pending_choice
    assert {str(o["id"]) for o in choice["options"]} - {"decline"} == {str(white[0].instance_id), str(white[1].instance_id)}
    life = p.life
    _reveal_all_matching(eng, [white[0].instance_id, white[1].instance_id])
    assert p.life == life + 4
    assert all(o in p.hand for o in white)  # revealing moves nothing


def test_revealing_none_is_allowed_and_gains_nothing():
    eng = game(library=4)
    p = eng.state.player_by_id("p1")
    _hand_cards(eng, ("Instant", "W"))
    activate(eng, card(eng, "Jasmine Seer"))
    life = p.life
    eng.resolve_pending_choice("decline")
    answer(eng)
    assert p.life == life and eng.state.pending_choice is None


def test_cinder_seer_deals_damage_equal_to_the_revealed_red_cards():
    eng = game(library=4)
    red = _hand_cards(eng, ("Instant", "R"), ("Instant", "R"), ("Instant", "R"))
    seer = card(eng, "Cinder Seer")
    activate(eng, seer, targets=[eng.state.player_by_id("p2")])
    life = eng.state.player_by_id("p2").life
    _reveal_all_matching(eng, [red[0].instance_id, red[2].instance_id])
    assert eng.state.player_by_id("p2").life == life - 2


def test_nightshade_seer_shrinks_the_target_by_the_revealed_count():
    eng = game(library=4)
    black = _hand_cards(eng, ("Instant", "B"), ("Instant", "B"))
    victim = filler(eng, "Bear", type_line="Creature", power=3, toughness=3, player="p2")
    seer = card(eng, "Nightshade Seer")
    activate(eng, seer, targets=[victim])
    _reveal_all_matching(eng, [black[0].instance_id, black[1].instance_id])
    eng.recompute_continuous_effects()
    assert (victim.power, victim.toughness) == (1, 1)


def test_rofellos_gift_returns_one_enchantment_per_revealed_green_card():
    eng = game(library=4)
    p = eng.state.player_by_id("p1")
    green = _hand_cards(eng, ("Instant", "G"), ("Instant", "G"))
    ench = [filler(eng, f"Ench{i}", type_line="Enchantment", zone=Zone.GRAVEYARD) for i in range(3)]
    spell = card(eng, "Rofellos's Gift", zone=Zone.HAND)
    cast(eng, spell)
    eng.resolve_pending_choice(green[0].instance_id)
    eng.resolve_pending_choice(green[1].instance_id)  # both green cards revealed: the choice moves on
    answer(eng)
    assert sum(1 for e in ench if e in p.hand) == 2


def test_metalworker_stays_unclaimed_because_a_mana_ability_cannot_use_the_stack():
    # RULE 605.1a / 605.3: the reveal would have to be answered while paying, so the stack reading must not be claimed.
    assert not _modeled("Metalworker")
