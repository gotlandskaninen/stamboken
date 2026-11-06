-- Init script för PostgreSQL
-- Skapar demo-databas vid första uppstart
-- 
-- Denna fil körs automatiskt av PostgreSQL docker image
-- vid första start (när postgres-data är tom)

-- Skapa demo-databas om den inte finns
SELECT 'CREATE DATABASE herdbook_demo'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'herdbook_demo')\gexec

-- Ge samma användare rättigheter
GRANT ALL PRIVILEGES ON DATABASE herdbook_demo TO herdbook;
