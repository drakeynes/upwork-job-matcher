
import os
import json
import argparse
import time
import requests
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from openai import OpenAI

# Load environment variables
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
     print("WARNING: OPENAI_API_KEY not found in .env")

# Google Scopes
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

# Serialized doc creation
doc_creation_lock = threading.Semaphore(1)

def get_google_creds():
    """
    Authenticates with Google and returns credentials.
    """
    creds = None
    if os.path.exists("config/token.json"):
        creds = Credentials.from_authorized_user_file("config/token.json", SCOPES)
    
    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                if not os.path.exists("config/credentials.json"):
                    raise FileNotFoundError("config/credentials.json not found.")
                print("Starting local server for OAuth...")
                flow = InstalledAppFlow.from_client_secrets_file("config/credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
            
            print("Saving credentials to config/token.json...")
            with open("config/token.json", "w") as token:
                token.write(creds.to_json())
    except Exception as e:
        print(f"AUTHENTICATION ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise e
            
    return creds

def load_bio():
    """
    Loads the user bio from config/bio.txt if it exists.
    """
    if os.path.exists("config/bio.txt"):
        with open("config/bio.txt", "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def call_llm(prompt, model_name="gpt-4o-mini"):
    """
    Calls the OpenAI LLM to generate text.
    """
    if not OPENAI_API_KEY:
        return "[Error: OPENAI_API_KEY missing]"

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"LLM Error: {e}")
        return f"[Error generating content: {e}]"

def generate_cover_letter(job, bio=""):
    prompt = f"""
    Write a max 35-word cover letter for this Upwork job.
    Job: {job.get('title')}
    Description: {job.get('description')}
    
    My Background (Bio):
    {bio}
    
    Rules:
    - Mirror the client's problem
    - Reference one concrete relevant build from my bio if applicable
    - Link to walkthrough doc: [DOC_LINK]
    - Do NOT invent fake projects. Only use what is in my bio or general expertise.
    
    Output strictly the cover letter text.
    """
    return call_llm(prompt)

def generate_proposal_body(job, bio=""):
    prompt = f"""
    Write a 200-350 word proposal for this Upwork job.
    Job: {job.get('title')}
    Description: {job.get('description')}
    
    My Background (Bio):
    {bio}
    
    Rules:
    - First-person, conversational
    - Clear problem mirror
    - Explicit step-by-step plan
    - Concrete deliverables
    - Realistic timeline
    - One sharp clarifying question
    - Use my bio to substantiate claims, but do not copy-paste it.
    
    Structure:
    Hey [name]...
    My approach...
    Deliverables...
    Timeline...
    Question...
    """
    return call_llm(prompt)

def create_google_doc(service_docs, service_drive, title, content):
    """
    Creates a Google Doc with the given content.
    Thread-safe with backoff.
    """
    doc_id = None
    doc_url = None
    
    with doc_creation_lock:
        backoff = 1.5
        for attempt in range(4):
            try:
                # Create Doc
                doc_metadata = {'title': title}
                doc = service_docs.documents().create(body=doc_metadata).execute()
                doc_id = doc.get('documentId')
                
                # Write Content
                requests_body = [
                    {
                        'insertText': {
                            'location': {'index': 1},
                            'text': content
                        }
                    }
                ]
                service_docs.documents().batchUpdate(documentId=doc_id, body={'requests': requests_body}).execute()
                
                # Get URL
                # drive_file = service_drive.files().get(fileId=doc_id, fields='webViewLink').execute()
                # doc_url = drive_file.get('webViewLink')
                doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
                
                time.sleep(1) # Rate limit padding
                break
                
            except HttpError as e:
                print(f"Error creating doc (Attempt {attempt+1}): {e}")
                time.sleep(backoff)
                backoff *= 2
                
    return doc_url

def update_sheet(service_sheets, sheet_id, row_data):
    """
    Appends a row to the Google Sheet.
    """
    try:
        body = {
            'values': [row_data]
        }
        service_sheets.spreadsheets().values().append(
            spreadsheetId=sheet_id,
            range="A1",
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()
    except HttpError as e:
        print(f"Error updating sheet: {e}")

def create_sheet(service_sheets, title="Upwork Proposals"):
    """
    Creates a new Google Sheet.
    """
    spreadsheet = {
        'properties': {
            'title': title
        }
    }
    spreadsheet = service_sheets.spreadsheets().create(body=spreadsheet, fields='spreadsheetId').execute()
    
    # Create Header Row
    headers = [
        "Title", "Job URL", "Budget", "Experience", "Skills", "Category", 
        "Client Country", "Client Spent", "Client Hires", "Connects", 
        "Proposal Count", "Posted Age", "Apply Link", "Cover Letter", 
        "Proposal Doc", "Status", "Rejection Reason"
    ]
    
    update_sheet(service_sheets, spreadsheet.get('spreadsheetId'), headers)
    
    return spreadsheet.get('spreadsheetId')

def process_job(job, services, sheet_id):
    """
    Full processing for a single job.
    """
    try:
        print(f"Processing job: {job.get('title')[:30]}...")
        
        # Load bio once per process or pass it down? 
        # Ideally passed in, but for simplicity loading global or in main.
        # Let's load it inside for thread safety if file read is fast, or better yet, pass it.
        # Refactoring process_job to accept bio is cleaner.
        # But for minimal changes, I'll load it here (os cache usually handles it well) or assume it was passed in kwargs?
        # Actually, let's just call load_bio() here. It's small.
        bio = load_bio()

        # Generator
        cl = generate_cover_letter(job, bio)
        prop = generate_proposal_body(job, bio)
        
        # Google Doc
        doc_title = f"Proposal: {job.get('title')} - {job.get('job_id')}"
        combined_text = f"Cover Letter:\n{cl}\n\nProposal:\n{prop}"
        
        doc_url = "FALLBACK_TEXT_ONLY"
        try:
            doc_url = create_google_doc(
                services['docs'], 
                services['drive'], 
                doc_title, 
                combined_text
            )
        except Exception as e:
            print(f"Failed to create doc for {job.get('job_id')}: {e}")
            
        # Format Budget
        budget_raw = job.get('budget')
        budget_str = ""
        if isinstance(budget_raw, dict):
            fixed = budget_raw.get('fixedBudget')
            hourly = budget_raw.get('hourlyRate', {})
            if fixed and fixed > 0:
                budget_str = f"${fixed}"
            elif hourly:
                min_rate = hourly.get('min')
                max_rate = hourly.get('max')
                if min_rate or max_rate:
                    budget_str = f"${min_rate or '?'}-${max_rate or '?'} /hr"
        else:
            budget_str = str(budget_raw) if budget_raw else ""
            
        # Calculate Age
        posted_date_str = job.get('posted_date')
        age_str = ""
        if posted_date_str:
            try:
                # Handle ISO format like 2026-01-15T23:58:47.815Z
                posted_dt = datetime.fromisoformat(posted_date_str.replace("Z", "+00:00"))
                now_dt = datetime.now(timezone.utc)
                diff = now_dt - posted_dt
                
                days = diff.days
                seconds = diff.seconds
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                
                if days > 0:
                    age_str = f"{days}d ago"
                elif hours > 0:
                    age_str = f"{hours}h ago"
                else:
                    age_str = f"{minutes}m ago"
            except Exception as e:
                pass

        # Prepare Sheet Row
        # Ensure all elements are strings or simple types
        row = [
            job.get('title') or "",
            job.get('job_url') or "",
            budget_str,
            job.get('experience_level') or "",
            ", ".join(job.get('skills', [])) if isinstance(job.get('skills'), list) else str(job.get('skills') or ""),
            "", 
            job.get('client_country') or "",
            str(job.get('client_total_spent') or ""),
            str(job.get('client_hires') or ""),
            "", 
            str(job.get('proposal_count') or ""),
            age_str, # Use Age instead of raw date
            job.get('apply_url') or "",
            str(cl),
            str(doc_url),
            "Ready", 
            "" 
        ]
        
        # Update Sheet
        if sheet_id and sheet_id != "DRY_RUN":
            update_sheet(services['sheets'], sheet_id, row)
        
        return {
            "job_id": job.get('job_id'),
            "status": "success",
            "doc_url": doc_url,
            "row_data": row
        }
        
    except Exception as e:
        print(f"Error processing job {job.get('job_id')}: {e}")
        return {"job_id": job.get('job_id'), "status": "failed", "error": str(e)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Input JSON file with jobs")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker threads (recommend 1 for 5RPM limit)")
    parser.add_argument("--sheet-id", help="Existing Google Sheet ID")
    parser.add_argument("--dry-run", action="store_true", help="Skip Google Sheet creation/updates")
    parser.add_argument("-o", "--output", help="Output results JSON")
    
    args = parser.parse_args()
    
    # Load Jobs
    with open(args.input, "r", encoding="utf-8") as f:
        jobs = json.load(f)
        
    # Init Google Services
    creds = get_google_creds()
    services = {
        'sheets': build('sheets', 'v4', credentials=creds),
        'docs': build('docs', 'v1', credentials=creds),
        'drive': build('drive', 'v3', credentials=creds)
    }
    
    # Setup Sheet
    sheet_id = args.sheet_id
    if args.dry_run:
        sheet_id = "DRY_RUN"
        print("Dry run enabled. Skipping Sheet creation.")
    elif not sheet_id:
        sheet_id = create_sheet(services['sheets'])
        print(f"Created new Sheet: https://docs.google.com/spreadsheets/d/{sheet_id}")
    
    # Process Pool
    results = []
    all_rows = []
    
    print(f"Starting processing with {args.workers} workers.")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_job, job, services, sheet_id): job for job in jobs}
        
        for future in futures:
            res = future.result()
            results.append(res)
            if 'row_data' in res:
                all_rows.append(res['row_data'])

    # Save Debug Rows
    with open(".tmp/debug_rows.json", "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)
    print(f"Saved {len(all_rows)} rows to .tmp/debug_rows.json for inspection.")

    # Save Results
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

if __name__ == "__main__":
    main()
