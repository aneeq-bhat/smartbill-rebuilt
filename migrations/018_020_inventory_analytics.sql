-- Batch 18-20: inventory thresholds and auditable manual stock adjustments.
-- The CLI command performs idempotent information_schema checks before ALTER.
CREATE TABLE IF NOT EXISTS inventory_movements (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  shop_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  movement_type ENUM('stock_in','stock_out') NOT NULL,
  quantity_delta INT NOT NULL,
  stock_before INT NOT NULL,
  stock_after INT NOT NULL,
  reason VARCHAR(240) NOT NULL,
  created_by BIGINT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_inventory_shop_created (shop_id, created_at),
  INDEX idx_inventory_product_created (product_id, created_at),
  CONSTRAINT fk_inventory_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
  CONSTRAINT fk_inventory_product FOREIGN KEY (product_id) REFERENCES products(id),
  CONSTRAINT fk_inventory_user FOREIGN KEY (created_by) REFERENCES users(id)
);
