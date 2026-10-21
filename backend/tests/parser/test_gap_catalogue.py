from mtg_analyzer.models.cards.card import Card
from mtg_analyzer.parser.gap_catalogue import GapCatalogue, GapOccurrence, build_catalogue
from mtg_analyzer.parser.oracle import parse_oracle


def card(name, text, spell=True, **kwargs):
    return Card(id=name, name=name, oracle_text=text, type_line='Sorcery' if spell else 'Creature', is_sorcery=spell, **kwargs)


def test_joint_ranking_preserves_zero_solo_chain_and_unique_card_counts():
    graph = GapCatalogue()
    for name, needs in [('AB', 'AB'), ('BC', 'BC'), ('CD', 'CD')]:
        for index, key in enumerate(needs * 2):
            graph.add(GapOccurrence(name, 0, 0, index, key, 'spell', frozenset({key})))
    rows, truncated = graph.ranking()
    counts = {package: len(cards) for package, cards in rows}
    assert not truncated
    assert all(counts[frozenset(key)] == 0 for key in 'ABCD')
    assert counts[frozenset('AB')] == 1
    assert counts[frozenset('ABC')] == 2
    assert counts[frozenset('ABCD')] == 3


def test_prerequisite_closure_keeps_large_packages_and_cycles_terminate():
    graph = GapCatalogue(requirements={'large': set('ABCDE'), 'shared': {'B'}},
                         prerequisites={'A': set('BCDE'), 'E': {'A'}})
    assert graph.closure({'A'}) == frozenset('ABCDE')
    rows, _ = graph.ranking(max_size=3)
    assert (frozenset('ABCDE'), frozenset({'large', 'shared'})) in rows


def test_modal_wrapper_and_good_modes_are_accounted_but_not_blockers():
    sample = card('Modal Test', 'Choose one —\n• Draw a card.\n• Invent a purple elephant.')
    result = parse_oracle(sample)
    assert not result.modeled
    graph = build_catalogue([sample])
    assert len(graph.occurrences) == len(result.unclaimed) == 3
    assert graph.requirements[sample.name] == {'invent a purple elephant'}
    assert len({occ.block for occ in graph.occurrences}) == 1
    assert sum(not occ.capabilities for occ in graph.occurrences) == 2


def test_context_is_per_occurrence_and_shared_body_crosses_roles():
    spell = card('Spell Test', 'Invent a purple elephant.')
    trigger = card('Trigger Test', 'When Trigger Test enters, invent a purple elephant.', False)
    graph = build_catalogue([spell, trigger])
    assert graph.requirements[spell.name] == graph.requirements[trigger.name]
    assert len({occ.context for occ in graph.occurrences}) == 2
    assert len(graph.unlocked({'invent a purple elephant'})) == 2


def test_unknown_modal_wrapper_stays_blocking():
    sample = card('Bad Wrapper', 'Choose seventeen —\n• Draw a card.\n• Gain 3 life.')
    graph = build_catalogue([sample])
    assert len(graph.occurrences) == len(parse_oracle(sample).unclaimed)
    assert graph.requirements[sample.name]
    assert not graph.unlocked({'draw a card', 'gain <n> life'})


def test_opaque_unmatched_gate_residue_is_retained(monkeypatch):
    import mtg_analyzer.parser.gap_catalogue as module
    from mtg_analyzer.parser.oracle.gate import ParseResult, UNMODELED
    sample = card('Opaque', 'Draw a card.')
    monkeypatch.setattr(module, 'parse_oracle', lambda _: ParseResult(coverage=UNMODELED, unclaimed=['synthetic failure']))
    graph = build_catalogue([sample])
    assert len(graph.occurrences) == 1
    assert graph.occurrences[0].opaque
    assert graph.ranking()[0] == []


def test_room_faces_keep_identical_lines_separate_and_unique_card_counts():
    sample = Card(id='room', name='Left // Right', layout='split', type_line='Enchantment — Room',
                  oracle_text='Invent a purple elephant.', back_name='Right',
                  back_type_line='Enchantment — Room', back_oracle_text='Invent a purple elephant.')
    graph = build_catalogue([sample])
    assert len(graph.occurrences) == 2
    assert {occ.face for occ in graph.occurrences} == {0, 1}
    assert len(graph.unlocked({'invent a purple elephant'})) == 1


def test_identical_line_has_different_meaning_in_spell_and_permanent():
    spell = card('Spell Context', 'Draw a card. Invent a purple elephant.')
    permanent = card('Permanent Context', 'Draw a card. Invent a purple elephant.', False)
    graph = build_catalogue([spell, permanent])
    assert len(graph.occurrences) == 2
    assert graph.requirements[spell.name] != graph.requirements[permanent.name]


def test_triggered_modal_wrapper_collateral_and_accounting():
    sample = card('Triggered Modal', 'When Triggered Modal enters, choose one —\n• Draw a card.\n• Invent a purple elephant.', False)
    graph = build_catalogue([sample])
    assert graph.requirements[sample.name] == {'invent a purple elephant'}
    assert graph.accounting() == {'expected': 3, 'recorded': 3, 'missing': {}, 'extra': {}}


def test_unparsed_back_face_does_not_invent_authoritative_blockers():
    for layout in ('transform', 'adventure'):
        sample = card('Front ' + layout, 'Invent a purple elephant.', layout=layout,
                      back_name='Back', back_type_line='Sorcery', back_oracle_text='Invent a blue giraffe.')
        graph = build_catalogue([sample])
        assert graph.requirements[sample.name] == {'invent a purple elephant'}
        assert graph.accounting()['expected'] == graph.accounting()['recorded'] == len(parse_oracle(sample).unclaimed)


def test_rank_span_cli_differs_from_whole_line(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[3] / '.claude/skills/extend-parser/scripts/parser_probe.py'
    spec = importlib.util.spec_from_file_location('probe_par177', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sample = card('CLI Span', 'Draw a card. Invent a purple elephant.')
    monkeypatch.setattr(module, 'load_cards', lambda *_: [sample])
    args = SimpleNamespace(card_db=None, limit=None, grep=None, joint=False, top=10, by='span')
    module.cmd_rank(args)
    span = capsys.readouterr().out
    args.by = 'line'
    module.cmd_rank(args)
    line = capsys.readouterr().out
    assert 'draw a card. invent' not in span
    assert 'draw a card. invent' in line
    assert 'invent a purple elephant' in span


def test_unsupported_triggered_modal_head_is_a_real_blocker():
    sample = card('Unknown Head', 'Whenever you invent a purple elephant, choose one —\n• Draw a card.\n• Gain 3 life.', False)
    graph = build_catalogue([sample])
    assert graph.requirements[sample.name]
    assert not graph.unlocked(set())
    assert all(occ.context != 'modal' for occ in graph.occurrences)
    assert graph.accounting()['missing'] == graph.accounting()['extra'] == {}


def test_trigger_body_span_is_minimal():
    sample = card('Minimal Body', 'When Minimal Body enters, draw a card. Invent a purple elephant.', False)
    graph = build_catalogue([sample])
    assert graph.requirements[sample.name] == {'invent a purple elephant'}


def test_named_successful_mode_is_collateral():
    sample = card('Named Modal', 'Choose one —\n• Brilliant idea — Draw a card.\n• Bad idea — Invent a purple elephant.')
    graph = build_catalogue([sample])
    assert len(graph.requirements[sample.name]) == 1
    assert graph.requirements[sample.name] == {'bad idea — invent a purple elephant'}


def test_collateral_only_diagnosis_cannot_unlock_unmodeled_card(monkeypatch):
    import mtg_analyzer.parser.gap_catalogue as module
    sample = card('Composition Gap', 'Choose one —\n• Draw a card.\n• Invent a purple elephant.')
    monkeypatch.setattr(module, '_parse_mode_body', lambda _: [])
    graph = build_catalogue([sample])
    assert not graph.unlocked(set())
    assert any(occ.context == 'card-verdict' and occ.opaque for occ in graph.occurrences)
    assert graph.accounting()['expected'] == graph.accounting()['recorded'] == 3
