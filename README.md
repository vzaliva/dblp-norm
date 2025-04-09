# DBLP BibTeX Normaliser

A Python tool for normalising BibTeX entries by querying the DBLP database.

## Description

This tool automates the process of normalising BibTeX entries by:
1. Reading an input BibTeX file
2. Querying the DBLP database for each entry
3. Replacing entries with their DBLP counterparts when found
4. Writing the normalised entries to an output file

Entries are retrieved using the title, with supplementary fuzzy author checks employed to resolve ambiguities and ensure accuracy.

## Prerequisites

- Python 3.8 or higher
- pip (Python package installer)

## Installation

1. Clone this repository:
```bash
git clone [repository-url]
cd dblp-norm
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows, use: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

```bash
python src/dblp-norm/dblp-norm.py input.bib output.bib
```

Where:
- `input.bib` is your source BibTeX file
- `output.bib` is the destination file for normalised entries

## License

GPLv3

