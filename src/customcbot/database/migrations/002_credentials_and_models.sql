-- Several AI services can be saved at once, each with the models to use from it.

-- A credential is one saved service: Ollama on this computer, or an online
-- service with its address and key.
CREATE TABLE credentials (
    id          INTEGER PRIMARY KEY,
    provider    TEXT NOT NULL,      -- an id from ai/provider_registry.py
    name        TEXT NOT NULL,      -- the label shown to the user
    base_url    TEXT,               -- NULL for Ollama: its address comes from Settings
    api_key     TEXT,               -- encrypted; see utils/encryption.py
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE models (
    id             INTEGER PRIMARY KEY,
    credential_id  INTEGER NOT NULL REFERENCES credentials(id) ON DELETE CASCADE,
    name           TEXT NOT NULL,                      -- the model's name at the service
    type           TEXT NOT NULL DEFAULT 'language',   -- language | text_to_speech
    vision         INTEGER NOT NULL DEFAULT 0,         -- 1 if it can read images
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (credential_id, name, type)
);
