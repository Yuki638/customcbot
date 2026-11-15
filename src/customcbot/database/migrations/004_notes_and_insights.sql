-- Notes, reusable prompts ("transformations") and what they produce ("insights").

CREATE TABLE notes (
    id            INTEGER PRIMARY KEY,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    content       TEXT NOT NULL DEFAULT '',
    note_type     TEXT NOT NULL DEFAULT 'human',   -- human: written by the user | ai: saved from an answer
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX notes_collection ON notes(collection_id);

-- A transformation is a task to carry out on a source, such as "list the key points".
CREATE TABLE transformations (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    prompt        TEXT,                -- NULL for a built-in that still has its original wording
    builtin       TEXT UNIQUE,         -- name of the template in prompts/transformations/, NULL for the user's own
    apply_default INTEGER NOT NULL DEFAULT 0,      -- 1: run on every new source
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO transformations (title, description, builtin) VALUES
    ('Study guide', 'An overview, the key ideas, important terms and questions to test yourself.', 'study_guide'),
    ('Key points', 'The most important points as a short list.', 'key_points'),
    ('Glossary', 'The important terms, each with a one-line definition.', 'glossary'),
    ('Revision questions', 'Questions to practise with, each with a short model answer.', 'revision_questions'),
    ('Explain it simply', 'What the material says, in plain language with an everyday example.', 'explain_simply');

CREATE TABLE source_insights (
    id                INTEGER PRIMARY KEY,
    source_id         INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    collection_id     INTEGER NOT NULL,
    transformation_id INTEGER REFERENCES transformations(id) ON DELETE SET NULL,
    insight_type      TEXT NOT NULL,   -- the transformation's title when it was made
    content           TEXT NOT NULL,
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX insights_source ON source_insights(source_id);

-- Study guides written by earlier versions become insights.
INSERT INTO source_insights (source_id, collection_id, transformation_id, insight_type, content)
SELECT s.id, s.collection_id, (SELECT id FROM transformations WHERE builtin = 'study_guide'), 'Study guide', s.summary
FROM sources s WHERE s.summary IS NOT NULL AND s.summary != '';

-- A passage can now belong to a note or an insight instead of a source, so
-- that these can be searched too. SQLite cannot relax a column in place, so
-- the table is rebuilt with the same ids.
DROP TRIGGER chunks_ai;
DROP TRIGGER chunks_ad;
ALTER TABLE chunks RENAME TO chunks_old;
CREATE TABLE chunks (
    id            INTEGER PRIMARY KEY,
    source_id     INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    note_id       INTEGER REFERENCES notes(id) ON DELETE CASCADE,
    insight_id    INTEGER REFERENCES source_insights(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL,
    ord           INTEGER NOT NULL,
    page          INTEGER,
    start_sec     REAL,
    text          TEXT NOT NULL,
    embedding     BLOB
);
INSERT INTO chunks (id, source_id, collection_id, ord, page, start_sec, text, embedding)
SELECT id, source_id, collection_id, ord, page, start_sec, text, embedding FROM chunks_old;
DROP TABLE chunks_old;
CREATE INDEX chunks_collection ON chunks(collection_id);
CREATE INDEX chunks_source ON chunks(source_id, ord);
CREATE INDEX chunks_note ON chunks(note_id);
CREATE INDEX chunks_insight ON chunks(insight_id);
CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
INSERT INTO chunks_fts(chunks_fts) VALUES ('rebuild');
