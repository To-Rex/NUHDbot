"""Admin sidebar order: each staff member's own layout, merged with what their role may open."""
from app.admin.common import NAV_GROUPS, clean_nav_layout, nav_groups_for
from app.enums import Role
from app.models import User


def keys(staff: User) -> dict[str, list[str]]:
    return {g: [k for k, _, _ in items] for g, items in nav_groups_for(staff)}


DEFAULT = {g: [k for k, _, _, _ in items] for g, items in NAV_GROUPS}


def test_default_order():
    assert keys(User(role=Role.ADMIN)) == DEFAULT


def test_saved_order_and_new_items():
    layout = {"groups": {"manage": ["audit", "dashboard"], "sales": ["support", "orders"], "people": []}}
    got = keys(User(role=Role.ADMIN, nav_layout=layout))
    assert got["manage"] == ["audit", "dashboard"]
    # items the layout does not mention (e.g. added in a later release) go back to their usual group
    assert got["sales"] == ["support", "orders", "auctions"]
    assert got["people"] == ["customers", "staff"]
    assert got["system"] == ["settings", "currencies", "geo", "ads", "reports"]
    assert sorted(k for ks in got.values() for k in ks) == sorted(k for ks in DEFAULT.values() for k in ks)


def test_role_still_limits_items():
    layout = {"groups": {"manage": ["staff", "settings", "support", "dashboard"]}}
    got = keys(User(role=Role.ORDERS, nav_layout=layout))
    assert got["manage"] == ["support", "dashboard"]  # staff / settings are admin-only
    assert "staff" not in got["people"] and got["system"] == []


def test_clean_layout():
    assert clean_nav_layout({"reset": True}) is None
    assert clean_nav_layout(["x"]) is None
    assert clean_nav_layout({"groups": "x"}) is None
    dirty = {"groups": {"manage": ["dashboard", "nope", 5, "orders"], "sales": ["orders", "support"], "evil": ["audit"], "people": "x"}}
    assert clean_nav_layout(dirty) == {"groups": {"manage": ["dashboard", "orders"], "sales": ["support"]}}
