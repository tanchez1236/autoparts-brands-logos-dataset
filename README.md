# Autoparts Brands Logos Dataset

Dataset abierto de logos de **marcas de autopartes**, generado mediante
scraping automatizado y validacion de imagenes.

Cada logo queda disponible en tres variantes listas para usar — igual que
[filippofilip95/car-logos-dataset](https://github.com/filippofilip95/car-logos-dataset)
pero enfocado en fabricantes de piezas aftermarket.

## Uso rapido

Cada marca tiene una entrada en `data/logos.json`:

```json
{
  "name": "Bosch",
  "slug": "bosch",
  "image": {
    "thumb":     "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/thumb/bosch.png",
    "optimized": "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/optimized/bosch.png",
    "original":  "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/original/bosch.png"
  }
}
```

## Estructura del repositorio

```text
autoparts-brands-logos-dataset/
├── brands-list.txt          # lista curada de marcas
├── requirements.txt
├── data/
│   └── logos.json           # dataset principal (generado)
├── logos/
│   ├── original/            # PNG a resolucion original
│   ├── optimized/           # PNG max 240 px
│   └── thumb/               # PNG max 100 px
├── dataset/                 # logos crudos descargados por los scrapers
│   └── <slug>/
│       ├── logo.png         # logo canónico (scrapers de sitios)
│       ├── 001.png …        # logos de motores de búsqueda
│       └── metadata.json
├── scrapers/
│   ├── autodoc_scraper.py
│   ├── rockauto_scraper.py
│   ├── eurocarparts_scraper.py
│   ├── bing_scraper.py
│   ├── dom_logo_scraper.py
│   ├── google_images_scraper.py
│   └── utils/
│       ├── cleaners.py
│       ├── downloader.py
│       └── validators.py
└── tools/
    ├── process_logos.py     # genera logos/original|optimized|thumb
    ├── generate_data.py     # genera data/logos.json
    ├── count.py
    ├── dedupe.py
    └── verify.py
```

## Advertencia

Los logos pertenecen a sus respectivos dueños. Este dataset es solo para investigacion, machine learning y propositos educativos. Antes de reutilizar imagenes en productos o publicaciones, revisa licencias, terminos de uso y politicas de marca de cada fabricante.

## Alcance del dataset

Enfocado en marcas de **partes automotrices y aftermarket**. La lista incluye fabricantes globales de:

- Frenos, suspension y direccion
- Filtros, lubricacion y sellos
- Encendido, inyeccion y electronica automotriz
- Iluminacion, climatizacion y enfriamiento
- Rodamientos, transmisiones y componentes de motor
- Neumaticos, baterias y accesorios tecnicos

---

## Instalacion

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Pipeline completo

### Paso 1 — Scrapear logos desde sitios de autopartes

Los scrapers de sitios descargan el logo oficial de cada marca directamente
desde las paginas de fabricantes de autodoc.es, rockauto.com y eurocarparts.com.
Los logos se guardan en `dataset/<slug>/logo.png`.

```bash
# autodoc.es
python scrapers/autodoc_scraper.py --dataset-dir dataset

# rockauto.com
python scrapers/rockauto_scraper.py --dataset-dir dataset

# eurocarparts.com/brands
python scrapers/eurocarparts_scraper.py --dataset-dir dataset
```

### Paso 2 (opcional) — Enriquecer con motores de busqueda

Si una marca no aparece en los catálogos anteriores puedes buscar logos
adicionales via API de Google o Bing.

**Google Custom Search**

```bash
export GOOGLE_CUSTOM_SEARCH_API_KEY="tu_api_key"
export GOOGLE_CUSTOM_SEARCH_CX="tu_cx"
python scrapers/google_images_scraper.py \
  --brands-file brands-list.txt --dataset-dir dataset --per-brand 5
```

**Bing Image Search**

```bash
export BING_IMAGE_SEARCH_API_KEY="tu_api_key"
python scrapers/bing_scraper.py \
  --brands-file brands-list.txt --dataset-dir dataset --per-brand 5
```

**DOM logo scraper** (sitio oficial especifico)

```bash
python scrapers/dom_logo_scraper.py \
  --brand "Bosch" \
  --domain "https://www.boschaftermarket.com" \
  --dataset-dir dataset
```

### Paso 3 — Generar variantes de logos

Convierte cada logo crudo en las tres variantes publicables:

| Variante    | Tamaño maximo | Ruta de salida              |
|-------------|---------------|-----------------------------|
| `original`  | sin cambio    | `logos/original/<slug>.png` |
| `optimized` | 240 × 240 px  | `logos/optimized/<slug>.png`|
| `thumb`     | 100 × 100 px  | `logos/thumb/<slug>.png`    |

```bash
python tools/process_logos.py
# Procesar una sola marca:
python tools/process_logos.py --slug bosch
# Sobreescribir existentes:
python tools/process_logos.py --force
```

### Paso 4 — Generar data/logos.json

```bash
python tools/generate_data.py \
  --repo-url https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master
```

El archivo resultante `data/logos.json` contiene un array de objetos:

```json
[
  {
    "name": "Bosch",
    "slug": "bosch",
    "image": {
      "thumb":     "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/thumb/bosch.png",
      "optimized": "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/optimized/bosch.png",
      "original":  "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/original/bosch.png"
    }
  }
]
```

---

## Formato de metadata por marca

```json
{
  "brand": "bosch",
  "name": "Bosch",
  "count": 4,
  "sources": ["autodoc", "eurocarparts", "bing"]
}
```

---

## Scripts auxiliares

```bash
# Contar imagenes por marca
python tools/count.py --dataset-dir dataset --sync-metadata

# Verificar que cada marca tenga al menos una imagen valida
python tools/verify.py --brands-file brands-list.txt --dataset-dir dataset

# Eliminar duplicados con perceptual hashing
python tools/dedupe.py --dataset-dir dataset --threshold 4
```

## Convenciones del dataset

- Carpeta por marca con slug en minusculas (`bosch`, `mann-filter`, …)
- `logo.png` = logo canonico descargado por los scrapers de sitios
- `site.png` = logo extraido por `dom_logo_scraper`
- `001.png`, `002.png`, … = logos descargados via motores de busqueda
- Solo se conservan archivos validos y no corruptos

## Como contribuir

1. Agrega marcas nuevas en `brands-list.txt` (una por linea).
2. Ejecuta los scrapers de sitios y/o de motores de busqueda.
3. Corre `tools/process_logos.py` y `tools/generate_data.py`.
4. Corre `tools/verify.py` y `tools/dedupe.py` antes de abrir un PR.
5. Mantén el repositorio centrado en fabricantes de partes automotrices.
- Integracion con CI para validar que no se agreguen imagenes corruptas
