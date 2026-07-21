"""HTML presentation functions with no database or HTTP side effects."""

from __future__ import annotations

import html
import json
import sqlite3


def render_page(title: str, body: str, user: sqlite3.Row | None = None) -> bytes:
    nav = (
        (
            f'<span class="auth-note">{html.escape(user["username"])}</span>'
            '<form action="/logout" method="post"><button class="link-button" type="submit">Log out</button></form>'
        )
        if user
        else (
            '<a class="nav-link" href="/login">Log in</a><a class="button compact" href="/register">Register</a>'
        )
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Flash Cards</title>
<link rel="stylesheet" href="/static/styles.css"></head>
<body><header class="topbar"><a class="brand" href="/">Flash Cards</a>
<nav class="nav-actions">{nav}</nav></header><main>{body}</main></body></html>""".encode()


def render_auth_page(mode: str, message: str = "", next_path: str = "/") -> bytes:
    is_register = mode == "register"
    title, action = ("Create account", "/register") if is_register else ("Log in", "/login")
    prompt = "Already have an account?" if is_register else "Need an account?"
    link_href, link_text = ("/login", "Log in") if is_register else ("/register", "Register")
    notice = f'<div class="notice error">{html.escape(message)}</div>' if message else ""
    autocomplete = "new-password" if is_register else "current-password"
    body = f"""<section class="auth-shell"><form class="auth-panel" action="{action}" method="post">
<div><h1>{title}</h1><p>Import and study your Anki decks from your own account.</p></div>{notice}
<label for="username">Username</label><input id="username" name="username" autocomplete="username" required>
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="{autocomplete}" required>
<input name="next" type="hidden" value="{html.escape(next_path, quote=True)}"><button type="submit">{title}</button>
<p class="auth-switch">{prompt} <a href="{link_href}">{link_text}</a></p></form></section>"""
    return render_page(title, body)


def render_dashboard(user: sqlite3.Row, decks: list[sqlite3.Row], message: str = "") -> bytes:
    items = []
    for deck in decks:
        accuracy = "No reviews yet"
        if deck["total_seen"]:
            accuracy = f"{round((deck['total_correct'] / deck['total_seen']) * 100)}% correct"
        items.append(f"""<article class="deck-card"><div><h2>{html.escape(deck["name"])}</h2>
<p>{deck["card_count"]} cards · {accuracy}</p></div><a class="button" href="/deck/{deck["id"]}">Study</a></article>""")
    empty = "" if items else '<p class="empty">Import an Anki package to start studying.</p>'
    notice = f'<div class="notice">{html.escape(message)}</div>' if message else ""
    body = f"""<section class="dashboard"><div class="intro"><h1>Your decks</h1>
<p>Import an Anki <code>.apkg</code> file, then study cards right in the browser.</p></div>{notice}
<form class="upload-panel" action="/upload" method="post" enctype="multipart/form-data">
<label for="apkg">Anki package</label><div class="upload-row">
<input id="apkg" name="apkg" type="file" accept=".apkg,application/zip" required><button type="submit">Import</button>
</div></form><section class="deck-grid">{"".join(items)}{empty}</section></section>"""
    body = body.replace(
        '<section class="deck-grid">',
        '<a class="button pdf-import-link" href="/pdf-import">Create cards from a PDF</a><section class="deck-grid">',
    )
    return render_page("Decks", body, user)


def render_study(user: sqlite3.Row, deck: sqlite3.Row, cards: list[sqlite3.Row]) -> bytes:
    payload = json.dumps([dict(card) for card in cards])
    body = f"""<section class="study-shell"><div class="study-head"><div>
<a class="back-link" href="/">Back to decks</a><h1>{html.escape(deck["name"])}</h1></div>
<div class="counter"><span id="cardNumber">1</span> / {len(cards)}</div></div>
<div class="progress"><div id="progressBar"></div></div>
<article id="studyCard" class="study-card" tabindex="0" aria-live="polite">
<div class="side-label" id="sideLabel">Front</div><div id="cardContent" class="card-content"></div></article>
<div class="actions"><button id="flipButton" type="button">Flip</button>
<button id="wrongButton" type="button" class="secondary">Again</button>
<button id="rightButton" type="button">Got it</button></div></section>
<script>window.FLASHCARDS = {payload};</script><script src="/static/study.js"></script>"""
    return render_page(str(deck["name"]), body, user)


def render_pdf_import(user: sqlite3.Row) -> bytes:
    body = """<section class="pdf-import-shell">
<div class="intro"><a class="back-link" href="/">Back to decks</a><h1>Create cards from a PDF</h1>
<p>Extract questions already in a document or generate grounded drafts with your local Ollama model.</p></div>
<div class="notice warning"><strong>Study aid only.</strong> Generated cards may contain mistakes and are not medically verified. Review every question, answer, and source excerpt before saving.</div>
<form id="pdfUploadForm" class="upload-panel">
<label for="pdfFile">PDF document</label><input id="pdfFile" name="pdf" type="file" accept=".pdf,application/pdf" required>
<fieldset><legend>Import mode</legend>
<label><input type="radio" name="mode" value="extract" checked> Extract existing questions (no AI)</label>
<label><input type="radio" name="mode" value="generate"> Generate new flashcards with Ollama (AI)</label></fieldset>
<button id="startPdfImport" type="submit">Process PDF</button></form>
<section id="pdfStatus" class="processing-panel" hidden aria-live="polite"><div class="status-row">
<strong id="pdfStatusLabel">Uploading</strong><span id="pdfProgressText">0%</span></div>
<div class="progress"><div id="pdfProgressBar"></div></div><p id="pdfStatusMessage"></p>
<button id="cancelPdfImport" class="secondary" type="button">Cancel processing</button></section>
<section id="draftReview" class="draft-review" hidden><div class="review-head"><div><h2>Review draft cards</h2>
<p>Only selected cards with completed answers will be saved.</p></div><div class="review-actions">
<button id="selectAllDrafts" type="button" class="secondary">Select all</button>
<button id="deselectAllDrafts" type="button" class="secondary">Deselect all</button></div></div>
<div id="draftWarnings"></div><div id="draftList" class="draft-list"></div>
<div class="save-panel"><label for="pdfDeckName">Deck name</label><input id="pdfDeckName" maxlength="200" required>
<button id="saveApprovedDrafts" type="button">Save selected cards</button></div></section>
</section><script src="/static/pdf_import.js"></script>"""
    return render_page("Create from PDF", body, user)
