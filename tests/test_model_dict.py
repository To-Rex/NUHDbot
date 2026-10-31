"""Model dictionary: line parsing, bulk add with de-duplication, merge into the product form's known models."""
import pytest

from app.services import brands, model_dict
from tests.conftest import make_product


@pytest.mark.parametrize(
    ("line", "expect"),
    [
        ("ST4000VX016", {"name": "ST4000VX016", "capacity_gb": None, "interface": None, "form_factor": None, "series": None}),
        ("ST4000VX016 | 4TB | SkyHawk", {"name": "ST4000VX016", "capacity_gb": 4000, "interface": None, "form_factor": None, "series": "SkyHawk"}),
        ("WD40PURZ, 4 TB, SATA, 3.5, Purple", {"name": "WD40PURZ", "capacity_gb": 4000, "interface": "SATA", "form_factor": "3.5", "series": "Purple"}),
        ("MG08ADA800E 8TB SATA 3.5\" MG08", {"name": "MG08ADA800E", "capacity_gb": 8000, "interface": "SATA", "form_factor": "3.5", "series": "MG08"}),
        ("- HDWD120 2ТБ", {"name": "HDWD120", "capacity_gb": 2000, "interface": None, "form_factor": None, "series": None}),
        ("ST2000LM015;1.5TB;BarraCuda 2.5", {"name": "ST2000LM015", "capacity_gb": 1500, "interface": None, "form_factor": None, "series": "BarraCuda 2.5"}),
        ("ST500LM030\t500GB\tsas", {"name": "ST500LM030", "capacity_gb": 500, "interface": "SAS", "form_factor": None, "series": None}),
        ("# comment", None),
        ("   ", None),
    ],
)
def test_parse_line(line, expect):
    assert model_dict.parse_line(line) == expect


async def test_bulk_add_dedupes_and_fills_specs(db):
    b = await brands.create_brand(db, name="Seagate")
    added, skipped = await model_dict.bulk_add(db, b, "ST4000VX016\nst4000vx016 | 4TB\n\nST8000VX010 | 8TB | SkyHawk\n# note\nST8000VX010")
    assert [m.name for m in added] == ["ST4000VX016", "ST8000VX010"] and skipped == 2
    assert added[0].capacity_gb == 4000  # filled from the duplicate line, name kept as first entered
    await db.commit()
    again, skipped = await model_dict.bulk_add(db, b, "ST4000VX016\nNEW1")
    assert [m.name for m in again] == ["NEW1"] and skipped == 1
    assert (await model_dict.counts(db))[b.id] == 3


async def test_known_models_merges_dictionary_and_products(db):
    b = await brands.create_brand(db, name="Toshiba")
    await model_dict.bulk_add(db, b, "HDWD120 | 2TB | P300\nHDWT140UZSVA")
    p = await make_product(db)
    p.model = "hdwd120"
    brands.sync_product_brand(p, b)
    await db.commit()
    known = await model_dict.known_models(db)
    mine = [k for k in known if k["b"] == b.id]
    assert [k["m"] for k in mine] == ["HDWD120", "HDWT140UZSVA"]  # product model deduped against the dictionary entry
    assert mine[0]["src"] == "dict" and mine[0]["cap"] == 2000 and mine[0]["series"] == "P300"
    m = (await model_dict.list_models(db, b.id))[0]
    await model_dict.delete_model(db, m)
    await db.commit()
    assert [k["m"] for k in await model_dict.known_models(db) if k["b"] == b.id] == ["HDWT140UZSVA", "hdwd120"]


async def test_bulk_add_series_from_the_form(db):
    b = await brands.create_brand(db, name="Seagate")
    await model_dict.bulk_add(db, b, "ST4000VX016")  # already listed, no series yet
    added, skipped = await model_dict.bulk_add(db, b, "ST8000VN004\nST4000VX016\nST16000NM001G | Exos", series="IronWolf")
    got = {m.name: m.series for m in await model_dict.list_models(db, b.id)}
    assert (len(added), skipped) == (2, 1)
    # the picked series goes to new lines and fills an empty one; a line naming its own series keeps it
    assert got == {"ST8000VN004": "IronWolf", "ST4000VX016": "IronWolf", "ST16000NM001G": "Exos"}
