CREATE TABLE IF NOT EXISTS order_return_requests (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  order_id BIGINT NOT NULL UNIQUE,
  consumer_user_id BIGINT NOT NULL,
  reason VARCHAR(120) NOT NULL,
  details TEXT NULL,
  status ENUM('requested','approved','rejected','received','closed') NOT NULL DEFAULT 'requested',
  admin_note TEXT NULL,
  reviewed_by BIGINT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_returns_consumer (consumer_user_id),
  INDEX idx_returns_status (status),
  CONSTRAINT fk_returns_order FOREIGN KEY (order_id) REFERENCES orders(id),
  CONSTRAINT fk_returns_consumer FOREIGN KEY (consumer_user_id) REFERENCES users(id),
  CONSTRAINT fk_returns_reviewer FOREIGN KEY (reviewed_by) REFERENCES users(id)
);
