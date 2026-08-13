from __future__ import annotations

from pathlib import Path

from .reconstruction import MeshPart


def write_mtl(path: Path, parts: list[MeshPart]):
    lines = []
    for part in parts:
        r, g, b = (c / 255.0 for c in part.rgb)
        lines += [
            f"newmtl {part.name}",
            f"Kd {r:.6f} {g:.6f} {b:.6f}",
            "Ka 0.000000 0.000000 0.000000",
            "Ks 0.050000 0.050000 0.050000",
            "d 1.0",
            "illum 2",
            "",
        ]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_obj(path: Path, mtl_path: Path, parts: list[MeshPart]):
    lines = [f"mtllib {mtl_path.name}"]
    vertex_offset = 1

    for part in parts:
        mesh = part.mesh
        lines += ["", f"o {part.name}", f"g {part.name}", f"usemtl {part.name}"]

        for x, y, z in mesh.vertices:
            lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")

        for a, b, c in mesh.faces:
            lines.append(
                f"f {a + vertex_offset} {b + vertex_offset} {c + vertex_offset}"
            )

        vertex_offset += len(mesh.vertices)

    path.write_text("\n".join(lines), encoding="utf-8")
