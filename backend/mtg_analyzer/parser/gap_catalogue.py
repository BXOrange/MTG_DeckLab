"""Read-only, context-preserving coverage research graph.

Capabilities are hypothetical grammar repairs, not promises of runtime support.
Every gate-unclaimed occurrence is retained, including opaque composition gaps.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .composition_diagnostics import CompositionProbe
from .oracle import PARSER_VERSION, abstract_clause, parse_oracle
from .oracle.gate import (
    _flip_halves, _room_halves, _is_spell, _split_triggered_modal_block, _parse_mode_body,
)
from .oracle.catalogue.modal import split_modal_block
from .oracle.normalize import normalize
from .oracle.residue import minimal_unclaimed_span
from .oracle.segmenter import segment_line
from .oracle.spec import ParserProvenance

# Bound exploratory combinations, never the underlying full-pool graph.
DEFAULT_PACKAGE_SIZE = 4
DEFAULT_CANDIDATE_LIMIT = 100_000


@dataclass(frozen=True)
class GapOccurrence:
    card: str
    face: int
    block: int
    line_index: int
    line: str
    context: str
    capabilities: frozenset[str]
    opaque: bool = False


@dataclass
class GapCatalogue:
    occurrences: list[GapOccurrence] = field(default_factory=list)
    requirements: dict[str, set[str]] = field(default_factory=dict)
    prerequisites: dict[str, set[str]] = field(default_factory=dict)
    expected_unresolved: Counter = field(default_factory=Counter)

    def accounting(self):
        actual = Counter(occ.card for occ in self.occurrences if occ.context != "card-verdict")
        return {"expected": sum(self.expected_unresolved.values()), "recorded": sum(actual.values()),
                "missing": dict(self.expected_unresolved - actual), "extra": dict(actual - self.expected_unresolved)}

    def add(self, occurrence: GapOccurrence):
        self.occurrences.append(occurrence)
        self.requirements.setdefault(occurrence.card, set()).update(occurrence.capabilities)

    def closure(self, capabilities):
        result = set(capabilities)
        pending = list(result)
        while pending:
            for prerequisite in self.prerequisites.get(pending.pop(), ()):
                if prerequisite not in result:
                    result.add(prerequisite)
                    pending.append(prerequisite)
        return frozenset(result)

    def unlocked(self, capabilities):
        selected = self.closure(capabilities)
        return frozenset(card for card, needed in self.requirements.items() if needed <= selected)

    def ranking(self, max_size=DEFAULT_PACKAGE_SIZE, candidate_limit=DEFAULT_CANDIDATE_LIMIT):
        """Singles, observed pairs/triples and connected unions of card packages.

        Complete card prerequisite packages survive even beyond max_size. The
        explicit truncation flag concerns exploration only; accounting is exact.
        """
        seeds = {self.closure(needed) for needed in self.requirements.values()
                 if needed and not any(key.startswith('opaque:') for key in needed)}
        # Even an opaque-blocked card contributes its known shared phrases.
        singles = {key for needed in self.requirements.values() for key in needed if not key.startswith('opaque:')}
        seeds.update(self.closure({key}) for key in singles)
        candidates = set(seeds)
        for needed in seeds:
            candidates.update(self.closure([capability]) for capability in needed)
            for size in range(2, min(3, max_size, len(needed)) + 1):
                candidates.update(self.closure(group) for group in combinations(sorted(needed), size))
        frontier = sorted(seeds, key=lambda value: (len(value), sorted(value)))
        truncated = len(candidates) > candidate_limit
        adjacent = defaultdict(set)
        for seed in seeds:
            for key in seed:
                adjacent[key].add(seed)
        while frontier and not truncated:
            following = set()
            for package in frontier:
                neighbours = set().union(*(adjacent[key] for key in package))
                for seed in sorted(neighbours, key=lambda value: (len(value), sorted(value))):
                    union = package | seed
                    if len(union) <= max_size and union not in candidates:
                        candidates.add(union)
                        following.add(union)
                        if len(candidates) >= candidate_limit:
                            truncated = True
                            break
                if truncated:
                    break
            frontier = sorted(following, key=lambda value: (len(value), sorted(value)))
        cards_by_key = defaultdict(set)
        for card, needed in self.requirements.items():
            for key in needed:
                cards_by_key[key].add(card)
        def unlocked(package):
            relevant = set().union(*(cards_by_key[key] for key in package))
            return frozenset(card for card in relevant if self.requirements[card] <= package)
        ranked = [(package, unlocked(package)) for package in candidates]
        ranked.sort(key=lambda row: (-len(row[1]), len(row[0]), sorted(row[0])))
        return ranked, truncated


def _phrase(text):
    # A body is the same capability in a spell, triggered or activated role.
    return abstract_clause(text.strip().rstrip('.').strip())


def build_catalogue(cards, covered=lambda card: False):
    catalogue = GapCatalogue()
    provenance = ParserProvenance(version=PARSER_VERSION, source='gap-catalogue')
    probe = CompositionProbe(provenance)
    for card in cards:
        result = parse_oracle(card)
        if result.modeled or result.never_supported or covered(card):
            continue
        name = card.name
        authoritative = Counter(result.unclaimed)
        catalogue.expected_unresolved[name] += len(result.unclaimed)
        faces = _room_halves(card) or _flip_halves(card) or [card]
        recorded = 0
        for face_index, face in enumerate(faces):
            failed = Counter(parse_oracle(face).unclaimed)
            lines = [line.strip() for line in normalize(face.oracle_text or '', face.name, face.keywords).split('\n') if line.strip()]
            modal = {}
            for index, line in enumerate(lines):
                block = split_modal_block(lines, index) if _is_spell(face) else None
                triggered = _split_triggered_modal_block(lines, index, provenance)
                if block is not None or triggered is not None:
                    end = (block or triggered)[-1]
                    for position in range(index, end):
                        modal[position] = (index, position == index)

            def claims(text):
                return segment_line(text, allow_spell_effect=_is_spell(face), is_saga=bool(getattr(face, 'is_saga', False)), provenance=provenance).claimed

            for index, line in enumerate(lines):
                if not failed[line] or not authoritative[line]:
                    continue
                failed[line] -= 1
                authoritative[line] -= 1
                block_index, header = modal.get(index, (index, False))
                context = 'modal' if index in modal else ('spell' if _is_spell(face) else 'permanent')
                opaque = False
                capabilities = set()
                if index in modal:
                    # A recognized header and successful sibling modes are
                    # collateral unclaimed lines, not independent repairs.
                    if not header:
                        body = line.removeprefix('•').strip()
                        if _parse_mode_body(body) is None:
                            capabilities.add(_phrase(body))
                else:
                    diagnosis = probe.split(line)
                    if diagnosis is not None:
                        kind, head, body, head_ok, body_ok = diagnosis
                        if not head_ok:
                            capabilities.add(_phrase(head))
                        if not body_ok:
                            prefix = 'when ~ enters, ' if kind == 'trigger' else '{t}: '
                            span = minimal_unclaimed_span(body, lambda text: probe.claims(prefix + text))
                            capabilities.add(_phrase(span))
                        context += ':' + kind
                    else:
                        span = minimal_unclaimed_span(line, claims)
                        if not claims(line):
                            capabilities.add(_phrase(span))
                    if not capabilities:
                        opaque = True
                        capabilities.add(f'opaque:{name}:{face_index}:{block_index}:{index}:{line}')
                catalogue.add(GapOccurrence(name, face_index, block_index, index, line, context, frozenset(capabilities), opaque))
                recorded += 1
            # Synthetic block bodies and unsupported card-level checks may not
            # appear verbatim in normalized text. Never lose those blockers.
            for line, count in failed.items():
                for offset in range(min(count, authoritative[line])):
                    authoritative[line] -= 1
                    identity = len(lines) + recorded + offset
                    key = f'opaque:{name}:{face_index}:{identity}:{line}'
                    catalogue.add(GapOccurrence(name, face_index, identity, identity, line, 'unresolved', frozenset({key}), True))
                    recorded += 1
        for line, count in authoritative.items():
            for offset in range(count):
                key = f"opaque:{name}:unattributed:{recorded}:{line}"
                catalogue.add(GapOccurrence(name, -1, -1, recorded, line, "unresolved", frozenset({key}), True))
                recorded += 1
        if not catalogue.requirements.get(name):
            key = f'opaque:{name}:card-verdict'
            catalogue.add(GapOccurrence(name, 0, 0, 0, '', 'card-verdict', frozenset({key}), True))
    return catalogue
