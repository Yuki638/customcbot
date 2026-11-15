-- A chat can be about one source only.
ALTER TABLE chats ADD COLUMN source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE;
CREATE INDEX chats_source ON chats(source_id);
