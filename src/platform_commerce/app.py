"""Commerce HTTP API. Workspace authority comes only from the verified token (``ws``)."""
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from platform_backend_core import create_app as base_app
from platform_backend_core import require_scope
from pydantic import BaseModel, ConfigDict, Field

from .store import CommerceStore, Conflict, NotFound


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class NewItem(Strict):
    sku: str = Field(max_length=64)
    name: str = Field(max_length=200)
    unit_price_minor: int
    currency: str = Field(max_length=3)


class ItemChange(Strict):
    name: str | None = Field(default=None, max_length=200)
    unit_price_minor: int | None = None
    active: bool | None = None


class NewPromotion(Strict):
    code: str = Field(max_length=32)
    currency: str = Field(max_length=3)
    percent_off: int | None = None
    amount_off_minor: int | None = None
    min_subtotal_minor: int = 0


class NewCart(Strict):
    currency: str = Field(max_length=3)


class Line(Strict):
    quantity: int


class PromotionCode(Strict):
    code: str = Field(max_length=32)


class NewOrder(Strict):
    cart_id: UUID = Field(strict=False)  # FastAPI validates parsed JSON, where a UUID is a string
    expected_total_minor: int | None = None


def create_app(database, verifier):
    app = base_app('commerce', database, verifier, max_body_bytes=16384)
    store = CommerceStore(database)
    app.state.readiness_checks['commerce_schema'] = store.ready

    # Fixed messages only: never the request body, key, SKU or database error text.
    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': 'invalid request'}, 422)

    @app.exception_handler(NotFound)
    async def missing(request, exc):
        return JSONResponse({'detail': 'Not found'}, 404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({'detail': exc.reason}, 409)

    def found(row):
        if row is None:
            raise HTTPException(404, 'Not found')
        return row

    page = Query(100, ge=1, le=100)

    # catalog
    @app.post('/v1/catalog/items', status_code=201)
    def create_item(body: NewItem, p=Depends(require_scope('catalog:write'))):
        return store.create_item(p.workspace, body.sku, body.name, body.unit_price_minor, body.currency)

    @app.get('/v1/catalog/items')
    def list_items(limit: int = page, after: UUID | None = None, p=Depends(require_scope('catalog:read'))):
        return store.list_items(p.workspace, limit, after)

    @app.get('/v1/catalog/items/{item_id}')
    def get_item(item_id: UUID, p=Depends(require_scope('catalog:read'))):
        return found(store.get_item(p.workspace, item_id))

    @app.patch('/v1/catalog/items/{item_id}')
    def update_item(item_id: UUID, body: ItemChange, p=Depends(require_scope('catalog:write'))):
        return store.update_item(p.workspace, item_id, name=body.name, unit_price_minor=body.unit_price_minor,
                                 active=body.active)

    # promotions
    @app.post('/v1/promotions', status_code=201)
    def create_promotion(body: NewPromotion, p=Depends(require_scope('promotions:write'))):
        return store.create_promotion(p.workspace, body.code, body.currency, percent_off=body.percent_off,
                                      amount_off_minor=body.amount_off_minor, min_subtotal_minor=body.min_subtotal_minor)

    @app.get('/v1/promotions')
    def list_promotions(limit: int = page, after: UUID | None = None, p=Depends(require_scope('promotions:read'))):
        return store.list_promotions(p.workspace, limit, after)

    # carts
    @app.post('/v1/carts', status_code=201)
    def create_cart(body: NewCart, p=Depends(require_scope('cart:write'))):
        return store.create_cart(p.workspace, body.currency)

    @app.get('/v1/carts/{cart_id}')
    def get_cart(cart_id: UUID, p=Depends(require_scope('cart:read'))):
        return found(store.get_cart(p.workspace, cart_id))

    @app.put('/v1/carts/{cart_id}/lines/{item_id}')
    def set_line(cart_id: UUID, item_id: UUID, body: Line, p=Depends(require_scope('cart:write'))):
        return store.set_line(p.workspace, cart_id, item_id, body.quantity)

    @app.put('/v1/carts/{cart_id}/promotion')
    def set_promotion(cart_id: UUID, body: PromotionCode, p=Depends(require_scope('cart:write'))):
        return store.set_promotion(p.workspace, cart_id, body.code)

    @app.delete('/v1/carts/{cart_id}/promotion')
    def clear_promotion(cart_id: UUID, p=Depends(require_scope('cart:write'))):
        return store.set_promotion(p.workspace, cart_id, None)

    # orders
    @app.post('/v1/orders')
    def place_order(body: NewOrder, key: str = Header(alias='Idempotency-Key', max_length=128),
                    p=Depends(require_scope('orders:write'))):
        order, created = store.place_order(p.workspace, p.actor, key, body.cart_id, body.expected_total_minor)
        return JSONResponse(jsonable_encoder(order), 201 if created else 200)

    @app.get('/v1/orders')
    def list_orders(limit: int = page, after: UUID | None = None, p=Depends(require_scope('orders:read'))):
        return store.list_orders(p.workspace, limit, after)

    @app.get('/v1/orders/{order_id}')
    def get_order(order_id: UUID, p=Depends(require_scope('orders:read'))):
        return found(store.get_order(p.workspace, order_id))

    @app.post('/v1/orders/{order_id}/cancel')
    def cancel_order(order_id: UUID, p=Depends(require_scope('orders:write'))):
        return store.cancel_order(p.workspace, order_id)

    return app
