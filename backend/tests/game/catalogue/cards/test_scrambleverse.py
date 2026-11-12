"""Scrambleverse resolves random assignments through the real spell pipeline."""
from mtg_analyzer.game.card_registry import specs_for
from tests.support.catalogue import battlefield_object
from tests.support.star_trek import cast, game, vanilla


def test_scrambleverse_assigns_before_control_changes_and_untaps(monkeypatch):
    engine, p1, p2 = game("Scrambleverse")
    spell = p1.hand[0]
    first = specs_for(spell.card)
    second = specs_for(spell.card)
    assert first[0] is not second[0]
    assert first[0].effects[0] is not second[0].effects[0]
    bear = vanilla(engine, "p1", "Bear")
    rock = battlefield_object(engine, "p2", "Rock", "Artifact")
    land = battlefield_object(engine, "p1", "Forest", "Basic Land — Forest", is_land=True)
    hidden = vanilla(engine, "p2", "Phased Bear")
    hidden.phased_out = True
    for obj in (bear, rock, land, hidden):
        obj.tapped = True
    assignments = iter([p2, p1])
    calls = []

    def choose(players):
        assert players == [p1, p2]
        assert bear.controller_id == "p1" and rock.controller_id == "p2"
        assert bear.tapped and rock.tapped
        calls.append(True)
        return next(assignments)

    monkeypatch.setattr(engine.rules, "random_choice", choose)
    cast(engine, p1, spell)
    assert len(calls) == 2
    assert bear.controller_id == "p2" and rock.controller_id == "p1"
    assert bear.summoning_sick
    assert not bear.tapped and not rock.tapped
    assert land.controller_id == "p1" and land.tapped
    assert hidden.controller_id == "p2" and hidden.tapped
    assert spell in p1.graveyard
    engine._step_cleanup()
    assert bear.controller_id == "p2" and rock.controller_id == "p1"


def test_scrambleverse_untaps_even_when_controller_stays_the_same(monkeypatch):
    engine, p1, p2 = game("Scrambleverse")
    bear = vanilla(engine, "p1")
    bear.tapped = True
    monkeypatch.setattr(engine.rules, "random_choice", lambda players: p1)
    cast(engine, p1, p1.hand[0])
    assert bear.controller_id == "p1" and not bear.tapped
    assert not bear.summoning_sick


def test_scrambleverse_resolves_on_empty_battlefield():
    engine, p1, p2 = game("Scrambleverse")
    spell = p1.hand[0]
    cast(engine, p1, spell)
    assert spell in p1.graveyard
