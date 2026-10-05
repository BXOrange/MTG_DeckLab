"""Lossless report storage: pooled card descriptors and chronological deltas.

Deltas contain [path, value] replacements and [path] dictionary deletions.
Lists of equal length are diffed by index; resized lists are replaced whole.
Card references identify descriptor content, not just Scryfall identity, so
transforms, copies and distinct tokens cannot overwrite one another.
"""
from copy import deepcopy
import gzip
import json
from pathlib import Path

CARD_FIELDS = frozenset({
    'card_id', 'name', 'base_power', 'base_toughness', 'type_line',
    'has_back_face', 'is_land', 'is_artifact', 'is_enchantment',
    'is_planeswalker', 'is_battle', 'is_saga', 'saga_final_chapter', 'token',
})


def _delta(old, new, path=None):
    path = [] if path is None else path
    if type(old) is not type(new):
        return [[path, new]]
    if isinstance(old, dict):
        changes = [[path + [key]] for key in old if key not in new]
        for key, value in new.items():
            changes.extend(_delta(old[key], value, path + [key]) if key in old
                           else [[path + [key], value]])
        return changes
    if isinstance(old, list) and len(old) == len(new):
        return [change for i, value in enumerate(new)
                for change in _delta(old[i], value, path + [i])]
    return [] if old == new else [[path, new]]


def _apply(base, changes):
    result = deepcopy(base)
    for change in changes:
        path = change[0]
        if not path:
            result = deepcopy(change[1])
            continue
        parent = result
        for key in path[:-1]:
            parent = parent[key]
        if len(change) == 1:
            del parent[path[-1]]
        else:
            parent[path[-1]] = deepcopy(change[1])
    return result


def encode_report(report):
    """Encode a v1 diagnostic report as v2 without modifying its input."""
    result = deepcopy(report)
    result['version'] = 2
    game = result.get('game')
    if game is None:
        return result
    cards, refs = {}, {}

    def pool(value):
        if isinstance(value, list):
            return [pool(item) for item in value]
        if not isinstance(value, dict):
            return value
        if 'card_id' in value and 'name' in value:
            descriptor = {key: value[key] for key in value if key in CARD_FIELDS}
            signature = json.dumps(descriptor, sort_keys=True, ensure_ascii=False)
            if signature not in refs:
                ref = f'c{len(cards)}'
                refs[signature] = ref
                cards[ref] = descriptor
            return {'$card': refs[signature], **{
                key: pool(item) for key, item in value.items() if key not in CARD_FIELDS
            }}
        return {key: pool(item) for key, item in value.items()}

    positions = [pool({'replay': action['replay_before'], 'state': action['state_before']})
                 for action in game['recent_actions']]
    positions.append(pool({'replay': game.pop('replay'), 'state': game.pop('state')}))
    actions = game['recent_actions']
    for index, action in enumerate(actions):
        del action['replay_before'], action['state_before']
        action['position_index'] = index
    game['positions'] = {
        'base': positions[0],
        'deltas': [_delta(old, new) for old, new in zip(positions, positions[1:])],
    }
    game['cards'] = cards
    return result


def decode_report(report):
    """Expand v2 into the familiar v1 layout; old reports remain readable."""
    result = deepcopy(report)
    if result.get('version') == 1:
        return result
    if result.get('version') != 2:
        raise ValueError('Unsupported bug-report version')
    result['version'] = 1
    game = result.get('game')
    if game is None:
        return result
    cards = game.pop('cards')

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        return {**(deepcopy(cards[value['$card']]) if '$card' in value else {}),
                **{key: expand(item) for key, item in value.items() if key != '$card'}}

    stored = game.pop('positions')
    positions = [stored['base']]
    for changes in stored['deltas']:
        positions.append(_apply(positions[-1], changes))
    for action in game['recent_actions']:
        position = expand(positions[action.pop('position_index')])
        action.update(replay_before=position['replay'], state_before=position['state'])
    game.update(expand(positions[-1]))
    return result


def load_report(path):
    """Read either legacy JSON or gzip JSON and expand storage references."""
    path = Path(path)
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return decode_report(json.load(handle))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Expand a bug report for inspection/Replay extraction')
    parser.add_argument('report')
    parser.add_argument('output', help='Destination JSON (use a temporary, unversioned path)')
    args = parser.parse_args()
    with open(args.output, 'x', encoding='utf-8') as handle:
        json.dump(load_report(args.report), handle, ensure_ascii=False, indent=2)
        handle.write('\n')
