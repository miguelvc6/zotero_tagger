import os
import sqlite3
import json
from pdfminer.high_level import extract_text
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from openai import OpenAI
import time
from dotenv import load_dotenv
from tqdm import tqdm
from pyzotero import zotero
import io
import sys
import contextlib
from tags import TAG_LIST

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

# Default path to Zotero data directory - adjust as needed
ZOTERO_DATA_DIR = os.path.join("C:\\", "Users", "vazquez", "Zotero")
ZOTERO_STORAGE_DIR = os.path.join(ZOTERO_DATA_DIR, "storage")
ZOTERO_DB_PATH = os.path.join(ZOTERO_DATA_DIR, "zotero.sqlite")

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file using a more robust approach."""
    try:
        # Check if file is actually a PDF before attempting extraction
        if not pdf_path.lower().endswith('.pdf'):
            return f"Not a PDF file: {os.path.basename(pdf_path)}"
            
        # Check file size (skip extremely large files)
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if file_size_mb > 50:  # Skip files larger than 50MB
            return f"PDF file too large ({file_size_mb:.1f}MB): {os.path.basename(pdf_path)}"
        
        # First try using the high-level function
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                return extract_text(pdf_path)
        except Exception as high_level_error:
            # If that fails, try a more robust approach with lower-level components
            try:
                output_string = io.StringIO()
                with open(pdf_path, 'rb') as in_file:
                    # Setup PDF resources
                    resource_manager = PDFResourceManager()
                    device = TextConverter(resource_manager, output_string, laparams=LAParams())
                    interpreter = PDFPageInterpreter(resource_manager, device)
                    
                    # Process each page
                    for page in PDFPage.get_pages(in_file, check_extractable=True):
                        try:
                            interpreter.process_page(page)
                        except:
                            # Skip problematic pages
                            continue
                            
                    # Get text
                    text = output_string.getvalue()
                    device.close()
                    output_string.close()
                    
                    if text.strip():
                        return text
                    else:
                        return f"Extracted empty text (fallback method): {str(high_level_error)}"
            except Exception as fallback_error:
                return f"Error extracting text (both methods failed): {str(high_level_error)} | {str(fallback_error)}"
    except Exception as e:
        return f"Error accessing file: {str(e)}"

def get_relevant_tags(text, tag_list):
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

def get_zotero_library_data():
    """Get item data directly from the Zotero SQLite database."""
    conn = sqlite3.connect(ZOTERO_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Query to get all items with their metadata
    query = """
    SELECT i.itemID, i.key, i.libraryID, i.itemTypeID, it.typeName, 
           COALESCE((SELECT value FROM itemData id 
            JOIN itemDataValues idv ON id.valueID = idv.valueID 
            JOIN fields f ON id.fieldID = f.fieldID 
            WHERE id.itemID = i.itemID AND f.fieldName = 'title'
            LIMIT 1), 'Untitled') as title,
           COALESCE((SELECT value FROM itemData id 
            JOIN itemDataValues idv ON id.valueID = idv.valueID 
            JOIN fields f ON id.fieldID = f.fieldID 
            WHERE id.itemID = i.itemID AND f.fieldName = 'abstractNote'
            LIMIT 1), '') as abstract
    FROM items i
    JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
    WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
    """
    cursor.execute(query)
    items = cursor.fetchall()
    
    # Query to get all attachments
    query_attachments = """
    SELECT ia.itemID, ia.parentItemID, i.key, ia.path, it.typeName, ia.contentType
    FROM itemAttachments ia
    JOIN items i ON ia.itemID = i.itemID
    JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
    WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
    """
    cursor.execute(query_attachments)
    attachments = cursor.fetchall()
    
    # Query to get all tags
    query_tags = """
    SELECT ti.itemID, t.name
    FROM tags t
    JOIN itemTags ti ON t.tagID = ti.tagID
    """
    cursor.execute(query_tags)
    tags = cursor.fetchall()
    
    # Create dictionary of items with their tags
    item_tags = {}
    for tag in tags:
        item_id = tag['itemID']
        if item_id not in item_tags:
            item_tags[item_id] = []
        item_tags[item_id].append(tag['name'])
    
    # Create dictionary of items with their attachments
    item_attachments = {}
    for attachment in attachments:
        parent_id = attachment['parentItemID']
        if parent_id not in item_attachments:
            item_attachments[parent_id] = []
        item_attachments[parent_id].append(dict(attachment))
    
    # Build comprehensive item data
    result = []
    for item in items:
        item_id = item['itemID']
        # Skip attachment items themselves
        if item['typeName'] == 'attachment':
            continue
            
        item_data = dict(item)
        item_data['tags'] = item_tags.get(item_id, [])
        item_data['attachments'] = item_attachments.get(item_id, [])
        result.append(item_data)
    
    conn.close()
    return result

def update_tags_in_db(item_id, item_key, tags_to_add):
    """Update tags for an item using the Zotero API."""
    try:
        # First get the current item from the API to ensure we have the latest version
        item = zot.item(item_key)
        
        # Extract existing tags
        existing_tags = [t['tag'] for t in item['data'].get('tags', [])]
        
        # Add new tags
        new_tags = [{'tag': tag} for tag in tags_to_add if tag not in existing_tags]
        if new_tags:
            item['data']['tags'].extend(new_tags)
            try:
                zot.update_item(item)
                return True, f"Added tags: {', '.join([t['tag'] for t in new_tags])}"
            except Exception as e:
                return False, f"Error updating via API: {str(e)}"
        else:
            return False, "No new tags to add"
    except Exception as e:
        return False, f"Error getting item from API: {str(e)}"

def process_local_pdfs(limit=None):
    """Process PDFs from local Zotero storage directory."""
    # Get data from Zotero database
    items = get_zotero_library_data()
    processed = 0
    pdfs_not_found = 0
    error_count = 0
    error_types = {}
    
    print(f"\nStarting test run with {limit if limit else 'all'} items...\n")
    print(f"Found {len(items)} total items in Zotero database")
    
    # Filter items to only include those with PDF attachments
    items_with_pdfs = []
    for item in items:
        has_pdf_attachment = False
        for attachment in item.get('attachments', []):
            # Check if this might be a PDF attachment
            content_type = attachment.get('contentType', '')
            if content_type == 'application/pdf':
                has_pdf_attachment = True
                break
            elif 'path' in attachment:
                path = attachment.get('path', '')
                # Only consider actual PDF files (not HTML or other types)
                if path and path.lower().endswith('.pdf'):
                    has_pdf_attachment = True
                    break
                # Also check attachment key directory for PDFs
                elif attachment.get('key'):
                    attachment_key = attachment.get('key')
                    possible_path = os.path.join(ZOTERO_STORAGE_DIR, attachment_key)
                    if os.path.isdir(possible_path):
                        try:
                            files = os.listdir(possible_path)
                            pdf_files = [f for f in files if f.lower().endswith('.pdf')]
                            if pdf_files:
                                has_pdf_attachment = True
                                break
                        except:
                            pass
        if has_pdf_attachment:
            items_with_pdfs.append(item)
    
    print(f"Found {len(items_with_pdfs)} items with PDF attachments")
    
    # Create a progress bar with the appropriate total
    total_items = min(limit, len(items_with_pdfs)) if limit is not None else len(items_with_pdfs)
    pbar = tqdm(total=total_items, desc="Processing papers with PDFs")
    
    for item in items_with_pdfs[:total_items]:
        title = item.get('title', 'Untitled')
        
        # Make sure title is not None before checking its length
        if title is None:
            title = 'Untitled'
            
        pbar.set_description(f"Processing: {title[:30]}..." if len(title) > 30 else f"Processing: {title}")
        
        # Process PDF attachments
        has_processed_pdf = False
        for attachment in item.get('attachments', []):
            # Check if this is a PDF attachment
            if 'path' in attachment:
                # Parse the path - it could be in various formats
                path = attachment.get('path', '')
                pdf_path = None
                
                # Handle different path formats
                if path and path.startswith('storage:'):
                    # Extract the filename from the storage path
                    filename = path.replace('storage:', '')
                    # Only process actual PDF files
                    if not filename.lower().endswith('.pdf'):
                        continue
                    # Construct the full path to the PDF file
                    attachment_key = attachment.get('key', '')
                    if attachment_key:
                        pdf_path = os.path.join(ZOTERO_STORAGE_DIR, attachment_key, filename)
                elif attachment.get('key'):
                    # For older or custom path formats
                    # Try the attachment key folder
                    attachment_key = attachment.get('key')
                    possible_path = os.path.join(ZOTERO_STORAGE_DIR, attachment_key)
                    if os.path.isdir(possible_path):
                        # Look for PDF files in this directory
                        try:
                            files = os.listdir(possible_path)
                            pdf_files = [f for f in files if f.lower().endswith('.pdf')]
                            if pdf_files:
                                pdf_path = os.path.join(possible_path, pdf_files[0])
                        except Exception as e:
                            pbar.write(f"Error accessing directory {possible_path}: {str(e)}")
                            continue
                
                if pdf_path and os.path.exists(pdf_path):
                    text = extract_text_from_pdf(pdf_path)
                    
                    # Check if extraction returned an error message
                    if text.startswith(("Error", "Not a PDF", "PDF file too large", "Extracted empty")):
                        pbar.write(f"✗ {title}: {text}")
                        error_count += 1
                        
                        # Track error types
                        error_type = text.split(':', 1)[0].strip()
                        if error_type not in error_types:
                            error_types[error_type] = 0
                        error_types[error_type] += 1
                        
                        continue
                    
                    # Get abstract and title for better context
                    abstract = item.get('abstract', '')
                    
                    # Combine title, abstract and text for classification
                    classification_text = f"Title: {title}\nAbstract: {abstract}\nContent: {text}"
                    
                    relevant_tags = get_relevant_tags(classification_text, TAG_LIST)
                    
                    # Get existing tags
                    existing_tags = item.get('tags', [])
                    
                    # Add new tags using the Zotero API
                    new_tags = [tag for tag in relevant_tags if tag not in existing_tags]
                    if new_tags:
                        success, message = update_tags_in_db(item['itemID'], item['key'], new_tags)
                        if success:
                            pbar.write(f"✓ {title}: {message}")
                        else:
                            pbar.write(f"✗ {title}: {message}")
                    else:
                        pbar.write(f"• {title}: No new tags to add")
                    
                    processed += 1
                    has_processed_pdf = True
                    # Break after processing the first PDF attachment
                    break
                else:
                    pdfs_not_found += 1
                    pbar.write(f"✗ {title}: PDF file not found")
        
        # Update progress bar
        pbar.update(1)
        
        if not has_processed_pdf:
            pbar.write(f"• {title}: No valid PDF attachments found")
        
        if limit is not None and processed >= limit:
            pbar.close()
            print(f"\nTest run completed. Processed {processed} PDFs.")
            print(f"PDFs not found locally: {pdfs_not_found}")
            
            # Report error statistics
            if error_count > 0:
                print(f"Encountered {error_count} extraction errors:")
                for error_type, count in error_types.items():
                    print(f"  - {error_type}: {count}")
            else:
                print("No extraction errors encountered.")
                
            return
            
        # Sleep to respect API rate limits (for OpenAI)
        time.sleep(1)
    
    pbar.close()
    print(f"\nProcessing completed. Processed {processed} PDFs.")
    print(f"PDFs not found locally: {pdfs_not_found}")
    
    # Report error statistics
    if error_count > 0:
        print(f"Encountered {error_count} extraction errors:")
        for error_type, count in error_types.items():
            print(f"  - {error_type}: {count}")
    else:
        print("No extraction errors encountered.")

if __name__ == "__main__":
    try:
        print("Starting local PDF tagger script...")
        # Check if Zotero database exists
        if not os.path.exists(ZOTERO_DB_PATH):
            print(f"Error: Zotero database not found at {ZOTERO_DB_PATH}")
            print("Please check your Zotero data directory path.")
            sys.exit(1)
            
        process_local_pdfs(limit=None)
    except Exception as e:
        print(f"Error during execution: {str(e)}")
        import traceback
        traceback.print_exc() 