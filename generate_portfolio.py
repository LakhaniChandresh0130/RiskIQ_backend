"""Generate a sample portfolio CSV with 5000 assets for testing"""
import csv
import random

# Indian stock symbols by sector
sectors = {
    "Financials": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BAJFINANCE", "HDFC", "AUBANK", "IDFCFIRSTB"],
    "Technology": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS", "PERSISTENT", "TATAELXSI", "L&TINFRA"],
    "Energy": ["RELIANCE", "ONGC", "NTPC", "POWERGRID", "TATAPOWER", "ADANIPORTS", "COALINDIA", "GAIL", "BPCL", "IOC"],
    "Consumer": ["HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DMART", "DABUR", "COLPAL", "GODREJCP", "MARICO"],
    "Automotive": ["MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "ASHOKLEY", "BHARATFORG", "MOTHERSON", "ENDURANCE"],
    "Pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "AUROPHARMA", "LUPIN", "DIVISLAB", "TCS", "BIOCON", "GLENMARK", "CADILAHC"],
    "Industrial": ["LT", "ABB", "SIEMENS", "SCHNEIDER", "THERMAX", "BHEL", "AIAENG", "ALOKINDS", "JINDALSTEL", "TATASTEEL"],
    "Infrastructure": ["L&T", "DLF", "GODREJPROP", "BRIGADE", "PRESTIGE", "PHOENIXLTD", "OBEROIRLTY", "MAHINDRALIFE", "GODREJPROP", "INDHOTEL"],
    "Telecom": ["RELIANCE", "BHARTIARTL", "VODAFONE IDEA", "TATACOMM", "RILCOMM", "MTNL", "INDT", "TANLA", "SMARTLINK", "IDEA"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "NMDC", "COALINDIA", "NLCINDIA", "MOIL", "SAIL", "HINDZINC"]
}

# Generate 5000 assets
with open('portfolio_5000.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['symbol', 'exchange', 'quantity', 'price', 'currency', 'asset_class', 'sector', 'name'])

    for i in range(5000):
        sector = random.choice(list(sectors.keys()))
        symbol = random.choice(sectors[sector])
        exchange = random.choice(['NSE', 'BSE'])
        quantity = random.randint(10, 5000)
        price = round(random.uniform(50, 3000), 2)
        currency = 'INR'
        asset_class = 'Equity'
        name = f"{symbol} {sector}"

        writer.writerow([symbol, exchange, quantity, price, currency, asset_class, sector, name])

print("Generated portfolio_5000.csv with 5000 assets")
