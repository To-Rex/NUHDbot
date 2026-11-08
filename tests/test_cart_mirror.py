"""The cart is mirrored on the user row: staff see it, an empty session starts from it, and only changes are written."""
from app.services import cart
from tests.conftest import make_user


async def test_cart_mirror_and_fallback(db):
    u = await make_user(db, 51)
    assert cart.user_cart(u) == {} and cart.effective_cart({}, u) == {} and cart.effective_cart({}, None) == {}
    cart.persist(u, {12: 3, 7: 0})
    await db.flush()
    assert u.cart == {"12": 3} and u.cart_at is not None
    stamp = u.cart_at
    cart.persist(u, {12: 3})  # the same cart: nothing rewritten
    assert u.cart_at == stamp
    assert cart.effective_cart({}, u) == {12: 3}  # a new device: the kept cart
    assert cart.effective_cart({"cart": {"5": 1}}, u) == {5: 1}  # the session's own cart wins
    cart.persist(u, {})
    assert u.cart is None and u.cart_at >= stamp
    assert cart.effective_cart({"cart": {}}, u) == {}
