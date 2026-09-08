from flashcards.web import parse_multipart, parse_multipart_form


def test_apkg_multipart_preserves_trailing_binary_whitespace():
    boundary = "mobile-boundary"
    content = b"PK\x03\x04archive-bytes\x20\n"
    body = (
        b"--mobile-boundary\r\n"
        b'Content-Disposition: form-data; name="apkg"; filename="cards.apkg"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n"
        + content
        + b"\r\n--mobile-boundary--\r\n"
    )

    assert parse_multipart(body, f"multipart/form-data; boundary={boundary}")["apkg"] == (
        "cards.apkg",
        content,
    )


def test_pdf_multipart_accepts_rfc_encoded_ipad_filename():
    body = (
        b"--ios\r\n"
        b'Content-Disposition: form-data; name="mode"\r\n\r\nextract\r\n'
        b"--ios\r\n"
        b"Content-Disposition: form-data; name=\"pdf\"; "
        b"filename*=UTF-8''Lezione%20uno.pdf\r\n"
        b"Content-Type: application/octet-stream\r\n\r\n"
        b"%PDF-1.7\ncontent\r\n"
        b"--ios--\r\n"
    )

    fields, files = parse_multipart_form(body, "multipart/form-data; boundary=ios")

    assert fields == {"mode": "extract"}
    assert files["pdf"] == ("Lezione uno.pdf", "application/octet-stream", b"%PDF-1.7\ncontent")
