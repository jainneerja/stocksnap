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
