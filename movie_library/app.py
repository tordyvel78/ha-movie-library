from flask import Flask, request, jsonify
import sqlite3
import os

app = Flask(__name__)
DB_PATH = "/config/movies.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            format TEXT,
            year INTEGER
        )
    """)
    conn.commit()
    conn.close()

@app.route("/")
def home():
    return "Movie Library running"

@app.route("/movies", methods=["GET"])
def get_movies():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM movies")
    rows = c.fetchall()
    conn.close()
    return jsonify(rows)

@app.route("/movies", methods=["POST"])
def add_movie():
    data = request.json
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO movies (title, format, year) VALUES (?, ?, ?)",
              (data["title"], data["format"], data["year"]))
    conn.commit()
    conn.close()
    return {"status": "added"}

if __name__ == "__main__":
    os.makedirs("/config", exist_ok=True)
    init_db()
    app.run(host="0.0.0.0", port=5000)
