import asyncio
import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .services import get_artist_cached

BASE = Path(__file__).resolve().parent.parent
app = FastAPI(title="YT Music Play Counts")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


class Batch(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=25)


async def safe(query: str) -> dict:
    try:
        return await get_artist_cached(query)
    except LookupError as e:
        return {"query": query, "error": str(e)}
    except Exception as e:  # network / YouTube changes
        return {"query": query, "error": f"Lookup failed: {type(e).__name__}"}


@app.get("/api/artist")
async def artist(q: str = Query(min_length=1)):
    data = await safe(q)
    if "error" in data:
        raise HTTPException(404, data["error"])
    return data


@app.post("/api/batch")
async def batch(body: Batch):
    names = list(dict.fromkeys(q.strip() for q in body.queries if q.strip()))
    return {"results": await asyncio.gather(*(safe(q) for q in names))}


@app.get("/api/export.csv")
async def export_csv(q: list[str] = Query(...)):
    results = await asyncio.gather(*(safe(x) for x in q))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["artist", "artist_id", "song", "video_id", "plays", "plays_display", "album", "album_id", "all_artist_ids"])
    for r in results:
        for s in r.get("songs", []):
            w.writerow([
                r["artist"]["name"], r["artist"]["id"], s["title"], s["video_id"], s["plays"] or "",
                s["plays_text"] or "", s["album"] or "", s["album_id"] or "",
                "|".join(a["id"] or "" for a in s["artists"]),
            ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="ytmusic_play_counts.csv"'},
    )


@app.get("/")
def index():
    return FileResponse(BASE / "templates" / "index.html")
