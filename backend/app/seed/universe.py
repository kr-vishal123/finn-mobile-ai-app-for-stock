"""Demo universe. The engine is not limited to these names: any NSE symbol can be
added at runtime (see services.companies.ensure_company)."""

# (nse_symbol, name, sector, industry)
PORTFOLIO = [
    ("HDFCBANK", "HDFC Bank Ltd", "Financials", "Private Bank"),
    ("BAJFINANCE", "Bajaj Finance Ltd", "Financials", "Consumer Finance (NBFC)"),
    ("CHOLAFIN", "Cholamandalam Investment and Finance Company Ltd", "Financials", "Vehicle & Rural Finance (NBFC)"),
    ("INFY", "Infosys Ltd", "Technology", "IT Services"),
    ("KPITTECH", "KPIT Technologies Ltd", "Technology", "Automotive Software"),
    ("LT", "Larsen & Toubro Ltd", "Industrials", "Engineering & Construction"),
    ("POLYCAB", "Polycab India Ltd", "Industrials", "Cables & Wires"),
    ("DIXON", "Dixon Technologies (India) Ltd", "Industrials", "Electronics Manufacturing Services"),
    ("TATAPOWER", "Tata Power Company Ltd", "Utilities", "Power Generation & Distribution"),
    ("SUNPHARMA", "Sun Pharmaceutical Industries Ltd", "Healthcare", "Pharmaceuticals"),
    ("ITC", "ITC Ltd", "Consumer Staples", "FMCG & Tobacco"),
    ("MARUTI", "Maruti Suzuki India Ltd", "Consumer Discretionary", "Passenger Vehicles"),
    ("TITAN", "Titan Company Ltd", "Consumer Discretionary", "Jewellery & Watches"),
    ("ASTRAL", "Astral Ltd", "Materials", "Pipes & Adhesives"),
    ("DEEPAKNTR", "Deepak Nitrite Ltd", "Materials", "Specialty Chemicals"),
    ("PIIND", "PI Industries Ltd", "Materials", "Agrochemicals (CSM)"),
]

RESEARCH = [
    ("NAVINFLUOR", "Navin Fluorine International Ltd", "Materials", "Fluorochemicals"),
    ("AARTIIND", "Aarti Industries Ltd", "Materials", "Specialty Chemicals"),
    ("PERSISTENT", "Persistent Systems Ltd", "Technology", "IT Services"),
    ("TRENT", "Trent Ltd", "Consumer Discretionary", "Fashion Retail"),
    ("KAYNES", "Kaynes Technology India Ltd", "Industrials", "Electronics Manufacturing Services"),
]
