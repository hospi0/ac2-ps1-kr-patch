# -*- coding: utf-8 -*-
r"""PoC 빌드 — 훅 방식 한글 글리프가 실제로 화면에 나오는지 본다.

  python tools/build_poc.py            # 드라이런: 패치 계산·시뮬 대조·허용범위 검사만 (쓰기 없음)
  python tools/build_poc.py --write    # work/out/ 에 새 bin/cue + dist/ xdelta (원본은 안 건드린다)

바꾸는 것 (전부 원본 바이트를 확인한 뒤):
  ① 본체 EXE(ACE2.DAT+0x800) — 훅 jal 2곳 · 초기화 jal 1곳 · 죽은 조각에 트램펄린/스텁 · PoC 문자열
  ② 디스크 끝 빈 섹터 LBA 246,564~ — 낮은 영역 이미지(루틴+블롭)
PoC 문자열 = 난이도 화면 하단 도움말 3줄(세이브스테이트 2 에서 보인 「難易度：ふつう」).
"""
import hashlib, os, shutil, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)
import krhook as K
from cdsector import fix_sector, edc

ORIG = r'C:\claude\roms\ps\Ace Combat 2 (Japan) (Rev 1)\Ace Combat 2 (Japan) (Rev 1).bin'
ORIG_MD5 = 'ECE1E7B3F995B67483B94F98401BB925'
OUTDIR = os.path.join(ROOT, 'work', 'out')
OUT = os.path.join(OUTDIR, 'AC2_KR_PoC.bin')
XD = r'C:\claude\utils\xdelta.exe'
FDST = r'F:\hospi\roms\ps roms\Ace Combat 2 (Japan) (Rev 1)\Ace Combat 2 (Japan) (Rev 1).bin'   # 사용자 실행본
XOUT = os.path.join(ROOT, 'dist', 'AC2_KR_PoC.xdelta')
RAW, UOFF = 2352, 24
DAT_LBA = 73                     # ISO 디렉터리 실측 (tools/discfs.py)
BASE, TEXT = 0x80018000, 0x1000  # 본체: DAT 파일 오프셋 = a - BASE + TEXT

POC = [
    (0x80019200, '難易度：難しい', '난이도：어려움'),
    (0x80019210, '難易度：ふつう', '난이도：보통'),
    (0x80019220, '難易度：やさしい', '난이도：쉬움'),
]


def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest().upper()


def sjis_codes():
    """한글에 줄 코드: 0x889F 부터 유효 SJIS 순서 (선두 0x88~0x9F · 뒤 0x40~0xFC, 0x7F 제외)."""
    for lead in range(0x88, 0xA0):
        for tr in range(0x40, 0xFD):
            if tr == 0x7F or (lead == 0x88 and tr < 0x9F):
                continue
            yield lead << 8 | tr


def assign(texts):
    syl = []
    for t in texts:
        for ch in t:
            if '가' <= ch <= '힣' and ch not in syl:
                syl.append(ch)
    g = sjis_codes()
    return {ch: next(g) for ch in syl}


def encode(s, cmap):
    out = bytearray()
    for ch in s:
        if ch in cmap:
            c = cmap[ch]; out += bytes([c >> 8, c & 0xFF])
        else:
            try:
                b = ch.encode('cp932')
            except UnicodeEncodeError:
                raise SystemExit('⛔ 인코딩 불가 글자 %r' % ch)
            out += b
    return bytes(out)


class Disc:
    """원본(읽기 전용) 위에 «바뀐 섹터»만 기억한다."""
    def __init__(self, path):
        self.f = open(path, 'rb'); self.mod = {}

    def sector(self, lba):
        if lba in self.mod:
            return self.mod[lba]
        self.f.seek(lba * RAW)
        return bytearray(self.f.read(RAW))

    def put(self, lba, sec):
        self.mod[lba] = sec


def exe_read(disc, a, n):
    f = a - BASE + TEXT
    out = bytearray()
    while n:
        lba, o = DAT_LBA + f // 2048, f % 2048
        k = min(n, 2048 - o)
        out += disc.sector(lba)[UOFF + o:UOFF + o + k]
        f += k; n -= k
    return bytes(out)


def exe_write(disc, a, data):
    f = a - BASE + TEXT
    i = 0
    while i < len(data):
        lba, o = DAT_LBA + f // 2048, f % 2048
        k = min(len(data) - i, 2048 - o)
        sec = disc.sector(lba)
        assert sec[15] == 2 and not (sec[18] & 0x20), 'DAT 섹터 %d 가 Mode2 Form1 이 아니다' % lba
        sec[UOFF + o:UOFF + o + k] = data[i:i + k]
        disc.put(lba, sec)
        f += k; i += k


def plan(disc):
    cmap = assign([kr for _, _, kr in POC])
    rows = sorted((c, ch) for ch, c in cmap.items())
    img, ecode, elab, nsec, P, r_addr, buf = K.build(rows)
    bad = K.verify(rows, img, ecode, elab, P, r_addr)
    print('한글 %d음절 · 코드 %04X~%04X · 낮은 영역 이미지 %d B (%d섹터) · EXE 조각 %d B' % (
        len(rows), rows[0][0], rows[-1][0], len(img), nsec, len(ecode)))
    print('시뮬 대조: 한글 %d/%d · 비한글→썽크 · 트램펄린 매직 유/무  %s' % (
        len(rows), len(rows), 'OK' if not bad else '⛔%d건' % bad))
    if bad:
        raise SystemExit('⛔ 시뮬 대조 실패 — 쓰지 않는다')

    patches = []                                   # (주소, 원본, 새것)
    for a, jp, kr in POC:
        old = exe_read(disc, a, len(jp.encode('cp932')) + 1)
        assert old == jp.encode('cp932') + b'\0', '⛔ %08X 원본이 %r 가 아니다: %r' % (a, jp, old)
        new = encode(kr, cmap)
        if len(new) > len(old) - 1:
            raise SystemExit('⛔ %r 가 원본 자리(%d B)보다 길다' % (kr, len(old) - 1))
        patches.append((a, old, new + bytes(len(old) - len(new))))
    for h in K.HOOKS:
        old = exe_read(disc, h, 4)
        assert struct.unpack('<I', old)[0] == K.jal(K.THUNK), '⛔ 훅 자리 %08X 가 jal 썽크가 아니다' % h
        patches.append((h, old, struct.pack('<I', K.jal(elab['TRAMP']))))
    old = exe_read(disc, K.INIT_SITE, 4)
    assert struct.unpack('<I', old)[0] == K.jal(K.INIT_TARGET), '⛔ 초기화 자리가 다르다'
    patches.append((K.INIT_SITE, old, struct.pack('<I', K.jal(elab['STUB']))))
    import deadcode
    # 쓰는 범위가 «죽은 블록들»로 빈틈없이 덮여야 한다 (블록 사이의 작은 살아 있는 조각을 덮으면 안 된다)
    cov, p = sorted(deadcode.dead), K.DEAD
    for s, e in cov:
        if s <= p < e:
            p = e
    assert p >= K.DEAD_END, \
        '⛔ 죽은 조각 0x%08X~ 가 죽은 블록으로 다 덮이지 않는다 (0x%08X 에서 끊김)' % (K.DEAD, p)
    old = exe_read(disc, K.DEAD, len(ecode))
    assert old[:4] == bytes.fromhex('68ffbd27'), '⛔ 죽은 조각 머리가 다르다'
    patches.append((K.DEAD, old, ecode))
    return patches, img, nsec, cmap


def apply(disc, patches, img, nsec):
    for a, old, new in patches:
        exe_write(disc, a, new)
    for i in range(nsec):
        lba = K.BLOB_LBA + i
        sec = disc.sector(lba)
        assert sec[15] == 2 and not any(sec[UOFF:UOFF + 2048]), '⛔ LBA %d 가 빈 섹터가 아니다' % lba
        sec[16:24] = bytes([0, 0, 0x08, 0, 0, 0, 0x08, 0])      # Form1 데이터
        chunk = img[i * 2048:(i + 1) * 2048]
        sec[UOFF:UOFF + 2048] = chunk + bytes(2048 - len(chunk))
        disc.put(lba, sec)
    for lba, sec in disc.mod.items():
        fix_sector(sec)


def census(orig, new, patches):
    """본체 EXE 전체를 원본과 비교 — 바뀐 바이트가 계획한 범위 밖이면 실패."""
    allowed = set()
    for a, old, nb in patches:
        for i in range(len(nb)):
            if old[i] != nb[i]:
                allowed.add(a + i)
    n = 0xA1800
    o = exe_read(orig, BASE, n); b = exe_read(new, BASE, n)
    diff = {BASE + i for i in range(n) if o[i] != b[i]}
    extra = diff - allowed; miss = allowed - diff
    print('본체 EXE 변경 %d B · 계획 밖 %d · 누락 %d' % (len(diff), len(extra), len(miss)))
    if extra or miss:
        raise SystemExit('⛔ 변경 census 불일치 %s %s' % (sorted(extra)[:5], sorted(miss)[:5]))


def main():
    write = '--write' in sys.argv
    disc = Disc(ORIG)
    patches, img, nsec, cmap = plan(disc)
    apply(disc, patches, img, nsec)
    census(Disc(ORIG), disc, patches)
    print('바뀐 섹터 %d개 (DAT %d · 블롭 %d)' % (len(disc.mod), len(disc.mod) - nsec, nsec))
    for a, jp, kr in POC:
        print('  %08X  %s → %s' % (a, jp, kr))
    if not write:
        print('드라이런 — 쓰지 않았다. 쓰려면 --write')
        return
    if md5(ORIG) != ORIG_MD5:
        raise SystemExit('⛔ 원본 md5 가 다르다')
    os.makedirs(OUTDIR, exist_ok=True); os.makedirs(os.path.dirname(XOUT), exist_ok=True)
    shutil.copyfile(ORIG, OUT)
    with open(OUT, 'r+b') as g:
        for lba, sec in sorted(disc.mod.items()):
            g.seek(lba * RAW); g.write(sec)
    with open(OUT[:-4] + '.cue', 'w', encoding='ascii') as c:
        c.write('FILE "%s" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n' % os.path.basename(OUT))
    # 되읽기 검증
    chk = Disc(OUT)
    census(Disc(ORIG), chk, patches)
    for lba in disc.mod:
        s = chk.sector(lba)
        assert struct.unpack_from('<I', s, 2072)[0] == edc(bytes(s[16:2072])), '⛔ EDC %d' % lba
    got = b''.join(bytes(chk.sector(K.BLOB_LBA + i)[UOFF:UOFF + 2048]) for i in range(nsec))[:len(img)]
    assert got == img, '⛔ 블롭 되읽기 불일치'
    assert os.path.getsize(OUT) == os.path.getsize(ORIG)
    m = md5(OUT)
    print('✅ %s  %d B  md5 %s' % (OUT, os.path.getsize(OUT), m))
    rt = os.path.join(os.environ.get('TEMP', '.'), 'ac2_rt.bin')
    subprocess.run([XD, '-e', '-9', '-S', 'lzma', '-A', '-B', '268435456', '-f', '-s', ORIG, OUT, XOUT], check=True)
    subprocess.run([XD, '-d', '-f', '-s', ORIG, XOUT, rt], check=True)
    r = md5(rt); os.remove(rt)
    print('xdelta %s %d B md5 %s · 왕복 %s' % (XOUT, os.path.getsize(XOUT), md5(XOUT), 'OK' if r == m else '⛔불일치'))
    # 사용자는 F: 설치본으로 돌린다 (2026-09-14 지시) — 빌드마다 같이 교체
    shutil.copyfile(OUT, FDST)
    print('F: 설치본 md5 %s %s' % (md5(FDST), 'OK' if md5(FDST) == m else '⛔불일치'))
    with open(os.path.join(OUTDIR, 'charmap_poc.tsv'), 'w', encoding='utf-8') as t:
        t.write('코드\t음절\n')
        for ch, c in sorted(cmap.items(), key=lambda x: x[1]):
            t.write('%04X\t%s\n' % (c, ch))


if __name__ == '__main__':
    main()
