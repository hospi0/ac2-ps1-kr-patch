# -*- coding: utf-8 -*-
"""16×15 조합형 부품 설계 — 초성 6벌 · 중성 2벌 · 종성 2벌 = **210 부품**

  python tools/johab.py            # 미리보기 PNG
  python tools/johab.py parts      # 부품 시트

## 왜 조합형인가
Tobal 2 는 폰트를 **BIOS 한자 ROM**에서 가져오고, 우리가 글리프를 넣을 수 있는 자리가
실행파일 안 **약 4 KB** 뿐이다(실행파일을 늘리면 게임 변수와 충돌).
완성형은 30 B/자 라 130자가 천장 — 전면 한글화가 안 된다.
조합형이면 **210 부품 × 30 B = 6,300 B** 로 **11,172자 전부** 표현된다.

## 벌 규칙
```
초성 벌0 : 중성이 «세로»(ㅏㅐㅑㅒㅓㅔㅕㅖㅣ)      -> 왼쪽 세로로 길게
초성 벌1 : 중성이 «가로·섞임»(ㅗㅛㅜㅠㅡ, ㅘㅚㅢ…) -> 위쪽 가로로 납작하게
중성 벌0 : 받침 없음      중성 벌1 : 받침 있음(세로로 줄여 자리를 낸다)
종성 1벌 : 아래 5줄
```
★★부품은 **폰트에서 마스크로 떼어낸다**(네오둥근모 16×16 완성형).
  ⛔호환자모를 상자에 «늘려 넣으면» 획이 뭉개져 못 읽는다 — 특히 ㅡ/ㅗ/ㅜ 가 덩어리가 된다.
    (2026-08-24 첫 시안이 그렇게 실패했다)
"""
import os, sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import io

W, H = 16, 15
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
JONG = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'
VERT = set('ㅏㅐㅑㅒㅓㅔㅕㅖㅣ')

# (x0, y0, x1, y1) — 부품을 넣을 상자 (양끝 포함)
BOX = {
    ('C', 0): (0, 1, 8, 13),      # 초성 · 중성 세로
    ('C', 1): (1, 0, 14, 7),      # 초성 · 중성 가로
    ('V', 0): None,               # 중성은 아래에서 종류별로
    ('J', 0): (2, 10, 13, 14),    # 종성
}
V_VERT = {0: (9, 0, 15, 14), 1: (9, 0, 15, 10)}     # 세로모음 (받침무/유)
V_HORZ = {0: (0, 8, 15, 14), 1: (0, 7, 15, 11)}     # 가로모음
V_MIX = {0: (0, 0, 15, 14), 1: (0, 0, 15, 11)}      # 섞임모음


def _tiles():
    import json
    import numpy as np
    FS = os.path.join(ROOT, 'work', 'fontsite')
    fid = 'font-45065ee8eedf7051'
    gm = json.load(io.open(os.path.join(FS, fid + '_glyph_map.json'), encoding='utf-8'))
    raw = open(os.path.join(FS, fid + '.bin'), 'rb').read()
    t = np.unpackbits(np.frombuffer(raw, dtype=np.uint8).reshape(-1, 32), axis=1).reshape(-1, 16, 16)
    return gm, t


def _g(gm, t, cho, jung, jong):
    """음절 -> 16×15 격자 (0/1)"""
    u = 0xAC00 + (cho * 21 + jung) * 28 + jong
    i = gm.get(chr(u))
    if i is None:
        return None
    return [[int(t[i][y][x]) for x in range(W)] for y in range(H)]


def _mask(g, x0=0, y0=0, x1=15, y1=14):
    o = [[0] * W for _ in range(H)]
    if not g:
        return o
    for y in range(y0, min(y1, H - 1) + 1):
        for x in range(x0, min(x1, W - 1) + 1):
            o[y][x] = g[y][x]
    return o


def _gg(gm, t, cho, jung, jong, alt=(11, 0, 2, 6, 5, 3, 9)):
    """★KS X 1001 2350자에는 **없는 음절**이 있다 — 초성을 바꿔 가며 찾는다.
    (「옪」 같은 조합은 완성형 표에 아예 없어 None 이 돌아온다)"""
    g = _g(gm, t, cho, jung, jong)
    if g:
        return g
    for c in alt:
        g = _g(gm, t, c, jung, jong)
        if g:
            return g
    return [[0] * W for _ in range(H)]


def _rest(gm, t, grp, j, k, src):
    """같은 중성·종성을 가진 **ㅇ 글자**에서 «초성이 아닌 부분»(모음+받침)을 뜬다.

    ★★초성 부품은 이걸 **빼서** 만든다. 경계를 상수 한 줄로 자르면 반드시 어딘가
      샌다 — 「낙」의 ㄱ 받침 가로획, 「윅」의 ㅜ 가로획이 초성에 딸려 나왔다
      (2026-08-25 사용자 지적 2건). 빼기는 새는 곳이 없다.
    """
    g = _g(gm, t, 11, j, k) or _gg(gm, t, 11, j, k)
    o = [[0] * W for _ in range(H)]
    # ★★가로획 줄은 **ㅇ 음절에서만** 잰다 — 소스 음절로 재면 ㅎ·ㅍ·ㅌ 자신의
    #   가로획을 모음 획으로 오인한다(「흐」는 bar=4 로 잡혀 ㅎ 밑이 잘렸다, 2026-08-25).
    bar = _bar(g)
    if grp == 1:                                   # 가로모음 — 초성이 전폭이라 오른쪽은 못 뺀다
        y0 = max(_cend2(g, bar, x1=16), _cend2(src, bar, x1=16)) + 1
    else:
        # ★받침이 없으면 세로모음 쪽엔 **뺄 게 없다** — `_jstart` 를 부르면 초성
        #   아랫부분을 받침으로 오인해 「너·리·대」의 초성이 깎인다(2026-08-25).
        if grp == 0:
            y0 = H if not k else max(_jstart(g), _jstart(src))
        else:
            y0 = max(_cend2(g, bar), _cend2(src, bar)) + 1
        for y in range(H):
            for x in range(9, W):
                o[y][x] = 1
    # ★★«픽셀 빼기»가 아니라 «영역 지우기» — 소스와 ㅇ 음절의 모음 위치가 한 줄만
    #   달라도 남는다. 「흐」의 ㅡ 는 y13, 「으」는 y12 라 「후」 밑에 가로획이 남았다.
    for y in range(y0, H):
        for x in range(W):
            o[y][x] = 1
    return o


def _sub(a, b):
    return [[a[y][x] & ~b[y][x] & 1 for x in range(W)] for y in range(H)]


def _blank(g, y):
    return not any(g[y])


def _bar(g, lo=4, hi=15, wide=10):
    """가로모음의 «가로획» 줄을 실측한다 (ㅡ·ㅗ 의 긴 가로선).

    ⛔초성 경계를 고정 상수로 자르면 **ㅅ·ㅈ·ㅌ 처럼 아래로 뻗는 초성이 잘린다**
      (2026-08-25 사용자 지적: 「스」의 ㅅ, ㅌ 밑이 뭉갬).
    """
    # ★★«그 줄 잉크 합»으로 재면 안 된다 — 「왁」의 ㅇ 은 y4 가 ###..###..##### 라
    #   합이 11 이라 가로획으로 오인된다(2026-08-25). **이어진 길이**로 재야 한다.
    for y in range(lo, hi):
        run = m = 0
        for v in g[y]:
            run = run + 1 if v else 0
            m = max(m, run)
        if m >= wide:
            return y
    return 12          # ★받침 없는 가로모음은 가로획이 y12 에 있다


def _cend(g, bar):
    """초성 잉크가 끝나는 줄 — «가로획 위쪽에서 마지막으로 잉크가 있는 줄».

    ★★한 줄로 초성/중성을 가르면 안 된다 — ㅗ 의 세로획이 **가로획 위**에 있어서
      가로획 기준으로 자르면 세로획이 통째로 초성 쪽에 남거나 사라진다
      (2026-08-25: 「토→트」, 「돌→들」, 「온→은」).
    """
    for y in range(bar - 1, 0, -1):
        if any(g[y]):
            return y
    return bar - 1


JONGC = (1, 4, 8, 16, 17, 21, 19, 22, 27)          # ㄱㄴㄹㅁㅂㅇㅅㅈㅎ
# ★섞임모음 초성은 **ㅟ 계열**에서 뜬다 — ㅘ 계열(「와」)은 초성이 y8 까지 내려와
#   경계를 낮게 잡으면 ㅇ 밑이 뚫린다. ㅟ 계열은 y6 에서 끝나 잘릴 게 없다.
JUNGC = {0: (0, 4, 20, 2, 6), 1: (18, 8, 13, 12, 17), 2: (16, 15, 14, 9, 11, 19, 10)}


def _chosrc(gm, t, cho, grp, f):
    """초성 부품의 출처 음절 — ★**초성은 절대 안 바꾸고** 중성·종성만 바꿔 가며 찾는다.

    ⛔`_gg` 의 «초성 바꿔 찾기» 에 맡기면 완성형에 없는 조합(쁩·쯕·톽…)에서
      **엉뚱한 자음**이 부품이 된다 — 2026-08-25 「뽑→옵」「쪽→옥」.
    """
    for j in JUNGC[grp]:
        for k in ((0,) if not f else JONGC):
            if _g(gm, t, cho, j, k) and _g(gm, t, 11, j, k):
                return j, k          # ★ㅇ 글자도 있어야 «모음·받침 영역»을 뺄 수 있다
    return JUNGC[grp][0], (0 if not f else 1)


def _cend2(g, bar, wide=4, x1=9):
    """초성이 끝나는 줄 — «굵은»(wide px 이상) 줄만 초성으로 본다.

    ★★ㅗ·ㅜ 의 세로획은 2 px 라 그냥 «마지막 잉크 줄»로 자르면 세로획이 초성에
      딸려 들어간다 — 2026-08-25 「의→외」「토→트」.
    """
    # ★«그 줄 합»이 아니라 **이어진 길이** — ㅛ 의 두 세로획(2+2 px)이 합 4 라
    #   합으로 재면 획으로 오인돼 ㅛ 가 통째로 사라진다 (2026-08-25 「요→으」).
    for y in range(bar - 1, 0, -1):
        run = m = 0
        for v in g[y][:x1]:
            run = run + 1 if v else 0
            m = max(m, run)
        if m >= wide:
            return y
    return 8


def _jstart(g, start=8):
    """받침이 시작하는 줄.

    ★★빈 줄이 없는 글자가 있다 — 「궁·욱」은 ㅜ 의 세로획(y8)이 받침(y9)에 바로 닿는다.
      ⛔그때 상수로 때우면 받침 윗줄이 중성 부품에 딸려 들어가
        «ㄴ 받침 위 가로획 찌꺼기»가 된다 (2026-08-25 사용자 지적).
      세로획은 x6~9 안에만 있으므로 «그 밖에 잉크가 나오는 첫 줄»이 받침이다.
    """
    for y in range(start, 14):
        if _blank(g, y):
            return y + 1
    for y in range(start, 14):
        if any(g[y][:6]) or any(g[y][10:]):
            return y
    return 10


def build():
    """★부품을 «폰트에서 마스크로 떼어낸다» — 늘려 넣으면 획이 뭉갠다.

    초성 4벌(중성 세로/가로 × 받침 무/유) · 중성 2벌(받침 무/유) · 종성 2벌(중성군) = **172 부품**
    ⛔초성을 받침 유무로 안 나누면 받침 글자에서 초성이 너무 길어 뭉갠다
      (2026-08-24 첫 시안: 이름->이릉, 왕->앙, 격->겨)
    """
    gm, t = _tiles()
    P = {}
    # ★★초성 **6벌** — 중성이 세로/가로/섞임 × 받침 무·유.
    #   ⛔섞임모음(ㅘㅚㅢ…)에 가로벌을 쓰면 초성이 폭을 다 먹어 «황→홯» 처럼 뭉갠다.
    #   ★부품은 «소스 글자 − 같은 조합 ㅇ 글자의 모음·받침 영역»으로 만든다(_rest).
    for i in range(19):
        for f in (0, 1):
            for grp in (0, 1, 2):
                j, k = _chosrc(gm, t, i, grp, f)
                g = _g(gm, t, i, j, k) or [[0] * W for _ in range(H)]
                g = _sub(g, _rest(gm, t, grp, j, k, g))
                if grp != 1:
                    g = _mask(g, x1=8)
                P[('C', i, grp, f)] = g
    for i, v in enumerate(JUNG):
        for f in (0, 1):
            g = _gg(gm, t, 11, i, f)                                   # 초성 ㅇ
            y1 = _jstart(g) - 1 if f else 14
            # ★★모음이 시작하는 줄은 **모음마다** 잰다 — 「우」는 가로획이 y9,
            #   「으」는 y12, 「위」는 y8 이다. 한 값으로 자르면 ㅜ 계열 가로획이 통째로
            #   사라진다 (2026-08-25: 「귀→거」, 「궤→게」).
            if v in VERT:
                P[('V', i, f)] = _mask(g, x0=9, y1=y1)
            elif v in 'ㅗㅛㅜㅠㅡ':
                q = _mask(g, y0=_cend2(g, _bar(g), x1=16) + 1, y1=y1)
                # ★ㅜ·ㅠ 는 가로획이 y9 로 높아 초성(ㅡ 기준, y8 까지) 밑변에 붙는다.
                #   받침 없을 때만 한 줄 내리면 원본처럼 한 줄 뜬다.
                if v in 'ㅜㅠ' and not f:
                    q = [[0] * W] + q[:H - 1]
                P[('V', i, f)] = q
            else:
                a = _mask(g, x0=9, y1=y1)
                b = _mask(g, y0=_cend2(g, _bar(g)) + 1, y1=y1)
                P[('V', i, f)] = [[a[y][x] | b[y][x] for x in range(W)] for y in range(H)]
    # ★★종성도 **2벌** — 세로모음(아+받침)과 가로모음(오+받침)은 받침 자리·폭이 다르다.
    #   1벌로 두면 «공/궁/훈» 처럼 가로모음 글자에서 받침이 어긋난다.
    for f in range(1, 28):
        g0 = _gg(gm, t, 11, 0, f); g1 = _gg(gm, t, 11, 8, f)
        P[('J', f, 0)] = _mask(g0, y0=_jstart(g0))                 # 아+받침 (세로)
        P[('J', f, 1)] = _mask(g1, y0=_jstart(g1))                 # 오+받침 (가로)
    _fill(P, gm, t)
    return P


VSIB = {3: 1, 7: 5, 19: 20}          # ㅒ->ㅐ  ㅖ->ㅔ  ㅢ->ㅣ
# 섞임모음의 구성요소 — 원본 음절이 없을 때 **합쳐서** 만든다
VMIX = {9: (8, 0), 10: (8, 1), 11: (8, 20), 14: (13, 4), 15: (13, 5), 16: (13, 20), 19: (18, 20)}


def _empty(g):
    return not any(any(r) for r in g)


def _fill(P, gm, t):
    """완성형 2350자에 **원본 음절이 없는** 부품을 대체한다.

    ★★비워 두면 그 자모가 화면에서 **그냥 사라진다** — 「뾰·얩·옰·읔」처럼
      드문 조합의 원본이 없어 16개가 비어 있었다 (2026-08-25).
    """
    for i in range(19):                                   # 초성: 받침유 -> 받침무
        if _empty(P[('C', i, 2, 1)]):
            P[('C', i, 2, 1)] = P[('C', i, 2, 0)]
    for i, v in enumerate(JUNG):                          # 중성: 형제 모음의 아래끝으로 자른다
        if _empty(P[('V', i, 1)]):
            if i in VMIX and not any(_empty(P[('V', m, 1)]) for m in VMIX[i]):
                # ★★ㅢ 는 받침 있는 원본 음절이 완성형에 없다 — 받침무 부품을 잘라 쓰면
                #   **가로획이 통째로 잘려** 사라진다(2026-08-25 「흰」). ㅡ+ㅣ 로 합친다.
                a, b = (P[('V', m, 1)] for m in VMIX[i])
                P[('V', i, 1)] = [[a[y][x] | b[y][x] for x in range(W)] for y in range(H)]
            else:
                sib = _gg(gm, t, 11, VSIB.get(i, i), 1)
                P[('V', i, 1)] = _mask(P[('V', i, 0)], y1=_jstart(sib) - 1)
    for f in range(1, 28):                                # 종성: 다른 벌로
        for k in (0, 1):
            if _empty(P[('J', f, k)]) and not _empty(P[('J', f, 1 - k)]):
                P[('J', f, k)] = P[('J', f, 1 - k)]


def compose(parts, ch):
    u = ord(ch) - 0xAC00
    c, v, f = u // 588, (u % 588) // 28, u % 28
    cs = 0 if JUNG[v] in VERT else (1 if JUNG[v] in 'ㅗㅛㅜㅠㅡ' else 2)
    jf = 1 if f else 0
    out = [[0] * W for _ in range(H)]
    for k in (('C', c, cs, jf), ('V', v, jf)) + ((('J', f, 0 if cs == 0 else 1),) if f else ()):
        p = parts[k]
        for y in range(H):
            for x in range(W):
                if p[y][x]:
                    out[y][x] = 1
    return out


def render(text, path, scale=3):
    from PIL import Image
    parts = build()
    im = Image.new('L', (W * len(text), H), 0)
    q = im.load()
    for k, ch in enumerate(text):
        if not ('가' <= ch <= '힣'):
            continue
        g = compose(parts, ch)
        for y in range(H):
            for x in range(W):
                if g[y][x]:
                    q[k * W + x, y] = 255
    im.resize((im.width * scale, im.height * scale), Image.NEAREST).save(path)
    return len(parts)


def main(argv):
    from PIL import Image
    lines = ['토너먼트 퀘스트 트레이닝 옵션',
             '나는 우주에 이름난 토발 별의',
             '황제 우단이다 마물로부터',
             '마을을 구해 달라고 청해 왔다',
             '왕궁 훈련 격투 승리 체력 회복']
    out = os.path.join(ROOT, 'work', 'shot')
    os.makedirs(out, exist_ok=True)
    im = Image.new('L', (W * max(len(t) for t in lines), (H + 3) * len(lines)), 0)
    n = 0
    for i, t in enumerate(lines):
        p = os.path.join(out, '_l%d.png' % i)
        n = render(t, p, 1)
        im.paste(Image.open(p), (0, i * (H + 3)))
        os.remove(p)
    im.resize((im.width * 3, im.height * 3), Image.NEAREST).save(os.path.join(out, 'johab.png'))
    print('부품 %d개 = %d B  ->  work/shot/johab.png' % (n, n * 30))


if __name__ == '__main__':
    main(sys.argv[1:])
