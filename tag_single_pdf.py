import os
import argparse
import sys
from pdfminer.high_level import extract_text
from openai import OpenAI
import io
import contextlib
from pyzotero import zotero
from dotenv import load_dotenv
from tags import TAG_LIST
import difflib

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Zotero client - for updating tags via API
library_id = os.getenv('ZOTERO_LIBRARY_ID')
library_type = 'user'  # or 'group'
api_key = os.getenv('ZOTERO_API_KEY')

# Validate required environment variables
if not all([os.getenv('OPENAI_API_KEY'), library_id, api_key]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

zot = zotero.Zotero(library_id, library_type, api_key)

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file."""
    try:
        # Check if file is actually a PDF before attempting extraction
        if not pdf_path.lower().endswith('.pdf'):
            return f"Not a PDF file: {os.path.basename(pdf_path)}"
            
        # Check file size (skip extremely large files)
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if file_size_mb > 50:  # Skip files larger than 50MB
            return f"PDF file too large ({file_size_mb:.1f}MB): {os.path.basename(pdf_path)}"
        
        # Try using the high-level extraction function
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return extract_text(pdf_path)
        except Exception as e:
            return f"Error extracting text: {str(e)}"
    except Exception as e:
        return f"Error accessing file: {str(e)}"

def get_relevant_tags(text, title="", abstract="", tag_list=TAG_LIST):
    """Use OpenAI to determine relevant tags."""
    # Create a prompt that explains the task
    prompt = f"""You are an expert research paper classifier specializing in AI and computer science papers. 
    Your task is to analyze the following research paper and assign relevant tags from this list: 
    
    <tag_list>
    {'\n '.join(tag_list)}
    </tag_list>
    
    Analysis Guidelines:
    1. Consider the entire paper holistically, including:
       - Title and abstract for main focus
       - Introduction for problem statement and motivation
       - Methods section for technical approaches
       - Results and discussion for applications and implications
       - Conclusion for final takeaways
    
    2. Tag Assignment Rules:
       - Only use tags from the provided list
       - BE CONSERVATIVE - only assign tags if you're confident they apply
       - Return tags as a comma-separated list
       - Assign tags based on both explicit mentions and implicit themes
       - Consider the paper's primary contributions and secondary aspects
       - Maximum 5 most relevant tags
    
    Paper to analyze:
    Title: {title}
    Abstract: {abstract}
    
    ###
    {text}
    ###

    Relevant tags (comma-separated, ordered by relevance):"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini-2025-04-14",
            messages=[
                {"role": "system", "content": "You are an expert research paper classifier that analyzes papers holistically and assigns comprehensive, relevant tags."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3  # Lower temperature for more consistent results
        )
        
        # Extract tags from response
        tags = [tag.strip() for tag in response.choices[0].message.content.split(',')]
        # Filter out any tags that aren't in our original list
        valid_tags = [tag for tag in tags if tag in tag_list]
        
        return valid_tags
    
    except Exception as e:
        print(f"Error getting tags from OpenAI: {str(e)}")
        return []

def update_item_tags(item_key, tags_to_add):
    """Update tags for a Zotero item using the API."""
    try:
        # Get the current item from the API
        item = zot.item(item_key)
        
        # Extract existing tags
        existing_tags = [t['tag'] for t in item['data'].get('tags', [])]
        
        # Add new tags
        new_tags = [{'tag': tag} for tag in tags_to_add if tag not in existing_tags]
        if new_tags:
            item['data']['tags'].extend(new_tags)
            zot.update_item(item)
            return True, f"Added tags: {', '.join([t['tag'] for t in new_tags])}"
        else:
            return False, "No new tags to add"
    except Exception as e:
        return False, f"Error updating via API: {str(e)}"

def get_zotero_item_by_pdf_path(pdf_path):
    """Try to find the Zotero item associated with the given PDF path."""
    try:
        # Get all items from Zotero library
        items = zot.items()
        
        # Get the PDF filename without path
        pdf_filename = os.path.basename(pdf_path)
        
        # Look for items with a matching PDF attachment
        for item in items:
            # Skip if not a regular item
            if item['data'].get('itemType') == 'attachment':
                continue
                
            # Check if this item has children (attachments)
            children = zot.children(item['key'])
            for child in children:
                # Check if this child is a PDF attachment
                if child['data'].get('itemType') == 'attachment' and child['data'].get('contentType') == 'application/pdf':
                    # Check if filename matches
                    if child['data'].get('filename') == pdf_filename:
                        return item
                    
        return None
    except Exception as e:
        print(f"Error searching for Zotero item: {str(e)}")
        return None

def find_similar_titles(title):
    """Find Zotero items with similar titles."""
    try:
        # Get all items from Zotero library
        items = zot.items()
        
        # Extract all titles
        all_titles = []
        title_to_item = {}
        
        for item in items:
            # Skip attachments
            if item['data'].get('itemType') == 'attachment':
                continue
            
            item_title = item['data'].get('title')
            if item_title:
                all_titles.append(item_title)
                title_to_item[item_title] = item
        
        # Find 5 most similar titles
        if title and all_titles:
            similar_titles = difflib.get_close_matches(title, all_titles, n=5, cutoff=0.4)
            return [(t, title_to_item[t]['key']) for t in similar_titles]
        
        return []
    except Exception as e:
        print(f"Error finding similar titles: {str(e)}")
        return []

def tag_pdf_file(pdf_path, item_key=None, title=None, abstract=None, preview_only=False):
    """Tag a single PDF file."""
    print(f"Processing PDF: {pdf_path}")
    
    # Extract text from PDF
    text = extract_text_from_pdf(pdf_path)
    
    # Check if extraction returned an error message
    if text.startswith(("Error", "Not a PDF", "PDF file too large")):
        print(f"Error: {text}")
        return False
    
    # Get relevant tags
    classification_text = f"Title: {title or 'Unknown'}\nAbstract: {abstract or ''}\nContent: {text}"
    relevant_tags = get_relevant_tags(text, title=title or "", abstract=abstract or "")
    
    print(f"\nSuggested tags: {', '.join(relevant_tags)}")
    
    # If preview only, don't update Zotero
    if preview_only:
        print("Preview only - no changes made to Zotero.")
        return True
    
    # Update tags in Zotero if item_key is provided
    if item_key:
        success, message = update_item_tags(item_key, relevant_tags)
        print(f"\nZotero update: {message}")
        return success
    else:
        print("\nNo Zotero item key provided - tags not added to Zotero.")
        return False

def main():
    parser = argparse.ArgumentParser(description="Tag a single PDF file using OpenAI and Zotero")
    parser.add_argument("pdf_path", help="Path to the PDF file to tag")
    parser.add_argument("--item-key", help="Zotero item key (if known)")
    parser.add_argument("--title", help="Document title (optional)")
    parser.add_argument("--abstract", help="Document abstract (optional)")
    parser.add_argument("--preview", action="store_true", help="Preview tags without updating Zotero")
    
    args = parser.parse_args()
    
    # Validate PDF path
    if not os.path.exists(args.pdf_path):
        print(f"Error: File not found: {args.pdf_path}")
        return 1
    
    item_key = args.item_key
    
    # If no item key provided, try to find item in Zotero
    if not item_key:
        print("No Zotero item key provided, searching for matching item...")
        item = get_zotero_item_by_pdf_path(args.pdf_path)
        if item:
            item_key = item['key']
            title = item['data'].get('title', args.title)
            abstract = item['data'].get('abstractNote', args.abstract)
            print(f"Found matching Zotero item: {title} (key: {item_key})")
        else:
            print("No matching Zotero item found.")
            title = args.title
            abstract = args.abstract
            
            # If title provided but no match, suggest similar titles
            if title:
                similar_titles = find_similar_titles(title)
                if similar_titles:
                    print("\nDid you mean one of these titles?")
                    for i, (similar_title, similar_key) in enumerate(similar_titles, 1):
                        print(f"{i}. {similar_title} (key: {similar_key})")
                    
                    try:
                        choice = input("\nEnter number to use that item (or press Enter to continue): ").strip()
                        if choice and choice.isdigit() and 0 < int(choice) <= len(similar_titles):
                            selected = similar_titles[int(choice) - 1]
                            item_key = selected[1]
                            title = selected[0]
                            try:
                                item = zot.item(item_key)
                                abstract = item['data'].get('abstractNote', abstract)
                                print(f"Selected: {title}")
                            except Exception as e:
                                print(f"Error getting item details: {str(e)}")
                    except KeyboardInterrupt:
                        print("\nSelection cancelled.")
    else:
        # If item key provided but no title/abstract, try to get from Zotero
        try:
            item = zot.item(item_key)
            title = item['data'].get('title', args.title)
            abstract = item['data'].get('abstractNote', args.abstract)
        except Exception as e:
            print(f"Error getting item details: {str(e)}")
            # If provided key is invalid, search for similar titles to the provided title
            if args.title:
                similar_titles = find_similar_titles(args.title)
                if similar_titles:
                    print("\nDid you mean one of these titles?")
                    for i, (similar_title, similar_key) in enumerate(similar_titles, 1):
                        print(f"{i}. {similar_title} (key: {similar_key})")
                    
                    try:
                        choice = input("\nEnter number to use that item (or press Enter to continue): ").strip()
                        if choice and choice.isdigit() and 0 < int(choice) <= len(similar_titles):
                            selected = similar_titles[int(choice) - 1]
                            item_key = selected[1]
                            title = selected[0]
                            try:
                                item = zot.item(item_key)
                                abstract = item['data'].get('abstractNote', abstract)
                                print(f"Selected: {title}")
                            except Exception:
                                pass
                    except KeyboardInterrupt:
                        print("\nSelection cancelled.")
            
            title = args.title
            abstract = args.abstract
    
    # Tag the PDF
    success = tag_pdf_file(
        args.pdf_path, 
        item_key=item_key,
        title=title,
        abstract=abstract,
        preview_only=args.preview
    )
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main()) 