-- Add rejected as a valid order status.
ALTER TABLE orders
MODIFY COLUMN status
ENUM('placed', 'accepted', 'packed', 'completed', 'cancelled', 'rejected')
NOT NULL DEFAULT 'placed';

-- Prevent stock from being restored more than once.
ALTER TABLE orders
ADD COLUMN stock_restored TINYINT(1) NOT NULL DEFAULT 0;
