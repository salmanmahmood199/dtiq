#!/usr/bin/env python3
"""
nosale_test.py

A script to test the 360iQ Data API with no-sale drawer events.
Modified to work with the local test environment on macOS.
"""

import os
import json
import time
import uuid
import requests
from datetime import datetime, timezone

# ——— Configuration ———
IDENTITY_URL   = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID      = 'externalPartner_NSRPetrol'
CLIENT_SECRET  = 'PLuz6j0b1D8Iqi2Clq2qv'
CASH_URL       = 'https://data-api-uat.go360iq.com/v1/CashOperations'

# Token cache
_token_data = {'access_token': None, 'expires_at': 0.0}

# Local paths for Mac environment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# We'll generate test data since the original files might not exist on Mac

def fetch_token():
    """Obtain OAuth token via client_credentials with caching."""
    now = time.time()
    if _token_data['access_token'] and (_token_data['expires_at'] - 60) > now:
        return _token_data['access_token']
    
    print("Fetching new authentication token...")
    resp = requests.post(
        IDENTITY_URL,
        data={
            'grant_type':    'client_credentials',
            'client_id':     CLIENT_ID,
            'client_secret': CLIENT_SECRET,
        },
        timeout=10
    )
    
    if resp.status_code != 200:
        print(f"Error fetching token: {resp.status_code}")
        print(resp.text)
        return None
    
    js = resp.json()
    token = js['access_token']
    _token_data['access_token'] = token
    _token_data['expires_at'] = now + js.get('expires_in', 3600)
    print(f"Token obtained! Expires in {js.get('expires_in', 3600)} seconds")
    
    return token

def generate_test_data():
    """
    Generate test data for a no-sale drawer event.
    In a real environment, this would come from the POS system.
    """
    current_time = datetime.now(timezone.utc)
    ts_utc = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    
    return {
        "guid": str(uuid.uuid4()),
        "ts_utc": ts_utc,
        "terminal": "01",
        "seq": "9876"
    }

def build_cash_op_payload(tx: dict, operation_type="PaidOut") -> dict:
    """
    Construct a Cash Operation payload for a no-sale drawer event.
    
    Parameters:
    - tx: Transaction data dictionary
    - operation_type: Type of drawer operation (PaidOut, NoSale, etc.)
    """
    ts_utc = tx['ts_utc']                     # e.g. "2025-05-30T15:00:20"
    biz_date = ts_utc[:10].replace('-', '')   # "20250530"
    seq = int(tx.get('seq', 0))
    
    return {
        "model": "CashOperation",
        "Event": {
            "TransactionGUID":          tx["guid"],
            "TransactionDateTimeStamp": ts_utc,
            "TransactionType":          "New",
            "BusinessDate":             biz_date,
            "Location": {
                "LocationID":  "1001",
                "Description": "Windsor Mill 711"
            },
            "TransactionDevice": {
                "DeviceID":          tx["terminal"],
                "DeviceDescription": f"POS Terminal {tx['terminal']}"
            },
            "Employee": {
                "EmployeeID":       "OP5",
                "EmployeeFullName": "Operator Five"
            },
            "EventTypeDrawer": {
                "Drawer": {
                    "DrawerEventGUID":      tx["guid"],
                    "DrawerEventNumber":    seq,
                    "DrawerOperationType":  operation_type,
                    "DrawerOpenTime":       ts_utc,
                    "DrawerTransactionReason": "No-Sale Drawer Open",
                    "ReasonDescription": "Testing no-sale drawer operations",
                    "CashManagement": [
                        { "Amount": 0.00 }
                    ]
                }
            }
        }
    }

def make_api_request(url, payload):
    """Make a request to one of the API endpoints with detailed logging."""
    token = fetch_token()
    if not token:
        return None
    
    headers = {
        'Authorization': f"Bearer {token}",
        'External-Party-ID': CLIENT_ID,
        'Content-Type': 'application/json'
    }
    
    print(f"\nMaking request to: {url}")
    print(f"Headers: {json.dumps(headers)}")
    print("Payload:")
    print(json.dumps(payload, indent=2))
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Response status: {resp.status_code}")
        
        if 200 <= resp.status_code < 300:
            print("Response body:")
            try:
                print(json.dumps(resp.json(), indent=2))
            except:
                print(resp.text[:1000])
            return {
                'status_code': resp.status_code,
                'success': True,
                'response': resp.json() if resp.text else {}
            }
        else:
            print("Error response:")
            try:
                print(json.dumps(resp.json(), indent=2))
            except:
                print(resp.text[:1000])
            return {
                'status_code': resp.status_code,
                'success': False,
                'response': resp.json() if resp.text else resp.text
            }
    except Exception as e:
        print(f"Error making request: {str(e)}")
        return {
            'status_code': 0,
            'success': False,
            'response': str(e)
        }

def test_no_sale():
    """Test a no-sale transaction."""
    test_data = generate_test_data()
    
    print("\n=== Testing No-Sale Transaction (PaidOut) ===\n")
    payload = build_cash_op_payload(test_data, "PaidOut")
    result = make_api_request(CASH_URL, payload)
    
    if result and result['success']:
        print("\n✅ Successfully sent PaidOut transaction!")
    else:
        print("\n❌ Failed to send PaidOut transaction")
    
    print("\n=== Testing No-Sale Transaction (CashDrop) ===\n")
    test_data = generate_test_data()  # Generate new GUID and timestamp
    payload = build_cash_op_payload(test_data, "CashDrop")
    result = make_api_request(CASH_URL, payload)
    
    if result and result['success']:
        print("\n✅ Successfully sent CashDrop transaction!")
    else:
        print("\n❌ Failed to send CashDrop transaction")

def main():
    print("360iQ Data API No-Sale Testing")
    print("--------------------------------")
    test_no_sale()

if __name__ == '__main__':
    main()
