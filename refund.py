#!/usr/bin/env python3
import os
import json
import requests
from decimal import Decimal, ROUND_HALF_UP

# ——— Configuration ———
IDENTITY_URL   = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID      = 'externalPartner_NSRPetrol'
CLIENT_SECRET  = 'PLuz6j0b1D8Iqi2Clq2qv'
REFUND_URL     = 'https://data-api-uat.go360iq.com/v1/Refunds'

# Directory & files
JSON_DIR = r'C:\Users\station6\Documents\dtiqapi\converted_json'
FILES = ['COM3_6198.json', 'COM4_8430.json', 'COM4_9286.json']

# ——— Helpers ———
def fetch_token():
    """OAuth client_credentials → bearer token."""
    r = requests.post(
        IDENTITY_URL,
        data={
            'grant_type':    'client_credentials',
            'client_id':     CLIENT_ID,
            'client_secret': CLIENT_SECRET,
        },
        timeout=10
    )
    r.raise_for_status()
    return r.json()['access_token']

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
        'model': 'RefundTransaction',
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

# ——— Main flow ———
def main():
    token = fetch_token()
    headers = {
        'Authorization':     f'Bearer {token}',
        'External-Party-ID': CLIENT_ID,
        'Content-Type':      'application/json'
    }

    for fname in FILES:
        path = os.path.join(JSON_DIR, fname)
        with open(path) as f:
            tx = json.load(f)

        payload = build_refund_payload(tx)
        print(f"\n--- SENDING Refund for {fname} ---")
        print(json.dumps(payload, indent=2))

        resp = requests.post(REFUND_URL, headers=headers, json=payload, timeout=10)
        print(f"→ {resp.status_code}")
        print(resp.text)

if __name__ == '__main__':
    main()
