"""Blatt mit beschriftetem Pixelraster ansehen -- damit lassen sich Positionen im
ORIGINALbild ablesen, auch wenn die Ansicht verkleinert ist."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

icao, sorte = sys.argv[1], sys.argv[2]
schritt = int(sys.argv[3]) if len(sys.argv) > 3 else 200
quelle = Path(f"/opt/friesenspy/data/aip_dfs/{icao}.{sorte}.roh.png")
im = Image.open(quelle).convert("RGB")
b, h = im.size
z = ImageDraw.Draw(im)
for x in range(0, b, schritt):
    z.line([(x, 0), (x, h)], fill=(255, 0, 0), width=2)
    z.text((x + 4, 4), str(x), fill=(255, 0, 0))
    z.text((x + 4, h - 16), str(x), fill=(255, 0, 0))
for y in range(0, h, schritt):
    z.line([(0, y), (b, y)], fill=(0, 120, 255), width=2)
    z.text((4, y + 3), str(y), fill=(0, 120, 255))
ziel = f"/tmp/{icao}.{sorte}.raster.png"
im.save(ziel)
print(f"{quelle.name}: {b} x {h} px  ->  {ziel}  (Raster {schritt} px)")
