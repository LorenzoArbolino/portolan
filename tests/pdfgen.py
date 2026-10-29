"""Tiny PDF writer for offline tests (no committed PDFs: *.pdf is gitignored on purpose)."""


def make_pdf(lines: list[str]) -> bytes:
    """One page, Helvetica, one line per entry. No lines = only a drawn box (like a scan)."""

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    if lines:
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
        for ln in lines:
            ops.append(f"({esc(ln)}) Tj T*")
        ops.append("ET")
    else:
        ops = ["0.5 g", "50 500 300 200 re f"]
    stream = "\n".join(ops).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_scanned_pdf(lines: list[str]) -> bytes | None:
    """An image-only PDF (no text layer): render a text PDF to JPEG with pdftoppm and wrap the JPEG.
    Returns None if poppler isn't installed."""
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    if not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "t.pdf"
        src.write_bytes(make_pdf(lines))
        subprocess.run(
            ["pdftoppm", "-r", "200", "-jpeg", "-singlefile", str(src), str(Path(d) / "img")], check=True
        )
        jpg = (Path(d) / "img.jpg").read_bytes()
    w, h = _jpeg_size(jpg)
    content = b"q 595 0 0 842 0 0 cm /Im0 Do Q"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /XObject << /Im0 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        f"/Filter /DCTDecode /Length {len(jpg)} >>\nstream\n".encode()
        + jpg
        + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _jpeg_size(jpg: bytes) -> tuple[int, int]:
    """Width and height from the JPEG SOF marker."""
    i = 2
    while i < len(jpg):
        marker, length = jpg[i + 1], int.from_bytes(jpg[i + 2 : i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(jpg[i + 7 : i + 9], "big"), int.from_bytes(jpg[i + 5 : i + 7], "big")
        i += 2 + length
    raise ValueError("no SOF marker")
