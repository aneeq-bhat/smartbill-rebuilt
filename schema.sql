CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('super_admin','shopkeeper','consumer') NOT NULL,
  status ENUM('pending','active','rejected','suspended') NOT NULL DEFAULT 'active',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS shops (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  owner_user_id BIGINT NOT NULL UNIQUE,
  name VARCHAR(160) NOT NULL,
  slug VARCHAR(180) NOT NULL UNIQUE,
  description TEXT NULL,
  address TEXT NULL,
  status ENUM('pending','active','rejected','suspended') NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_shops_owner FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS products (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  shop_id BIGINT NOT NULL,
  name VARCHAR(180) NOT NULL,
  sku VARCHAR(80) NULL,
  description TEXT NULL,
  price DECIMAL(12,2) NOT NULL,
  stock_qty INT NOT NULL DEFAULT 0,
  is_listed BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_products_shop (shop_id),
  INDEX idx_products_market (is_listed, shop_id),
  CONSTRAINT fk_products_shop FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS customers (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  shop_id BIGINT NOT NULL,
  name VARCHAR(120) NOT NULL,
  phone VARCHAR(40) NULL,
  email VARCHAR(190) NULL,
  linked_user_id BIGINT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_customers_shop (shop_id),
  CONSTRAINT fk_customers_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
  CONSTRAINT fk_customers_user FOREIGN KEY (linked_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS invoices (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  shop_id BIGINT NOT NULL,
  customer_id BIGINT NULL,
  invoice_number VARCHAR(60) NOT NULL,
  subtotal DECIMAL(12,2) NOT NULL,
  tax_total DECIMAL(12,2) NOT NULL DEFAULT 0,
  grand_total DECIMAL(12,2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_invoice_shop_number (shop_id, invoice_number),
  INDEX idx_invoice_shop (shop_id),
  CONSTRAINT fk_invoices_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
  CONSTRAINT fk_invoices_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS invoice_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  invoice_id BIGINT NOT NULL,
  product_id BIGINT NULL,
  item_name VARCHAR(180) NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL,
  line_total DECIMAL(12,2) NOT NULL,
  CONSTRAINT fk_items_invoice FOREIGN KEY (invoice_id) REFERENCES invoices(id),
  CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  consumer_user_id BIGINT NOT NULL,
  shop_id BIGINT NOT NULL,
  status ENUM('placed','accepted','packed','completed','cancelled') NOT NULL DEFAULT 'placed',
  total DECIMAL(12,2) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_orders_consumer (consumer_user_id),
  INDEX idx_orders_shop (shop_id),
  CONSTRAINT fk_orders_consumer FOREIGN KEY (consumer_user_id) REFERENCES users(id),
  CONSTRAINT fk_orders_shop FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS order_items (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  product_name VARCHAR(180) NOT NULL,
  quantity INT NOT NULL,
  unit_price DECIMAL(12,2) NOT NULL,
  line_total DECIMAL(12,2) NOT NULL,
  CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id),
  CONSTRAINT fk_order_items_product FOREIGN KEY (product_id) REFERENCES products(id)
);
