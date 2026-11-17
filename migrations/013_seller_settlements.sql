CREATE TABLE IF NOT EXISTS seller_onboarding (
  shop_id BIGINT PRIMARY KEY,
  legal_business_name VARCHAR(180) NULL,
  business_type VARCHAR(80) NULL,
  contact_phone VARCHAR(40) NULL,
  business_address TEXT NULL,
  pan_status ENUM('not_submitted','submitted','verified','rejected') NOT NULL DEFAULT 'not_submitted',
  bank_status ENUM('not_submitted','submitted','verified','rejected') NOT NULL DEFAULT 'not_submitted',
  address_status ENUM('not_submitted','submitted','verified','rejected') NOT NULL DEFAULT 'not_submitted',
  route_status ENUM('not_applied','submitted','under_review','approved','rejected','not_eligible') NOT NULL DEFAULT 'not_applied',
  route_linked_account_id VARCHAR(100) NULL,
  admin_notes TEXT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_seller_onboarding_shop FOREIGN KEY (shop_id) REFERENCES shops(id)
);

CREATE TABLE IF NOT EXISTS platform_commission_settings (
  id TINYINT PRIMARY KEY,
  commission_bps INT NOT NULL DEFAULT 0,
  updated_by BIGINT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT chk_commission_bps CHECK (commission_bps >= 0 AND commission_bps <= 3000),
  CONSTRAINT fk_commission_admin FOREIGN KEY (updated_by) REFERENCES users(id)
);

INSERT IGNORE INTO platform_commission_settings (id, commission_bps) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS seller_ledger (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  shop_id BIGINT NOT NULL,
  order_id BIGINT NOT NULL UNIQUE,
  payment_transaction_id BIGINT NULL,
  gross_paise BIGINT NOT NULL,
  commission_bps INT NOT NULL DEFAULT 0,
  commission_paise BIGINT NOT NULL DEFAULT 0,
  net_paise BIGINT NOT NULL,
  status ENUM('pending','held','eligible','manual_paid','reversed') NOT NULL DEFAULT 'pending',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_seller_ledger_shop_status (shop_id,status),
  CONSTRAINT fk_seller_ledger_shop FOREIGN KEY (shop_id) REFERENCES shops(id),
  CONSTRAINT fk_seller_ledger_order FOREIGN KEY (order_id) REFERENCES orders(id),
  CONSTRAINT fk_seller_ledger_payment FOREIGN KEY (payment_transaction_id) REFERENCES payment_transactions(id)
);

CREATE TABLE IF NOT EXISTS seller_manual_settlements (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  ledger_id BIGINT NOT NULL UNIQUE,
  amount_paise BIGINT NOT NULL,
  payment_reference VARCHAR(120) NOT NULL,
  note VARCHAR(500) NULL,
  recorded_by BIGINT NOT NULL,
  recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_manual_settlement_ledger FOREIGN KEY (ledger_id) REFERENCES seller_ledger(id),
  CONSTRAINT fk_manual_settlement_admin FOREIGN KEY (recorded_by) REFERENCES users(id)
);
