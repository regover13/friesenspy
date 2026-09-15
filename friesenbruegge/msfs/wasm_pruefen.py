"""Prueft die drei Build-Fallen an der fertigen .wasm -- ohne Simulator.

Alle drei sehen von aussen GLEICH aus: ein Modul, das nichts tut. Sichtbar wurden sie
bisher nur in der DevMode-Konsole, also erst nach einem Neustart des Simulators. Sie stehen
aber alle drei in der Import- und Exporttabelle der Datei und sind damit in Sekunden
messbar:

    Falle 1  /GS- fehlt          ->  Import `__stack_chk_fail`
                                     (ERR_UNKNOWN_BLANK_IMPORT, Modul wird VOR dem Start verworfen)
    Falle 2  --export-table fehlt ->  kein Export vom Typ `table`
                                     (WASM: Error getting indirect function table, erst beim Callback)
    Falle 3  --allow-undefined    ->  die SimConnect-Funktionen fehlen unter den `env::`-Importen

Der vierte Fall ist kein Flag, sondern eine Nebenwirkung: Zieht neuer Code einen wasi-Import
herein, den die MSFS-Laufzeit nicht kennt (`poll_oneoff` etwa, ueber ein `sleep`), stirbt das
Modul wie bei Falle 1. Deshalb listet das Skript ALLE Importe -- die Liste mit der vom
letzten gruenen Bau zu vergleichen, ist die eigentliche Pruefung.

Aufruf:  python wasm_pruefen.py bruegge.wasm
"""
import sys, io

def leb(f):
    r = s = 0
    while True:
        b = f.read(1)[0]
        r |= (b & 0x7f) << s
        if not (b & 0x80): return r
        s += 7

def name(f):
    return f.read(leb(f)).decode('utf-8', 'replace')

KIND = {0: 'func', 1: 'table', 2: 'mem', 3: 'global'}

def lies(pfad):
    d = open(pfad, 'rb').read()
    f = io.BytesIO(d)
    assert f.read(4) == b'\0asm', 'kein WASM'
    f.read(4)
    imports, exports, sektionen = [], [], []
    while True:
        b = f.read(1)
        if not b: break
        sid = b[0]
        groesse = leb(f)
        ende = f.tell() + groesse
        sektionen.append((sid, groesse))
        if sid == 2:
            for _ in range(leb(f)):
                m, n = name(f), name(f)
                k = f.read(1)[0]
                imports.append((m, n, KIND.get(k, k)))
                if k == 0: leb(f)
                elif k == 1:
                    f.read(1); lim = leb(f); leb(f)
                    if lim: leb(f)
                elif k == 2:
                    lim = leb(f); leb(f)
                    if lim: leb(f)
                elif k == 3: f.read(2)
        elif sid == 7:
            for _ in range(leb(f)):
                n = name(f); k = f.read(1)[0]; leb(f)
                exports.append((n, KIND.get(k, k)))
        f.seek(ende)
    return imports, exports, sektionen

for pfad in sys.argv[1:]:
    print('=' * 70)
    print(pfad)
    try:
        imp, exp, sek = lies(pfad)
    except Exception as e:
        print('  FEHLER:', e); continue
    print(f'  Sektionen: {[s[0] for s in sek]}')
    print(f'  --- {len(imp)} Importe ---')
    verdaechtig = []
    for m, n, k in imp:
        mark = ''
        if 'stack_chk' in n or 'stack_chk' in m:
            mark = '   <<< FALLE 1: /GS- fehlt'
            verdaechtig.append(n)
        print(f'    [{k:6}] {m}::{n}{mark}')
    print(f'  --- {len(exp)} Exporte ---')
    for n, k in exp:
        print(f'    [{k:6}] {n}')
    tab = [n for n, k in exp if k == 'table']
    print('  FALLE 2 (--export-table): ' + ('OK, Tabelle exportiert: ' + ', '.join(tab) if tab else '<<< KEINE Tabelle exportiert'))
    print('  FALLE 1 (/GS-): ' + ('<<< ' + ', '.join(verdaechtig) if verdaechtig else 'OK, kein __stack_chk_*'))
