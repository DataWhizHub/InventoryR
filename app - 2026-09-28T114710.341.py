"""
Restaurant Inventory Management System  (Streamlit)

Monthly cycle
  1. Record purchases through the month            -> "Purchases"
  2. At month end count what is left on the shelf   -> "Month-End Stock Take"
  3. Read the report: Opening + Purchases - Closing = SOLD (qty and value)
  4. Next month's Opening stock = this month's Closing stock (automatic)

Storage: Google Sheets ONLY (no local files). Tabs items / purchases / counts / openings / users
are created automatically in the Sheet.

Streamlit secrets (.streamlit/secrets.toml, or the "Secrets" box on Streamlit Cloud):
    [gcp_service_account]
    type = "service_account"
    project_id = "..."
    private_key_id = "..."
    private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
    client_email = "...@...iam.gserviceaccount.com"
    client_id = "..."
    token_uri = "https://oauth2.googleapis.com/token"
    # sheet_id = "..."           <- optional, overrides SHEET_ID below
    # registration_code = "..."  <- optional, required to register
The Google Sheet must be shared with client_email as EDITOR.
"""
import hashlib
import hmac
import io
import os
import re
import secrets as pysecrets
import time
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Restaurant Inventory", page_icon="🍽️", layout="wide")

# Your Google Sheet (the long id in its URL). Not a secret, but the service-account key IS - keep it in st.secrets.
SHEET_ID = "12KVW70mON33I_51l8hlYCmQaarxGdqcOAtCjIVp8Gr4"

SCHEMA = {
    "items": {"item": "str", "group": "str", "size": "str", "category": "str", "unit": "str",
              "sell_price": "num"},
    "users": {"username": "str", "role": "str", "salt": "str", "hash": "str", "created": "str"},
    "sessions": {"token_hash": "str", "username": "str", "expires": "str"},
    "purchases": {"date": "str", "month": "str", "item": "str", "qty": "num",
                  "unit_price": "num", "supplier": "str", "note": "str", "entered_by": "str"},
    "counts": {"month": "str", "item": "str", "closing_qty": "num", "counted_by": "str"},
    "openings": {"month": "str", "item": "str", "qty": "num", "unit_price": "num"},
}


# ───────────────────────────── helpers ─────────────────────────────
def secrets_has(key):
    try:
        return key in st.secrets
    except Exception:
        return False


def clean(table, df):
    """Force the right columns / types on a table."""
    df = df.copy()
    for col, kind in SCHEMA[table].items():
        if col not in df.columns:
            df[col] = None
        if kind == "num":
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
        else:
            df[col] = df[col].fillna("").astype(str).str.strip()
    df = df[list(SCHEMA[table])]
    key = "item" if "item" in df.columns else "username" if "username" in df.columns else None
    if key:
        df = df[df[key] != ""]
    return df.reset_index(drop=True)


# ───────────────────────────── storage ─────────────────────────────
class GSheetStore:
    label = "Google Sheets"

    def __init__(self):
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"],
        )
        self.gspread = gspread
        self.book = gspread.authorize(creds).open_by_key(st.secrets["sheet_id"] if secrets_has("sheet_id") else SHEET_ID)
        self._sheets = {}

    def _retry(self, fn, tries=4):
        for i in range(tries):
            try:
                return fn()
            except self.gspread.exceptions.APIError:
                if i == tries - 1:
                    raise
                time.sleep(2 ** i)              # back off on quota / temporary errors

    def _ws(self, t):
        if t not in self._sheets:
            try:
                ws = self._retry(lambda: self.book.worksheet(t))
            except self.gspread.WorksheetNotFound:
                ws = self._retry(lambda: self.book.add_worksheet(title=t, rows=1000, cols=len(SCHEMA[t])))
            self._sheets[t] = ws
        return self._sheets[t]

    def read(self, t):
        values = self._retry(lambda: self._ws(t).get_all_values())
        if len(values) < 2:
            return pd.DataFrame(columns=list(SCHEMA[t]))
        return pd.DataFrame(values[1:], columns=values[0])

    def write(self, t, df):
        ws = self._ws(t)
        out = df.astype(object).where(df.notna(), "")
        rows = [list(df.columns)] + out.values.tolist()

        def _do():
            ws.clear()
            ws.update(range_name="A1", values=rows, value_input_option="RAW")

        self._retry(_do)


@st.cache_resource
def get_store():
    if not secrets_has("gcp_service_account"):
        raise RuntimeError("[gcp_service_account] is missing from Streamlit secrets.")
    return GSheetStore()


@st.cache_data(ttl=120, show_spinner=False)
def _load(t):
    return clean(t, get_store().read(t))


def load(t):
    return _load(t).copy()


def save(t, df):
    get_store().write(t, clean(t, df))
    _load.clear()
    st.session_state["ver"] = st.session_state.get("ver", 0) + 1


def ver():
    return st.session_state.get("ver", 0)


# ───────────────────────────── calculation engine ─────────────────────────────
def baseline_month():
    o = load("openings")
    return None if o.empty else o["month"].min()


def available_months():
    first = baseline_month()
    if not first:
        return []
    last = max(date.today().strftime("%Y-%m"), load("counts")["month"].max() or "")
    return [str(p) for p in pd.period_range(first, last, freq="M")]


def compute(upto):
    """
    One row per item per month, from the opening-stock month up to `upto`.
    Sold = Opening + Purchases - Closing.  Value uses the weighted-average cost
    of (opening stock + that month's purchases).
    """
    items, purchases = load("items"), load("purchases")
    counts, openings = load("counts"), load("openings")
    if openings.empty or not upto:
        return pd.DataFrame()

    first = openings["month"].min()
    months = [str(p) for p in pd.period_range(first, upto, freq="M")]
    openings = openings[openings["month"] == first]
    purchases = purchases.assign(qty=purchases["qty"].fillna(0),
                                 unit_price=purchases["unit_price"].fillna(0))
    purchases["value"] = purchases["qty"] * purchases["unit_price"]
    last_price = purchases.sort_values("date").groupby("item")["unit_price"].last().to_dict()

    state = {r.item: (0.0 if pd.isna(r.qty) else r.qty, 0.0 if pd.isna(r.unit_price) else r.unit_price)
             for r in openings.itertuples()}
    meta = items.set_index("item")
    rows = []
    for m in months:
        pm = purchases[purchases["month"] == m].groupby("item").agg(pq=("qty", "sum"), pv=("value", "sum"))
        cm = counts[counts["month"] == m].set_index("item")["closing_qty"].dropna()
        month_closed = len(cm) > 0
        for item in items["item"]:
            oq, oc = state.get(item, (0.0, 0.0))
            pq, pv = (pm.loc[item, "pq"], pm.loc[item, "pv"]) if item in pm.index else (0.0, 0.0)
            avail = oq + pq
            cost = (oq * oc + pv) / avail if avail > 0 else (oc or last_price.get(item, 0.0))
            counted = item in cm.index
            if counted:
                cq, status = float(cm[item]), "Counted"
            elif avail == 0:
                cq, status = 0.0, "Counted"
            elif month_closed:
                cq, status = None, "Not counted"
            else:
                cq, status = None, "Open month"
            sold = None if cq is None else avail - cq
            if sold is not None and sold < -1e-9:
                status = "Check: count > stock"
            sp = meta.loc[item, "sell_price"]
            rows.append({
                "month": m, "item": item, "group": meta.loc[item, "group"] or item, "size": meta.loc[item, "size"],
                "category": meta.loc[item, "category"], "unit": meta.loc[item, "unit"],
                "open_qty": oq, "open_value": oq * oc, "purch_qty": pq, "purch_value": pv,
                "available": avail, "avg_cost": cost, "closing_qty": cq,
                "closing_value": None if cq is None else cq * cost,
                "sold_qty": sold, "sold_value": None if sold is None else sold * cost,
                "sell_price": sp,
                "sales_value": sold * sp if (sold is not None and pd.notna(sp) and sp > 0) else None,
                "status": status,
            })
            state[item] = ((avail if cq is None else cq), cost)
    df = pd.DataFrame(rows)
    df["margin"] = df["sales_value"] - df["sold_value"]
    return df


# ───────────────────────────── legacy Excel importer ─────────────────────────────
SIZE_RE = re.compile(r"\s+(\d+(?:\.\d+)?\s*(?:ml|l|g|kg)|small|medium|large)$", re.I)


def split_group_size(name):
    """'Water 1.5ml' -> ('Water', '1.5ml');  'Butter' -> ('Butter', '')"""
    m = SIZE_RE.search(name)
    return (name[:m.start()].strip(), m.group(1).strip()) if m else (name, "")


MONTH_NUM = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun",
                                          "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

CATEGORY_RULES = [
    ("Beverages", ["water", "coca", "sprite", "egb", "soda", "tonic", "ginger ale", "pepsi", "7up",
                   "redbull", "aloe", "ole ", "fyre", "nescafe bottle"]),
    ("Tea & Coffee", ["coffee", "tea", "nescafe", "nestea", "n.cafe", "n.tea"]),
    ("Dairy & Desserts", ["watalappan", "kalkiri", "yougurt", "curd", "jelly", "milk", "cheese", "butter",
                          "ice cream", "chocolate", "strawberry", "fruit & nut", "toping", "ghee"]),
    ("Sauces & Pastes", ["sauce", "paste", "chutney", "mustard cream", "mayonise", "ketchup", "oyster",
                         "vinegar", "stock powder", "rose water", "soya"]),
    ("Spices", ["snoring", "cinnamon", "cardamom", "cloves", "mustard seeds", "uluhal", "chilie", "turmeric",
                "pepper", "curry", "roast", "masala", "biriyani", "papadam"]),
    ("Dry Goods", ["rice", "kekulu", "samba", "basmathi", "dhal", "sugar", "salt", "noodle", "pasta",
                   "spagathie", "soyameat", "flour", "hoppers", "biscuit", "oil can", "peas"]),
    ("Frozen & Snacks", ["roll", "cutlet", "french fries", "kottu", "bread", "bun", "sausage", "drumstick"]),
    ("Meat & Seafood", ["buriyani", "chicken", "beef", "pork", "mutton", "fish", "prawn", "cuttlefish",
                        "seafood", "portion", "r/c"]),
    ("Vegetables & Eggs", ["onion", "garlic", "potato", "mushroom", "carrot", "leeks", "cabbage", "tomato",
                           "chillie", "cucumber", "capcicum", "minchi", "salad", "coriander", "bellpaper",
                           "beans", "egg"]),
    ("Packaging & Cleaning", ["grocery", "shoping", "lunch sheet", "serviatte", "tissue", "tooth pic", "straw",
                              "dishwash", "clorex", "moping", "handwash", "pinol", "cleaner"]),
]


def guess_category(name):
    n = name.lower() + " "
    for cat, words in CATEGORY_RULES:
        if any(w in n for w in words):
            return cat
    return "Other"


def parse_qty(v, name, warnings):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        n, unit = float(v), None
    else:
        m = re.fullmatch(r"([\d.]+)\s*(kg|g|l)?", str(v).strip().lower().replace(",", ""))
        if not m:
            warnings.append(f"{name}: could not read quantity '{v}' -> used 0")
            return 0.0
        n, unit = float(m[1]), m[2]
    if "oil can" in name.lower():                       # counted in cans; sheet mixes litres and cans
        if unit == "l" or n >= 10:
            return n / 20
        return n
    return n / 1000 if unit == "g" else n


def parse_price(v, name, warnings):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().replace(",", "")
    m = re.fullmatch(r"\((\d+(?:\.\d+)?)\s*g\)\s*([\d.]+)", s)
    if m:                                               # price per 25g -> price per kg
        return float(m[2]) * 1000 / float(m[1])
    m = re.fullmatch(r"\(\d+\s*pkt\)\s*([\d.]+)", s)
    if m:
        return float(m[1])
    try:
        return float(s)
    except ValueError:
        warnings.append(f"{name}: could not read price '{v}' -> used 0")
        return 0.0


def parse_legacy_excel(file):
    from openpyxl import load_workbook

    ws = load_workbook(file, data_only=True).active
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    blocks = []
    for idx, v in enumerate(header):
        m = re.match(r"\s*(opening|purchases|closing)[^(]*\((\w{3})\w*\s+(\d{4})\)", str(v or ""), re.I)
        if m:
            blocks.append((m[1].lower(), f"{m[3]}-{MONTH_NUM[m[2][:3].lower()]:02d}", idx))
    if not blocks:
        raise ValueError("Could not find 'Opening / Purchases / Closing Stock (Mon YYYY)' headers in row 1.")

    warnings, items, openings, purchases, counts = [], [], [], [], []
    seen, base = {}, ""

    for row in ws.iter_rows(min_row=3, values_only=True):
        raw = row[0]
        if raw is None:
            continue
        label = str(raw).strip()
        if label.lower() == "total":
            break
        if all(c is None for c in row[1:]):             # section header e.g. "Water"
            base = label
            continue
        variant = label[:1].isdigit() or label.lower() in {"small", "medium", "large"}   # sizes: 500ml, 1l, Medium...
        name = f"{base} {label}" if variant else label
        if not variant:
            base = split_group_size(label)[0]
        name = re.sub(r"\s+", " ", name).strip()
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            new = f"{name} ({seen[name]})"
            warnings.append(f"Duplicate item name '{name}' -> imported as '{new}' (rename it in Setup if you like)")
            name = new
        grp, size = split_group_size(name)
        items.append({"item": name, "group": grp, "size": size, "category": guess_category(name),
                      "unit": "", "sell_price": None})

        for kind, month, c in blocks:
            q = parse_qty(row[c], name, warnings)
            p = parse_price(row[c + 1], name, warnings) if c + 1 < len(row) else 0.0
            if kind == "opening":
                openings.append({"month": month, "item": name, "qty": q, "unit_price": p})
            elif kind == "purchases" and q > 0:
                purchases.append({"date": str(pd.Period(month).end_time.date()), "month": month, "item": name,
                                  "qty": q, "unit_price": p, "supplier": "", "note": "Imported from Excel"})
                if p == 0:
                    warnings.append(f"{name}: purchase in {month} has price 0")
            elif kind == "closing":
                counts.append({"month": month, "item": name, "closing_qty": q})

    return {"items": pd.DataFrame(items), "openings": pd.DataFrame(openings),
            "purchases": pd.DataFrame(purchases), "counts": pd.DataFrame(counts)}, warnings


# ───────────────────────────── users / login ─────────────────────────────
MAX_ADMINS = 1          # one Admin ...
MAX_USERS = 3           # ... and three normal Users, each with their own account
COOKIE = "inv_session"  # browser cookie that keeps people logged in
SESSION_DAYS = 30


def read_users():
    return clean("users", get_store().read("users"))          # never cached: slot counts must be exact


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def is_admin():
    return st.session_state.get("role") == "Admin"


def cookie_token():
    try:
        return st.context.cookies.get(COOKIE)
    except Exception:
        return None


def emit_cookie():
    """Runs the pending 'set / clear browser cookie' command (queued by login / logout)."""
    cmd = st.session_state.pop("cookie_cmd", None)
    if cmd:
        token, max_age = cmd
        html = (f"<script>window.parent.document.cookie = "
                f"'{COOKIE}={token}; max-age={max_age}; path=/; SameSite=Lax';</script>")
        if hasattr(st, "iframe"):                                # newer Streamlit
            st.iframe(html, height=1)
        else:                                                    # older Streamlit
            import streamlit.components.v1 as components
            components.html(html, height=0)


def start_session(username, role, remember):
    st.session_state["user"], st.session_state["role"] = username, role
    if remember:                                                # save the login in the Sheet + browser
        token = pysecrets.token_urlsafe(32)
        sess = clean("sessions", get_store().read("sessions"))
        sess = sess[pd.to_datetime(sess["expires"], errors="coerce") > datetime.now()]
        new = pd.DataFrame([{"token_hash": sha(token), "username": username,
                             "expires": (datetime.now() + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")}])
        get_store().write("sessions", pd.concat([sess, new], ignore_index=True))
        st.session_state["cookie_cmd"] = (token, SESSION_DAYS * 86400)


def restore_session():
    """Log the person back in from the browser cookie (survives refresh / closing the tab)."""
    token = cookie_token()
    if not token:
        return False
    sess = clean("sessions", get_store().read("sessions"))
    hit = sess[sess["token_hash"] == sha(token)]
    if hit.empty or pd.to_datetime(hit.iloc[0]["expires"], errors="coerce") < datetime.now():
        return False
    users = read_users()
    u = users[users["username"] == hit.iloc[0]["username"]]
    if u.empty:
        return False
    st.session_state["user"], st.session_state["role"] = u.iloc[0]["username"], u.iloc[0]["role"] or "User"
    return True


def logout():
    token = cookie_token()
    if token:
        sess = clean("sessions", get_store().read("sessions"))
        get_store().write("sessions", sess[sess["token_hash"] != sha(token)])
    for k in ("user", "role"):
        st.session_state.pop(k, None)
    st.session_state["cookie_cmd"] = ("", 0)
    st.rerun()


def change_password(old, new, new2):
    users = read_users()
    i = users.index[users["username"] == st.session_state["user"]][0]
    if not hmac.compare_digest(hash_pw(old, users.at[i, "salt"]), users.at[i, "hash"]):
        return "Current password is wrong."
    if len(new) < 6 or new != new2:
        return "New passwords must match and be at least 6 characters."
    salt = pysecrets.token_hex(16)
    users.at[i, "salt"], users.at[i, "hash"] = salt, hash_pw(new, salt)
    get_store().write("users", users)
    return None


def users_admin():
    users = read_users()
    admins = (users["role"] == "Admin").sum()
    st.caption(f"Admin: {admins}/{MAX_ADMINS}   ·   Users: {len(users) - admins}/{MAX_USERS}. "
               "Remove a user to free a slot (they can then register again).")
    for i, r in users.iterrows():
        c1, c2 = st.columns([4, 1])
        c1.write(f"**{r['username']}**  ·  {r['role'] or 'User'}  ·  registered {r['created'][:10]}")
        if r["role"] != "Admin" and c2.button("Remove", key=f"rm_{r['username']}"):
            get_store().write("users", users.drop(index=i))
            st.rerun()


def auth_gate():
    if st.session_state.get("user") or restore_session():
        return
    st.markdown("<h1 style='text-align:center'>🍽️ Restaurant Inventory Management</h1>", unsafe_allow_html=True)
    users = read_users()
    admins = int((users["role"] == "Admin").sum())
    normal = len(users) - admins
    roles_open = (["Admin"] if admins < MAX_ADMINS else []) + (["User"] if normal < MAX_USERS else [])

    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        t_login, t_reg = st.tabs(["🔑 Login", "📝 Register"])

        with t_login:
            with st.form("login"):
                u = st.text_input("Username", key="login_user")
                p = st.text_input("Password", type="password", key="login_pass")
                remember = st.checkbox(f"Keep me logged in on this device ({SESSION_DAYS} days)", value=True)
                if st.form_submit_button("Login", type="primary"):
                    row = users[users["username"] == u.strip().lower()]
                    if not row.empty and hmac.compare_digest(hash_pw(p, row.iloc[0]["salt"]), row.iloc[0]["hash"]):
                        start_session(row.iloc[0]["username"], row.iloc[0]["role"] or "User", remember)
                        st.rerun()
                    st.error("Wrong username or password.")

        with t_reg:
            if not roles_open:
                st.warning(f"Registration is closed: {MAX_ADMINS} Admin and {MAX_USERS} Users are already registered.")
            else:
                st.caption(f"Free places – Admin: {MAX_ADMINS - admins}, Users: {MAX_USERS - normal}")
                with st.form("register"):
                    role = st.radio("Register as", roles_open, horizontal=True, key="reg_role")
                    u = st.text_input("Choose a username", key="reg_user")
                    p1 = st.text_input("Password (min 6 characters)", type="password", key="reg_p1")
                    p2 = st.text_input("Repeat password", type="password", key="reg_p2")
                    need = "admin_code" if role == "Admin" else "registration_code"
                    code = st.text_input(f"{'Admin' if role == 'Admin' else 'Registration'} code", type="password",
                                         key="reg_code") if secrets_has(need) else ""
                    if st.form_submit_button("Create account", type="primary"):
                        u = u.strip().lower()
                        fresh = read_users()                     # re-check right before saving
                        f_admins = int((fresh["role"] == "Admin").sum())
                        full = f_admins >= MAX_ADMINS if role == "Admin" else len(fresh) - f_admins >= MAX_USERS
                        if secrets_has(need) and code != st.secrets[need]:
                            st.error("Wrong code.")
                        elif not re.fullmatch(r"[a-z0-9_.-]{3,20}", u):
                            st.error("Username: 3-20 letters, numbers, _ . -")
                        elif len(p1) < 6 or p1 != p2:
                            st.error("Passwords must match and be at least 6 characters.")
                        elif full:
                            st.error(f"No free {role} place left.")
                        elif u in fresh["username"].values:
                            st.error("That username is taken.")
                        else:
                            salt = pysecrets.token_hex(16)
                            new = pd.DataFrame([{"username": u, "role": role, "salt": salt, "hash": hash_pw(p1, salt),
                                                 "created": datetime.now().isoformat(timespec="seconds")}])
                            get_store().write("users", pd.concat([fresh, new], ignore_index=True))
                            start_session(u, role, True)
                            st.rerun()
    st.stop()


# ───────────────────────────── pages ─────────────────────────────
def fmt_cfg(**extra):
    num = st.column_config.NumberColumn
    cfg = {
        "month": None,
        "item": st.column_config.TextColumn("Item"),
        "group": st.column_config.TextColumn("Item"),
        "size": st.column_config.TextColumn("Size"),
        "category": st.column_config.TextColumn("Category"),
        "unit": st.column_config.TextColumn("Unit"),
        "open_qty": num("Opening Qty", format="%.2f"),
        "open_value": num("Opening Value", format="%.2f"),
        "purch_qty": num("Purchased Qty", format="%.2f"),
        "purch_value": num("Purchased Value", format="%.2f"),
        "available": num("Available Qty", format="%.2f"),
        "avg_cost": num("Avg Cost", format="%.2f"),
        "closing_qty": num("Closing Qty", format="%.2f"),
        "closing_value": num("Closing Value", format="%.2f"),
        "sold_qty": num("SOLD Qty", format="%.2f"),
        "sold_value": num("SOLD Value (cost)", format="%.2f"),
        "sell_price": num("Selling Price", format="%.2f"),
        "sales_value": num("Sales Value", format="%.2f"),
        "margin": num("Margin", format="%.2f"),
        "status": st.column_config.TextColumn("Status"),
    }
    cfg.update(extra)
    return cfg


def need_setup():
    st.info("Start in **⚙️ Setup**: import your Excel file, or add items and enter the opening stock.")


def page_report():
    st.header("📊 Monthly Report")
    months = available_months()
    if not months:
        return need_setup()
    m = st.selectbox("Month", months[::-1])
    full = compute(m)
    df = full[full["month"] == m]

    f1, f2 = st.columns(2)
    cats = sorted(df["category"].unique())
    pick = f1.multiselect("Category", cats)
    q = f2.text_input("Search item")
    if pick:
        df = df[df["category"].isin(pick)]
    if q:
        df = df[df["item"].str.contains(q, case=False, na=False)]

    k = st.columns(5)
    k[0].metric("Opening value", f"{df['open_value'].sum():,.0f}")
    k[1].metric("Purchases", f"{df['purch_value'].sum():,.0f}")
    k[2].metric("Closing value", f"{df['closing_value'].sum():,.0f}")
    k[3].metric("Sold (at cost)", f"{df['sold_value'].sum():,.0f}")
    k[4].metric("Sales value", f"{df['sales_value'].sum():,.0f}" if df["sales_value"].notna().any() else "–")

    if (df["status"] == "Open month").any():
        st.info("This month has no stock take yet, so Sold is blank. Do it in **Month-End Stock Take**.")
    if (df["status"] == "Not counted").any():
        st.warning(f"{(df['status'] == 'Not counted').sum()} item(s) with stock were not counted.")
    if df["status"].str.startswith("Check").any():
        st.error("Some counts are higher than Opening + Purchases (negative sold). "
                 "Check missing purchases or count mistakes:  "
                 + ", ".join(df.loc[df["status"].str.startswith("Check"), "item"]))

    cols = ["group", "size", "category", "open_qty", "purch_qty", "closing_qty", "sold_qty", "avg_cost",
            "sold_value", "closing_value", "sales_value", "margin", "status"]
    st.dataframe(df[cols], hide_index=True, width="stretch", column_config=fmt_cfg(), height=520)

    with st.expander("🧮 Totals by item group (e.g. all Water sizes together)"):
        g = df.groupby("group", sort=False)[["open_value", "purch_value", "closing_value", "sold_value"]].sum()
        st.dataframe(g, width="stretch", column_config={c: st.column_config.NumberColumn(format="%.2f") for c in g.columns})

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.drop(columns=["month"]).to_excel(xw, sheet_name=m, index=False)
        full.to_excel(xw, sheet_name="All months", index=False)
    st.download_button("⬇️ Download Excel", buf.getvalue(), file_name=f"inventory_{m}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    top = df.dropna(subset=["sold_value"]).nlargest(15, "sold_value")
    if not top.empty:
        st.subheader("Top 15 items by sold value")
        st.bar_chart(top.set_index("item")["sold_value"])

    with st.expander("📈 Month-by-month trend"):
        what = st.radio("Show", ["sold_qty", "sold_value", "purch_value"], horizontal=True,
                        format_func=lambda x: {"sold_qty": "Sold qty", "sold_value": "Sold value",
                                               "purch_value": "Purchased value"}[x])
        st.dataframe(full.pivot_table(index="item", columns="month", values=what, aggfunc="sum"),
                     width="stretch")


def last_prices():
    p = load("purchases").sort_values("date")
    prices = load("openings").set_index("item")["unit_price"].dropna().to_dict()
    prices.update(p.groupby("item")["unit_price"].last().dropna().to_dict())
    return prices


def page_purchases():
    st.header("🛒 Purchases")
    items = load("items")
    if items.empty:
        return need_setup()
    names = items["item"].tolist()
    t1, t2 = st.tabs(["➕ Add purchases", "🧾 Purchase log"])

    with t1:
        st.caption("Add one row per item received. Leave **Unit price** blank to use the last known price.")
        start = pd.DataFrame({"date": [date.today()], "item": [None], "qty": [None],
                              "unit_price": [None], "supplier": [""]})
        new = st.data_editor(
            start, num_rows="dynamic", hide_index=True, width="stretch", key=f"padd_{ver()}",
            column_config={
                "date": st.column_config.DateColumn("Date", required=True),
                "item": st.column_config.SelectboxColumn("Item", options=names, required=True),
                "qty": st.column_config.NumberColumn("Qty", min_value=0.0, format="%.2f"),
                "unit_price": st.column_config.NumberColumn("Unit price", min_value=0.0, format="%.2f"),
                "supplier": st.column_config.TextColumn("Supplier"),
            })
        if st.button("Save purchases", type="primary"):
            new = new.dropna(subset=["item"])
            new = new[new["qty"].fillna(0) > 0]
            if new.empty:
                st.warning("Nothing to save – pick an item and a quantity.")
            else:
                lp = last_prices()
                new = new.copy()
                new["date"] = pd.to_datetime(new["date"]).dt.strftime("%Y-%m-%d").fillna(str(date.today()))
                new["month"] = new["date"].str[:7]
                new["unit_price"] = [p if pd.notna(p) else lp.get(i, 0.0) for i, p in zip(new["item"], new["unit_price"])]
                new["note"] = ""
                new["entered_by"] = st.session_state["user"]
                save("purchases", pd.concat([load("purchases"), new], ignore_index=True))
                st.success(f"Saved {len(new)} purchase line(s).")
                st.rerun()

    with t2:
        p = load("purchases")
        if p.empty:
            st.info("No purchases yet.")
        else:
            months = sorted(p["month"].unique(), reverse=True)
            m = st.selectbox("Month", months)
            sub = p[p["month"] == m].copy()
            sub["date"] = pd.to_datetime(sub["date"]).dt.date
            ed = st.data_editor(
                sub.drop(columns=["month"]), num_rows="dynamic", hide_index=True, width="stretch",
                key=f"plog_{m}_{ver()}",
                column_config={
                    "date": st.column_config.DateColumn("Date", required=True),
                    "item": st.column_config.SelectboxColumn("Item", options=names, required=True),
                    "qty": st.column_config.NumberColumn("Qty", format="%.2f"),
                    "unit_price": st.column_config.NumberColumn("Unit price", format="%.2f"),
                    "supplier": "Supplier", "note": "Note", "entered_by": "Entered by"},
                disabled=["entered_by"])
            st.metric("Total purchased this month", f"{(ed['qty'].fillna(0) * ed['unit_price'].fillna(0)).sum():,.2f}")
            if st.button("Save changes to this month"):
                ed = ed.dropna(subset=["item"]).copy()
                ed["date"] = pd.to_datetime(ed["date"]).dt.strftime("%Y-%m-%d")
                ed["month"] = ed["date"].str[:7]
                save("purchases", pd.concat([p[p["month"] != m], ed], ignore_index=True))
                st.success("Updated.")
                st.rerun()


def page_stock_take():
    st.header("📋 Month-End Stock Take")
    months = available_months()
    if not months:
        return need_setup()
    default = max(len(months) - 2, 0) if len(months) > 1 else 0   # usually the month that just ended
    m = st.selectbox("Month being closed", months[::-1], index=len(months) - 1 - default)
    cur = compute(m)
    cur = cur[cur["month"] == m].copy()
    counts = load("counts")
    saved = counts[counts["month"] == m].set_index("item")["closing_qty"]
    cur["counted"] = cur["item"].map(saved)
    table = cur[["item", "category", "unit", "open_qty", "purch_qty", "available", "counted"]]

    st.caption("Enter the quantity physically left on the shelf in **Counted**. "
               "Items with no stock at all don't need to be entered.")
    ed = st.data_editor(
        table, hide_index=True, width="stretch", height=520, key=f"take_{m}_{ver()}",
        disabled=["item", "category", "unit", "open_qty", "purch_qty", "available"],
        column_config={
            "item": "Item", "category": "Category", "unit": "Unit",
            "open_qty": st.column_config.NumberColumn("Opening", format="%.2f"),
            "purch_qty": st.column_config.NumberColumn("Purchased", format="%.2f"),
            "available": st.column_config.NumberColumn("Expected (Opening + Purchased)", format="%.2f"),
            "counted": st.column_config.NumberColumn("✏️ Counted", min_value=0.0, format="%.2f"),
        })

    est = ed.merge(cur[["item", "avg_cost"]], on="item")
    done = est.dropna(subset=["counted"]).copy()
    done["sold"] = done["available"] - done["counted"]
    c = st.columns(3)
    c[0].metric("Items counted", f"{len(done)} / {(est['available'] > 0).sum()} with stock")
    c[1].metric("Estimated sold (cost)", f"{(done['sold'] * done['avg_cost']).sum():,.0f}")
    neg = done[done["sold"] < -1e-9]
    if not neg.empty:
        st.warning("Counted more than expected (missing purchase?): " + ", ".join(neg["item"]))

    if st.button("💾 Save stock take", type="primary"):
        new = done[["item", "counted"]].rename(columns={"counted": "closing_qty"})
        new.insert(0, "month", m)
        new["counted_by"] = st.session_state["user"]
        save("counts", pd.concat([counts[counts["month"] != m], new], ignore_index=True))
        st.success(f"Stock take for {m} saved. Next month's opening stock is now set.")
        st.rerun()


def page_setup():
    st.header("⚙️ Setup")
    admin = is_admin()
    tabs = st.tabs(["📦 Items"] + (["🏁 Opening stock", "📥 Import from Excel", "👥 Users"] if admin else []))
    t1 = tabs[0]

    with t1:
        st.caption("Add / edit items. **Selling price** is optional (for drinks etc.) – it enables Sales value & Margin. "
                   "⚠️ Renaming an item disconnects it from its past records.")
        items = load("items")
        ed = st.data_editor(items, num_rows="dynamic", hide_index=True, width="stretch",
                            key=f"items_{ver()}",
                            column_config={"item": st.column_config.TextColumn("Item (full name)", required=True),
                                           "group": "Group (e.g. Water)", "size": "Size (e.g. 500ml)",
                                           "category": "Category", "unit": "Unit",
                                           "sell_price": st.column_config.NumberColumn("Selling price", min_value=0.0)})
        if st.button("Fill blank Group / Size from item names"):
            ed = clean("items", ed)
            for i, r in ed.iterrows():
                g, sz = split_group_size(r["item"])
                ed.loc[i, "group"] = r["group"] or g
                ed.loc[i, "size"] = r["size"] or sz
            save("items", ed)
            st.rerun()
        if st.button("Save items", type="primary"):
            ed = clean("items", ed)
            dup = ed[ed["item"].duplicated()]["item"].tolist()
            if dup:
                st.error("Duplicate item names: " + ", ".join(dup))
            else:
                save("items", ed)
                st.success("Items saved.")
                st.rerun()

    if not admin:
        st.info("Opening stock, Excel import and user management are available to the Admin only.")
        return
    t2, t3, t4 = tabs[1:]
    with t4:
        users_admin()

    with t2:
        items = load("items")
        if items.empty:
            st.info("Add items first.")
        else:
            op = load("openings")
            cur_month = baseline_month() or date.today().strftime("%Y-%m")
            d = st.date_input("Opening stock is as at the start of month", pd.Period(cur_month).start_time.date())
            month = d.strftime("%Y-%m")
            base = items[["item"]].merge(op[op["month"] == cur_month][["item", "qty", "unit_price"]], how="left", on="item")
            ed = st.data_editor(base, hide_index=True, width="stretch", disabled=["item"], height=480,
                                key=f"open_{ver()}",
                                column_config={"qty": st.column_config.NumberColumn("Opening Qty", min_value=0.0),
                                               "unit_price": st.column_config.NumberColumn("Unit price", min_value=0.0)})
            st.warning("This is only for the very first month you use the system. "
                       "After that opening stock carries forward automatically.")
            if st.button("Save opening stock", type="primary"):
                ed = ed.copy()
                ed[["qty", "unit_price"]] = ed[["qty", "unit_price"]].fillna(0)
                ed.insert(0, "month", month)
                save("openings", ed)
                st.success("Opening stock saved.")
                st.rerun()

    with t3:
        st.caption("Upload your existing report (Opening / Purchases / Closing Stock columns per month). "
                   "It will create items, opening stock, purchases and month-end counts.")
        up = st.file_uploader("Inventory report (.xlsx)", type=["xlsx"])
        if up:
            try:
                data, warns = parse_legacy_excel(up)
            except Exception as e:
                st.error(f"Could not read the file: {e}")
                return
            st.write({k: len(v) for k, v in data.items()})
            st.dataframe(data["items"], hide_index=True, height=250, width="stretch")
            if warns:
                with st.expander(f"⚠️ {len(warns)} things to review"):
                    st.write("\n".join(f"- {w}" for w in warns))
            ok = st.checkbox("Replace ALL existing data with this import")
            if st.button("Import", type="primary", disabled=not ok):
                for t, df in data.items():
                    save(t, df)
                st.success("Imported. Category names were guessed – fix them under 📦 Items if needed.")
                st.rerun()


# ───────────────────────────── main ─────────────────────────────
STYLE = """
<style>
.block-container {padding-top: 1.6rem;}
div[data-testid="stMetric"] {background: rgba(128,128,128,.08); border: 1px solid rgba(128,128,128,.25);
                             border-radius: 10px; padding: 10px 14px;}
.app-banner {background: linear-gradient(90deg,#1f4e79,#2e75b6); color: #fff; padding: 14px 22px;
             border-radius: 12px; margin-bottom: 1rem; font-size: 1.35rem; font-weight: 600;}
</style>
"""


def main():
    try:
        get_store()
    except Exception as e:
        st.error("Could not connect to your Google Sheet. Check that (1) the service-account details are in "
                 "Streamlit **Secrets** under `[gcp_service_account]`, (2) the Sheet is shared with the "
                 "service account's `client_email` as **Editor**, and (3) the Google Sheets and Drive APIs are enabled.")
        st.exception(e)
        st.stop()

    st.markdown(STYLE, unsafe_allow_html=True)
    emit_cookie()
    auth_gate()

    st.markdown("<div class='app-banner'>🍽️ Restaurant Inventory Management System</div>", unsafe_allow_html=True)
    with st.sidebar:
        st.title("Menu")
        page = st.radio("Menu", ["📊 Monthly Report", "🛒 Purchases", "📋 Month-End Stock Take", "⚙️ Setup"],
                        label_visibility="collapsed")
        st.divider()
        st.write(f"👤 **{st.session_state['user']}**  ·  {st.session_state['role']}")
        with st.expander("🔒 Change password"):
            with st.form("chpw", clear_on_submit=True):
                old = st.text_input("Current password", type="password")
                n1 = st.text_input("New password", type="password")
                n2 = st.text_input("Repeat new password", type="password")
                if st.form_submit_button("Change"):
                    err = change_password(old, n1, n2)
                    st.error(err) if err else st.success("Password changed.")
        if st.button("Logout"):
            logout()
        st.caption(f"Storage: {get_store().label}")
        if st.button("🔄 Refresh data"):
            _load.clear()
            st.rerun()

    {"📊 Monthly Report": page_report, "🛒 Purchases": page_purchases,
     "📋 Month-End Stock Take": page_stock_take, "⚙️ Setup": page_setup}[page]()


main()
