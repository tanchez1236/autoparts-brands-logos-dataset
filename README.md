# Autoparts Brands Logos Dataset

An open dataset of auto parts brand logos, generated through automated scraping,
image cleaning, and validation.

Each brand logo is published in three ready-to-use variants:

- `thumb` (max 100 px)
- `optimized` (max 240 px)
- `original` (full available resolution)

## Quick Usage

Each brand is represented as one entry in `data/logos.json`:

```json
{
  "name": "Bosch",
  "slug": "bosch",
  "image": {
    "thumb": "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/thumb/bosch.png",
    "optimized": "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/optimized/bosch.png",
    "original": "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master/logos/original/bosch.png"
  }
}
```

## Repository Structure

```text
autoparts-brands-logos-dataset/
├── brands-list.txt
├── requirements.txt
├── data/
│   └── logos.json
├── logos/
│   ├── original/
│   ├── optimized/
│   └── thumb/
├── dataset/
│   └── <slug>/
│       ├── logo.png
│       ├── 001.png ...
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
    ├── process_logos.py
    ├── generate_data.py
    ├── count.py
    ├── dedupe.py
    └── verify.py
```

## Legal Notice

All logos are trademarks of their respective owners.

This dataset is provided for research, educational, and machine-learning
purposes. Before using logos in products, marketing, or publications, review the
applicable license terms, trademark policies, and source website terms.

## Dataset Scope

Focused on automotive aftermarket and parts brands, including categories such as:

- Braking, suspension, and steering
- Filters, lubrication, and seals
- Ignition, injection, and automotive electronics
- Lighting, HVAC, and cooling
- Bearings, transmissions, and engine components
- Batteries, tires, and technical accessories

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Full Pipeline

### 1. Scrape logos from auto parts websites

Site scrapers download canonical logos directly into `dataset/<slug>/logo.png`.

```bash
# autodoc.es
python scrapers/autodoc_scraper.py --dataset-dir dataset

# rockauto.com
python scrapers/rockauto_scraper.py --dataset-dir dataset

# eurocarparts.com/brands
python scrapers/eurocarparts_scraper.py --dataset-dir dataset
```

### 2. (Optional) Enrich with search engines

If a brand is missing from catalog sources, you can fetch additional logos from
Google or Bing image APIs.

```bash
# Google Custom Search
export GOOGLE_CUSTOM_SEARCH_API_KEY="your_api_key"
export GOOGLE_CUSTOM_SEARCH_CX="your_cx"
python scrapers/google_images_scraper.py \
  --brands-file brands-list.txt --dataset-dir dataset --per-brand 5

# Bing Image Search
export BING_IMAGE_SEARCH_API_KEY="your_api_key"
python scrapers/bing_scraper.py \
  --brands-file brands-list.txt --dataset-dir dataset --per-brand 5
```

For a specific official domain:

```bash
python scrapers/dom_logo_scraper.py \
  --brand "Bosch" \
  --domain "https://www.boschaftermarket.com" \
  --dataset-dir dataset
```

### 3. Build publishable logo variants

```bash
python tools/process_logos.py

# Single brand
python tools/process_logos.py --slug bosch

# Overwrite existing outputs
python tools/process_logos.py --force
```

### 4. Generate `data/logos.json`

```bash
python tools/generate_data.py \
  --repo-url https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master
```

## Brand Metadata Format

`dataset/<slug>/metadata.json` typically follows:

```json
{
  "brand": "bosch",
  "name": "Bosch",
  "count": 4,
  "sources": ["autodoc", "eurocarparts", "bing"]
}
```

## Utility Scripts

```bash
# Count images by brand and sync metadata counters
python tools/count.py --dataset-dir dataset --sync-metadata

# Verify each brand has at least one valid image
python tools/verify.py --brands-file brands-list.txt --dataset-dir dataset

# Add or update a brand logo
python tools/manage_logos.py --action add --brand "Bosch" --logo /path/to/logo.png --generate-data
python tools/manage_logos.py --action update --brand "Bosch" --logo /path/to/new-logo.png --generate-data

# Remove near-duplicates using perceptual hashing
python tools/dedupe.py --dataset-dir dataset --threshold 4
```

## Dataset Conventions

- One folder per brand slug (`bosch`, `mann-filter`, etc.)
- `logo.png` is the canonical logo from site scrapers
- `site.png` is extracted by `dom_logo_scraper`
- `001.png`, `002.png`, etc. are search-engine results
- Invalid/corrupt files should not be kept

## Contributing

Contributions are welcome.

Please use a fork + feature branch + pull request workflow so changes can be
reviewed and integrated cleanly.

1. Fork this repository.
2. Create a branch from `main` in your fork (for example: `feat/add-new-brands`).
3. Make your changes and run the full data pipeline when relevant.
4. Run validation tools before opening a PR:

```bash
python tools/verify.py --brands-file brands-list.txt --dataset-dir dataset
python tools/dedupe.py --dataset-dir dataset --threshold 4
```

5. Open a Pull Request with a clear summary of what changed.

If your PR is approved, it can be merged and incorporated into future dataset
updates.
