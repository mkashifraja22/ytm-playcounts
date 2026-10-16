# YT Music Play Counts

FastAPI + HTML tool that returns YouTube Music play counts and song, artist and album IDs for any list of artists.

## Run
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload
Open http://localhost:8000

Docker: `docker build -t ytm . && docker run -p 8000:8000 ytm`

## Structure
    app/services.py       ytmusicapi lookup, parsing, caching
    app/main.py           routes: /api/artist, /api/batch, /api/export.csv
    templates/index.html  page
    static/css/style.css  styles
    static/js/app.js      UI logic

## Notes
- There is no official YouTube Music API. This uses the unofficial `ytmusicapi` library, which can break when YouTube changes its web client.
- Play counts are rounded by YouTube Music above 1K.
- The app extracts the displayed YouTube Music play counts directly from the artist's Top songs
  playlist response. If those counts are unavailable, it falls back to video view counts; set
  `YT_API_KEY` (see .env.example) to use the official Data API v3 as a final fallback.
