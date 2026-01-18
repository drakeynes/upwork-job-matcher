# Upwork Job Matcher (Prototype)

## What this is
This is a prototype exploring how to narrow freelance job listings down to a small set of high-fit opportunities and generate tailored first-pass proposals.

The focus is not on fully automating decisions, but on designing a workflow that:
- starts with constrained search criteria
- uses profile-aware evaluation to screen listings
- assists with proposal drafting while keeping human judgment in control

This project is exploratory and intentionally lightweight.

---

## Why I built it
When searching for automation and internal operations roles, most listings are either poor fits, require deeper expertise, or don’t align with a specific working style.

This prototype explores whether combining:
- careful search constraints
- profile-aware evaluation
- and assisted proposal drafting  

can reduce noise and decision fatigue while still keeping the human in the loop.

---

## High-level approach
At a high level, the prototype follows this flow:

1. Query recent job listings using constrained search terms and platform filters  
2. Pass candidate listings to an evaluation step that compares them against a defined user profile  
3. Discard low-fit listings and keep potential matches  
4. Generate a draft proposal for high-fit roles to speed up application

The evaluation step is intentionally conservative and designed to support—not replace—human judgment.

---

## Current state
- Early-stage prototype
- Designed for learning and iteration
- Not production-hardened
- Assumes human review before any application is sent

The implementation favors clarity over optimization so the reasoning behind each step is easy to inspect.

---

## Design notes
- Search criteria act as the primary hard constraint  
- Profile-aware evaluation is used to reduce obvious mismatches  
- Proposal drafting is assistive, not autonomous  
- The system is designed to be adjusted as the user’s goals and skills evolve  

This reflects how I tend to approach automation work: define constraints first, add intelligence only where it clearly helps, and keep control with the operator.

---

## Possible next steps
- Improve evaluation heuristics using application outcomes  
- Refine profile inputs to tighten fit over time  
- Add clearer feedback loops for discarded listings  

These are intentionally left open as part of the exploration.

---

## Repository contents
- `upwork_apify_scraper.py` — collects recent job listings using constrained search criteria
- `upwork_proposal_generator.py` — evaluates listings against a user profile and drafts proposals
- `run.bat` — runs both steps sequentially for local testing

---

## Notes
This repository is meant to demonstrate how I think about workflow design and decision support, not to present a finished product.
