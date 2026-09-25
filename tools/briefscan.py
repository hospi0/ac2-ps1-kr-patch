# -*- coding: utf-8 -*-
"""미션 브리핑 하위 파일 전수 — 일본어 줄 = 하위+0x908 부터 40 B 고정 칸.

  python tools/briefscan.py            # 통계 + 고유 블록 목록

## 규격 (0x8008CA28 선적재 · 0x8008CCB0 줄 그리기 — docs §11)
```
하위+0     u32 ?(영문 쪽 개수 후보)
하위+4     u32 N  일본어 칸 수 (칸0 = 「제목」, 칸1..N-1 = 본문, 칸N = "END")
하위+8     "[English title]" + 영문 내레이션 (번역 대상 아님)
하위+0x908 칸 k = 하위+0x908+40k, NUL 끝 SJIS
```
⛔ 칸 사이의 `-`·`+C3`·`C6` 은 저작 도구가 남긴 «앞 칸 찌꺼기»다 — 제어코드가 아니다.
"""
import collections, hashlib, os, struct, sys, bisect
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
D = open(os.path.join(HERE, '..', 'work', 'ACE2.DAT'), 'rb').read()
N = struct.unpack_from('<I', D, 4)[0]
ENTS = [struct.unpack_from('<II', D, 8 + 8 * i) for i in range(N)]
STARTS = [o * 512 for s, o in ENTS]
LB = '「'.encode('cp932')
SLOT, BASE = 40, 0x908


def where(p):
    k = bisect.bisect_right(STARTS, p) - 1
    s, o = ENTS[k]
    return ('E%03d' % k, p - o * 512) if p < o * 512 + (s & 0xFFFFFFF) else ('TAIL', p - 0x173E400)


def scan():
    out = []
    i = D.find(b'[', 0)
    while i >= 0:
        p = i - 8
        if p >= 0 and D[p + BASE:p + BASE + 2] == LB:
            n = struct.unpack_from('<I', D, p + 4)[0]
            if 1 <= n <= 64:
                recs = []
                for k in range(n + 1):
                    b = D[p + BASE + SLOT * k:p + BASE + SLOT * (k + 1)]
                    recs.append(b.split(b'\0')[0])
                out.append((p, n, recs))
        i = D.find(b'[', i + 1)
    return out


if __name__ == '__main__':
    subs = scan()
    print('브리핑 하위 파일 %d개' % len(subs))
    uniq = collections.OrderedDict()
    for p, n, recs in subs:
        h = hashlib.md5(b'\n'.join(recs)).hexdigest()[:8]
        uniq.setdefault(h, []).append((p, n, recs))
    lines = set(); mx = 0; endok = 0; bad = []
    for h, occ in uniq.items():
        p, n, recs = occ[0]
        if recs[n] == b'END':
            endok += 1
        else:
            bad.append((where(p), recs[n][:12]))
        for r in recs[:n]:
            lines.add(r); mx = max(mx, len(r))
        title = recs[0].decode('cp932', 'replace')
        print('  %s ×%-2d %-5s+%-6X N=%2d  %s' % (h, len(occ), *where(p), n, title))
    ch = sum(len(x) // 2 for x in lines)
    print('고유 블록 %d · END 정상 %d · 고유 줄 %d · %d자 · 최장 %d B' % (len(uniq), endok, len(lines), ch, mx))
    if bad:
        print('⛔ 칸 N 이 END 가 아닌 블록:', bad[:10])
    # 칸 안에 제어바이트·반각 ASCII 가 섞인 줄 — ⛔SJIS 뒷바이트(0x40~0x7E)를 ASCII 로 세면 안 된다
    def kinds(r):
        k = set(); i = 0
        while i < len(r):
            c = r[i]
            if (0x81 <= c <= 0x9F or 0xE0 <= c <= 0xFC) and i + 1 < len(r):
                i += 2; continue
            k.add('ctl' if c < 0x20 or c == 0x7F else 'asc' if c < 0x80 else 'hi')
            i += 1
        return k
    odd = [r for r in lines if kinds(r)]
    print('반각/제어바이트 섞인 줄 %d:' % len(odd), [(r.decode('cp932', 'replace'), sorted(kinds(r))) for r in odd][:15])
