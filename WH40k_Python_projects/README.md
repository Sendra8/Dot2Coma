# whproxy — Warhammer miniature → 4 vistas → proxy imprimible a 3 colores

Implementación del brief `WARHAMMER_MINI_PIPELINE_CODEX.md`.

A partir de un nombre aproximado de unidad produce, de forma determinista:

1. el producto de Games Workshop que mejor encaja (Algolia + fuzzy matching);
2. la carpeta oficial de imágenes 360 (desambiguada dentro de cajas multi-unidad);
3. cuatro fotografías cardinales: **front / left / back / right**;
4. las mismas cuatro vistas simplificadas a **ocre / gris / negro** por rango de luminancia;
5. un proxy volumétrico reconstruido por *visual hull* a partir de las cuatro siluetas;
6. un `.obj` + `.mtl` multiparte con esos tres colores como **volúmenes reales**;
7. un visor 3D interactivo autocontenido;
8. renders estáticos desde ese visor;
9. una `preview.png` agregada;
10. un `manifest.json` que hace el resultado reproducible.

## Instalación

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install fast-simplification      # decimación de malla (opcional pero recomendado)
playwright install chromium          # sólo para los renders estáticos
```

## Uso

```bash
python -m whproxy build "Norn Emissary"
python -m whproxy build "XV104 Riptide" --height-mm 120
python -m whproxy build "norn emissry" --black 0.05 --gray 0.15
```

Salida en `output/<slug>/` con el árbol descrito en el brief.

## Imágenes propias (`--frames-dir`)

Si tienes las cuatro vistas cardinales en disco — descargadas desde una máquina con
salida a internet, o fotos tuyas de la miniatura montada sobre fondo blanco — puedes
saltarte Algolia y el CDN por completo:

```bash
python -m whproxy build "Norn Emissary" --frames-dir ./mis_fotos
```

```text
mis_fotos/
├── front.jpg
├── left.jpg
├── back.jpg
└── right.jpg
```

Acepta `.jpg`, `.jpeg`, `.png` y `.webp`. Requisitos: fondo blanco, modelo centrado, y
que `left`/`right` sean pasos reales de 90° del torno — no una copia espejada.

**Este es el modo que da resultados reales cuando la red está cortada.**

## Modo offline

`--source offline` (o `WHPROXY_SOURCE=offline`) sustituye Algolia y el CDN de GW por
un catálogo fixture y por fotogramas de torno **sintéticos**, renderizados desde un
modelo vóxel procedural por arquetipo.

**Advertencia importante sobre qué es y qué no es.** El muñeco vóxel está escrito a
mano en `whproxy/offline.py` con cápsulas, elipsoides y cajas colocadas a ojo. No es
una simplificación de la miniatura real ni deriva de ninguna imagen suya: es una
figura inventada con forma de bípedo, de mecha o de tanque a la que se le pone la
etiqueta de la unidad que pidas. La silueta que sale **no se parece a la unidad de
verdad más allá de la categoría general**.

Existe para una sola cosa: ejercitar las etapas 5-14 del pipeline cuando no hay
fuente disponible. Es útil para CI y para depurar el visual hull, no para obtener un
proxy de una unidad concreta. Para eso usa `--frames-dir` o el modo `network`.

Nunca se presenta como fotografía oficial: el manifest lleva
`"provider": "offline-synthetic"` más un campo `warning`, y la `preview.png` se
etiqueta `[SYNTHETIC SOURCE FRAMES]`.

## Configuración

Todo por variables de entorno, porque GW rota credenciales e índices:

```text
GW_ALGOLIA_APP_ID     M5ZIQZNQ2H
GW_ALGOLIA_API_KEY    92c6a8254f9d34362df8e6d96475e5d8
GW_ALGOLIA_INDEX      prod-lazarus-product-en-gb
GW_CDN_BASE           https://www.warhammer.com
WHPROXY_SOURCE        network | offline
WHPROXY_CACHE         .cache
WHPROXY_CHROMIUM      ruta a un binario de Chromium alternativo
```

## Decisiones de diseño que importan

- **La geometría sale de la silueta, el color de la luminancia.** Un detalle oscuro
  nunca abre un agujero en el modelo.
- **El color es volumen, no piel.** Gris y negro ocupan una cáscara de
  `surface_color_depth_mm`; más adentro todo vuelve a ocre. Así las tres partes son
  imprimibles y no planos flotantes.
- **Union, no intersection**, al fusionar vistas opuestas: para cubicar/almacenar es
  preferible sobreestimar que perder una garra o una cresta.
- **`back` y `right` se espejan** antes de combinarse, para que los cuatro ejes de
  cámara compartan un único sistema de coordenadas del mundo.
- **La fila 0 de la imagen es la cabeza**, así que las máscaras se invierten en Z
  antes del *marching cubes* o el modelo sale del revés.

## Tests

```bash
pytest
```

Cubre los seis tests del brief: resolución de carpeta 360 Norn Emissary vs
Assimilator, mapeo cardinal, asignación por cuantiles, mínimo de ocre, extensión del
visual hull y núcleo ocre bajo cáscara negra.

## Estado de red en el entorno donde se generaron las muestras

`www.warhammer.com` y `M5ZIQZNQ2H-dsn.algolia.net` devuelven 403 en el CONNECT del
proxy de egress.

Por tanto las muestras de `samples/` están generadas con `--source offline` y **no
representan a las unidades cuyo nombre llevan** — son el muñeco procedural descrito
arriba. Están ahí como evidencia de que el pipeline corre entero, no como resultado.

En una máquina con salida a esos dos hosts, el mismo comando sin `--source` usa las
fotografías oficiales sin cambiar nada más.
