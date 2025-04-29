# Zotero Tag Assignment

An AI-powered tool for automatically assigning semantic tags to research papers in your Zotero library.

## Overview

This repository contains a set of Python scripts that use OpenAI's language models to automatically analyze academic papers stored in your Zotero library and assign relevant tags from a predefined taxonomy. The tools can process individual PDFs or batch process your entire Zotero library.

## Features

- **Intelligent tagging**: Uses GPT-4.1-mini to analyze paper content and assign relevant subject tags
- **Multiple operation modes**:
  - Tag a single PDF with optional manual overrides
  - Batch process your entire Zotero library
  - Process local PDFs directly from your Zotero storage folder
- **Customizable taxonomy**: Edit the tag list in `tags.py` to match your research interests
- **Utilities**:
  - Remove all tags from your library with `tag_removal.py`

## Requirements

- Python 3.7+
- A Zotero library with PDF attachments
- An OpenAI API key

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/zotero_tag_assig.git
   cd zotero_tag_assig
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root with the following variables:
   ```
   OPENAI_API_KEY=your_openai_api_key
   ZOTERO_LIBRARY_ID=your_zotero_library_id
   ZOTERO_API_KEY=your_zotero_api_key
   ```

   You can find your Zotero library ID and API key at https://www.zotero.org/settings/keys

4. (Optional) Configure the Zotero data directory path in `local_pdf_tagger.py` if your Zotero data is not in the default location.

## Usage

### Tag a Single PDF File

```
python tag_single_pdf.py path/to/your/paper.pdf [options]
```

Options:
- `--item-key KEY`: Specify the Zotero item key (if known)
- `--title TITLE`: Provide the document title
- `--abstract ABSTRACT`: Provide the document abstract
- `--preview`: Preview tags without updating Zotero

If no item key is provided, the script will attempt to find the matching item in your Zotero library.

### Batch Processing Your Entire Library

```
python tag_assigm_batch.py
```

This will:
1. Connect to your Zotero library via the API
2. Process all items with PDF attachments
3. Extract text from each PDF
4. Generate relevant tags using the OpenAI model
5. Update the items in your Zotero library

To process only a limited number of items (for testing):

```
# Edit the script to set a limit
process_zotero_items(limit=10)  # Process only 10 items
```

### Process Local PDFs

```
python local_pdf_tagger.py
```

This script reads directly from your local Zotero storage folder, which can be faster than using the API for large libraries.

### Remove All Tags

```
python tag_removal.py
```

Use this to clear all tags from your Zotero library before starting fresh.

## Customizing the Tag List

Edit `tags.py` to modify the list of available tags. The current list focuses on AI/ML research topics.

## How It Works

1. The scripts extract text from PDFs using pdfminer
2. The extracted text, along with available metadata like title and abstract, is sent to OpenAI's API
3. The model analyzes the content and assigns relevant tags from the predefined list
4. New tags are added to the Zotero item via the Zotero API

## Troubleshooting

- **"PDF file not found"**: Check that the Zotero storage path is correctly configured
- **"Error extracting text"**: Some PDFs may be scanned images or have complex layouts that are difficult to extract
- **API rate limits**: The scripts include delays to respect OpenAI's rate limits, but you may need to adjust these for your API tier

## License

[MIT License](LICENSE)

## Acknowledgments

- This tool uses the [pyzotero](https://github.com/urschrei/pyzotero) library for Zotero API access
- Text extraction is handled by [pdfminer.six](https://github.com/pdfminer/pdfminer.six)
- AI-powered tagging uses [OpenAI's API](https://openai.com/blog/openai-api) 