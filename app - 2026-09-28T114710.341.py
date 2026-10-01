import streamlit as st
import pandas as pd
import altair as alt
import gspread
import hashlib
import hmac
import secrets
import calendar
import io
from datetime import date, datetime
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

# ============================================================
# RESTAURANT INVENTORY & SALES PERFORMANCE SYSTEM
# Storage: Google Sheets only (no local database / CSV)
#
#   Stock Entry       : month-end stock (item, size, qty, unit price, description)
#   Purchases         : purchases of the month (from previous month's stock items)
#   Sales Performance : Sold = Previous month stock + Purchases - This month stock
#   Settings          : admin creates / manages user logins
# ============================================================

st.set_page_config(
    page_title="Restaurant Inventory",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

MAX_STANDARD_USERS = 3  # 1 Admin + up to 3 normal users
CACHE_SECONDS = 20      # how long sheet data is cached (protects the Google API quota)

# ------------------------- THEME ----------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: Inter, sans-serif; }
.stApp { background: #f3f6fa; }
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

div[data-baseweb="input"] > div, div[data-baseweb="select"] > div, textarea { border-radius: 8px !important; }
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ------------------------- GOOGLE SHEETS --------------------
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

TABLES = {
    "Users": ["id", "username", "password", "full_name", "role", "active", "created_at"],
    "Items": ["id", "item_name", "size", "active"],
    "Stock": ["id", "month_key", "item_id", "quantity", "unit_price",
              "description", "entered_by", "updated_at"],
    "Purchases": ["id", "month_key", "purchase_date", "item_id", "quantity", "unit_price",
                  "description", "entered_by", "created_at"],
}
NUMERIC_COLS = ["quantity", "unit_price"]

# Tabs are created as Rest_Users, Rest_Items, Rest_Stock, Rest_Purchases so they never
# clash with tabs from your other apps if you reuse the same Google Sheet file.
TAB_PREFIX = "Rest_"


@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_worksheets():
    """Connect once, create any missing worksheet tabs and their header rows."""
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    sh = gspread.authorize(creds).open_by_key(st.secrets["sheet_id"])
    # Google Sheets tab names are case-insensitive, so match that way
    existing = {ws.title.strip().lower(): ws for ws in sh.worksheets()}

    result = {}
    for name, headers in TABLES.items():
        title = TAB_PREFIX + name
        ws = existing.get(title.lower())
        if ws is None:
            ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(headers, value_input_option="RAW")
        elif [h.strip() for h in first_row[:len(headers)]] != headers:
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
    return v


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def read_table(name):
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
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    if "active" in df.columns:
        df["active"] = pd.to_numeric(df["active"], errors="coerce").fillna(0).astype(int)
    return df


def new_id(prefix):
    return f"{prefix}-{secrets.token_hex(4)}"


def add_row(name, data):
    ws = get_worksheets()[name]
    row = [_clean(data.get(h, "")) for h in TABLES[name]]
    ws.append_row(row, value_input_option="RAW")
    read_table.clear()


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
    read_table.clear()
    return True


def delete_row(name, row_id):
    ws = get_worksheets()[name]
    ids = ws.col_values(1)
    if row_id in ids:
        ws.delete_rows(ids.index(row_id) + 1)
    read_table.clear()


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
    read_table.clear()


def save_stock_batch(month_key, rows, entered_by):
    """
    Save many stock entries at once (max 3 API calls, however many rows).
    rows: list of dicts with item_id, quantity, unit_price, description.
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
        if key in sheet_row:
            n = sheet_row[key]
            # columns D..H = quantity, unit_price, description, entered_by, updated_at
            updates.append({
                "range": f"D{n}:H{n}",
                "values": [[float(r["quantity"]), float(r["unit_price"]),
                            r["description"], entered_by, now]],
            })
        else:
            new_rows.append([
                new_id("S"), month_key, r["item_id"], float(r["quantity"]),
                float(r["unit_price"]), r["description"], entered_by, now,
            ])

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if new_rows:
        ws.append_rows(new_rows, value_input_option="RAW")
    read_table.clear()


# Connect now and show a friendly message if setup is incomplete
try:
    get_worksheets()
except KeyError as e:
    st.error(f"Missing Streamlit secret: {e}. Add `sheet_id` and `[gcp_service_account]` "
             "to .streamlit/secrets.toml (see the setup notes).")
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
    return df[df["active"] == 1][["id", "item_name", "size"]].sort_values(["item_name", "size"])


def items_lookup():
    """Items renamed so 'id' becomes 'item_id' (for merging with Stock / Purchases)."""
    df = read_table("Items")
    return df.rename(columns={"id": "item_id"})[["item_id", "item_name", "size", "active"]]


def pick_item(pool, key):
    """Two-step selector: Item, then Size / Variety. Returns (item_id, item_name, size)."""
    names = sorted(pool["item_name"].unique())
    c1, c2 = st.columns(2)
    with c1:
        name = st.selectbox("Item", names, key=f"{key}_name")
    sizes = pool[pool["item_name"] == name].sort_values("size")
    lookup = dict(zip(sizes["id"], sizes["size"]))
    with c2:
        item_id = st.selectbox(
            "Size / Variety", list(lookup.keys()),
            format_func=lambda x: size_label(lookup[x]), key=f"{key}_size_{name}"
        )
    return item_id, name, lookup[item_id]


def item_exists(name, size):
    df = read_table("Items")
    hit = df[(df["item_name"].str.lower() == name.strip().lower()) &
             (df["size"].str.lower() == size.strip().lower())]
    return hit


def add_item_ui(key):
    """Add an item and its sizes / varieties in one go, using a table.
    Sizes are OPTIONAL: leave the table empty for an item that has no size / variety."""
    ver_key = f"{key}_ver"
    st.session_state.setdefault(ver_key, 0)

    with st.form(f"{key}_form", clear_on_submit=True):
        name = st.text_input("Item name *", placeholder="Water")
        st.caption("List its sizes / varieties below. Click the empty bottom row to add more rows. "
                   "**Leave the table empty if this item has no size / variety.**")
        sizes_df = st.data_editor(
            pd.DataFrame({"Size / Variety": ["", "", ""]}),
            num_rows="dynamic", hide_index=True, use_container_width=True,
            key=f"{key}_sizes_{st.session_state[ver_key]}",
        )
        submitted = st.form_submit_button("Save Item & Sizes", type="primary")

    if submitted:
        sizes, seen = [], set()
        for s in sizes_df["Size / Variety"].fillna("").astype(str):
            s = s.strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                sizes.append(s)

        if not name.strip():
            st.error("Item name is required.")
        else:
            if not sizes:
                sizes = [""]  # item without any size / variety
            items_df = read_table("Items")
            taken = set(
                items_df.loc[items_df["item_name"].str.lower() == name.strip().lower(), "size"]
                .str.strip().str.lower()
            )
            to_add = [s for s in sizes if s.lower() not in taken]
            skipped = [s for s in sizes if s.lower() in taken]

            if to_add:
                add_rows("Items", [
                    {"id": new_id("I"), "item_name": name.strip(), "size": s, "active": 1}
                    for s in to_add
                ])
                st.session_state[ver_key] += 1
                st.success(f"Added {name.strip()}: {', '.join(size_label(s) for s in to_add)}.")
            if skipped:
                st.warning(f"Already exist (skipped, may be inactive): "
                           f"{', '.join(size_label(s) for s in skipped)}.")


def header(title, subtitle):
    st.markdown(f'<div class="page-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def normal_user_count():
    u = read_table("Users")
    return int(((u["role"] != "Admin") & (u["active"] == 1)).sum())


# ------------------------- AUTHENTICATION -------------------
def registration_exists():
    return len(read_table("Users")) > 0


def registration_page():
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
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown('<div class="login-logo">🍽️ Restaurant Inventory</div>', unsafe_allow_html=True)
        st.markdown('<div class="login-caption">Monthly stock, purchases & sales performance</div>',
                    unsafe_allow_html=True)

        username = st.text_input("Username", placeholder="Enter username")
        password = st.text_input("Password", type="password", placeholder="Enter password")

        if st.button("Sign In", type="primary", use_container_width=True):
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

st.sidebar.markdown('<div class="sidebar-brand">🍽️ Restaurant</div>', unsafe_allow_html=True)
st.sidebar.markdown('<div class="sidebar-sub">Inventory & Sales Performance</div>', unsafe_allow_html=True)
st.sidebar.markdown(f"""
<div class="user-chip">
    <div class="user-name">{user["full_name"]}</div>
    <div class="user-role">{user["role"]} • @{user["username"]}</div>
</div>
""", unsafe_allow_html=True)

menu = ["Stock Entry", "Purchases", "Sales Performance"]
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

        item_names = ["All items"] + sorted(items["item_name"].unique().tolist())
        sel_item = st.selectbox("Item", item_names, key="stock_item_sel")

        pool = items if sel_item == "All items" else items[items["item_name"] == sel_item]
        pool = pool.rename(columns={"id": "item_id"})

        cur = stock_all[stock_all["month_key"] == sk][["item_id", "quantity", "unit_price", "description"]]
        prv = stock_all[stock_all["month_key"] == prev][["item_id", "unit_price"]] \
            .rename(columns={"unit_price": "prev_price"})

        base = pool.merge(cur, on="item_id", how="left").merge(prv, on="item_id", how="left")
        base["unit_price"] = base["unit_price"].fillna(base["prev_price"])  # suggest last month's price
        base["description"] = base["description"].fillna("")
        base = base.sort_values(["item_name", "size"])

        editor_df = pd.DataFrame({
            "item_id": base["item_id"].values,
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
                disabled=["Item", "Size / Variety"],
                column_config={
                    "item_id": None,
                    "Quantity": st.column_config.NumberColumn(
                        "Quantity (opening stock)" if is_opening else "Quantity (closing stock)",
                        min_value=0.0, step=1.0),
                    "Unit Price": st.column_config.NumberColumn("Unit Price (Rs.)", min_value=0.0, format="%.2f"),
                    "Description": st.column_config.TextColumn("Description"),
                },
                key=f"stock_editor_{sk}_{sel_item}_{st.session_state['stock_ver']}",
            )
            save_clicked = st.form_submit_button("Save Stock", type="primary")

        if save_clicked:
            rows = []
            for _, r in edited.iterrows():
                if pd.isna(r["Quantity"]):
                    continue
                rows.append({
                    "item_id": r["item_id"],
                    "quantity": float(r["Quantity"]),
                    "unit_price": 0.0 if pd.isna(r["Unit Price"]) else float(r["Unit Price"]),
                    "description": "" if pd.isna(r["Description"]) else str(r["Description"]).strip(),
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
    entries = entries.sort_values(["item_name", "size"])

    if entries.empty:
        st.info("No stock entered for this month yet.")
    else:
        table = entries[["item_name", "size", "quantity", "unit_price", "Stock Value",
                         "description", "entered_by"]].rename(columns={
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
            labels = {r["id"]: f'{r["item_name"]} - {size_label(r["size"])}' for _, r in entries.iterrows()}
            del_id = st.selectbox("Entry", list(labels.keys()), format_func=lambda x: labels[x], key="del_stock")
            if st.button("Delete Entry", key="del_stock_btn"):
                delete_row("Stock", del_id)
                st.rerun()


# ============================================================
# PURCHASES  (table entry: pick the item, then fill one table for all its sizes)
# ============================================================
elif page == "Purchases":
    header("Monthly Purchases",
           "Record purchases made this month. Pick an item, then fill the table for its sizes / varieties.")

    mk = month_picker("Purchase month", "purch")
    prev = previous_month(mk)

    show_all = st.checkbox("Also show items with no stock entry in the previous month", value=False)

    stock_all = read_table("Stock")

    if show_all:
        pool = get_items()
    else:
        prev_stock = stock_all[stock_all["month_key"] == prev].merge(items_lookup(), on="item_id", how="left")
        prev_stock = prev_stock[prev_stock["active"] == 1]
        pool = prev_stock[["item_id", "item_name", "size"]].rename(columns={"item_id": "id"}) \
            .sort_values(["item_name", "size"])

    if pool.empty:
        st.warning(f"No stock was entered for {month_label(prev)}. Enter the opening stock of "
                   f"{month_label(mk)} (Stock Entry → Opening stock) or the closing stock of {month_label(prev)} first, "
                   "or tick the option above to show all items.")
    else:
        names = sorted(pool["item_name"].unique())
        item_name = st.selectbox("Item", names, key="purch_item")

        sizes_pool = pool[pool["item_name"] == item_name].sort_values("size")
        prev_prices = stock_all[stock_all["month_key"] == prev][["item_id", "unit_price"]] \
            .rename(columns={"item_id": "id", "unit_price": "prev_price"})
        sizes_pool = sizes_pool.merge(prev_prices, on="id", how="left")  # suggest last month's price

        n_rows = len(sizes_pool)
        editor_df = pd.DataFrame({
            "id": sizes_pool["id"].values,
            "Size / Variety": sizes_pool["size"].values,
            "Purchase Quantity": [float("nan")] * n_rows,
            "Unit Price (Rs.)": sizes_pool["prev_price"].astype(float).values,
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
                disabled=["Size / Variety"],
                column_config={
                    "id": None,
                    "Size / Variety": st.column_config.TextColumn("Size / Variety"),
                    "Purchase Quantity": st.column_config.NumberColumn(
                        "Purchase Quantity", min_value=0.0, step=1.0),
                    "Unit Price (Rs.)": st.column_config.NumberColumn(
                        "Unit Price (Rs.)", min_value=0.0, format="%.2f"),
                    "Description": st.column_config.TextColumn("Description"),
                },
                key=f"purch_editor_{mk}_{item_name}_{show_all}_{st.session_state['purch_ver']}",
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
        table = plist[["purchase_date", "item_name", "size", "quantity", "unit_price", "Total",
                       "description", "entered_by"]].rename(columns={
            "purchase_date": "Date", "item_name": "Item", "size": "Size / Variety",
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
            labels = {r["id"]: f'{r["purchase_date"]} • {r["item_name"]} - {size_label(r["size"])} • {r["quantity"]:g}'
                      for _, r in plist.iterrows()}
            del_id = st.selectbox("Purchase", list(labels.keys()), format_func=lambda x: labels[x], key="del_purch")
            if st.button("Delete Purchase", key="del_purch_btn"):
                delete_row("Purchases", del_id)
                st.rerun()


# ============================================================
# SALES PERFORMANCE
# ============================================================
elif page == "Sales Performance":
    header("Sales Performance",
           "Quantity sold = Previous month stock + This month purchases − This month stock. "
           "Sales value = Quantity sold × this month's unit price.")

    stock = read_table("Stock")[["month_key", "item_id", "quantity", "unit_price"]] \
        .rename(columns={"quantity": "closing_qty"})
    purch = read_table("Purchases").groupby(["month_key", "item_id"], as_index=False)["quantity"].sum() \
        .rename(columns={"quantity": "purchase_qty"})
    items_all = items_lookup()[["item_id", "item_name", "size"]]

    if stock.empty:
        st.info("No stock has been entered yet.")
    else:
        stock["prev_key"] = stock["month_key"].map(previous_month)
        prev_stock = stock[["month_key", "item_id", "closing_qty"]].rename(
            columns={"month_key": "prev_key", "closing_qty": "opening_qty"}
        )

        df = stock.merge(prev_stock, on=["prev_key", "item_id"], how="left")
        # Only months where the previous month's stock exists can be calculated
        df = df[df["prev_key"].isin(set(stock["month_key"]))].copy()
        df["opening_qty"] = df["opening_qty"].fillna(0.0)
        df = df.merge(purch, on=["month_key", "item_id"], how="left")
        df["purchase_qty"] = df["purchase_qty"].fillna(0.0)
        df = df.merge(items_all, on="item_id", how="left")

        df["sold_qty"] = df["opening_qty"] + df["purchase_qty"] - df["closing_qty"]
        df["sales_value"] = df["sold_qty"] * df["unit_price"]

        if df.empty:
            st.info("Sales need at least two consecutive months of stock entries "
                    "(previous month and this month).")
        else:
            # ---- Filters ----
            f1, f2, f3 = st.columns([1.3, 1.3, 1.4])
            with f1:
                names = ["All items"] + sorted(df["item_name"].dropna().unique().tolist())
                sel_item = st.selectbox("Item", names, key="sales_item")
            with f2:
                if sel_item == "All items":
                    sel_size = st.selectbox("Size / Variety", ["All sizes"], disabled=True, key="sales_size_all")
                else:
                    sizes = ["All sizes"] + sorted(df.loc[df["item_name"] == sel_item, "size"].unique().tolist())
                    sel_size = st.selectbox(
                        "Size / Variety", sizes, key=f"sales_size_{sel_item}",
                        format_func=lambda s: s if s == "All sizes" else size_label(s))
            with f3:
                metric = st.radio("Chart shows", ["Total Sales (Rs.)", "Quantity Sold"],
                                  horizontal=True, key="sales_metric")

            view = df.copy()
            if sel_item != "All items":
                view = view[view["item_name"] == sel_item]
                if sel_size != "All sizes":
                    view = view[view["size"] == sel_size]

            if view.empty:
                st.info("No sales data for this selection.")
            else:
                col = "sales_value" if metric.startswith("Total") else "sold_qty"

                trend = view.groupby("month_key", as_index=False)[col].sum().sort_values("month_key")
                trend["Month"] = pd.to_datetime(trend["month_key"] + "-01").dt.strftime("%b %Y")
                trend = trend.rename(columns={col: "Value"})

                total_sales = view["sales_value"].sum()
                total_qty = view["sold_qty"].sum()
                k1, k2, k3 = st.columns(3)
                for k, (label, value, cls) in zip(
                    [k1, k2, k3],
                    [("Total Sales", money(total_sales), "kpi-orange"),
                     ("Total Quantity Sold", f"{total_qty:,.2f}", "kpi-blue"),
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
                st.markdown(f'<div class="section-title">Monthly Sales: {title}</div>', unsafe_allow_html=True)

                chart = (
                    alt.Chart(trend)
                    .mark_line(point=True, strokeWidth=3, color="#2563eb")
                    .encode(
                        x=alt.X("Month:N", sort=trend["Month"].tolist(), title="Month",
                                axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("Value:Q", title=metric),
                        tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Value:Q", title=metric, format=",.2f")],
                    )
                    .properties(height=400)
                )
                st.altair_chart(chart, use_container_width=True)

                if (view["sold_qty"] < 0).any():
                    st.warning("Some rows have a negative quantity sold. "
                               "Check the stock or purchase entries for those items.")

                st.markdown('<div class="section-title">Details</div>', unsafe_allow_html=True)
                table = view.sort_values(["month_key", "item_name", "size"])[
                    ["month_key", "item_name", "size", "opening_qty", "purchase_qty",
                     "closing_qty", "sold_qty", "unit_price", "sales_value"]
                ].rename(columns={
                    "month_key": "Month", "item_name": "Item", "size": "Size / Variety",
                    "opening_qty": "Previous Stock", "purchase_qty": "Purchases",
                    "closing_qty": "This Month Stock", "sold_qty": "Quantity Sold",
                    "unit_price": "Unit Price", "sales_value": "Sales Value",
                })
                st.dataframe(table, use_container_width=True, hide_index=True)

                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    table.to_excel(writer, sheet_name="Sales Performance", index=False)
                st.download_button(
                    "Download Excel", out.getvalue(), "sales_performance.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )


# ============================================================
# SETTINGS (Admin only)
# ============================================================
elif page == "Settings":
    if not is_admin:
        st.error("Only an Admin can access Settings.")
        st.stop()

    header("Settings", "Create user logins, manage items and change your password.")

    tab1, tab2, tab3 = st.tabs(["👥 Users", "📦 Items", "🔑 My Password"])

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

        all_items = read_table("Items").sort_values(["item_name", "size"])
        all_items["Status"] = all_items["active"].map({1: "Active", 0: "Inactive"})
        st.dataframe(
            all_items[["item_name", "size", "Status"]].rename(
                columns={"item_name": "Item", "size": "Size / Variety"}),
            use_container_width=True, hide_index=True
        )

        if not all_items.empty:
            labels = {r["id"]: f'{r["item_name"]} - {size_label(r["size"])} ({r["Status"]})'
                      for _, r in all_items.iterrows()}
            sel_i = st.selectbox("Select item", list(labels.keys()), format_func=lambda x: labels[x], key="manage_item")
            is_active = int(all_items[all_items["id"] == sel_i].iloc[0]["active"]) == 1
            if st.button("Deactivate Item" if is_active else "Reactivate Item"):
                update_row("Items", sel_i, {"active": 0 if is_active else 1})
                st.rerun()
            st.caption("Inactive items are hidden from selection lists; past records and sales history are kept.")

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
