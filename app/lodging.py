"""หาที่พักรอบที่ทำงานจากข้อมูล OpenStreetMap (ฟรี ไม่ต้องใช้ key)

1. หาพิกัดที่ทำงานด้วย Nominatim — ชื่อบริษัทมักไม่มีใน OSM จึงถอยไปใช้จังหวัด/อำเภอแทน
2. ดึงโรงแรม/เกสต์เฮาส์/อพาร์ตเมนต์รอบพิกัดนั้นด้วย Overpass แล้วเรียงตามระยะทาง
ข้อมูลเป็นของจริงจาก OSM ไม่มีการแต่งชื่อที่พักขึ้นเอง แต่ในไทยข้อมูลยังไม่ครบเท่า Google Maps
"""
import asyncio
import math
import re
import time

import httpx

from .config import BASE_DIR, GOOGLE_MAPS_KEY

UA = {"User-Agent": "DNA-Office-AI/1.0 (internal lodging search)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
# คำค้นสำรองใน Nominatim เมื่อ Overpass ไม่ตอบ (เซิร์ฟเวอร์ฟรีมักเต็ม)
NOMINATIM_WORDS = ["hotel", "guest house", "resort", "motel", "hostel", "apartment"]
TYPES = {"hotel": "โรงแรม", "motel": "โมเทล", "guest_house": "เกสต์เฮาส์", "hostel": "โฮสเทล", "apartment": "อพาร์ตเมนต์/ห้องพัก"}
_cache: dict[tuple, tuple[float, object]] = {}  # กันเรียกบริการฟรีซ้ำถี่ๆ (ตามเงื่อนไขการใช้งานของ OSM)
CACHE_SECONDS = 1800


def google_key() -> str:
    """key ของ Google Maps Embed API — จาก env หรือไฟล์ google_maps_key.txt (ไม่ขึ้น git)"""
    if GOOGLE_MAPS_KEY:
        return GOOGLE_MAPS_KEY
    f = BASE_DIR / "google_maps_key.txt"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


async def _cached(key: tuple, fetch):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = await fetch()
    _cache[key] = (time.time(), value)
    return value


_last_call = 0.0


async def _polite_wait():
    """Nominatim ให้เรียกได้ไม่เกิน 1 ครั้งต่อวินาที — เรียกถี่กว่านั้นจะได้ผลว่างกลับมา"""
    global _last_call
    wait = 1.1 - (time.time() - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.time()


def clean_company(name: str) -> str:
    """ตัดคำนำหน้า/ต่อท้ายชื่อบริษัทที่ทำให้ค้นในแผนที่ไม่เจอ เช่น บริษัท ... จำกัด (มหาชน) (TFM)"""
    name = re.sub(r"\(.*?\)", " ", name)
    name = re.sub(r"บริษัท|บจก\.?|บมจ\.?|หจก\.?|จำกัด|มหาชน|co\.?,?\s*ltd\.?|public company limited|company limited", " ", name, flags=re.I)
    return " ".join(name.split())


async def geocode(query: str) -> dict | None:
    async def fetch():
        await _polite_wait()
        async with httpx.AsyncClient(timeout=20, headers=UA) as c:
            r = await c.get(NOMINATIM, params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "th", "accept-language": "th"})
            r.raise_for_status()
        rows = r.json()
        return {"lat": float(rows[0]["lat"]), "lon": float(rows[0]["lon"]), "label": rows[0].get("display_name", query)} if rows else None
    return await _cached(("geo", query), fetch)


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lon2 - lon1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


async def _overpass(lat: float, lon: float, radius_m: int) -> list[dict] | None:
    query = (f'[out:json][timeout:8];(nwr["tourism"~"^({"|".join(TYPES)})$"](around:{radius_m},{lat},{lon}););'
             "out center tags 200;")
    for url in OVERPASS:  # เซิร์ฟเวอร์ฟรีบางทีปฏิเสธเมื่อคนใช้เยอะ ลองอีกตัว
        try:
            async with httpx.AsyncClient(timeout=8, headers=UA) as c:
                r = await c.post(url, data={"data": query})
                r.raise_for_status()
            return [{"tags": e.get("tags", {}), **e.get("center", e)} for e in r.json()["elements"]]
        except (httpx.HTTPError, ValueError):
            continue
    return None


async def _nominatim_hotels(lat: float, lon: float, radius_m: int) -> list[dict]:
    """ตัวสำรอง: ค้นคำว่า hotel, guest house ฯลฯ ในกรอบรอบพิกัด (เว้น 1 วินาทีต่อครั้งตามเงื่อนไขของ Nominatim)"""
    dlat = radius_m / 111_000
    dlon = dlat / max(math.cos(math.radians(lat)), 0.1)
    box = f"{lon - dlon},{lat + dlat},{lon + dlon},{lat - dlat}"
    seen, out = set(), []
    async with httpx.AsyncClient(timeout=20, headers=UA) as c:
        for word in NOMINATIM_WORDS:
            await _polite_wait()
            r = await c.get(NOMINATIM, params={"q": word, "format": "jsonv2", "limit": 50, "viewbox": box,
                                               "bounded": 1, "countrycodes": "th", "extratags": 1})
            r.raise_for_status()
            for row in r.json():
                if row.get("category") != "tourism" or row["osm_id"] in seen:
                    continue
                seen.add(row["osm_id"])
                tags = {"tourism": row.get("type"), "name": row.get("name"), **(row.get("extratags") or {})}
                out.append({"tags": tags, "lat": float(row["lat"]), "lon": float(row["lon"])})
    return out


async def hotels_around(lat: float, lon: float, radius_m: int) -> list[dict]:
    async def fetch():
        found = await _overpass(lat, lon, radius_m)
        return found if found is not None else await _nominatim_hotels(lat, lon, radius_m)

    elements = await _cached(("osm", round(lat, 3), round(lon, 3), radius_m), fetch)
    out = []
    for e in elements:
        tags, pos = e["tags"], e
        name = tags.get("name") or tags.get("name:th") or tags.get("name:en")
        if not name or "lat" not in pos:
            continue
        out.append({
            "name": name,
            "type": TYPES.get(tags.get("tourism"), "ที่พัก"),
            "lat": pos["lat"], "lon": pos["lon"],
            "km": round(_distance_km(lat, lon, pos["lat"], pos["lon"]), 1),
            "phone": tags.get("phone") or tags.get("contact:phone") or "",
            "website": tags.get("website") or tags.get("contact:website") or "",
            "stars": tags.get("stars", ""),
        })
    return sorted(out, key=lambda h: h["km"])


async def nearby(place: str, area: str, lat: float | None = None, lon: float | None = None) -> dict:
    """คืนตำแหน่งที่ทำงาน + ที่พักรอบๆ · approx=True แปลว่าหาที่ทำงานไม่เจอ ใช้ตำแหน่งกลางของจังหวัด/อำเภอแทน"""
    approx, label = False, ""
    if lat is None or lon is None:
        found = None
        short = clean_company(place)
        tries = [f"{place} {area}", f"{short} {area}", short, area] if place else [area]
        for q in dict.fromkeys(t.strip() for t in tries if t.strip()):  # ไม่ค้นคำซ้ำ
            found = await geocode(q)
            if found:
                approx = q == area and bool(place)
                break
        if not found:
            return {"found": False}
        lat, lon, label = found["lat"], found["lon"], found["label"]
    hotels = await hotels_around(lat, lon, 10_000)
    radius = 10
    if len(hotels) < 5:  # รอบที่ทำงานมีน้อย ขยายวงค้นหา
        hotels, radius = await hotels_around(lat, lon, 25_000), 25
    return {"found": True, "lat": lat, "lon": lon, "label": label, "approx": approx,
            "radius_km": radius, "hotels": hotels[:40]}


# ---------- พิกัดจากลิงก์ Google Maps ----------
# ลิงก์แชร์ (maps.app.goo.gl) จะ redirect ไปหน้า /maps/place/... ที่มีพิกัดของหมุดอยู่ใน URL
# รับเฉพาะโดเมนของ Google เพื่อไม่ให้ server ถูกใช้เปิดเว็บอื่นตามลิงก์ที่ผู้ใช้วาง
ALLOWED_HOSTS = ("google.com", "google.co.th", "goo.gl", "g.co")
COORD_PATTERNS = [
    r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",  # พิกัดของหมุดสถานที่ (แม่นที่สุด)
    r"[?&](?:q|query|ll|destination|center)=(-?\d+\.\d+)(?:,|%2C)\+?\s*(-?\d+\.\d+)",
    r"@(-?\d+\.\d+),(-?\d+\.\d+)",  # จุดกลางของแผนที่ที่เปิดอยู่ (ใช้เมื่อไม่มีแบบแรก)
]


def _coords(text: str) -> tuple[float, float] | None:
    for pattern in COORD_PATTERNS:
        if m := re.search(pattern, text):
            lat, lon = float(m[1]), float(m[2])
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
    return None


def _allowed(url: str) -> bool:
    host = httpx.URL(url).host.lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def _place_name(url: str) -> str:
    m = re.search(r"/maps/place/([^/@?]+)", url)
    return httpx.URL("http://x/?n=" + m[1]).params.get("n", "").strip() if m else ""


async def resolve_link(text: str) -> dict:
    """รับลิงก์ Google Maps หรือพิกัด "13.61, 100.26" → {lat, lon, name}"""
    text = text.strip()
    if m := re.fullmatch(r"\(?\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*\)?", text):
        return {"lat": float(m[1]), "lon": float(m[2]), "name": ""}
    m = re.search(r"https?://\S+", text)
    if not m or not _allowed(m[0]):
        raise ValueError("ใช้ได้เฉพาะลิงก์ Google Maps หรือพิกัด เช่น 13.6125, 100.2650")
    url = m[0]
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for _ in range(6):  # ตาม redirect ของลิงก์สั้นเองทีละขั้น เพื่อตรวจโดเมนทุกครั้ง
            if found := _coords(url):
                return {"lat": found[0], "lon": found[1], "name": _place_name(url)}
            r = await c.get(url, follow_redirects=False)
            nxt = r.headers.get("location")
            if not nxt:
                break
            nxt = str(r.url.join(nxt))
            if "consent.google" in nxt:  # หน้าขอความยินยอมคุกกี้ — ลิงก์จริงอยู่ใน continue
                nxt = httpx.URL(nxt).params.get("continue", nxt)
            if not _allowed(nxt):
                break
            url = nxt
    raise ValueError("ลิงก์นี้ไม่มีพิกัดของสถานที่ — ใน Google Maps ให้กดที่โรงงาน แล้วกด \"แชร์\" → \"คัดลอกลิงก์\"")
