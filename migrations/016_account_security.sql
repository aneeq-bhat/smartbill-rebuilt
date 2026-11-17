-- Account security schema for email verification and password recovery.
-- Existing users remain verified; new registrations explicitly set email_verified=0.
ALTER TABLE users ADD COLUMN email_verified TINYINT(1) NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS account_security_tokens (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  purpose ENUM('verify_email','reset_password') NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  used_at DATETIME NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_account_tokens_user_purpose (user_id,purpose,used_at),
  INDEX idx_account_tokens_expiry (expires_at),
  CONSTRAINT fk_account_tokens_user FOREIGN KEY (user_id) REFERENCES users(id)
);
