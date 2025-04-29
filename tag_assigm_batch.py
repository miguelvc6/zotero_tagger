import os
from pdfminer.high_level import extract_text
from pyzotero import zotero
from openai import OpenAI
import time
from dotenv import load_dotenv
from tqdm import tqdm
import io
import sys
import contextlib
from tags import TAG_LIST

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Initialize Zotero client
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
        # Redirect stderr to suppress pdfminer warnings
        with contextlib.redirect_stderr(io.StringIO()):
            return extract_text(pdf_path)
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {str(e)}")
        return ""

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

def process_zotero_items(limit=None):
    """Process items in Zotero library.
    
    Args:
        limit (int): Number of papers to process in this test run
    """
    items = zot.everything(zot.items())
    processed = 0
    
    # We'll process all top-level items (not attachments themselves) and check for PDF attachments
    top_level_items = [item for item in items if item['data'].get('itemType') != 'attachment']
    
    print(f"\nStarting test run with {limit if limit else 'all'} items...\n")
    print(f"Found {len(top_level_items)} top-level items out of {len(items)} total items")
    
    # Filter items with PDF attachments first
    items_with_pdfs = []
    for item in top_level_items:
        attachments = zot.children(item['key'])
        has_pdf = any(attachment['data'].get('contentType') == 'application/pdf' for attachment in attachments)
        if has_pdf:
            items_with_pdfs.append(item)
    
    print(f"Found {len(items_with_pdfs)} items with PDF attachments")
    
    # Create a progress bar with the appropriate total
    total_items = min(limit, len(items_with_pdfs)) if limit is not None else len(items_with_pdfs)
    pbar = tqdm(total=total_items, desc="Processing papers with PDFs")
    
    for item in items_with_pdfs:
        # Get attachments for this item
        attachments = zot.children(item['key'])
        title = item['data'].get('title', '')
        
        pbar.set_description(f"Processing: {title[:30]}..." if len(title) > 30 else f"Processing: {title}")
        
        # Process only PDF attachments
        for attachment in attachments:
            if attachment['data'].get('contentType') == 'application/pdf':
                # Get the storage folder key from the attachment data
                storage_key = attachment['data'].get('key', '')
                if not storage_key:
                    pbar.write(f"✗ No storage key found for attachment of {title}")
                    continue
                    
                # Construct the path to look in the storage subfolder
                pdf_path = os.path.join("C:\\", "Users", "vazquez", "Zotero", "storage", 
                                      storage_key, attachment['data'].get('filename', ''))
                
                if os.path.exists(pdf_path):
                    text = extract_text_from_pdf(pdf_path)
                    
                    # Get abstract and title for better context
                    abstract = item['data'].get('abstractNote', '')
                    
                    # Combine title, abstract and text for classification
                    classification_text = f"Title: {title}\nAbstract: {abstract}\nContent: {text}"
                    
                    relevant_tags = get_relevant_tags(classification_text, TAG_LIST)
                    
                    # Get existing tags
                    existing_tags = [t['tag'] for t in item['data'].get('tags', [])]
                    
                    # Add new tags
                    new_tags = [{'tag': tag} for tag in relevant_tags if tag not in existing_tags]
                    if new_tags:
                        item['data']['tags'].extend(new_tags)
                        try:
                            zot.update_item(item)
                            pbar.write(f"✓ {title}: Added tags: {', '.join([t['tag'] for t in new_tags])}")
                        except Exception as e:
                            pbar.write(f"✗ Error updating {title}: {str(e)}")
                    else:
                        pbar.write(f"• {title}: No new tags to add")
                    
                    processed += 1
                    # Break after processing the first PDF attachment
                    break
                else:
                    pbar.write(f"✗ PDF file not found for {title}")
        
        # Update progress bar
        pbar.update(1)
        
        if limit is not None and processed >= limit:
            pbar.close()
            print(f"\nTest run completed. Processed {processed} items with PDFs.")
            return
            
        # Sleep to respect API rate limits
        time.sleep(1)
    
    pbar.close()
    print(f"\nProcessing completed. Processed {processed} items with PDFs.")

if __name__ == "__main__":
    process_zotero_items(limit=None)  # Process all papers
