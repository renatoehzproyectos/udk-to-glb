# UModel en Android ARM64 (ruta preferida)

Si UModel funciona vía Box64, **usarlo** y no reinventar el parser.

## Requisitos Termux

```bash
pkg update
pkg install -y proot-distro wget
# opcional: proot-distro install debian
```

## Box64

```bash
pkg install -y box64
# o compilar desde https://github.com/ptitSeb/box64
```

## UModel

Descarga oficial (x86-64 Linux): https://www.gildor.org/en/projects/umodel

```bash
# ejemplo
box64 ./umodel -game=rocketleague -list TJBrotherAirDribble.udk
box64 ./umodel -game=rocketleague -export -meshes -out=export TJBrotherAirDribble.udk
```

Export típico: `.pskx` (o glTF si la build lo soporta). Luego convertir a GLB con el writer propio si hace falta.

## Si Box64 falla

Usar el parser Python de este repo (`extract_one_mesh.py`).
