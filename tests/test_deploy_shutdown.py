"""Warum uvicorn ein Zeitlimit fuer den Shutdown braucht (GitHub-Issue #37).

Gemessen am 15.09.2026: **Alle 839 HTTP-502 der beiden Vortage** (14. und 15.09.) fielen in
das Fenster eines Deploys -- kein einziger lag daneben. Das Fenster ist jedes Mal gleich
gebaut und dauert 16 bis 20 Sekunden:

    | Abschnitt                        | Dauer  |
    |----------------------------------|--------|
    | alter Container haelt sich fest  | ~10 s  |
    | neuer Container startet die App  |  ~7 s  |

Die 10 Sekunden sind exakt Dockers Gnadenfrist. uvicorn beendet auf SIGTERM naemlich **nicht**:
`/api/sse` liefert einen endlosen `StreamingResponse`, und uvicorn wartet vor dem Beenden auf
das Ende aller laufenden Antworten ("Waiting for connections to close."). Ein Stream, der nie
endet, haelt es fest, bis Docker `SIGKILL` schickt.

Isoliert gemessen, gleiches Image, eine einzige offene SSE-Verbindung:

    | Variante                          | Stopp-Dauer | Exit-Code       |
    |-----------------------------------|-------------|-----------------|
    | ohne SSE-Verbindung               |    0,7 s    | 0               |
    | mit SSE, ohne Zeitlimit           |   30,5 s    | **137 (KILL)**  |
    | mit SSE, `--timeout-...` = 1 s    |    1,8 s    | 0               |

Der Exit-Code ist der zweite, vorher unbemerkte Teil des Fundes: Ohne Zeitlimit wird die App
bei **jedem** Deploy hart abgeschossen -- mitten in dem, was sie gerade in SQLite schreibt.
"""
from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")

#: Dockers Gnadenfrist zwischen SIGTERM und SIGKILL, wenn `stop_grace_period` fehlt --
#: und das tut es in `docker-compose.yml` bewusst, weil ein hoeherer Wert die Sache
#: verschlimmern wuerde: Er verlaengert nur das Warten, statt es zu beenden.
DOCKER_GNADENFRIST_S = 10


def _cmd_block() -> str:
    """Nur die CMD-Anweisung, nicht die Kommentare darueber.

    Der Kommentarblock im Dockerfile erwaehnt die Parameter woertlich; eine freie Suche
    ueber die ganze Datei wuerde also den Kommentar finden statt der Anweisung.
    """
    start = DOCKERFILE.index("CMD [")
    return DOCKERFILE[start:DOCKERFILE.index("]", start)]


def test_uvicorn_hat_ein_zeitlimit_fuer_den_shutdown():
    """Ohne dieses Argument haelt eine einzige offene SSE-Verbindung den Stopp bis zum KILL."""
    assert "--timeout-graceful-shutdown" in _cmd_block(), (
        "CMD ohne --timeout-graceful-shutdown: jeder Deploy kostet dann die volle "
        "Gnadenfrist und endet mit SIGKILL statt mit einem sauberen Shutdown."
    )


def test_das_zeitlimit_liegt_unter_der_gnadenfrist():
    """Ein Wert >= 10 s aendert nichts -- Docker killt vorher, und genau das ist der Fehler."""
    block = _cmd_block()
    wert = block.split("--timeout-graceful-shutdown")[1].split(",")[1]
    sekunden = int(wert.strip().strip('"\' \\\n'))
    assert sekunden < DOCKER_GNADENFRIST_S, (
        f"{sekunden} s ist nicht kleiner als Dockers Gnadenfrist ({DOCKER_GNADENFRIST_S} s) -- "
        "dann greift SIGKILL zuerst und das Zeitlimit bleibt wirkungslos."
    )
