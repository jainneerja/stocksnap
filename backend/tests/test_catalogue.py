"""Product catalogue: a folder of product photos -> names, prices -> PDF."""

import io

from PIL import Image

from conftest import photo


def _files(*names):
    colours = [(220, 60, 120), (40, 90, 200), (30, 160, 80), (200, 170, 40)]
    return [("files", (n, photo(colours[i % 4]), "image/jpeg")) for i, n in enumerate(names)]


def test_folder_to_pdf(client):
    files = _files("dress10.jpg", "IMG_2041.jpg", "red_leaves-dress.jpg", "dress9.jpg")
    files.append(("files", ("notes.txt", b"hello", "text/plain")))      # not a photo: ignored
    r = client.post("/api/catalogues", files=files, data={"title": "Diwali dresses", "hint": "Laddu Gopal dress"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    c = client.get(f"/api/catalogues/{cid}").json()          # background work done in TestClient
    assert c["status"] == "done" and c["total"] == 4
    assert [it["file"] for it in c["items"]] == ["dress9.jpg", "dress10.jpg", "IMG_2041.jpg", "red_leaves-dress.jpg"]
    names = {it["file"]: it["name"] for it in c["items"]}
    assert names["red_leaves-dress.jpg"] == "Red leaves dress"   # the seller's file name wins
    assert names["IMG_2041.jpg"] == "Rhododendron Tee"           # camera name: the AI names it
    assert all(it["description"] for it in c["items"])
    assert all("Laddu Gopal dress" in s for s in client.vision.sellers)   # the seller's word reaches the AI

    first = c["items"][0]["id"]
    e = client.put(f"/api/catalogues/{cid}", json={"subtitle": "WhatsApp 98xxxxxx", "columns": 3,
                                                    "items": [{"id": first, "price": "₹499", "include": True},
                                                              {"id": c["items"][1]["id"], "include": False}]}).json()
    assert e["items"][0]["price"] == "₹499" and e["items"][1]["include"] is False and e["columns"] == 3

    pdf = client.get(f"/api/catalogues/{cid}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/catalogues/{cid}/photos/{c['items'][0]['photo']}").status_code == 200
    assert client.get(f"/api/catalogues/{cid}/photos/catalogue.json").status_code == 404
    assert [x["id"] for x in client.get("/api/catalogues").json()] == [cid]
    assert client.delete(f"/api/catalogues/{cid}").status_code == 204
    assert client.get(f"/api/catalogues/{cid}").status_code == 404


def test_works_without_ai(make_client):
    c = make_client(vision_fails=True)
    cid = c.post("/api/catalogues", files=_files("IMG_1.jpg", "PXL_2.jpg"), data={"hint": "dress"}).json()["id"]
    cat = c.get(f"/api/catalogues/{cid}").json()
    assert cat["status"] == "done"
    assert all(it["status"] == "ready" and it["name"] for it in cat["items"])
    assert cat["mode"] == "instant"
    assert c.get(f"/api/catalogues/{cid}/pdf").content[:4] == b"%PDF"


def test_no_photos(client):
    r = client.post("/api/catalogues", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert r.status_code == 400


def test_name_from_file():
    from app.services.catalogue import name_from_file

    assert name_from_file("blue_pearl-set (2).jpg") == "Blue pearl set"
    for camera in ("IMG_2041.jpg", "WhatsApp Image 2026-10-01 at 10.jpeg", "PXL_20261001.jpg", "1234.png"):
        assert name_from_file(camera) == "", camera


def test_folders_give_size_design_colour(client):
    paths = ["Lehenga/Size 6/Design 1/Blue.jpg", "Lehenga/Size 6/Design 1/Red.jpg",
             "Lehenga/Size 7/Design 2/Light Pink.jpg", "Lehenga/_preview/sheet.jpg"]
    files = _files("Blue.jpg", "Red.jpg", "Light Pink.jpg", "sheet.jpg")
    r = client.post("/api/catalogues", files=files,
                    data={"paths": paths, "hint": "Lehenga patka", "title": "Mata Rani"})
    assert r.status_code == 201, r.text
    c = client.get(f"/api/catalogues/{r.json()['id']}").json()
    assert c["layout"] == "designs" and c["total"] == 3            # _preview folder skipped
    first = c["items"][0]
    assert (first["size"], first["design"], first["colour"]) == ("6", "Design 1", "Blue")
    assert first["name"] == "Lehenga patka Design 1 Blue (size 6)"
    assert c["items"][2]["colour"] == "Light Pink"
    client.put(f"/api/catalogues/{c['id']}", json={"items": [{"id": first["id"], "price": "₹350"}]})
    pdf = client.get(f"/api/catalogues/{c['id']}/pdf")
    assert pdf.content[:4] == b"%PDF"


def _jpg(path, colour):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (300, 300), colour).save(path, "JPEG")


def test_from_shop_folder(client, tmp_path):
    shop = tmp_path / "Ekaa Creations (Anjana Aggarwal)"
    lg = shop / "Catalogue 1 -  Ladoo Gopal"
    _jpg(lg / "front_page.jpg", (250, 200, 200))
    _jpg(lg / "Size 4" / "Design 1 - Rs 70" / "Blue.jpg", (30, 60, 200))
    _jpg(lg / "Size 4" / "Design 1 - Rs 70" / "Ladoo Gopal Blue.jpg", (30, 60, 220))
    _jpg(lg / "Size 4" / "Design 2 - Rs 200" / "Pink.jpg", (230, 80, 160))
    _jpg(lg / "Size 5" / "Design 1" / "Red.jpg", (220, 30, 30))
    _jpg(shop / "Catalogue 2 - Lehenga Patka" / "Size 7" / "Design 2 - Rs 140" / "Dark Pink.jpg", (200, 20, 120))

    r = client.post("/api/catalogues/from-folder", json={"path": str(shop)})
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["shop"], out["owner"]) == ("Ekaa Creations", "Anjana Aggarwal")
    assert [c["title"] for c in out["catalogues"]] == ["Ladoo Gopal", "Lehenga Patka"]
    first = out["catalogues"][0]
    assert first["photos"] == 4 and first["designs"] == 3
    assert any("No price" in n and "Design 1 (size 5)" in n for n in first["notes"])
    assert sorted(p.split("(")[-1] for p in first["saved"]) == ["with prices).pdf", "without prices).pdf"]
    with_p = lg / "Ladoo Gopal - catalogue (with prices).pdf"
    assert with_p.read_bytes()[:4] == b"%PDF" and (lg / "Ladoo Gopal - catalogue (without prices).pdf").is_file()

    cat = client.get(f"/api/catalogues/{first['id']}").json()
    by_file = {it["file"].replace("\\\\", "/"): it for it in cat["items"]}
    blue = by_file["Size 4/Design 1 - Rs 70/Blue.jpg"]
    assert (blue["size"], blue["design"], blue["price"], blue["colour"]) == ("4", "Design 1", "₹70", "Blue")
    assert by_file["Size 4/Design 1 - Rs 70/Ladoo Gopal Blue.jpg"]["colour"] == "Blue (on idol)"
    assert cat["cover"] == "cover.jpg" and cat["subtitle"] == ""
    assert client.get(f"/api/catalogues/{first['id']}/photos/cover.jpg").status_code == 200
    assert client.get(f"/api/catalogues/{first['id']}/pdf?prices=false").content[:4] == b"%PDF"


def test_from_folder_errors(client, tmp_path):
    assert client.post("/api/catalogues/from-folder", json={"path": str(tmp_path / "nope")}).status_code == 400
    (tmp_path / "empty").mkdir()
    assert client.post("/api/catalogues/from-folder", json={"path": str(tmp_path / "empty")}).status_code == 400
