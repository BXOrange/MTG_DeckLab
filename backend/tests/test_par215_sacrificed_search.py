"""PAR-215: "search your library for a creature card with mana value equal to 1 plus the sacrificed creature's mana
value" (Prime Speaker Vannifar) -- the sacrifice cost's last-known mana value (RULE 608.2h) plus a literal."""
from mtg_analyzer.models.game.game_object import Zone
from tests.support.deck_batch import card, filler, game, main_phase


def test_vannifar_search_is_modeled():
    from mtg_analyzer.parser.oracle import parse_oracle
    from mtg_analyzer.services.card_database import CardDatabase, DEFAULT_DB_PATH
    assert parse_oracle(CardDatabase(DEFAULT_DB_PATH).get_card("Prime Speaker Vannifar")).modeled


def test_vannifar_offers_only_the_exact_one_plus_mana_value():
    eng = game(library=0)
    main_phase(eng)
    vannifar = card(eng, "Prime Speaker Vannifar")
    victim = filler(eng, "Victim", mv=2, power=1, toughness=1)
    p1 = eng.state.player_by_id("p1")
    for name, mv in (("TooCheap", 2), ("Exact", 3), ("TooBig", 4)):
        filler(eng, name, mv=mv, power=1, toughness=1, zone=Zone.LIBRARY)
    eng.activate_ability(p1, vannifar, 0, sacrifice_choice=victim.instance_id)
    eng.resolve_until_stable()
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "search"
    assert {o["label"] for o in choice["options"] if o["id"] != "decline"} == {"Exact"}


def test_may_sacrifice_then_search_reads_the_sacrificed_value():
    """Vivien on the Hunt's +2 sentence as a spell: the effect-level sacrifice stamps the same last-known value."""
    from mtg_analyzer.models.cards.card import Card
    from mtg_analyzer.models.game.game_object import GameObject
    from tests.support.deck_batch import _place, answer, cast

    eng = game(library=0)
    text = ("You may sacrifice a creature. If you do, search your library for a creature card with mana value equal "
            "to 1 plus the sacrificed creature's mana value, put it onto the battlefield, then shuffle.")
    spell_card = Card(id="probe", name="Probe Sorcery", type_line="Sorcery", oracle_text=text, is_sorcery=True)
    spell = _place(eng, GameObject(spell_card, owner_id="p1", zone=Zone.HAND), "p1", Zone.HAND)
    victim = filler(eng, "Victim", mv=2, power=1, toughness=1)
    for name, mv in (("TooCheap", 2), ("Exact", 3)):
        filler(eng, name, mv=mv, power=1, toughness=1, zone=Zone.LIBRARY)
    cast(eng, spell)
    for _ in range(6):
        choice = eng.state.pending_choice
        if choice is None or choice.get("kind") == "search":
            break
        options = choice.get("options") or []
        eng.resolve_pending_choice(str(options[0]["id"]) if options else "yes")
    choice = eng.state.pending_choice
    assert choice and choice["kind"] == "search"
    assert {o["label"] for o in choice["options"] if o["id"] != "decline"} == {"Exact"}
