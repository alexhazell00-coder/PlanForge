"""Native Windows & Linux icon builder and runtime window-icon loader.

Reads ``docs/icon_transparent_background.png`` (using only Python's standard
library ``zlib`` and ``struct``) and generates:
- ``planforge/assets/planforge.ico`` — Windows multi-size icon (16..256 px)
- ``planforge/assets/planforge-<size>.png`` & ``planforge.png`` — Linux / XDG & Tk icons
"""

from __future__ import annotations

import ctypes
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)
PNG_EXPORT_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256, 512)

APP_USER_MODEL_ID = "PlanForge.Desktop.Application.1"


def bundle_root() -> Path:
    """Return the root directory for bundled resources (source tree or PyInstaller)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def assets_dir() -> Path:
    """Return the directory containing packaged PlanForge icon assets."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "planforge" / "assets"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "assets"


def source_icon_path(repo_root: Path | None = None) -> Path:
    """Locate ``docs/icon_transparent_background.png`` (or its bundled fallback)."""
    root = repo_root or bundle_root()
    candidates = (
        root / "docs" / "icon_transparent_background.png",
        assets_dir() / "icon_transparent_background.png",
        assets_dir() / "planforge.png",
    )
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(data: bytes) -> tuple[int, int, bytearray]:
    """Decode an 8-bit non-interlaced RGB/RGBA/greyscale PNG into flat RGBA bytes."""
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError("Invalid PNG signature.")

    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    palette: list[tuple[int, int, int]] = []
    trns: bytes = b""
    idat_parts: list[bytes] = []

    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        chunk_data = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data[:13]
            )
        elif chunk_type == b"PLTE":
            palette = [
                (chunk_data[i], chunk_data[i + 1], chunk_data[i + 2])
                for i in range(0, len(chunk_data), 3)
            ]
        elif chunk_type == b"tRNS":
            trns = chunk_data
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width <= 0 or height <= 0:
        raise ValueError("Invalid PNG dimensions.")
    if bit_depth != 8 or interlace != 0:
        raise ValueError(f"Unsupported PNG format (bit_depth={bit_depth}, interlace={interlace}).")

    channels_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    if color_type not in channels_map:
        raise ValueError(f"Unsupported PNG color_type={color_type}.")
    bpp = channels_map[color_type]
    stride = width * bpp

    raw = zlib.decompress(b"".join(idat_parts))
    expected_len = height * (1 + stride)
    if len(raw) < expected_len:
        raise ValueError("Truncated PNG image data.")

    prev_row = bytearray(stride)
    cur_row = bytearray(stride)
    rgba = bytearray(width * height * 4)

    src_offset = 0
    dst_offset = 0
    for _y in range(height):
        filt = raw[src_offset]
        src_offset += 1
        row_bytes = raw[src_offset:src_offset + stride]
        src_offset += stride

        if filt == 0:
            cur_row[:] = row_bytes
        elif filt == 1:
            for i in range(stride):
                left = cur_row[i - bpp] if i >= bpp else 0
                cur_row[i] = (row_bytes[i] + left) & 0xFF
        elif filt == 2:
            for i in range(stride):
                cur_row[i] = (row_bytes[i] + prev_row[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = cur_row[i - bpp] if i >= bpp else 0
                cur_row[i] = (row_bytes[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                left = cur_row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                cur_row[i] = (row_bytes[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"Unknown PNG filter type {filt}.")

        if color_type == 6:
            rgba[dst_offset:dst_offset + width * 4] = cur_row
            dst_offset += width * 4
        elif color_type == 2:
            for x in range(width):
                rgba[dst_offset] = cur_row[x * 3]
                rgba[dst_offset + 1] = cur_row[x * 3 + 1]
                rgba[dst_offset + 2] = cur_row[x * 3 + 2]
                rgba[dst_offset + 3] = 255
                dst_offset += 4
        elif color_type == 4:
            for x in range(width):
                g = cur_row[x * 2]
                rgba[dst_offset] = g
                rgba[dst_offset + 1] = g
                rgba[dst_offset + 2] = g
                rgba[dst_offset + 3] = cur_row[x * 2 + 1]
                dst_offset += 4
        elif color_type == 0:
            for x in range(width):
                g = cur_row[x]
                rgba[dst_offset] = g
                rgba[dst_offset + 1] = g
                rgba[dst_offset + 2] = g
                rgba[dst_offset + 3] = 255
                dst_offset += 4
        elif color_type == 3:
            for x in range(width):
                idx = cur_row[x]
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                a = trns[idx] if idx < len(trns) else 255
                rgba[dst_offset] = r
                rgba[dst_offset + 1] = g
                rgba[dst_offset + 2] = b
                rgba[dst_offset + 3] = a
                dst_offset += 4

        prev_row[:] = cur_row

    return width, height, rgba


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def encode_png_rgba(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """Encode flat 8-bit RGBA pixels into a compact standard PNG byte stream."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row_stride = width * 4
    scanlines = bytearray()
    for y in range(height):
        scanlines.append(0)
        start = y * row_stride
        scanlines.extend(rgba[start:start + row_stride])
    compressed = zlib.compress(bytes(scanlines), level=9)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )


def pad_to_square_rgba(width: int, height: int, rgba: bytes | bytearray) -> tuple[int, bytearray]:
    """Center an image onto a transparent square RGBA canvas without distortion."""
    if width == height:
        return width, bytearray(rgba)
    side = max(width, height)
    square = bytearray(side * side * 4)
    pad_x = (side - width) // 2
    pad_y = (side - height) // 2
    for y in range(height):
        src_start = y * width * 4
        dst_start = ((y + pad_y) * side + pad_x) * 4
        square[dst_start:dst_start + width * 4] = rgba[src_start:src_start + width * 4]
    return side, square


def resize_square_rgba(side: int, rgba: bytes | bytearray, target: int) -> bytearray:
    """Resize a square RGBA image to ``target x target`` in premultiplied RGBA space."""
    if target == side:
        return bytearray(rgba)

    out = bytearray(target * target * 4)
    scale = side / target

    x_spans: list[tuple[int, int, list[tuple[int, float]]]] = []
    for tx in range(target):
        sx0 = tx * scale
        sx1 = (tx + 1) * scale
        ix0 = int(sx0)
        ix1 = min(side - 1, int(sx1))
        weights: list[tuple[int, float]] = []
        for ix in range(ix0, ix1 + 1):
            left = max(sx0, float(ix))
            right = min(sx1, float(ix + 1))
            w = right - left
            if w > 0.0:
                weights.append((ix * 4, w))
        x_spans.append((ix0, ix1, weights))

    for ty in range(target):
        sy0 = ty * scale
        sy1 = (ty + 1) * scale
        iy0 = int(sy0)
        iy1 = min(side - 1, int(sy1))
        y_weights: list[tuple[int, float]] = []
        for iy in range(iy0, iy1 + 1):
            top = max(sy0, float(iy))
            bot = min(sy1, float(iy + 1))
            w = bot - top
            if w > 0.0:
                y_weights.append((iy * side * 4, w))

        row_out = ty * target * 4
        for tx in range(target):
            pr = pg = pb = pa = total_w = 0.0
            for row_off, wy in y_weights:
                for col_off, wx in x_spans[tx][2]:
                    w = wx * wy
                    idx = row_off + col_off
                    a = rgba[idx + 3] / 255.0
                    pr += rgba[idx] * a * w
                    pg += rgba[idx + 1] * a * w
                    pb += rgba[idx + 2] * a * w
                    pa += a * w
                    total_w += w
            dst = row_out + tx * 4
            if total_w > 0.0 and pa > 1e-6:
                alpha = min(1.0, pa / total_w)
                out[dst] = min(255, int(round(pr / pa)))
                out[dst + 1] = min(255, int(round(pg / pa)))
                out[dst + 2] = min(255, int(round(pb / pa)))
                out[dst + 3] = min(255, int(round(alpha * 255.0)))
    return out


def _encode_ico_dib_frame(width: int, height: int, rgba: bytes | bytearray) -> bytes:
    """Encode a standard 32-bit BGRA BITMAPINFOHEADER DIB + 1-bit AND mask frame.

    Using uncompressed 32-bit BGRA DIB frames for <=128px and PNG for 256px matches
    Microsoft's official Windows Vista/10/11 ICO specification and guarantees full
    compatibility across Windows Explorer, Start Menu .lnk shortcuts, PyInstaller
    PE resource embedding, and Tcl/Tk's Win32 ``wm iconbitmap`` loader.
    """
    bih = struct.pack(
        "<IiiHHIIiiII",
        40,  # biSize
        width,
        height * 2,  # combined XOR + AND height per ICO specification
        1,  # biPlanes
        32,  # biBitCount (BGRA)
        0,  # biCompression (BI_RGB)
        width * height * 4,
        0,
        0,
        0,
        0,
    )
    xor_rows = bytearray(width * height * 4)
    and_stride = ((width + 31) // 32) * 4
    and_mask = bytearray(and_stride * height)

    dst = 0
    for y in range(height - 1, -1, -1):  # bottom-up scanlines
        row_src = y * width * 4
        and_row = (height - 1 - y) * and_stride
        for x in range(width):
            p = row_src + x * 4
            r = rgba[p]
            g = rgba[p + 1]
            b = rgba[p + 2]
            a = rgba[p + 3]
            xor_rows[dst] = b
            xor_rows[dst + 1] = g
            xor_rows[dst + 2] = r
            xor_rows[dst + 3] = a
            dst += 4
            if a == 0:
                and_mask[and_row + (x >> 3)] |= 0x80 >> (x & 7)

    return bih + bytes(xor_rows) + bytes(and_mask)


def encode_ico(
    png_by_size: dict[int, bytes],
    sizes: Sequence[int] = ICO_SIZES,
    rgba_by_size: dict[int, bytes | bytearray] | None = None,
) -> bytes:
    """Pack square frames into a Windows multi-resolution ``.ico`` container."""
    entries: list[tuple[int, bytes]] = [(s, png_by_size[s]) for s in sizes if s in png_by_size]
    if not entries:
        raise ValueError("At least one icon size is required to build an .ico file.")

    header = struct.pack("<HHH", 0, 1, len(entries))
    directory = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(entries)

    for size, png_bytes in entries:
        frame_bytes = (
            _encode_ico_dib_frame(size, size, rgba_by_size[size])
            if rgba_by_size is not None and size in rgba_by_size and size < 256
            else png_bytes
        )
        dim_byte = 0 if size >= 256 else size
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                dim_byte,
                dim_byte,
                0,
                0,
                1,
                32,
                len(frame_bytes),
                offset,
            )
        )
        payload.extend(frame_bytes)
        offset += len(frame_bytes)

    return header + bytes(directory) + bytes(payload)


def generate_icon_bundle(
    src_png: Path | None = None,
    out_dir: Path | None = None,
) -> dict[str, Path]:
    """Generate ``planforge.ico`` and multi-size ``.png`` files from
    ``docs/icon_transparent_background.png``.
    """
    source = src_png or source_icon_path()
    target_dir = out_dir or assets_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    raw_bytes = source.read_bytes()
    width, height, rgba = decode_png_rgba(raw_bytes)
    side, square_rgba = pad_to_square_rgba(width, height, rgba)

    rgba_by_size: dict[int, bytes | bytearray] = {}
    png_by_size: dict[int, bytes] = {}
    current_side = side
    current_rgba = square_rgba
    for size in sorted(PNG_EXPORT_SIZES, reverse=True):
        while current_side >= size * 2:
            half = current_side // 2
            current_rgba = resize_square_rgba(current_side, current_rgba, half)
            current_side = half
        scaled = resize_square_rgba(current_side, current_rgba, size)
        rgba_by_size[size] = scaled
        png_by_size[size] = encode_png_rgba(size, size, scaled)

    written: dict[str, Path] = {}

    orig_copy = target_dir / "icon_transparent_background.png"
    if source.resolve() != orig_copy.resolve():
        orig_copy.write_bytes(raw_bytes)
    written["source_copy"] = orig_copy

    for size, png_data in sorted(png_by_size.items()):
        sized_path = target_dir / f"planforge-{size}.png"
        sized_path.write_bytes(png_data)
        written[f"png_{size}"] = sized_path

    main_png = target_dir / "planforge.png"
    main_png.write_bytes(png_by_size[512])
    written["png"] = main_png

    ico_path = target_dir / "planforge.ico"
    ico_path.write_bytes(encode_ico(png_by_size, rgba_by_size=rgba_by_size))
    written["ico"] = ico_path

    return written


def configure_platform_app_identity() -> None:
    """Ensure Windows groups the window under PlanForge's icon rather than python.exe."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass


def apply_window_icon(window: Any) -> bool:
    """Attach the PlanForge icon to a Tkinter root window."""
    folder = assets_dir()
    applied = False

    if sys.platform == "win32":
        ico_file = folder / "planforge.ico"
        if ico_file.is_file():
            try:
                window.iconbitmap(default=str(ico_file))
                applied = True
            except Exception:
                pass

    try:
        import tkinter as tk

        photo_images: list[Any] = []
        for size in (256, 128, 64, 48, 32, 16):
            candidate = folder / f"planforge-{size}.png"
            if candidate.is_file():
                photo_images.append(tk.PhotoImage(file=str(candidate)))
        if not photo_images:
            fallback = source_icon_path()
            if fallback.is_file():
                photo_images.append(tk.PhotoImage(file=str(fallback)))
        if photo_images:
            window._icon_photos = photo_images
            window.iconphoto(True, *photo_images)
            applied = True
    except Exception:
        pass

    return applied


def main() -> int:
    written = generate_icon_bundle()
    print(f"Generated {len(written)} icon assets in {assets_dir()}:")
    for key in ("ico", "png"):
        path = written[key]
        print(f"  - {path.name} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
