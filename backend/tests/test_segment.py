import io

import pytest
from PIL import Image

from app.services.segment import find_pieces
from trays import jewellery_tray, soap_tray


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_counts_jewellery_on_black(seed):
    data, n = jewellery_tray(seed=seed)
    seg = find_pieces(Image.open(io.BytesIO(data)))
    assert len(seg.pieces) == n and seg.background == "dark"


def test_touching_earring_pair_counts_as_one():
    data, n = jewellery_tray(seed=3, touching_pair_at=(1, 2))
    assert len(find_pieces(Image.open(io.BytesIO(data))).pieces) == n


def test_low_contrast_kraft_soap_on_white_is_found():
    seg = find_pieces(Image.open(io.BytesIO(soap_tray([1, 1, 1, 1, 0, 2, 0, 2]))))
    assert len(seg.pieces) == 8 and seg.background == "light"
    assert all(p.w > 300 for p in seg.pieces)  # whole bar, not just its label text


def test_mat_smaller_than_frame():
    data, n = jewellery_tray(seed=2, size=(1800, 1300))
    table = Image.new("RGB", (2400, 1800), (150, 110, 75))
    table.paste(Image.open(io.BytesIO(data)), (300, 250))
    assert len(find_pieces(table).pieces) == n


def test_numbering_reads_rows_left_to_right():
    data, _ = jewellery_tray(seed=1, cols=3, rows=2)
    p = find_pieces(Image.open(io.BytesIO(data))).pieces
    assert p[0].x < p[1].x < p[2].x and p[3].y > p[0].y
