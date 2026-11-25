"""MotoAhlas Instagram yayın otomasyonu (Instagram Graph API, içerik yayınlama).

Varsayılan mod DRY-RUN: hiçbir şey göndermez, ne yapacağını yazar.
Yayınlamak için hepsi gerekli:
  1. posts.json içinde gönderinin "approved": true olması (kullanıcı onayı),
  2. ortam değişkenleri IG_ACCESS_TOKEN (instagram_content_publish izinli) ve IG_USER_ID,
  3. görsellerin herkese açık bir adresten sunulması (--base-url),
  4. --send bayrağı.

Kullanım:
  python yayinla.py --base-url https://ornek.com/ig/          # dry-run, vakti gelenleri listeler
  python yayinla.py --base-url https://ornek.com/ig/ --send   # vakti gelen ve onaylı olanları yayınlar
  python yayinla.py --only sym-adx-125 --base-url ... --send  # tek gönderi

Zamanlama: Windows Görev Zamanlayıcı ile 15 dakikada bir `--send` ile çalıştırılır.
Not: Bu betik henüz canlı API'ye karşı denenmedi. İlk gerçek çalıştırmayı tek gönderiyle (--only) yapın.
"""
import argparse, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
# Instagram Login tokeni için: IG_API=https://graph.instagram.com/v23.0
API = os.environ.get("IG_API", "https://graph.facebook.com/v23.0")
TZ = ZoneInfo("Europe/Istanbul")
STATE = os.path.join(HERE, "yayinlandi.json")


def call(path, params, token):
    data = urllib.parse.urlencode({**params, "access_token": token}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{path}", data=data), timeout=60) as r:
        return json.load(r)


def wait_ready(cid, token):
    for _ in range(30):
        url = f"{API}/{cid}?fields=status_code&access_token={urllib.parse.quote(token)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            st = json.load(r).get("status_code")
        if st == "FINISHED":
            return
        if st == "ERROR":
            raise RuntimeError(f"Konteyner hatası: {cid}")
        time.sleep(2)
    raise RuntimeError(f"Konteyner zaman aşımı: {cid}")


def publish(post, base, uid, token):
    urls = [base.rstrip("/") + "/" + f for f in post["files"]]
    if len(urls) == 1:
        c = call(f"{uid}/media", {"image_url": urls[0], "caption": post["caption"]}, token)["id"]
    else:
        kids = [call(f"{uid}/media", {"image_url": u, "is_carousel_item": "true"}, token)["id"] for u in urls]
        for k in kids:
            wait_ready(k, token)
        c = call(f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": post["caption"]}, token)["id"]
    wait_ready(c, token)
    return call(f"{uid}/media_publish", {"creation_id": c}, token)["id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get("IG_BASE_URL"), help="görsellerin herkese açık adresi (veya IG_BASE_URL)")
    ap.add_argument("--max-late-min", type=int, default=180, help="vakti bu kadar dakikadan fazla geçmiş gönderiyi atla")
    ap.add_argument("--send", action="store_true", help="gerçekten yayınla (yoksa dry-run)")
    ap.add_argument("--only", help="yalnızca bu id")
    a = ap.parse_args()

    posts = json.load(open(os.path.join(HERE, "posts.json"), encoding="utf8"))["posts"]
    done = json.load(open(STATE, encoding="utf8")) if os.path.exists(STATE) else {}
    now = datetime.now(TZ)
    if not a.base_url:
        sys.exit("--base-url (veya IG_BASE_URL) gerekli.")
    token, uid = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if a.send and not (token and uid):
        sys.exit("IG_ACCESS_TOKEN ve IG_USER_ID ortam değişkenleri gerekli.")

    failed = False
    for p in posts:
        if a.only and p["id"] != a.only:
            continue
        due = datetime.fromisoformat(f"{p['date']}T{p['time']}").replace(tzinfo=TZ)
        if p["id"] in done:
            continue
        if not a.only and due > now:
            continue
        tag = f"{p['date']} {p['time']} {p['id']} ({len(p['files'])} görsel)"
        late_min = (now - due).total_seconds() / 60
        if not a.only and late_min > a.max_late_min:
            print("ATLANDI (vakti geçti):", tag)
            continue
        if p.get("manual"):
            print("ATLANDI (elle yayınlanacak):", tag)
            continue
        if not p.get("approved"):
            print("ATLANDI (onay yok):", tag)
            continue
        if not a.send:
            print("DRY-RUN yayınlanacaktı:", tag)
            continue
        try:
            mid = publish(p, a.base_url, uid, token)
        except Exception as e:  # bir gönderinin hatası diğerlerini durdurmasın
            print("HATA:", tag, repr(e))
            failed = True
            continue
        done[p["id"]] = {"media_id": mid, "at": now.isoformat()}
        json.dump(done, open(STATE, "w", encoding="utf8"), indent=1)
        print("YAYINLANDI:", tag, mid)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
