"""Commerce schema. Applied only by ``python -m platform_commerce migrate`` with the DDL role."""
from platform_backend_core import Migration

_WORKSPACE = "workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid"
TABLES = ('catalog_item', 'promotion', 'cart', 'cart_line', 'commerce_order', 'order_line')


def _rls(table):
    return (f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n'
            f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n'
            f'CREATE POLICY workspace ON {table} USING({_WORKSPACE}) WITH CHECK({_WORKSPACE});\n')


# Never edit an applied migration (including _rls and TABLES above): readiness and the
# runner compare its checksum. Add a new version instead.
# Orders stop at placed or cancelled: payment capture is outside this boundary (owner decision D8).
MIGRATIONS = [Migration('0001', """
CREATE TABLE catalog_item(
  workspace_id uuid NOT NULL, id uuid NOT NULL,
  sku text NOT NULL CHECK(sku ~ '^[A-Za-z0-9._-]{1,64}$'),
  name text NOT NULL CHECK(length(name) BETWEEN 1 AND 200),
  unit_price_minor bigint NOT NULL CHECK(unit_price_minor BETWEEN 0 AND 10000000000),
  currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,sku));
CREATE TABLE promotion(
  workspace_id uuid NOT NULL, id uuid NOT NULL,
  code text NOT NULL CHECK(code ~ '^[A-Z0-9_-]{1,32}$'),
  currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
  percent_off integer CHECK(percent_off BETWEEN 1 AND 100),
  amount_off_minor bigint CHECK(amount_off_minor BETWEEN 1 AND 10000000000),
  min_subtotal_minor bigint NOT NULL DEFAULT 0 CHECK(min_subtotal_minor BETWEEN 0 AND 1000000000000),
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CHECK((percent_off IS NULL) <> (amount_off_minor IS NULL)),
  PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,code));
CREATE TABLE cart(
  workspace_id uuid NOT NULL, id uuid NOT NULL,
  currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
  status text NOT NULL DEFAULT 'open' CHECK(status IN ('open','ordered')),
  promotion_code text CHECK(promotion_code ~ '^[A-Z0-9_-]{1,32}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(workspace_id,id));
CREATE TABLE cart_line(
  workspace_id uuid NOT NULL, cart_id uuid NOT NULL, item_id uuid NOT NULL,
  quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 1000),
  PRIMARY KEY(workspace_id,cart_id,item_id),
  FOREIGN KEY(workspace_id,cart_id) REFERENCES cart(workspace_id,id),
  FOREIGN KEY(workspace_id,item_id) REFERENCES catalog_item(workspace_id,id));
CREATE TABLE commerce_order(
  workspace_id uuid NOT NULL, id uuid NOT NULL, cart_id uuid NOT NULL,
  idempotency_key text NOT NULL, fingerprint text NOT NULL,
  status text NOT NULL DEFAULT 'placed' CHECK(status IN ('placed','cancelled')),
  currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
  subtotal_minor bigint NOT NULL CHECK(subtotal_minor >= 0),
  discount_minor bigint NOT NULL CHECK(discount_minor BETWEEN 0 AND subtotal_minor),
  total_minor bigint NOT NULL CHECK(total_minor = subtotal_minor - discount_minor),
  promotion_code text,
  placed_by uuid NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  cancelled_at timestamptz CHECK((status = 'cancelled') = (cancelled_at IS NOT NULL)),
  PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,idempotency_key), UNIQUE(workspace_id,cart_id),
  FOREIGN KEY(workspace_id,cart_id) REFERENCES cart(workspace_id,id));
CREATE TABLE order_line(
  workspace_id uuid NOT NULL, order_id uuid NOT NULL, item_id uuid NOT NULL,
  sku text NOT NULL, name text NOT NULL,
  unit_price_minor bigint NOT NULL CHECK(unit_price_minor >= 0),
  quantity integer NOT NULL CHECK(quantity BETWEEN 1 AND 1000),
  line_total_minor bigint NOT NULL CHECK(line_total_minor = unit_price_minor * quantity),
  PRIMARY KEY(workspace_id,order_id,item_id),
  FOREIGN KEY(workspace_id,order_id) REFERENCES commerce_order(workspace_id,id));
CREATE INDEX ON commerce_order(workspace_id,created_at,id);
""" + ''.join(_rls(t) for t in TABLES))]
