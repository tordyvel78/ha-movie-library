from flask import Flask, request, jsonify, render_template_string, redirect, url_for
import sqlite3
import os

app = Flask(__name__)
DB_PATH = "/config/movies.db"

HTML = """
<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Movie Library</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 16px; }
    h1 { margin-top: 0; }
    form { display: grid; gap: 10px; max-width: 420px; }
    input, select, button { padding: 10px; font-size: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 18px; }
    th, td { border-bottom: 1px solid #3333; padding: 10px; text-align: left; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    .row > * { flex: 1; min-width: 120px; }
  </style>
</head>
<body>
  <h1>Movie Library</h1>

  <form method="post" action="/add">
    <div class="row">
      <input name="title" placeholder="Titel" required>
      <input name="year" placeholder="År" type="number" min="1888" max="2100">
    </div>
    <select name="format" required>
      <option value="Blu-ray">Blu-ray</option>
      <option value="4K UHD">4K UHD</option>
      <option value="DVD">DVD</option>
    </select>
    <button type="submit">Lägg till</button>
  </form>

  <table>
    <thead>
      <tr><th>Titel</th><th>Format</th><th>År</th></tr>
    </thead>
    <tbody>
      {% for m in movies %}
        <tr>
          <td>{{m[1]}}</td>
          <td>{{m[2]}}</td>
          <td>{{m[3] if m[3] else ""}}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</body>
</html>
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            format TEXT NOT NULL,
            year INTEGER
        )
    """)
    conn.commit()
    conn.close()

def get_all_movies():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, format, year FROM movies ORDER BY title COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return rows

@app.route("/")
def home():
    return render_template_string(HTML, movies=get_all_movies())

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    fmt = request.form.get("format", "").strip()
    year = request.form.get("year", "").strip()
    year_val = int(year) if year.isdigit() else None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO movies (title, format, year) VALUES (?, ?, ?)",
              (title, fmt, year_val))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))

# API (valfritt men bra att ha kvar)
@app.route("/api/movies", methods=["GET"])
def api_movies():
    return jsonify(get_all_movies())

if __name__ == "__main__":
    os.makedirs("/config", exist_ok=True)
    init_db()
    app.run(host="0.0.0.0", port=5000)
