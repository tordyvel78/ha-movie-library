import os, sqlite3
import requests
from flask import Flask, request, jsonify, render_template_string, redirect, url_for

app = Flask(__name__)
DB_PATH = "/config/movies.db"

# Home Assistant add-on options hamnar i /data/options.json
OPTIONS_PATH = "/data/options.json"

def load_options():
    try:
        import json
        with open(OPTIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def tmdb_headers():
    opts = load_options()
    token = (opts.get("tmdb_token") or "").strip()
    if not token:
        return None, "TMDB-token saknas. Lägg in den i appens konfiguration."
    return {"Authorization": f"Bearer {token}"}, None

def tmdb_language():
    opts = load_options()
    return (opts.get("tmdb_language") or "sv-SE").strip()

HTML = """
<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Movie Library</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 16px; }
    form { display: grid; gap: 10px; max-width: 520px; }
    input, select, button { padding: 10px; font-size: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 18px; }
    th, td { border-bottom: 1px solid #3333; padding: 10px; text-align: left; }
    .row { display:flex; gap:10px; flex-wrap:wrap; }
    .row > * { flex:1; min-width:160px; }
    .results { margin-top: 10px; }
    .card { border: 1px solid #3333; border-radius: 10px; padding: 10px; margin: 8px 0; }
    .muted { opacity: .7; }
    .err { color: #b00020; font-weight: 600; }
  </style>
</head>
<body>
  <h1>Movie Library</h1>

  {% if error %}
    <div class="err">{{error}}</div>
  {% endif %}

  <form method="post" action="/add">
    <div class="row">
      <input id="title" name="title" placeholder="Titel" required value="{{prefill_title or ''}}">
      <input id="year" name="year" placeholder="År" type="number" min="1888" max="2100" value="{{prefill_year or ''}}">
      <input type="hidden" id="tmdb_id" name="tmdb_id" value="">
    </div>

    <div class="row">
      <select id="format" name="format" required>
        {% for opt in ["Blu-ray","4K UHD","DVD"] %}
          <option value="{{opt}}" {% if prefill_format==opt %}selected{% endif %}>{{opt}}</option>
        {% endfor %}
      </select>

      <button type="button" onclick="tmdbSearch()">Sök på TMDB</button>
    </div>

    <div id="tmdb_results" class="results"></div>

    <button type="submit">Lägg till</button>
  </form>

  <table>
    <thead><tr><th>Titel</th><th>Format</th><th>År</th></tr></thead>
    <tbody>
      {% for m in movies %}
        <tr><td>{{m[1]}}</td><td>{{m[2]}}</td><td>{{m[3] if m[3] else ""}}</td></tr>
      {% endfor %}
    </tbody>
  </table>

<script>
async function tmdbSearch() {
  const q = document.getElementById("title").value.trim();
  const box = document.getElementById("tmdb_results");
  box.innerHTML = "";
  if (!q) return;

  const res = await fetch(`tmdb/search?q=${encodeURIComponent(q)}`);
  const data = await res.json();

  if (!res.ok) {
    box.innerHTML = `<div class="err">${data.error || "TMDB-fel"}</div>`;
    return;
  }

  if (!data.results || data.results.length === 0) {
    box.innerHTML = `<div class="muted">Inga träffar på TMDB.</div>`;
    return;
  }

  box.innerHTML = data.results.slice(0, 8).map(r => `
    <div class="card">
      <div><strong>${r.title}</strong> <span class="muted">(${r.year || ""})</span></div>
      <div class="muted">${r.original_title || ""}</div>
      <button type="button" onclick="addFromTmdb(${r.id})">Lägg till</button>
    </div>
  `).join("");
}

async function useTmdb(id) {
  const res = await fetch(`tmdb/movie/${id}`);
  const data = await res.json();
  if (!res.ok) return;

  document.getElementById("tmdb_id").value = id;
  document.getElementById("title").value = data.title || "";
  document.getElementById("year").value = data.year || "";
  document.getElementById("tmdb_results").innerHTML = `<div class="muted">Vald: ${data.title} (${data.year||""})</div>`;
}

async function addFromTmdb(id) {
  const fmt = document.getElementById("format").value;
  const res = await fetch(`tmdb/add/${id}`, {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body: new URLSearchParams({format: fmt})
  });

  const data = await res.json();

  if (data.status === "added") {
    document.getElementById("tmdb_results").innerHTML =
      `<div class="muted">Tillagd! Laddar om…</div>`;
    window.location.reload();
  } else if (data.status === "duplicate") {
    document.getElementById("tmdb_results").innerHTML =
      `<div class="muted">Finns redan i samlingen (dublett stoppad).</div>`;
  } else {
    document.getElementById("tmdb_results").innerHTML =
      `<div class="err">${data.error || "Fel vid tillägg"}</div>`;
  }
}

</script>
</body>
</html>
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Skapa tabell om den inte finns (ny installation)
    c.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            format TEXT NOT NULL,
            year INTEGER,
            tmdb_id INTEGER
        )
    """)

    # Migrera: lägg till kolumnen tmdb_id om den saknas
    c.execute("PRAGMA table_info(movies)")
    cols = [row[1] for row in c.fetchall()]
    if "tmdb_id" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN tmdb_id INTEGER")

    # Unikhet på tmdb_id (hindrar dubletter från TMDB)
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_movies_tmdb_id ON movies(tmdb_id)")

    # (Valfritt men bra) Unikhet för manuella inlägg: title+year+format
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_movies_title_year_format ON movies(title, year, format)")

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
    return render_template_string(HTML, movies=get_all_movies(), error=None,
                                  prefill_title=None, prefill_year=None, prefill_format="Blu-ray")

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    fmt = request.form.get("format", "").strip()
    year = request.form.get("year", "").strip()
    tmdb_id = request.form.get("tmdb_id", "").strip()

    year_val = int(year) if year.isdigit() else None
    tmdb_val = int(tmdb_id) if tmdb_id.isdigit() else None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        # Om tmdb_id finns: den är unik via index -> stoppar dublett
        if tmdb_val is not None:
            c.execute(
                "INSERT INTO movies (title, format, year, tmdb_id) VALUES (?, ?, ?, ?)",
                (title, fmt, year_val, tmdb_val)
            )
        else:
            # Manuell: stoppa dublett via title+year+format-index
            c.execute(
                "INSERT INTO movies (title, format, year, tmdb_id) VALUES (?, ?, ?, NULL)",
                (title, fmt, year_val)
            )

        conn.commit()
    except sqlite3.IntegrityError:
        # Dublett – gör inget och visa tillbaka sidan med fel
        conn.close()
        return render_template_string(
            HTML,
            movies=get_all_movies(),
            error="Dublett: filmen finns redan i samlingen.",
            prefill_title=title,
            prefill_year=year_val,
            prefill_format=fmt
        )

    conn.close()
    return redirect(url_for("home"))

@app.route("/tmdb/add/<int:movie_id>", methods=["POST"])
def tmdb_add(movie_id: int):
    headers, err = tmdb_headers()
    if err:
        return jsonify({"error": err}), 400

    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"language": tmdb_language()}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"TMDB-detaljer misslyckades ({r.status_code})"}), 502

    j = r.json()
    title = (j.get("title") or "").strip()
    date = j.get("release_date") or ""
    year = int(date.split("-")[0]) if date and date[:4].isdigit() else None

    fmt = (request.form.get("format") or "Blu-ray").strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO movies (title, format, year, tmdb_id) VALUES (?, ?, ?, ?)",
            (title, fmt, year, movie_id)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "duplicate"}), 200

    conn.close()
    return jsonify({"status": "added"}), 200


@app.route("/tmdb/search")
def tmdb_search():
    headers, err = tmdb_headers()
    if err:
        return jsonify({"error": err}), 400

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})

    url = "https://api.themoviedb.org/3/search/movie"
    params = {"query": q, "language": tmdb_language(), "include_adult": "false"}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"TMDB-sök misslyckades ({r.status_code})"}), 502

    j = r.json()
    out = []
    for item in j.get("results", [])[:20]:
        title = item.get("title") or ""
        original_title = item.get("original_title") or ""
        date = item.get("release_date") or ""
        year = date.split("-")[0] if date else ""
        out.append({"id": item.get("id"), "title": title, "original_title": original_title, "year": year})
    return jsonify({"results": out})

@app.route("/tmdb/movie/<int:movie_id>")
def tmdb_movie(movie_id: int):
    headers, err = tmdb_headers()
    if err:
        return jsonify({"error": err}), 400

    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"language": tmdb_language()}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"TMDB-detaljer misslyckades ({r.status_code})"}), 502

    j = r.json()
    title = j.get("title") or ""
    date = j.get("release_date") or ""
    year = date.split("-")[0] if date else ""
    return jsonify({"title": title, "year": year})

if __name__ == "__main__":
    os.makedirs("/config", exist_ok=True)
    init_db()
    app.run(host="0.0.0.0", port=5000)
