"""Capacity entry in the admin product form: value + unit (TB default), legacy GB field still accepted."""
import pytest

from app.admin.products import parse_capacity


@pytest.mark.parametrize(
    ("form", "gb"),
    [
        ({"capacity_value": "4", "capacity_unit": "tb"}, 4000),
        ({"capacity_value": "1.5", "capacity_unit": "tb"}, 1500),
        ({"capacity_value": "1,5", "capacity_unit": "tb"}, 1500),
        ({"capacity_value": "0.5"}, 500),  # unit defaults to TB
        ({"capacity_value": "500", "capacity_unit": "gb"}, 500),
        ({"capacity_value": "18", "capacity_unit": "TB"}, 18000),
        ({"capacity_gb": "2000"}, 2000),  # legacy field
        ({"capacity_value": "", "capacity_gb": "3000"}, 3000),
        ({"capacity_value": "0", "capacity_unit": "tb"}, 0),
        ({"capacity_value": "abc", "capacity_unit": "tb"}, 0),
        ({"capacity_value": "-2", "capacity_unit": "gb"}, 0),
        ({"capacity_value": "99999999", "capacity_unit": "tb"}, 0),
        ({}, 0),
    ],
)
def test_parse_capacity(form, gb):
    assert parse_capacity(form) == gb
