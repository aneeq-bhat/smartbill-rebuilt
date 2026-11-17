CREATE TABLE IF NOT EXISTS payment_transactions (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  consumer_user_id BIGINT NOT NULL,
  razorpay_order_id VARCHAR(80) NOT NULL UNIQUE,
  razorpay_payment_id VARCHAR(80) NULL UNIQUE,
  amount_paise BIGINT NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'INR',
  status ENUM('created','paid','failed','paid_stock_conflict') NOT NULL DEFAULT 'created',
  cart_snapshot LONGTEXT NOT NULL,
  order_ids LONGTEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_payment_consumer (consumer_user_id),
  CONSTRAINT fk_payment_consumer FOREIGN KEY (consumer_user_id) REFERENCES users(id)
);

ALTER TABLE orders ADD COLUMN payment_transaction_id BIGINT NULL;
ALTER TABLE orders ADD INDEX idx_orders_payment_transaction (payment_transaction_id);
ALTER TABLE orders ADD CONSTRAINT fk_orders_payment_transaction FOREIGN KEY (payment_transaction_id) REFERENCES payment_transactions(id);
