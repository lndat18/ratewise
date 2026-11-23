CREATE TABLE shipments (
    id bigserial PRIMARY KEY,
    code text UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE emails (
    id bigserial PRIMARY KEY,
    message_id text UNIQUE NOT NULL,
    subject text NOT NULL DEFAULT '',
    from_addr text NOT NULL DEFAULT '',
    to_addrs text[] NOT NULL DEFAULT '{}',
    cc_addrs text[] NOT NULL DEFAULT '{}',
    sent_at timestamptz,
    body_text text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE email_sources (
    email_id bigint NOT NULL REFERENCES emails (id),
    folder text NOT NULL,
    uidvalidity bigint NOT NULL,
    uid bigint NOT NULL,
    UNIQUE (folder, uidvalidity, uid)
);

CREATE TABLE shipment_emails (
    shipment_id bigint NOT NULL REFERENCES shipments (id),
    email_id bigint NOT NULL REFERENCES emails (id),
    PRIMARY KEY (shipment_id, email_id)
);

CREATE TABLE attachments (
    id bigserial PRIMARY KEY,
    email_id bigint NOT NULL REFERENCES emails (id),
    filename text NOT NULL DEFAULT '',
    content_type text NOT NULL DEFAULT '',
    size_bytes bigint NOT NULL,
    sha256 text NOT NULL
);

CREATE TABLE sync_state (
    folder text PRIMARY KEY,
    uidvalidity bigint NOT NULL,
    last_uid bigint NOT NULL
);

CREATE INDEX shipment_emails_email_id_idx ON shipment_emails (email_id);
CREATE INDEX emails_sent_at_idx ON emails (sent_at);
CREATE INDEX attachments_email_id_idx ON attachments (email_id);
