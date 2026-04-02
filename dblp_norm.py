#!/usr/bin/env python3
"""
DBLP BibTeX Normaliser - A tool to normalise BibTeX entries using DBLP.
"""

import re
import requests
import time
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

DBLP_MIRRORS = ['dblp.org', 'dblp.uni-trier.de', 'dblp.dagstuhl.de']

def dblp_get(url, max_retries=3):
    """GET a URL, honouring 429 Retry-After headers."""
    for attempt in range(max_retries):
        response = requests.get(url)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            print(f"Rate-limited (429), waiting {retry_after}s before retry...")
            time.sleep(retry_after)
            continue
        response.raise_for_status()
        time.sleep(1)
        return response
    raise requests.RequestException("DBLP rate limit: max retries exceeded")

def rewrite_dblp_url(url, base_url):
    """Replace the host in a DBLP URL with the chosen mirror base."""
    parsed = urlparse(url)
    base_parsed = urlparse(base_url)
    return urlunparse(parsed._replace(scheme=base_parsed.scheme, netloc=base_parsed.netloc))

def normalize_author_name(name):
    """Normalize author name for comparison."""
    # Handle DBLP author format (dictionary)
    if isinstance(name, dict):
        name = name.get('text', '')
    # Convert to lowercase and remove extra spaces
    return ' '.join(str(name).lower().split())

def get_author_similarity(authors1, authors2):
    """Calculate similarity between two author lists."""
    if not authors1 or not authors2:
        return 0.0
        
    # Normalize and split authors
    if isinstance(authors1, str):
        authors1 = [normalize_author_name(a) for a in authors1.split(' and ')]
    else:
        authors1 = [normalize_author_name(a) for a in authors1]
        
    if isinstance(authors2, str):
        authors2 = [normalize_author_name(a) for a in authors2.split(' and ')]
    else:
        authors2 = [normalize_author_name(a) for a in authors2]
    
    # Calculate similarity for each author pair
    total_similarity = 0
    for a1 in authors1:
        best_match = process.extractOne(a1, authors2, scorer=fuzz.token_sort_ratio)
        total_similarity += best_match[1] if best_match else 0
    
    # Return average similarity
    return total_similarity / len(authors1)

def fetch_dblp_entry(title, original_authors=None, base_url="https://dblp.org"):
    """
    Fetch the BibTeX entry from DBLP for a given title.

    Args:
        title (str): The title of the publication to search for
        original_authors (str): Original authors for fuzzy matching
        base_url (str): DBLP mirror base URL

    Returns:
        str: The BibTeX entry if found, None otherwise
    """
    # Format the title for the DBLP API query
    query = '+'.join(title.split())
    url = f"{base_url}/search/publ/api?q={query}&format=json"

    try:
        response = dblp_get(url)
        data = response.json()

        # Check if there are any matches
        total_matches = int(data['result']['hits']['@total'])
        if total_matches == 0:
            return None
        elif total_matches > 1 and original_authors:
            # If we have multiple matches and original authors, try to find the best match
            best_match = None
            best_similarity = 0
            for hit in data['result']['hits']['hit']:
                info = hit['info']
                if 'authors' in info:
                    similarity = get_author_similarity(original_authors, info['authors']['author'])
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = hit

            if best_similarity >= 70:  # Threshold for considering it a good match
                print(f"Found {total_matches} matches - using best author match (similarity: {best_similarity:.1f}%)")
                bibtex_url = rewrite_dblp_url(best_match['info']['url'] + '.bib', base_url)
                bibtex_response = dblp_get(bibtex_url)
                return bibtex_response.text
            else:
                print(f"Found {total_matches} matches - no good author match found (best similarity: {best_similarity:.1f}%)")
                return None
        elif total_matches > 1:
            # Skip if multiple matches found and no authors to compare
            print(f"Found {total_matches} matches - skipping to avoid ambiguity")
            return None
        else:
            # Get the first (and only) match
            hit = data['result']['hits']['hit'][0]
            info = hit['info']

            # Check author similarity even for single match
            if original_authors and 'authors' in info:
                similarity = get_author_similarity(original_authors, info['authors']['author'])
                if similarity < 70:
                    print(f"Single match found but author similarity too low ({similarity:.1f}%) - skipping")
                    return None
                print(f"Single match found with good author similarity ({similarity:.1f}%)")

            bibtex_url = rewrite_dblp_url(info['url'] + '.bib', base_url)
            bibtex_response = dblp_get(bibtex_url)
            return bibtex_response.text
    except requests.RequestException as e:
        print(f"Error fetching data from DBLP: {e}", file=sys.stderr)
        return None

def normalize_bibtex_file(input_file, output_file, base_url="https://dblp.org"):
    """
    Normalize the BibTeX entries in the input file using DBLP and write to the output file.
    
    Args:
        input_file (str): Path to the input BibTeX file
        output_file (str): Path to the output BibTeX file
    """
    input_path = Path(input_file)
    output_path = Path(output_file)
    
    if not input_path.exists():
        print(f"Error: Input file '{input_file}' does not exist", file=sys.stderr)
        sys.exit(1)
        
    try:
        # Configure parser to preserve case and handle common strings
        parser = BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        parser.homogenise_fields = False
        
        with open(input_path, 'r', encoding='utf-8') as f:
            bib_database = bibtexparser.load(f, parser=parser)
    except Exception as e:
        print(f"Error parsing input file: {e}", file=sys.stderr)
        sys.exit(1)

    normalized_entries = []
    total_entries = len(bib_database.entries)
    processed = 0
    replaced = 0
    kept = 0
    skipped = 0
    already_dblp = 0

    print("\nProcessing entries:")
    print("-" * 80)

    for entry in bib_database.entries:
        processed += 1
        
        if 'title' in entry:
            # Check if entry is already from DBLP
            if 'bibsource' in entry and 'dblp computer science bibliography' in entry['bibsource'].lower():
                print(f"\nEntry {processed}/{total_entries}")
                print(f"Title: {' '.join(entry['title'].split())}")
                print("Status: ℹ Already from DBLP - Keeping original entry")
                # Convert entry back to BibTeX string
                db = BibDatabase()
                db.entries = [entry]
                writer = BibTexWriter()
                normalized_entries.append(writer.write(db).strip())
                already_dblp += 1
                continue

            # Clean title by removing line feeds and extra spaces
            title = ' '.join(entry['title'].split())
            print(f"\nEntry {processed}/{total_entries}")
            print(f"Title: {title}")
            
            # Get original authors if available
            original_authors = entry.get('author', None)
            
            # Fetch the DBLP entry using cleaned title and authors
            dblp_entry = fetch_dblp_entry(title, original_authors, base_url)
            if dblp_entry:
                print("Status: ✓ Found in DBLP - Entry replaced")
                normalized_entries.append(dblp_entry)
                replaced += 1
            else:
                print("Status: ✗ Not found in DBLP - Keeping original entry")
                # Convert entry back to BibTeX string
                db = BibDatabase()
                db.entries = [entry]
                writer = BibTexWriter()
                normalized_entries.append(writer.write(db).strip())
                kept += 1
        else:
            print(f"\nEntry {processed}/{total_entries}")
            print("Status: ⚠ No title found - Keeping original entry")
            print("Entry content:")
            print(entry)
            # Convert entry back to BibTeX string
            db = BibDatabase()
            db.entries = [entry]
            writer = BibTexWriter()
            normalized_entries.append(writer.write(db).strip())
            kept += 1

        # Delay is handled inside dblp_get() after each request

    # Write the normalized entries to the output file
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(normalized_entries))
        print("\n" + "=" * 80)
        print(f"Processing complete!")
        print(f"Total entries processed: {total_entries}")
        print(f"Entries already from DBLP: {already_dblp}")
        print(f"Entries replaced with DBLP versions: {replaced}")
        print(f"Entries skipped due to multiple matches: {skipped}")
        print(f"Original entries kept: {kept}")
        print(f"Successfully wrote normalised entries to {output_file}")
        print("=" * 80)
    except IOError as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Normalise BibTeX entries using DBLP',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('input_file', help='Input BibTeX file')
    parser.add_argument('output_file', nargs='?', default=None,
                        help='Output BibTeX file (default: overwrite input after creating .bak backup)')
    parser.add_argument('--mirror', choices=DBLP_MIRRORS,
                        default='dblp.org', help='DBLP mirror to use')

    args = parser.parse_args()

    base_url = f"https://{args.mirror}"

    if args.output_file is None:
        import shutil
        backup = args.input_file + '.bak'
        shutil.copy2(args.input_file, backup)
        print(f"Backed up {args.input_file} to {backup}")
        normalize_bibtex_file(args.input_file, args.input_file, base_url)
    else:
        normalize_bibtex_file(args.input_file, args.output_file, base_url)

if __name__ == '__main__':
    main()
