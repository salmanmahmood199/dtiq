#!/usr/bin/env python3
"""
promo_test.py

A focused script to test the 360iQ Data API with promotion transactions.
Updates timestamps to current date for proper testing.
"""

import json
import time
import requests
from datetime import datetime, timezone
import re

# Configuration from the original script
IDENTITY_URL    = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID       = 'externalPartner_NSRPetrol'
CLIENT_SECRET   = 'PLuz6j0b1D8Iqi2Clq2qv'
TXN_URL         = 'https://data-api-uat.go360iq.com/v1/Transactions'

# Token cache
_token_data = {'access_token': None, 'expires_at': 0.0}

def fetch_token():
    """Get an authentication token from the identity server"""
    now = time.time()
    if _token_data['access_token'] and (_token_data['expires_at'] - 60) > now:
        return _token_data['access_token']
    
    print("Fetching new authentication token...")
    resp = requests.post(
        IDENTITY_URL,
        data={
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
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

def make_api_request(url, payload):
    """Make a request to one of the API endpoints"""
    token = fetch_token()
    if not token:
        return None
    
    headers = {
        'Authorization': f"Bearer {token}",
        'External-Party-ID': CLIENT_ID,
        'Content-Type': 'application/json'
    }
    
    print(f"Making request to: {url}")
    print(f"Payload preview: {json.dumps(payload)[:200]}...")
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        print(f"Response status: {resp.status_code}")
        
        return {
            'status_code': resp.status_code,
            'success': 200 <= resp.status_code < 300,
            'response': resp.json() if resp.text and 200 <= resp.status_code < 300 else resp.text
        }
    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            'status_code': 0,
            'success': False,
            'response': str(e)
        }

def update_timestamps(payload, current_date=None):
    """Update all timestamps in the payload to current date"""
    if current_date is None:
        current_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    # Deep conversion of timestamps
    if isinstance(payload, dict):
        for key, value in list(payload.items()):
            if key in ['TransactionDateTimeStamp', 'Timestamp', 'OrderTime'] and isinstance(value, str):
                # Keep time portion but update date
                try:
                    time_part = value[11:]  # Extract time part
                    payload[key] = f"{current_date}T{time_part}"
                except:
                    payload[key] = f"{current_date}T12:00:00"
            elif key == 'BusinessDate' and isinstance(value, str):
                # Format as YYYYMMDD
                payload[key] = current_date.replace('-', '')
            else:
                update_timestamps(value, current_date)
    elif isinstance(payload, list):
        for item in payload:
            update_timestamps(item, current_date)
    
    return payload

def test_promotion_transaction():
    """Test a transaction with promotions"""
    # Sample transaction with promotion
    payload = {
        'model': 'Transaction',
        'Event': {
            'TransactionGUID': '12345678-2345-2345-2345-123456789012',
            'TransactionDateTimeStamp': '2025-06-13T13:00:00',
            'TransactionType': 'New',
            'BusinessDate': '20250613',
            'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
            'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
            'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
            'EventTypeOrder': {
                'Order': {
                    'OrderID': '12345678-2345-2345-2345-123456789012',
                    'OrderNumber': 123,
                    'OrderTime': '2025-06-13T13:00:00',
                    'OrderState': 'Closed',
                    'OrderItem': [
                        {
                            'OrderItemState': [{'ItemState': {'value': 'Added'}, 'Timestamp': '2025-06-13T13:00:00'}],
                            'MenuProduct': {
                                'menuProductID': '123_1',
                                'name': 'Test Product',
                                'MenuItem': [
                                    {
                                        'ItemType': 'Sale',
                                        'Category': 'Test Category',
                                        'iD': '123_1_MI',
                                        'Description': 'Test Product',
                                        'Pricing': [{'Tax': [], 'ItemPrice': 15.0, 'Quantity': 1}],
                                        'SKU': {'productName': 'Test Product', 'productCode': '123_1'}
                                    }
                                ],
                                'SKU': {'productName': 'Test Product', 'productCode': '123_1'}
                            }
                        },
                        {
                            'OrderItemState': [{'ItemState': {'value': 'Added'}, 'Timestamp': '2025-06-13T13:00:00'}],
                            'MenuProduct': {
                                'menuProductID': '123_2',
                                'name': 'PROMO EVD ValueGrl3x',  # Promotion item
                                'MenuItem': [
                                    {
                                        'ItemType': 'Sale',
                                        'Category': 'Promotion',
                                        'iD': '123_2_MI',
                                        'Description': 'PROMO EVD ValueGrl3x',
                                        'Pricing': [{'Tax': [], 'ItemPrice': -2.97, 'Quantity': 1}],  # Negative price for discount
                                        'SKU': {'productName': 'PROMO EVD ValueGrl3x', 'productCode': '123_2'}
                                    }
                                ],
                                'SKU': {'productName': 'PROMO EVD ValueGrl3x', 'productCode': '123_2'}
                            }
                        }
                    ],
                    'Total': {'ItemPrice': float(12.03), 'Tax': [{'Description': 'Sales Tax', 'Amount': float(1.50)}]},
                    'OrderItemCount': 2,
                    'Payment': [
                        {
                            'Timestamp': '2025-06-13T13:00:00',
                            'Status': 'Accepted',
                            'Amount': 13.53,
                            'Change': 0.0,
                            'TenderType': {'value': 'Cash'}
                        }
                    ],
                    'SubTotal': 15.00,
                    'Discount': 2.97,  # Promotion discount
                    'Tax': [{'Description': 'Sales Tax', 'Amount': 1.50}],
                    'Total': 13.53
                }
            }
        }
    }
    
    # Ensure all timestamps are up to date
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    payload = update_timestamps(payload, today)
    
    print("Testing transaction with promotion...")
    result = make_api_request(TXN_URL, payload)
    
    if result and result['success']:
        print("✅ Successfully sent transaction with promotion!")
        print(f"Response: {json.dumps(result['response'], indent=2)}")
    else:
        print("❌ Failed to send transaction")
        print(f"Status code: {result['status_code']}")
        print(f"Response: {result['response']}")

if __name__ == "__main__":
    print("360iQ Data API Promotion Testing")
    print("--------------------------------")
    test_promotion_transaction()
