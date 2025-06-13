#!/usr/bin/env python3
"""
test_api.py

A simple script to test the 360iQ Data API endpoints.
"""

import json
import time
import requests
from pprint import pprint

# Configuration from the original script
IDENTITY_URL    = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID       = 'externalPartner_NSRPetrol'
CLIENT_SECRET   = 'PLuz6j0b1D8Iqi2Clq2qv'
CASH_URL        = 'https://data-api-uat.go360iq.com/v1/CashOperations'
TXN_URL         = 'https://data-api-uat.go360iq.com/v1/Transactions'
REFUND_URL      = 'https://data-api-uat.go360iq.com/v1/Refunds'

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
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10)
        return {
            'status_code': resp.status_code,
            'success': 200 <= resp.status_code < 300,
            'response': resp.json() if resp.text and resp.status_code < 300 else resp.text
        }
    except Exception as e:
        return {
            'status_code': 0,
            'success': False,
            'response': str(e)
        }

def test_cash_operations_api():
    """Test the Cash Operations API endpoint"""
    # Sample payload for cash operations
    payload = {
        'model': 'CashOperation',
        'Event': {
            'TransactionGUID': '12345678-1234-1234-1234-123456789012',
            'TransactionDateTimeStamp': '2023-01-01T12:00:00',
            'TransactionType': 'New',
            'BusinessDate': '20230101',
            'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
            'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
            'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
            'EventTypeCashOperation': {
                'CashOperation': {
                    'CashOperationType': {'value': 'PaidIn'},
                    'Amount': 50.00,
                    'Reason': 'Test Cash Operation'
                }
            }
        }
    }
    
    print("\n=== Testing Cash Operations API ===")
    result = make_api_request(CASH_URL, payload)
    print(f"Status Code: {result['status_code']}")
    print(f"Success: {result['success']}")
    print("Response:")
    pprint(result['response'])

def test_transactions_api():
    """Test the Transactions API endpoint"""
    # Sample payload for transactions
    payload = {
        'model': 'Transaction',
        'Event': {
            'TransactionGUID': '12345678-2345-2345-2345-123456789012',
            'TransactionDateTimeStamp': '2023-01-01T13:00:00',
            'TransactionType': 'New',
            'BusinessDate': '20230101',
            'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
            'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
            'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
            'EventTypeTransaction': {
                'Transaction': {
                    'SubTotal': 15.00,
                    'Tax': [{'Description': 'Sales Tax', 'Amount': 1.50}],
                    'Total': 16.50,
                    'Order': {
                        'OrderID': '12345678-2345-2345-2345-123456789012',
                        'OrderNumber': 123,
                        'OrderTime': '2023-01-01T13:00:00',
                        'OrderState': 'Closed',
                        'OrderItem': [
                            {
                                'OrderItemState': [{'ItemState': {'value': 'Added'}, 'Timestamp': '2023-01-01T13:00:00'}],
                                'MenuProduct': {
                                    'menuProductID': '123_1',
                                    'name': 'Test Product',
                                    'MenuItem': [
                                        {
                                            'ItemType': 'Regular',
                                            'Category': 'Test Category',
                                            'iD': '123_1_MI',
                                            'Description': 'Test Product',
                                            'Pricing': [{'Tax': [], 'ItemPrice': 15.0, 'Quantity': 1}],
                                            'SKU': {'productName': 'Test Product', 'productCode': '123_1'}
                                        }
                                    ],
                                    'SKU': {'productName': 'Test Product', 'productCode': '123_1'}
                                }
                            }
                        ],
                        'Total': {'ItemPrice': 15.00, 'Tax': [{'Description': 'Sales Tax', 'Amount': 1.50}]},
                        'OrderItemCount': 1,
                        'Payment': [
                            {
                                'Timestamp': '2023-01-01T13:00:00',
                                'Status': 'Accepted',
                                'Amount': 16.50,
                                'Change': 0.0,
                                'TenderType': {'value': 'Cash'}
                            }
                        ]
                    }
                }
            }
        }
    }
    
    print("\n=== Testing Transactions API ===")
    result = make_api_request(TXN_URL, payload)
    print(f"Status Code: {result['status_code']}")
    print(f"Success: {result['success']}")
    print("Response:")
    pprint(result['response'])

def test_refunds_api():
    """Test the Refunds API endpoint"""
    # Sample payload for refunds
    payload = {
        'model': 'RefundTransaction',
        'Event': {
            'TransactionGUID': '12345678-3456-3456-3456-123456789012',
            'TransactionDateTimeStamp': '2023-01-01T14:00:00',
            'TransactionType': 'New',
            'BusinessDate': '20230101',
            'Location': {'LocationID': '1001', 'Description': 'Store 1001'},
            'TransactionDevice': {'DeviceID': '1', 'DeviceDescription': 'POS Terminal 1'},
            'Employee': {'EmployeeID': '101', 'EmployeeFullName': 'Test Employee'},
            'EventTypeRefund': {
                'Refund': {
                    'RefundTotal': 16.50,
                    'RefundTransactionType': {
                        'Order': {
                            'OrderID': '12345678-3456-3456-3456-123456789012',
                            'OrderNumber': 124,
                            'OrderTime': '2023-01-01T14:00:00',
                            'OrderState': 'Closed',
                            'OrderItem': [
                                {
                                    'OrderItemState': [{'ItemState': {'value': 'Added'}, 'Timestamp': '2023-01-01T14:00:00'}],
                                    'MenuProduct': {
                                        'menuProductID': '124_1',
                                        'name': 'Test Refund Product',
                                        'MenuItem': [
                                            {
                                                'ItemType': 'Refund',
                                                'Category': 'Refund',
                                                'iD': '124_1_MI',
                                                'Description': 'Test Refund Product',
                                                'Pricing': [{'Tax': [], 'ItemPrice': 15.0, 'Quantity': 1}],
                                                'SKU': {'productName': 'Test Refund Product', 'productCode': '124_1'}
                                            }
                                        ],
                                        'SKU': {'productName': 'Test Refund Product', 'productCode': '124_1'}
                                    }
                                }
                            ],
                            'Total': {'ItemPrice': 15.00, 'Tax': []},
                            'OrderItemCount': 1,
                            'Payment': [
                                {
                                    'Timestamp': '2023-01-01T14:00:00',
                                    'Status': 'Accepted',
                                    'Amount': 16.50,
                                    'Change': 0.0,
                                    'TenderType': {'value': 'Cash'}
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    
    print("\n=== Testing Refunds API ===")
    result = make_api_request(REFUND_URL, payload)
    print(f"Status Code: {result['status_code']}")
    print(f"Success: {result['success']}")
    print("Response:")
    pprint(result['response'])

def show_available_functions():
    """Display the available API testing functions"""
    print("\nAvailable API testing functions:")
    print("1. test_cash_operations_api() - Test the Cash Operations API endpoint")
    print("2. test_transactions_api() - Test the Transactions API endpoint")
    print("3. test_refunds_api() - Test the Refunds API endpoint")
    print("4. fetch_token() - Just fetch and display the authentication token")
    print("\nExample usage: test_cash_operations_api()")

if __name__ == "__main__":
    print("360iQ Data API Testing Tool")
    print("---------------------------")
    show_available_functions()
    
    # Uncomment these lines to test the endpoints directly
    # test_cash_operations_api()
    # test_transactions_api()
    # test_refunds_api()
