# -*- coding: utf-8 -*-
r"""번역표 검사기 — 빌드 전에 반드시 통과해야 한다 (build.py 가 먼저 부른다).

  python tools/krcheck.py            # 오류가 있으면 종료코드 1

검사 (docs §10~§12):
  보호 칸   ID 집합·원문이 현재 추출 기준선(ac2text)과 같다
  토큰      {br} {lb} {rb} {raw:XX} {sj:XXXX} 문법 · 배정표 밖 글자 = 오류(인코딩 누락은 빌드 에러)
  길이      BRF ≤ 39 B · RAD ≤ 26 B · EXE 는 원문보다 길면 «이주»(풀로 옮김) — 단 «같은 간격 표» 안이면 간격-1 이하
  반각      BRF·RAD 에 반각 금지 (렌더러가 2바이트씩 읽는다)
  세로      RAD 에 가로획 부호 ー…―－‐—～〜 금지 → 「｜」
  EXE 제어  {br} 개수 · «%XX» 코드가 원문과 같아야 한다
  캐시      브리핑 한 편(BRF_nn_*) 의 서로 다른 2바이트 글자 > 256 오류 · > 240 경고
  상태      미번역/작업중/검토필요/판단필요/완료 외 값 = 오류 · 한국어가 있는데 «미번역» = 경고
"""
import collections, csv, io, os, re, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ac2text as T

TEXTD = os.path.join(HERE, '..', 'work', 'text')
FILES = {'EXE': 'exe.tsv', 'BRF': 'brief.tsv', 'RAD': 'radio.tsv'}
STATES = {'미번역', '작업중', '검토필요', '판단필요', '완료'}
VERT_BAD = set('ー…―－‐—～〜')
CACHE_MAX, CACHE_WARN = 256, 240


def load_tsv(kind):
    path = os.path.join(TEXTD, FILES[kind])
    rows = []
    with io.open(path, encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f, delimiter='\t', quoting=csv.QUOTE_NONE):
            rows.append(r)
    return rows


def assign_codes(texts):
    """번역문 전체의 한글 음절 → 0x889F~ 코드 (유니코드 순 · 결정적)."""
    syl = sorted({ch for t in texts for ch in t if '가' <= ch <= '힣'})
    codes = []
    for lead in range(0x88, 0xA0):
        for tr in range(0x40, 0xFD):
            if tr == 0x7F or (lead == 0x88 and tr < 0x9F):
                continue
            codes.append(lead << 8 | tr)
    if len(syl) > len(codes):
        raise SystemExit('⛔ 음절 %d 개가 코드 공간 %d 를 넘는다' % (len(syl), len(codes)))
    return {ch: codes[i] for i, ch in enumerate(syl)}


def stride_groups(exe):
    """«같은 간격으로 늘어선» EXE 문장 3개 이상 → {ID: 간격}. 색인×간격 접근일 수 있어 이주 금지."""
    ents = sorted(exe, key=lambda e: e['addr'])
    out = {}
    i = 0
    while i < len(ents) - 2:
        st = ents[i + 1]['addr'] - ents[i]['addr']
        j = i + 1
        while j + 1 < len(ents) and ents[j + 1]['addr'] - ents[j]['addr'] == st:
            j += 1
        if j - i + 1 >= 3 and st <= 64 and all(len(ents[k]['raw']) < st for k in range(i, j + 1)):
            for k in range(i, j + 1):
                out[ents[k]['id']] = st
            i = j
        else:
            i += 1
    return out


def exe_cap(e, strides):
    """EXE 문장을 «제자리»에 쓸 수 있는 최대 바이트(NUL 제외).
    기본 = 원문 길이. 같은 간격 표 칸이면 원본에서 문자열 뒤로 이어지는 0 구간까지(간격 안에서만) —
    ⛔표의 «마지막 칸»은 간격만큼 비어 있지 않을 수 있다(0x80019284 뒤 20 B 에 다른 문자열)."""
    n = len(e['raw'])
    st = strides.get(e['id'])
    if not st:
        return n
    o = T.exe_off(e['addr'])
    j = o + n
    while j < o + st and T.D[j] == 0:
        j += 1
    return (j - o) - 1


def check(verbose=True):
    """→ (오류 수, 경고 수, 번역 dict {ID: 한국어}, 배정표, 기준선 dict)"""
    base = {'EXE': T.exe_strings(), 'BRF': T.briefings()[0], 'RAD': T.radio()[0]}
    bmap = {k: {e['id']: e for e in v} for k, v in base.items()}
    strides = stride_groups(base['EXE'])
    err, warn = [], []
    tr = {}
    tabs = {k: load_tsv(k) for k in FILES}
    for k, rows in tabs.items():
        ids = [r['ID'] for r in rows]
        if len(ids) != len(set(ids)):
            err.append('%s: ID 중복' % k)
        if set(ids) != set(bmap[k]):
            err.append('%s: ID 집합이 기준선과 다르다 (없음 %d · 남음 %d)' % (
                k, len(set(bmap[k]) - set(ids)), len(set(ids) - set(bmap[k]))))
        for r in rows:
            b = bmap[k].get(r['ID'])
            if b is None:
                continue
            if r['원문'] != b['jp']:
                err.append('%s 원문(보호 칸)이 바뀌었다' % r['ID'])
            st = r.get('상태') or ''
            if st not in STATES:
                err.append('%s 상태 %r' % (r['ID'], st))
            ko = r.get('한국어') or ''
            if ko:
                tr[r['ID']] = ko
                if st == '미번역':
                    warn.append('%s 한국어가 있는데 상태가 «미번역»' % r['ID'])
    cmap = assign_codes(tr.values())
    for rid, ko in tr.items():
        k = rid[:3]
        b = bmap[k][rid]
        try:
            enc = T.encode(ko, cmap)
        except ValueError as ex:
            err.append('%s %s' % (rid, ex)); continue
        if k in ('BRF', 'RAD'):
            if '{' in ko:
                err.append('%s 토큰 금지(%s)' % (rid, ko))
            half = [ch for ch in ko if ord(ch) < 0x80]
            if half:
                err.append('%s 반각 %r — 전각으로' % (rid, ''.join(half)))
            lim = T.BRF_MAX if k == 'BRF' else T.RAD_MAX
            if len(enc) > lim:
                err.append('%s %d B > %d B (%d자 초과)' % (rid, len(enc), lim, (len(enc) - lim + 1) // 2))
            if k == 'RAD':
                bad = [ch for ch in ko if ch in VERT_BAD]
                if bad:
                    err.append('%s 세로쓰기에 가로획 부호 %r → 「｜」' % (rid, ''.join(bad)))
        else:  # EXE
            if ko.count('{br}') != b['jp'].count('{br}'):
                err.append('%s {br} 개수 %d ≠ 원문 %d' % (rid, ko.count('{br}'), b['jp'].count('{br}')))
            pj = re.findall(r'%[0-9A-Fa-f]{2}', b['jp']); pk = re.findall(r'%[0-9A-Fa-f]{2}', ko)
            if pj != pk:
                err.append('%s «%%XX» 제어 %s ≠ 원문 %s' % (rid, pk, pj))
            if any(0x20 <= ord(ch) < 0x7F and ch not in '%' for ch in ko) and not any(0x20 <= ord(ch) < 0x7F for ch in b['jp']):
                warn.append('%s 원문에 없던 반각 문자' % rid)
            if rid in strides and len(enc) > exe_cap(b, strides):
                err.append('%s 같은 간격 표 안 — %d B > 제자리 한도 %d B (이주 금지)' % (rid, len(enc), exe_cap(b, strides)))
    # 브리핑 캐시 한도
    blk = collections.defaultdict(set)
    for e in base['BRF']:
        s = tr.get(e['id']) or e['jp']
        enc = T.encode(s, cmap) if e['id'] in tr else e['raw']
        i = 0
        while i < len(enc):
            if T.is_lead(enc[i]):
                blk[e['id'][:6]].add(enc[i:i + 2]); i += 2
            else:
                i += 1
    for bid, s in sorted(blk.items()):
        if len(s) > CACHE_MAX:
            err.append('%s 고유 글자 %d > %d (글자 캐시 넘침)' % (bid, len(s), CACHE_MAX))
        elif len(s) > CACHE_WARN:
            warn.append('%s 고유 글자 %d (한도 %d 근접)' % (bid, len(s), CACHE_MAX))
    if verbose:
        tot = {k: len(v) for k, v in bmap.items()}
        done = collections.Counter(rid[:3] for rid in tr)
        print('번역 %s · 음절 %d · 같은 간격 표 문장 %d' % (
            ' · '.join('%s %d/%d' % (k, done[k], tot[k]) for k in FILES), len(cmap), len(strides)))
        mx = max((len(s) for s in blk.values()), default=0)
        print('브리핑 한 편 최대 고유 글자 %d' % mx)
        for m in err[:40]:
            print('  ⛔', m)
        for m in warn[:20]:
            print('  ⚠', m)
        print('오류 %d · 경고 %d' % (len(err), len(warn)))
    return len(err), len(warn), tr, cmap, base, strides


if __name__ == '__main__':
    e, w, *_ = check()
    sys.exit(1 if e else 0)
