# Flash Cards App

A small local web app for importing Anki `.apkg` decks and studying them in the browser.

## Run

```bash
python3 app.py
```

Then open http://127.0.0.1:8000/register, create an account, and log in.

You can change the host or port with:

```bash
FLASHCARDS_HOST=127.0.0.1 FLASHCARDS_PORT=8000 python3 app.py
```

## What Works Now

- registration and login with HTTP-only session cookies
- `.apkg` upload and import
- parsing `collection.anki2` and `collection.anki21`
- local SQLite storage in `data/flashcards.sqlite3`
- deck list with review stats
- front/back study mode with progress tracking

This first pass uses the first Anki note field as the front of each card and the remaining fields as the back.
