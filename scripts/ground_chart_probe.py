"""Vorabprobe zur Flugplatzkarten-Passung -- Beleg der Messwerte der Spec, Abschnitt 2.

NICHT der Produktivcode. Dies ist der Prototyp vom 30.08.2026, mit dem die Machbarkeit
belegt wurde, bevor die Spec entstand. Er liegt im Repo, damit die Zahlen in Abschnitt 2
des Designs nachvollziehbar bleiben und nicht als Behauptung dastehen.

Aufruf: die Blaetter muessen als PNG vorliegen, runways.csv unter /tmp/oa_runways.csv.

Gemessene Restfehler: EDDL 5,7 m | EDDM Flugplatzkarte 6,6 m | EDDH 29,6 m |
EDDM Rollkarte 74,0 m. Die Prueffungen wiesen vier Fehlpassungen (229/793/849/1152 m) ab.

Spec: docs/superpowers/specs/2026-08-30-ground-chart-overlay-design.md

Passung mit durchprobierter Zuordnung und Randerkennung.

Neu gegenueber Probe 2:
  * Die Zuordnung Bildbahn -> echte Bahn wird nicht geraten, sondern durchprobiert;
    Richter ist der Restfehler. Das war der Fehler bei EDDV.
  * Ein Bahnende dicht am Blattrand ist KEIN Passpunkt -- dort ist die Bahn nur
    abgeschnitten. Mehrblattrige Rollkarten (EDDV hat drei) zeigen Ausschnitte.
  * Aehnlichkeitstransformation (Drehung, Massstab, Verschiebung) statt Affin: Eine
    Karte ist nicht geschert. Vier Unbekannte, zwei Passpunkte genuegen.
"""
import csv, math, collections, itertools, sys
from PIL import Image

def bahnfarbe(im, tief=100, hoch=210, mindest=0.006):
    W,H=im.size; px=im.load(); h=collections.Counter()
    for y in range(0,H,3):
        for x in range(0,W,3):
            v=px[x,y]
            if tief<=v<=hoch: h[v]+=1
    ges=(W//3+1)*(H//3+1)
    if not h: return None
    ton,n=h.most_common(1)[0]
    return ton if n/ges>=mindest else None

def komponenten(im, ton, spiel=6, mindest=8000):
    tief,hoch=ton-spiel,ton+spiel
    W,H=im.size; px=im.load(); laeufe=[]; zv=[]
    for y in range(H):
        zv.append(len(laeufe)); x=0
        while x<W:
            if tief<=px[x,y]<=hoch:
                x0=x
                while x<W and tief<=px[x,y]<=hoch: x+=1
                if x-x0>=3: laeufe.append((y,x0,x-1))
            else: x+=1
    zv.append(len(laeufe))
    el=list(range(len(laeufe)))
    def f(i):
        while el[i]!=i: el[i]=el[el[i]]; i=el[i]
        return i
    for y in range(1,H):
        i,j=zv[y],zv[y-1]; ei,ej=zv[y+1],zv[y]
        while i<ei and j<ej:
            _,a0,a1=laeufe[i]; _,b0,b1=laeufe[j]
            if a1>=b0 and b1>=a0:
                ra,rb=f(i),f(j)
                if ra!=rb: el[rb]=ra
            if a1<b1: i+=1
            else: j+=1
    g={}
    for i,l in enumerate(laeufe): g.setdefault(f(i),[]).append(l)
    return [v for v in g.values() if sum(b-a+1 for _,a,b in v)>=mindest]

def hauptachse(lauf):
    n=sx=sy=0
    for y,x0,x1 in lauf:
        k=x1-x0+1; n+=k; sy+=y*k; sx+=(x0+x1)*k/2.0
    cx,cy=sx/n,sy/n; mxx=myy=mxy=0.0
    for y,x0,x1 in lauf:
        dy=y-cy
        for x in range(x0,x1+1):
            dx=x-cx; mxx+=dx*dx; myy+=dy*dy; mxy+=dx*dy
    mxx/=n; myy/=n; mxy/=n
    th=0.5*math.atan2(2*mxy,mxx-myy)
    ca,sa=math.cos(th),math.sin(th); lo=hi=qlo=qhi=None
    for y,x0,x1 in lauf:
        for x in (x0,x1):
            u=(x-cx)*ca+(y-cy)*sa; v=-(x-cx)*sa+(y-cy)*ca
            lo=u if lo is None else min(lo,u); hi=u if hi is None else max(hi,u)
            qlo=v if qlo is None else min(qlo,v); qhi=v if qhi is None else max(qhi,v)
    return dict(cx=cx,cy=cy,th=th,laenge=hi-lo,breite=qhi-qlo,n=n,u0=lo,u1=hi)

def enden_tasten(im, ton, a, spiel=6, luecke=60):
    W,H=im.size; px=im.load()
    ca,sa=math.cos(a["th"]),math.sin(a["th"])
    halb=max(3.0,a["breite"]/2.0-2)
    def bahn_bei(u):
        t=g=0; v=-halb
        while v<=halb:
            x=int(round(a["cx"]+u*ca-v*sa)); y=int(round(a["cy"]+u*sa+v*ca))
            if 0<=x<W and 0<=y<H:
                g+=1
                if ton-spiel<=px[x,y]<=ton+spiel: t+=1
            v+=1.0
        return g>0 and t/g>=0.55
    aus=[]
    for r in (-1,1):
        u=a["u0"] if r<0 else a["u1"]; leer=0
        while leer<luecke:
            u+=r
            if bahn_bei(u): leer=0
            else: leer+=1
            if abs(u)>4*max(W,H): break
        aus.append(u-r*leer)
    return aus[0],aus[1]

def am_rand(p, W, H, saum=45):
    x,y=p
    return x<saum or y<saum or x>W-saum or y>H-saum

def referenzbahnen(icao):
    aus=[]
    for r in csv.DictReader(open("/tmp/oa_runways.csv")):
        if r["airport_ident"]!=icao or r["closed"]!="0": continue
        if not all(r[k] for k in ("le_latitude_deg","le_longitude_deg",
                                  "he_latitude_deg","he_longitude_deg")): continue
        aus.append(dict(name=f"{r['le_ident']}/{r['he_ident']}",
                        le=(float(r["le_latitude_deg"]),float(r["le_longitude_deg"])),
                        he=(float(r["he_latitude_deg"]),float(r["he_longitude_deg"]))))
    return aus

def meter(p,q,lat0):
    return ((q[1]-p[1])*111320.0*math.cos(math.radians(lat0)), (q[0]-p[0])*110540.0)

def aehnlich(paare):
    """Drehung+Massstab+Verschiebung, kleinste Quadrate. (a,b,e,n): X=a*x-b*y+e, Y=b*x+a*y+n"""
    n=len(paare)
    if n<2: return None
    sx=sy=sX=sY=sxX=syY=sxY=syX=sxx=syy=0.0
    for (x,y),(X,Y) in paare:
        sx+=x; sy+=y; sX+=X; sY+=Y
        sxX+=x*X; syY+=y*Y; sxY+=x*Y; syX+=y*X; sxx+=x*x; syy+=y*y
    d=n*(sxx+syy)-sx*sx-sy*sy
    if abs(d)<1e-9: return None
    a=(n*(sxX+syY)-sx*sX-sy*sY)/d
    b=(n*(sxY-syX)-sx*sY+sy*sX)/d
    e=(sX-a*sx+b*sy)/n
    f=(sY-b*sx-a*sy)/n
    return a,b,e,f

def rest(paare,t):
    a,b,e,f=t; aus=[]
    for (x,y),(X,Y) in paare:
        aus.append(math.hypot(a*x-b*y+e-X, b*x+a*y+f-Y))
    return aus

def probe(pfad, icao, sorte, laut=True):
    im=Image.open(pfad).convert("L"); W,H=im.size
    ton=bahnfarbe(im)
    if ton is None: return dict(icao=icao,sorte=sorte,status="keine Bahnfarbe")
    achsen=[]
    for g in komponenten(im,ton):
        a=hauptachse(g)
        if a["breite"]<4 or a["laenge"]/a["breite"]<8: continue
        ua,ub=enden_tasten(im,ton,a); a["ua"],a["ub"]=ua,ub
        ca,sa=math.cos(a["th"]),math.sin(a["th"])
        a["pa"]=(a["cx"]+ua*ca, a["cy"]+ua*sa)
        a["pb"]=(a["cx"]+ub*ca, a["cy"]+ub*sa)
        a["ra"]=am_rand(a["pa"],W,H); a["rb"]=am_rand(a["pb"],W,H)
        a["voll"]=ub-ua
        achsen.append(a)
    achsen.sort(key=lambda a:-a["voll"])
    achsen=achsen[:4]
    ref=referenzbahnen(icao)
    if not achsen or len(ref)<1:
        return dict(icao=icao,sorte=sorte,status=f"{len(achsen)} Bahnen im Bild, {len(ref)} Referenz")
    lat0=ref[0]["le"][0]
    best=None
    for zuord in itertools.permutations(range(len(ref)), min(len(achsen),len(ref))):
        for drehungen in itertools.product((False,True), repeat=len(zuord)):
            paare=[]
            for k,(ri,dreh) in enumerate(zip(zuord,drehungen)):
                a=achsen[k]; r=ref[ri]
                m_le=meter(ref[0]["le"],r["le"],lat0); m_he=meter(ref[0]["le"],r["he"],lat0)
                z_a,z_b=(m_he,m_le) if dreh else (m_le,m_he)
                if not a["ra"]: paare.append((a["pa"],z_a))
                if not a["rb"]: paare.append((a["pb"],z_b))
            if len(paare)<4: continue
            skalen=[]
            for k,ri in enumerate(zuord):
                a=achsen[k]; r=ref[ri]
                if a["ra"] or a["rb"]: continue      # abgeschnitten: Laenge sagt nichts
                m_le=meter(ref[0]["le"],r["le"],lat0); m_he=meter(ref[0]["le"],r["he"],lat0)
                L=math.hypot(m_he[0]-m_le[0], m_he[1]-m_le[1])
                if a["voll"]>1: skalen.append(L/a["voll"])
            if len(skalen)>=2 and max(skalen)/min(skalen) > 1.08: continue
            paare=[((x,-y),z) for (x,y),z in paare]   # Bild-y zeigt nach unten
            t=aehnlich(paare)
            if t is None: continue
            nordung=(-math.degrees(math.atan2(t[1],t[0])))%360
            if 90.0 < nordung < 270.0: continue      # kopfueber -- gibt es nicht
            r_=rest(paare,t); m=max(r_)
            if best is None or m<best[0]:
                best=(m,sum(r_)/len(r_),t,zuord,drehungen,len(paare))
    if best is None:
        return dict(icao=icao,sorte=sorte,status="keine verwertbare Zuordnung",
                    bahnen=len(achsen))
    m,mit,t,zuord,dreh,npaare=best
    mps=math.hypot(t[0],t[1])
    winkel=math.degrees(math.atan2(t[1],t[0]))
    if laut:
        print(f"  {icao} {sorte:15s} {str((W,H)):13s} Ton={ton:3d} Bahnen={len(achsen)} "
              f"Punkte={npaare}  Rest max {m:7.1f} m  Massstab {mps:5.3f} m/px  "
              f"Nordung {(-winkel)%360:6.2f}deg")
    return dict(icao=icao,sorte=sorte,status="ok",rest_max=m,rest_mittel=mit,
                mps=mps,bahnen=len(achsen),punkte=npaare)

if __name__=="__main__":
    import glob, os, re
    dateien=[("/tmp/eddl/seite6.png","EDDL")]
    for p in sorted(glob.glob("/tmp/eddl/EDD*_s*.png")):
        dateien.append((p, os.path.basename(p)[:4]))
    gut=schlecht=0
    for p,icao in dateien:
        try:
            e=probe(p,icao,os.path.basename(p).replace(".png",""))
            if e.get("status")!="ok":
                print(f"  {icao} {os.path.basename(p):16s} -> {e['status']}")
                schlecht+=1
            elif e["rest_max"]<15: gut+=1
            else: schlecht+=1
        except Exception as ex:
            print(f"  {icao} {p}: FEHLER {ex}"); schlecht+=1
    print(f"\nBlaetter mit Restfehler < 15 m: {gut}, uebrige: {schlecht}")
