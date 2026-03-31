-- APIS database initialization script
-- Run once on first postgres container start via docker-entrypoint-initdb.d

-- Create the test database alongside the primary one
CREATE DATABASE apis_test
    WITH
    OWNER = apis
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.utf8'
    LC_CTYPE = 'en_US.utf8'
    TEMPLATE = template0;
