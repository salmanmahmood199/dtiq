#!/usr/bin/env python3
"""
void_test.py

A script to test the 360iQ Data API with void transactions.
Based on the API documentation and the original script structure.
"""

import json
import time
import requests
from datetime import datetime, timezone

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
    """Make a request to one of the API endpoints with detailed logging"""
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
    print(json.dumps(payload, indent=2)[:800] + "...")
    
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

def test_void_transaction():
    """Test a void transaction"""
    # Get current timestamp in UTC
    current_time = datetime.now(timezone.utc)
    ts_utc = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    business_date = current_time.strftime('%Y%m%d')
    
    # Transaction GUID
    guid = "12345678-1234-5678-1234-567812345687"
    
    # Items list with a voided item
    items_list = [
        {
            'OrderItemState': [{'ItemState': {'value': 'Voided'}, 'Timestamp': ts_utc}],
            'MenuProduct': {
                'menuProductID': 'PID7890_1',
                'name': 'Test Voided Product',
                'MenuItem': [{
                    'ItemType': 'Voided',
                    'Category': 'General',
                    'iD': 'PID7890_1_MI',
                    'Description': 'Test Voided Product',
                    'Pricing': [{'Tax': [], 'ItemPrice': 15.0, 'Quantity': 1}],
                    'SKU': {'productName': 'Test Voided Product', 'productCode': 'PID7890_1'}
                }],
                'SKU': {'productName': 'Test Voided Product', 'productCode': 'PID7890_1'}
            }
        }
    ]
    
    # Payment (even for void transactions, payment information is often required)
    payments = [
        {
            'Timestamp': ts_utc,
            'Status': 'Accepted',
            'Amount': 0.0,  # No payment for void transaction
            'Change': 0.0,
            'TenderType': {'value': 'Cash'}
        }
    ]
    
    # Tax array
    tax_arr = [{'amount': 0.0, 'Description': 'Sales Tax'}]
    
    # Main event structure
    event = {
        'TransactionGUID': guid,
        'TransactionDateTimeStamp': ts_utc,
        'TransactionType': 'Update',  # Use Update for void transactions
        'BusinessDate': business_date,
        'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
        'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
        'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
        'EventTypeOrder': {
            'Order': {
                'OrderID': guid,
                'OrderNumber': 7891,
                'OrderTime': ts_utc,
                'OrderState': 'Voided',  # Set order state to Voided
                'OrderItem': items_list,
                'Total': {'ItemPrice': 0.0, 'Tax': tax_arr},
                'OrderItemCount': len(items_list),
                'Payment': payments
            }
        }
    }
    
    # Complete payload
    payload = {'model': 'Transaction', 'Event': event}
    
    print("Testing void transaction...")
    result = make_api_request(TXN_URL, payload)
    
    if result and result['success']:
        print("\n✅ Successfully sent void transaction!")
    else:
        print("\n❌ Failed to send void transaction")

# Second test - partial void (some items voided in a transaction)
def test_partial_void_transaction():
    """Test a transaction with a mix of regular and voided items"""
    # Get current timestamp in UTC
    current_time = datetime.now(timezone.utc)
    ts_utc = current_time.strftime('%Y-%m-%dT%H:%M:%S')
    business_date = current_time.strftime('%Y%m%d')
    
    # Transaction GUID
    guid = "12345678-1234-5678-1234-567812345688"
    
    # Items list with both regular and voided items
    items_list = [
        {
            'OrderItemState': [{'ItemState': {'value': 'Added'}, 'Timestamp': ts_utc}],
            'MenuProduct': {
                'menuProductID': 'PID7890_1',
                'name': 'Regular Product',
                'MenuItem': [{
                    'ItemType': 'Sale',
                    'Category': 'General',
                    'iD': 'PID7890_1_MI',
                    'Description': 'Regular Product',
                    'Pricing': [{'Tax': [], 'ItemPrice': 10.0, 'Quantity': 1}],
                    'SKU': {'productName': 'Regular Product', 'productCode': 'PID7890_1'}
                }],
                'SKU': {'productName': 'Regular Product', 'productCode': 'PID7890_1'}
            }
        },
        {
            'OrderItemState': [{'ItemState': {'value': 'Voided'}, 'Timestamp': ts_utc}],
            'MenuProduct': {
                'menuProductID': 'PID7890_2',
                'name': 'Voided Product',
                'MenuItem': [{
                    'ItemType': 'Voided',
                    'Category': 'General',
                    'iD': 'PID7890_2_MI',
                    'Description': 'Voided Product',
                    'Pricing': [{'Tax': [], 'ItemPrice': 5.0, 'Quantity': 1}],
                    'SKU': {'productName': 'Voided Product', 'productCode': 'PID7890_2'}
                }],
                'SKU': {'productName': 'Voided Product', 'productCode': 'PID7890_2'}
            }
        }
    ]
    
    # Payment
    payments = [
        {
            'Timestamp': ts_utc,
            'Status': 'Accepted',
            'Amount': 10.0,  # Only paying for the regular item
            'Change': 0.0,
            'TenderType': {'value': 'Cash'}
        }
    ]
    
    # Tax array
    tax_arr = [{'amount': 0.0, 'Description': 'Sales Tax'}]
    
    # Main event structure
    event = {
        'TransactionGUID': guid,
        'TransactionDateTimeStamp': ts_utc,
        'TransactionType': 'Update',  # Use Update for transactions with voids
        'BusinessDate': business_date,
        'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
        'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
        'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
        'EventTypeOrder': {
            'Order': {
                'OrderID': guid,
                'OrderNumber': 7892,
                'OrderTime': ts_utc,
                'OrderState': 'Closed',  # Order is still closed since not everything is voided
                'OrderItem': items_list,
                'Total': {'ItemPrice': 10.0, 'Tax': tax_arr},
                'OrderItemCount': len(items_list),
                'Payment': payments
            }
        }
    }
    
    # Complete payload
    payload = {'model': 'Transaction', 'Event': event}
    
    print("\nTesting partial void transaction...")
    result = make_api_request(TXN_URL, payload)
    
    if result and result['success']:
        print("\n✅ Successfully sent partial void transaction!")
    else:
        print("\n❌ Failed to send partial void transaction")

if __name__ == "__main__":
    print("360iQ Data API Void Testing")
    print("--------------------------------")
    test_void_transaction()
    test_partial_void_transaction()
