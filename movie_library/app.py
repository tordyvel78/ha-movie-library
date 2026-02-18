import os, sqlite3
import requests
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from time import time
from pathlib import Path
from urllib.parse import urlparse
from flask import send_from_directory


app = Flask(__name__)
DB_PATH = "/config/movies.db"

# Home Assistant add-on options hamnar i /data/options.json
OPTIONS_PATH = "/data/options.json"

_tmdb_cache = {}  # movie_id -> (expires_ts, payload)

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

def _cache_get(movie_id: int):
    item = _tmdb_cache.get(movie_id)
    if not item:
        return None
    exp, payload = item
    if time() > exp:
        _tmdb_cache.pop(movie_id, None)
        return None
    return payload

def _cache_set(movie_id: int, payload: dict, ttl_seconds: int = 3600):
    _tmdb_cache[movie_id] = (time() + ttl_seconds, payload)

@app.route("/tmdb/search_enriched")
def tmdb_search_enriched():
    headers, err = tmdb_headers()
    if err:
        return jsonify({"error": err}), 400

    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"results": []})

    # 1) Sök
    url = "https://api.themoviedb.org/3/search/movie"
    params = {"query": q, "language": tmdb_language(), "include_adult": "false"}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    if r.status_code != 200:
        return jsonify({"error": f"TMDB-sök misslyckades ({r.status_code})"}), 502

    j = r.json()
    base_results = j.get("results", [])[:8]  # vi enrichar topp 8

    out = []
    for item in base_results:
        movie_id = item.get("id")
        title = item.get("title") or ""
        original_title = item.get("original_title") or ""
        date = item.get("release_date") or ""
        year = date.split("-")[0] if date else ""
        overview = (item.get("overview") or "").strip()
        vote = item.get("vote_average")
        poster = item.get("poster_path")

        poster_url = f"https://image.tmdb.org/t/p/w185{poster}" if poster else None

        # 2) Runtime kräver detaljer – cacha 1h
        cached = _cache_get(movie_id) if movie_id else None
        runtime = None
        if cached is not None:
            runtime = cached.get("runtime")
        elif movie_id:
            durl = f"https://api.themoviedb.org/3/movie/{movie_id}"
            dparams = {"language": tmdb_language()}
            dr = requests.get(durl, headers=headers, params=dparams, timeout=10)
            if dr.status_code == 200:
                dj = dr.json()
                runtime = dj.get("runtime")
                _cache_set(movie_id, {"runtime": runtime})

        out.append({
            "id": movie_id,
            "title": title,
            "original_title": original_title,
            "year": year,
            "overview": overview,
            "vote": vote,
            "runtime": runtime,     # minuter
            "poster": poster_url
        })

    return jsonify({"results": out})

@app.route("/poster/<path:filename>")
def poster(filename: str):
    posters_dir = Path("/config/movie_library/posters")
    return send_from_directory(posters_dir, filename)

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
    
    .grid {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 14px;
    }
    .tile { border: 1px solid #3333; border-radius: 12px; padding: 10px; }
    .posterwrap { position: relative; }
    .posterwrap img { width: 100%; border-radius: 10px; display:block; }
    .poster_placeholder { width:100%; aspect-ratio: 2/3; background:#0001; border-radius: 10px; }
    .rating{
      position:absolute;
      top:8px; right:8px;
      padding:4px 8px;
      border-radius:999px;
    
      /* bättre kontrast på mörk poster */
      background: rgba(255,255,255,.92);
      color:#111;
      border:1px solid rgba(0,0,0,.25);
      box-shadow: 0 2px 10px rgba(0,0,0,.35);
      font-size:12px;
      font-weight:800;
      letter-spacing:.2px;
    }
    
    .title { margin-top: 8px; font-weight: 700; font-size: 14px; line-height: 1.2; }
    .meta { margin-top: 6px; display:flex; justify-content: space-between; gap:8px; align-items: baseline; }
    .badge { font-size: 12px; padding: 2px 8px; border-radius: 999px; border:1px solid #3333; }
    
    .danger{
      width:100%;
      padding:8px 10px;
      border-radius:10px;
      border:1px solid #3333;
      background:#fff;
      font-size:14px;
      cursor:pointer;
    }
    .danger:hover{
      border-color:#b00020;
      color:#b00020;
    }
    
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

  <div class="grid">
    {% for m in movies %}
      <div class="tile">
        <div class="posterwrap">
          {% if m[4] %}
            <img src="poster/{{m[4]}}" alt="">
          {% else %}
            <div class="poster_placeholder"></div>
          {% endif %}
  
          {% if m[5] %}
            <div class="rating">★ {{ "%.1f"|format(m[5]) }}</div>
          {% endif %}
        </div>
  
        <div class="title">{{m[1]}}</div>
        <div class="meta">
          <span class="badge">{{m[2]}}</span>
          <span class="muted">{{m[3] or ""}}</span>
        </div>
        <form method="post"
              action="/delete/{{m[0]}}"
              onsubmit="return confirm('Ta bort {{m[1]}}?');"
              style="margin-top:8px;">
          <button type="submit" class="danger">Ta bort</button>
        </form>        
      </div>
    {% endfor %}
  </div>

<script>
async function tmdbSearch() {
  const q = document.getElementById("title").value.trim();
  const box = document.getElementById("tmdb_results");
  box.innerHTML = "";

  if (!q) {
    box.innerHTML = `<div class="muted">Skriv en titel först.</div>`;
    return;
  }

  box.innerHTML = `<div class="muted">Söker…</div>`;

  const res = await fetch(`tmdb/search_enriched?q=${encodeURIComponent(q)}`);
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    box.innerHTML = `<div class="err">${data.error || "TMDB-fel"}</div>`;
    return;
  }

  const results = data.results || [];
  if (results.length === 0) {
    box.innerHTML = `<div class="muted">Inga träffar på TMDB.</div>`;
    return;
  }

  box.innerHTML = results.map(r => `
    <div class="card" style="display:flex; gap:12px; align-items:flex-start;">
      ${r.poster ? `<img src="${r.poster}" style="width:70px; border-radius:6px;">` : `<div style="width:70px;"></div>`}
      <div style="flex:1;">
        <div style="display:flex; gap:10px; align-items:baseline; flex-wrap:wrap;">
          <strong>${r.title}</strong>
          <span class="muted">${r.year || ""}</span>
          <span class="muted">⭐ ${r.vote ?? "-"}</span>
          <span class="muted">${r.runtime ? `${r.runtime} min` : ""}</span>
        </div>
        ${r.overview ? `<div style="margin-top:6px;">${r.overview.substring(0, 200)}${r.overview.length>200?"…":""}</div>` : ""}
        <div style="margin-top:8px;">
          <button type="button" onclick="addFromTmdb(${r.id})">Lägg till</button>
        </div>
      </div>
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

function wireEnterToSearch() {
  const title = document.getElementById("title");
  title.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();   // stoppar form submit
      tmdbSearch();
    }
  });
}
document.addEventListener("DOMContentLoaded", wireEnterToSearch);

</script>
</body>
</html>
"""

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Migrera: poster_file + vote
    c.execute("PRAGMA table_info(movies)")
    cols = [row[1] for row in c.fetchall()]
    if "poster_file" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN poster_file TEXT")
    if "vote" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN vote REAL")
    

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
    c.execute("SELECT id, title, format, year, poster_file, vote FROM movies ORDER BY title COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return rows

@app.route("/delete/<int:movie_id>", methods=["POST"])
def delete_movie(movie_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Hämta ev posterfil för att kunna ta bort lokalt
    c.execute("SELECT poster_file FROM movies WHERE id=?", (movie_id,))
    row = c.fetchone()

    c.execute("DELETE FROM movies WHERE id=?", (movie_id,))
    conn.commit()
    conn.close()

    # Ta bort posterfil om den finns
    if row and row[0]:
        try:
            posters_dir = Path("/config/movie_library/posters")
            f = posters_dir / row[0]
            if f.exists():
                f.unlink()
        except Exception:
            pass

    return redirect(url_for("home"))


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
    
    vote = j.get("vote_average")  # float
    poster_path = j.get("poster_path")  # t.ex. "/abc123.jpg"
    
    poster_file = None
    if poster_path:
        posters_dir = Path("/config/movie_library/posters")
        posters_dir.mkdir(parents=True, exist_ok=True)
    
        # behåll filändelsen (.jpg/.png) om den finns
        ext = Path(urlparse(poster_path).path).suffix or ".jpg"
        poster_file = f"tmdb_{movie_id}{ext}"
        dest = posters_dir / poster_file
    
        # TMDB image CDN (w342 är bra balans)
        img_url = f"https://image.tmdb.org/t/p/w342{poster_path}"
        ir = requests.get(img_url, timeout=15)
        if ir.status_code == 200:
            dest.write_bytes(ir.content)
        else:
            poster_file = None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO movies (title, format, year, tmdb_id, poster_file, vote) VALUES (?, ?, ?, ?, ?, ?)",
            (title, fmt, year, movie_id, poster_file, vote)
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
    params = {
        "query": q,
        "language": tmdb_language(),
        "include_adult": "false"
    }

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
        overview = item.get("overview") or ""
        vote = item.get("vote_average")
        poster = item.get("poster_path")

        poster_url = (
            f"https://image.tmdb.org/t/p/w185{poster}"
            if poster else None
        )

        out.append({
            "id": item.get("id"),
            "title": title,
            "original_title": original_title,
            "year": year,
            "overview": overview,
            "vote": vote,
            "poster": poster_url
        })

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
