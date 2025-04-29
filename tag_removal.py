import os
from pyzotero import zotero
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# 1. Connect to Zotero
LIBRARY_ID = os.getenv('ZOTERO_LIBRARY_ID')
LIBRARY_TYPE = 'user'  # 'user' or 'group'
API_KEY = os.getenv('ZOTERO_API_KEY')

# Validate required environment variables
if not all([LIBRARY_ID, API_KEY]):
    raise ValueError("Missing required environment variables. Please check your .env file.")

zot = zotero.Zotero(LIBRARY_ID, LIBRARY_TYPE, API_KEY)

# 2. Fetch all items (you can adjust 'limit' if needed)
items = zot.everything(zot.items())

# 3. Loop through each item and remove tags
for item in items:
    # Check if the item has any tags
    if 'tags' in item['data'] and item['data']['tags']:
        item_id = item['key']
        item_version = item['version']

        # Prepare the updated item
        updated_item = {
            'itemType': item['data']['itemType'],
            'tags': [],
            'key': item_id,
            'version': item_version
        }

        # 4. Send the update
        zot.update_item(updated_item)
        print(f"Tags removed from item {item_id}")

print("Finished removing all tags!")
