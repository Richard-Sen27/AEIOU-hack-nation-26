-- Idempotent bootstrap for the atlas database. Run as a superuser, connected to the target
-- database (docker-entrypoint-initdb.d on first start, `make db-bootstrap` afterwards, and the
-- test harness for throwaway databases). Dev passwords equal the role name.

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_owner') THEN
    CREATE ROLE atlas_owner LOGIN PASSWORD 'atlas_owner';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_app') THEN
    CREATE ROLE atlas_app LOGIN PASSWORD 'atlas_app';
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_pipeline') THEN
    CREATE ROLE atlas_pipeline LOGIN PASSWORD 'atlas_pipeline';
  END IF;
  -- Owns the narrow SECURITY DEFINER functions; cannot log in.
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atlas_definer') THEN
    CREATE ROLE atlas_definer NOLOGIN;
  END IF;
END
$$;

ALTER ROLE atlas_owner NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
ALTER ROLE atlas_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE atlas_pipeline NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE atlas_definer NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOLOGIN;

-- atlas_owner may hand function ownership to atlas_definer (needs SET on that role).
GRANT atlas_definer TO atlas_owner;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I OWNER TO atlas_owner', current_database());
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format(
    'GRANT CONNECT, TEMPORARY ON DATABASE %I TO atlas_app, atlas_pipeline', current_database()
  );
END
$$;

ALTER SCHEMA public OWNER TO atlas_owner;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO atlas_app, atlas_pipeline, atlas_definer;
GRANT CREATE ON SCHEMA public TO atlas_definer;

CREATE SCHEMA IF NOT EXISTS staging AUTHORIZATION atlas_pipeline;
ALTER SCHEMA staging OWNER TO atlas_pipeline;
REVOKE ALL ON SCHEMA staging FROM PUBLIC;
