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

### Normalise an Existing BibTeX File

```bash
python dblp-norm.py input.bib output.bib
```

Where:
- `input.bib` is your source BibTeX file
- `output.bib` is the destination file for normalised entries

### Extract and Add BibTeX Entries from PDFs

You can also extract titles and authors from PDF files, look up their citations in DBLP, and add any missing entries to your BibTeX file:

```bash
python dblp-from-pdf.py refs.bib paper1.pdf paper2.pdf ...
```

Where:
- `refs.bib` is your BibTeX file (will be created if it does not exist)
- `paper1.pdf`, `paper2.pdf`, ... are the PDF files to process

The script will:
- Extract the title and authors from each PDF
- Query DBLP for a matching citation
- Add new entries to the BibTeX file if not already present
- Report any PDFs it could not process or find in DBLP

## License

GPLv3

