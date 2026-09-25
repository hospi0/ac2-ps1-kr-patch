# -*- coding: utf-8 -*-
"""세이브스테이트 여러 개를 한꺼번에: 화면 · 글자 캐시 점유 · 캐시 VRAM 그림 · 빈 RAM 페이지.

  python tools/ac2state.py D:/.../SLPS-00830_1.sav D:/.../SLPS-00830_2.sav ...

출력: work/state/<n>/{screen.png, screen_half.png, ram.bin, vram.bin, gcache.png}

## 글자 캐시 (역어셈블 0x80099FDC)
```
0x800BE668  u32 × 256   칸마다 SJIS 코드(하위 16비트, 0 = 빈 칸)
VRAM        x = 0x2C0 + (칸&15)*4  (하프워드) · y = 0x100 + (칸&0xF0)   · 칸 = 16×16 4bpp
```
"""
import os, re, struct, sys
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from state import load, split
from PIL import Image

OUT = os.path.join(HERE, '..', 'work', 'state')
GC = 0x800BE668
LO, HI, PAGE = 0x800C2000, 0x80200000, 0x1000


def r32(ram, a):
    return struct.unpack_from('<I', ram, a - 0x80000000)[0]


def vram_4bpp(vram, x0, y0, wh, h):
    """하프워드 x0.. 폭 wh, 높이 h 를 4bpp 회색으로."""
    im = Image.new('L', (wh * 4, h))
    px = im.load()
    for y in range(h):
        for x in range(wh):
            v = struct.unpack_from('<H', vram, ((y0 + y) * 1024 + x0 + x) * 2)[0]
            for k in range(4):
                px[x * 4 + k, y] = ((v >> (4 * k)) & 15) * 17
    return im


def main():
    global OUT
    args = sys.argv[1:]
    if '--out' in args:                      # 옛 추출물을 덮지 않도록 (예: work/state2)
        k = args.index('--out'); OUT = args[k + 1]; del args[k:k + 2]
    zero_all = None
    for path in args:
        n = re.search(r'_(\d+)\.sav$', path).group(1)
        od = os.path.join(OUT, n)
        os.makedirs(od, exist_ok=True)
        shot, (w, h), body = load(path)
        im = Image.frombytes('RGBA', (w, h), shot).convert('RGB')
        im.save(os.path.join(od, 'screen.png'))
        im.resize((w // 2, h // 2)).save(os.path.join(od, 'screen_half.png'))
        ram, vram, ram0 = split(body)
        open(os.path.join(od, 'ram.bin'), 'wb').write(ram)
        if vram:
            open(os.path.join(od, 'vram.bin'), 'wb').write(vram)
            vram_4bpp(vram, 0x2C0, 0x100, 64, 256).save(os.path.join(od, 'gcache.png'))
        codes = [r32(ram, GC + 4 * i) & 0xFFFF for i in range(256)]
        used = [c for c in codes if c]
        txt = ''.join(bytes([c >> 8, c & 0xFF]).decode('cp932', 'replace') for c in used)
        print('== 상태 %s  스샷 %dx%d  RAM@0x%X' % (n, w, h, ram0))
        print('   글자 캐시 %d/256칸  %s' % (len(used), txt))
        # 빈 페이지
        zp = set()
        for a in range(LO, HI, PAGE):
            o = a - 0x80000000
            if not any(ram[o:o + PAGE]):
                zp.add(a)
        print('   0x%X 이상 0 인 4KB 페이지 %d개' % (LO, len(zp)))
        zero_all = zp if zero_all is None else zero_all & zp
    # 연속 구간으로
    runs = []
    for a in sorted(zero_all or []):
        if runs and runs[-1][1] == a:
            runs[-1][1] = a + PAGE
        else:
            runs.append([a, a + PAGE])
    print('== 모든 상태에서 0 인 구간 (16KB 이상)')
    for s, e in runs:
        if e - s >= 0x4000:
            print('   %08X..%08X  %d KB' % (s, e, (e - s) >> 10))


if __name__ == '__main__':
    main()
