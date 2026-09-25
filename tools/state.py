# -*- coding: utf-8 -*-
"""DuckStation 세이브스테이트(.sav) → 스크린샷 · 메인 RAM 2MB · VRAM 1MB.

  python tools/state.py <SLPS-00830_1.sav> --out work/state/1

## 형식 (magic 'DUCC' · 테마 아쿠아리움 도구에서 가져옴)
```
0xA8 u32 미디어경로 길이 · 0xAC 오프셋 · 0xB0 subimage · 0xB4 스샷 압축(0=없음 2=zstd)
0xB8 스샷 폭 · 0xBC 높이 · 0xC0 크기 · 0xC4 오프셋                (RGBA8888)
0xC8 본체 압축(2=zstd) · 0xCC 압축 크기 · 0xD0 원본 크기 · 0xD4 오프셋
```
RAM 시작은 «본체 EXE 코드 조각»을 찾아 맞춘다(섹션 머리 길이를 믿지 않는다).
"""
import argparse, os, struct

HERE = os.path.dirname(os.path.abspath(__file__))
MAINEXE = os.path.join(HERE, '..', 'work', 'ACE2MAIN.EXE')
PROBE = 0x80065300              # 한자 ROM 변환 함수 안쪽 — ⛔0x80065220 은 훅 자리(0x80065230)를 품어 패치판에서 못 찾는다
BASE, HDR = 0x80018000, 0x800


def load(path):
    d = open(path, 'rb').read()
    assert d[:4] == b'DUCC', '세이브스테이트가 아니다'
    scomp, sw, sh, ssize, soff = struct.unpack_from('<5I', d, 0xB4)
    comp, csize, usize, doff = struct.unpack_from('<4I', d, 0xC8)
    import zstandard as zstd
    dc = zstd.ZstdDecompressor()
    shot = d[soff:soff + ssize]
    if scomp:
        shot = dc.decompress(shot, max_output_size=1 << 24)
    body = d[doff:doff + csize]
    if comp:
        body = dc.decompress(body, max_output_size=max(usize, 1 << 26))
    return shot, (sw, sh), body


def split(body):
    exe = open(MAINEXE, 'rb').read()
    o = PROBE - BASE + HDR
    probe = exe[o:o + 64]
    p = body.find(probe)
    assert p >= 0, 'RAM 을 못 찾음(본체 EXE 조각 없음)'
    ram0 = p - (PROBE - 0x80000000)
    ram = body[ram0:ram0 + 0x200000]
    tag = struct.pack('<I', 8) + b'GPU-VRAM'
    v = body.find(tag)
    vram = None
    if v >= 0:
        v += len(tag)
        # 섹션 머리 뒤에 길이 필드가 있을 수 있다 — 1MB 가 딱 남는 첫 자리로 맞춘다
        for k in (0, 4, 8):
            if v + k + 0x100000 <= len(body):
                vram = body[v + k:v + k + 0x100000]
                break
    return ram, vram, ram0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sav'); ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    shot, (w, h), body = load(a.sav)
    from PIL import Image
    Image.frombytes('RGBA', (w, h), shot).convert('RGB').save(os.path.join(a.out, 'screen.png'))
    ram, vram, ram0 = split(body)
    open(os.path.join(a.out, 'ram.bin'), 'wb').write(ram)
    if vram:
        open(os.path.join(a.out, 'vram.bin'), 'wb').write(vram)
    print('%s  스샷 %dx%d · 본체 %d B · RAM@0x%X · VRAM %s' % (a.sav, w, h, len(body), ram0, 'OK' if vram else '없음'))


if __name__ == '__main__':
    main()
