from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image, ImageDraw

from .reconstruction import MeshPart

CAMERAS = {
    "front": dict(eye=dict(x=0.0, y=-2.4, z=0.15), up=dict(x=0, y=0, z=1)),
    "back": dict(eye=dict(x=0.0, y=2.4, z=0.15), up=dict(x=0, y=0, z=1)),
    "left": dict(eye=dict(x=-2.4, y=0.0, z=0.15), up=dict(x=0, y=0, z=1)),
    "right": dict(eye=dict(x=2.4, y=0.0, z=0.15), up=dict(x=0, y=0, z=1)),
    "iso": dict(eye=dict(x=1.7, y=-1.7, z=1.15), up=dict(x=0, y=0, z=1)),
    "top": dict(eye=dict(x=0.0, y=0.0, z=2.7), up=dict(x=0, y=1, z=0)),
}


def make_figure(parts: list[MeshPart], camera=None) -> go.Figure:
    fig = go.Figure()

    for part in parts:
        mesh = part.mesh
        r, g, b = part.rgb
        fig.add_trace(
            go.Mesh3d(
                x=mesh.vertices[:, 0],
                y=mesh.vertices[:, 1],
                z=mesh.vertices[:, 2],
                i=mesh.faces[:, 0],
                j=mesh.faces[:, 1],
                k=mesh.faces[:, 2],
                color=f"rgb({r},{g},{b})",
                flatshading=True,
                name=part.name,
                showscale=False,
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        template="plotly_white",
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        scene=dict(
            aspectmode="data",
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=camera or CAMERAS["iso"],
        ),
    )
    return fig


def write_viewer(parts: list[MeshPart], path: Path):
    fig = make_figure(parts, CAMERAS["iso"])
    # include_plotlyjs=True -> fully self-contained local HTML
    pio.write_html(fig, path, include_plotlyjs=True, full_html=True)


def _chromium_executable() -> str | None:
    """Locate a Chromium that Playwright can drive.

    Preinstalled images often ship a browser build whose revision does not match
    the pinned Playwright version, in which case the default launch fails while
    the binary itself works fine via `executable_path`.
    """
    candidate = os.getenv("WHPROXY_CHROMIUM") or "/opt/pw-browsers/chromium"
    return candidate if Path(candidate).exists() else None


async def _capture_cameras(
    html_path: Path,
    targets: dict[str, Path],
    size: int = 900,
) -> None:
    from playwright.async_api import async_playwright

    launch_kwargs: dict = {"headless": True}
    executable = _chromium_executable()
    if executable:
        launch_kwargs["executable_path"] = executable

    async with async_playwright() as p:
        browser = await p.chromium.launch(**launch_kwargs)
        page = await browser.new_page(viewport={"width": size, "height": size})
        await page.goto(html_path.resolve().as_uri(), wait_until="load")
        await page.wait_for_selector(".plot-container", timeout=30_000)
        await page.wait_for_timeout(600)

        for name, png_path in targets.items():
            camera = json.dumps(CAMERAS[name])
            await page.evaluate(
                """(camera) => {
                    const gd = document.querySelector('.js-plotly-plot');
                    return Plotly.relayout(gd, {'scene.camera': camera});
                }""",
                json.loads(camera),
            )
            await page.wait_for_timeout(350)
            await page.locator(".plot-container").screenshot(path=str(png_path))

        await browser.close()


def render_views(parts: list[MeshPart], out_dir: Path) -> tuple[dict[str, Path], dict]:
    """Render every camera to PNG. Returns `(paths, status)`.

    A missing browser must not fail model generation, so failures are reported
    in the status dict instead of raising.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "_render.html"
    pio.write_html(
        make_figure(parts, CAMERAS["iso"]),
        html_path,
        include_plotlyjs=True,
        full_html=True,
    )

    targets = {name: out_dir / f"{name}.png" for name in CAMERAS}

    try:
        asyncio.run(_capture_cameras(html_path, targets))
        status = {"renderer": "playwright", "ok": True}
    except Exception as exc:  # noqa: BLE001 - fallback path is deliberate
        status = {"renderer": "playwright", "ok": False, "error": str(exc)}
        try:
            for name, png_path in targets.items():
                make_figure(parts, CAMERAS[name]).write_image(
                    str(png_path), width=900, height=900
                )
            status = {"renderer": "kaleido", "ok": True, "playwright_error": str(exc)}
        except Exception as exc2:  # noqa: BLE001
            status["kaleido_error"] = str(exc2)
            html_path.unlink(missing_ok=True)
            return {}, status

    html_path.unlink(missing_ok=True)
    return {n: p for n, p in targets.items() if p.exists()}, status


def make_preview_grid(render_paths: dict[str, Path], out_path: Path, title: str = ""):
    order = [n for n in ["front", "left", "back", "right", "iso", "top"] if n in render_paths]
    if not order:
        raise RuntimeError("No renders available for the preview grid")

    cell = 640
    label_h = 42
    header = 56 if title else 0
    canvas = Image.new("RGB", (cell * 3, header + (cell + label_h) * 2), "white")
    draw = ImageDraw.Draw(canvas)

    if title:
        draw.text((18, 20), title, fill="black")

    for idx, name in enumerate(order):
        im = Image.open(render_paths[name]).convert("RGB")
        im.thumbnail((cell, cell))
        x0 = (idx % 3) * cell
        y0 = header + (idx // 3) * (cell + label_h)
        x = x0 + (cell - im.width) // 2
        y = y0 + (cell - im.height) // 2
        canvas.paste(im, (x, y))
        draw.text((x0 + 14, y0 + cell + 8), name.upper(), fill="black")

    canvas.save(out_path, quality=92)
