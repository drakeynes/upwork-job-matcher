
import os
import sys
import json
import argparse
import time
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_ID = "upwork-vibe~upwork-job-scraper"

def scrape_jobs(limit, days_back, search_queries=None):
    """
    Runs the Apify actor to scrape Upwork jobs.
    """
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN not found in .env")

    url = f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    
    # Calculate creation time filter if days_back is provided
    # Note: The actor might not support date filtering directly in input efficiently for all fields,
    # but we will pass what we can or filter post-scrape if needed.
    # The directive says "Free tier supports only: limit, fromDate, toDate".
    
    # Calculate dates
    # fromDate should be current time - days_back
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=days_back)
    
    # Format as YYYY-MM-DD (Apify usually expects this or ISO)
    # Checking actor docs (assumed): usually accepts 'publication_time' or similar. 
    # Directive says "fromDate", "toDate".
    
    queries = [q.strip() for q in search_queries.split(",")] if search_queries else ["workflow automation"]
    
    # Reverting to 'upwork-vibe/upwork-job-scraper' with FLATTENED keys.
    # Analysis of successful run shows keys like "includeKeywords.matchTitle".
    # Nested objects caused 400 "Property not allowed".
    
    # We must iterate if we have multiple queries because 'keywords' field implies AND logic usually, 
    # but let's pass all as a list first. The user wants "OR" likely, but standard search is often AND.
    # Actually, Upwork search supports boolean "OR". But here we have a list.
    # We'll pass them as a list. If results are scant, we might need to loop.
    
    run_input = {
        "limit": limit,
        "fromDate": from_date.strftime("%Y-%m-%d"),
        "toDate": now.strftime("%Y-%m-%d"),
        # Flattened keys
        "includeKeywords.keywords": queries,
        "includeKeywords.matchTitle": True,
        "includeKeywords.matchDescription": True,
        "includeKeywords.matchSkills": True,
        # Adding sort by recency if possible? Schema didn't show it.
        # User had "jobCategories" in their successful run. We'll omit for now to keep it broad.
    }
    
    print(f"Starting Apify actor run (upwork-vibe/upwork-job-scraper) with input: {json.dumps(run_input)}")
    
    # Retry Logic for starting the run
    max_retries = 3
    run_id = None
    dataset_id = None
    
    try:
        for attempt in range(max_retries):
            try:
                # upwork-vibe/upwork-job-scraper
                actor_url = f"https://api.apify.com/v2/acts/upwork-vibe~upwork-job-scraper/runs?token={APIFY_API_TOKEN}"
                response = requests.post(actor_url, json=run_input)
                response.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                print(f"HTTP Error {e.response.status_code}. Writing details to .tmp/error.log")
                try:
                    with open(".tmp/error.log", "w", encoding="utf-8") as f:
                        f.write(e.response.text)
                except:
                    pass
                
                if e.response.status_code in [400, 403, 404]:
                     # If 403, it might be a block or input issue. 
                     # We will re-raise to stop execution if it persists.
                     if attempt == max_retries - 1:
                         raise e
                    
                print(f"Error starting run (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(2 * (attempt + 1))
        
        run_data = response.json().get("data", {})
        run_id = run_data.get("id")
        dataset_id = run_data.get("defaultDatasetId")
        
        print(f"Run started: {run_id}")
        
        # Poll for completion
        while True:
            try:
                status_url = f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}"
                status_res = requests.get(status_url)
                status_data = status_res.json().get("data", {})
                status = status_data.get("status")
                
                print(f"Status: {status}")
                
                if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
                    break
                    
                time.sleep(5)
            except Exception as e:
                print(f"Polling error: {e}. Retrying poll...")
                time.sleep(5)
            
        if status != "SUCCEEDED":
            raise Exception(f"Run failed/aborted with status: {status}")
            
        # Fetch results
        dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}&format=json"
        for attempt in range(max_retries):
            try:
                dataset_res = requests.get(dataset_url)
                dataset_res.raise_for_status()
                return dataset_res.json()
            except Exception as e:
                 print(f"Error fetching dataset (Attempt {attempt+1}): {e}")
                 if attempt == max_retries - 1:
                     raise e
                 time.sleep(2)
                 
    except Exception as glob_e:
        print(f"Fatal error during scraping: {glob_e}")
        # If we failed, return empty list or re-raise
        raise glob_e

def filter_jobs(jobs, verified_payment, min_spent, experience_levels, days_back):
    """
    Filters jobs based on criteria.
    """
    filtered = []
    
    now = datetime.now(timezone.utc)
    cutoff_time = now - timedelta(days=days_back)
    
    print(f"Filtering {len(jobs)} jobs...")
    
    if jobs:
        print(f"DEBUG: First Job Client Data: {jobs[0].get('client')}")

    for job in jobs:
        # 1. Posted time check
        # Apify usually returns 'postedDate' or 'date_created'
        posted_date_str = job.get("postedDate") or job.get("date_created") or job.get("createdAt")
        
        # Parse logic depends on actual format. Assuming ISO for now.
        # If scraper returns '2h ago' type strings, we might need parsing logic. 
        # But 'upwork-job-scraper' usually gives ISO strings.
        
        # Skip time check if we can't parse, or handle gracefully.
        # For now, relying on Apify's fromDate input to handle the bulk of date filtering.
        
        # 2. Verified Payment
        if verified_payment:
            client = job.get("client", {})
            # Schema analysis shows 'paymentMethodVerified' is a boolean in 'client' output
            # Previous logic checked for string 'VERIFIED' which caused rejection.
            is_verified = job.get("isPaymentVerified") or client.get("paymentMethodVerified") is True or client.get("paymentVerificationStatus") == "VERIFIED"
            
            if not is_verified:
                # print(f"Rejected {job.get('uid')} - Payment not verified")
                continue

        # 3. Min Spent
        if min_spent > 0:
            client = job.get("client", {})
            total_spent = client.get("totalSpent")
            # Schema analysis shows 'totalSpent' inside 'stats' object
            if total_spent is None and "stats" in client:
                total_spent = client.get("stats", {}).get("totalSpent")
            
            total_spent = total_spent or 0
            
            # Ensure it's a number
            try:
                total_spent = float(str(total_spent).replace(",", "").replace("$", ""))
            except:
                total_spent = 0
                
            if total_spent < min_spent:
                # print(f"Rejected {job.get('uid')} - Low Spend: {total_spent}")
                continue
                
        # 4. Experience Level
        # Schema analysis shows 'experienceLevel' might be in 'vendor' object
        job_level = job.get("experienceLevel") or job.get("vendor", {}).get("experienceLevel")
        
        if experience_levels and job_level:
            permitted = [l.strip().lower() for l in experience_levels]
            if job_level.lower() not in permitted:
                # print(f"Rejected {job.get('uid')} - Level: {job_level}")
                continue
                
        # 5. Connects (Optional - verify later)
        
        # 6. Proposal Count
        # Schema analysis shows 'proposals' might be missing.
        proposals = job.get("proposals") or job.get("proposalCount")
        
        if proposals:
             # Strict filtering: Reject high proposal buckets
             reject_phrases = ["15 to 20", "20 to 50", "50+"]
             if any(phrase in str(proposals) for phrase in reject_phrases):
                 continue
             if isinstance(proposals, (int, float)) and proposals >= 15:
                 continue
                 
        filtered.append(job)
        
    return filtered

def transform_job(job):
    """
    Transforms raw job to our output contract.
    """
    client = job.get("client", {})
    
    # Construct Apply URL
    # Directive: https://www.upwork.com/nx/proposals/job/~{id}/apply/
    # But we need the ciphertext ID (ciphertext). 'id' in JSON is often the readable one? 
    # Usually scraped 'id' is the ciphertext like '~01...' or we need to look for 'ciphertext'.
    # Job ID extraction
    job_id = job.get("id") or job.get("ciphertext")
    job_url = job.get("url") or job.get("externalLink")
    
    if not job_id and job_url and "~" in job_url:
        # Extract from URL like https://www.upwork.com/jobs/~0123...
        try:
             job_id = "~" + job_url.split("~")[-1]
        except:
             pass

    apply_url = f"https://www.upwork.com/nx/proposals/job/{job_id}/apply/" if job_id else ""
    
    return {
        "job_id": job_id,
        "title": job.get("title"),
        "description": job.get("description"),
        "skills": job.get("skills", []),
        "budget": job.get("budget"), # Fixed
        "hourly_rate": job.get("hourlyRate"), # Hourly
        "job_type": job.get("jobType"), # fixed-price / hourly
        "experience_level": job.get("experienceLevel") or job.get("vendor", {}).get("experienceLevel"),
        "client_country": client.get("location", {}).get("country") or client.get("countryCode"),
        "client_total_spent": client.get("stats", {}).get("totalSpent") if "stats" in client else client.get("totalSpent"),
        "client_hires": client.get("stats", {}).get("totalHires") if "stats" in client else client.get("totalHires"),
        "proposal_count": job.get("proposals") or job.get("proposalCount"), # might vary
        "posted_date": job.get("postedDate") or job.get("date_created") or job.get("createdAt"),
        "job_url": job_url,
        "apply_url": apply_url,
    }

def main():
    parser = argparse.ArgumentParser(description="Scrape and filter Upwork jobs.")
    parser.add_argument("--search-queries", type=str, default="workflow automation", help="Comma-separated search queries")
    parser.add_argument("--limit", type=int, default=50, help="Max jobs to fetch")
    parser.add_argument("--days", type=int, default=1, help="Days back to search") # Default 1 day
    parser.add_argument("--verified-payment", action="store_true", help="Require verified payment")
    parser.add_argument("--min-spent", type=float, default=1000, help="Minimum client spend") # Default 1000
    parser.add_argument("--experience", type=str, help="Comma-sep experience levels (e.g. intermediate,expert)")
    parser.add_argument("-o", "--output", required=True, help="Output JSON file path")
    
    args = parser.parse_args()
    
    print(f"Fetching jobs from Upwork for query: '{args.search_queries}'...")
    try:
        raw_jobs = scrape_jobs(args.limit, args.days, args.search_queries)
    except Exception as e:
        print(f"Error scraping: {e}")
        sys.exit(1)

    print(f"Fetched {len(raw_jobs)} raw jobs.")
    
    # Process experience levels
    exp_levels = args.experience.split(",") if args.experience else []
    
    filtered = filter_jobs(raw_jobs, args.verified_payment, args.min_spent, exp_levels, args.days)
    
    print(f"Filtered down to {len(filtered)} jobs.")
    
    if filtered:
        print("DEBUG: Raw keys of first job:", list(filtered[0].keys()))
    
    # Transform
    output_data = [transform_job(j) for j in filtered]
    
    # Save
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
        
    print(f"Saved to {args.output}")

if __name__ == "__main__":
    main()
