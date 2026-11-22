-- TicketDesk database schema (PostgreSQL 16 / Amazon RDS)
-- The application also creates these tables automatically on first start
-- (SQLAlchemy create_all), so running this script by hand is optional.
-- It documents the schema and can be used to create it manually:
--   psql "host=<rds-endpoint> dbname=ticketdesk user=<user> sslmode=require" -f db/schema.sql

CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(50)  NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,             -- PBKDF2-SHA256, never plain text
    role           VARCHAR(20)  NOT NULL DEFAULT 'user', -- user | agent | admin
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tickets (
    id             SERIAL PRIMARY KEY,
    title          VARCHAR(200) NOT NULL,
    description    TEXT         NOT NULL,
    priority       VARCHAR(20)  NOT NULL DEFAULT 'Medium', -- Low | Medium | High | Critical
    status         VARCHAR(20)  NOT NULL DEFAULT 'Open',   -- Open | In Progress | Resolved | Closed
    created_by_id  INTEGER      NOT NULL REFERENCES users(id),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS ix_tickets_created_by_id ON tickets(created_by_id);

CREATE TABLE IF NOT EXISTS attachments (
    id              SERIAL PRIMARY KEY,
    ticket_id       INTEGER      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    original_name   VARCHAR(255) NOT NULL,
    storage_key     VARCHAR(512) NOT NULL UNIQUE,   -- S3 key: attachments/ticket-<id>/<uuid>-<name>
    content_type    VARCHAR(100) NOT NULL,
    size_bytes      INTEGER      NOT NULL,
    uploaded_by_id  INTEGER      NOT NULL REFERENCES users(id),
    uploaded_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_attachments_ticket_id ON attachments(ticket_id);

CREATE TABLE IF NOT EXISTS ticket_events (
    id             SERIAL PRIMARY KEY,
    ticket_id      INTEGER      NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    from_status    VARCHAR(20),
    to_status      VARCHAR(20)  NOT NULL,
    note           VARCHAR(500),
    changed_by_id  INTEGER      NOT NULL REFERENCES users(id),
    changed_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ticket_events_ticket_id ON ticket_events(ticket_id);

-- Useful checks during the demo:
--   SELECT status, count(*) FROM tickets GROUP BY status;
--   SELECT t.id, t.title, a.original_name, a.storage_key FROM tickets t JOIN attachments a ON a.ticket_id = t.id;
