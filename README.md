# 360iQ Data API Test Environment

This repository contains example scripts for interacting with the 360iQ Data API. 
The `simulate_test_environment.py` script posts a sample transaction with a fixed
timestamp so you can verify API integration without being connected to a POS.

## Requirements
- Python 3.9+
- `requests` library

Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage
Set your API credentials as environment variables before running the script:
```bash
export CLIENT_ID="<your client id>"
export CLIENT_SECRET="<your client secret>"
```
Then run:
```bash
python simulate_test_environment.py
```
The script sends a single transaction dated **2025‑06‑13 18:00** (America/New_York) 
and prints the HTTP response status and body.

## Existing Script
The original `711usingtransactionsummary.py` listens to POS serial ports and 
forwards transactions to the API in real time. The test script does not require 
a POS device and can be run locally or in CI to validate endpoint behavior.
