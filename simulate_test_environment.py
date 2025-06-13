#!/usr/bin/env python3
"""Simulate a 360iQ API transaction for testing.

This script posts a single sample transaction to the 360iQ Data API.
The transaction timestamp is fixed at 6 PM America/New_York on
2025-06-13 so that front-end displays show the entry at the top.
Credentials are read from environment variables to avoid storing
secrets in the repository.
"""

import os
import uuid
import requests
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from zoneinfo import ZoneInfo

IDENTITY_URL = os.environ.get('IDENTITY_URL', 'https://identity-qa.go360iq.com/connect/token')
CLIENT_ID = os.environ.get('CLIENT_ID', 'externalPartner_NSRPetrol')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET', 'PLuz6j0b1D8Iqi2Clq2qv')
TXN_URL = os.environ.get('TXN_URL', 'https://data-api-uat.go360iq.com/v1/Transactions')


def fetch_token() -> str:
    resp = requests.post(
        IDENTITY_URL,
        data={
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()['access_token']


def build_sample_tx() -> dict:
    local_dt = datetime(2025, 6, 13, 18, 0, 0, tzinfo=ZoneInfo('America/New_York'))
    ts_utc = local_dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S')
    return {
        'guid': str(uuid.uuid4()),
        'ts_utc': ts_utc,
        'store': '1001',
        'terminal': '01',
        'seq': '1',
        'employee_id': 'demo',
        'employee_name': 'Demo User',
        'location_desc': 'Store 1001',
        'items': [
            {'name': 'Sample Item', 'price': 1.99, 'quantity': 1, 'event': 'add'},
        ],
        'voids': [],
        'payments': [
            {'amount': 1.99, 'tenderType': 'VISA'},
        ],
        'summary_map': {
            'SUBTOTAL': 1.99,
            'TAX ON 1.99': 0.0,
            'TOTAL DUE': 1.99,
        },
    }


def map_tender(desc: str) -> str:
    d = desc.upper()
    if 'CASH' in d:
        return 'Cash'
    if any(x in d for x in ('VISA', 'MASTERCARD', 'AMEX', 'DISCOVER')):
        return 'CreditCard'
    if 'DEBIT' in d:
        return 'DebitCard'
    if d.startswith(('ACCT#', 'ACCOUNT')):
        return 'AccountPayment'
    return 'Other'


def build_txn_payload(tx: dict) -> dict:
    sm = tx['summary_map']
    subtotal = sm.get('SUBTOTAL', 0.0)
    tax_amt = next((v for k, v in sm.items() if k.startswith('TAX')), 0.0)
    total_due = sm.get('TOTAL DUE', subtotal + tax_amt)
    net_item = Decimal(subtotal).quantize(Decimal('0.01'), ROUND_HALF_UP)
    tax_d = Decimal(tax_amt).quantize(Decimal('0.01'), ROUND_HALF_UP)
    tot_due = Decimal(total_due).quantize(Decimal('0.01'), ROUND_HALF_UP)
    paid = sum(p['amount'] for p in tx['payments'])
    paid_d = Decimal(paid).quantize(Decimal('0.01'), ROUND_HALF_UP)
    change = (paid_d - tot_due).quantize(Decimal('0.01'), ROUND_HALF_UP)

    items_list = []
    idx = 1
    for itm in tx['items'] + tx['voids']:
        is_void = itm['event'] == 'void'
        state = 'Voided' if is_void else 'Added'
        typ = 'Voided' if is_void else 'Sale'
        pid = f"PID{tx['seq']}_{idx}"
        idx += 1
        items_list.append({
            'OrderItemState': [{'ItemState': {'value': state}, 'Timestamp': tx['ts_utc']}],
            'MenuProduct': {
                'menuProductID': pid,
                'name': itm['name'],
                'MenuItem': [{
                    'ItemType': typ,
                    'Category': 'General',
                    'iD': f"{pid}_MI",
                    'Description': itm['name'],
                    'Pricing': [{'Tax': [], 'ItemPrice': itm['price'], 'Quantity': itm['quantity']}],
                    'SKU': {'productName': itm['name'], 'productCode': pid},
                }],
                'SKU': {'productName': itm['name'], 'productCode': pid},
            },
        })

    payments = []
    pi = 0
    for p in tx['payments']:
        amt = Decimal(p['amount']).quantize(Decimal('0.01'), ROUND_HALF_UP)
        if amt == 0:
            continue
        ch = float(change) if pi == 0 else 0.0
        payments.append({
            'Timestamp': tx['ts_utc'],
            'Status': 'Accepted',
            'Amount': float(amt),
            'Change': ch,
            'TenderType': {'value': map_tender(p['tenderType'])},
        })
        pi += 1

    tax_arr = [{'amount': float(tax_d), 'Description': 'Sales Tax'}] if tax_d > 0 else []

    evt = {
        'TransactionGUID': tx['guid'],
        'TransactionDateTimeStamp': tx['ts_utc'],
        'TransactionType': 'New',
        'BusinessDate': tx['ts_utc'][:10].replace('-', ''),
        'Location': {'LocationID': tx['store'], 'Description': tx['location_desc']},
        'TransactionDevice': {'DeviceID': tx['terminal'], 'DeviceDescription': f"POS Terminal {tx['terminal']}"},
        'Employee': {'EmployeeID': tx['employee_id'], 'EmployeeFullName': tx['employee_name']},
        'EventTypeOrder': {
            'Order': {
                'OrderID': tx['guid'],
                'OrderNumber': int(tx['seq']),
                'OrderTime': tx['ts_utc'],
                'OrderState': 'Closed',
                'OrderItem': items_list,
                'Total': {'ItemPrice': float(net_item), 'Tax': tax_arr},
                'OrderItemCount': len(items_list),
                'Payment': payments,
            }
        },
    }
    return {'model': 'Transaction', 'Event': evt}


def send_sample_transaction() -> None:
    tx = build_sample_tx()
    payload = build_txn_payload(tx)
    token = fetch_token()
    headers = {
        'Authorization': f"Bearer {token}",
        'External-Party-ID': CLIENT_ID,
        'Content-Type': 'application/json',
    }
    resp = requests.post(TXN_URL, json=payload, headers=headers, timeout=10)
    print(resp.status_code, resp.text)


if __name__ == '__main__':
    send_sample_transaction()
