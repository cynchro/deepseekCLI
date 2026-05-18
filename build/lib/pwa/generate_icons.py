"""Genera los íconos PNG para la PWA. Ejecutar una sola vez."""
import struct, zlib, math

def png(size):
    def chunk(name, data):
        c = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', c)

    bg   = (10,  10,  10)
    fg   = (0,  204,  68)
    rows = []
    cx, cy, r = size // 2, size // 2, size * 0.32

    for y in range(size):
        row = [0]
        for x in range(size):
            dx, dy = x - cx, y - cy
            # Fondo redondeado
            corner = size * 0.18
            in_rect = (corner <= x <= size - corner and 0 <= y <= size) or \
                      (0 <= x <= size and corner <= y <= size - corner)
            in_corner = any(
                math.hypot(x - ox, y - oy) <= corner
                for ox, oy in [(corner, corner), (size-corner, corner),
                               (corner, size-corner), (size-corner, size-corner)]
            )
            in_bg = in_rect or in_corner

            # Letra "d" simplificada como círculo + barra vertical
            in_circle = math.hypot(dx + size*0.06, dy) <= r * 0.68
            in_stem   = (-size*0.38 <= dx - size*0.28 <= -size*0.18 and abs(dy) <= r)
            in_fg = in_bg and (in_circle or in_stem)

            if in_fg:
                row += list(fg) + [255]
            elif in_bg:
                row += list(bg) + [255]
            else:
                row += [0, 0, 0, 0]
        rows.append(bytes(row))

    raw = b''.join(b'\x00' + r for r in rows)
    compressed = zlib.compress(raw)

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
        + chunk(b'IDAT', compressed)
        + chunk(b'IEND', b'')
    )

from pathlib import Path
static = Path(__file__).parent / 'static'
for size in (192, 512):
    (static / f'icon-{size}.png').write_bytes(png(size))
    print(f'  ✅ icon-{size}.png generado')
