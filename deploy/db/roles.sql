-- Run once as a superuser before migrations. Passwords come from the environment in production
-- (psql -v api_password=... -f roles.sql).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bankrec_api') THEN
    CREATE ROLE bankrec_api LOGIN;
  END IF;
END $$;
