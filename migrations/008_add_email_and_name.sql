-- Add email, first_name, last_name columns (nullable for existing users)
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN first_name TEXT;
ALTER TABLE users ADD COLUMN last_name TEXT;

-- Make username nullable for future users who register with email only
ALTER TABLE users ALTER COLUMN username DROP NOT NULL;

-- Unique index on email (partial: only non-null values)
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique ON users (email) WHERE email IS NOT NULL;
