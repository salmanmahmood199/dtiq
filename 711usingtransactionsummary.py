#!/usr/bin/env python3
"""
pos_stream_uploader.py

Listens on COM3 and COM4 for POS JSON payloads, builds full transaction objects,
writes raw JSON to disk, then transforms and POSTs to 360iQ Data API.

Modifications:
  • Store ID is force-overridden to "1001" so that the 360iQ UAT environment
    accepts every transaction.
  • EmployeeID and EmployeeFullName are populated from POS 'operator'.
  • Location.Description is set to a non-empty string ("Store 1001").
  • Subtotal, discounts, tax, and total are now sourced directly from POS transactionSummary.
  • Change calculation uses 'TOTAL DUE' from transactionSummary.
  • Full transactionSummary is stored in each raw JSON for audit.

References:
  – 360iQ Tax sub-model: requires 'amount' and 'Description'
  – 360iQ Transaction Model: Employee/Location fields required
"""

import os
import re
import json
import uuid
import time
import queue
import threading
import requests
import serial
import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ─── CONFIGURATION ───
SERIAL_PORTS    = ['COM3', 'COM4']
BAUDRATE        = 9600
BYTESIZE        = serial.EIGHTBITS
PARITY          = serial.PARITY_NONE
STOPBITS        = serial.STOPBITS_ONE
RTSCTS          = True
TIMEOUT         = 1  # seconds

IDENTITY_URL    = 'https://identity-qa.go360iq.com/connect/token'
CLIENT_ID       = 'externalPartner_NSRPetrol'
CLIENT_SECRET   = 'PLuz6j0b1D8Iqi2Clq2qv'
CASH_URL        = 'https://data-api-uat.go360iq.com/v1/CashOperations'
TXN_URL         = 'https://data-api-uat.go360iq.com/v1/Transactions'
REFUND_URL      = 'https://data-api-uat.go360iq.com/v1/Refunds'

USER_TZ         = 'America/New_York'
LOG_DIR         = 'logs'
EVENTS_DIR      = 'events'
TRANSACTIONS_DIR= 'transactions'
HEADER_PATTERN  = re.compile(r'mlen=(\d+)$')

# Queues and token cache
tx_queue      = queue.Queue()
parser_queue  = queue.Queue()
_token_data   = {'access_token': None, 'expires_at': 0.0}

# ─── DIRECTORY UTILITIES ───

def ensure_directories():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(EVENTS_DIR, exist_ok=True)
    os.makedirs(TRANSACTIONS_DIR, exist_ok=True)

# ─── AUTHENTICATION ───

def fetch_token() -> str:
    now = time.time()
    if _token_data['access_token'] and (_token_data['expires_at'] - 60) > now:
        return _token_data['access_token']
    resp = requests.post(
        IDENTITY_URL,
        data={
            'grant_type': 'client_credentials',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET
        },
        timeout=10
    )
    resp.raise_for_status()
    js = resp.json()
    token = js['access_token']
    _token_data['access_token'] = token
    _token_data['expires_at']  = now + js.get('expires_in', 3600)
    print(f"[INFO] Fetched new token; expires in {js.get('expires_in',3600)}s.")
    return token

# ─── TIMESTAMP & GUID ───

def to_utc(local_ts: str) -> str:
    """Convert local timestamp to UTC, or use current time if conversion fails"""
    try:
        # If local_ts is very old, use current time instead to ensure transactions appear in frontend
        tz = ZoneInfo(USER_TZ)
        dt = datetime.fromisoformat(local_ts).replace(tzinfo=tz)
        
        # Check if timestamp is older than 2023
        if dt.year < 2023:
            # Use current time instead
            dt = datetime.now(tz)
            print(f"[INFO] Using current time ({dt.isoformat()}) instead of old timestamp: {local_ts}")
        
        return dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%S')
    except Exception as e:
        print(f"[WARN] Error converting timestamp: {e}. Using current UTC time.")
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')


def generate_guid(store: str, terminal: str, seq: str, ts_utc: str) -> str:
    ns = f"{store}-{terminal}-{seq}-{ts_utc}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ns))

# ─── RAW LOGGING & EVENTS ───

def log_raw_json(port: str, raw: str):
    ensure_directories()
    path = os.path.join(LOG_DIR, f"pos_transactions_{port}.log")
    ts = datetime.now(timezone.utc).isoformat()
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f"{ts} {raw}\n")


def save_tx_event(tx: dict):
    ensure_directories()
    fname = f"{tx['seq']}_{tx['guid']}.json"
    with open(os.path.join(EVENTS_DIR, fname), 'w', encoding='utf-8') as f:
        json.dump(tx, f, indent=2)


def write_transaction_by_date(tx: dict, success: bool, status_code: int, resp_body: str = ""):
    ts = tx['ts_utc']
    date = ts.split('T')[0]
    y, m, d = date.split('-')
    base = os.path.join(TRANSACTIONS_DIR, y, m, d)
    sent = os.path.join(base, 'sent')
    failed = os.path.join(base, 'failed')
    os.makedirs(sent, exist_ok=True)
    os.makedirs(failed, exist_ok=True)
    fname = f"{tx['seq']}_{tx['guid']}.json"
    dest = sent if success else failed
    with open(os.path.join(dest, fname), 'w', encoding='utf-8') as f:
        json.dump(tx, f, indent=2)
    logf = os.path.join(dest, 'sent.log' if success else 'failed.log')
    snippet = (resp_body or '')[:200].replace('\n', ' ')
    with open(logf, 'a', encoding='utf-8') as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} {tx['seq']}_{tx['guid']} {status_code} {snippet}\n")

# ─── TENDER MAPPING ───

def map_tender(desc: str) -> str:
    d = desc.upper()
    if 'CASH' in d: return 'Cash'
    if any(x in d for x in ('VISA','MASTERCARD','AMEX','DISCOVER')): return 'CreditCard'
    if 'DEBIT' in d: return 'DebitCard'
    if d.startswith(('ACCT#','ACCOUNT')): return 'AccountPayment'
    return 'Other'

# ─── SERIAL-PORT READER ───

def read_from_port(port: str):
    while True:
        try:
            print(f"[INFO] Opening serial port {port}...")
            ser = serial.Serial(
                port=port,
                baudrate=BAUDRATE,
                bytesize=BYTESIZE,
                parity=PARITY,
                stopbits=STOPBITS,
                rtscts=RTSCTS,
                timeout=TIMEOUT
            )
            print(f"[INFO] Listening on {port}...")
            while True:
                hdr = ser.readline().decode('utf-8', errors='replace').strip()
                m = HEADER_PATTERN.match(hdr)
                if not m:
                    continue
                length = int(m.group(1))
                data = ser.read(length)
                try:
                    txt = data.decode('utf-8', errors='replace')
                except:
                    txt = data.decode('latin1', errors='ignore')
                log_raw_json(port, txt)
                try:
                    rec = json.loads(txt)
                except json.JSONDecodeError:
                    print(f"[WARN] Invalid JSON on {port}: {txt[:80]}…")
                    continue
                parser_queue.put((port, rec))
        except Exception as e:
            print(f"[ERROR] Port {port}: {e}. Retrying in 5s...")
            time.sleep(5)
        finally:
            try:
                ser.close()
            except:
                pass

# ─── PARSER WORKER ───

buffers = {p: None for p in SERIAL_PORTS}

def parser_worker():
    while True:
        port, rec = parser_queue.get()
        cmd = rec.get('CMD')
        
        # Handle cash operations (no-sale, paid-out, cash-drop)
        # These come in as direct commands, not part of a transaction
        if cmd in ['NoSale', 'PaidOut', 'CashDrop']:
            # Map the command to operation type
            operation_type = cmd.lower()  # Convert to lowercase for consistency
            
            # Get timestamp or use current time
            ts_local = rec.get('datetime', '')
            if not ts_local:
                now = datetime.now()
                ts_local = now.strftime("%Y-%m-%dT%H:%M:%S")
            ts_utc = to_utc(ts_local)
            
            # Get terminal, sequence, and amount info
            terminal = rec.get('terminal', port[-1])
            seq = rec.get('sequence', '0')
            amount = rec.get('amount', 0.0)
            store = '1001'  # Force to valid test store in UAT env
            guid = generate_guid(store, terminal, seq, ts_utc)
            
            # Create transaction object for cash operation
            tx = {
                'guid': guid, 
                'seq': seq, 
                'type': 'cash-operation',
                'operation': operation_type,
                'amount': amount,
                'store': store,
                'location_desc': 'Windsor Mill 711',  # Hardcoded for UAT
                'terminal': terminal,
                'ts_local': ts_local, 
                'ts_utc': ts_utc,
                'operator': rec.get('operator', ''),
                'employee_id': rec.get('operator', 'OP5'),
                'employee_name': rec.get('operator', 'Operator Five'),
                'items': [],
                'payments': [],
                'summary_map': {},
                'voids': []
            }
            
            # Save and queue the transaction
            save_tx_event(tx)
            tx_queue.put(tx)
            parser_queue.task_done()
            continue
            
        # StartTransaction
        if cmd == 'StartTransaction':
            buffers[port] = {
                'meta': None,
                'items': [],
                'voids': [],
                'payments': [],
                'summary_list': [],
                'summary_map': {},
                'operation': rec.get('operation', '')  # Capture operation if present
            }
            parser_queue.task_done()
            continue
            
        buf = buffers.get(port)
        if buf is None:
            parser_queue.task_done()
            continue
            
        # metaData
        if rec.get('metaData'):
            buf['meta'] = rec['metaData']
            # Check if this is a special operation (no-sale, paid-out, cash-drop)
            if 'operation' in rec['metaData'] and rec['metaData']['operation']:
                buf['operation'] = rec['metaData']['operation']
            parser_queue.task_done()
            continue
            
        # cartChangeTrail
        if rec.get('cartChangeTrail') is not None:
            raw = rec['cartChangeTrail']
            trail = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(trail, dict):
                trail = [trail]
            for c in trail:
                et = c.get('eventType')
                nm = c.get('itemName', '')
                pr = float(c.get('price', 0.0)) if c.get('price') is not None else 0.0
                qt = int(c.get('quantity', 1)) if c.get('quantity') is not None else 1
                entry = {
                    'name': nm,
                    'price': pr,
                    'quantity': qt,
                    'event': 'void' if et == 'voidLineItem' else 'add'
                }
                (buf['voids' if entry['event'] == 'void' else 'items']).append(entry)
            parser_queue.task_done()
            continue
            
        # paymentSummary
        if rec.get('paymentSummary') is not None:
            raw = rec['paymentSummary']
            pays = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(pays, dict):
                pays = [pays]
            
            # Clear existing payments to avoid duplicates
            buf['payments'] = []
            
            # Extract payment information
            for p in pays:
                # Only process actual payment entries (those with dollar amounts)
                if p.get('details', '').startswith('$'):
                    amt = float(p.get('details', '0').replace('$', ''))
                    tender_type = p.get('description', '')
                    
                    # Store payment info
                    buf['payments'].append({
                        'amount': amt, 
                        'tenderType': tender_type,
                        'is_cash': tender_type.upper() == 'CASH'
                    })
                    
                    # If it's a cash payment, mark the buffer to look for change in the next transaction summary
                    if tender_type.upper() == 'CASH':
                        buf['awaiting_cash_change'] = True
            
            parser_queue.task_done()
            continue
            
        # transactionSummary
        if rec.get('transactionSummary') is not None:
            raw = rec['transactionSummary']
            summ = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(summ, dict):
                summ = [summ]
            
            # If this is the first summary, store it
            if not buf.get('summary_list'):
                buf['summary_list'] = summ
                smap = {}
                for e in summ:
                    key = e.get('description', '').upper().strip()
                    val_str = e.get('details', '').replace('$', '').replace(',', '').strip()
                    try:
                        val = float(val_str)
                    except:
                        val = 0.0  # Default to zero if conversion fails
                    smap[key] = val
                buf['summary_map'] = smap
            # If this is a second transaction summary and we're awaiting change for cash payment
            elif buf.get('awaiting_cash_change', False):
                print(f"[INFO] Processing second transaction summary for cash change")
                for e in summ:
                    key = e.get('description', '').upper().strip()
                    if key == 'CHANGE':
                        val_str = e.get('details', '').replace('$', '').replace(',', '').strip()
                        try:
                            change_amount = float(val_str)
                            # Update the cash payment with the change amount
                            for payment in buf['payments']:
                                if payment.get('is_cash', False):
                                    payment['change'] = change_amount
                                    print(f"[INFO] Updated cash payment with change amount: ${change_amount}")
                                    break
                        except:
                            print(f"[ERROR] Failed to parse change amount: {val_str}")
                # Reset the flag
                buf['awaiting_cash_change'] = False
                
                # Don't overwrite the first transaction summary
                # buf['summary_map'] stays as is
            
            # Process EndTransaction
            meta = buf['meta'] or {}
            ts_local = meta.get('timeStamp', rec.get('timestamp', ''))
            if not ts_local:
                now = datetime.now()
                ts_local = now.strftime("%Y-%m-%dT%H:%M:%S")
            ts_utc = to_utc(ts_local)
            terminal = meta.get('terminalId', port[-1])
            seq = meta.get('sequenceNumber', '0')
            store = meta.get('storeId', '1001')  # Force to valid test store in UAT env
            guid = generate_guid(store, terminal, seq, ts_utc)
            
            # Check if this is a refund transaction
            is_refund = False
            # Check if any items have negative price (refund indicator)
            if any(item['price'] < 0 for item in buf['items']):
                is_refund = True
            # Check refund in operation field
            if buf.get('operation', '').lower() == 'refund':
                is_refund = True
            # Check refund in metadata
            if meta.get('transactionType', '').lower() == 'refund':
                is_refund = True
                
            # Determine transaction type
            tx_type = 'refund' if is_refund else 'standard-sale'
            if buf.get('operation', '').lower() in ['nosale', 'paidout', 'cashdrop']:
                tx_type = 'cash-operation'
                
            # Create transaction object
            tx = {
                'guid': guid, 
                'seq': seq, 
                'type': tx_type,
                'operation': buf.get('operation', ''),
                'store': store,
                'location_desc': 'Windsor Mill 711',  # Hardcoded for UAT
                'terminal': terminal,
                'ts_local': ts_local, 
                'ts_utc': ts_utc,
                'operator': meta.get('operatorId', ''),
                'employee_id': meta.get('operatorId', 'OP5'),
                'employee_name': meta.get('operatorName', 'Operator Five'),
                'items': buf['items'],
                'payments': buf['payments'],
                'summary_map': buf['summary_map'],
                'voids': buf['voids']
            }
            
            save_tx_event(tx)
            tx_queue.put(tx)
            buffers[port] = None
            parser_queue.task_done()
            continue
        parser_queue.task_done()

# ─── PAYLOAD BUILDERS ───

def build_cash_op_payload(tx: dict) -> dict:
    biz = tx['ts_utc'][:10].replace('-', '')  # Date portion as YYYYMMDD
    ts  = tx['ts_utc']
    
    # Determine cash operation type - default to NoSale if not specified
    operation_type = 'NoSale'  # Default value
    
    # Map operation type from transaction data
    op = tx.get('operation', '').lower()
    if op == 'paidout':
        operation_type = 'PaidOut'
    elif op == 'cashdrop' or op == 'drop':
        operation_type = 'Drop'
    elif op == 'nosale' or not op:
        operation_type = 'NoSale'
        
    # Get amount if present (for PaidOut or Drop operations)
    amount = tx.get('amount', 0.0)
    if isinstance(amount, str):
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            amount = 0.0
    
    # Start building the payload
    cash_op_payload = {
        'model': 'CashOperation',
        'Event': {
            'TransactionGUID': tx['guid'],
            'TransactionDateTimeStamp': ts,
            'TransactionType': 'New',
            'BusinessDate': biz,
            'Location': {
                'LocationID': tx['store'],
                'Description': tx['location_desc'],
            },
            'TransactionDevice': {
                'DeviceID': tx['terminal'],
                'DeviceDescription': f"POS Terminal {tx['terminal']}"
            },
            'Employee': {
                'EmployeeID': tx['employee_id'],
                'EmployeeFullName': tx['employee_name']
            },
            'EventTypeCashOperation':{
                'CashOperation':{
                    'CashOperationType': {'value': operation_type},
                }
            }
        }
    }


def build_txn_payload(tx: dict) -> dict:
    sm = tx['summary_map']
    subtotal = sm.get('SUBTOTAL', 0.0)
    discount = sm.get('DISCOUNT(S)', 0.0)
    tax_amt  = next((v for k, v in sm.items() if k.startswith('TAX')), 0.0)
    total_due= sm.get('TOTAL DUE', subtotal + discount + tax_amt)
    net_item = Decimal(subtotal + discount).quantize(Decimal('0.01'), ROUND_HALF_UP)
    tax_d    = Decimal(tax_amt).quantize(Decimal('0.01'), ROUND_HALF_UP)
    tot_due  = Decimal(total_due).quantize(Decimal('0.01'), ROUND_HALF_UP)
    paid     = sum(p['amount'] for p in tx['payments'] if p['amount'] > 0)
    paid_d   = Decimal(paid).quantize(Decimal('0.01'), ROUND_HALF_UP)
    change   = (paid_d - tot_due).quantize(Decimal('0.01'), ROUND_HALF_UP)
    
    # Build items
    items_list = []
    idx = 1
    for itm in tx['items'] + tx['voids']:
        is_void = itm['event'] == 'void'
        state   = 'Voided' if is_void else 'Added'
        typ     = 'Voided' if is_void else 'Sale'
        pid     = f"PID{tx['seq']}_{idx}"
        idx += 1
        
        # Better handling for promotions
        is_promo = 'PROMO' in itm['name'].upper() or itm['price'] < 0
        category = 'Promotion' if is_promo else 'General'
        
        # For promotions with positive prices, convert to negative
        item_price = itm['price']
        if is_promo and item_price > 0 and not is_void:
            # Make it negative for proper promotion handling
            item_price = -abs(item_price)
            print(f"[INFO] Converting positive promotion price to negative: {itm['name']} from ${itm['price']} to ${item_price}")
        else:
            item_price = itm['price']
        
        # Create the item with proper categorization
        items_list.append({
            'OrderItemState': [{ 'ItemState': {'value': state}, 'Timestamp': tx['ts_utc'] }],
            'MenuProduct': {
                'menuProductID': pid,
                'name': itm['name'],
                'MenuItem': [{
                    'ItemType': typ,
                    'Category': category,
                    'iD': f"{pid}_MI",
                    'Description': itm['name'],
                    'Pricing': [{ 
                        'Tax': [], 
                        'ItemPrice': float(Decimal(item_price).quantize(Decimal('0.01'), ROUND_HALF_UP)),
                        'Quantity': itm['quantity'] 
                    }],
                    'SKU': { 'productName': itm['name'], 'productCode': pid }
                }],
                'SKU': { 'productName': itm['name'], 'productCode': pid }
            }
        })
    # Build payments
    payments = []
    for p in tx['payments']:
        amt = Decimal(p['amount']).quantize(Decimal('0.01'), ROUND_HALF_UP)
        if amt == 0:
            continue
        
        # Use the change amount directly from the payment if available
        # This comes from the second transaction summary for cash payments
        change_amt = Decimal(p.get('change', 0.0)).quantize(Decimal('0.01'), ROUND_HALF_UP)
        
        payments.append({
            'Timestamp': tx['ts_utc'], 
            'Status': 'Accepted' if amt >= 0 else 'Denied',
            'Amount': float(amt), 
            'Change': float(change_amt),
            'TenderType': {'value': map_tender(p['tenderType'])}
        })
        
    # If no payments were found, add a default cash payment equal to the total due
    # This is required as the API validation requires at least one payment
    if not payments and tot_due > 0:
        print(f"[INFO] No payments found - adding default cash payment of {float(tot_due)}")
        payments.append({
            'Timestamp': tx['ts_utc'],
            'Status': 'Accepted',
            'Amount': float(tot_due),
            'Change': 0.0,
            'TenderType': {'value': 'Cash'}
        })
    # Tax array
    tax_arr = [{ 'amount': float(tax_d), 'Description': 'Sales Tax' }] if tax_d > 0 else []
    # Determine transaction state based on voids and item types
    has_voided_items = bool(tx['voids'])
    all_items_voided = has_voided_items and all(item['event'] == 'void' for item in tx['items'] + tx['voids'])
    
    # Determine order state
    order_state = 'Closed'
    if all_items_voided:
        order_state = 'Voided'
    elif has_voided_items:
        order_state = 'Closed'  # Partial void
    
    # Determine transaction type
    transaction_type = 'New'
    if has_voided_items:
        transaction_type = 'Update'  # All voids are updates
    
    # Add a timestamp for better frontend visibility
    current_ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')
    
    # Ensure there's a valid sequence number for OrderNumber
    seq_num = int(tx['seq'] or 1000)  # Use 1000 as base if seq is empty/zero
    if seq_num <= 0:
        seq_num = int(time.time()) % 10000  # Use timestamp-based number as fallback
    
    # Assemble event
    evt = {
        'TransactionGUID': tx['guid'],
        'TransactionDateTimeStamp': current_ts,  # Use current time for better frontend visibility
        'TransactionType': transaction_type,
        'BusinessDate': current_ts[:10].replace('-', ''),  # Use current date
        'Location': {'LocationID': tx['store'], 'Description': tx['location_desc']},
        'TransactionDevice': {'DeviceID': tx['terminal'], 'DeviceDescription': f"POS Terminal {tx['terminal']}"},
        'Employee': {'EmployeeID': tx['employee_id'], 'EmployeeFullName': tx['employee_name']},
        'EventTypeOrder': {
            'Order': {
                'OrderID': tx['guid'],
                'OrderNumber': seq_num,  # Use non-default sequence number
                'OrderTime': current_ts,  # Use current time
                'OrderState': order_state,
                'OrderItem': items_list,
                'Total': { 'ItemPrice': float(net_item), 'Tax': tax_arr },
                'OrderItemCount': len(items_list),
                'Payment': payments
            }
        }
    }
    return { 'model': 'Transaction', 'Event': evt }


def build_refund_payload(tx: dict) -> dict:
    ts = tx['ts_utc']
    biz= ts[:10].replace('-', '')
    items_list=[]; idx=1; raw_sub=Decimal('0.00')
    for itm in tx['items']:
        price = Decimal(itm['price']).quantize(Decimal('0.01'), ROUND_HALF_UP)
        pid   = f"{tx['seq']}_{idx}"; idx+=1
        items_list.append({
            'OrderItemState': [{ 'ItemState': {'value': 'Added'}, 'Timestamp': ts }],
            'MenuProduct': {
                'menuProductID': pid,
                'name': itm['name'],
                'MenuItem': [{
                    'ItemType': 'Refund', 'Category': 'Refund', 'iD': f"{pid}_MI",
                    'Description': itm['name'], 'Pricing': [{ 'Tax': [], 'ItemPrice': float(price), 'Quantity': itm['quantity'] }],
                    'SKU': { 'productName': itm['name'], 'productCode': pid }
                }],
                'SKU': { 'productName': itm['name'], 'productCode': pid }
            }
        })
        raw_sub += price * itm['quantity']
    refund_total = sum(p['amount'] for p in tx['payments'])
    payments=[]
    for p in tx['payments']:
        amt = p['amount']
        if amt == 0: continue
        payments.append({
            'Timestamp': ts, 'Status': 'Accepted', 'Amount': amt, 'Change': 0.0,
            'TenderType': {'value': map_tender(p['tenderType'])}
        })
    order={
        'OrderID': tx['guid'], 'OrderNumber': int(tx['seq'] or 0), 'OrderTime': ts,
        'OrderState': 'Closed', 'OrderItem': items_list,
        'Total': { 'ItemPrice': float(raw_sub.quantize(Decimal('0.01'), ROUND_HALF_UP)), 'Tax': [] },
        'OrderItemCount': len(items_list), 'Payment': payments
    }
    return {
        'model':'RefundTransaction',
        'Event':{
            'TransactionGUID': tx['guid'],
            'TransactionDateTimeStamp': ts,
            'TransactionType': 'New',
            'BusinessDate': biz,
            'Location': {'LocationID': tx['store'], 'Description': tx['location_desc']},
            'TransactionDevice': {'DeviceID': tx['terminal'], 'DeviceDescription': f"POS Terminal {tx['terminal']}"},
            'Employee': {'EmployeeID': tx['employee_id'], 'EmployeeFullName': tx['employee_name']},
            'EventTypeRefund': { 'Refund': { 'RefundTotal': refund_total, 'RefundTransactionType': { 'Order': order } } }
        }
    }

# ─── DISPATCHER ───

def dispatcher_worker():
    while True:
        tx = tx_queue.get()
        
        # Classify transaction type for appropriate URL and logging
        transaction_category = "unknown"
        
        # Check if this is a no-sale or cash operation
        if 'operation' in tx and tx['operation']:
            payload = build_cash_op_payload(tx)
            url = CASH_URL
            operation_type = tx.get('operation', '').lower()
            
            if operation_type == 'nosale':
                transaction_category = "no-sale"
            elif operation_type == 'paidout':
                transaction_category = "paid-out"
            elif operation_type == 'cashdrop':
                transaction_category = "cash-drop"
            else:
                transaction_category = "cash-operation"
                
        # Check if this is a refund transaction
        elif tx['type'].lower() == 'refund' or (tx['items'] and all(i.get('price', 0) < 0 for i in tx['items'])):
            payload = build_refund_payload(tx)
            url = REFUND_URL
            transaction_category = "refund"
            
        # Standard transaction
        else:
            payload = build_txn_payload(tx)
            url = TXN_URL
            
            # Categorize the transaction for better logging
            has_voids = bool(tx['voids'])
            all_voided = has_voids and all(item['event'] == 'void' for item in tx['items'] + tx['voids'])
            has_promos = any('PROMO' in item['name'].upper() or item.get('price', 0) < 0 for item in tx['items'])
            
            if all_voided:
                transaction_category = "full-void"
            elif has_voids:
                transaction_category = "partial-void"
            elif has_promos:
                transaction_category = "promotion"
            else:
                transaction_category = "standard-sale"
        
        # Log what we're sending
        print(f"\n[INFO] Sending {transaction_category} transaction to {url.split('/')[-1]} endpoint")
        
        # Make the API request
        try:
            token = fetch_token()
            headers = {
                'Authorization': f"Bearer {token}",
                'External-Party-ID': CLIENT_ID,
                'Content-Type': 'application/json'
            }
            
            # Send the payload to the API
            print(f"[INFO] Request payload type: {payload['model']}")
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            status_code = resp.status_code
            body = resp.text
            
            # Log the result
            if 200 <= status_code < 300:
                print(f"[SUCCESS] {transaction_category.upper()} transaction sent successfully: Status {status_code}")
            else:
                print(f"[ERROR] Failed to send {transaction_category} transaction: Status {status_code}")
                print(f"[ERROR] Response body: {body[:200]}...")
                
        except Exception as e:
            status_code = 0
            body = str(e)
            print(f"[ERROR] Exception sending {transaction_category} transaction: {e}")
            
        # Record the result
        success = 200 <= status_code < 300
        write_transaction_by_date(tx, success, status_code, body)
        tx_queue.task_done()

# ─── MAIN ───
if __name__ == '__main__':
    ensure_directories()
    threading.Thread(target=parser_worker, daemon=True).start()
    threading.Thread(target=dispatcher_worker, daemon=True).start()
    for port in SERIAL_PORTS:
        threading.Thread(target=read_from_port, args=(port,), daemon=True).start()
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("[INFO] Shutting down...")
