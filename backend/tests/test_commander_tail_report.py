"""The research report routes causes without inventing missing mechanics."""
from collections import Counter
from types import SimpleNamespace

import pytest

from scripts import commander_tail_report as report
from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.composition_diagnostics import CompositionProbe
from mtg_analyzer.parser.oracle import NEVER_SUPPORTED, abstract_clause
from mtg_analyzer.parser.oracle.spec import ParserProvenance


def card(name, text='', type_line='Enchantment'):
    return Card(id=name, name=name, oracle_text=text, type_line=type_line,
                is_instant=type_line == "Instant", is_sorcery=type_line == "Sorcery")


def probe():
    return CompositionProbe(ParserProvenance(version=report.PARSER_VERSION, source='report-test'))


@pytest.mark.parametrize('text', [
    'roll a d20, then teleport a card', 'fateseal 99, then teleport a card',
    'meld them into an imaginary card', 'heal 12 damage, then teleport a card',
    'harness, then teleport a card', "triple target creature's power and toughness",
    'loses this ability and becomes an aura enchantment', 'specialize 9',
    'a creature dealt damage by ~ this turn dies', 'waterbend 8, then teleport a card',
    'whenever you waterbend, teleport a card', 'clash with an opponent, then teleport a card',
    'put suspect counters on it', 'incubate 13, then teleport a card',
    'collect evidence 5, then teleport a card', 'face a villainous choice',
    'exchange control of imaginary objects', 'put it tapped and attacking',
    'target creature loses banding', 'creatures you control have horsemanship',
])
def test_shipped_instruction_words_do_not_create_mec_or_dead_mechanic_routes(text):
    template = abstract_clause(text)
    bucket, _ = report.classify([template], [text], False, 'UNMODELED', Counter({template: 1}), 5)
    assert bucket == 'E'


def test_mode_body_that_claims_with_period_is_wrapper_residue_not_missing_effect():
    result = report.analyse_card(card('Modal audit'),
                                 ['choose 1 —', "• triple target creature's power and toughness until end of turn."],
                                 'UNMODELED')
    assert result == ([], [], True)
    assert report.classify(*result, 'UNMODELED', Counter(), 5)[0] == 'A'


@pytest.mark.parametrize(('text', 'expected'), [
    ('when ~ enters, draw a card.', ('trigger', True, True)),
    ('when the moon becomes blue, draw a card.', ('trigger', False, True)),
    ('when ~ enters, teleport three noodles.', ('trigger', True, False)),
    ('when the moon becomes blue, teleport three noodles.', ('trigger', False, False)),
    ('{t}: draw a card.', ('activated', True, True)),
    ('{t}: teleport three noodles.', ('activated', True, False)),
    ('pay a million noodles: draw a card.', ('activated', False, True)),
])
def test_actual_segmenter_known_good_partners_distinguish_head_and_body(text, expected):
    result = probe().split(text)
    assert result is not None
    kind, _, _, head_ok, body_ok = result
    assert (kind, head_ok, body_ok) == expected


def test_static_clauses_do_not_become_fake_trigger_or_activation_axes():
    assert probe().split('creatures have a strange new ability') is None


def test_modifier_axis_requires_the_shortened_sentence_to_parse():
    p = probe()
    repairs = p.modifier_repairs('if the moon is made of cheese, draw a card.')
    assert [(axis, shortened) for axis, _, shortened in repairs] == [("leading 'if <cond>,'", 'draw a card')]
    assert p.modifier_repairs('if the moon is made of cheese, teleport three noodles.') == []
    # Removing one phrase cannot repair two independent unknown modifiers.
    assert p.modifier_repairs('if the moon is made of cheese, draw a card for each noodle in your soup.') == []
    assert p.modifier_repairs('draw a card.') == []


def test_report_sticker_type_overrides_modeled_or_authored_name(monkeypatch):
    monkeypatch.setattr(report, 'parse_oracle', lambda _: SimpleNamespace(
        coverage='MODELED', modeled=True, unclaimed=[]))
    monkeypatch.setattr(report, 'is_registered', lambda _: True)
    payload = report.build_report([card('Empty insert', type_line='  StIcKeRs  '),
                                   card('Sticker Collector', 'Draw a card.', 'Sorcery')])
    assert payload['buckets']['F'] == ['Empty insert']
    assert payload['totals']['covered'] == 1
    assert payload['totals']['never_supported'] == 1


def test_non_goals_do_not_change_raw_coverage_accounting():
    cards = [card('Draft audit', 'Draft this card face up.'),
             card('Attraction audit', 'Open an Attraction.'),
             card('Insert audit', type_line='Stickers'),
             card('Normal draw audit', 'Draw a card.', 'Sorcery')]
    payload = report.build_report(cards)
    assert payload['totals'] == {
        'commander_legal': 4, 'covered': 1, 'unmodeled': 2,
        'never_supported': 1, 'report_only_non_goals': 2, 'fraction': .25,
    }
    assert payload['buckets']['F'] == ['Attraction audit', 'Draft audit', 'Insert audit']
    assert len(payload['excluded_reasons']) == 3


def test_recurring_templates_still_precede_e_diagnostics_and_deduplicate_per_card():
    cards = [card('First unknown', 'When First unknown enters, teleport three noodles.'),
             card('Second unknown', 'When Second unknown enters, teleport three noodles.')]
    payload = report.build_report(cards, min_cluster=2)
    assert len(payload['buckets']['B']) == 1
    assert payload['buckets']['B'][0]['cards'] == ['First unknown', 'Second unknown']
    assert not payload['buckets']['E']
    assert not payload['E_axes']


def test_e_preserves_multiple_clauses_and_only_counts_a_card_once_per_axis(capsys):
    text = ('When Mixed audit enters, if the moon is made of cheese, draw a card.\n'
            'When Mixed audit dies, if the moon is made of cheese, draw a card.\n'
            'Creatures have an unknown keyword.')
    payload = report.build_report([card('Mixed audit', text)])
    assert payload['buckets']['E'][0]['axes'] == ['other/static/non-split', 'trigger H+B-']
    trigger = next(row for row in payload['E_axes'] if row['axis'] == 'trigger H+B-')
    assert trigger['clause_count'] == 2
    assert trigger['cards'] == ['Mixed audit']
    assert payload['E_modifier_axes'][0]['cards'] == ['Mixed audit']
    assert payload['E_modifier_axes'][0]['clause_count'] == 1
    report.print_report(payload)
    printed = capsys.readouterr().out
    assert 'overlapping card sets; not additive' in printed
    assert "leading 'if <cond>,'" in printed
    assert 'Check status' not in printed
    assert 'check_status' not in str(payload)
