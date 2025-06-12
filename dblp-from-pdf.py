#!/usr/bin/env python3
"""
DBLP PDF Citation Extractor - Extract citations from PDFs and add them to BibTeX files using DBLP.
"""

import re
import requests
import time
import argparse
import sys
from pathlib import Path
import bibtexparser
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter
from bibtexparser.bibdatabase import BibDatabase
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
import pypdf
from pypdf import PdfReader

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
        # Handle DBLP author format (dictionary with @pid and text)
        if isinstance(authors2, dict) and 'author' in authors2:
            if isinstance(authors2['author'], list):
                authors2 = [a.get('text', '') for a in authors2['author']]
            else:
                authors2 = [authors2['author'].get('text', '')]
        else:
            authors2 = [normalize_author_name(a) for a in authors2]
    
    # If we have a single author in both lists, use a more lenient comparison
    if len(authors1) == 1 and len(authors2) == 1:
        # Try exact match first
        if authors1[0] == authors2[0]:
            return 100.0
        # Try partial match
        if authors1[0] in authors2[0] or authors2[0] in authors1[0]:
            return 90.0
        # Try fuzzy match with a lower threshold
        similarity = fuzz.token_sort_ratio(authors1[0], authors2[0])
        return similarity if similarity > 60 else 0.0
    
    # Calculate similarity for each author pair
    total_similarity = 0
    for a1 in authors1:
        best_match = process.extractOne(a1, authors2, scorer=fuzz.token_sort_ratio)
        total_similarity += best_match[1] if best_match else 0
    
    # Return average similarity
    return total_similarity / len(authors1)

def fetch_dblp_entry(title, original_authors=None):
    """
    Fetch the BibTeX entry from DBLP for a given title.
    
    Args:
        title (str): The title of the publication to search for
        original_authors (str): Original authors for fuzzy matching
        
    Returns:
        str: The BibTeX entry if found, None otherwise
    """
    # Format the title for the DBLP API query
    query = '+'.join(title.split())
    url = f"https://dblp.org/search/publ/api?q={query}&format=json"

    try:
        response = requests.get(url)
        response.raise_for_status()
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
                    similarity = get_author_similarity(original_authors, info['authors'])
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = hit
            
            if best_similarity >= 60:  # Lowered threshold from 70 to 60
                print(f"Found {total_matches} matches - using best author match (similarity: {best_similarity:.1f}%)")
                bibtex_url = best_match['info']['url'] + '.bib'
                bibtex_response = requests.get(bibtex_url)
                bibtex_response.raise_for_status()
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
                similarity = get_author_similarity(original_authors, info['authors'])
                if similarity < 60:  # Lowered threshold from 70 to 60
                    print(f"Single match found but author similarity too low ({similarity:.1f}%) - skipping")
                    return None
                print(f"Single match found with good author similarity ({similarity:.1f}%)")
            
            bibtex_url = info['url'] + '.bib'
            bibtex_response = requests.get(bibtex_url)
            bibtex_response.raise_for_status()
            return bibtex_response.text
    except requests.RequestException as e:
        print(f"Error fetching data from DBLP: {e}", file=sys.stderr)
        return None

def extract_pdf_metadata(pdf_path):
    """
    Extract title and authors from a PDF file.
    
    Args:
        pdf_path (Path): Path to the PDF file
        
    Returns:
        tuple: (title, authors) or (None, None) if extraction fails
    """
    try:
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            
            # Try to get metadata from PDF properties
            metadata = reader.metadata
            title = None
            authors = None
            
            if metadata:
                title = metadata.get('/Title', None)
                author = metadata.get('/Author', None)
                if author:
                    authors = author
            
            # If metadata doesn't contain title or authors, try to extract from first page
            if (not title or not authors) and len(reader.pages) > 0:
                first_page = reader.pages[0]
                text = first_page.extract_text()
                
                # Split into lines and clean them
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                
                # Look for title in the first few lines
                if not title:
                    # Skip lines that are likely not titles
                    skip_patterns = [
                        r'^[0-9\s\-]+$',  # Just numbers and dashes
                        r'^abstract$',     # Abstract header
                        r'^introduction$', # Introduction header
                        r'^page\s+\d+$',   # Page numbers
                        r'^proceedings',   # Proceedings lines
                        r'^copyright',     # Copyright notices
                        r'^\d{4}$',        # Just a year
                    ]
                    
                    # First pass: look for lines that look like titles
                    potential_titles = []
                    for i, line in enumerate(lines[:15]):  # Look in first 15 lines
                        # Skip if line matches any skip pattern
                        if any(re.match(pattern, line.lower()) for pattern in skip_patterns):
                            continue
                            
                        # Look for lines that might be titles
                        if (len(line) > 15 and  # Not too short
                            len(line) < 200 and  # Not too long
                            not line.isdigit() and  # Not just numbers
                            not re.search(r'@[a-zA-Z0-9._%+-]+@', line) and  # No email addresses
                            not re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', line)):  # No URLs
                            
                            potential_titles.append((i, line))
                    
                    # Second pass: analyze potential titles to find the best one
                    if potential_titles:
                        # Look for patterns that indicate a title
                        title_indicators = [
                            r'^[A-Z][^a-z]*$',  # All caps (likely a title)
                            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*$',  # Title case
                            r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*:',  # Title case with colon
                        ]
                        
                        # Score each potential title
                        scored_titles = []
                        for i, line in potential_titles:
                            score = 0
                            # Higher score for lines that look more like titles
                            if any(re.match(pattern, line) for pattern in title_indicators):
                                score += 2
                            # Higher score for lines that are not too long
                            if len(line) < 100:
                                score += 1
                            # Higher score for lines that don't contain certain words
                            if not re.search(r'editors?|proceedings|conference|workshop|symposium', line.lower()):
                                score += 1
                            # Higher score for lines that are earlier in the document
                            score += (15 - i) / 15
                            
                            scored_titles.append((score, line))
                        
                        # Choose the highest scoring title
                        if scored_titles:
                            title = max(scored_titles, key=lambda x: x[0])[1]
                
                # Try to extract authors from text if not found in metadata
                if not authors:
                    # Look for author patterns after title
                    author_patterns = [
                        r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s+and\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*$',  # Names with "and"
                        r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s*,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*$',  # Names with commas
                        r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:\s*;\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)*$',  # Names with semicolons
                    ]
                    
                    # Look in lines after the title
                    title_index = next((i for i, line in enumerate(lines) if line == title), -1)
                    if title_index >= 0:
                        for line in lines[title_index + 1:title_index + 10]:  # Look in next 10 lines
                            # Skip if line looks like a title or other non-author text
                            if (len(line) > 100 or  # Too long
                                re.search(r'abstract|introduction|keywords|email|@|http', line.lower()) or
                                re.match(r'^[0-9\s\-]+$', line)):
                                continue
                                
                            # Check if line matches any author pattern
                            if any(re.match(pattern, line) for pattern in author_patterns):
                                authors = line
                                break
            
            # Clean up extracted data
            if title:
                title = re.sub(r'\s+', ' ', title).strip()
                # Remove common unwanted patterns
                title = re.sub(r'^(the\s+)?paper\s+', '', title, flags=re.IGNORECASE)
                # Remove any remaining editor information
                title = re.sub(r'\s*\(eds?\.\)\s*$', '', title, flags=re.IGNORECASE)
                # Remove any remaining colons at the end
                title = re.sub(r'\s*:\s*$', '', title)
                
            if authors:
                authors = re.sub(r'\s+', ' ', authors).strip()
                # Remove common prefixes/suffixes
                authors = re.sub(r'^(by\s+|authors?\s*:?\s*)', '', authors, flags=re.IGNORECASE)
                # Normalize separators
                authors = re.sub(r'\s*;\s*', ' and ', authors)
                authors = re.sub(r'\s*,\s*(?=[A-Z])', ' and ', authors)
                
            return title, authors
            
    except Exception as e:
        print(f"Error reading PDF {pdf_path}: {e}")
        return None, None

def load_existing_bib(bib_file):
    """
    Load existing BibTeX file and return database and list of titles.
    
    Args:
        bib_file (Path): Path to the BibTeX file
        
    Returns:
        tuple: (BibDatabase, set of normalized titles)
    """
    if not bib_file.exists():
        # Create empty database if file doesn't exist
        return BibDatabase(), set()
    
    try:
        parser = BibTexParser(common_strings=True)
        parser.ignore_nonstandard_types = False
        parser.homogenise_fields = False
        
        with open(bib_file, 'r', encoding='utf-8') as f:
            bib_database = bibtexparser.load(f, parser=parser)
        
        # Extract existing titles for comparison
        existing_titles = set()
        for entry in bib_database.entries:
            if 'title' in entry:
                title = ' '.join(entry['title'].split()).lower()
                existing_titles.add(title)
        
        return bib_database, existing_titles
        
    except Exception as e:
        print(f"Error loading existing BibTeX file: {e}")
        return BibDatabase(), set()

def update_bib_file(bib_file, new_entries):
    """
    Update the BibTeX file with new entries.
    
    Args:
        bib_file (Path): Path to the BibTeX file
        new_entries (list): List of new BibTeX entries to add
    """
    if not new_entries:
        return
    
    try:
        # Read existing content
        existing_content = ""
        if bib_file.exists():
            with open(bib_file, 'r', encoding='utf-8') as f:
                existing_content = f.read().strip()
        
        # Write updated content
        with open(bib_file, 'w', encoding='utf-8') as f:
            if existing_content:
                f.write(existing_content)
                f.write('\n\n')
            f.write('\n\n'.join(new_entries))
            f.write('\n')
            
    except IOError as e:
        print(f"Error writing to BibTeX file: {e}", file=sys.stderr)
        sys.exit(1)

def process_pdfs(pdf_files, bib_file):
    """
    Process a list of PDF files and update the BibTeX file with new entries.
    
    Args:
        pdf_files (list): List of PDF file paths
        bib_file (str): Path to the BibTeX file to update
    """
    bib_path = Path(bib_file)
    
    # Load existing bibliography
    bib_database, existing_titles = load_existing_bib(bib_path)
    
    new_entries = []
    processed_count = 0
    found_count = 0
    already_exists_count = 0
    failed_extraction_count = 0
    failed_lookup_count = 0
    
    failed_pdfs = []
    
    print(f"\nProcessing {len(pdf_files)} PDF files:")
    print("-" * 80)
    
    for i, pdf_file in enumerate(pdf_files):
        pdf_path = Path(pdf_file)
        processed_count += 1
        
        print(f"\nProcessing PDF {processed_count}/{len(pdf_files)}: {pdf_path.name}")
        
        if not pdf_path.exists():
            print(f"Status: ✗ File not found")
            failed_pdfs.append((pdf_file, "File not found"))
            continue
        
        # Extract metadata from PDF
        title, authors = extract_pdf_metadata(pdf_path)
        
        if not title:
            print(f"Status: ✗ Could not extract title from PDF")
            failed_pdfs.append((pdf_file, "Could not extract title"))
            failed_extraction_count += 1
            continue
        
        print(f"Extracted title: {title}")
        if authors:
            print(f"Extracted authors: {authors}")
        
        # Check if this paper is already in the bibliography
        normalized_title = ' '.join(title.split()).lower()
        if normalized_title in existing_titles:
            print(f"Status: ℹ Already exists in bibliography - Skipping")
            already_exists_count += 1
            continue
        
        # Look up in DBLP
        dblp_entry = fetch_dblp_entry(title, authors)
        if dblp_entry:
            print("Status: ✓ Found in DBLP - Adding to bibliography")
            new_entries.append(dblp_entry)
            existing_titles.add(normalized_title)  # Prevent duplicates within this run
            found_count += 1
        else:
            print("Status: ✗ Not found in DBLP")
            failed_pdfs.append((pdf_file, "Not found in DBLP"))
            failed_lookup_count += 1
        
        # Add delay to avoid overwhelming DBLP
        time.sleep(1)
    
    # Update the BibTeX file with new entries
    if new_entries:
        update_bib_file(bib_path, new_entries)
    
    # Print summary
    print("\n" + "=" * 80)
    print("Processing Summary:")
    print(f"Total PDFs processed: {processed_count}")
    print(f"New entries found and added: {found_count}")
    print(f"Entries already in bibliography: {already_exists_count}")
    print(f"Failed to extract metadata: {failed_extraction_count}")
    print(f"Failed DBLP lookup: {failed_lookup_count}")
    
    if new_entries:
        print(f"\nSuccessfully added {len(new_entries)} new entries to {bib_file}")
    
    if failed_pdfs:
        print(f"\nFailed to process {len(failed_pdfs)} PDFs:")
        for pdf_file, reason in failed_pdfs:
            print(f"  • {Path(pdf_file).name}: {reason}")
    
    print("=" * 80)

def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Extract citations from PDFs and add them to BibTeX files using DBLP',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('bib_file', help='BibTeX file to update (will be created if it doesn\'t exist)')
    parser.add_argument('pdf_files', nargs='+', help='PDF files to process')
    
    args = parser.parse_args()
    
    # Validate PDF files
    valid_pdfs = []
    for pdf_file in args.pdf_files:
        pdf_path = Path(pdf_file)
        if pdf_path.exists() and pdf_path.suffix.lower() == '.pdf':
            valid_pdfs.append(pdf_file)
        else:
            print(f"Warning: Skipping {pdf_file} (not a valid PDF file)")
    
    if not valid_pdfs:
        print("Error: No valid PDF files provided", file=sys.stderr)
        sys.exit(1)
    
    process_pdfs(valid_pdfs, args.bib_file)

if __name__ == '__main__':
    main() 