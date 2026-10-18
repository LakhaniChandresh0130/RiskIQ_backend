"""Generate a diverse portfolio CSV with 5000 assets including stocks, bonds, commodities, and FX"""
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

# US stocks
us_stocks = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM", "V", "JNJ", "WMT", "PG", "DIS", "NFLX", "AMD"]

# Bonds
bonds = ["US Treasury 10Y", "US Treasury 5Y", "US Treasury 2Y", "India Govt Bond 10Y", "India Govt Bond 5Y", "Corporate Bond AAA", "Corporate Bond AA"]

# Commodities
commodities = ["GOLD", "SILVER", "CRUDE OIL", "NATURAL GAS", "COPPER", "ALUMINUM", "ZINC", "NICKEL"]

# FX pairs
fx_pairs = ["USDINR", "EURINR", "GBPINR", "JPYINR", "USDJPY", "EURUSD", "GBPUSD"]

# Generate 5000 assets with diverse asset classes
with open('portfolio_diverse_5000.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['symbol', 'exchange', 'quantity', 'price', 'currency', 'asset_class', 'sector', 'name'])

    for i in range(5000):
        # Distribution: 60% stocks, 15% bonds, 15% commodities, 10% FX
        rand = random.random()

        if rand < 0.50:  # 50% Indian stocks
            sector = random.choice(list(sectors.keys()))
            symbol = random.choice(sectors[sector])
            exchange = random.choice(['NSE', 'BSE'])
            quantity = random.randint(10, 5000)
            price = round(random.uniform(50, 3000), 2)
            currency = 'INR'
            asset_class = 'Equity'
            name = f"{symbol} {sector}"

        elif rand < 0.75:  # 25% US stocks
            symbol = random.choice(us_stocks)
            exchange = random.choice(['NASDAQ', 'NYSE'])
            quantity = random.randint(5, 500)
            price = round(random.uniform(50, 500), 2)
            currency = 'USD'
            asset_class = 'Equity'
            sector = 'Technology'
            name = f"{symbol} US {sector}"

        elif rand < 0.90:  # 15% Bonds
            symbol = random.choice(bonds)
            exchange = 'NSE'
            quantity = random.randint(50, 2000)
            price = round(random.uniform(90, 110), 2)
            currency = 'INR'
            asset_class = 'Bond'
            sector = 'Rates'
            name = symbol

        elif rand < 0.97:  # 7% Commodities
            symbol = random.choice(commodities)
            exchange = 'MCX'
            quantity = random.randint(10, 500)
            price = round(random.uniform(100, 5000), 2)
            currency = 'INR'
            asset_class = 'Commodity'
            sector = 'Metals' if symbol in ['GOLD', 'SILVER', 'COPPER', 'ALUMINUM', 'ZINC', 'NICKEL'] else 'Energy'
            name = symbol

        else:  # 3% FX
            symbol = random.choice(fx_pairs)
            exchange = 'NSE'
            quantity = random.randint(1000, 100000)
            price = round(random.uniform(70, 90), 2)
            currency = 'INR'
            asset_class = 'FX'
            sector = 'Currency'
            name = f"{symbol} Spot"

        writer.writerow([symbol, exchange, quantity, price, currency, asset_class, sector, name])

print("Generated portfolio_diverse_5000.csv with 5000 diverse assets")
