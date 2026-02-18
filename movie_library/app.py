import requests
import json

def tmdb_search(api_key, query):
    url = f"https://api.themoviedb.org/3/search/movie?api_key={api_key}&query={query}"
    response = requests.get(url)
    if response.status_code == 200:
        return json.loads(response.text)
    else:
        return None

# Other parts of the original app.py code should follow...