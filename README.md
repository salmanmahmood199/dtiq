# 360iQ Data API Integration

This repository contains integration code for the 360iQ Data API, specifically designed to process POS transaction data and send it to the appropriate endpoints.

## API Endpoints

### Authentication
- **URL**: `https://identity-qa.go360iq.com/connect/token`
- **Method**: POST
- **Credentials**: Uses OAuth2 client credentials flow with client ID and secret
- **Token Caching**: Tokens are cached locally and reused until they expire (3600s)

### Transaction Endpoints

1. **Standard Transactions**
   - **URL**: `https://data-api-uat.go360iq.com/v1/Transactions`
   - **Payload Type**: `Transaction`
   - **Used For**: Regular sales transactions with items and payments
   - **Required Fields**:
     - Transaction GUID
     - OrderNumber (must not be a default value)
     - Payment collection (must not be empty)
     - Employee information
     - Location information

2. **Cash Operations**
   - **URL**: `https://data-api-uat.go360iq.com/v1/CashOperations`
   - **Payload Type**: `CashOperation`
   - **Used For**: No-sale drawer events, paid-outs, cash drops
   - **Operation Types**:
     - `nosale`: Standard drawer opening
     - `paidout`: Cash paid out from drawer
     - `cashdrop`: Cash added to drawer

3. **Refunds**
   - **URL**: `https://data-api-uat.go360iq.com/v1/Refunds`
   - **Payload Type**: `RefundTransaction`
   - **Used For**: Refund transactions
   - **Detection**: Transactions with:
     - Negative item prices OR
     - `refund` in operation field OR
     - `refund` in transactionType

## Testing Environment

### Test Scripts
- **`nosale.py`**: Tests no-sale drawer events by generating test data and sending to CashOperations endpoint
- **`refund.py`**: Tests refund transactions by generating test data and sending to Refunds endpoint
- **`promo_test.py`**: Tests promotion handling
- **`void_test.py`**: Tests voided transactions

### Test Data
- Transaction logs are stored in `pos_transactions_COM3.log` and `pos_transactions_COM4.log`
- These files contain real POS transaction data in JSON format
- The main script can parse these logs to extract transaction data

### Testing Authentication
- All test scripts include token caching to minimize authentication calls
- Tokens are valid for 3600 seconds (1 hour)

### UAT Environment Constraints
- Store ID must be "1001" for UAT compliance
- Location description is set to "Windsor Mill 711"

## Main Script: 711usingtransactionsummary.py

### Transaction Processing Flow
1. **Data Collection**:
   - Listens for JSON payloads on serial ports COM3 and COM4
   - Parses received data into structured transaction objects

2. **Transaction Detection**:
   - Identifies transaction type based on:
     - Direct command (NoSale, PaidOut, CashDrop)
     - Item pricing (negative prices indicate refunds)
     - Metadata fields (operation, transactionType)

3. **Special Cases**:
   - **Cash Payments**: Two-phase processing captures change amount accurately
   - **Void Handling**: Distinguishes between complete voids and partial voids
   - **Promotions**: Auto-detects promotions and formats them properly

4. **Payload Construction**:
   - Dynamically builds payloads based on transaction type
   - Ensures required fields are always present
   - Handles validation requirements (e.g., non-empty Payment collection)

5. **Dispatching**:
   - Routes transactions to the correct API endpoint based on type:
     - Standard sales → Transactions endpoint
     - Cash operations → CashOperations endpoint
     - Refunds → Refunds endpoint

### Recent Improvements
- **Enhanced Cash Payment Handling**: Uses second transaction summary to get accurate change amount
- **Fallback Payment Generation**: Ensures payment collection is never empty (API validation requirement)
- **Improved OrderNumber Logic**: Ensures OrderNumber is never a default value
- **Transaction Type Detection**: Better detection of transaction types from various data sources
- **Refund Validation Fixes**: Correctly places model field and uses proper tender types

## Running the Code

1. **Environment Setup**:
   ```bash
   python -m venv dtiq_venv
   source dtiq_venv/bin/activate
   pip install requests
   ```

2. **Running Main Script**:
   ```bash
   python 711usingtransactionsummary.py
   ```

3. **Testing Individual API Features**:
   ```bash
   python nosale.py  # Test no-sale operations
   python refund.py  # Test refund transactions
   ```

## Troubleshooting

- **API Validation Errors**:
  - Check that Payment collection is not empty
  - Ensure OrderNumber is not zero or default
  - Verify tender types match expected values

- **Token Issues**:
  - Delete token cache if experiencing authentication problems
  - Check client credentials are correct

- **Data Format Issues**:
  - Verify timestamps are in UTC with proper formatting
  - Ensure monetary amounts are properly quantized to 2 decimal places
