CREATE TABLE IF NOT EXISTS comments (
    reddit_id TEXT PRIMARY KEY,
    comment TEXT NOT NULL,
    parent_comment TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    label INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id SERIAL PRIMARY KEY,
    participant_id TEXT NOT NULL,
    reddit_id TEXT NOT NULL,
    comment_text TEXT NOT NULL,
    parent_comment TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    dataset_label INTEGER NOT NULL,
    selected_label INTEGER NOT NULL,
    native BOOLEAN NOT NULL
);
