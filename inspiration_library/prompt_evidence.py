"""Lossless model-facing evidence encoding; persisted observations stay untouched."""
from collections import Counter
import json


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


RULES = ('Evidence encoding: $ref names an exact value in shared; $columns/$rows encode '
         'objects by column order; $base/$changes encode an ordered list of objects, '
         'each change independently overlays $base using set and remove. Expand these '
         'before reasoning. All state IDs, list order and facts are preserved.')


def pack_evidence(value, *, preserve_selectors=False, preserve_states=False):
    counts = Counter()
    reserved = False
    def count(item):
        nonlocal reserved
        if isinstance(item, str) and len(item) >= 80:
            counts[item] += 1
        elif isinstance(item, list):
            for child in item:
                count(child)
        elif isinstance(item, dict):
            reserved |= any(str(k).startswith('$') for k in item)
            for key, child in item.items():
                if not (preserve_selectors and 'selector' in key):
                    count(child)
    count(value)
    if reserved:
        return value
    shared = {f'e{i}': text for i, (text, n) in enumerate(counts.items()) if n > 1}
    refs = {text: key for key, text in shared.items()}
    def encode(item):
        if isinstance(item, str) and item in refs:
            return {'$ref': refs[item]}
        if isinstance(item, dict):
            return {k: v if preserve_selectors and 'selector' in k else encode(v) for k, v in item.items()}
        if not isinstance(item, list):
            return item
        rows = [encode(row) for row in item]
        choices = [rows]
        if (len(rows) >= 2 and all(isinstance(row, dict) for row in rows)
                and not (preserve_states and any(k in row for row in rows for k in ('state_id', 'delta_id', 'action')))
                and not (preserve_selectors and any('selector' in k for row in rows for k in row))):
            base = rows[0]
            changes = [{'set': {k: v for k, v in row.items() if k not in base or base[k] != v},
                        'remove': [k for k in base if k not in row]} for row in rows]
            choices.append({'$base': base, '$changes': changes})
            if all(set(row) == set(base) for row in rows):
                columns = list(base)
                choices.append({'$columns': columns, '$rows': [[row[k] for k in columns] for row in rows]})
        return min(choices, key=lambda choice: len(dumps(choice)))
    packed = {'encoding': RULES, 'shared': shared, 'evidence': encode(value)}
    return packed if len(dumps(packed)) < len(dumps(value)) else value


def unpack_evidence(value):
    """For tests/audits, not a production quality gate."""
    if not isinstance(value, dict) or value.get('encoding') != RULES:
        return value
    def decode(item):
        if isinstance(item, list):
            return [decode(row) for row in item]
        if not isinstance(item, dict):
            return item
        if '$ref' in item:
            return value['shared'][item['$ref']]
        if '$columns' in item:
            return [{k: decode(v) for k, v in zip(item['$columns'], row)} for row in item['$rows']]
        if '$base' in item:
            return [decode({**{k: v for k, v in item['$base'].items() if k not in change['remove']},
                            **change['set']}) for change in item['$changes']]
        return {k: decode(v) for k, v in item.items()}
    return decode(value['evidence'])


def evidence_json(value, *, preserve_selectors=False, preserve_states=False):
    return dumps(pack_evidence(value, preserve_selectors=preserve_selectors, preserve_states=preserve_states))
