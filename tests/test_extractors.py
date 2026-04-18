from app.services.extractors import TextractExtractor


class UnsupportedPdfThenImageClient:
    def __init__(self):
        self.calls = 0

    def detect_document_text(self, Document):
        self.calls += 1
        payload = Document["Bytes"]
        if payload.startswith(b"%PDF-"):
            raise RuntimeError("UnsupportedDocumentException")
        return {
            "Blocks": [
                {
                    "BlockType": "LINE",
                    "Text": "MILWAUKEE AREA TECHNICAL COLLEGE",
                    "Geometry": {"BoundingBox": {"Left": 0.1, "Top": 0.2, "Width": 0.5, "Height": 0.03}},
                    "Page": 1,
                },
                {
                    "BlockType": "LINE",
                    "Text": "ENG 201 English Composition A",
                    "Geometry": {"BoundingBox": {"Left": 0.1, "Top": 0.3, "Width": 0.5, "Height": 0.03}},
                    "Page": 1,
                },
            ]
        }


def test_textract_extractor_falls_back_to_rendered_pdf_page_images(monkeypatch):
    import fitz

    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Scanned transcript placeholder")
        pdf_bytes = document.tobytes()
    finally:
        document.close()

    client = UnsupportedPdfThenImageClient()
    extractor = TextractExtractor(client=client)

    result = extractor.extract_with_layout(pdf_bytes)

    assert client.calls >= 2
    assert "MILWAUKEE AREA TECHNICAL COLLEGE" in result["text"]
    assert any(line["page_number"] == 1 for line in result["line_locations"])
    assert any("English Composition" in line["text"] for line in result["line_locations"])
