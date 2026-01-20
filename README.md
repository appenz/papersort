# PaperSort

A command-line tool that automatically sorts PDF documents into a hierarchical folder structure using AI.
You specify the folder structure as a simple text document that looks something like this:

```
- Financial : Financial documents, banking records, and insurance policies
   - Bank Accounts : Bank statements and account records
      - By company
      - By year
   - Taxes : Tax returns and related documents
      - By year
   - Insurance : Insurance policies and claims
      - By company
   - Other : Documents that don't fit in above categories
```

If you really want to maximize automation, ask your favorite LLM to come up with a folder structure and it
will do an amazing job. PaperSort will analyze each PDF document using an LLM of your choice (currently
supports OpenAI and Mistral out of the box) and sort accordingly.

Currently only supports Google Drive as a document store, but that can easily be changed.
Currently only runs on macOS, but changes for other platforms should be trivial.

## Installation

1. Create a Google Service account that has access to Google Drive. Frankly, this is the hardest part. Requires access to the IAM console of your organization. May or may not work with individual accounts. Google's IAM is still a mess. Save the service account key in ``service_account_key.json``
2. Share the relevant folders with the service account.
2. Install [uv](https://docs.astral.sh/uv/) 
3. Clone this repository
4. Create a `.env` file with your API key and the ID's of the Google Drive folders (see below)
4. Create a `layout.txt` file in your document store
5. Run:

```bash
uv run papersort.py --copy
```

And watch the magic.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MISTRAL_API_KEY` | API key for Mistral AI (if using Mistral) |
| `OPENAI_API_KEY` | API key for OpenAI (if using OpenAI) |
| `LLM_PROVIDER` | Which LLM to use: `openai` or `mistral` |
| `INBOX` | Source folder with documents to sort. Format: `gdrive:<folder-id>` or `local:<path>` |
| `DOCSTORE` | Destination document store. Format: `gdrive:<folder-id>` or `local:<path>` |

The folder ID for Google Drive is the last part of the URL, i.e. after the "...folders/"

## Layout File

The document store must contain a `layout.txt` file that defines your folder hierarchy. PaperSort uses this to determine where each document should be filed.

### Sample layout.txt

```
This is my document store layout for organizing personal and financial documents.

---LAYOUT STARTS HERE---

- Personal & Identification : Important personal documents such as IDs, certificates, and legal papers
   - Birth & Marriage : Birth certificates, marriage certificates, and related documents
   - IDs & Licenses : Driver's licenses, passports, Social Security cards
   - Legal : Wills, power of attorney, estate planning documents
   - Other : Documents that don't fit in above categories

- Financial : Financial documents, banking records, and insurance policies
   - Bank Accounts : Bank statements and account records
      - By company
      - By year
   - Taxes : Tax returns and related documents
      - By year
   - Insurance : Insurance policies and claims
      - By company
   - Other : Documents that don't fit in above categories

- Medical : Health and medical records
   - By year
```

### Special Folder Types

#### By year

When a category contains `By year`, documents are automatically sorted into year-based subfolders. For example, a 2024 tax return would be filed under:

```
Financial/Taxes/2024/
```

The year is extracted from the document content (for tax documents, this is the tax year, not the filing date).

#### By company

When a category contains `By company`, documents are automatically sorted into company-based subfolders. For example, a Chase bank statement would be filed under:

```
Financial/Bank Accounts/Chase/
```

The company name is extracted and normalized by the LLM (e.g., "Chase Bank", "JPMorgan Chase" → "Chase").

## Usage

### Process all documents in inbox

```bash
uv run papersort.py
```

### Process and copy to document store

```bash
uv run papersort.py --copy
```

### Process a single file

```bash
uv run papersort.py --file /path/to/document.pdf
```

### Show the document store layout

```bash
uv run papersort.py --showlayout
```

### Verify and re-copy missing files

```bash
uv run papersort.py --copy --verify
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `--file <path>` | Process a single PDF file |
| `--copy` | Copy files to document store after processing |
| `--verify` | Verify files exist at destination (use with --copy) |
| `--update` | Reprocess documents even if cached |
| `--showlayout` | Print the document store layout tree |

## How It Works

1. **Scan**: PaperSort scans the inbox for PDF files
2. **Analyze**: Each document is sent to the LLM, which extracts:
   - Title
   - Year (document year, e.g., tax year)
   - Date (creation/sent date)
   - Entity (company or organization)
   - Summary
   - Suggested filing path
3. **Cache**: Results are cached locally to avoid re-processing
4. **Copy** (optional): With `--copy`, files are renamed and copied to the suggested location

## License

MIT License - see LICENSE file for details.

## Sample layout.txt

```
This document describes the layout of our document store.

The basic layout is a hirarchical tree of folders where indenting denotes subforlders:

- FOLDERNAME : description
  - SUBFOLDER : description
    - SUBSUBFOLDER : description
- FOLDERNAME : description
   - SUBFOLDER : description

Inportant Rules:
- Folder names must be 30 characters or shorter
- Folder names must be valid Linux file system path names
- Instead of a subfolder name, there can be special keywords:
   - "By year" means it should be replaced by the year it is about (e.g. "2023", "2024" etc.)
   - "By company" means it should be replaced by the year it is about, e.g. ("Chase", "Goldman Sachs", "First Republic")
   - Examples
      - Correct: Tax/2024 
      - Correct: Boards/Megacorp
      - WRONG: Tax/By Year/2024
   - If there is a folder that looks like a good match, prioritize this over creating a new one
- There is often an "other" folder, use it if you can't determing which subfolder is the right one

Key information about these documents:
- Documents are for a Family of five: 
   - Parents: Guido Appenzeller and Isabelle Steiner
   - Kids: Bob Appenzeller, Steve Appenzeller
- Address: 1234 Fantasy Road, Disneyland, CA 12345

---LAYOUT STARTS HERE---

- Research Papers: Conference or Journal publications
   - By year

- Employers : Various documents for companies that I worked for or founded
   - Voltage Security : Anything related to this company that I founded
      - Employment
      - Press & Awards
      - Equity : Anything related to founding, stocks, vesting, exercise and sale of the company
      - Technical documents
      - Other
   - Big Switch Networks : Anything related to this company that I founded. Sometimes abbreviated BSN.
      - Employment
      - Press & Awards
      - Equity : Anything related to founding, stocks, vesting, exercise and sale of the company
      - Technical documents
      - Other
   - Yubico : Anything related to employment, stock grants or anything else at Yubico
   - VMware : Anything related to employment, stock grants or anything else at Vmware

- Stanford : Anything related to Stanford University 

- Personal & Identification : Important personal documents such as IDs, certificates, licenses, and legal papers.
   - Birth & Marriage : Birth certificates, marriage certificates, and related documents
   - Citizenship & Immigration : All citizenship and immigration related documents
   - IDs & Licenses : Driver's licenses, passports, Social Security cards
   - Legal : Wills, power of attorney, estate planning documents
   - Other : Documents that don't fit in above categories

- Financial & Banking : Financial documents, banking records, and insurance policies
   - Bank Accounts : Bank statements and investment account records
      - By company
   - Retirement : 401k, IRA, and pension account documents
   - Credit : Credit card statements and credit reports
   - Safe Deposit : Safe deposit box inventory and access records
   - Insurance : House, car, and liability insurance policies
      - By company
   - Stock Certificates : Scans of the certificates
   - Travel Receipts: Receipts for travel related expenses
      - Flight
      - Hotels
      - Other
   - Food Receipts: Receipts for restaurants or buying food
   - Other : Documents that don't fit in above categories

- Taxes : Private tax-related documents for Guido & Isabelle
   - Tax Forms : W-2s, 1099s, K-1, 1065 and pay stubs
      - By year
   - Federal : Federal tax returns and IRS communications
      - By year
   - State : California state tax returns and communications
      - By year
   - Property : Property tax records and related communications
      - By year
   - Business : Non-LLC business tax documents
   - Bank Statements : Bank and brokerage statements
      - By company
   - Donation Receipts : Donation acknowledgements
   - Other : Documents that don't fit in above categories

- Medical & Health : Health-related documents and records
   - Insurance : Health, dental, and vision insurance policies
   - Records : Medical records and prescriptions
   - Vaccinations : Vaccination records and history
   - Dental & Vision : Dental and vision care records
   - Bills : Medical bills and payment records
      - By company
   - Other : Documents that don't fit in above categories

- Education & Childcare : Educational and childcare related documents
   - School : Private school invoices and tuition payments
   - Academic : Report cards, transcripts, and test scores
   - Activities : Camps and extracurricular activity receipts
   - Daycare : Daycare related documents and payments
   - Other : Documents that don't fit in above categories

- House & Property : Property and home-related documents
   - Deeds & Mortgages : Property deeds and mortgage documents
   - Improvements : Home improvement records and contracts
   - Warranties : Appliance and system warranties
   - Other : Documents that don't fit in above categories

- Vehicles & Transportation : Vehicle and transportation related documents
   - Registration : Vehicle registration and titles
   - Insurance : Auto insurance policies
   - Maintenance : Service and maintenance records
   - Purchase : Purchase agreements and financing
   - Driver Training : Driver's education and permits
   - Transit : Public transit passes and toll accounts
   - Other : Documents that don't fit in above categories

- Bills & Utilities : Utility and service bills
   - Utilities : Electricity, water, and gas bills
   - Communications : Internet, cable, and phone bills
   - Services : Trash and security system invoices
   - Streaming : Streaming service subscriptions
   - Mobile : Cell phone plans and invoices
   - Other : Documents that don't fit in above categories

- Warranties & Manuals : Product warranties and manuals
   - Electronics : Electronic device manuals and warranties
   - Appliances : Appliance manuals and warranties
   - Home Goods : Furniture and home goods warranties
   - Vehicles : Vehicle-related warranties
   - Other : Documents that don't fit in above categories

- Aircraft : Anything related to may aircraft
   - FBO Receipts : Invoices or receipts from FBOs and aviation service firms for Fuel, Gas, Jet-A, 100LL, landing fees, ramp fees or handling.
   - Insurance : Aviation insurance policies
   - N122JM : Documents related to our Pilatus PC-12NG aircraft (but NOT FBO receipts)
      - Registration : Aircraft registration and title
      - Purchase : Purchase and ownership documents
      - Tax : Aircraft tax documents
      - Maintenance : Maintenance logs and records
      - Other : Other docs related to N122JM
   - Pilot : Pilot certificates and medical records
   - Training : Training and certification documents. FlightSafety.
   - Flight : Flight plans and FAA documentation
   - Contract Pilots : Bills and other documents related to our contract pilots Libor Kovarcik
   - Other : Aviation related documents that don't fit in above categories 


- Unsortable & Other : This is the catchall for documents that really don't fit anywhere
```