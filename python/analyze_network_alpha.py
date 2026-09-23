import os
import json
import re
import datetime
import logging
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NetworkAlpha")

# Load environment variables
load_dotenv()

# File Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, '../data')
ALL_COMPANIES_FILE = os.path.join(DATA_DIR, 'allCompanies.json')
COMPANY_DETAILS_FILE = os.path.join(DATA_DIR, 'companyDetailsByKodeEmiten.json')
FINANCIAL_RATIO_FILE = os.path.join(DATA_DIR, 'financial_ratio.json')
OUTPUT_FILE = os.path.join(DATA_DIR, 'network_alpha_data.json')

# Database configs
NEO4J_URI = os.getenv("NEO4J_URI", "neo4j://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = os.getenv("POSTGRES_PORT", "5432")
PG_DB = os.getenv("POSTGRES_DB", "postgres")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

# Define Blue Chip Stock codes (known high-market-cap, high-reputation Indonesian stocks)
BLUE_CHIPS = {
    "BBCA", "BBRI", "BMRI", "TLKM", "ASII", "BBNI", "UNVR", "KLBF", "ICBP", 
    "PGAS", "JSMR", "ADRO", "PTBA", "INDF", "GOTO", "AMRT", "SMGR", "UNTR", 
    "BRPT", "TPIA", "BYAN", "CPIN", "TCPI", "INKP", "ADMR"
}

def clean_name(name):
    """Clean Indonesian corporate names and titles for consistent deduplication."""
    if not name or not isinstance(name, str):
        return ""
    # Convert to uppercase
    n = name.strip().upper()
    # Remove punctuation except spaces
    n = re.sub(r'[^\w\s]', '', n)
    
    # Remove common corporate indicators if we want to isolate people
    # but keep them for shareholder networks. We clean titles first.
    titles = [
        r'\bDR\b', r'\bDRS\b', r'\bIR\b', r'\bPROF\b', r'\bKH\b', r'\bHJ\b', r'\bH\b',
        r'\bSH\b', r'\bMH\b', r'\bPHD\b', r'\bSE\b', r'\bMM\b', r'\bMSI\b', r'\bST\b',
        r'\bMT\b', r'\bBSC\b', r'\bMBA\b', r'\bMACC\b', r'\bAK\b', r'\bBBA\b', r'\bME\b'
    ]
    for title in titles:
        n = re.sub(title, '', n)
        
    # Collapse double spaces
    n = re.sub(r'\s+', ' ', n).strip()
    return n

def is_corporate_name(name):
    """Identifies if a shareholder or entity is a corporation/proxy rather than an individual."""
    if not name:
        return False
    name_upper = name.upper()
    keywords = [
        "PT", "LTD", "LIMITED", "INC", "TBK", "MASYARAKAT", "SAHAM", "PENGENDALI", 
        "REPUBLIK", "GOVERNMENT", "FUND", "TRUST", "NOMINEES", "BANK", "ASSET", 
        "MANAGEMENT", "SECURITIES", "CORP", "CORPORATION", "CO", "SOCIETE", 
        "INVESTMENT", "HOLDINGS", "CAPITAL", "PENSION", "TREASURY"
    ]
    return any(keyword in name_upper for keyword in keywords)

# ==========================================
# 1. LOAD FINANCIAL RATIOS
# ==========================================
def load_financial_ratios():
    """Load latest financial ratios from PostgreSQL or fallback to JSON."""
    ratios = {}
    db_success = False

    # Try PostgreSQL first
    try:
        from sqlalchemy import create_engine
        pg_url = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
        engine = create_engine(pg_url)
        # Check connection
        with engine.connect() as conn:
            query = """
            WITH latest_fs AS (
                SELECT code, MAX(fs_date) as latest_date
                FROM financial_ratios
                GROUP BY code
            )
            SELECT 
                sf.code, sf.stock_name, sf.sector, sf.sub_sector, sf.industry, sf.sub_industry,
                sf.fs_date, sf.assets, sf.liabilities, sf.equity, sf.sales, sf.ebt, 
                sf.profit_period, sf.profit_attr_owner, sf.eps, sf.book_value, 
                sf.per, sf.price_bv, sf.de_ratio, sf.roa, sf.roe, sf.npm
            FROM 
                financial_ratios sf
            JOIN 
                latest_fs lf ON sf.code = lf.code AND sf.fs_date = lf.latest_date
            """
            df = pd.read_sql(query, conn)
            # Convert to dictionary
            for _, row in df.iterrows():
                code = row['code']
                ratios[code] = {
                    'code': code,
                    'stock_name': row['stock_name'],
                    'sector': row['sector'],
                    'sub_sector': row['sub_sector'],
                    'industry': row['industry'],
                    'sub_industry': row['sub_industry'],
                    'fs_date': str(row['fs_date']) if row['fs_date'] else None,
                    'assets': float(row['assets']) if row['assets'] is not None else 0.0,
                    'liabilities': float(row['liabilities']) if row['liabilities'] is not None else 0.0,
                    'equity': float(row['equity']) if row['equity'] is not None else 0.0,
                    'sales': float(row['sales']) if row['sales'] is not None else 0.0,
                    'profit_period': float(row['profit_period']) if row['profit_period'] is not None else 0.0,
                    'eps': float(row['eps']) if row['eps'] is not None else 0.0,
                    'book_value': float(row['book_value']) if row['book_value'] is not None else 0.0,
                    'per': float(row['per']) if row['per'] is not None else 0.0,
                    'price_bv': float(row['price_bv']) if row['price_bv'] is not None else 0.0,
                    'de_ratio': float(row['de_ratio']) if row['de_ratio'] is not None else 0.0,
                    'roa': float(row['roa']) if row['roa'] is not None else 0.0,
                    'roe': float(row['roe']) if row['roe'] is not None else 0.0,
                    'npm': float(row['npm']) if row['npm'] is not None else 0.0
                }
            logger.info(f"Successfully loaded {len(ratios)} financial records from PostgreSQL.")
            db_success = True
    except Exception as e:
        logger.warning(f"Could not connect to PostgreSQL database ({e}). Falling back to JSON file.")

    # Fallback to JSON file
    if not db_success:
        if os.path.exists(FINANCIAL_RATIO_FILE):
            try:
                with open(FINANCIAL_RATIO_FILE, 'r') as f:
                    raw_data = json.load(f)
                
                # Group by code and take the latest record
                data_list = raw_data.get('data', [])
                sorted_data = sorted(data_list, key=lambda x: (x.get('code', ''), x.get('fsDate', '')), reverse=True)
                
                seen_codes = set()
                for item in sorted_data:
                    code = item.get('code')
                    if not code or code in seen_codes:
                        continue
                    seen_codes.add(code)
                    
                    ratios[code] = {
                        'code': code,
                        'stock_name': item.get('stockName'),
                        'sector': item.get('sector'),
                        'sub_sector': item.get('subSector'),
                        'industry': item.get('industry'),
                        'sub_industry': item.get('subIndustry'),
                        'fs_date': item.get('fsDate'),
                        'assets': float(item.get('assets', 0.0) or 0.0),
                        'liabilities': float(item.get('liabilities', 0.0) or 0.0),
                        'equity': float(item.get('equity', 0.0) or 0.0),
                        'sales': float(item.get('sales', 0.0) or 0.0),
                        'profit_period': float(item.get('profitPeriod', 0.0) or 0.0),
                        'eps': float(item.get('eps', 0.0) or 0.0),
                        'book_value': float(item.get('bookValue', 0.0) or 0.0),
                        'per': float(item.get('per', 0.0) or 0.0),
                        'price_bv': float(item.get('priceBV', 0.0) or 0.0),
                        'de_ratio': float(item.get('deRatio', 0.0) or 0.0),
                        'roa': float(item.get('roa', 0.0) or 0.0),
                        'roe': float(item.get('roe', 0.0) or 0.0),
                        'npm': float(item.get('npm', 0.0) or 0.0)
                    }
                logger.info(f"Successfully loaded {len(ratios)} financial records from local JSON file.")
            except Exception as e:
                logger.error(f"Error reading financial ratio JSON: {e}")
        else:
            logger.error(f"Financial ratio JSON not found at {FINANCIAL_RATIO_FILE}")

    return ratios

# ==========================================
# 2. LOAD COMPANY NETWORKS
# ==========================================
def load_company_networks():
    """Load boards and ownership networks from Neo4j or fallback to JSON."""
    company_details = {}
    db_success = False

    # Try Neo4j first
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        # Test connection
        driver.verify_connectivity()
        
        with driver.session() as session:
            # Query all company nodes
            company_query = "MATCH (c:Company) RETURN c.kode AS code, c.companyName AS companyName"
            result = session.run(company_query)
            for record in result:
                code = record['code']
                company_details[code] = {
                    'directors': [],
                    'commissioners': [],
                    'shareholders': [],
                    'subsidiaries': []
                }
                
            # Query Directors
            dir_query = """
            MATCH (i:Insider)-[r:DIRECTOR_OF]->(c:Company) 
            RETURN c.kode AS code, i.name AS name, r.jabatan AS jabatan, r.afiliasi AS afiliasi
            """
            result = session.run(dir_query)
            for record in result:
                code = record['code']
                if code in company_details:
                    company_details[code]['directors'].append({
                        'name': record['name'],
                        'jabatan': record['jabatan'],
                        'afiliasi': record['afiliasi']
                    })
                    
            # Query Commissioners
            comm_query = """
            MATCH (i:Insider)-[r:COMMISSIONER_OF]->(c:Company) 
            RETURN c.kode AS code, i.name AS name, r.jabatan AS jabatan, r.independen AS independen
            """
            result = session.run(comm_query)
            for record in result:
                code = record['code']
                if code in company_details:
                    company_details[code]['commissioners'].append({
                        'name': record['name'],
                        'jabatan': record['jabatan'],
                        'independen': record['independen']
                    })

            # Query Shareholders
            sh_query = """
            MATCH (i:Insider)-[r:OWNS]->(c:Company) 
            RETURN c.kode AS code, i.name AS name, r.jumlah AS jumlah, r.persentase AS persentase, r.pengendali AS pengendali, r.kategori AS kategori
            """
            result = session.run(sh_query)
            for record in result:
                code = record['code']
                if code in company_details:
                    company_details[code]['shareholders'].append({
                        'name': record['name'],
                        'jumlah': float(record['jumlah']) if record['jumlah'] is not None else 0.0,
                        'persentase': float(record['persentase']) if record['persentase'] is not None else 0.0,
                        'pengendali': bool(record['pengendali']) if record['pengendali'] is not None else False,
                        'kategori': record['kategori']
                    })
            
            # Query Subsidiaries
            sub_query = """
            MATCH (s:Subsidiary)-[r:SUBSIDIARY_OF]->(c:Company) 
            RETURN c.kode AS code, s.name AS name, r.persentase AS persentase, s.bidangUsaha AS bidangUsaha
            """
            result = session.run(sub_query)
            for record in result:
                code = record['code']
                if code in company_details:
                    company_details[code]['subsidiaries'].append({
                        'name': record['name'],
                        'persentase': float(record['persentase']) if record['persentase'] is not None else 0.0,
                        'bidang_usaha': record['bidangUsaha']
                    })
                    
        driver.close()
        logger.info(f"Successfully loaded {len(company_details)} company networks from Neo4j.")
        db_success = True
    except Exception as e:
        logger.warning(f"Could not connect to Neo4j database ({e}). Falling back to JSON file.")

    # Fallback to JSON file
    if not db_success:
        if os.path.exists(COMPANY_DETAILS_FILE):
            try:
                with open(COMPANY_DETAILS_FILE, 'r') as f:
                    raw_details = json.load(f)
                
                for code, item in raw_details.items():
                    # Parse directors
                    dirs = []
                    for d in item.get('Direktur', []):
                        dirs.append({
                            'name': d.get('Nama', ''),
                            'jabatan': d.get('Jabatan', 'DIREKTUR'),
                            'afiliasi': d.get('Afiliasi', False)
                        })
                        
                    # Parse commissioners
                    comms = []
                    for k in item.get('Komisaris', []):
                        comms.append({
                            'name': k.get('Nama', ''),
                            'jabatan': k.get('Jabatan', 'KOMISARIS'),
                            'independen': k.get('Independen', False)
                        })
                        
                    # Parse shareholders
                    shs = []
                    for s in item.get('PemegangSaham', []):
                        shs.append({
                            'name': s.get('Nama', ''),
                            'jumlah': float(s.get('Jumlah', 0.0) or 0.0),
                            'persentase': float(s.get('Persentase', 0.0) or 0.0),
                            'pengendali': s.get('Pengendali', False),
                            'kategori': s.get('Kategori', '')
                        })
                        
                    # Parse subsidiaries
                    subs = []
                    for sub in item.get('AnakPerusahaan', []):
                        subs.append({
                            'name': sub.get('Nama', ''),
                            'persentase': float(sub.get('Persentase', 0.0) or 0.0),
                            'bidang_usaha': sub.get('BidangUsaha', '')
                        })
                        
                    company_details[code] = {
                        'directors': dirs,
                        'commissioners': comms,
                        'shareholders': shs,
                        'subsidiaries': subs
                    }
                logger.info(f"Successfully loaded {len(company_details)} company networks from local JSON file.")
            except Exception as e:
                logger.error(f"Error reading company details JSON: {e}")
        else:
            logger.error(f"Company details JSON not found at {COMPANY_DETAILS_FILE}")

    return company_details


# ==========================================
# 3. TRADING RADAR ENGINE
# ==========================================
def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        x = float(value)
        return x if x == x else default
    except Exception:
        return default


def _clamp(value, low=0.0, high=100.0):
    return max(low, min(high, float(value)))


def build_trading_radar(data_dir, min_value_rp=1_000_000_000.0):
    """
    Historical daily trading engine.

    IMPORTANT:
    - Uses real historical stock_summary timeseries.
    - Does NOT fabricate 15:00-15:50 intraday data.
    - Foreign flow is stock-level aggregate, not broker attribution.
    - Absorption/distribution are daily signatures, not order-book claims.
    """
    try:
        import pandas as pd
        from idx.core.timeseries import read_dataset
    except Exception as exc:
        logger.warning(f"Trading radar dependencies unavailable: {exc}")
        return {}, {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "sessions": 0,
        }

    try:
        history = read_dataset(
            "stock_summary",
            base_dir=os.path.join(data_dir, "timeseries"),
        )
    except Exception as exc:
        logger.warning(f"Could not load stock historical timeseries: {exc}")
        return {}, {
            "status": "UNAVAILABLE",
            "reason": str(exc),
            "sessions": 0,
        }

    if history is None or history.empty:
        return {}, {
            "status": "UNAVAILABLE",
            "reason": "No stock historical timeseries available.",
            "sessions": 0,
        }

    required = [
        "Date", "StockCode", "OpenPrice", "High", "Low", "Close",
        "Volume", "Value", "ForeignBuy", "ForeignSell",
    ]
    missing = [c for c in required if c not in history.columns]
    if missing:
        return {}, {
            "status": "UNAVAILABLE",
            "reason": f"Missing columns: {missing}",
            "sessions": 0,
        }

    df = history.copy()

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["StockCode"] = df["StockCode"].astype(str).str.upper().str.strip()

    numeric_cols = [
        "OpenPrice", "High", "Low", "Close", "Volume", "Value",
        "ForeignBuy", "ForeignSell", "NonRegularVolume",
        "NonRegularValue", "Bid", "BidVolume", "Offer", "OfferVolume",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["Date", "StockCode"])
    df = df[df["Close"] > 0].sort_values(["StockCode", "Date"])

    if df.empty:
        return {}, {
            "status": "UNAVAILABLE",
            "reason": "Historical dataset contains no valid closing prices.",
            "sessions": 0,
        }

    # Remove duplicate stock/date records defensively.
    df = df.drop_duplicates(["StockCode", "Date"], keep="last")

    sessions = int(df["Date"].nunique())
    latest_date = df["Date"].max()

    radar = {}

    for code, g in df.groupby("StockCode", sort=False):
        g = g.sort_values("Date").copy()

        if len(g) < 5:
            continue

        close = g["Close"]
        high = g["High"]
        low = g["Low"]
        open_px = g["OpenPrice"].where(g["OpenPrice"] > 0, close)
        volume = g["Volume"].clip(lower=0)
        value = g["Value"].clip(lower=0)

        foreign_buy = g["ForeignBuy"].clip(lower=0)
        foreign_sell = g["ForeignSell"].clip(lower=0)
        foreign_net = foreign_buy - foreign_sell

        # Basic daily structure.
        ret = close.pct_change().fillna(0.0)

        prev_close = close.shift(1)
        tr_components = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        )
        true_range = tr_components.max(axis=1).fillna(0.0)

        atr14 = true_range.rolling(14, min_periods=5).mean()
        atr_pct = (atr14 / close.replace(0, pd.NA) * 100.0).fillna(0.0)

        sma5 = close.rolling(5, min_periods=3).mean()
        sma10 = close.rolling(10, min_periods=5).mean()
        sma20 = close.rolling(20, min_periods=5).mean()
        sma50 = close.rolling(50, min_periods=10).mean()

        vol5 = volume.rolling(5, min_periods=3).mean()
        vol20 = volume.rolling(20, min_periods=5).mean()
        value20 = value.rolling(20, min_periods=5).mean()

        rvol = (
            volume / vol20.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(0.0)

        volume_accel = (
            vol5 / vol20.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(0.0)

        high20 = high.rolling(20, min_periods=5).max()
        low20 = low.rolling(20, min_periods=5).min()

        # Daily VWAP proxy from OHLC. This is NOT intraday VWAP.
        typical_price = (high + low + close) / 3.0
        vwap20_num = (typical_price * volume).rolling(20, min_periods=5).sum()
        vwap20_den = volume.rolling(20, min_periods=5).sum()
        vwap20 = (
            vwap20_num / vwap20_den.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(close)

        # Price efficiency: directional movement / total movement.
        abs_daily_move = close.diff().abs()
        direction_5 = (close - close.shift(5)).abs()
        path_5 = abs_daily_move.rolling(5, min_periods=3).sum()
        efficiency5 = (
            direction_5 / path_5.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(0.0)

        direction10 = (close - close.shift(10)).abs()
        path10 = abs_daily_move.rolling(10, min_periods=5).sum()
        efficiency10 = (
            direction10 / path10.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(0.0)

        # Foreign persistence.
        fn5 = foreign_net.rolling(5, min_periods=3).sum()
        fn10 = foreign_net.rolling(10, min_periods=5).sum()
        fn20 = foreign_net.rolling(20, min_periods=5).sum()

        fb5 = foreign_buy.rolling(5, min_periods=3).sum()
        fs5 = foreign_sell.rolling(5, min_periods=3).sum()

        # Daily candle geometry.
        candle_range = (high - low).clip(lower=0)
        close_location = (
            (close - low) / candle_range.replace(0, pd.NA)
        ).replace([float("inf"), -float("inf")], pd.NA).fillna(0.5)

        upper_wick = high - pd.concat([open_px, close], axis=1).max(axis=1)
        lower_wick = pd.concat([open_px, close], axis=1).min(axis=1) - low

        # Latest row.
        row = g.iloc[-1]
        c = _safe_float(row["Close"])
        o = _safe_float(row["OpenPrice"], c)
        h = _safe_float(row["High"], c)
        l = _safe_float(row["Low"], c)
        v = _safe_float(row["Volume"])
        val = _safe_float(row["Value"])

        latest_ret = _safe_float(ret.iloc[-1]) * 100.0
        latest_rvol = _safe_float(rvol.iloc[-1])
        latest_accel = _safe_float(volume_accel.iloc[-1])
        latest_atr = _safe_float(atr_pct.iloc[-1])

        s20 = _safe_float(sma20.iloc[-1], c)
        s50 = _safe_float(sma50.iloc[-1], s20)
        vwap = _safe_float(vwap20.iloc[-1], c)

        h20 = _safe_float(high20.iloc[-1], c)
        l20 = _safe_float(low20.iloc[-1], c)

        eff5 = _safe_float(efficiency5.iloc[-1])
        eff10 = _safe_float(efficiency10.iloc[-1])

        fn1 = _safe_float(foreign_net.iloc[-1])
        fn5v = _safe_float(fn5.iloc[-1])
        fn10v = _safe_float(fn10.iloc[-1])
        fn20v = _safe_float(fn20.iloc[-1])

        fb5v = _safe_float(fb5.iloc[-1])
        fs5v = _safe_float(fs5.iloc[-1])

        cl = _safe_float(close_location.iloc[-1], 0.5)
        uw = _safe_float(upper_wick.iloc[-1])
        lw = _safe_float(lower_wick.iloc[-1])

        avg_value20 = _safe_float(value20.iloc[-1])
        price_vs_vwap = ((c / vwap) - 1.0) * 100.0 if vwap > 0 else 0.0
        price_vs_sma20 = ((c / s20) - 1.0) * 100.0 if s20 > 0 else 0.0
        price_vs_sma50 = ((c / s50) - 1.0) * 100.0 if s50 > 0 else 0.0

        support_distance = ((c / l20) - 1.0) * 100.0 if l20 > 0 else 0.0
        resistance_distance = ((h20 / c) - 1.0) * 100.0 if c > 0 else 0.0

        # Liquidity tiers.
        if avg_value20 >= 100_000_000_000:
            liquidity_score = 100.0
        elif avg_value20 >= 25_000_000_000:
            liquidity_score = 85.0
        elif avg_value20 >= 10_000_000_000:
            liquidity_score = 70.0
        elif avg_value20 >= 2_000_000_000:
            liquidity_score = 50.0
        elif avg_value20 >= min_value_rp:
            liquidity_score = 30.0
        else:
            liquidity_score = 0.0

        # Trend structure.
        uptrend = c > s20 and s20 >= s50 and s20 > _safe_float(sma20.iloc[max(0, len(sma20)-5)], s20)
        downtrend = c < s20 and s20 <= s50
        trend_score = 0.0
        if uptrend:
            trend_score = 100.0
        elif c > s20:
            trend_score = 65.0
        elif downtrend:
            trend_score = 30.0
        else:
            trend_score = 50.0

        # Support quality:
        # Close near 20D low, positive lower wick, and positive foreign flow
        # increase support/reversal quality.
        support_score = 0.0
        if support_distance <= 5.0:
            support_score += 40.0
        elif support_distance <= 8.0:
            support_score += 25.0
        elif support_distance <= 12.0:
            support_score += 10.0

        if cl >= 0.65:
            support_score += 20.0
        if lw > 0 and candle_range.iloc[-1] > 0:
            if (lw / candle_range.iloc[-1]) >= 0.25:
                support_score += 20.0
        if fn5v > 0:
            support_score += 20.0

        support_score = _clamp(support_score)

        # Breakout proximity without chasing.
        breakout_score = 0.0
        if resistance_distance <= 2.0 and latest_rvol >= 1.2:
            breakout_score = 100.0
        elif resistance_distance <= 5.0 and latest_rvol >= 1.0:
            breakout_score = 75.0
        elif resistance_distance <= 8.0:
            breakout_score = 50.0
        else:
            breakout_score = 25.0

        # Absorption-like daily signature:
        # high relative volume + small price displacement + close toward high
        # + positive/neutral foreign flow + support/VWAP retention.
        absorption = 0.0
        if latest_rvol >= 1.5:
            absorption += 30.0
        elif latest_rvol >= 1.2:
            absorption += 20.0

        if abs(latest_ret) <= 1.5:
            absorption += 20.0
        elif abs(latest_ret) <= 2.5:
            absorption += 10.0

        if cl >= 0.65:
            absorption += 20.0
        if price_vs_vwap >= -1.0:
            absorption += 10.0
        if fn5v >= 0:
            absorption += 10.0
        if support_distance <= 8.0:
            absorption += 10.0

        absorption = _clamp(absorption)

        # Distribution signature:
        # high volume + negative return + close near low + large upper wick.
        distribution = 0.0
        if latest_rvol >= 1.5:
            distribution += 25.0
        elif latest_rvol >= 1.2:
            distribution += 15.0

        if latest_ret <= -1.5:
            distribution += 25.0
        elif latest_ret < 0:
            distribution += 10.0

        if cl <= 0.35:
            distribution += 25.0

        if candle_range.iloc[-1] > 0 and uw / candle_range.iloc[-1] >= 0.25:
            distribution += 15.0

        if fn5v < 0:
            distribution += 10.0

        distribution = _clamp(distribution)

        # Pump/FOMO / extension risk.
        extension_risk = 0.0
        if price_vs_sma20 >= 10.0:
            extension_risk += 35.0
        elif price_vs_sma20 >= 6.0:
            extension_risk += 20.0
        elif price_vs_sma20 >= 3.0:
            extension_risk += 10.0

        if price_vs_vwap >= 8.0:
            extension_risk += 30.0
        elif price_vs_vwap >= 5.0:
            extension_risk += 18.0

        if resistance_distance <= 0.5:
            extension_risk += 20.0

        if latest_ret >= 7.0:
            extension_risk += 20.0
        elif latest_ret >= 4.0:
            extension_risk += 10.0

        extension_risk = _clamp(extension_risk)

        fomo_risk = _clamp(
            (20.0 if latest_ret >= 5.0 else 0.0)
            + (25.0 if latest_rvol >= 3.0 else 0.0)
            + (25.0 if price_vs_sma20 >= 10.0 else 0.0)
            + (15.0 if cl >= 0.9 and latest_ret > 3.0 else 0.0)
            + (15.0 if resistance_distance <= 1.0 and latest_ret > 2.0 else 0.0)
        )

        # Foreign accumulation quality.
        foreign_score = 50.0
        if fn5v > 0:
            foreign_score += 20.0
        elif fn5v < 0:
            foreign_score -= 20.0

        if fn10v > 0:
            foreign_score += 15.0
        elif fn10v < 0:
            foreign_score -= 15.0

        if fb5v > fs5v:
            foreign_score += 15.0

        foreign_score = _clamp(foreign_score)

        # Momentum quality.
        momentum_score = 0.0
        if uptrend:
            momentum_score += 35.0
        elif c > s20:
            momentum_score += 20.0

        if latest_rvol >= 1.5:
            momentum_score += 25.0
        elif latest_rvol >= 1.1:
            momentum_score += 15.0

        if 0.25 <= eff5 <= 1.0:
            momentum_score += 20.0

        if latest_ret > 0:
            momentum_score += 20.0

        momentum_score = _clamp(momentum_score)

        # Fair-entry quality.
        fair_entry = 100.0
        if abs(price_vs_vwap) > 3:
            fair_entry -= min(30.0, abs(price_vs_vwap) * 3.0)
        if price_vs_sma20 > 5:
            fair_entry -= min(30.0, (price_vs_sma20 - 5.0) * 4.0)
        if resistance_distance < 2:
            fair_entry -= 20.0
        if support_distance <= 5:
            fair_entry += 10.0

        fair_entry = _clamp(fair_entry)

        # Volatility quality: avoid dead sideways names, but don't blindly reward extremes.
        volatility_score = 50.0
        if 1.5 <= latest_atr <= 6.0:
            volatility_score = 100.0
        elif 0.8 <= latest_atr < 1.5:
            volatility_score = 65.0
        elif 6.0 < latest_atr <= 10.0:
            volatility_score = 70.0
        elif latest_atr < 0.8:
            volatility_score = 30.0
        else:
            volatility_score = 35.0

        # Price-volume efficiency.
        efficiency_score = _clamp(
            (eff5 * 70.0) + (eff10 * 30.0)
        )

        # Distribution penalty is intentionally separate from absorption:
        # high volume + flat price is NOT automatically rejected.
        distribution_penalty = distribution * 0.35
        fomo_penalty = fomo_risk * 0.30
        extension_penalty = extension_risk * 0.25

        # ⚡ NEXT-DAY
        next_day = (
            absorption * 0.15
            + foreign_score * 0.15
            + momentum_score * 0.10
            + efficiency_score * 0.08
            + min(latest_rvol / 2.0, 1.0) * 100.0 * 0.10
            + support_score * 0.08
            + fair_entry * 0.06
            + volatility_score * 0.06
            + liquidity_score * 0.05
            + breakout_score * 0.07
        )
        next_day -= distribution_penalty + fomo_penalty + extension_penalty
        next_day = _clamp(next_day)

        # 🔄 SWING
        swing = (
            trend_score * 0.15
            + support_score * 0.20
            + foreign_score * 0.15
            + absorption * 0.12
            + momentum_score * 0.10
            + fair_entry * 0.10
            + volatility_score * 0.08
            + liquidity_score * 0.05
            + breakout_score * 0.05
        )
        swing -= distribution_penalty * 0.8 + extension_penalty * 0.6
        swing = _clamp(swing)

        # 🪃 REVERSAL
        reversal = (
            support_score * 0.25
            + absorption * 0.20
            + foreign_score * 0.15
            + efficiency_score * 0.10
            + fair_entry * 0.10
            + volatility_score * 0.08
            + liquidity_score * 0.05
            + (100.0 - trend_score) * 0.07
        )
        reversal -= distribution_penalty + fomo_penalty * 0.5
        reversal = _clamp(reversal)

        # Setup classification.
        setups = []

        if next_day >= 65:
            if breakout_score >= 75 and momentum_score >= 55:
                setups.append("MOMENTUM")
            if absorption >= 55:
                setups.append("ABSORPTION")

        if swing >= 60:
            if uptrend and support_score >= 45:
                setups.append("PULLBACK")
            elif not uptrend and support_score >= 55:
                setups.append("REVERSAL")

        if reversal >= 65 and support_score >= 55:
            if "REVERSAL" not in setups:
                setups.append("REVERSAL")

        if foreign_score >= 70 and fn5v > 0:
            setups.append("FOREIGN_ACCUMULATION")

        if not setups:
            setups.append("WATCH")

        # Human-readable reasons.
        reasons = []

        if absorption >= 60:
            reasons.append("high volume with relatively contained price movement / absorption-like")
        if foreign_score >= 70:
            reasons.append("positive foreign flow over recent sessions")
        elif foreign_score <= 30:
            reasons.append("foreign selling pressure")
        if support_score >= 65:
            reasons.append("near/supporting recent low structure")
        if breakout_score >= 75:
            reasons.append("near breakout zone with volume confirmation")
        if momentum_score >= 65:
            reasons.append("positive momentum/trend structure")
        if distribution >= 60:
            reasons.append("distribution-like daily signature")
        if fomo_risk >= 55:
            reasons.append("FOMO/extension risk elevated")
        if liquidity_score < 50:
            reasons.append("liquidity below preferred tier")

        radar[code] = {
            "date": str(row["Date"]),
            "next_day_score": round(next_day, 2),
            "swing_score": round(swing, 2),
            "reversal_score": round(reversal, 2),
            "setups": setups,
            "reasons": reasons[:6],

            "rvol": round(latest_rvol, 3),
            "volume_acceleration": round(latest_accel, 3),
            "atr_pct": round(latest_atr, 3),
            "price_efficiency_5d": round(eff5, 3),
            "price_efficiency_10d": round(eff10, 3),

            "foreign_net_1d": round(fn1, 2),
            "foreign_net_5d": round(fn5v, 2),
            "foreign_net_10d": round(fn10v, 2),
            "foreign_net_20d": round(fn20v, 2),
            "foreign_buy_5d": round(fb5v, 2),
            "foreign_sell_5d": round(fs5v, 2),
            "foreign_score": round(foreign_score, 2),

            "absorption_score": round(absorption, 2),
            "distribution_score": round(distribution, 2),
            "support_score": round(support_score, 2),
            "breakout_score": round(breakout_score, 2),
            "trend_score": round(trend_score, 2),
            "momentum_score": round(momentum_score, 2),

            "price_vs_vwap_pct": round(price_vs_vwap, 3),
            "price_vs_sma20_pct": round(price_vs_sma20, 3),
            "price_vs_sma50_pct": round(price_vs_sma50, 3),
            "support_distance_pct": round(support_distance, 3),
            "resistance_distance_pct": round(resistance_distance, 3),

            "fair_entry_score": round(fair_entry, 2),
            "volatility_score": round(volatility_score, 2),
            "liquidity_score": round(liquidity_score, 2),
            "avg_value_20": round(avg_value20, 2),

            "pump_risk": round(extension_risk, 2),
            "fomo_risk": round(fomo_risk, 2),

            "close_location": round(cl, 3),
            "daily_return_pct": round(latest_ret, 3),
            "close": round(c, 4),
            "volume": round(v, 2),
            "value": round(val, 2),

            # Explicitly distinguish daily proxy from true intraday EOD pressure.
            "eod_pressure": "UNAVAILABLE_INTRADAY",
            "absorption_type": (
                "ABSORPTION_LIKE"
                if absorption >= 60 and distribution < 55
                else "DISTRIBUTION_LIKE"
                if distribution >= 60
                else "NEUTRAL"
            ),
        }

    # Build ranked lists.
    eligible = [
        (code, item)
        for code, item in radar.items()
        if item["liquidity_score"] > 0
    ]

    def ranked(key, limit=50):
        rows = sorted(
            eligible,
            key=lambda x: x[1].get(key, 0.0),
            reverse=True,
        )[:limit]

        out = []
        for rank, (code, item) in enumerate(rows, start=1):
            out.append({
                "rank": rank,
                "code": code,
                "score": item.get(key, 0.0),
                "setups": item.get("setups", []),
                "reasons": item.get("reasons", []),
            })
        return out

    ranking = {
        "next_day": ranked("next_day_score"),
        "swing": ranked("swing_score"),
        "reversal": ranked("reversal_score"),
        "absorption": sorted(
            [
                {
                    "rank": rank,
                    "code": code,
                    "score": item["absorption_score"],
                    "setups": item["setups"],
                    "reasons": item["reasons"],
                }
                for rank, (code, item) in enumerate(
                    sorted(
                        eligible,
                        key=lambda x: x[1]["absorption_score"],
                        reverse=True,
                    )[:50],
                    start=1,
                )
            ],
            key=lambda x: x["rank"],
        ),
    }

    meta = {
        "status": "OK",
        "sessions": sessions,
        "first_date": str(df["Date"].min()),
        "last_date": str(latest_date),
        "stocks": int(df["StockCode"].nunique()),
        "data_frequency": "DAILY",
        "intraday_eod_pressure_available": False,
        "broker_stock_attribution_available": False,
        "foreign_flow_level": "STOCK_AGGREGATE",
        "absorption_level": "DAILY_SIGNATURE",
    }

    return radar, {
        "meta": meta,
        "rankings": ranking,
    }



# ==========================================
# 3.5 WALK-FORWARD TRADING BACKTEST
# ==========================================
def backtest_trading_radar(data_dir, min_value_rp=1_000_000_000.0):
    """
    Walk-forward validation of the trading hypotheses.

    For each stock/date T:
      - features use observations <= T only
      - outcome uses T+1 only

    This is deliberately independent from the current dashboard ranking.
    """

    try:
        import pandas as pd
        import numpy as np
        from idx.core.timeseries import read_dataset
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc),
        }

    try:
        df = read_dataset(
            "stock_summary",
            base_dir=os.path.join(data_dir, "timeseries"),
        ).copy()
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "reason": str(exc),
        }

    if df.empty:
        return {
            "status": "UNAVAILABLE",
            "reason": "No historical stock data.",
        }

    required = [
        "Date", "StockCode", "OpenPrice", "High", "Low", "Close",
        "Volume", "Value", "ForeignBuy", "ForeignSell",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return {
            "status": "UNAVAILABLE",
            "reason": f"Missing columns: {missing}",
        }

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["StockCode"] = df["StockCode"].astype(str).str.upper().str.strip()

    nums = [
        "OpenPrice", "High", "Low", "Close", "Volume", "Value",
        "ForeignBuy", "ForeignSell",
    ]
    for col in nums:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df = (
        df.dropna(subset=["Date", "StockCode"])
          .sort_values(["StockCode", "Date"])
          .drop_duplicates(["StockCode", "Date"], keep="last")
    )

    # Forward outcomes.
    g = df.groupby("StockCode", group_keys=False)

    df["T1_Open"] = g["OpenPrice"].shift(-1)
    df["T1_High"] = g["High"].shift(-1)
    df["T1_Low"] = g["Low"].shift(-1)
    df["T1_Close"] = g["Close"].shift(-1)

    df["T1_Open_Ret"] = (
        (df["T1_Open"] / df["Close"]) - 1.0
    ) * 100.0

    df["T1_Close_Ret"] = (
        (df["T1_Close"] / df["Close"]) - 1.0
    ) * 100.0

    df["T1_High_Ret"] = (
        (df["T1_High"] / df["Close"]) - 1.0
    ) * 100.0

    df["T1_Low_Ret"] = (
        (df["T1_Low"] / df["Close"]) - 1.0
    ) * 100.0

    df = df.dropna(subset=["T1_Open", "T1_High", "T1_Low", "T1_Close"])

    results = []

    # We deliberately recompute features chronologically per stock.
    for code, x in df.groupby("StockCode", sort=False):
        x = x.sort_values("Date").copy()

        if len(x) < 30:
            continue

        close = x["Close"]
        high = x["High"]
        low = x["Low"]
        volume = x["Volume"]
        value = x["Value"]

        foreign_net = x["ForeignBuy"] - x["ForeignSell"]

        prev = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev).abs(),
                (low - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr14 = tr.rolling(14, min_periods=10).mean()
        atr_pct = atr14 / close.replace(0, np.nan) * 100.0

        sma20 = close.rolling(20, min_periods=15).mean()
        sma50 = close.rolling(50, min_periods=30).mean()

        vol20 = volume.rolling(20, min_periods=15).mean()
        value20 = value.rolling(20, min_periods=15).mean()

        rvol = volume / vol20.replace(0, np.nan)

        fn5 = foreign_net.rolling(5, min_periods=3).sum()
        fn10 = foreign_net.rolling(10, min_periods=5).sum()

        high20 = high.rolling(20, min_periods=15).max()
        low20 = low.rolling(20, min_periods=15).min()

        candle_range = (high - low).clip(lower=0)
        close_location = (
            (close - low) / candle_range.replace(0, np.nan)
        ).fillna(0.5)

        upper_wick = high - pd.concat(
            [x["OpenPrice"], close], axis=1
        ).max(axis=1)

        lower_wick = pd.concat(
            [x["OpenPrice"], close], axis=1
        ).min(axis=1) - low

        daily_ret = close.pct_change() * 100.0

        abs_move = close.diff().abs()
        direction5 = (close - close.shift(5)).abs()
        path5 = abs_move.rolling(5, min_periods=3).sum()
        efficiency5 = (
            direction5 / path5.replace(0, np.nan)
        ).fillna(0.0)

        for i in range(30, len(x) - 1):
            c = float(close.iloc[i])
            if c <= 0:
                continue

            avg_val = float(value20.iloc[i]) if pd.notna(value20.iloc[i]) else 0.0
            if avg_val < min_value_rp:
                continue

            rv = float(rvol.iloc[i]) if pd.notna(rvol.iloc[i]) else 0.0
            atr = float(atr_pct.iloc[i]) if pd.notna(atr_pct.iloc[i]) else 0.0

            s20 = float(sma20.iloc[i]) if pd.notna(sma20.iloc[i]) else c
            s50 = float(sma50.iloc[i]) if pd.notna(sma50.iloc[i]) else s20

            fn5v = float(fn5.iloc[i]) if pd.notna(fn5.iloc[i]) else 0.0
            fn10v = float(fn10.iloc[i]) if pd.notna(fn10.iloc[i]) else 0.0

            h20 = float(high20.iloc[i]) if pd.notna(high20.iloc[i]) else c
            l20 = float(low20.iloc[i]) if pd.notna(low20.iloc[i]) else c

            cl = float(close_location.iloc[i])
            rng = float(candle_range.iloc[i])
            uw = float(upper_wick.iloc[i])
            lw = float(lower_wick.iloc[i])

            ret1 = float(daily_ret.iloc[i]) if pd.notna(daily_ret.iloc[i]) else 0.0
            eff = float(efficiency5.iloc[i])

            price_vs_sma20 = ((c / s20) - 1.0) * 100.0 if s20 else 0.0
            price_vs_sma50 = ((c / s50) - 1.0) * 100.0 if s50 else 0.0

            support_distance = ((c / l20) - 1.0) * 100.0 if l20 else 999.0
            resistance_distance = ((h20 / c) - 1.0) * 100.0 if c else 999.0

            uptrend = c > s20 and s20 >= s50
            downtrend = c < s20 and s20 <= s50

            # Daily absorption signature.
            absorption = 0.0

            if rv >= 1.5:
                absorption += 30
            elif rv >= 1.2:
                absorption += 20

            if abs(ret1) <= 1.5:
                absorption += 20
            elif abs(ret1) <= 2.5:
                absorption += 10

            if cl >= 0.65:
                absorption += 20

            if fn5v >= 0:
                absorption += 10

            if support_distance <= 8:
                absorption += 10

            if rng > 0 and lw / rng >= 0.25:
                absorption += 10

            absorption = min(100.0, absorption)

            # Distribution.
            distribution = 0.0

            if rv >= 1.5:
                distribution += 25
            elif rv >= 1.2:
                distribution += 15

            if ret1 <= -1.5:
                distribution += 25
            elif ret1 < 0:
                distribution += 10

            if cl <= 0.35:
                distribution += 25

            if rng > 0 and uw / rng >= 0.25:
                distribution += 15

            if fn5v < 0:
                distribution += 10

            distribution = min(100.0, distribution)

            # Foreign accumulation.
            foreign_acc = (
                fn5v > 0 and
                fn10v > 0
            )

            # Momentum.
            momentum = (
                uptrend and
                rv >= 1.1 and
                ret1 > 0 and
                eff >= 0.25
            )

            # Pullback.
            pullback = (
                uptrend and
                support_distance <= 8.0 and
                ret1 <= 1.5 and
                rv >= 0.8
            )

            # Reversal:
            # weak/downtrend + support + rejection/absorption.
            reversal = (
                (downtrend or c <= s20)
                and support_distance <= 8.0
                and (
                    absorption >= 50
                    or (cl >= 0.65 and lw > 0)
                    or foreign_acc
                )
                and distribution < 70
            )

            setups = []

            if momentum:
                setups.append("MOMENTUM")

            if pullback:
                setups.append("PULLBACK")

            if reversal:
                setups.append("REVERSAL")

            if absorption >= 50 and distribution < 60:
                setups.append("ABSORPTION")

            if foreign_acc:
                setups.append("FOREIGN_ACCUMULATION")

            if not setups:
                continue

            t1_high = float(x["T1_High"].iloc[i])
            t1_low = float(x["T1_Low"].iloc[i])
            t1_close = float(x["T1_Close"].iloc[i])
            t1_open = float(x["T1_Open"].iloc[i])

            base = c

            results.append({
                "date": str(x["Date"].iloc[i]),
                "code": code,
                "setups": setups,

                "score_absorption": absorption,
                "score_distribution": distribution,
                "rvol": rv,
                "atr_pct": atr,
                "foreign_net_5d": fn5v,
                "foreign_net_10d": fn10v,
                "support_distance_pct": support_distance,
                "resistance_distance_pct": resistance_distance,

                "t1_open_ret": ((t1_open / base) - 1) * 100,
                "t1_close_ret": ((t1_close / base) - 1) * 100,
                "t1_high_ret": ((t1_high / base) - 1) * 100,
                "t1_low_ret": ((t1_low / base) - 1) * 100,

                "hit_2": t1_high >= base * 1.02,
                "hit_3": t1_high >= base * 1.03,
                "hit_4": t1_high >= base * 1.04,
                "hit_5": t1_high >= base * 1.05,
            })

    if not results:
        return {
            "status": "OK",
            "samples": 0,
            "message": "No qualifying historical signals.",
        }

    r = pd.DataFrame(results)

    def summarize(name=None):
        if name is None:
            q = r
        else:
            q = r[r["setups"].apply(lambda xs: name in xs)]

        if q.empty:
            return {
                "samples": 0,
            }

        return {
            "samples": int(len(q)),
            "avg_t1_open_pct": round(float(q["t1_open_ret"].mean()), 3),
            "median_t1_open_pct": round(float(q["t1_open_ret"].median()), 3),
            "avg_t1_close_pct": round(float(q["t1_close_ret"].mean()), 3),
            "median_t1_close_pct": round(float(q["t1_close_ret"].median()), 3),
            "avg_t1_high_pct": round(float(q["t1_high_ret"].mean()), 3),
            "median_t1_high_pct": round(float(q["t1_high_ret"].median()), 3),
            "avg_t1_low_pct": round(float(q["t1_low_ret"].mean()), 3),
            "hit_2_pct": round(float(q["hit_2"].mean() * 100), 2),
            "hit_3_pct": round(float(q["hit_3"].mean() * 100), 2),
            "hit_4_pct": round(float(q["hit_4"].mean() * 100), 2),
            "hit_5_pct": round(float(q["hit_5"].mean() * 100), 2),
        }

    setup_summary = {
        name: summarize(name)
        for name in [
            "ABSORPTION",
            "MOMENTUM",
            "PULLBACK",
            "REVERSAL",
            "FOREIGN_ACCUMULATION",
        ]
    }

    # Threshold analysis for absorption and foreign accumulation.
    threshold_summary = {}

    for threshold in [1.0, 1.2, 1.5, 2.0]:
        q = r[
            (r["rvol"] >= threshold)
            & (r["score_absorption"] >= 50)
            & (r["score_distribution"] < 60)
        ]

        if not q.empty:
            threshold_summary[f"rvol_{threshold}"] = {
                "samples": int(len(q)),
                "avg_t1_close_pct": round(float(q["t1_close_ret"].mean()), 3),
                "median_t1_close_pct": round(float(q["t1_close_ret"].median()), 3),
                "hit_3_pct": round(float(q["hit_3"].mean() * 100), 2),
                "hit_5_pct": round(float(q["hit_5"].mean() * 100), 2),
            }

    return {
        "status": "OK",
        "samples": int(len(r)),
        "first_signal_date": str(r["date"].min()),
        "last_signal_date": str(r["date"].max()),
        "setup_summary": setup_summary,
        "threshold_summary": threshold_summary,
    }


# ==========================================
# 3.6 WALK-FORWARD TRADE BACKTEST V2
# ==========================================
def backtest_trading_radar_v2(data_dir, min_value_rp=1_000_000_000.0):
    """
    Clean trade-oriented walk-forward validation.

    Entry:
        T close

    Next session:
        - gap/open return
        - MFE = T close -> T+1 high
        - MAE = T close -> T+1 low
        - close-to-close return

    Invalid zero/non-positive prices are excluded.
    """

    import pandas as pd
    import numpy as np

    try:
        from idx.core.timeseries import read_dataset
        df = read_dataset(
            "stock_summary",
            base_dir=os.path.join(data_dir, "timeseries"),
        ).copy()
    except Exception as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}

    if df.empty:
        return {"status": "UNAVAILABLE", "reason": "No data"}

    required = [
        "Date", "StockCode", "OpenPrice", "High", "Low", "Close",
        "Volume", "Value", "ForeignBuy", "ForeignSell",
    ]

    missing = [c for c in required if c not in df.columns]
    if missing:
        return {
            "status": "UNAVAILABLE",
            "reason": f"Missing columns: {missing}",
        }

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["StockCode"] = (
        df["StockCode"].astype(str).str.upper().str.strip()
    )

    numeric_cols = [
        "OpenPrice", "High", "Low", "Close",
        "Volume", "Value", "ForeignBuy", "ForeignSell",
    ]

    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = (
        df.dropna(subset=["Date", "StockCode"])
          .sort_values(["StockCode", "Date"])
          .drop_duplicates(["StockCode", "Date"], keep="last")
    )

    g = df.groupby("StockCode", group_keys=False)

    df["T1_Open"] = g["OpenPrice"].shift(-1)
    df["T1_High"] = g["High"].shift(-1)
    df["T1_Low"] = g["Low"].shift(-1)
    df["T1_Close"] = g["Close"].shift(-1)

    # Valid price requirement.
    valid_t = (
        df["Close"] > 0
        & df["T1_Open"].gt(0)
        & df["T1_High"].gt(0)
        & df["T1_Low"].gt(0)
        & df["T1_Close"].gt(0)
    )

    df = df[valid_t].copy()

    results = []

    for code, x in df.groupby("StockCode", sort=False):
        x = x.sort_values("Date").copy()

        if len(x) < 35:
            continue

        close = x["Close"]
        high = x["High"]
        low = x["Low"]
        volume = x["Volume"].fillna(0)
        value = x["Value"].fillna(0)

        foreign_net = (
            x["ForeignBuy"].fillna(0)
            - x["ForeignSell"].fillna(0)
        )

        prev = close.shift(1)

        tr = pd.concat(
            [
                high - low,
                (high - prev).abs(),
                (low - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr14 = tr.rolling(14, min_periods=10).mean()
        atr_pct = atr14 / close.replace(0, np.nan) * 100

        sma20 = close.rolling(20, min_periods=15).mean()
        sma50 = close.rolling(50, min_periods=30).mean()

        vol20 = volume.rolling(20, min_periods=15).mean()
        value20 = value.rolling(20, min_periods=15).mean()

        rvol = volume / vol20.replace(0, np.nan)

        fn5 = foreign_net.rolling(5, min_periods=3).sum()
        fn10 = foreign_net.rolling(10, min_periods=5).sum()

        high20 = high.rolling(20, min_periods=15).max()
        low20 = low.rolling(20, min_periods=15).min()

        daily_ret = close.pct_change() * 100

        candle_range = (high - low).clip(lower=0)

        close_location = (
            (close - low)
            / candle_range.replace(0, np.nan)
        ).fillna(0.5)

        upper_wick = (
            high
            - pd.concat(
                [x["OpenPrice"], close],
                axis=1,
            ).max(axis=1)
        )

        lower_wick = (
            pd.concat(
                [x["OpenPrice"], close],
                axis=1,
            ).min(axis=1)
            - low
        )

        for i in range(30, len(x) - 1):
            c = float(close.iloc[i])

            if c <= 0:
                continue

            avg_value = value20.iloc[i]

            if pd.isna(avg_value) or avg_value < min_value_rp:
                continue

            rv = (
                float(rvol.iloc[i])
                if pd.notna(rvol.iloc[i])
                else 0.0
            )

            fn5v = (
                float(fn5.iloc[i])
                if pd.notna(fn5.iloc[i])
                else 0.0
            )

            fn10v = (
                float(fn10.iloc[i])
                if pd.notna(fn10.iloc[i])
                else 0.0
            )

            s20 = (
                float(sma20.iloc[i])
                if pd.notna(sma20.iloc[i])
                else c
            )

            s50 = (
                float(sma50.iloc[i])
                if pd.notna(sma50.iloc[i])
                else s20
            )

            h20 = (
                float(high20.iloc[i])
                if pd.notna(high20.iloc[i])
                else c
            )

            l20 = (
                float(low20.iloc[i])
                if pd.notna(low20.iloc[i])
                else c
            )

            ret1 = (
                float(daily_ret.iloc[i])
                if pd.notna(daily_ret.iloc[i])
                else 0.0
            )

            cl = float(close_location.iloc[i])

            rng = (
                float(candle_range.iloc[i])
                if pd.notna(candle_range.iloc[i])
                else 0.0
            )

            uw = (
                float(upper_wick.iloc[i])
                if pd.notna(upper_wick.iloc[i])
                else 0.0
            )

            lw = (
                float(lower_wick.iloc[i])
                if pd.notna(lower_wick.iloc[i])
                else 0.0
            )

            support_distance = (
                ((c / l20) - 1) * 100
                if l20 > 0
                else 999
            )

            uptrend = c > s20 and s20 >= s50
            downtrend = c < s20 and s20 <= s50

            absorption = 0

            if rv >= 1.5:
                absorption += 30
            elif rv >= 1.2:
                absorption += 20

            if abs(ret1) <= 1.5:
                absorption += 20
            elif abs(ret1) <= 2.5:
                absorption += 10

            if cl >= 0.65:
                absorption += 20

            if fn5v >= 0:
                absorption += 10

            if support_distance <= 8:
                absorption += 10

            if rng > 0 and lw / rng >= 0.25:
                absorption += 10

            absorption = min(100, absorption)

            distribution = 0

            if rv >= 1.5:
                distribution += 25
            elif rv >= 1.2:
                distribution += 15

            if ret1 <= -1.5:
                distribution += 25
            elif ret1 < 0:
                distribution += 10

            if cl <= 0.35:
                distribution += 25

            if rng > 0 and uw / rng >= 0.25:
                distribution += 15

            if fn5v < 0:
                distribution += 10

            distribution = min(100, distribution)

            foreign_acc = fn5v > 0 and fn10v > 0

            momentum = (
                uptrend
                and rv >= 1.1
                and ret1 > 0
            )

            pullback = (
                uptrend
                and support_distance <= 8
                and ret1 <= 1.5
                and rv >= 0.8
            )

            reversal = (
                (downtrend or c <= s20)
                and support_distance <= 8
                and (
                    absorption >= 50
                    or (cl >= 0.65 and lw > 0)
                    or foreign_acc
                )
                and distribution < 70
            )

            setups = []

            if momentum:
                setups.append("MOMENTUM")

            if pullback:
                setups.append("PULLBACK")

            if reversal:
                setups.append("REVERSAL")

            if absorption >= 50 and distribution < 60:
                setups.append("ABSORPTION")

            if foreign_acc:
                setups.append("FOREIGN_ACCUMULATION")

            if not setups:
                continue

            t1_open = float(x["T1_Open"].iloc[i])
            t1_high = float(x["T1_High"].iloc[i])
            t1_low = float(x["T1_Low"].iloc[i])
            t1_close = float(x["T1_Close"].iloc[i])

            if min(t1_open, t1_high, t1_low, t1_close) <= 0:
                continue

            open_ret = (t1_open / c - 1) * 100
            close_ret = (t1_close / c - 1) * 100
            mfe = (t1_high / c - 1) * 100
            mae = (t1_low / c - 1) * 100

            results.append({
                "date": str(x["Date"].iloc[i]),
                "code": code,
                "setups": setups,

                "rvol": rv,
                "absorption": absorption,
                "distribution": distribution,

                "open_ret": open_ret,
                "close_ret": close_ret,
                "mfe": mfe,
                "mae": mae,

                "win": close_ret > 0,
                "hit_2": mfe >= 2,
                "hit_3": mfe >= 3,
                "hit_4": mfe >= 4,
                "hit_5": mfe >= 5,
            })

    if not results:
        return {
            "status": "OK",
            "samples": 0,
        }

    r = pd.DataFrame(results)

    def summarize(label=None):
        if label:
            q = r[
                r["setups"].apply(
                    lambda x: label in x
                )
            ]
        else:
            q = r

        if q.empty:
            return {"samples": 0}

        return {
            "samples": int(len(q)),
            "win_rate_pct": round(
                float(q["win"].mean() * 100), 2
            ),
            "median_open_pct": round(
                float(q["open_ret"].median()), 3
            ),
            "median_close_pct": round(
                float(q["close_ret"].median()), 3
            ),
            "median_mfe_pct": round(
                float(q["mfe"].median()), 3
            ),
            "median_mae_pct": round(
                float(q["mae"].median()), 3
            ),
            "hit_2_pct": round(
                float(q["hit_2"].mean() * 100), 2
            ),
            "hit_3_pct": round(
                float(q["hit_3"].mean() * 100), 2
            ),
            "hit_4_pct": round(
                float(q["hit_4"].mean() * 100), 2
            ),
            "hit_5_pct": round(
                float(q["hit_5"].mean() * 100), 2
            ),
        }

    return {
        "status": "OK",
        "samples": int(len(r)),
        "first_signal_date": str(r["date"].min()),
        "last_signal_date": str(r["date"].max()),
        "overall": summarize(),
        "setups": {
            name: summarize(name)
            for name in [
                "ABSORPTION",
                "MOMENTUM",
                "PULLBACK",
                "REVERSAL",
                "FOREIGN_ACCUMULATION",
            ]
        },
    }

# ==========================================
# 3. ANALYSIS PIPELINE
# ==========================================
def run_analysis_pipeline():
    """Runs the integrated network and financial analysis."""
    logger.info("Starting Analysis Pipeline...")
    
    # Load raw data
    ratios = load_financial_ratios()

    # Historical trading radar.
    trading_radar, trading_meta = build_trading_radar(DATA_DIR)

    # Walk-forward validation of the trading hypotheses.
    trading_backtest = backtest_trading_radar_v2(DATA_DIR)
    if trading_backtest.get("status") == "OK":
        logger.info(
            "Trading backtest: samples=%s",
            trading_backtest.get("samples", 0),
        )
    logger.info(
        "Trading radar: %s | sessions=%s | stocks=%s",
        trading_meta.get("meta", {}).get("status", trading_meta.get("status")),
        trading_meta.get("meta", {}).get("sessions", 0),
        trading_meta.get("meta", {}).get("stocks", 0),
    )

    # Load latest market close from the daily Parquet export.
    market_data = {}
    market_file = os.path.join(DATA_DIR, "parquet", "stock_summary.parquet")
    try:
        import pandas as pd
        market_df = pd.read_parquet(
            market_file,
            columns=["Date", "StockCode", "Close", "Previous", "Change", "Return", "ListedShares"],
        )
        if not market_df.empty:
            market_df["StockCode"] = market_df["StockCode"].astype(str).str.upper().str.strip()
            market_df = market_df.sort_values("Date").drop_duplicates("StockCode", keep="last")
            for row in market_df.itertuples(index=False):
                code = str(row.StockCode).upper().strip()
                close = float(row.Close) if pd.notna(row.Close) else 0.0
                previous = float(row.Previous) if pd.notna(row.Previous) else 0.0
                change = float(row.Change) if pd.notna(row.Change) else 0.0
                daily_return = float(row.Return) if pd.notna(row.Return) else 0.0
                listed_shares = float(row.ListedShares) if pd.notna(row.ListedShares) else 0.0
                if code:
                    market_data[code] = {
                        "close": close,
                        "previous_price": previous,
                        "daily_change": change,
                        "daily_change_pct": daily_return * 100.0,
                        "listed_shares": listed_shares,
                        "date": str(row.Date),
                    }
            logger.info(f"Loaded latest market prices for {len(market_data)} stocks.")
    except Exception as e:
        logger.warning(f"Could not load latest market prices ({e}). Using financial snapshot valuation.")


    # Load dividend yields from the same dividend engine used by the API/dashboard.
    dividend_yields = {}
    try:
        from idx.dividend import screen_upcoming_dividends
        dividend_df = screen_upcoming_dividends(
            min_yield=0.0,
            year_filter="2026",
            limit=5000,
        )
        if not dividend_df.empty:
            for dividend_row in dividend_df.to_dict("records"):
                ticker = str(dividend_row.get("Ticker", "")).upper().strip()
                if ticker:
                    dividend_yields[ticker] = float(dividend_row.get("Yield%", 0.0) or 0.0)
        logger.info(f"Loaded dividend yields for {len(dividend_yields)} stocks.")
    except Exception as e:
        logger.warning(f"Could not load dividend yields ({e}). Dashboard yield will be unavailable.")

    networks = load_company_networks()
    
    # Join keys
    all_codes = set(ratios.keys()).union(set(networks.keys()))
    logger.info(f"Analyzing {len(all_codes)} unique stock codes.")
    
    # 3.1 Calculate Estimated Market Capitalization using latest close where available.
    market_caps = {}
    for code in all_codes:
        f_data = ratios.get(code, {})
        equity = f_data.get("equity", 0.0)
        price_bv = f_data.get("price_bv", 0.0)
        per = f_data.get("per", 0.0)
        net_profit = f_data.get("profit_period", 0.0)
        md = market_data.get(code, {})
        close = md.get("close", 0.0)
        listed_shares = md.get("listed_shares", 0.0)

        if close > 0 and listed_shares > 0:
            mcap = close * listed_shares / 1_000_000_000.0
        elif price_bv > 0 and equity > 0:
            mcap = price_bv * equity
        elif per > 0 and net_profit > 0:
            mcap = per * net_profit
        elif equity > 0:
            mcap = equity
        else:
            mcap = f_data.get("assets", 0.0) * 0.5

        market_caps[code] = mcap

    # 3.2 Map out Director Networks & Owner Networks
    # Find overlapping insiders across companies
    insider_to_companies = {}
    shareholder_to_companies = {}
    
    for code, net_data in networks.items():
        # Map directors
        for d in net_data['directors']:
            insider_name = clean_name(d['name'])
            if not insider_name:
                continue
            if insider_name not in insider_to_companies:
                insider_to_companies[insider_name] = []
            insider_to_companies[insider_name].append({
                'code': code,
                'role': 'Director',
                'title': d['jabatan']
            })
            
        # Map commissioners
        for k in net_data['commissioners']:
            insider_name = clean_name(k['name'])
            if not insider_name:
                continue
            if insider_name not in insider_to_companies:
                insider_to_companies[insider_name] = []
            insider_to_companies[insider_name].append({
                'code': code,
                'role': 'Commissioner',
                'title': k['jabatan']
            })
            
        # Map shareholders
        for s in net_data['shareholders']:
            sh_name = clean_name(s['name'])
            if not sh_name:
                continue
            if sh_name not in shareholder_to_companies:
                shareholder_to_companies[sh_name] = []
            shareholder_to_companies[sh_name].append({
                'code': code,
                'jumlah': s['jumlah'],
                'persentase': s['persentase'],
                'pengendali': s['pengendali'],
                'raw_name': s['name']
            })

    # 3.3 Find "Super Insiders" (Individual retail tycoons/wealthy stakeholders)
    # We filter out corporate names, and sum up their estimated holdings value
    super_insiders_dict = {}
    
    for sh_name, holdings in shareholder_to_companies.items():
        if is_corporate_name(sh_name):
            continue
            
        total_value = 0.0
        active_holdings = []
        
        for h in holdings:
            code = h['code']
            percentage = h['persentase']
            mcap = market_caps.get(code, 0.0)
            holding_value = (percentage / 100.0) * mcap
            
            if holding_value > 0:
                total_value += holding_value
                active_holdings.append({
                    'code': code,
                    'percentage': percentage,
                    'value': holding_value,
                    'is_controller': h['pengendali']
                })
                
        # Also check if this insider serves on the board of any companies
        connected_roles = []
        if sh_name in insider_to_companies:
            for role_data in insider_to_companies[sh_name]:
                connected_roles.append({
                    'code': role_data['code'],
                    'role': role_data['role'],
                    'title': role_data['title']
                })
                
        # Filter: To be a "Super Insider", they must hold > 5 billion IDR in shares 
        # OR sit on the board of > 1 listed company with shares owned
        if total_value > 5000.0 or len(active_holdings) >= 2 or (len(active_holdings) >= 1 and len(connected_roles) >= 1):
            # Resolve the raw name (take the longest/nicest raw name)
            raw_name = sorted([h['raw_name'] for h in holdings], key=len, reverse=True)[0]
            
            super_insiders_dict[sh_name] = {
                'name': raw_name,
                'clean_name': sh_name,
                'total_value': total_value,
                'holdings': active_holdings,
                'connected_roles': connected_roles
            }

    # 3.4 Group Conglomerate Networks (by corporate controlling shareholders)
    conglomerates_dict = {}
    for sh_name, holdings in shareholder_to_companies.items():
        # A conglomerate controller must be a corporate name (or super insider controller) 
        # and control (pengendali = True or percentage > 20%) multiple companies
        controlled_companies = []
        for h in holdings:
            if h['pengendali'] or h['persentase'] >= 20.0:
                controlled_companies.append(h['code'])
                
        if len(controlled_companies) >= 2 and is_corporate_name(sh_name):
            raw_name = sorted([h['raw_name'] for h in holdings], key=len, reverse=True)[0]
            conglomerates_dict[sh_name] = {
                'controller_name': raw_name,
                'clean_name': sh_name,
                'companies': list(set(controlled_companies))
            }

    # 3.5 Calculate scores and build output list for each company
    companies_list = []
    
    for code in all_codes:
        f_data = ratios.get(code, {})
        net_data = networks.get(code, {
            'directors': [],
            'commissioners': [],
            'shareholders': [],
            'subsidiaries': []
        })
        
        # Financial Ratios
        roe = f_data.get('roe', 0.0)
        roa = f_data.get('roa', 0.0)
        npm = f_data.get('npm', 0.0)
        de_ratio = f_data.get('de_ratio', 0.0)
        per = f_data.get('per', 0.0)
        price_bv = f_data.get("price_bv", 0.0)
        latest_close = market_data.get(code, {}).get("close", 0.0)
        eps = f_data.get("eps", 0.0)
        book_value = f_data.get("book_value", 0.0)

        # Recalculate market-based valuation using the latest available close.
        if latest_close > 0 and eps != 0:
            per = latest_close / eps
        if latest_close > 0 and book_value > 0:
            price_bv = latest_close / book_value
        
        # 1. Financial Health Score (out of 40)
        f_score = 0.0
        if roe >= 20.0:
            f_score += 15.0
        elif roe >= 15.0:
            f_score += 10.0
        elif roe >= 10.0:
            f_score += 5.0
        elif roe < 0.0:
            f_score -= 10.0 # penalty for losing money
            
        if de_ratio > 0:
            if de_ratio <= 0.5:
                f_score += 15.0
            elif de_ratio <= 1.0:
                f_score += 10.0
            elif de_ratio <= 2.0:
                f_score += 5.0
        else:
            f_score += 5.0 # assume moderate leverage if missing
            
        if npm >= 20.0:
            f_score += 10.0
        elif npm >= 10.0:
            f_score += 7.0
        elif npm >= 5.0:
            f_score += 3.0
            
        f_score = max(0.0, min(40.0, f_score))
        
        # 2. Valuation Score (out of 30)
        v_score = 0.0
        # PE Ratio Scoring
        if 0.0 < per < 10.0:
            v_score += 15.0
        elif 10.0 <= per < 15.0:
            v_score += 10.0
        elif 15.0 <= per < 25.0:
            v_score += 5.0
            
        # PBV Ratio Scoring
        if 0.0 < price_bv < 1.0:
            v_score += 15.0
        elif 1.0 <= price_bv < 1.5:
            v_score += 10.0
        elif 1.5 <= price_bv < 3.0:
            v_score += 5.0
            
        v_score = max(0.0, min(30.0, v_score))
        
        # 3. Network Connection Score (out of 30)
        n_score = 0.0
        
        # A. Shared directors/commissioners with Blue Chip companies
        has_blue_chip_bridge = False
        shared_directors = []
        
        # Find all board members of this company
        board_names = []
        for d in net_data['directors']:
            b_name = clean_name(d['name'])
            if b_name:
                board_names.append(b_name)
        for k in net_data['commissioners']:
            b_name = clean_name(k['name'])
            if b_name:
                board_names.append(b_name)
                
        # Check if any board member sits on a Blue Chip board
        for b_name in board_names:
            if b_name in insider_to_companies:
                connected_companies = [r['code'] for r in insider_to_companies[b_name]]
                # Filter out current company
                connected_companies = [c for c in connected_companies if c != code]
                
                # Check for blue chip overlap
                blue_overlap = set(connected_companies).intersection(BLUE_CHIPS)
                if blue_overlap:
                    has_blue_chip_bridge = True
                    shared_directors.append({
                        'insider_name': b_name,
                        'connected_to': list(blue_overlap)
                    })
                    
        if has_blue_chip_bridge:
            n_score += 12.0
            
        # B. Super-Insider Alignment
        has_super_insider = False
        for s in net_data['shareholders']:
            sh_name = clean_name(s['name'])
            if sh_name in super_insiders_dict and s['persentase'] >= 1.0:
                has_super_insider = True
                break
                
        if has_super_insider:
            n_score += 10.0
            
        # C. Conglomerate strength
        is_in_strong_conglom = False
        for s in net_data['shareholders']:
            sh_name = clean_name(s['name'])
            if sh_name in conglomerates_dict:
                # Check average ROE of this conglomerate's companies
                conglom_codes = conglomerates_dict[sh_name]['companies']
                conglom_roes = [ratios.get(c, {}).get('roe', 0.0) for c in conglom_codes if c in ratios]
                if conglom_roes and (sum(conglom_roes) / len(conglom_roes)) >= 15.0:
                    is_in_strong_conglom = True
                    break
                    
        if is_in_strong_conglom:
            n_score += 8.0
            
        n_score = max(0.0, min(30.0, n_score))
        
        # Calculate Total SMSS Score
        total_score = f_score + v_score + n_score
        
        # Build list of network codes for quick visual rendering in dashboard
        network_connections = set()
        for b_name in board_names:
            if b_name in insider_to_companies:
                for conn in insider_to_companies[b_name]:
                    if conn['code'] != code:
                        network_connections.add(conn['code'])
                        
        for s in net_data['shareholders']:
            sh_name = clean_name(s['name'])
            if sh_name in shareholder_to_companies:
                for conn in shareholder_to_companies[sh_name]:
                    if conn['code'] != code:
                        network_connections.add(conn['code'])
                        
        companies_list.append({
            'code': code,
            'name': f_data.get('stock_name') or next((c.get('companyName') for c in net_data.get('shareholders', []) if c.get('code') == code), code),
            'sector': f_data.get('sector', 'N/A'),
            'sub_sector': f_data.get('sub_sector', 'N/A'),
            'industry': f_data.get('industry', 'N/A'),
            'sub_industry': f_data.get('sub_industry', 'N/A'),
            'roe': roe,
            'roa': roa,
            'npm': npm,
            'de_ratio': de_ratio,
            'per': per,
            'price_bv': price_bv,
            'assets': f_data.get('assets', 0.0),
            'liabilities': f_data.get('liabilities', 0.0),
            'equity': f_data.get('equity', 0.0),
            'sales': f_data.get('sales', 0.0),
            'profit_period': f_data.get('profit_period', 0.0),
            'eps': f_data.get('eps', 0.0),
            'book_value': f_data.get('book_value', 0.0),
            'fs_date': f_data.get('fs_date', 'N/A'),
            'close': latest_close,
            'previous_price': market_data.get(code, {}).get('previous_price', 0.0),
            'daily_change': market_data.get(code, {}).get('daily_change', 0.0),
            'daily_change_pct': market_data.get(code, {}).get('daily_change_pct', 0.0),
            'price_date': market_data.get(code, {}).get('date', 'N/A'),
            'yield': dividend_yields.get(code, 0.0),
            'estimated_mcap': market_caps.get(code, 0.0),
            'board_members': [
                {
                    'name': d['name'],
                    'role': 'Director',
                    'title': d['jabatan']
                } for d in net_data['directors']
            ] + [
                {
                    'name': k['name'],
                    'role': 'Commissioner',
                    'title': k['jabatan']
                } for k in net_data['commissioners']
            ],
            'shareholders': [
                {
                    'name': s['name'],
                    'percentage': s['persentase'],
                    'is_controller': s['pengendali']
                } for s in net_data['shareholders']
            ],
            'subsidiaries': [
                {
                    'name': sub['name'],
                    'percentage': sub['persentase'],
                    'bidang_usaha': sub['bidang_usaha']
                } for sub in net_data['subsidiaries']
            ],
            'score': {
                'financial': f_score,
                'valuation': v_score,
                'network': n_score,
                'total': total_score
            },
            'trading': trading_radar.get(code, {
                'next_day_score': 0.0,
                'swing_score': 0.0,
                'reversal_score': 0.0,
                'setups': [],
                'reasons': [],
                'status': 'UNAVAILABLE'
            }),
            'network_connections': list(network_connections)[:15],  # Limit to top 15 connections
            'shared_directors': shared_directors
        })

    # Sort companies list by total score descending
    companies_list = sorted(companies_list, key=lambda x: x['score']['total'], reverse=True)

    # 3.6 Conglomerates formatting
    conglomerates_list = []
    for clean_id, conglom in conglomerates_dict.items():
        c_codes = conglom['companies']
        
        # Calculate aggregate metrics
        total_assets = 0.0
        roes = []
        pbvs = []
        
        for c in c_codes:
            f_data = ratios.get(c, {})
            total_assets += f_data.get('assets', 0.0)
            if 'roe' in f_data and f_data['roe'] > 0:
                roes.append(f_data['roe'])
            if 'price_bv' in f_data and f_data['price_bv'] > 0:
                pbvs.append(f_data['price_bv'])
                
        avg_roe = sum(roes) / len(roes) if roes else 0.0
        avg_pbv = sum(pbvs) / len(pbvs) if pbvs else 0.0
        
        conglomerates_list.append({
            'controller_name': conglom['controller_name'],
            'companies': c_codes,
            'total_assets': total_assets,
            'average_roe': avg_roe,
            'average_pbv': avg_pbv
        })
        
    conglomerates_list = sorted(conglomerates_list, key=lambda x: x['total_assets'], reverse=True)

    # Sort super insiders by portfolio value descending
    super_insiders_list = sorted(
        super_insiders_dict.values(),
        key=lambda x: x['total_value'],
        reverse=True
    )

    # Prepare final output structure
    # Trading rankings are separate from the fundamental/network SMSS ranking.
    # This keeps the old multibagger/compounder engine intact while exposing
    # dedicated next-day, swing, reversal and absorption candidates.
    output_data = {
        'companies': companies_list,
        'super_insiders': super_insiders_list,
        'conglomerates': conglomerates_list,
        'trading_radar': trading_meta,
        'trading_backtest': trading_backtest,
        'last_updated': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # Save to file
    try:
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        with open(OUTPUT_FILE, 'w') as f:
            json.dump(output_data, f, indent=2)
        logger.info(f"Successfully generated analysis dashboard dataset at {OUTPUT_FILE}")
    except Exception as e:
        logger.error(f"Failed to save dashboard dataset: {e}")

if __name__ == "__main__":
    run_analysis_pipeline()




