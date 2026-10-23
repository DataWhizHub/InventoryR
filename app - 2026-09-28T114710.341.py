import streamlit as st
import pandas as pd
import altair as alt
import gspread
import hashlib
import hmac
import secrets
import calendar
import html
import io
import re
from datetime import date, datetime
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

# ============================================================
# RESTAURANT INVENTORY & SOLD QUANTITY SYSTEM
# Storage: Google Sheets only (no local database / CSV)
#
#   Stock Entry       : month-end stock (item, size, qty, unit price, description)
#   Purchases         : purchases of the month (from previous month's stock items)
#   Sold Quantity     : Sold = Previous month stock + Purchases - This month stock
#   Other Expenses    : expenses with Date, Expense Type, Total Rs (editable / deletable)
#   Monthly Sales     : Cash + Card + QR payments of the month (Total = sum)
#   Profit Report     : Profit = Total Sales - Total Cost of Sales - Other Expenses
#   Settings          : users, items (code + main category), password, data import
#
#   Imported previous data keeps its own Total values (column total_value).
# ============================================================

st.set_page_config(
    page_title="Kico Foods Family Restaurant",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAX_STANDARD_USERS = 3  # 1 Admin + up to 3 normal users
CACHE_SECONDS = 300     # sheet data is cached; a save refreshes only the table that changed

# ------------------------- THEME ----------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: Inter, sans-serif; }
.stApp { background: #ffffff; }
.block-container { padding-top: 2.4rem !important; padding-bottom: 2rem; max-width: 1500px; }

section[data-testid="stSidebar"] { background: #172033 !important; border-right: 1px solid #26344d; }
section[data-testid="stSidebar"] * { color: #eef4ff !important; }
section[data-testid="stSidebar"] button {
    color: #ffffff !important; background: #263754 !important; border: 1px solid #3b4d6b !important;
}
section[data-testid="stSidebar"] button:hover { background: #334766 !important; }
.sidebar-brand { font-size: 1.35rem; font-weight: 800; color: #ffffff !important; margin: 0 0 2px 0; }
.sidebar-sub { color: #9fb0ca !important; font-size: .76rem; margin-bottom: 1rem; }
.user-chip { background: #202d43; border: 1px solid #30415d; border-radius: 10px; padding: 10px 12px; margin: 8px 0 15px 0; }
.user-name { font-weight: 700; color: #fff !important; }
.user-role { font-size: .72rem; color: #9fb0ca !important; }

.page-title { font-size: 2rem; line-height: 1.2; font-weight: 800; color: #162033; margin: 0 0 4px 0; }
.page-subtitle { color: #68758a; margin: 0 0 20px 0; font-size: .92rem; }
.card { background: #fff; border: 1px solid #e1e7ef; border-radius: 14px; padding: 18px;
        box-shadow: 0 4px 18px rgba(24,39,75,.05); }
.kpi-label { color: #718096; font-size: .76rem; font-weight: 700; text-transform: uppercase; letter-spacing: .03em; }
.kpi-value { color: #172033; font-size: 1.55rem; font-weight: 800; margin-top: 5px; }
.kpi-blue { border-left: 4px solid #2563eb; }
.kpi-green { border-left: 4px solid #16a34a; }
.kpi-orange { border-left: 4px solid #ea580c; }
.section-title { color: #172033; font-weight: 800; font-size: 1.08rem; margin: 22px 0 10px 0; }
.login-logo { font-size: 2rem; font-weight: 800; color: #172033; }
.login-caption { color: #718096; margin-bottom: 14px; }

/* ---- Profit report table ---- */
.pl-title { font-size: 1.25rem; font-weight: 800; color: #172033; margin: 6px 0 10px 0; }
.pl-table { width: 100%; max-width: 640px; border-collapse: collapse; }
.pl-table td { border: 1px solid #cbd5e1; padding: 9px 14px; color: #162033; background: #ffffff; }
.pl-table td.amt { text-align: right; white-space: nowrap; }
.pl-table tr.head td { background: #e8eef7; font-weight: 800; }
.pl-table tr.sub td { color: #4b5a70; font-size: .92rem; background: #f8fafc; }
.pl-table tr.sub td:first-child { padding-left: 34px; }
.pl-table tr.profit td { background: #e8eef7; font-weight: 800; font-size: 1.08rem; }
.pl-table tr.profit td.pos { color: #15803d; }
.pl-table tr.profit td.neg { color: #dc2626; }

div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, textarea { border-radius: 8px !important; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
#MainMenu { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent !important; pointer-events: none; }
header[data-testid="stHeader"] button, header[data-testid="stHeader"] a { pointer-events: auto; }
[data-testid="stToolbarActions"], [data-testid="stMainMenu"], [data-testid="stAppDeployButton"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"], .stDeployButton { display: none !important; }
/* keep the "open sidebar" arrow visible and clickable after the sidebar is hidden */
[data-testid="stExpandSidebarButton"], [data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"] { display: flex !important; visibility: visible !important;
    pointer-events: auto !important; z-index: 999999; }
footer { visibility: hidden; }

/* ---- Force light look on the main page (device dark mode safe) ---- */
:root { color-scheme: light only; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
    background: #ffffff !important; color: #162033 !important;
}
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li,
[data-testid="stMain"] [data-testid="stWidgetLabel"] p,
[data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] h1, [data-testid="stMain"] h2, [data-testid="stMain"] h3,
[data-testid="stMain"] label, [data-testid="stMain"] summary {
    color: #162033 !important;
}
[data-testid="stMain"] input, [data-testid="stMain"] textarea,
[data-testid="stMain"] div[data-baseweb="input"] > div,
[data-testid="stMain"] div[data-baseweb="select"] > div,
[data-testid="stMain"] div[data-baseweb="base-input"] {
    background: #ffffff !important; color: #162033 !important;
}
div[data-baseweb="popover"] ul, div[data-baseweb="popover"] li,
div[data-baseweb="popover"] div[role="listbox"] {
    background: #ffffff !important; color: #162033 !important;
}
[data-testid="stMain"] [data-testid="stExpander"] details {
    background: #ffffff !important; border-color: #e1e7ef !important;
}
[data-testid="stMain"] button[kind="secondary"],
[data-testid="stMain"] [data-testid="stFormSubmitButton"] button[kind="secondary"],
[data-testid="stMain"] [data-testid="stDownloadButton"] button {
    background: #ffffff !important; color: #162033 !important; border: 1px solid #cbd5e1 !important;
}
[data-testid="stMain"] button[kind="primary"],
[data-testid="stMain"] button[kind="primaryFormSubmit"] {
    background: #2563eb !important; color: #ffffff !important; border: none !important;
}
[data-testid="stMain"] button[data-baseweb="tab"] { color: #162033 !important; }
/* alerts: dark text */
[data-testid="stMain"] [data-testid="stAlert"] * { color: #162033 !important; }
/* Tables / data editors are drawn on a canvas that follows the DEVICE theme (CSS cannot recolour it).
   On a dark device the canvas is dark, so flip it: result = white background, dark text, blue stays blue. */
@media (prefers-color-scheme: dark) {
    [data-testid="stMain"] [data-testid="stDataFrame"],
    [data-testid="stMain"] [data-testid="stDataEditor"] { filter: invert(1) hue-rotate(180deg); }
    /* the small box that opens when you type inside a table cell */
    #portal input, #portal textarea { background: #ffffff !important; color: #162033 !important; }
    #portal .gdg-clip-region, #portal .gdg-clip-region > div { background: #ffffff !important; }
}
</style>
""", unsafe_allow_html=True)


# ------------------------- GOOGLE SHEETS --------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# total_value (last column of Stock and Purchases) is filled ONLY for imported previous data.
# NOTE: new columns of Expenses (expense_date) and Sales (cash/card/qr) are added at the END, so
# existing tabs are extended automatically and old data is kept.
TABLES = {
    "Users": ["id", "username", "password", "full_name", "role", "active", "created_at"],
    "Items": ["id", "item_code", "item_name", "size", "category", "active"],
    "Stock": ["id", "month_key", "item_id", "quantity", "unit_price",
              "description", "entered_by", "updated_at", "total_value"],
    "Purchases": ["id", "month_key", "purchase_date", "item_id", "quantity", "unit_price",
                  "description", "entered_by", "created_at", "total_value"],
    "Expenses": ["id", "month_key", "expense_type", "amount", "entered_by", "updated_at", "expense_date"],
    "Sales": ["id", "month_key", "total_sales", "entered_by", "updated_at",
              "cash_sales", "card_sales", "qr_sales"],
}
NUMERIC_COLS = ["quantity", "unit_price", "amount", "total_sales", "cash_sales", "card_sales", "qr_sales"]

# Tabs are created as Rest_Users, Rest_Items, Rest_Stock, Rest_Purchases, Rest_Expenses, Rest_Sales
# so they never clash with tabs from your other apps if you reuse the same Google Sheet file.
TAB_PREFIX = "Rest_"
IMPORT_TAB = "Rest_Import"  # paste your old data here, then import from Settings > Import Data


@st.cache_resource
def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds).open_by_key(st.secrets["sheet_id"])


def get_worksheets():
    # the table list is part of the cache key, so adding a new table never needs a manual reboot
    return _get_worksheets(tuple(TABLES), tuple(tuple(h) for h in TABLES.values()))


@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def _get_worksheets(table_names, table_headers):
    """Connect once, create any missing worksheet tabs and their header rows."""
    sh = get_spreadsheet()
    # Google Sheets tab names are case-insensitive, so match that way
    existing = {ws.title.strip().lower(): ws for ws in sh.worksheets()}

    result = {}
    for name, headers in TABLES.items():
        title = TAB_PREFIX + name
        ws = existing.get(title.lower())
        if ws is None:
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        first_row = [h.strip() for h in ws.row_values(1)]
        if not first_row:
            ws.append_row(headers, value_input_option="RAW")
        elif first_row[:len(headers)] == headers:
            pass
        elif len(first_row) < len(headers) and first_row == headers[:len(first_row)]:
            # older version of the tab (without the newest column(s)): extend the header row
            if ws.col_count < len(headers):
                ws.resize(cols=len(headers))
            ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        else:
            raise ValueError(
                f"The tab '{ws.title}' already exists but its header row does not match this app "
                f"(expected: {', '.join(headers)}). Rename or delete that tab, or change TAB_PREFIX."
            )
        result[name] = ws
    return result


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return int(v)
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
    if isinstance(v, float) and v != v:  # NaN -> empty cell
        return ""
    return v


@st.cache_resource
def _table_versions():
    """Shared version counter per table. A save bumps only that table, so only it is re-read."""
    return {name: 0 for name in TABLES}


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _read_table_cached(name, version):
    ws = get_worksheets()[name]
    values = ws.get_all_values()
    headers = TABLES[name]
    rows = []
    for r in values[1:]:
        r = (r + [""] * len(headers))[:len(headers)]
        if r[0] != "":
            rows.append(r)
    df = pd.DataFrame(rows, columns=headers)
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "", regex=False), errors="coerce").fillna(0.0)
    if "total_value" in df.columns:
        # blank stays NaN = "no imported total, use quantity x unit price"
        df["total_value"] = pd.to_numeric(
            df["total_value"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    if "active" in df.columns:
        df["active"] = pd.to_numeric(df["active"], errors="coerce").fillna(0).astype(int)
    return df


def read_table(name):
    return _read_table_cached(name, _table_versions().setdefault(name, 0))


def _clear_tables(name=None):
    """Refresh one table (name) or all tables (no argument)."""
    v = _table_versions()
    for t in ([name] if name else list(TABLES)):
        v[t] = v.get(t, 0) + 1


read_table.clear = _clear_tables


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4)}"


def add_row(name, data):
    ws = get_worksheets()[name]
    row = [_clean(data.get(h, "")) for h in TABLES[name]]
    ws.append_row(row, value_input_option="RAW")
    read_table.clear(name)


def update_row(name, row_id, changes):
    ws = get_worksheets()[name]
    ids = ws.col_values(1)
    if row_id not in ids:
        return False
    r = ids.index(row_id) + 1
    headers = TABLES[name]
    batch = [
        {"range": rowcol_to_a1(r, headers.index(k) + 1), "values": [[_clean(v)]]}
        for k, v in changes.items()
    ]
    ws.batch_update(batch, value_input_option="RAW")
    read_table.clear(name)
    return True


def delete_row(name, row_id):
    ws = get_worksheets()[name]
    ids = ws.col_values(1)
    if row_id in ids:
        ws.delete_rows(ids.index(row_id) + 1)
    read_table.clear(name)


def find_stock_id(month_key, item_id):
    """Fresh (uncached) lookup so two people saving at once do not create duplicates."""
    ws = get_worksheets()["Stock"]
    for r in ws.get_all_values()[1:]:
        if len(r) >= 3 and r[1] == month_key and r[2] == item_id:
            return r[0]
    return None


def add_rows(name, rows):
    """Append many rows with ONE API call."""
    if not rows:
        return
    ws = get_worksheets()[name]
    data = [[_clean(r.get(h, "")) for h in TABLES[name]] for r in rows]
    ws.append_rows(data, value_input_option="RAW")
    read_table.clear(name)


def save_stock_batch(month_key, rows, entered_by):
    """
    Save many stock entries at once (max 3 API calls, however many rows).
    rows: list of dicts with item_id, quantity, unit_price, description and optional total_value
          (total_value is only given for imported data; otherwise it is cleared).
    Existing (month, item) rows are updated, the rest are appended.
    """
    ws = get_worksheets()["Stock"]
    values = ws.get_all_values()
    sheet_row = {}  # (month_key, item_id) -> row number in the sheet
    for i, r in enumerate(values[1:], start=2):
        if len(r) >= 3 and r[0] != "":
            sheet_row[(r[1], r[2])] = i

    now = datetime.now().isoformat()
    updates, new_rows = [], []
    for r in rows:
        key = (month_key, r["item_id"])
        tv = _clean(r.get("total_value"))
        tv = float(tv) if tv != "" else ""
        if key in sheet_row:
            n = sheet_row[key]
            # columns D..I = quantity, unit_price, description, entered_by, updated_at, total_value
            updates.append({
                "range": f"D{n}:I{n}",
                "values": [[float(r["quantity"]), float(r["unit_price"]),
                            r["description"], entered_by, now, tv]],
            })
        else:
            new_rows.append([
                new_id("S"), month_key, r["item_id"], float(r["quantity"]),
                float(r["unit_price"]), r["description"], entered_by, now, tv,
            ])

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    read_table.clear("Stock")


def set_purchase_totals(pairs):
    """pairs: list of (purchase_id, total). Fills total_value for already imported purchases (1-2 API calls)."""
    if not pairs:
        return
    ws = get_worksheets()["Purchases"]
    ids = ws.col_values(1)
    col = TABLES["Purchases"].index("total_value") + 1
    batch = []
    for pid, total in pairs:
        if pid in ids:
            batch.append({"range": rowcol_to_a1(ids.index(pid) + 1, col), "values": [[float(total)]]})
    if batch:
        ws.batch_update(batch, value_input_option="RAW")
    read_table.clear("Purchases")


def save_expenses(month_key, rows, entered_by):
    """
    Replace ALL expense rows of one month with `rows`.
    rows: list of dicts: expense_date (ISO text), expense_type, amount and optional id / entered_by
          (id and entered_by are kept for rows that already existed).
    Rows of other months are kept untouched. Uses 2-3 API calls however many rows there are.
    """
    ws = get_worksheets()["Expenses"]
    headers = TABLES["Expenses"]
    # UNFORMATTED_VALUE keeps the real numbers of the other months (not rounded / comma text)
    values = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    keep = [(list(r) + [""] * len(headers))[:len(headers)]
            for r in values[1:] if len(r) >= 2 and r[0] != "" and r[1] != month_key]
    now = datetime.now().isoformat()
    new = [[r.get("id") or new_id("E"), month_key, r["expense_type"], float(r["amount"]),
            r.get("entered_by") or entered_by, now, r["expense_date"]] for r in rows]
    data = [headers] + keep + new
    ws.update(range_name="A1", values=data, value_input_option="RAW")
    if len(values) > len(data):  # old rows that are no longer needed at the bottom
        ws.batch_clear([f"A{len(data) + 1}:{rowcol_to_a1(len(values), len(headers))}"])
    read_table.clear("Expenses")


def save_monthly_sales(month_key, cash, card, qr, entered_by):
    """
    One row per month: Cash + Card + QR payments. total_sales (= the sum) is what the Profit Report uses.
    Update the row if the month exists, otherwise add a new row.
    """
    ws = get_worksheets()["Sales"]
    values = ws.get_all_values()
    now = datetime.now().isoformat()
    cash, card, qr = float(cash), float(card), float(qr)
    total = cash + card + qr
    for i, r in enumerate(values[1:], start=2):
        if len(r) >= 2 and r[0] != "" and r[1] == month_key:
            # columns C..H = total_sales, entered_by, updated_at, cash_sales, card_sales, qr_sales
            ws.batch_update([{"range": f"C{i}:H{i}",
                              "values": [[total, entered_by, now, cash, card, qr]]}],
                            value_input_option="RAW")
            break
    else:
        ws.append_row([new_id("M"), month_key, total, entered_by, now, cash, card, qr],
                      value_input_option="RAW")
    read_table.clear("Sales")


# Connect now and show a friendly message if setup is incomplete
try:
    get_worksheets()
except KeyError as e:
    st.error(f"Missing Streamlit secret or worksheet: {e}. Add `sheet_id` and `[gcp_service_account]` "
             "to .streamlit/secrets.toml (see the setup notes). If you just updated the app, reboot it once.")
    st.stop()
except gspread.exceptions.SpreadsheetNotFound:
    st.error("Spreadsheet not found. Check `sheet_id` and share the sheet with the service-account "
             "email as Editor.")
    st.stop()
except Exception as e:
    st.error(f"Could not connect to Google Sheets: {e}")
    st.stop()


# ------------------------- HELPERS --------------------------
def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, digest = str(stored).split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(calc, digest)


def money(value):
    return f"Rs. {float(value):,.2f}"


def size_label(size):
    """Display text for a size / variety. Items without a size show '(No size)'."""
    s = "" if size is None or (isinstance(size, float) and pd.isna(size)) else str(size).strip()
    return s if s else "(No size)"


def month_label(month_key):
    return pd.to_datetime(month_key + "-01").strftime("%B %Y")


def previous_month(month_key):
    d = pd.to_datetime(month_key + "-01") - pd.DateOffset(months=1)
    return d.strftime("%Y-%m")


def month_picker(label, key):
    """Year + month selectors. Returns 'YYYY-MM'."""
    today = date.today()
    years = list(range(today.year - 4, today.year + 2))
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        y = st.selectbox(f"{label} - Year", years, index=years.index(today.year), key=f"{key}_y")
    with c2:
        m = st.selectbox(
            f"{label} - Month", list(range(1, 13)), index=today.month - 1,
            format_func=lambda x: calendar.month_name[x], key=f"{key}_m"
        )
    return f"{y}-{m:02d}"


def get_items():
    df = read_table("Items")
    return df[df["active"] == 1][["id", "item_code", "item_name", "size", "category"]] \
        .sort_values(["category", "item_name", "size"])


def items_lookup():
    """Items renamed so 'id' becomes 'item_id' (for merging with Stock / Purchases)."""
    df = read_table("Items")
    return df.rename(columns={"id": "item_id"})[
        ["item_id", "item_code", "item_name", "size", "category", "active"]]


def category_list():
    df = read_table("Items")
    return sorted(c for c in df["category"].astype(str).str.strip().unique() if c)


def next_item_codes(count):
    """Next `count` item codes: 0001, 0002, ... continuing after the highest numeric code in use."""
    codes = read_table("Items")["item_code"].astype(str).str.strip()
    nums = [int(c) for c in codes if c.isdigit()]
    start = (max(nums) if nums else 0) + 1
    return [f"{n:04d}" for n in range(start, start + count)]


def add_item_ui(key):
    """Add an item with a Main Category. Item Codes (0001, 0002, ...) are generated automatically."""
    ver_key = f"{key}_ver"
    st.session_state.setdefault(ver_key, 0)
    cats = category_list()

    with st.form(f"{key}_form", clear_on_submit=True):
        a, b, c = st.columns([2, 1.5, 1.5])
        name = a.text_input("Item name *", placeholder="Water")
        cat_sel = b.selectbox("Main category", ["(choose)"] + cats)
        cat_new = c.text_input("...or new category", placeholder="Beverages")
        st.caption("One row per size / variety. Item Codes are generated automatically "
                   f"(next code: {next_item_codes(1)[0]}). "
                   "For an item with no size, leave the table empty. "
                   "Click the empty bottom row to add more rows.")
        rows_df = st.data_editor(
            pd.DataFrame({"Size / Variety": ["", "", ""]}),
            num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"{key}_sizes_{st.session_state[ver_key]}",
        )
        submitted = st.form_submit_button("Save Item", type="primary")

    if submitted:
        category = cat_new.strip() or ("" if cat_sel == "(choose)" else cat_sel)
        sizes = [s.strip() for s in rows_df["Size / Variety"].fillna("").astype(str) if s.strip()]
        if not sizes:
            sizes = [""]  # item without a size / variety

        if not name.strip():
            st.error("Item name is required.")
        elif not category:
            st.error("Choose or type a main category.")
        elif len({s.lower() for s in sizes}) != len(sizes):
            st.error("The same size / variety is entered twice.")
        else:
            read_table.clear("Items")  # fresh read so codes are never reused
            codes = next_item_codes(len(sizes))
            add_rows("Items", [
                {"id": new_id("I"), "item_code": code, "item_name": name.strip(),
                 "size": s, "category": category, "active": 1}
                for code, s in zip(codes, sizes)
            ])
            st.session_state[ver_key] += 1
            st.success(f"Added {name.strip()} ({category}): {', '.join(codes)}.")


def header(title, subtitle):
    st.markdown(f'<div class="page-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def show_flash(key):
    """Show (once) a success message stored before a st.rerun()."""
    msg = st.session_state.pop(key, None)
    if msg:
        st.success(msg)


def normal_user_count():
    u = read_table("Users")
    return int(((u["role"] != "Admin") & (u["active"] == 1)).sum())


def add_cost_of_sales(df):
    """
    Adds the column 'cost_of_sales' to a Sold Quantity table.
    Weighted average price = (previous end qty x previous end price + total purchase value)
                             / (previous end qty + purchase qty)
    Cost of Sales = weighted average price x sold quantity
    """
    df = df.copy()
    out = []
    for r in df.to_dict("records"):
        open_qty = max(float(r["opening_qty"]), 0.0)
        buy_qty = max(float(r["purchase_qty"]), 0.0)
        total_qty = open_qty + buy_qty
        if total_qty <= 0:
            out.append(0.0)
            continue
        total_value = open_qty * float(r["opening_price"]) + float(r["purchase_value"])
        out.append((total_value / total_qty) * float(r["sold_qty"]))
    df["cost_of_sales"] = out
    return df


def compute_sold_data():
    """
    Sold quantity (and cost of sales) of every item and month, calculated from the stock and
    purchases tables. Returns None when no stock exists yet, otherwise a DataFrame
    (empty if there are not two consecutive months of stock).
    """
    stock = read_table("Stock")[["month_key", "item_id", "quantity", "unit_price", "total_value"]] \
        .rename(columns={"quantity": "closing_qty", "total_value": "closing_total"})
    if stock.empty:
        return None

    purch_raw = read_table("Purchases").copy()
    # imported purchases use their own Total; all others use quantity x unit price
    # (the purchase unit price is still needed by the PDF report)
    purch_raw["purchase_value"] = purch_raw["total_value"].where(
        purch_raw["total_value"].notna(), purch_raw["quantity"] * purch_raw["unit_price"])
    purch = purch_raw.groupby(["month_key", "item_id"], as_index=False)[["quantity", "purchase_value"]].sum() \
        .rename(columns={"quantity": "purchase_qty"})
    items_all = items_lookup()[["item_id", "item_code", "item_name", "size", "category"]]

    stock["prev_key"] = stock["month_key"].map(previous_month)
    prev_stock = stock[["month_key", "item_id", "closing_qty", "unit_price", "closing_total"]].rename(
        columns={"month_key": "prev_key", "closing_qty": "opening_qty", "unit_price": "opening_price",
                 "closing_total": "opening_total"}
    )

    df = stock.merge(prev_stock, on=["prev_key", "item_id"], how="left")
    # Only months where the previous month's stock exists can be calculated
    df = df[df["prev_key"].isin(set(stock["month_key"]))].copy()
    df["opening_qty"] = df["opening_qty"].fillna(0.0)
    df["opening_price"] = df["opening_price"].fillna(0.0)
    df = df.merge(purch, on=["month_key", "item_id"], how="left")
    df["purchase_qty"] = df["purchase_qty"].fillna(0.0)
    df["purchase_value"] = df["purchase_value"].fillna(0.0)
    df = df.merge(items_all, on="item_id", how="left")
    df["category"] = df["category"].fillna("")

    df["sold_qty"] = df["opening_qty"] + df["purchase_qty"] - df["closing_qty"]
    return add_cost_of_sales(df)


def build_sales_report_pdf(rep, mk, prev_rep=None):
    """
    Monthly Sold Quantity Report PDF (landscape A4) for month `mk`.
    - Only Sold Quantity and Cost of Sales are shown (no sales values)
    - Cost of Sales = (weighted average price x Sold Quantity, where the weighted average price =
                      (prev end qty x prev end price + purchase value) / (prev end qty + purchase qty)
    - Main-category-wise "Total" row after each category's items
    - Last page: Main Category sold quantity summary (previous month, this month, growth %)
    The rows are split into fixed-size pages by hand (header repeated on every page), so the
    tables never need reportlab's automatic table splitting.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, PageBreak, KeepInFrame)

    cur_name = calendar.month_name[int(mk[5:7])]
    prev_name = calendar.month_name[int(previous_month(mk)[5:7])]
    ROWS_PER_PAGE = 20

    rep = rep.copy()
    rep["category"] = rep["category"].astype(str).str.strip()
    rep = rep.sort_values(["category", "item_name", "size"]).copy()
    rep["label"] = [str(n) if str(s).strip() == "" else f"{n} - {str(s).strip()}"
                    for n, s in zip(rep["item_name"], rep["size"])]
    rep["purchase_price"] = [(v / q) if q else 0.0 for v, q in zip(rep["purchase_value"], rep["purchase_qty"])]

    # ---- Cost of Sales (same calculation as the Profit Report) ----
    rep = add_cost_of_sales(rep)

    def n2(x):
        return f"{float(x):,.2f}"

    cell_style = ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10)

    # entries: ("item", category, cells) or ("sub", category, cells)
    entries = []
    for cat, g in rep.groupby("category", sort=False):
        for _, r in g.iterrows():
            entries.append(("item", cat, [
                cat, Paragraph(str(r["label"]).replace("&", "&amp;").replace("<", "&lt;"), cell_style),
                n2(r["opening_qty"]), n2(r["opening_price"]),
                n2(r["purchase_qty"]), n2(r["purchase_price"]),
                n2(r["closing_qty"]), n2(r["unit_price"]),
                n2(r["sold_qty"]), n2(r["cost_of_sales"]),
            ]))
        entries.append(("sub", cat, [
            f"Total - {cat}" if cat else "Total", "", "", "", "", "", "", "",
            n2(g["sold_qty"].sum()), n2(g["cost_of_sales"].sum()),
        ]))
    total_sold = n2(rep["sold_qty"].sum())
    total_cost = n2(rep["cost_of_sales"].sum())

    widths = [90, 170, 56, 56, 56, 56, 56, 56, 80, 90]
    title_style = ParagraphStyle("t", parent=getSampleStyleSheet()["Heading2"], alignment=1)
    title = f"Monthly Sold Quantity Report - {cur_name} {mk[:4]}"

    chunks = [entries[i:i + ROWS_PER_PAGE] for i in range(0, len(entries), ROWS_PER_PAGE)] or [[]]
    story = []
    for ci, chunk in enumerate(chunks):
        is_last = ci == len(chunks) - 1
        data = [
            ["Main Category", "Item with Size/Variety", f"{prev_name} End Stock", "",
             f"{cur_name} Purchases", "", f"{cur_name} End Stock", "", "Sold Quantity", "Cost of Sales"],
            ["", "", "Quantity", "Unit Price", "Quantity", "Unit Price", "Quantity", "Unit Price", "", ""],
        ]
        spans = [("SPAN", (0, 0), (0, 1)), ("SPAN", (1, 0), (1, 1)), ("SPAN", (2, 0), (3, 0)),
                 ("SPAN", (4, 0), (5, 0)), ("SPAN", (6, 0), (7, 0)), ("SPAN", (8, 0), (8, 1)),
                 ("SPAN", (9, 0), (9, 1))]

        # category shown once per group of item rows (merged cell); category total row spans A-H
        start, cur, sub_rows = None, None, []
        for i, (kind, cat, cells) in enumerate(chunk):
            r_no = 2 + i
            if kind == "item":
                if cur != cat:
                    if start is not None and r_no - 1 > start:
                        spans.append(("SPAN", (0, start), (0, r_no - 1)))
                    start, cur = r_no, cat
            else:
                if start is not None and r_no - 1 > start:
                    spans.append(("SPAN", (0, start), (0, r_no - 1)))
                start, cur = None, None
                spans.append(("SPAN", (0, r_no), (7, r_no)))
                sub_rows.append(r_no)
            data.append(cells)
        last_data_row = 1 + len(chunk)
        if start is not None and last_data_row > start:
            spans.append(("SPAN", (0, start), (0, last_data_row)))

        total_row = None
        if is_last:
            total_row = len(data)
            data.append(["Total", "", "", "", "", "", "", "", total_sold, total_cost])
            spans.append(("SPAN", (0, total_row), (7, total_row)))

        style = [
            ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, 1), "CENTER"),
            ("ALIGN", (2, 2), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 2), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#e8eef7")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for r_no in sub_rows:
            style += [("FONTNAME", (0, r_no), (-1, r_no), "Helvetica-Bold"),
                      ("BACKGROUND", (0, r_no), (-1, r_no), colors.HexColor("#f1f5fb")),
                      ("ALIGN", (0, r_no), (7, r_no), "RIGHT")]
        if total_row is not None:
            style += [("FONTNAME", (0, total_row), (-1, total_row), "Helvetica-Bold"),
                      ("BACKGROUND", (0, total_row), (-1, total_row), colors.HexColor("#e8eef7")),
                      ("ALIGN", (0, total_row), (7, total_row), "RIGHT")]
        table = Table(data, colWidths=widths)
        table.setStyle(TableStyle(style + spans))

        page = [Paragraph(title + ("" if ci == 0 else " (continued)"), title_style), Spacer(1, 8), table]
        # shrink-to-fit safety net: a page can never overflow, so no layout error is possible
        story.append(KeepInFrame(786, 500, page, mode="shrink"))
        story.append(PageBreak())

    # ---- Main Category sold quantity summary (last page) ----
    cur_by_cat = rep.groupby("category")["sold_qty"].sum()
    if prev_rep is not None and len(prev_rep) > 0:
        pr = prev_rep.copy()
        pr["category"] = pr["category"].astype(str).str.strip()
        prev_by_cat = pr.groupby("category")["sold_qty"].sum()
    else:
        prev_by_cat = pd.Series(dtype=float)

    cats = sorted(set(cur_by_cat.index) | set(prev_by_cat.index))
    cur_year = int(mk[:4])
    prev_year = int(previous_month(mk)[:4])
    sum_data = [["Main Category", f"{prev_name} {prev_year} Sold Quantity",
                 f"{cur_name} {cur_year} Sold Quantity", "Growth %"]]

    def growth(cur_v, prev_v):
        if not prev_v:
            return "N/A"
        return f"{(cur_v - prev_v) / abs(prev_v) * 100:+,.2f}%"

    for c in cats:
        pv, cv = float(prev_by_cat.get(c, 0.0)), float(cur_by_cat.get(c, 0.0))
        sum_data.append([c or "(No category)", n2(pv), n2(cv), growth(cv, pv)])
    tp, tc = float(prev_by_cat.sum()), float(cur_by_cat.sum())
    sum_data.append(["Total", n2(tp), n2(tc), growth(tc, tp)])

    last_r = len(sum_data) - 1
    sum_table = Table(sum_data, colWidths=[200, 170, 170, 100])
    sum_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, last_r), (-1, last_r), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
        ("BACKGROUND", (0, last_r), (-1, last_r), colors.HexColor("#e8eef7")),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(Paragraph(f"Main Category Sold Quantity Summary - {cur_name} {cur_year}", title_style))
    story.append(Spacer(1, 8))
    story.append(sum_table)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=28, rightMargin=28,
                            topMargin=28, bottomMargin=28, title=title)
    doc.build(story)
    return buf.getvalue()


def build_profit_report_pdf(title, sales, cost, expenses, profit):
    """
    Profit Report PDF (portrait A4).
    expenses: list of (expense_type, amount). Profit = Total Sales - Total Cost of Sales - Other Expenses.
    Under "Other Expenses" every expense type is shown ONCE with its total
    (several entries of the same type, e.g. on different dates, are added together).
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    def n2(x):
        return f"{float(x):,.2f}"

    # ---- total of each expense type (same type = one row; first spelling / order is kept) ----
    type_totals = {}   # lower-case type -> [display name, total]
    for t, a in expenses:
        name = str(t).strip()
        key = name.lower()
        if key in type_totals:
            type_totals[key][1] += float(a)
        else:
            type_totals[key] = [name, float(a)]
    expense_rows = [(name, total) for name, total in type_totals.values()]

    other_total = sum(a for _, a in expense_rows)
    data = [["Total Sales", n2(sales)],
            ["Total Cost of Sales", n2(cost)],
            ["Other Expenses", n2(other_total)]]
    for t, a in expense_rows:
        data.append([t, n2(a)])
    data.append(["Profit", n2(profit)])
    profit_row = len(data) - 1

    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, 0), (-1, 2), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, 2), colors.HexColor("#e8eef7")),
        ("LEFTPADDING", (0, 3), (0, profit_row - 1), 26),
        ("TEXTCOLOR", (0, 3), (-1, profit_row - 1), colors.HexColor("#4b5a70")),
        ("FONTNAME", (0, profit_row), (-1, profit_row), "Helvetica-Bold"),
        ("FONTSIZE", (0, profit_row), (-1, profit_row), 11),
        ("BACKGROUND", (0, profit_row), (-1, profit_row), colors.HexColor("#e8eef7")),
    ]
    table = Table(data, colWidths=[300, 150])
    table.setStyle(TableStyle(style))

    title_style = ParagraphStyle("pt", parent=getSampleStyleSheet()["Heading2"], alignment=1)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=60, rightMargin=60,
                            topMargin=50, bottomMargin=50, title=title)
    doc.build([Paragraph(html.escape(title), title_style), Spacer(1, 12), table])
    return buf.getvalue()


# ------------------------- DATA IMPORT ----------------------
MONTH_NUM = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
BLOCK_RE = re.compile(r"(opening stock|closing stock|purchases)\s*\(\s*([a-z]+)\s+(\d{4})\s*\)", re.I)


def parse_num(v):
    """'570kg' -> 570, '250g' -> 0.25, '(100pkt)1860' -> 1860, '-' -> None. Returns (number, note)."""
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "nan", "None"):
        return None, ""
    s = re.sub(r"\(.*?\)", "", s).strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)", s)
    if not m:
        return None, f"Could not read '{v}'"
    num, unit = float(m.group(1)), m.group(2).lower()
    if unit in ("", "kg", "l"):
        return num, ""
    if unit == "g":
        val = num / 1000 if num >= 10 else num
        return val, f"'{v}' read as {val:g} kg"
    return num, f"Unit '{unit}' ignored in '{v}'"


def parse_import_tab():
    """
    Reads the Rest_Import tab.
    Columns A-D : Item Code | Main Category | Item | Size
    Row 1       : group headings, e.g. 'Opening Stock (April 2026)', 'Purchases (May 2026)'
    Row 2       : Qty | Unit Price | Total under each group
    Row 3 +     : data
    The Total of each group is kept and later used for calculations.
    """
    # UNFORMATTED_VALUE = real stored numbers (167.7), not the rounded text shown in the cell (168)
    values = get_spreadsheet().worksheet(IMPORT_TAB).get_all_values(value_render_option="UNFORMATTED_VALUE")
    if len(values) < 3:
        return {"error": f"The {IMPORT_TAB} tab needs 2 header rows and at least one data row."}
    raw = pd.DataFrame(values).fillna("")

    groups, last = [], ""
    for v in raw.iloc[0]:
        v = str(v).strip()
        if v:
            last = v
        groups.append(last)
    subs = [str(v).strip().lower() for v in raw.iloc[1]]

    blocks = {}  # (kind, month_key) -> {"qty": col, "price": col, "total": col}
    for i in range(4, raw.shape[1]):
        m = BLOCK_RE.search(groups[i])
        if not m or subs[i] not in ("qty", "unit price", "total"):
            continue
        month = MONTH_NUM.get(m.group(2).lower())
        if not month:
            continue
        mk = f"{int(m.group(3))}-{month:02d}"
        kind = m.group(1).lower().split()[0]  # opening / closing / purchases
        blocks.setdefault((kind, mk), {})[{"qty": "qty", "unit price": "price", "total": "total"}[subs[i]]] = i
    if not blocks:
        return {"error": "No headings like 'Opening Stock (April 2026)' were found in row 1."}

    items, stock, purch, issues = {}, {}, [], []
    for _, r in raw.iloc[2:].iterrows():
        code, cat, name, size = [str(r[i]).strip() for i in range(4)]
        if not code:
            continue
        items[code] = {"category": cat, "name": name, "size": size}
        label = f"{name} {size}".strip()
        for (kind, mk), cols in blocks.items():
            qty, n1 = parse_num(r[cols["qty"]]) if "qty" in cols else (None, "")
            price, n2 = parse_num(r[cols["price"]]) if "price" in cols else (None, "")
            total, _ = parse_num(r[cols["total"]]) if "total" in cols else (None, "")
            for n in (n1, n2):
                if n:
                    issues.append({"Code": code, "Item": label,
                                   "Column": f"{kind.title()} {mk}", "Problem": n})
            if qty is None:
                continue
            price = price or 0.0
            if total is not None and abs(qty * price - total) > max(1.0, 0.02 * abs(total)):
                issues.append({"Code": code, "Item": label, "Column": f"{kind.title()} {mk}",
                               "Problem": f"Qty x Price = {qty * price:,.2f} but Total says {total:,.2f}"})
            if kind == "purchases":
                if qty > 0:
                    purch.append({"code": code, "month_key": mk, "quantity": qty,
                                  "unit_price": price, "total": total})
            else:
                # Opening stock of a month = closing stock of the previous month
                smk = previous_month(mk) if kind == "opening" else mk
                stock[(smk, code)] = {"quantity": qty, "unit_price": price, "total": total}
    return {"items": items, "stock": stock, "purchases": purch, "issues": issues}


def create_import_tab():
    """Create the Rest_Import tab with the two header rows. Returns False if it already exists."""
    sh = get_spreadsheet()
    if IMPORT_TAB.lower() in [w.title.strip().lower() for w in sh.worksheets()]:
        return False
    groups = ["Opening Stock (April 2026)",
              "Purchases (April 2026)", "Closing Stock (April 2026)",
              "Purchases (May 2026)", "Closing Stock (May 2026)",
              "Purchases (June 2026)", "Closing Stock (June 2026)"]
    row1 = ["Item Code", "Main Category", "Item", "Size"]
    row2 = ["", "", "", ""]
    for g in groups:
        row1 += [g, "", ""]
        row2 += ["Qty", "Unit Price", "Total"]
    ws = sh.add_worksheet(title=IMPORT_TAB, rows=300, cols=len(row1))
    ws.format("A:A", {"numberFormat": {"type": "TEXT"}})  # keep codes like 001 as text
    ws.update(range_name="A1", values=[row1, row2], value_input_option="RAW")
    ws.freeze(rows=2)
    return True


def run_import(imp, username):
    """Returns (new items, stock records saved, new purchases, existing purchases that got their Total)."""
    items_df = read_table("Items")
    code_to_id = dict(zip(items_df["item_code"].str.strip(), items_df["id"]))
    new_items = []
    for code, it in imp["items"].items():
        if code not in code_to_id:
            code_to_id[code] = new_id("I")
            new_items.append({"id": code_to_id[code], "item_code": code, "item_name": it["name"],
                              "size": it["size"], "category": it["category"], "active": 1})
    add_rows("Items", new_items)

    by_month = {}
    for (mk, code), v in imp["stock"].items():
        by_month.setdefault(mk, []).append({
            "item_id": code_to_id[code], "quantity": v["quantity"],
            "unit_price": v["unit_price"], "description": "Imported",
            "total_value": v.get("total")})  # imported Total is kept for calculations
    for mk, rows in sorted(by_month.items()):
        save_stock_batch(mk, rows, username)

    read_table.clear("Purchases")
    pdf = read_table("Purchases")
    imported = pdf[pdf["description"] == "Imported"]
    done = {(m, i): (pid, tv) for m, i, pid, tv in
            zip(imported["month_key"], imported["item_id"], imported["id"], imported["total_value"])}
    now, new_p, fill_totals = datetime.now().isoformat(), [], []
    for p in imp["purchases"]:
        iid = code_to_id[p["code"]]
        if (p["month_key"], iid) in done:
            # already imported once: only fill in the Total if it is still missing
            pid, tv = done[(p["month_key"], iid)]
            if p.get("total") is not None and pd.isna(tv):
                fill_totals.append((pid, p["total"]))
            continue
        new_p.append({
            "id": new_id("P"), "month_key": p["month_key"], "purchase_date": p["month_key"] + "-01",
            "item_id": iid, "quantity": p["quantity"], "unit_price": p["unit_price"],
            "description": "Imported", "entered_by": username, "created_at": now,
            "total_value": p.get("total")})
    add_rows("Purchases", new_p)
    set_purchase_totals(fill_totals)
    return len(new_items), len(imp["stock"]), len(new_p), len(fill_totals)


# ------------------------- AUTHENTICATION -------------------
def center_page_css():
    """Centre the login / registration block in the middle of the page."""
    st.markdown("""
<style>
.block-container { min-height: 92vh; display: flex; flex-direction: column; justify-content: center; }
.login-logo, .login-caption { text-align: center; }
</style>
""", unsafe_allow_html=True)


def registration_exists():
    return len(read_table("Users")) > 0


def registration_page():
    center_page_css()
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="login-logo">🍽️ Restaurant Inventory</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-caption">Create the first administrator account</div>', unsafe_allow_html=True)
        st.info("This screen appears only once. The first account becomes the Administrator. "
                "The Administrator creates all other logins from Settings.")

        full_name = st.text_input("Full Name *")
        username = st.text_input("Username *")
        password = st.text_input("Password *", type="password")
        confirm = st.text_input("Confirm Password *", type="password")

        if st.button("Create Administrator Account", type="primary", use_container_width=True):
            if not full_name.strip() or not username.strip() or not password:
                st.error("Please complete all required fields.")
            elif len(password) < 6:
                st.error("Password must contain at least 6 characters.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                read_table.clear()
                if registration_exists():
                    st.warning("Registration is already completed. Please log in.")
                else:
                    add_row("Users", {
                        "id": new_id("U"), "username": username.strip(),
                        "password": hash_password(password), "full_name": full_name.strip(),
                        "role": "Admin", "active": 1, "created_at": datetime.now().isoformat(),
                    })
                    st.success("Administrator created. Please log in.")
                    st.rerun()


def login_page():
    center_page_css()
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="login-logo">🍽️ Restaurant Inventory</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-caption">Monthly stock, purchases & sold quantity</div>',
                    unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            try:
                username = st.text_input("Username", placeholder="Enter username", autocomplete="username")
                password = st.text_input("Password", type="password", placeholder="Enter password",
                                         autocomplete="current-password")
            except TypeError:  # older Streamlit without the autocomplete option
                username = st.text_input("Username", placeholder="Enter username")
                password = st.text_input("Password", type="password", placeholder="Enter password")
            submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

        if submitted:
            users = read_table("Users")
            hit = users[(users["username"] == username.strip()) & (users["active"] == 1)]
            if not hit.empty and verify_password(password, hit.iloc[0]["password"]):
                st.session_state.user = hit.iloc[0].to_dict()
                st.rerun()
            else:
                st.error("Invalid username or password.")


if "user" not in st.session_state:
    if not registration_exists():
        registration_page()
    else:
        login_page()
    st.stop()


# ------------------------- SIDEBAR --------------------------
user = st.session_state.user
is_admin = user["role"] == "Admin"

st.sidebar.markdown('<div class="sidebar-brand">🍽️ Kico Foods Family Restaurant</div>', unsafe_allow_html=True)
st.sidebar.markdown('<div class="sidebar-sub">Inventory & Sold Quantity</div>', unsafe_allow_html=True)
st.sidebar.markdown(f"""
<div class="user-chip">
    <div class="user-name">{user["full_name"]}</div>
    <div class="user-role">{user["role"]} • @{user["username"]}</div>
</div>
""", unsafe_allow_html=True)

menu = ["Stock Entry", "Purchases", "Sold Quantity", "Other Expenses", "Monthly Sales", "Profit Report"]
if is_admin:
    menu.append("Settings")

page = st.sidebar.radio("MENU", menu)
st.sidebar.divider()
if st.sidebar.button("🔄 Refresh data", use_container_width=True):
    read_table.clear()
    st.rerun()
if st.sidebar.button("↪  Logout", use_container_width=True):
    st.session_state.pop("user", None)
    st.rerun()


# ============================================================
# STOCK ENTRY  (month-end stock)
# ============================================================
if page == "Stock Entry":
    header("Monthly Stock Entry",
           "Order of work: Opening stock (first month only) → Purchases → Closing stock at the end of "
           "each month. Later months use the previous month's closing stock as their opening stock.")

    mk = month_picker("Stock month", "stock")

    stock_type = st.radio(
        "Stock type",
        ["Closing stock (end of month)", "Opening stock (start of month)"],
        horizontal=True, key="stock_type",
    )
    is_opening = stock_type.startswith("Opening")
    # Opening stock of a month = closing stock of the previous month, so it is stored under that month.
    sk = previous_month(mk) if is_opening else mk
    if is_opening:
        stock_title = f"Opening stock - start of {month_label(mk)}"
        st.info(f"Opening stock of {month_label(mk)} is the same as the closing stock of {month_label(sk)}. "
                "Enter it once for your first month; after that it comes automatically from the previous "
                "month's closing stock.")
    else:
        stock_title = f"Closing stock - end of {month_label(mk)}"

    with st.expander("➕ Add a new item with its sizes / varieties (sizes are optional)"):
        add_item_ui("stock_add")

    items = get_items()

    if items.empty:
        st.info("No items yet. Add your first item above.")
    else:
        prev = previous_month(sk)
        stock_all = read_table("Stock")

        sel_cat = st.selectbox("Main category", ["All categories"] + sorted(items["category"].unique()),
                               key="stock_cat_sel")
        if sel_cat != "All categories":
            items = items[items["category"] == sel_cat]

        item_names = ["All items"] + sorted(items["item_name"].unique().tolist())
        sel_item = st.selectbox("Item", item_names, key=f"stock_item_sel_{sel_cat}")

        pool = items if sel_item == "All items" else items[items["item_name"] == sel_item]
        pool = pool.rename(columns={"id": "item_id"})

        cur = stock_all[stock_all["month_key"] == sk][["item_id", "quantity", "unit_price", "description", "total_value"]]
        prv = stock_all[stock_all["month_key"] == prev][["item_id", "unit_price"]] \
            .rename(columns={"unit_price": "prev_price"})

        base = pool.merge(cur, on="item_id", how="left").merge(prv, on="item_id", how="left")
        base["unit_price"] = base["unit_price"].fillna(base["prev_price"])  # suggest last month's price
        base["description"] = base["description"].fillna("")
        base = base.sort_values(["item_name", "size"])

        editor_df = pd.DataFrame({
            "item_id": base["item_id"].values,
            "Code": base["item_code"].values,
            "Item": base["item_name"].values,
            "Size / Variety": [("" if str(s).strip() == "" else s) for s in base["size"].values],
            "Quantity": base["quantity"].values,
            "Unit Price": base["unit_price"].values,
            "Description": base["description"].values,
        })

        st.session_state.setdefault("stock_ver", 0)
        st.caption(f"{stock_title}: fill the table and press **Save Stock** once - "
                   "all rows are saved together. Leave Quantity empty to skip a row; enter 0 if the item is out of stock.")

        with st.form("stock_form"):
            edited = st.data_editor(
                editor_df,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                disabled=["Code", "Item", "Size / Variety"],
                column_config={
                    "item_id": None,
                    "Quantity": st.column_config.NumberColumn(
                        "Quantity (opening stock)" if is_opening else "Quantity (closing stock)",
                        min_value=0.0, step=0.01, format="%.2f"),
                    "Unit Price": st.column_config.NumberColumn("Unit Price (Rs.)", min_value=0.0, format="%.2f"),
                    "Description": st.column_config.TextColumn("Description"),
                },
                key=f"stock_editor_{sk}_{sel_cat}_{sel_item}_{st.session_state['stock_ver']}",
            )
            save_clicked = st.form_submit_button("Save Stock", type="primary")

        if save_clicked:
            # imported rows keep their Total only while quantity and unit price are left unchanged
            orig = {r.item_id: (float(r.quantity), float(r.unit_price), r.total_value)
                    for r in cur.itertuples()}
            rows = []
            for _, r in edited.iterrows():
                if pd.isna(r["Quantity"]):
                    continue
                qty = float(r["Quantity"])
                price = 0.0 if pd.isna(r["Unit Price"]) else float(r["Unit Price"])
                keep_total = None
                o = orig.get(r["item_id"])
                if o is not None and pd.notna(o[2]) and abs(o[0] - qty) < 1e-9 and abs(o[1] - price) < 1e-9:
                    keep_total = float(o[2])
                rows.append({
                    "item_id": r["item_id"],
                    "quantity": qty,
                    "unit_price": price,
                    "description": "" if pd.isna(r["Description"]) else str(r["Description"]).strip(),
                    "total_value": keep_total,
                })
            if not rows:
                st.warning("Enter at least one quantity before saving.")
            else:
                save_stock_batch(sk, rows, user["username"])
                st.session_state["stock_ver"] += 1
                st.success(f"{len(rows)} stock entr{'y' if len(rows) == 1 else 'ies'} saved: {stock_title}.")

    # Entries of the selected month
    st.markdown(f'<div class="section-title">{stock_title}</div>',
                unsafe_allow_html=True)

    stock_all = read_table("Stock")
    entries = stock_all[stock_all["month_key"] == sk].merge(items_lookup(), on="item_id", how="left")
    entries["Stock Value"] = entries["quantity"] * entries["unit_price"]
    entries = entries.sort_values(["category", "item_name", "size"])

    if entries.empty:
        st.info("No stock entered for this month yet.")
    else:
        table = entries[["item_code", "category", "item_name", "size", "quantity", "unit_price",
                         "Stock Value", "description", "entered_by"]].rename(columns={
            "item_code": "Code", "category": "Main Category",
            "item_name": "Item", "size": "Size / Variety", "quantity": "Quantity",
            "unit_price": "Unit Price", "description": "Description", "entered_by": "Entered By",
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.markdown(
            f'<div class="card kpi-blue"><div class="kpi-label">Total Stock Value</div>'
            f'<div class="kpi-value">{money(entries["Stock Value"].sum())}</div></div>',
            unsafe_allow_html=True
        )

        with st.expander("🗑️ Delete a stock entry"):
            labels = {r["id"]: f'{r["item_code"]} • {r["item_name"]} - {size_label(r["size"])}'
                      for _, r in entries.iterrows()}
            del_id = st.selectbox("Entry", list(labels.keys()), format_func=lambda x: labels[x], key="del_stock")
            if st.button("Delete Entry", key="del_stock_btn"):
                delete_row("Stock", del_id)
                st.rerun()


# ============================================================
# PURCHASES  (table entry: pick the item, then fill one table for all its sizes)
# ============================================================
elif page == "Purchases":
    header("Monthly Purchases",
           "Record purchases made this month. Pick a category and item, then fill the table for its sizes / varieties.")

    mk = month_picker("Purchase month", "purch")
    prev = previous_month(mk)

    show_all = st.checkbox("Also show items with no stock entry in the previous month", value=False)

    stock_all = read_table("Stock")

    if show_all:
        pool = get_items()
    else:
        prev_stock = stock_all[stock_all["month_key"] == prev].merge(items_lookup(), on="item_id", how="left")
        prev_stock = prev_stock[prev_stock["active"] == 1]
        pool = prev_stock[["item_id", "item_code", "item_name", "size", "category"]] \
            .rename(columns={"item_id": "id"}).sort_values(["item_name", "size"])

    if pool.empty:
        st.warning(f"No stock was entered for {month_label(prev)}. Enter the opening stock of "
                   f"{month_label(mk)} (Stock Entry → Opening stock) or the closing stock of {month_label(prev)} first, "
                   "or tick the option above to show all items.")
    else:
        sel_cat = st.selectbox("Main category", ["All categories"] + sorted(pool["category"].unique()),
                               key="purch_cat")
        if sel_cat != "All categories":
            pool = pool[pool["category"] == sel_cat]

        names = sorted(pool["item_name"].unique())
        item_name = st.selectbox("Item", names, key=f"purch_item_{sel_cat}")

        sizes_pool = pool[pool["item_name"] == item_name].sort_values("size")
        prev_prices = stock_all[stock_all["month_key"] == prev][["item_id", "unit_price"]] \
            .rename(columns={"item_id": "id", "unit_price": "prev_price"})
        sizes_pool = sizes_pool.merge(prev_prices, on="id", how="left")  # fallback: last month's stock price

        # Suggested Unit Price = the unit price of the LATEST purchase entered for that item
        # (latest purchase date, then latest entry time). Only if the item has no purchase
        # history yet, fall back to the previous month's stock unit price.
        purch_hist = read_table("Purchases")
        purch_hist = purch_hist[purch_hist["unit_price"] > 0].sort_values(["purchase_date", "created_at"])
        latest_purch_price = purch_hist.groupby("item_id", as_index=False).tail(1)[["item_id", "unit_price"]] \
            .rename(columns={"item_id": "id", "unit_price": "latest_price"})
        sizes_pool = sizes_pool.merge(latest_purch_price, on="id", how="left")
        sizes_pool["suggest_price"] = sizes_pool["latest_price"].fillna(sizes_pool["prev_price"])

        n_rows = len(sizes_pool)
        editor_df = pd.DataFrame({
            "id": sizes_pool["id"].values,
            "Code": sizes_pool["item_code"].values,
            "Size / Variety": sizes_pool["size"].values,
            "Purchase Quantity": [float("nan")] * n_rows,
            "Unit Price (Rs.)": sizes_pool["suggest_price"].astype(float).values,
            "Description": [""] * n_rows,
        })

        y, m = int(mk[:4]), int(mk[5:7])
        first_day = date(y, m, 1)
        last_day = date(y, m, calendar.monthrange(y, m)[1])

        st.session_state.setdefault("purch_ver", 0)
        st.caption("Fill Purchase Quantity for the sizes you bought and press **Save Purchase** once - "
                   "all filled rows are saved together. Leave Quantity empty to skip a row.")

        with st.form("purchase_form", clear_on_submit=False):
            p_date = st.date_input("Purchase Date", value=first_day,
                                   min_value=first_day, max_value=last_day, key=f"pd_{mk}")
            edited = st.data_editor(
                editor_df,
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                disabled=["Code", "Size / Variety"],
                column_config={
                    "id": None,
                    "Size / Variety": st.column_config.TextColumn("Size / Variety"),
                    "Purchase Quantity": st.column_config.NumberColumn(
                        "Purchase Quantity", min_value=0.0, step=0.01, format="%.2f"),
                    "Unit Price (Rs.)": st.column_config.NumberColumn(
                        "Unit Price (Rs.)", min_value=0.0, format="%.2f"),
                    "Description": st.column_config.TextColumn("Description"),
                },
                key=f"purch_editor_{mk}_{sel_cat}_{item_name}_{show_all}_{st.session_state['purch_ver']}",
            )
            save_clicked = st.form_submit_button("Save Purchase", type="primary")

        if save_clicked:
            now = datetime.now().isoformat()
            new_rows = []
            for _, r in edited.iterrows():
                if pd.isna(r["Purchase Quantity"]) or float(r["Purchase Quantity"]) <= 0:
                    continue
                new_rows.append({
                    "id": new_id("P"), "month_key": mk, "purchase_date": p_date.isoformat(),
                    "item_id": r["id"], "quantity": float(r["Purchase Quantity"]),
                    "unit_price": 0.0 if pd.isna(r["Unit Price (Rs.)"]) else float(r["Unit Price (Rs.)"]),
                    "description": "" if pd.isna(r["Description"]) else str(r["Description"]).strip(),
                    "entered_by": user["username"], "created_at": now,
                })
            if not new_rows:
                st.error("Enter a purchase quantity greater than zero for at least one row.")
            else:
                add_rows("Purchases", new_rows)
                st.session_state["purch_ver"] += 1
                st.success(f"{len(new_rows)} purchase entr{'y' if len(new_rows) == 1 else 'ies'} saved: {item_name}.")

    st.markdown(f'<div class="section-title">Purchases in {month_label(mk)}</div>', unsafe_allow_html=True)

    purch_all = read_table("Purchases")
    plist = purch_all[purch_all["month_key"] == mk].merge(items_lookup(), on="item_id", how="left")
    plist["Total"] = plist["quantity"] * plist["unit_price"]
    plist = plist.sort_values(["purchase_date", "id"], ascending=False)

    if plist.empty:
        st.info("No purchases recorded for this month.")
    else:
        table = plist[["purchase_date", "item_code", "category", "item_name", "size", "quantity",
                       "unit_price", "Total", "description", "entered_by"]].rename(columns={
            "purchase_date": "Date", "item_code": "Code", "category": "Main Category",
            "item_name": "Item", "size": "Size / Variety",
            "quantity": "Quantity", "unit_price": "Unit Price",
            "description": "Description", "entered_by": "Entered By",
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.markdown(
            f'<div class="card kpi-green"><div class="kpi-label">Total Purchases</div>'
            f'<div class="kpi-value">{money(plist["Total"].sum())}</div></div>',
            unsafe_allow_html=True
        )

        with st.expander("🗑️ Delete a purchase"):
            labels = {r["id"]: f'{r["purchase_date"]} • {r["item_code"]} • {r["item_name"]} - {size_label(r["size"])} • {r["quantity"]:g}'
                      for _, r in plist.iterrows()}
            del_id = st.selectbox("Purchase", list(labels.keys()), format_func=lambda x: labels[x], key="del_purch")
            if st.button("Delete Purchase", key="del_purch_btn"):
                delete_row("Purchases", del_id)
                st.rerun()


# ============================================================
# SOLD QUANTITY
# ============================================================
elif page == "Sold Quantity":
    header("Sold Quantity",
           "Quantity sold = Previous month stock + This month purchases − This month stock.")

    df = compute_sold_data()

    if df is None:
        st.info("No stock has been entered yet.")
    else:
        if df.empty:
            st.info("Sold quantity needs at least two consecutive months of stock entries "
                    "(previous month and this month).")
        else:
            df_all = df.copy()  # unfiltered data, used by the PDF report below

            # ---- Filters ----
            f0, f1, f2 = st.columns([1.1, 1.3, 1.3])
            with f0:
                sel_cat = st.selectbox("Main category", ["All categories"] +
                                       sorted(df["category"].unique().tolist()), key="sales_cat")
            if sel_cat != "All categories":
                df = df[df["category"] == sel_cat]
            with f1:
                names = ["All items"] + sorted(df["item_name"].dropna().unique().tolist())
                sel_item = st.selectbox("Item", names, key=f"sales_item_{sel_cat}")
            with f2:
                if sel_item == "All items":
                    sel_size = st.selectbox("Size / Variety", ["All sizes"], disabled=True, key="sales_size_all")
                else:
                    sizes = ["All sizes"] + sorted(df.loc[df["item_name"] == sel_item, "size"].unique().tolist())
                    sel_size = st.selectbox(
                        "Size / Variety", sizes, key=f"sales_size_{sel_item}",
                        format_func=lambda s: s if s == "All sizes" else size_label(s))

            view = df.copy()
            if sel_item != "All items":
                view = view[view["item_name"] == sel_item]
                if sel_size != "All sizes":
                    view = view[view["size"] == sel_size]

            if view.empty:
                st.info("No sold quantity data for this selection.")
            else:
                trend = view.groupby("month_key", as_index=False)["sold_qty"].sum().sort_values("month_key")
                trend["Month"] = pd.to_datetime(trend["month_key"] + "-01").dt.strftime("%b %Y")
                trend = trend.rename(columns={"sold_qty": "Value"})

                total_qty = view["sold_qty"].sum()
                k1, k2 = st.columns(2)
                for k, (label, value, cls) in zip(
                    [k1, k2],
                    [("Total Quantity Sold", f"{total_qty:,.2f}", "kpi-blue"),
                     ("Months Covered", str(trend.shape[0]), "kpi-green")]
                ):
                    with k:
                        st.markdown(
                            f'<div class="card {cls}"><div class="kpi-label">{label}</div>'
                            f'<div class="kpi-value">{value}</div></div>',
                            unsafe_allow_html=True
                        )

                title = "All items" if sel_item == "All items" else (
                    sel_item if sel_size == "All sizes" else f"{sel_item} - {size_label(sel_size)}")
                if sel_cat != "All categories":
                    title = f"{sel_cat} / {title}"
                st.markdown(f'<div class="section-title">Monthly Sold Quantity: {title}</div>', unsafe_allow_html=True)

                base_chart = alt.Chart(trend).encode(
                    x=alt.X("Month:N", sort=trend["Month"].tolist(), title="Month",
                            axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("Value:Q", title="Quantity Sold"),
                )
                line = base_chart.mark_line(point=True, strokeWidth=3, color="#2563eb").encode(
                    tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Value:Q", title="Quantity Sold", format=",.2f")],
                )
                # value shown on every point
                labels = base_chart.mark_text(dy=-14, fontSize=12, fontWeight="bold", color="#172033").encode(
                    text=alt.Text("Value:Q", format=",.2f"),
                )
                chart = (line + labels).properties(height=400, padding={"top": 24, "right": 12, "left": 5, "bottom": 5}) \
                    .configure(background="#ffffff") \
                    .configure_view(fill="#ffffff", strokeWidth=0) \
                    .configure_axis(labelColor="#162033", titleColor="#162033", domainColor="#94a3b8",
                                    tickColor="#94a3b8", gridColor="#e2e8f0")
                st.altair_chart(chart, use_container_width=True, theme=None)

                st.markdown('<div class="section-title">Details</div>', unsafe_allow_html=True)
                # "Cost of Sales" (last column) = same calculation as in the PDF report / Profit Report
                table = view.sort_values(["month_key", "category", "item_name", "size"])[
                    ["month_key", "item_code", "category", "item_name", "size", "opening_qty", "opening_price",
                     "purchase_qty", "closing_qty", "unit_price", "sold_qty", "cost_of_sales"]
                ].rename(columns={
                    "month_key": "Month", "item_code": "Code", "category": "Main Category",
                    "item_name": "Item", "size": "Size / Variety",
                    "opening_qty": "Previous Stock", "opening_price": "Previous Unit Price",
                    "purchase_qty": "Purchases",
                    "closing_qty": "This Month Stock", "unit_price": "Unit Price",
                    "sold_qty": "Quantity Sold", "cost_of_sales": "Cost of Sales",
                })
                st.dataframe(table, use_container_width=True, hide_index=True)

                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    table.to_excel(writer, sheet_name="Sold Quantity", index=False)
                st.download_button(
                    "Download Excel", out.getvalue(), "sold_quantity.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            # ---- Monthly Sold Quantity Report (PDF) - all items, independent of the filters above ----
            st.markdown('<div class="section-title">Monthly Sold Quantity Report (PDF)</div>', unsafe_allow_html=True)
            report_months = sorted(df_all["month_key"].unique().tolist(), reverse=True)
            rep_mk = st.selectbox("Report month", report_months, format_func=month_label, key="report_month")
            rep = df_all[df_all["month_key"] == rep_mk]
            prev_rep = df_all[df_all["month_key"] == previous_month(rep_mk)]
            try:
                pdf_bytes = build_sales_report_pdf(rep, rep_mk, prev_rep)
                st.download_button(
                    f"📄 Download Monthly Sold Quantity Report - {month_label(rep_mk)} (PDF)",
                    pdf_bytes, f"monthly_sold_quantity_report_{rep_mk}.pdf", "application/pdf",
                    key="report_pdf_btn",
                )
            except ImportError:
                st.error("PDF export needs the `reportlab` package. Add `reportlab` to requirements.txt and reboot the app.")


# ============================================================
# OTHER EXPENSES
#   Add: Date + Expense Type (typed, with suggestions of old types) + Total
#   Table of the selected month at the bottom: edit cells, delete rows, Save Changes
#   Delete option: pick one expense entry and delete it
# ============================================================
elif page == "Other Expenses":
    header("Other Expenses",
           "Enter the other expenses (rent, salaries, electricity, ...) with their date. "
           "They are deducted in the Profit Report.")
    show_flash("exp_flash")

    mk = month_picker("Expense month", "exp")
    y, m = int(mk[:4]), int(mk[5:7])
    first_day = date(y, m, 1)
    last_day = date(y, m, calendar.monthrange(y, m)[1])

    exp_all = read_table("Expenses")
    cur_exp = exp_all[exp_all["month_key"] == mk].copy()

    # Previously entered expense types (all months) - suggested while the user types
    known_types = sorted({str(t).strip() for t in exp_all["expense_type"] if str(t).strip()},
                         key=lambda s: s.lower())
    type_case = {t.lower(): t for t in known_types}  # reuse the old spelling, e.g. "rent" -> "Rent"

    st.session_state.setdefault("exp_ver", 0)

    # ---------------- ADD AN EXPENSE ----------------
    st.markdown('<div class="section-title">Add an Expense</div>', unsafe_allow_html=True)
    st.caption("Type the expense type, or pick one of the earlier types from the list "
               "(the list narrows down as you type). A new type is saved automatically.")

    today = date.today()
    default_date = today if first_day <= today <= last_day else first_day

    with st.form("expense_add_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 1.6, 1])
        e_date = c1.date_input("Date", value=default_date, min_value=first_day, max_value=last_day,
                               key=f"exp_date_{mk}_{st.session_state['exp_ver']}")
        try:
            e_type = c2.selectbox(
                "Expense Type", known_types, index=None, accept_new_options=True,
                placeholder="Type or choose an expense type",
                key=f"exp_type_{st.session_state['exp_ver']}")
        except TypeError:  # older Streamlit without accept_new_options: plain text box
            e_type = c2.text_input("Expense Type", placeholder="Type the expense type",
                                   key=f"exp_type_txt_{st.session_state['exp_ver']}")
            if known_types:
                c2.caption("Earlier types: " + ", ".join(known_types))
        e_amt = c3.number_input("Total (Rs)", min_value=0.0, value=0.0, step=100.0, format="%.2f",
                                key=f"exp_amt_{st.session_state['exp_ver']}")
        add_clicked = st.form_submit_button("➕ Add Expense", type="primary")

    if add_clicked:
        etype = (e_type or "").strip()
        if not etype:
            st.error("Enter or choose an Expense Type.")
        elif e_amt <= 0:
            st.error("Enter a Total greater than zero.")
        else:
            etype = type_case.get(etype.lower(), etype)
            add_row("Expenses", {
                "id": new_id("E"), "month_key": f"{e_date.year}-{e_date.month:02d}",
                "expense_date": e_date.isoformat(), "expense_type": etype,
                "amount": float(e_amt), "entered_by": user["username"],
                "updated_at": datetime.now().isoformat(),
            })
            st.session_state["exp_ver"] += 1
            st.session_state["exp_flash"] = f"Expense added: {etype} - {money(e_amt)} on {e_date.isoformat()}."
            st.rerun()

    # ---------------- EXPENSES OF THE SELECTED MONTH ----------------
    st.markdown(f'<div class="section-title">Expenses in {month_label(mk)}</div>', unsafe_allow_html=True)

    if cur_exp.empty:
        st.info("No expenses saved for this month yet.")
    else:
        # old rows saved before the Date column existed show the 1st of the month
        cur_exp["expense_date"] = cur_exp["expense_date"].astype(str).str.strip()
        cur_exp["date_value"] = pd.to_datetime(cur_exp["expense_date"], errors="coerce")
        cur_exp["date_value"] = cur_exp["date_value"].fillna(pd.Timestamp(first_day))
        cur_exp = cur_exp.sort_values(["date_value", "updated_at"]).reset_index(drop=True)

        editor_df = pd.DataFrame({
            "id": cur_exp["id"].astype(str).values,
            "Date": [d.date() for d in cur_exp["date_value"]],
            "Expense Type": cur_exp["expense_type"].astype(str).values,
            "Total (Rs)": cur_exp["amount"].astype(float).values,
        })

        st.caption("Made a mistake? Change a Date, Expense Type or Total directly in the table. "
                   "To delete a record, tick the box on the left of the row and press the Delete key "
                   "(or the bin icon), then press **Save Changes**. Nothing is changed until you save.")

        with st.form("expense_edit_form"):
            edited = st.data_editor(
                editor_df,
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "id": None,
                    "Date": st.column_config.DateColumn(
                        "Date", min_value=first_day, max_value=last_day, format="YYYY-MM-DD"),
                    "Expense Type": st.column_config.TextColumn("Expense Type", required=False),
                    "Total (Rs)": st.column_config.NumberColumn(
                        "Total (Rs)", min_value=0.0, step=0.01, format="%.2f"),
                },
                key=f"exp_editor_{mk}_{st.session_state['exp_ver']}",
            )
            save_clicked = st.form_submit_button("💾 Save Changes", type="primary")

        if save_clicked:
            by_id = {r["id"]: r["entered_by"] for _, r in cur_exp.iterrows()}
            rows, errors = [], []
            for _, r in edited.iterrows():
                etype = "" if pd.isna(r["Expense Type"]) else str(r["Expense Type"]).strip()
                amt = r["Total (Rs)"]
                d = r["Date"]
                if not etype and pd.isna(amt):
                    continue  # completely empty row
                if not etype:
                    errors.append("A row has a Total but no Expense Type.")
                    continue
                if pd.isna(amt):
                    errors.append(f"'{etype}' has no Total (Rs).")
                    continue
                if pd.isna(d):
                    errors.append(f"'{etype}' has no Date.")
                    continue
                d = pd.to_datetime(d).date()
                if not (first_day <= d <= last_day):
                    errors.append(f"'{etype}': the Date must be inside {month_label(mk)}.")
                    continue
                rid = None if pd.isna(r["id"]) else str(r["id"])
                rows.append({
                    "id": rid, "expense_date": d.isoformat(),
                    "expense_type": type_case.get(etype.lower(), etype),
                    "amount": float(amt), "entered_by": by_id.get(rid) if rid else None,
                })
            if errors:
                for e in dict.fromkeys(errors):
                    st.error(e)
            else:
                save_expenses(mk, rows, user["username"])
                st.session_state["exp_ver"] += 1
                if rows:
                    st.session_state["exp_flash"] = (
                        f"Changes saved: {len(rows)} expense record{'' if len(rows) == 1 else 's'} "
                        f"in {month_label(mk)}.")
                else:
                    st.session_state["exp_flash"] = f"All expenses of {month_label(mk)} were deleted."
                st.rerun()

        st.markdown(
            f'<div class="card kpi-orange"><div class="kpi-label">Total Other Expenses</div>'
            f'<div class="kpi-value">{money(cur_exp["amount"].sum())}</div></div>',
            unsafe_allow_html=True
        )

        # ---------------- DELETE AN EXPENSE ENTRY ----------------
        with st.expander("🗑️ Delete an expense entry"):
            exp_labels = {
                r["id"]: f'{r["date_value"].date().isoformat()} • {r["expense_type"]} • {money(r["amount"])}'
                for _, r in cur_exp.iterrows()
            }
            del_exp_id = st.selectbox(
                "Expense entry", list(exp_labels.keys()), format_func=lambda x: exp_labels[x],
                key=f"del_exp_{mk}_{st.session_state['exp_ver']}")
            if st.button("Delete Entry", key=f"del_exp_btn_{mk}"):
                delete_row("Expenses", del_exp_id)
                st.session_state["exp_ver"] += 1
                st.session_state["exp_flash"] = f"Expense deleted: {exp_labels[del_exp_id]}."
                st.rerun()


# ============================================================
# MONTHLY SALES  (Cash + Card + QR payments of a month)
#   Delete option: pick one saved month and delete its sales entry
# ============================================================
elif page == "Monthly Sales":
    header("Total Monthly Sale",
           "Enter the sales of the month by payment type (Cash, Card, QR). "
           "The total is used in the Profit Report.")
    show_flash("sales_flash")

    mk = month_picker("Sales month", "msale")

    sales_all = read_table("Sales")
    hit = sales_all[sales_all["month_key"] == mk]
    if hit.empty:
        ex_cash = ex_card = ex_qr = ex_total = 0.0
    else:
        last = hit.iloc[-1]
        ex_cash, ex_card, ex_qr = float(last["cash_sales"]), float(last["card_sales"]), float(last["qr_sales"])
        ex_total = float(last["total_sales"])

    st.session_state.setdefault("sales_ver", 0)
    if hit.empty:
        st.caption(f"No sales saved for {month_label(mk)} yet.")
    elif ex_total > 0 and (ex_cash + ex_card + ex_qr) == 0:
        st.warning(f"The total sales of {month_label(mk)} ({money(ex_total)}) were saved before the Cash / Card / QR "
                   "split existed. Enter the three amounts below and save to replace that total.")
    else:
        st.caption(f"Sales of {month_label(mk)} are already saved ({money(ex_total)}). "
                   "Saving again updates these values.")

    with st.form("sales_form"):
        s1, s2, s3 = st.columns(3)
        v = st.session_state["sales_ver"]
        cash = s1.number_input("Cash Sales (Rs)", min_value=0.0, value=ex_cash, step=100.0, format="%.2f",
                               key=f"sales_cash_{mk}_{v}")
        card = s2.number_input("Card Sales (Rs)", min_value=0.0, value=ex_card, step=100.0, format="%.2f",
                               key=f"sales_card_{mk}_{v}")
        qr = s3.number_input("QR Payments (Rs)", min_value=0.0, value=ex_qr, step=100.0, format="%.2f",
                             key=f"sales_qr_{mk}_{v}")
        save_clicked = st.form_submit_button("Save Sales", type="primary")

    if save_clicked:
        total = cash + card + qr
        if total <= 0:
            st.error("Enter at least one amount (Cash, Card or QR) greater than zero.")
        else:
            save_monthly_sales(mk, cash, card, qr, user["username"])
            st.session_state["sales_ver"] += 1
            st.session_state["sales_flash"] = (
                f"Sales of {month_label(mk)} saved: Cash {money(cash)} + Card {money(card)} "
                f"+ QR {money(qr)} = Total {money(total)}.")
            st.rerun()

    if not hit.empty:
        st.markdown(
            f'<div class="card kpi-green"><div class="kpi-label">Total Sales - {month_label(mk)}</div>'
            f'<div class="kpi-value">{money(ex_total)}</div></div>',
            unsafe_allow_html=True
        )

    st.markdown('<div class="section-title">Saved Monthly Sales</div>', unsafe_allow_html=True)
    if sales_all.empty:
        st.info("No monthly sales saved yet.")
    else:
        hist = sales_all.sort_values("month_key", ascending=False).copy()
        hist["Month"] = hist["month_key"].map(month_label)
        st.dataframe(
            hist[["Month", "cash_sales", "card_sales", "qr_sales", "total_sales", "entered_by", "updated_at"]].rename(columns={
                "cash_sales": "Cash (Rs)", "card_sales": "Card (Rs)", "qr_sales": "QR (Rs)",
                "total_sales": "Total Sales (Rs)", "entered_by": "Entered By", "updated_at": "Updated At"}),
            use_container_width=True, hide_index=True,
            column_config={
                "Cash (Rs)": st.column_config.NumberColumn(format="%.2f"),
                "Card (Rs)": st.column_config.NumberColumn(format="%.2f"),
                "QR (Rs)": st.column_config.NumberColumn(format="%.2f"),
                "Total Sales (Rs)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        # ---------------- DELETE A MONTHLY SALES ENTRY ----------------
        with st.expander("🗑️ Delete a monthly sales entry"):
            sales_labels = {
                r["id"]: f'{month_label(r["month_key"])} • Cash {money(r["cash_sales"])} • '
                         f'Card {money(r["card_sales"])} • QR {money(r["qr_sales"])} • '
                         f'Total {money(r["total_sales"])}'
                for _, r in hist.iterrows()
            }
            del_sales_id = st.selectbox(
                "Sales entry", list(sales_labels.keys()), format_func=lambda x: sales_labels[x],
                key=f"del_sales_{st.session_state['sales_ver']}")
            if st.button("Delete Entry", key="del_sales_btn"):
                delete_row("Sales", del_sales_id)
                st.session_state["sales_ver"] += 1
                st.session_state["sales_flash"] = f"Sales entry deleted: {sales_labels[del_sales_id]}."
                st.rerun()


# ============================================================
# PROFIT REPORT
#   Profit = Total Sales - Total Cost of Sales - Other Expenses
# ============================================================
elif page == "Profit Report":
    header("Profit Report", "Profit = Total Sales − Total Cost of Sales − Other Expenses.")

    mk = month_picker("Report month", "profit")
    month_name = calendar.month_name[int(mk[5:7])]
    title = f"Profit Report - {month_name} {mk[:4]}"

    # Total Cost of Sales (from stock + purchases, same calculation as the Sold Quantity PDF)
    sold = compute_sold_data()
    sold_m = sold[sold["month_key"] == mk] if sold is not None else None
    cost_ok = sold_m is not None and not sold_m.empty
    cost = float(sold_m["cost_of_sales"].sum()) if cost_ok else 0.0

    # Total Sales
    sales_all = read_table("Sales")
    s_hit = sales_all[sales_all["month_key"] == mk]
    sales_ok = not s_hit.empty
    sales = float(s_hit.iloc[-1]["total_sales"]) if sales_ok else 0.0

    # Other Expenses
    exp_all = read_table("Expenses")
    exp_m = exp_all[exp_all["month_key"] == mk]
    expenses = [(str(t), float(a)) for t, a in zip(exp_m["expense_type"], exp_m["amount"])]
    other_total = sum(a for _, a in expenses)

    profit = sales - cost - other_total

    if not sales_ok:
        st.warning(f"Total sales for {month_label(mk)} are not entered yet (Monthly Sales section). "
                   "Total Sales is shown as 0.")
    if not cost_ok:
        st.warning(f"Total Cost of Sales for {month_label(mk)} cannot be calculated yet. Stock entries for "
                   f"{month_label(previous_month(mk))} and {month_label(mk)} are needed. Cost of Sales is shown as 0.")
    if not expenses:
        st.info(f"No other expenses saved for {month_label(mk)}.")

    def money_cell(v):
        return f"{float(v):,.2f}"

    rows_html = (
        f'<tr class="head"><td>Total Sales</td><td class="amt">{money_cell(sales)}</td></tr>'
        f'<tr class="head"><td>Total Cost of Sales</td><td class="amt">{money_cell(cost)}</td></tr>'
        f'<tr class="head"><td>Other Expenses</td><td class="amt">{money_cell(other_total)}</td></tr>'
    )
    for t, a in expenses:
        rows_html += f'<tr class="sub"><td>{html.escape(t)}</td><td class="amt">{money_cell(a)}</td></tr>'
    cls = "pos" if profit >= 0 else "neg"
    rows_html += f'<tr class="profit"><td>Profit</td><td class="amt {cls}">{money_cell(profit)}</td></tr>'

    st.markdown(
        f'<div class="pl-title">{html.escape(title)}</div>'
        f'<table class="pl-table"><tbody>{rows_html}</tbody></table>',
        unsafe_allow_html=True
    )

    try:
        pdf_bytes = build_profit_report_pdf(title, sales, cost, expenses, profit)
        st.download_button(f"📄 Download {title} (PDF)", pdf_bytes, f"profit_report_{mk}.pdf",
                           "application/pdf", key="profit_pdf_btn")
    except ImportError:
        st.error("PDF export needs the `reportlab` package. Add `reportlab` to requirements.txt and reboot the app.")


# ============================================================
# SETTINGS (Admin only)
# ============================================================
elif page == "Settings":
    if not is_admin:
        st.error("Only an Admin can access Settings.")
        st.stop()

    header("Settings", "Create user logins, manage items, change your password and import previous data.")

    tab1, tab2, tab3, tab4 = st.tabs(["👥 Users", "📦 Items", "🔑 My Password", "📥 Import Data"])

    # ---------------- USERS ----------------
    with tab1:
        used = normal_user_count()
        st.markdown("### Create New Login")
        st.caption(f"Active users: {used} of {MAX_STANDARD_USERS} (Admin not counted).")

        if used >= MAX_STANDARD_USERS:
            st.warning(f"The limit of {MAX_STANDARD_USERS} users is reached. "
                       "Deactivate a user to create another login.")
        else:
            with st.form("create_user", clear_on_submit=True):
                a, b = st.columns(2)
                full_name = a.text_input("Full Name *")
                username = a.text_input("Username *")
                password = b.text_input("Password *", type="password")
                confirm = b.text_input("Confirm Password *", type="password")

                if st.form_submit_button("Create User", type="primary"):
                    users_now = read_table("Users")
                    if not full_name.strip() or not username.strip() or not password:
                        st.error("Full name, username and password are required.")
                    elif len(password) < 6:
                        st.error("Password must contain at least 6 characters.")
                    elif password != confirm:
                        st.error("Passwords do not match.")
                    elif (users_now["username"].str.lower() == username.strip().lower()).any():
                        st.error("That username already exists.")
                    else:
                        add_row("Users", {
                            "id": new_id("U"), "username": username.strip(),
                            "password": hash_password(password), "full_name": full_name.strip(),
                            "role": "User", "active": 1, "created_at": datetime.now().isoformat(),
                        })
                        st.success(f"Login created for {username.strip()}.")
                        st.rerun()

        users = read_table("Users").sort_values(["role", "username"])
        users["Status"] = users["active"].map({1: "Active", 0: "Inactive"})
        st.dataframe(
            users[["username", "full_name", "role", "Status", "created_at"]].rename(columns={
                "username": "Username", "full_name": "Full Name", "role": "Role", "created_at": "Created At"}),
            use_container_width=True, hide_index=True
        )

        others = users[users["username"] != user["username"]]
        if not others.empty:
            st.markdown("### Manage User")
            labels = {r["id"]: f'{r["username"]} ({r["Status"]})' for _, r in others.iterrows()}
            sel = st.selectbox("Select user", list(labels.keys()), format_func=lambda x: labels[x], key="manage_user")
            row = others[others["id"] == sel].iloc[0]

            c1, c2 = st.columns(2)
            with c1:
                if row["Status"] == "Active":
                    if st.button("Deactivate User"):
                        update_row("Users", sel, {"active": 0})
                        st.rerun()
                else:
                    if st.button("Reactivate User"):
                        if row["role"] != "Admin" and normal_user_count() >= MAX_STANDARD_USERS:
                            st.error(f"The limit of {MAX_STANDARD_USERS} active users is reached.")
                        else:
                            update_row("Users", sel, {"active": 1})
                            st.rerun()
            with c2:
                with st.form("reset_pw", clear_on_submit=True):
                    new_pw = st.text_input("New password for selected user", type="password")
                    if st.form_submit_button("Reset Password"):
                        if len(new_pw) < 6:
                            st.error("Password must contain at least 6 characters.")
                        else:
                            update_row("Users", sel, {"password": hash_password(new_pw)})
                            st.success("Password reset.")

    # ---------------- ITEMS ----------------
    with tab2:
        st.markdown("### Item Master")
        add_item_ui("settings_add")

        all_items = read_table("Items").sort_values(["category", "item_name", "size"])
        all_items["Status"] = all_items["active"].map({1: "Active", 0: "Inactive"})
        st.dataframe(
            all_items[["item_code", "category", "item_name", "size", "Status"]].rename(
                columns={"item_code": "Code", "category": "Main Category",
                         "item_name": "Item", "size": "Size / Variety"}),
            use_container_width=True, hide_index=True
        )

        if not all_items.empty:
            labels = {r["id"]: f'{r["item_code"]} • {r["item_name"]} - {size_label(r["size"])} ({r["Status"]})'
                      for _, r in all_items.iterrows()}
            sel_i = st.selectbox("Select item", list(labels.keys()), format_func=lambda x: labels[x], key="manage_item")
            is_active = int(all_items[all_items["id"] == sel_i].iloc[0]["active"]) == 1
            if st.button("Deactivate Item" if is_active else "Reactivate Item"):
                update_row("Items", sel_i, {"active": 0 if is_active else 1})
                st.rerun()
            st.caption("Inactive items are hidden from selection lists; past records and sold quantity history are kept.")

    # ---------------- MY PASSWORD ----------------
    with tab3:
        st.markdown("### Change My Password")
        old = st.text_input("Current Password", type="password")
        new = st.text_input("New Password", type="password")
        confirm = st.text_input("Confirm New Password", type="password")

        if st.button("Change Password", type="primary"):
            users_now = read_table("Users")
            current = users_now[users_now["id"] == user["id"]]
            if current.empty or not verify_password(old, current.iloc[0]["password"]):
                st.error("Current password is incorrect.")
            elif len(new) < 6:
                st.error("New password must contain at least 6 characters.")
            elif new != confirm:
                st.error("New passwords do not match.")
            else:
                update_row("Users", user["id"], {"password": hash_password(new)})
                st.success("Password changed successfully.")

    # ---------------- IMPORT DATA ----------------
    with tab4:
        st.markdown("### Import previous data")
        st.caption(
            f"Paste your sheet into a tab named **{IMPORT_TAB}** in the Google Sheet "
            "(columns: Item Code | Main Category | Item | Size | then the month groups such as "
            "'Opening Stock (April 2026)', 'Purchases (April 2026)', 'Closing Stock (April 2026)'; "
            "row 2 = Qty / Unit Price / Total; data from row 3). Then read and check it here."
        )
        if st.button(f"➕ Create the {IMPORT_TAB} tab with headers"):
            if create_import_tab():
                st.success(f"Tab {IMPORT_TAB} created. Open your Google Sheet and paste your data from row 3 "
                           "(columns A-D: Item Code, Main Category, Item, Size; then Qty / Unit Price / Total).")
            else:
                st.info(f"The {IMPORT_TAB} tab already exists.")

        if st.button("🔍 Read & check Rest_Import"):
            try:
                st.session_state["imp"] = parse_import_tab()
            except gspread.exceptions.WorksheetNotFound:
                st.session_state.pop("imp", None)
                st.error(f"Create a tab named exactly {IMPORT_TAB} in your Google Sheet first.")

        imp = st.session_state.get("imp")
        if imp and imp.get("error"):
            st.error(imp["error"])
        elif imp:
            k1, k2, k3 = st.columns(3)
            k1.metric("Items found", len(imp["items"]))
            k2.metric("Stock records", len(imp["stock"]))
            k3.metric("Purchase records", len(imp["purchases"]))
            if imp["issues"]:
                st.warning(f"{len(imp['issues'])} rows need a look. Fix them in {IMPORT_TAB} and read again, "
                           "or import anyway.")
                st.dataframe(pd.DataFrame(imp["issues"]), use_container_width=True, hide_index=True)
            else:
                st.success("All checks passed.")
            if st.button("✅ Import now", type="primary"):
                n_i, n_s, n_p, n_t = run_import(imp, user["username"])
                st.session_state.pop("imp", None)
                st.success(f"Imported {n_i} new items, {n_s} stock records (new or updated with Totals), "
                           f"{n_p} new purchases. Totals added to {n_t} existing purchases.")
