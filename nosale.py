#!/usr/bin/env python3
import os
import json
import requests

# ——— Configuration ———
IDENTITY_URL   = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID      = 'externalPartner_NSRPetrol'
CLIENT_SECRET  = 'PLuz6j0b1D8Iqi2Clq2qv'
CASH_URL       = 'https://data-api-uat.go360iq.com/v1/CashOperations'

# Directory where your JSON lives
SALES_DIR      = r'C:\Users\station6\Documents\dtiqapi\converted_json'

# Only these two “no-sale” files
FILES = [
    'COM3_5653.json',
    'COM3_5709.json'
]

def fetch_token():
    """Obtain OAuth token via client_credentials."""
    resp = requests.post(
        IDENTITY_URL,
        data={
            'grant_type':    'client_credentials',
            'client_id':     CLIENT_ID,
            'client_secret': CLIENT_SECRET,
        },
        timeout=10
    )
    resp.raise_for_status()
    return resp.json()['access_token']

def build_cash_op_payload(tx: dict) -> dict:
    """
    Construct a Cash Operation payload for a no‐sale drawer event.
    """
    ts_utc   = tx['ts_utc']                    # e.g. "2025-05-30T15:00:20"
    biz_date = ts_utc[:10].replace('-', '')     # "20250530"
    seq      = int(tx.get('seq', 0))
    
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
                    "DrawerOperationType":  "PaidOut",
                    "DrawerOpenTime":       ts_utc,
                    "CashManagement": [
                        { "Amount": 0.00 }
                    ]
                }
            }
        }
    }

def main():
    token = fetch_token()
    headers = {
        'Authorization':     f'Bearer {token}',
        'External-Party-ID': CLIENT_ID,
        'Content-Type':      'application/json'
    }

    for fname in FILES:
        path = os.path.join(SALES_DIR, fname)
        with open(path, 'r') as f:
            tx = json.load(f)

        payload = build_cash_op_payload(tx)
        print(f"\n--- SENDING CashOperation for {fname} ---")
        print(json.dumps(payload, indent=2))

        resp = requests.post(CASH_URL, headers=headers, json=payload, timeout=10)
        print(f"→ {resp.status_code}")
        print(resp.text)

if __name__ == '__main__':
    main()
