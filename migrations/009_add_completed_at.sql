ALTER TABLE todos ADD COLUMN completed_at TIMESTAMPTZ;

-- Backfill: for already-completed todos, use updated_at as best guess
UPDATE todos SET completed_at = updated_at WHERE completed = true;
