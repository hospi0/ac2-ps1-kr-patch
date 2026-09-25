# -*- coding: utf-8 -*-
r"""번역 대상 추출 — 본체 EXE 문장 · 미션 브리핑 · 무선 메시지 → 번역표 TSV + 위치 JSON.

  python tools/ac2text.py            # work/text/{exe,brief,radio}.tsv + locs.json 생성, 왕복 검증
  python tools/ac2text.py --check    # 쓰지 않고 왕복 검증만

## 번역표 (UTF-8 TSV) — 번역자가 고치는 칸은 «한국어·상태·메모» 뿐
```
ID	최대B	원문	한국어	상태	메모
```
- 원문·최대B·ID 는 보호 칸(추출기가 채운다). 위치·원본 바이트는 `locs.json` 한 곳에서만 관리.
- 상태: 미번역 / 작업중 / 검토필요 / 판단필요 / 완료   (docs · 스킬 규약 translation-artifacts §4)

## 토큰 (바이트와 1:1)
`{br}`=0x0A · `{raw:XX}`=해독 안 한 1바이트 · `{sj:XXXX}`=cp932 왕복이 안 되는 2바이트 · `{lb}` `{rb}`=중괄호

## 종류 (docs §10·§11)
- EXE  본체 EXE(ACE2.DAT+0x800) 의 문장 중 «포인터가 가리키고 SJIS 가 든 것». 길이 제한 = 이주 가능(포인터 교체)이라 최대B 는 원문 길이(참고값).
- BRF  브리핑 하위 파일 +0x908+40k 칸 (k<N). 최대 39 B(NUL 포함 40). 같은 블록 사본 전부에 같은 번역.
- RAD  무선 메시지 32 B 레코드 126개. 최대 26 B(렌더러 0x1A). 90벌 전부에 같은 번역.
"""
import collections, hashlib, json, os, re, struct, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
import briefscan

D = briefscan.D
OUTD = os.path.join(ROOT, 'work', 'text')
EXE_BASE, EXE_TEXT, EXE_SIZE = 0x80018000, 0x1000, 0xA1800      # DAT 오프셋 = a - EXE_BASE + EXE_TEXT
RAD_KEY_ENT, RAD_KEY_OFF, RAD_N, RAD_REC, RAD_MAX = 154, 0x22B80, 126, 32, 26
BRF_MAX = 39
# 무선 메시지는 화면 오른쪽 «세로쓰기»(글리프를 회전 없이 16×16 으로 위→아래) — docs §12
RAD_NOTE = '세로쓰기·전각 13자 이하·반각 금지·가로획 부호(ー…―) 대신 ｜'


def exe_off(a):
    return a - EXE_BASE + EXE_TEXT


# ── 토큰 코덱
def is_lead(c):
    return 0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC


def decode(b):
    out = []; i = 0
    while i < len(b):
        c = b[i]
        if is_lead(c) and i + 1 < len(b) and 0x40 <= b[i + 1] <= 0xFC and b[i + 1] != 0x7F:
            two = b[i:i + 2]
            try:
                ch = two.decode('cp932')
                if ch.encode('cp932') == two:
                    out.append(ch)
                else:
                    out.append('{sj:%02X%02X}' % (two[0], two[1]))
            except UnicodeDecodeError:
                out.append('{sj:%02X%02X}' % (two[0], two[1]))
            i += 2; continue
        if c == 0x0A:
            out.append('{br}')
        elif c == 0x7B:
            out.append('{lb}')
        elif c == 0x7D:
            out.append('{rb}')
        elif 0x20 <= c < 0x7F:
            out.append(chr(c))
        else:
            out.append('{raw:%02X}' % c)
        i += 1
    return ''.join(out)


TOK = re.compile(r'\{(br|lb|rb|raw:[0-9A-F]{2}|sj:[0-9A-F]{4})\}')


def encode(s, extra=None):
    """토큰 문자열 → 바이트. extra = {글자: 2바이트 코드} (한글 배정표). 모르는 글자는 빌드 에러."""
    out = bytearray(); i = 0
    while i < len(s):
        if s[i] == '{':
            m = TOK.match(s, i)
            if not m:
                raise ValueError('토큰 문법 오류 @%d: %r' % (i, s))
            t = m.group(1)
            out += {'br': b'\n', 'lb': b'{', 'rb': b'}'}.get(t) or bytes.fromhex(t.split(':')[1])
            i = m.end(); continue
        ch = s[i]
        if extra and ch in extra:
            c = extra[ch]; out += bytes([c >> 8, c & 0xFF])
        else:
            try:
                out += ch.encode('cp932')
            except UnicodeEncodeError:
                raise ValueError('⛔ 인코딩 불가 글자 %r (배정표에 없음)' % ch)
        i += 1
    return bytes(out)


# ── EXE 문장
def exe_strings():
    X = D[EXE_TEXT:EXE_TEXT + EXE_SIZE]
    lo, hi = EXE_BASE, EXE_BASE + EXE_SIZE
    refs = collections.defaultdict(list)            # 목표 → [('u32', 주소) | ('hi16', lui주소, lo주소)]
    W = [struct.unpack_from('<I', X, p)[0] for p in range(0, len(X) - 3, 4)]
    for i, w in enumerate(W):
        a = lo + 4 * i
        if lo <= w < hi:
            refs[w].append(('u32', a))
        if w >> 26 == 0x0F:
            rt = (w >> 16) & 31; h = (w & 0xFFFF) << 16
            for k in range(1, 12):
                if i + k >= len(W):
                    break
                y = W[i + k]
                if (y >> 26) in (0x09, 0x0D) and (y >> 21) & 31 == rt:
                    l = y & 0xFFFF
                    v = (h + (l - 0x10000 if (y >> 26) == 0x09 and l & 0x8000 else l)) & 0xFFFFFFFF
                    if lo <= v < hi:
                        refs[v].append(('hi16', a, lo + 4 * (i + k)))
                    break
    ents = []
    for t in sorted(refs):
        o = t - lo
        e = X.find(b'\0', o, o + 512)
        if e < 0 or e == o:
            continue
        b = X[o:e]
        # SJIS 2바이트 글자가 하나 이상 있고, 전체가 «글자·{br}·ASCII» 로만 된 것
        txt = decode(b)
        if '{raw:' in txt or '{sj:' in txt:
            continue
        if not any(ord(ch) > 0x7F for ch in txt):
            continue
        ents.append((t, b, txt, refs[t]))
    # 앞 문자열의 꼬리(공유 접미사)를 가리키는 것 표시
    spans = [(t, t + len(b)) for t, b, _, _ in ents]
    out = []
    for t, b, txt, rf in ents:
        host = [s for s, e in spans if s < t < e]
        out.append(dict(id='EXE_%08X' % t, addr=t, raw=b, jp=txt, refs=rf,
                        suffix_of=('EXE_%08X' % host[0]) if host else None))
    return out


# ── 브리핑
def briefings():
    subs = briefscan.scan()
    blocks = collections.OrderedDict()
    for p, n, recs in sorted(subs):
        key = hashlib.md5(b'\n'.join(recs[:n])).hexdigest()
        blocks.setdefault(key, []).append((p, n, recs))
    out = []
    for bi, (key, occ) in enumerate(blocks.items(), 1):
        p0, n, recs = occ[0]
        for k in range(n):
            locs = [p + briefscan.BASE + briefscan.SLOT * k for p, _, _ in occ]
            out.append(dict(id='BRF_%02d_%02d' % (bi, k), raw=recs[k], jp=decode(recs[k]), locs=locs,
                            note=('제목' if k == 0 else '') + (' · 사본 %d' % len(occ))))
    return out, len(blocks), len(subs)


# ── 무선 메시지
def radio():
    s, o = struct.unpack_from('<II', D, 8 + 8 * RAD_KEY_ENT)
    t0 = o * 512 + RAD_KEY_OFF
    key = D[t0:t0 + RAD_REC * 8]
    copies = []
    i = D.find(key)
    while i >= 0:
        copies.append(i); i = D.find(key, i + 1)
    ref = D[t0:t0 + RAD_REC * RAD_N]
    for c in copies:
        assert D[c:c + RAD_REC * RAD_N] == ref, '⛔ 무선 사본 %X 가 기준과 다르다' % c
    out = []
    for k in range(RAD_N):
        b = ref[RAD_REC * k:RAD_REC * (k + 1)].split(b'\0')[0]
        out.append(dict(id='RAD_%03d' % k, raw=b, jp=decode(b), locs=[c + RAD_REC * k for c in copies],
                        note='빈 레코드' if not b else RAD_NOTE))
    return out, len(copies)


def roundtrip(exe, brf, rad):
    """① 토큰→바이트 = 원본  ② 모든 위치에 원문을 다시 써 넣은 DAT = 원본 DAT"""
    bad = 0
    for e in exe + brf + rad:
        if encode(e['jp']) != e['raw']:
            bad += 1; print('  ⛔ 토큰 왕복 실패', e['id'], e['jp'])
    dat = bytearray(D)
    for e in exe:
        o = exe_off(e['addr'])
        dat[o:o + len(e['raw'])] = encode(e['jp'])
    for e in brf + rad:
        for o in e['locs']:
            b = encode(e['jp'])
            dat[o:o + len(b)] = b
    same = bytes(dat) == D
    # 위치 검사: 각 위치의 원본 바이트 = raw + NUL
    for e in brf + rad:
        for o in e['locs']:
            if D[o:o + len(e['raw']) + 1] != e['raw'] + b'\0':
                bad += 1; print('  ⛔ 위치 불일치', e['id'], hex(o))
    return bad, same


def write_tsv(path, rows, maxb):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('ID\t최대B\t원문\t한국어\t상태\t메모\n')
        for e in rows:
            f.write('%s\t%d\t%s\t\t미번역\t%s\n' % (e['id'], maxb(e), e['jp'], e.get('note') or ''))


def main():
    exe = exe_strings()
    brf, nblk, nsub = briefings()
    rad, ncopy = radio()
    ch = lambda L: sum(sum(1 for c in e['jp'] if ord(c) > 0x7F) for e in L)
    sfx = sum(1 for e in exe if e['suffix_of'])
    nref = sum(len(e['refs']) for e in exe)
    print('EXE  %d문장 · %d자 · 참조 %d곳 (u32 %d · lui 쌍 %d) · 공유 접미사 %d' % (
        len(exe), ch(exe), nref, sum(1 for e in exe for r in e['refs'] if r[0] == 'u32'),
        sum(1 for e in exe for r in e['refs'] if r[0] == 'hi16'), sfx))
    print('BRF  %d블록(하위 파일 %d) · %d줄 · %d자 · 최장 %d B' % (nblk, nsub, len(brf), ch(brf), max(len(e['raw']) for e in brf)))
    print('RAD  %d줄 · %d자 · 사본 %d벌 · 최장 %d B' % (len(rad), ch(rad), ncopy, max(len(e['raw']) for e in rad)))
    bad, same = roundtrip(exe, brf, rad)
    print('왕복: 토큰·위치 불일치 %d · 원문 재삽입 DAT = 원본 %s' % (bad, 'OK' if same else '⛔다름'))
    if bad or not same:
        raise SystemExit('⛔ 왕복 실패 — 쓰지 않는다')
    if '--check' in sys.argv:
        return
    os.makedirs(OUTD, exist_ok=True)
    write_tsv(os.path.join(OUTD, 'exe.tsv'), exe, lambda e: len(e['raw']))
    write_tsv(os.path.join(OUTD, 'brief.tsv'), brf, lambda e: BRF_MAX)
    write_tsv(os.path.join(OUTD, 'radio.tsv'), rad, lambda e: RAD_MAX)
    locs = {
        'source': {'image_md5': 'ECE1E7B3F995B67483B94F98401BB925', 'dat_lba': 73,
                   'exe': {'base': hex(EXE_BASE), 'dat_text_off': hex(EXE_TEXT), 'size': hex(EXE_SIZE)}},
        'EXE': {e['id']: {'addr': hex(e['addr']), 'raw': e['raw'].hex(), 'suffix_of': e['suffix_of'],
                          'refs': [[r[0]] + [hex(x) for x in r[1:]] for r in e['refs']]} for e in exe},
        'BRF': {e['id']: {'raw': e['raw'].hex(), 'max': BRF_MAX, 'locs': [hex(o) for o in e['locs']]} for e in brf},
        'RAD': {e['id']: {'raw': e['raw'].hex(), 'max': RAD_MAX, 'locs': [hex(o) for o in e['locs']]} for e in rad},
    }
    with open(os.path.join(OUTD, 'locs.json'), 'w', encoding='utf-8') as f:
        json.dump(locs, f, ensure_ascii=False, indent=1)
    print('→ work/text/{exe,brief,radio}.tsv · locs.json')


if __name__ == '__main__':
    main()
