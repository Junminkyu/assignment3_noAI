"""Flask application for collecting human sarcasm labels on Reddit comments."""

import json
import os

from flask import Flask, redirect, render_template, request, session, url_for
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COMMENTS_PATH = os.path.join(BASE_DIR, "data", "sarcasm.json")
DATABASE_URL = os.environ.get("DATABASE_URL")
LABELS = ["Not sarcastic", "Sarcastic"]
COMMENTS_PER_PARTICIPANT = 10
CHECK_OPTIONS = [
    {"value": "channel_name", "label": "/nexus6"},
    {
        "value": "parent_comment",
        "label": "How long does it take to qi from an empty battery? Empty as in when I try to turn on it...",
    },
    {
        "value": "comment",
        "label": "Check out the ampere program, it'll show you your charge rate.",
    },
]
CHECK_QUESTIONS = [
    {
        "name": "channel_name",
        "prompt": "What is the channel name in the image?",
        "answer": "channel_name",
    },
    {
        "name": "parent_comment",
        "prompt": "What is the parent comment in the image?",
        "answer": "parent_comment",
    },
    {
        "name": "comment",
        "prompt": "What is the comment in the image?",
        "answer": "comment",
    },
    {
        "name": "sarcasm_data",
        "prompt": "Which text in the image are you being asked to evaluate for sarcasm?",
        "answer": "comment",
    },
]


def database_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def initialize_database():
    """Create required tables and import the provided Reddit-comment dataset."""
    with open(COMMENTS_PATH, encoding="utf-8") as file:
        comments = json.load(file)

    with database_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                reddit_id TEXT PRIMARY KEY,
                comment TEXT NOT NULL,
                parent_comment TEXT NOT NULL,
                subreddit TEXT NOT NULL,
                label INTEGER NOT NULL
            );
        """)
        connection.execute(
            "ALTER TABLE comments ADD COLUMN IF NOT EXISTS parent_comment TEXT"
        )
        connection.execute(
            "ALTER TABLE comments ADD COLUMN IF NOT EXISTS subreddit TEXT"
        )
        connection.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id SERIAL PRIMARY KEY,
                participant_id TEXT NOT NULL,
                reddit_id TEXT NOT NULL,
                comment_text TEXT NOT NULL,
                parent_comment TEXT NOT NULL,
                subreddit TEXT NOT NULL,
                dataset_label INTEGER NOT NULL,
                selected_label INTEGER NOT NULL,
                born_in_us BOOLEAN NOT NULL
            );
        """)
        connection.execute(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS parent_comment TEXT"
        )
        connection.execute(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS subreddit TEXT"
        )
        connection.execute(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS dataset_label INTEGER"
        )
        connection.execute(
            "ALTER TABLE submissions ADD COLUMN IF NOT EXISTS born_in_us BOOLEAN"
        )
        connection.execute("""
            UPDATE submissions AS submission
            SET
                comment_text = comment.comment,
                parent_comment = comment.parent_comment,
                subreddit = comment.subreddit,
                dataset_label = comment.label
            FROM comments AS comment
            WHERE submission.reddit_id = comment.reddit_id
              AND (
                  submission.parent_comment IS NULL
                  OR submission.subreddit IS NULL
                  OR submission.dataset_label IS NULL
              )
        """)
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO comments (
                    reddit_id, comment, parent_comment, subreddit, label
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (reddit_id) DO UPDATE SET
                    comment = EXCLUDED.comment,
                    parent_comment = EXCLUDED.parent_comment,
                    subreddit = EXCLUDED.subreddit,
                    label = EXCLUDED.label
                """,
                [
                    (
                        str(comment["reddit_id"]),
                        comment["comment"],
                        comment["parent_comment"],
                        comment["subreddit"],
                        int(comment["label"]),
                    )
                    for comment in comments
                ],
            )


@app.get("/")
def home():
    return render_template("home.html")


@app.post("/start")
def start_task():
    participant_id = request.form.get("participant_id", "").strip()
    born_in_us = request.form.get("born_in_us")
    if not participant_id:
        return render_template("home.html", error="Enter a participant ID to begin."), 400
    if born_in_us not in {"yes", "no"}:
        return render_template(
            "home.html",
            participant_id=participant_id,
            error="Select whether you were born in the United States to begin.",
        ), 400

    with database_connection() as connection:
        existing_submission = connection.execute(
            "SELECT 1 FROM submissions WHERE participant_id = %s LIMIT 1",
            (participant_id,),
        ).fetchone()
        if existing_submission:
            return render_template(
                "home.html",
                participant_id=participant_id,
                born_in_us=born_in_us,
                error="This username has already been used. Enter a different username.",
            ), 400

        comments = connection.execute(
            """
            SELECT reddit_id, subreddit, parent_comment, comment, label
            FROM comments
            ORDER BY RANDOM()
            LIMIT %s
            """,
            (COMMENTS_PER_PARTICIPANT,),
        ).fetchall()

    session.clear()
    session["participant_id"] = participant_id
    session["born_in_us"] = born_in_us == "yes"
    session["comments"] = [dict(comment) for comment in comments]
    session["answers"] = {}
    session["index"] = 0
    return redirect(url_for("instructions"))


@app.get("/instructions")
def instructions():
    return render_template("instructions.html")


@app.route("/check", methods=["GET", "POST"])
def check():
    if not session.get("comments"):
        return redirect(url_for("home"))

    selected_answers = {}
    if request.method == "POST":
        selected_answers = {
            question["name"]: request.form.get(question["name"])
            for question in CHECK_QUESTIONS
        }
        if all(
            selected_answers[question["name"]] == question["answer"]
            for question in CHECK_QUESTIONS
        ):
            return redirect(url_for("label_comment"))

        return render_template(
            "check.html",
            questions=CHECK_QUESTIONS,
            options=CHECK_OPTIONS,
            selected_answers=selected_answers,
            error="Please answer all questions correctly before beginning the task.",
        ), 400

    return render_template(
        "check.html",
        questions=CHECK_QUESTIONS,
        options=CHECK_OPTIONS,
        selected_answers=selected_answers,
    )


@app.route("/label", methods=["GET", "POST"])
def label_comment():
    comments = session.get("comments")
    if not comments:
        return redirect(url_for("home"))

    position = session.get("index", 0)
    if request.method == "POST":
        selected_label = request.form.get("selected_label", type=int)
        if selected_label not in range(len(LABELS)):
            return render_template(
                "label.html",
                comment=comments[position],
                position=position,
                labels=LABELS,
                total=COMMENTS_PER_PARTICIPANT,
                error="Select one label before continuing.",
            ), 400

        answers = session["answers"]
        answers[comments[position]["reddit_id"]] = selected_label
        session["answers"] = answers
        position += 1
        session["index"] = position

        if position == len(comments):
            with database_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO submissions (
                            participant_id,
                            reddit_id,
                            comment_text,
                            parent_comment,
                            subreddit,
                            dataset_label,
                            selected_label,
                            born_in_us
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            (
                                session["participant_id"],
                                comment["reddit_id"],
                                comment["comment"],
                                comment["parent_comment"],
                                comment["subreddit"],
                                comment["label"],
                                answers[comment["reddit_id"]],
                                session["born_in_us"],
                            )
                            for comment in comments
                        ],
                    )
            session.clear()
            return redirect(url_for("complete"))

    return render_template(
        "label.html",
        comment=comments[position],
        position=position,
        labels=LABELS,
        total=COMMENTS_PER_PARTICIPANT,
    )


@app.get("/complete")
def complete():
    return render_template("complete.html")


@app.get("/results")
def results():
    with database_connection() as connection:
        submissions = connection.execute(
            """
            SELECT
                participant_id,
                reddit_id,
                subreddit,
                parent_comment,
                comment_text,
                dataset_label,
                selected_label,
                born_in_us
            FROM submissions
            """
        ).fetchall()
    return render_template("results.html", submissions=submissions, labels=LABELS)


initialize_database()


if __name__ == "__main__":
    app.run(debug=True)
