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

@app.get("/api/movies")
def api_movies():
    rows = get_all_movies()
    out = []
    for m in rows:
        out.append({
            "id": m[0],
            "title": m[1],
            "format": m[2],
            "year": m[3],
            "poster_file": m[4],
            "vote": m[5],
            "added_at": m[6],
            "watched": m[7],
        })
    return jsonify({"movies": out})

@app.route("/poster/<path:filename>")
def poster(filename: str):
    posters_dir = "/config/movie_library/posters"  # str, inte Path
    resp = send_from_directory(posters_dir, filename)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

HTML = """
<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Movie Library</title>
  
  <style>
    body{
      font-family: system-ui, sans-serif;
      margin:16px;
    
      background:
        radial-gradient(circle at 20% 20%, #1e2430 0%, #0f131a 60%),
        linear-gradient(180deg, #111 0%, #0b0f15 100%);
      color:#e6e6e6;
    }
    
    form { display: grid; gap: 10px; max-width: 520px; }
    input, select, button { padding: 10px; font-size: 16px; }
    table { border-collapse: collapse; width: 100%; margin-top: 18px; }
    th, td { border-bottom: 1px solid #3333; padding: 10px; text-align: left; }
    .row { display:flex; gap:10px; flex-wrap:wrap; }
    .row > * { flex:1; min-width:160px; }
    .results { margin-top: 10px; }
    .card{
      border:1px solid rgba(255,255,255,.08);
      border-radius:10px;
      padding:10px;
      margin:8px 0;
      background: rgba(255,255,255,.03);
    }
    
    .muted { opacity: .7; }
    .err { color: #b00020; font-weight: 600; }
    
    .grid {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: 14px;
    }
    
    .tile{
      border:1px solid rgba(255,255,255,.08);
      border-radius:12px;
      padding:10px;
      background: rgba(255,255,255,.04);
      backdrop-filter: blur(2px);
      transition: transform .12s ease, box-shadow .12s ease;
    }
    
    .tile[data-watched="1"] {
      opacity: 0.65;
    }
    
    .tile[data-watched="1"] .posterwrap::after {
      content: "✓ SETT";
      position: absolute;
      left: 8px;
      bottom: 8px;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      background: rgba(0,0,0,.65);
      color: #7CFF9B;
      border: 1px solid rgba(124,255,155,.35);
    }
    
    .tile:hover{
      transform: translateY(-3px);
      box-shadow: 0 8px 24px rgba(0,0,0,.35);
    }
    
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
      border:1px solid rgba(255,0,0,.2);
      color:#ff8b8b;
      background:#2a1215;
      font-size:14px;
      cursor:pointer;
    }
    .danger:hover{
      border-color:#b00020;
      color:#b00020;
    }
    .linkbtn{
      display:inline-block;
      padding:10px 12px;
      border:1px solid #3333;
      border-radius:12px;
      text-decoration:none;
      color:inherit;
    }
    .linkbtn:hover{ border-color:#3336; }
    
    .topbar{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      margin: 10px 0 14px 0;
    }
    .left{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
    
    .search{
      background:#1b212c;
      color:#fff;
      border:1px solid rgba(255,255,255,.08);
    }
    
    .search:focus{ outline:none; border-color:#3336; }
    
    .iconbtn{
      width:42px; height:42px;
      border-radius:999px;
      border:1px solid rgba(255,255,255,.08);
      background:#1b212c;
      color:#fff;
      font-size:26px;
      line-height: 0;
      cursor:pointer;
    }
    .iconbtn:hover{ border-color:#3336; }
    .iconbtn.edit{ font-size:20px; }
    
    .modal{ display:none; }
    .modal.open{ display:block; }
    
    .modal-backdrop{
      position:fixed;
      inset:0;
      background: rgba(0,0,0,.45);
      z-index: 9998;     /* VIKTIGT */
    }
    
    .modal-card{
      position:fixed;
      top: 72px;
      left: 50%;
      transform: translateX(-50%);
      width: min(720px, calc(100vw - 24px));
      max-height: calc(100vh - 100px);
      overflow:auto;
    
      background:#1b212c;
      border-radius:16px;
      border:1px solid rgba(255,255,255,.08);
      color:#eaeaea;
      box-shadow: 0 12px 40px rgba(0,0,0,.35);
      padding: 14px;
    
      z-index: 9999;     /* VIKTIGT */
    }
    
    .modal-head{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:10px;
      margin-bottom: 10px;
    }
    
    .iconbtn.small{
      width:36px; height:36px;
      font-size:22px;
    }
    
    .mm_postercol{
      width:300px;
      flex:0 0 260px;
    }
    
    @media (max-width: 520px){
      .mm_postercol{
        width: 100%;
        flex: 1 1 100%;
        max-width: 320px;
      }
    }
    
    .section{
      margin-top: 14px;
      padding: 14px;
      border-radius: 14px;
      border:1px solid rgba(255,255,255,.08);
      background: rgba(255,255,255,.03);
    }
    
    .section-title{
      font-weight:700;
      font-size:14px;
      letter-spacing:.4px;
      text-transform:uppercase;
      opacity:.7;
      margin-bottom:10px;
    }
    
    .tmdb-search-row{
      display:flex;
      gap:8px;
    }
    
    .tmdb-search-row input{
      flex:1;
    }
    
    .manual{
      margin-top:18px;
      border-color: rgba(0,150,255,.15);
      background: rgba(0,150,255,.04);
    }
    
    .format-group{
      display:flex;
      gap:16px;
      margin-top:6px;
    }
    
    .chk{
      display:flex;
      align-items:center;
      gap:6px;
      font-size:14px;
    }
    
    .primary-btn{
      margin-top:12px;
      width:100%;
      padding:10px;
      border-radius:12px;
      border:1px solid rgba(255,255,255,.15);
      background:#2a3342;
      color:#fff;
      font-weight:600;
      cursor:pointer;
    }
    
    .primary-btn:hover{
      border-color:#4a90ff;
    }
    
    .format-bar{
      margin: 12px 0 4px 0;
      padding: 10px 14px;
      border-radius: 999px;
      border:1px solid rgba(255,255,255,.08);
      background: rgba(255,255,255,.05);
      display:flex;
      justify-content:center;
    }
    
    .format-group{
      display:flex;
      gap:22px;
    }

    .toolbar { display:flex; gap:.6rem; align-items:center; margin:.75rem 0; flex-wrap:wrap; }
    .toolbar__label { opacity:.8; font-size:.95rem; }
    .toolbar__select {
      padding: .45rem .6rem;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,.12);
    
      background: rgba(20,20,20,.85);
      color: #fff;
    
      font-size: .95rem;
      outline: none;
      cursor: pointer;
    
      appearance: none;
      -webkit-appearance: none;
      -moz-appearance: none;
    }
    .toolbar__button { padding:.45rem .6rem; border-radius:10px; border:1px solid rgba(255,255,255,.12);
      background:rgba(0,0,0,.18); color:inherit;
    }
    .toolbar__button { cursor:pointer; }
    
    .watched-btn {
      position: absolute;
      top: 6px;
      right: 6px;
      background: rgba(0,0,0,.6);
      border: none;
      color: white;
      font-size: 16px;
      padding: 4px 6px;
      border-radius: 6px;
      cursor: pointer;
    }
    
  </style>
  
</head>
<body>
  <h1>Movie Library</h1>
  
  <div class="topbar">
    <div class="left">
      <input id="lib_search" class="search" placeholder="Sök i samlingen…" autocomplete="off">
    </div>
  
    <div class="right" style="display:flex; gap:10px; align-items:center;">
      {% if manage_mode %}
        <a class="linkbtn" href="./">Tillbaka</a>
      {% else %}
        <a class="iconbtn edit" href="manage" aria-label="Hantera samling" title="Hantera samling" style="text-align:center; text-decoration:none; display:flex; align-items:center; justify-content:center;">
          ✎
        </a>
  
        <button type="button" class="iconbtn" onclick="openAddModal()" aria-label="Lägg till film" title="Lägg till film">
          +
        </button>
      {% endif %}
    </div>
  </div>  
  
  <div id="search_hint" class="muted" style="margin-top:8px; display:none;"></div>
  

  {% if error %}
    <div class="err">{{error}}</div>
  {% endif %}

  

  <div id="addModal" class="modal" aria-hidden="true">
    <div class="modal-backdrop" onclick="closeAddModal()"></div>
  
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Lägg till film">
      <div class="modal-head">
        <strong>Lägg till film</strong>
        <button type="button" class="iconbtn small" onclick="closeAddModal()" aria-label="Stäng">×</button>
      </div>
  
      <form method="post" action="add" onsubmit="return addMovie(this);">

        <!-- ================= TMDB-SEKTION ================= -->
        <div class="section">
          <div class="section-title">Sök på TMDB</div>
        
          <div class="tmdb-search-row">
            <input id="tmdb_query"
                   placeholder="Filmtitel…"
                   autocomplete="off">
        
            <button type="button" onclick="tmdbSearch()">Sök</button>
          </div>
        
          <div id="tmdb_results" class="results"></div>
        </div>
        
        
        <!-- ================= FORMAT (GEMENSAM) ================= -->
        <div class="format-bar">
          <div class="format-group">
            <label class="chk">
              <input type="checkbox" name="format" value="Blu-ray" checked>
              Blu-ray
            </label>
        
            <label class="chk">
              <input type="checkbox" name="format" value="4K UHD">
              4K UHD
            </label>
        
            <label class="chk">
              <input type="checkbox" name="format" value="DVD">
              DVD
            </label>
          </div>
        </div>
        
        
        <!-- ================= MANUELL SEKTION ================= -->
        <div class="section manual">
          <div class="section-title">Manuell inläggning</div>
        
          <div class="row">
            <input name="title" placeholder="Titel" required>
            <input name="year" placeholder="År" type="number" min="1888" max="2100">
          </div>
        
          <input type="hidden" id="tmdb_id" name="tmdb_id">
        
          <button type="submit" class="primary-btn">
            Lägg till manuellt
          </button>
        </div>
        
      
      </form>
      
    </div>
  </div>
  
  <div id="movieModal" class="modal" aria-hidden="true">
    <div class="modal-backdrop" onclick="closeMovieModal()"></div>
  
    <div class="modal-card" role="dialog" aria-modal="true" aria-label="Filmdetaljer">
      <div class="modal-head">
        <strong id="mm_title">Film</strong>
        <button type="button" class="iconbtn small" onclick="closeMovieModal()" aria-label="Stäng">×</button>
      </div>
  
      <div style="display:flex; gap:14px; align-items:flex-start; flex-wrap:wrap;">
        <div class="mm_postercol">
          <img id="mm_poster" src="" alt="" style="width:100%; border-radius:12px; display:none;">
          <div id="mm_poster_ph" class="poster_placeholder" style="display:block; width:100%;"></div>
        </div>
  
        <div style="flex:1; min-width:240px;">
          <div class="muted" id="mm_meta" style="margin-bottom:8px;"></div>
          <div id="mm_overview" style="line-height:1.45;"></div>
  
          <div id="mm_genres" class="muted" style="margin-top:10px;"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="toolbar">
    <label class="toolbar__label" for="sort_by">Sortera:</label>

    <select id="sort_by" class="toolbar__select">
      <option value="title">Namn</option>
      <option value="year">År</option>
      <option value="rating">Betyg</option>
      <option value="added_at">Senast inlagd</option>
    </select>

    <button id="sort_dir" class="toolbar__button" type="button" title="Växla ordning">
      A→Ö
    </button>
  </div>
  
  <div class="grid">
    {% for m in movies %}
      <div class="tile"
           data-id="{{m[0]}}"
           data-title="{{ (m[1] or '') }}"
           data-year="{{ (m[3] or '') }}"
           data-vote="{{ (m[5] if m[5] is not none else '') }}"
           data-added="{{ (m[6] or '') }}"
           data-watched="{{ m[7] }}"
           data-format="{{ (m[2] or '')|lower }}">
        <div class="posterwrap">
          {% if m[4] %}
            <img
              src="poster/{{m[4]}}"
              alt=""
              loading="lazy"
              decoding="async"
              fetchpriority="low"
            >
          {% else %}
            <div class="poster_placeholder"></div>
          {% endif %}
  
          {% if m[5] is not none %}
            <div class="rating">★ {{ "%.1f"|format(m[5]) }}</div>
          {% endif %}
          {% if manage_mode %}
            <button class="watched-btn"
                    onclick="toggleWatched({{m[0]}}, this); event.stopPropagation();"
                    title="Markera som sett">
              👁
            </button>
          {% endif %}
        </div>
  
        <div class="title">{{m[1]}}</div>
        <div class="meta">
          <span class="badge">{{m[2]}}</span>
          <span class="muted">{{m[3] or ""}}</span>
        </div>
        
        {% if manage_mode %}
          <form onsubmit="return deleteMovie(this);"
                method="post"
                action="delete/{{m[0]}}"
                style="margin-top:8px;">
            <button type="submit" class="danger">Ta bort</button>
          </form>
        {% endif %}
               
      </div>
    {% endfor %}
  </div>

<script>
async function tmdbSearch() {
  const q = document.getElementById("tmdb_query").value.trim();
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



async function addFromTmdb(id) {

  // Hämta markerade checkbox-format
  const checked = Array.from(
    document.querySelectorAll('input[name="format"]:checked')
  ).map(cb => cb.value);

  const fmt = checked.length ? checked.join(", ") : "Blu-ray";

  const res = await fetch(`tmdb/add/${id}`, {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body: new URLSearchParams({format: fmt})
  });

  const data = await res.json();

  if (data.status === "added") {

    await refreshLibraryGrid();

    const box = document.getElementById("tmdb_results");
    if (box){
      const el = document.createElement("div");
      el.className = "muted";
      el.style.margin = "6px 0";
      el.textContent = "Tillagd ✓";
      box.prepend(el);
      setTimeout(() => el.remove(), 900);
    }

  } else if (data.status === "duplicate") {

    document.getElementById("tmdb_results").innerHTML =
      `<div class="muted">Finns redan i samlingen (dublett stoppad).</div>`;

  } else {

    document.getElementById("tmdb_results").innerHTML =
      `<div class="err">${data.error || "Fel vid tillägg"}</div>`;

  }
}


function wireEnterToSearch() {
  const title = document.getElementById("tmdb_query");
  title.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();   // stoppar form submit
      tmdbSearch();
    }
  });
}
document.addEventListener("DOMContentLoaded", wireEnterToSearch);

async function deleteMovie(formEl) {
  const ok = confirm("Ta bort filmen?");
  if (!ok) return false;

  try {
    const res = await fetch(formEl.action, { method: "POST" });
    if (res.ok) {
      // Ladda om nuvarande sida (med rätt ingress-prefix)
      await refreshLibraryGrid();
    } else {
      alert("Kunde inte ta bort (HTTP " + res.status + ").");
    }
  } catch (e) {
    alert("Nätverksfel vid borttagning.");
  }
  return false; // stoppa normal form-submit/redirect
}

function norm(s){
  return (s || "")
    .toString()
    .toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "") // åäö-hantering-ish
    .trim();
}

// Enkel fuzzy: matcha query som "subsequence" i text och ge score
function fuzzyScore(text, query){
  text = norm(text);
  query = norm(query);
  if (!query) return 1;

  let ti = 0;
  let score = 0;
  let streak = 0;

  for (let qi = 0; qi < query.length; qi++){
    const qc = query[qi];
    let found = false;
    while (ti < text.length){
      if (text[ti] === qc){
        found = true;
        streak += 1;
        score += 10 * streak; // belöna sammanhängande träffar
        ti += 1;
        break;
      } else {
        streak = 0;
        ti += 1;
      }
    }
    if (!found) return 0;
  }

  // Bonus om query är prefix i något ord
  if (text.split(/\s+/).some(w => w.startsWith(query))) score += 30;

  return score;
}

function filterLibrary(){
  const q = document.getElementById("lib_search").value;
  const tiles = Array.from(document.querySelectorAll(".grid .tile"));
  const hint = document.getElementById("search_hint");

  if (!q.trim()){
    tiles.forEach(t => { t.style.display = ""; t.style.order = ""; });
    hint.style.display = "none";
    return;
  }

  let shown = 0;

  tiles.forEach(t => {
    const title = t.dataset.title || "";
    const year = t.dataset.year || "";
    const fmt  = t.dataset.format || "";

    const hay = `${title} ${year} ${fmt}`;
    const s = fuzzyScore(hay, q);

    if (s > 0){
      t.style.display = "";
      // sortera “bäst match” först via flex/grid order
      t.style.order = String(1000000 - s);
      shown += 1;
    } else {
      t.style.display = "none";
      t.style.order = "";
    }
  });

  hint.style.display = "";
  hint.textContent = `${shown} träff${shown===1?"":"ar"} i samlingen`;
}

function wireLibrarySearch(){
  const inp = document.getElementById("lib_search");
  if (!inp) return;
  inp.addEventListener("input", filterLibrary);
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { inp.value = ""; filterLibrary(); }
  });
}
document.addEventListener("DOMContentLoaded", wireLibrarySearch);

function openAddModal(){
  const m = document.getElementById("addModal");
  m.classList.add("open");
  m.setAttribute("aria-hidden", "false");

  // ===== Rensa TMDB-sök =====
  const tmdbInput = document.getElementById("tmdb_query");
  if (tmdbInput) tmdbInput.value = "";

  const results = document.getElementById("tmdb_results");
  if (results) results.innerHTML = "";

  // ===== Rensa hidden tmdb_id =====
  const tmdbId = document.getElementById("tmdb_id");
  if (tmdbId) tmdbId.value = "";

  // ===== Rensa manuella fält =====
  const manualTitle = document.querySelector('.manual input[name="title"]');
  const manualYear  = document.querySelector('.manual input[name="year"]');

  if (manualTitle) manualTitle.value = "";
  if (manualYear) manualYear.value = "";

  // ===== Återställ checkboxar =====
  const checkboxes = document.querySelectorAll('input[name="format"]');
  checkboxes.forEach(cb => cb.checked = false);

  const blu = document.querySelector('input[name="format"][value="Blu-ray"]');
  if (blu) blu.checked = true;

  // Fokus på TMDB-sökfält
  setTimeout(() => {
    if (tmdbInput) tmdbInput.focus();
  }, 0);
}


function closeAddModal(){
  const m = document.getElementById("addModal");
  m.classList.remove("open");
  m.setAttribute("aria-hidden", "true");
}

async function addMovie(formEl){
  try{
    const res = await fetch(formEl.action, {
      method: "POST",
      body: new FormData(formEl)
    });

    if (res.ok){

      // Uppdatera bara griden
      await refreshLibraryGrid();

      // Visa liten tillagd-feedback
      const box = document.getElementById("tmdb_results");
      if (box){
        const el = document.createElement("div");
        el.className = "muted";
        el.style.margin = "6px 0";
        el.textContent = "Tillagd ✓";
        box.prepend(el);
        setTimeout(() => el.remove(), 900);
      }

    } else {
      alert("Kunde inte lägga till (HTTP " + res.status + ").");
    }
  } catch(e){
    alert("Nätverksfel vid tillägg.");
  }
  return false;
}

function escapeHtml(s){
  return (s ?? "").toString()
    .replaceAll("&","&amp;")
    .replaceAll("<","&lt;")
    .replaceAll(">","&gt;")
    .replaceAll('"',"&quot;")
    .replaceAll("'","&#39;");
}

function tileHtml(m, manageMode){
  const id = m.id;
  const title = m.title || "";
  const year = m.year ?? "";
  const fmt = (m.format || "");
  const fmtLower = fmt.toLowerCase();
  const vote = (m.vote === null || m.vote === undefined) ? null : Number(m.vote);
  const poster = m.poster_file ? `poster/${encodeURIComponent(m.poster_file)}` : "";
  const watched = (m.watched === 1 || m.watched === "1") ? "1" : "0";

  // Obs: data-title sparas original, vi normaliserar vid sort/filter i JS
  return `
    <div class="tile"
         data-id="${id}"
         data-title="${escapeHtml(title)}"
         data-year="${escapeHtml(year)}"
         data-vote="${vote == null ? "" : vote}"
         data-added="${escapeHtml(m.added_at || "")}"
         data-watched="${watched}"
         data-format="${escapeHtml(fmtLower)}">
      <div class="posterwrap">
        ${poster
          ? `<img src="${poster}" alt="" loading="lazy" decoding="async" fetchpriority="low">`
          : `<div class="poster placeholder"></div>`
        }
        ${vote != null ? `<div class="rating">★ ${vote.toFixed(1)}</div>` : ``}
        ${manageMode ? `
          <button class="watched-btn"
                  onclick="toggleWatched(${id}, this); event.stopPropagation();"
                  title="Markera som sett">👁</button>
        ` : ``}
      </div>

      <div class="title">${escapeHtml(title)}</div>
      <div class="meta">
        <span class="badge">${escapeHtml(fmt)}</span>
        <span class="muted">${escapeHtml(year)}</span>
      </div>

      ${manageMode ? `
        <form method="post" action="delete/${id}" onsubmit="return confirm('Ta bort?');">
          <button class="danger" type="submit">Ta bort</button>
        </form>
      ` : ``}
    </div>
  `;
}

async function refreshLibraryGrid(){
  const curGrid = document.querySelector(".grid");
  if (!curGrid) return;

  // manage_mode finns redan i templaten som Jinja-boolean
  const manageMode = {{ 'true' if manage_mode else 'false' }};

  const res = await fetch("api/movies", { cache: "no-store" });
  if (!res.ok) return;

  const data = await res.json();
  const movies = Array.isArray(data.movies) ? data.movies : [];

  // Bygg HTML i minnet och byt i ett svep
  curGrid.innerHTML = movies.map(m => tileHtml(m, manageMode)).join("");

  // Re-wire tile klick (öppna modal) + behåll din filter/sort om du vill
  wireTileClicks();

  // Om du använder sorteringen som sätter order: kör om den efter refresh
  if (typeof sortGridTiles === "function") sortGridTiles();

  // Om du använder filterLibrary() (sök i samlingen): applicera igen
  if (typeof filterLibrary === "function") filterLibrary();
}

function openMovieModal(){
  const m = document.getElementById("movieModal");
  m.classList.add("open");
  m.setAttribute("aria-hidden", "false");
}
function closeMovieModal(){
  const m = document.getElementById("movieModal");
  m.classList.remove("open");
  m.setAttribute("aria-hidden", "true");
}

async function showMovieDetails(movieRowId){
  openMovieModal();

  // reset UI
  document.getElementById("mm_title").textContent = "Laddar…";
  document.getElementById("mm_meta").textContent = "";
  document.getElementById("mm_overview").textContent = "";
  document.getElementById("mm_genres").textContent = "";

  const img = document.getElementById("mm_poster");
  const ph  = document.getElementById("mm_poster_ph");
  img.style.display = "none";
  ph.style.display = "block";

  const res = await fetch(`movie/${movieRowId}`, { cache: "no-store" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok){
    document.getElementById("mm_title").textContent = "Kunde inte ladda";
    document.getElementById("mm_overview").textContent = data.error || "Fel";
    return;
  }

  document.getElementById("mm_title").textContent = data.title || "Film";

  const bits = [];
  if (data.year) bits.push(data.year);
  if (data.format) bits.push(data.format);
  if (data.runtime) bits.push(`${data.runtime} min`);
  if (data.vote != null) bits.push(`⭐ ${Number(data.vote).toFixed(1)}`);
  document.getElementById("mm_meta").textContent = bits.join(" • ");

  const ov = data.overview || "Ingen handling hittades.";
  document.getElementById("mm_overview").textContent = ov;

  if (data.genres && data.genres.length){
    document.getElementById("mm_genres").textContent = data.genres.join(" / ");
  }

  if (data.poster_local){
    img.src = data.poster_local;
    img.onload = () => { ph.style.display = "none"; img.style.display = "block"; };
    img.onerror = () => { img.style.display = "none"; ph.style.display = "block"; };
  }
}

async function toggleWatched(id, btn) {
  await fetch(`toggle_watched/${id}`, {
    method: "POST"
  });

  const tile = btn.closest(".tile");
  const current = tile.dataset.watched === "1" ? "1" : "0";
  const next = current === "1" ? "0" : "1";

  tile.dataset.watched = next;
}

function wireTileClicks(){
  document.querySelectorAll(".grid .tile").forEach(tile => {
    tile.addEventListener("click", (e) => {
      if (e.target && e.target.closest && e.target.closest("form")) return;
      if (e.target && e.target.closest && e.target.closest(".watched-btn")) return;

      const id = tile.dataset.id;
      if (id) showMovieDetails(id);
    });
  });
}

document.addEventListener("DOMContentLoaded", wireTileClicks);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape"){
    const add = document.getElementById("addModal");
    const mov = document.getElementById("movieModal");

    if (add && add.classList.contains("open")) closeAddModal();
    if (mov && mov.classList.contains("open")) closeMovieModal();
  }
});

(function(){
  const collatorSV = new Intl.Collator("sv", { sensitivity: "base" });

  function getSortState() {
    return {
      by: localStorage.getItem("ml_sort_by") || "title",
      dir: localStorage.getItem("ml_sort_dir") || "asc",
    };
  }

  function setSortState(by, dir) {
    localStorage.setItem("ml_sort_by", by);
    localStorage.setItem("ml_sort_dir", dir);
  }

  function normTitle(s){
    return (s || "").toString().trim();
  }

  function num(v, fallback){
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
  }

  function timeMs(v){
    if (!v) return 0;
    const t = Date.parse(v);
    return Number.isFinite(t) ? t : 0;
  }

  function updateSortUI(by, dir){
    const sel = document.getElementById("sort_by");
    const btn = document.getElementById("sort_dir");
    if (!sel || !btn) return;

    sel.value = by;
    btn.textContent =
      by === "title"
        ? (dir === "asc" ? "A→Ö" : "Ö→A")
        : (dir === "asc" ? "↑" : "↓");
  }

  function sortGridTiles(){
    const { by, dir } = getSortState();
    const sign = dir === "desc" ? -1 : 1;

    const tiles = Array.from(document.querySelectorAll(".grid .tile"));

    // Om användaren söker i samlingen: låt sök-rankning vinna (din filterLibrary använder order för matchscore)
    const q = (document.getElementById("lib_search")?.value || "").trim();
    if (q) {
      updateSortUI(by, dir);
      return;
    }

    const ranked = tiles.map((t) => {
      const title = normTitle(t.dataset.title);
      const year  = num(t.dataset.year, 0);
      const vote  = (t.dataset.vote === "" || t.dataset.vote == null) ? null : num(t.dataset.vote, 0);
      const added = timeMs(t.dataset.added);

      // primary key
      let key;
      if (by === "title") key = title;
      else if (by === "year") key = year;
      else if (by === "rating") key = (vote == null ? -1 : vote);
      else if (by === "added_at") key = added;
      else key = title;

      return { t, title, year, vote, added, key };
    });

    ranked.sort((a, b) => {
      let diff = 0;

      if (by === "title") {
        diff = collatorSV.compare(a.title, b.title);
      } else if (by === "year") {
        diff = (a.year - b.year);
      } else if (by === "rating") {
        diff = ((a.vote == null ? -1 : a.vote) - (b.vote == null ? -1 : b.vote));
      } else if (by === "added_at") {
        diff = (a.added - b.added);
      }

      // sekundärsort: alltid titel
      if (diff === 0) diff = collatorSV.compare(a.title, b.title);

      return diff * sign;
    });

    // Applicera ordning via CSS order (funkar fint med CSS grid)
    ranked.forEach((x, i) => {
      x.t.style.order = String(i);
    });

    updateSortUI(by, dir);
  }

  function initSort(){
    const sel = document.getElementById("sort_by");
    const btn = document.getElementById("sort_dir");
    if (!sel || !btn) return;

    sel.addEventListener("change", (e) => {
      const { dir } = getSortState();
      setSortState(e.target.value, dir);
      sortGridTiles();
    });

    btn.addEventListener("click", () => {
      const { by, dir } = getSortState();
      setSortState(by, dir === "asc" ? "desc" : "asc");
      sortGridTiles();
    });

    sortGridTiles();
  }

  document.addEventListener("DOMContentLoaded", initSort);

  // Kör om sort efter att du uppdaterat griden (refreshLibraryGrid)
  const _oldRefresh = window.refreshLibraryGrid;
  if (typeof _oldRefresh === "function") {
    window.refreshLibraryGrid = async function(){
      await _oldRefresh();
      sortGridTiles();
    };
  }
})();

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
    
    # Migrera: poster_file + vote
    c.execute("PRAGMA table_info(movies)")
    cols = [row[1] for row in c.fetchall()]
    if "poster_file" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN poster_file TEXT")
    if "vote" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN vote REAL")
    if "added_at" not in cols:
        c.execute("ALTER TABLE movies ADD COLUMN added_at TEXT")
        # Sätt added_at på befintliga rader om du vill:
        c.execute("UPDATE movies SET added_at = COALESCE(added_at, datetime('now'))")
    if "watched" not in cols:
      c.execute("ALTER TABLE movies ADD COLUMN watched INTEGER DEFAULT 0")
    
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
    c.execute("SELECT id, title, format, year, poster_file, vote, added_at, watched FROM movies ORDER BY title COLLATE NOCASE")
    rows = c.fetchall()
    conn.close()
    return rows

@app.post("/toggle_watched/<int:movie_id>")
def toggle_watched(movie_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("UPDATE movies SET watched = CASE watched WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (movie_id,))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})

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

    return ("", 204)


@app.route("/")
def home():
    return render_template_string(
        HTML,
        movies=get_all_movies(),
        error=None,
        prefill_title=None,
        prefill_year=None,
        prefill_format="Blu-ray",
        manage_mode=False
    )

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    formats = request.form.getlist("format")
    fmt = ", ".join(formats) if formats else ""
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
                "INSERT INTO movies (title, format, year, tmdb_id, added_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (title, fmt, year_val, tmdb_val)
            )
        else:
            # Manuell: stoppa dublett via title+year+format-index
            c.execute(
                "INSERT INTO movies (title, format, year, tmdb_id, added_at) VALUES (?, ?, ?, NULL, datetime('now'))",
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
    return ("", 204)

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
    
        # TMDB image CDN
        img_url = f"https://image.tmdb.org/t/p/w185{poster_path}"
        ir = requests.get(img_url, timeout=15)
        if ir.status_code == 200:
            dest.write_bytes(ir.content)
        else:
            poster_file = None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO movies (title, format, year, tmdb_id, poster_file, vote, added_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (title, fmt, year, movie_id, poster_file, vote)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "duplicate"}), 200

    conn.close()
    return jsonify({"status": "added"}), 200

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

@app.route("/manage")
def manage():
    return render_template_string(
        HTML,
        movies=get_all_movies(),
        error=None,
        prefill_title=None,
        prefill_year=None,
        prefill_format="Blu-ray",
        manage_mode=True
    )

@app.route("/movie/<int:movie_row_id>")
def movie_details(movie_row_id: int):
    # Hämta från DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, title, format, year, poster_file, vote, tmdb_id FROM movies WHERE id=?", (movie_row_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Not found"}), 404

    _id, title, fmt, year, poster_file, vote, tmdb_id = row

    payload = {
        "id": _id,
        "title": title,
        "format": fmt,
        "year": year,
        "poster_local": f"poster/{poster_file}" if poster_file else None,
        "vote": vote,
        "tmdb_id": tmdb_id,
        "overview": None,
        "runtime": None,
        "release_date": None,
        "genres": [],
    }

    # Om vi har tmdb_id: hämta extra info från TMDB (cacha)
    if tmdb_id:
        cached = _cache_get(int(tmdb_id))
        if cached is not None and cached.get("details"):
            payload.update(cached["details"])
            return jsonify(payload)

        headers, err = tmdb_headers()
        if not err:
            url = f"https://api.themoviedb.org/3/movie/{int(tmdb_id)}"
            params = {"language": tmdb_language()}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                j = r.json()
                details = {
                    "overview": (j.get("overview") or "").strip() or None,
                    "runtime": j.get("runtime"),
                    "release_date": j.get("release_date"),
                    "genres": [g.get("name") for g in (j.get("genres") or []) if g.get("name")],
                    "vote": j.get("vote_average") if j.get("vote_average") is not None else payload["vote"],
                }
                payload.update(details)
                _cache_set(int(tmdb_id), {"details": details}, ttl_seconds=3600)

    return jsonify(payload)


if __name__ == "__main__":
    os.makedirs("/config", exist_ok=True)
    init_db()
    app.run(host="0.0.0.0", port=5000)
