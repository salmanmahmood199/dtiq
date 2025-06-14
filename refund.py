#!/usr/bin/env python3
import os
import json
import uuid
import time
import random
import requests
import datetime
from decimal import Decimal, ROUND_HALF_UP

# ——— Configuration ———
IDENTITY_URL = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID = 'externalPartner_NSRPetrol'
CLIENT_SECRET = 'PLuz6j0b1D8Iqi2Clq2qv'
REFUND_URL = 'https://data-api-uat.go360iq.com/v1/Refunds'

# Token cache
TOKEN_CACHE = {
    'token': None,
    'expiry': 0
}

# ——— Helpers ———
def fetch_token():
    """OAuth client_credentials → bearer token with caching."""
    global TOKEN_CACHE
    
    # Check if we have a valid cached token
    current_time = time.time()
    if TOKEN_CACHE['token'] and TOKEN_CACHE['expiry'] > current_time + 60:
        print(f"Using cached token (expires in {int(TOKEN_CACHE['expiry'] - current_time)} seconds)")
        return TOKEN_CACHE['token']
    
    # Need to fetch a new token
    print("Fetching new auth token...")
    try:
        r = requests.post(
            IDENTITY_URL,
            data={
                'grant_type': 'client_credentials',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
            },
            timeout=10
        )
        r.raise_for_status()
        response = r.json()
        
        # Cache the token
        TOKEN_CACHE['token'] = response['access_token']
        TOKEN_CACHE['expiry'] = current_time + response['expires_in']
        
        print(f"New token obtained, expires in {response['expires_in']} seconds")
        return TOKEN_CACHE['token']
    except Exception as e:
        print(f"Error fetching auth token: {e}")
        raise

def build_refund_payload(tx: dict) -> dict:
    """
    Turn one of your JSONs into a RefundTransaction payload.
    • Uses static store '1001' so the API recognizes it.
    • Quantizes all money fields to 2 decimals.
    • Sets OrderState='Closed' as required for refunds.
    """
    ts_utc   = tx['ts_utc']                            # e.g. "2025-05-30T14:24:01"
    biz_date = ts_utc[:10].replace('-', '')            # "20250530"

    # 1) Line items (price NEGATIVE for refunds):
    items = []
    for idx, item in enumerate(tx.get('items', []), start=1):
        price = Decimal(item.get('price', 0.0))
        quant_price = float(
            (price).quantize(Decimal('0.01'), ROUND_HALF_UP)
        )
        items.append({
            'OrderItemState': [
                { 'ItemState': {'value': 'Added'}, 'Timestamp': ts_utc }
            ],
            'MenuProduct': {
                'menuProductID': f"{tx['seq']}_{idx}",
                'name':          item.get('name', ''),
                'MenuItem': [
                    {
                        'ItemType':    'Sale',
                        'Category':    'Refund',
                        'iD':          f"{tx['seq']}_{idx}_MI",
                        'Description': item.get('name', ''),
                        'Pricing': [
                            {
                                'Tax':       [],
                                # POS JSON already has negative price for refunds
                                'ItemPrice': quant_price,
                                'Quantity':  item.get('quantity', 1)
                            }
                        ],
                        'SKU': {
                            'productName': item.get('name', ''),
                            'productCode': f"{tx['seq']}_{idx}"
                        }
                    }
                ],
                'SKU': {
                    'productName': item.get('name', ''),
                    'productCode': f"{tx['seq']}_{idx}"
                }
            }
        })

    # 2) Subtotal (sum of POS prices, which are negative):
    raw_sub = sum(i.get('price', 0.0) * i.get('quantity', 1)
                  for i in tx.get('items', []))
    total_items = float(
        Decimal(raw_sub).quantize(Decimal('0.01'), ROUND_HALF_UP)
    )

    # 3) RefundTotal comes from payments
    raw_refund = sum(p.get('amount', 0.0) for p in tx.get('payments', []))
    refund_total = float(
        Decimal(raw_refund).quantize(Decimal('0.01'), ROUND_HALF_UP)
    )

    # 4) Payments array
    payments = []
    for p in tx.get('payments', []):
        amt = p.get('amount', 0.0)
        if amt == 0: 
            continue
        payments.append({
            'Timestamp':  ts_utc,
            'Status':     'Accepted',
            'Amount':     amt,
            'Change':     0.0,
            'TenderType': {'value': p.get('tenderType', 'Other')}
        })

    # 5) Order object
    order = {
        'OrderID':        tx['guid'],
        'OrderNumber':    int(tx.get('seq', 0)),
        'OrderTime':      ts_utc,
        'OrderState':     'Closed',        # required for refund events
        'OrderItem':      items,
        'Total':          {'ItemPrice': total_items, 'Tax': []},
        'OrderItemCount': len(items),
        'Payment':        payments
    }

    # 6) Wrap it up
    return {
        # 'model' field will be added at the top level during API call
        'Event': {
            'TransactionGUID':          tx['guid'],
            'TransactionDateTimeStamp': ts_utc,
            'TransactionType':          'New',
            'BusinessDate':             biz_date,
            'Location': {
                'LocationID':  '1001',                 # ← YOUR VALID STORE
                'Description': 'Windsor Mill 711'      # ← SAME AS nosale/newvoid
            },
            'TransactionDevice': {
                'DeviceID':          tx.get('terminal', ''),
                'DeviceDescription': f"POS Terminal {tx.get('terminal', '')}"
            },
            'Employee': {
                'EmployeeID':       'OP5',
                'EmployeeFullName': 'Operator Five'
            },
            'EventTypeRefund': {
                'Refund': {
                    'RefundTotal':            refund_total,
                    'RefundTransactionType': {
                        'Order': order
                    }
                }
            }
        }
    }

def generate_test_refund_data():
    """Generate a sample transaction for refund testing."""
    # Create a timestamp in the required format
    now = datetime.datetime.now(datetime.UTC)  # Using UTC timezone-aware object
    ts_utc = now.strftime("%Y-%m-%dT%H:%M:%S")
    
    # Generate a unique transaction ID
    tx_id = random.randint(1000, 9999)
    guid = str(uuid.uuid4())
    terminal = f"T{random.randint(1, 5)}"
    
    # Generate random items
    items = [
        {
            "name": "Coffee",
            "price": -3.99,  # Negative for refund
            "quantity": 1
        },
        {
            "name": "Donut",
            "price": -1.50,  # Negative for refund
            "quantity": 2
        }
    ]
    
    # Generate payment
    refund_amount = sum(item["price"] * item["quantity"] for item in items)
    payments = [
        {
            "tenderType": "CreditCard",  # Updated to valid TenderType from API validation
            "amount": abs(refund_amount)  # Positive amount for the refund payment
        }
    ]
    
    # Return the transaction data
    return {
        "seq": tx_id,
        "guid": guid,
        "terminal": terminal,
        "ts_utc": ts_utc,
        "items": items,
        "payments": payments
    }

def test_refund():
    """Standalone function to test refund API with generated data."""
    print("\n===== Testing Refund API =====")
    
    # Generate test data
    test_data = generate_test_refund_data()
    print(f"Generated test transaction: {json.dumps(test_data, indent=2)}")
    
    # Fetch token and build headers
    token = fetch_token()
    headers = {
        'Authorization': f'Bearer {token}',
        'External-Party-ID': CLIENT_ID,
        'Content-Type': 'application/json'
    }
    
    # Build and send payload
    payload = build_refund_payload(test_data)
    
    # Add model field at top level for API requirements
    final_payload = {
        "model": "RefundTransaction",
        **payload
    }
    
    print(f"\n--- SENDING Refund Transaction ---")
    print(json.dumps(final_payload, indent=2))
    
    try:
        resp = requests.post(REFUND_URL, headers=headers, json=final_payload, timeout=10)
        print(f"\n--- RESPONSE: {resp.status_code} ---")
        print(f"Headers: {dict(resp.headers)}")
        
        if resp.text:
            try:
                formatted_json = json.dumps(resp.json(), indent=2)
                print(f"Response JSON: {formatted_json}")
            except json.JSONDecodeError:
                print(f"Response Text: {resp.text}")
        
        resp.raise_for_status()  # Raise exception for non-200 responses
        print("\n✅ Refund API test completed successfully!")
        return True
    except Exception as e:
        print(f"\n❌ Error in Refund API test: {e}")
        return False

# ——— Main flow ———
def main():
    """Run refund tests with generated test data."""
    test_refund()

if __name__ == '__main__':
    main()
