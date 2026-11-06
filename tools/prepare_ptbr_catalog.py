"""Build reviewed PT-BR text from the pinned HNNEWGAMES patch, never game media."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'launcher'))
from ps2_disc import Iso, Pck
import ps2_text

FAN_PACK = (181235029, 'acbcb5511871ed40b32bd3fe126a308513dfa518fa514689c55b8014f6d24816')
ORIGINAL_PACK = (181235029, '8f96dc906a0af489b60ef281dd90d26ab0314939cb5d68f4ac3879543811a4ad')
EXTENDED = set('¡©\xad®°¿ÀÁÂÃÄÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜß')
ACCENTS = str.maketrans('àáâãäçèéêëìíîïñòóôõöùúûü\xa0', 'ÀÁÂÃÃÇÈÉÊËÌÍÎÏÑÒÓÔÕÕÙÚÛÜ ')


def normalized(value):
    # The audited fan tables use umlauts for most Portuguese nasal vowels.
    value = value.translate(ACCENTS).replace('Ä', 'Ã').replace('Ö', 'Õ')
    if not value or len(value.encode('latin1')) >= 4096 or any(
            not (32 <= ord(c) < 127 or c in '\r\n\t' or c in EXTENDED) for c in value):
        raise ValueError('Invalid PT-BR text or unsupported glyph')
    return value


def read_padded(raw, sha256, padding):
    if hashlib.sha256(raw).hexdigest() != sha256 or not 0 <= padding <= 1240:
        raise ValueError('Unrecognized fan translation table')
    if padding:
        if raw[-padding:] != bytes(padding):
            raise ValueError('Invalid fan translation table padding')
        raw = raw[:-padding]
    return ps2_text.read_table(raw)


def disc_tables(path, pin, padded):
    with Iso(path) as iso:
        if iso.size('PACKFILE.PCK') != pin[0] or iso.digest('PACKFILE.PCK') != pin[1]:
            raise ValueError('Unexpected PS2 translation source archive')
        pack = Pck(iso, 'PACKFILE.PCK')
        result = {}
        for name in sorted(pack.entries):
            if '/localization/' not in name or not name.endswith('_s.bxml'):
                continue
            raw = pack.read(name)
            if name in padded:
                row = padded[name]
                result[name] = read_padded(raw, row['sha256'], row['padding'])
            else:
                result[name] = ps2_text.read_table(raw)
        return result


def catalogue(original, fan, spanish, edits):
    contexts, output, issues, seen, uses = {}, {}, [], set(), Counter()
    for name, rows in sorted(original.items()):
        if not name.endswith('_e.bxml'):
            continue
        source = name[:-6] + 's.bxml'
        for key, english in rows.items():
            if not english:
                continue
            item = contexts.setdefault((key, english), {'candidates':set(), 'paths':set(), 'unchanged':False})
            item['paths'].add(name)
            candidate = fan.get(source, {}).get(key)
            if candidate:
                item['candidates'].add(normalized(candidate))
                if candidate == spanish.get(source, {}).get(key):
                    item['unchanged'] = True
    identities = {}
    for (key, english), item in sorted(contexts.items()):
        identity = ps2_text.context_id(key, english)
        if identity in identities and identities[identity] != (key, english):
            raise ValueError('Catalogue context identity collision')
        identities[identity] = key, english
        candidates = sorted(item['candidates'])
        reason = []
        if identity in edits:
            value = normalized(edits[identity])
            seen.add(identity)
            source = 'reviewed'
        else:
            value = candidates[0] if len(candidates) == 1 else None
            if not candidates: reason.append('missing')
            elif len(candidates) != 1: reason.append('conflict')
            if item['unchanged']: reason.append('unchanged_spanish_requires_review')
            source = 'fan_translation'
        if value is not None and ps2_text.tokens(value) != ps2_text.tokens(english):
            reason.append('semantic_tokens')
        if reason:
            issues.append({'identity':f'{identity:016x}','key':key,'english':english,
                           'candidates':candidates,'reason':reason,'paths':sorted(item['paths'])})
        else:
            output[identity] = value
            uses[source] += 1
    if seen != edits.keys():
        raise ValueError('Corrections do not match original contexts')
    report = {'unique_contexts':len(contexts),'accepted':len(output),'review_count':len(issues),
              'reasons':dict(Counter(reason for item in issues for reason in item['reason'])),
              'sources':dict(uses),'issues':issues,'original_contexts_embedded':False}
    if issues:
        return None, report
    raw = bytearray(ps2_text.MAGIC + struct.pack('<I',len(output)))
    for identity, text in sorted(output.items()):
        encoded = text.encode('latin1')
        raw.extend(struct.pack('<QI',identity,len(encoded)))
        raw.extend(encoded)
    return bytes(raw), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-iso', required=True, type=Path)
    parser.add_argument('--patched-iso', required=True, type=Path)
    parser.add_argument('--xbox-pack', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--corrections', type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise ValueError('Catalogue output already exists')
    if args.xbox_pack.stat().st_size > 256*1024**2:
        raise ValueError('Xbox text archive exceeds supported size')
    original = ps2_text.tables(args.xbox_pack.read_bytes())
    if ps2_text.inventory(original) != ps2_text.CONTEXT_SHA256:
        raise ValueError('Unsupported original Xbox text contexts')
    pins = json.loads(Path(__file__).with_name('ptbr-source-tables.json').read_text(encoding='utf-8'))
    fan = disc_tables(args.patched_iso,FAN_PACK,pins)
    spanish = disc_tables(args.original_iso,ORIGINAL_PACK,{})
    edits = {}
    if args.corrections:
        document = json.loads(args.corrections.read_text(encoding='utf-8'))
        if not isinstance(document,dict) or set(document) != {'schema','contexts'} or document['schema'] != 1:
            raise ValueError('Unsupported PT-BR corrections')
        if not isinstance(document['contexts'],dict) or len(document['contexts']) > 10000:
            raise ValueError('Invalid PT-BR correction count')
        for identity,value in document['contexts'].items():
            if len(identity) != 16 or any(c not in '0123456789abcdef' for c in identity) or not isinstance(value,str):
                raise ValueError('Invalid PT-BR correction')
            edits[int(identity,16)] = value
    raw, report = catalogue(original,fan,spanish,edits)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'issues'},indent=2))
    if args.output:
        if raw is None:
            raise ValueError('Review all reported contexts before producing a catalogue')
        with args.output.open('xb') as target:
            target.write(raw)


if __name__ == '__main__':
    main()
