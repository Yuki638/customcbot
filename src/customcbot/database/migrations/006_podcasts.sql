-- Podcasts: who speaks, what kind of episode, and the episodes made.

CREATE TABLE speaker_profiles (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    speakers    TEXT NOT NULL,          -- JSON list of 1 to 4 {name, voice, role}
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE episode_profiles (
    id                 INTEGER PRIMARY KEY,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL DEFAULT '',
    speaker_profile_id INTEGER REFERENCES speaker_profiles(id) ON DELETE SET NULL,
    briefing           TEXT NOT NULL,   -- what the episode should be like
    segments           INTEGER NOT NULL DEFAULT 3,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE podcast_episodes (
    id                 INTEGER PRIMARY KEY,
    collection_id      INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    episode_profile_id INTEGER REFERENCES episode_profiles(id) ON DELETE SET NULL,
    title              TEXT NOT NULL,
    briefing           TEXT NOT NULL DEFAULT '',
    outline            TEXT,            -- JSON
    transcript         TEXT,            -- JSON list of {speaker, text}
    audio_path         TEXT,            -- relative to the podcasts folder
    duration_sec       REAL,
    status             TEXT NOT NULL DEFAULT 'queued',   -- queued | working | ready | error
    error              TEXT,
    job_id             INTEGER,
    created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX podcast_episodes_collection ON podcast_episodes(collection_id);

INSERT INTO speaker_profiles (name, description, speakers) VALUES
    ('Two hosts', 'A tutor who explains and a student who asks.',
     '[{"name": "Maya", "voice": "af_heart", "role": "a friendly tutor who explains things clearly"}, {"name": "Daniel", "voice": "am_michael", "role": "a curious student who asks the questions a learner would ask"}]'),
    ('One narrator', 'A single calm voice.',
     '[{"name": "Maya", "voice": "af_heart", "role": "a calm narrator who explains things clearly"}]'),
    ('Two hosts (British)', 'The same pair with British voices.',
     '[{"name": "Emma", "voice": "bf_emma", "role": "a friendly tutor who explains things clearly"}, {"name": "George", "voice": "bm_george", "role": "a curious student who asks the questions a learner would ask"}]');

INSERT INTO episode_profiles (name, description, speaker_profile_id, briefing, segments) VALUES
    ('Study recap', 'A conversation that walks through the key ideas.', 1,
     'A friendly recap that walks through the key ideas of the material, so a student can revise by listening.', 3),
    ('Quick overview', 'A short summary read by one voice.', 2,
     'A short, clear overview of what the material covers and why it matters.', 2),
    ('Exam drill', 'Questions and answers, as practice before a test.', 1,
     'Practice for an exam: one host asks a question about the material, the other answers it and explains why.', 3);
