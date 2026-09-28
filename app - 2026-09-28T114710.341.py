
import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import io
from datetime import date, datetime

# ============================================================
# RESTAURANT INVENTORY & MONTHLY SALES ESTIMATION SYSTEM
# Formula:
#   Quantity Sold = Opening Stock + Monthly Purchases - Closing Stock
# ============================================================

st.set_page_config(
    page_title="Restaurant Inventory",
    page_icon="🍽️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB = "restaurant_inventory.db"

# ------------------------- THEME ----------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: Inter, sans-serif;
}

.stApp {
    background: #f3f6fa;
}

.block-container {
    padding-top: 2.4rem !important;
    padding-bottom: 2rem;
    max-width: 1500px;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: #172033 !important;
    border-right: 1px solid #26344d;
}
section[data-testid="stSidebar"] * {
    color: #eef4ff !important;
}
section[data-testid="stSidebar"] .stRadio label {
    border-radius: 8px;
    padding: 4px 8px;
}
.sidebar-brand {
    font-size: 1.35rem;
    font-weight: 800;
    color: #ffffff !important;
    margin: 0 0 2px 0;
}
.sidebar-sub {
    color: #9fb0ca !important;
    font-size: .76rem;
    margin-bottom: 1rem;
}
.user-chip {
    background: #202d43;
    border: 1px solid #30415d;
    border-radius: 10px;
    padding: 10px 12px;
    margin: 8px 0 15px 0;
}
.user-name {
    font-weight: 700;
    color: #fff !important;
}
.user-role {
    font-size: .72rem;
    color: #9fb0ca !important;
}

/* Make sidebar logout clearly visible */
section[data-testid="stSidebar"] button {
    color: #ffffff !important;
    background: #263754 !important;
    border: 1px solid #3b4d6b !important;
}
section[data-testid="stSidebar"] button:hover {
    background: #334766 !important;
    color: #ffffff !important;
}

/* Page */
.page-title {
    font-size: 2rem;
    line-height: 1.2;
    font-weight: 800;
    color: #162033;
    margin: 0 0 4px 0;
}
.page-subtitle {
    color: #68758a;
    margin: 0 0 20px 0;
    font-size: .92rem;
}

.card {
    background: #ffffff;
    border: 1px solid #e1e7ef;
    border-radius: 14px;
    padding: 18px;
    box-shadow: 0 4px 18px rgba(24, 39, 75, .05);
}
.kpi-label {
    color: #718096;
    font-size: .76rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: .03em;
}
.kpi-value {
    color: #172033;
    font-size: 1.55rem;
    font-weight: 800;
    margin-top: 5px;
}
.kpi-blue { border-left: 4px solid #2563eb; }
.kpi-green { border-left: 4px solid #16a34a; }
.kpi-orange { border-left: 4px solid #ea580c; }
.kpi-purple { border-left: 4px solid #7c3aed; }

.section-title {
    color: #172033;
    font-weight: 800;
    font-size: 1.08rem;
    margin: 22px 0 10px 0;
}

/* Inputs */
div[data-baseweb="input"] > div,
div[data-baseweb="select"] > div,
textarea {
    border-radius: 8px !important;
}

/* Login */
.login-wrap {
    max-width: 440px;
    margin: 7vh auto 0 auto;
}
.login-card {
    background: #fff;
    border: 1px solid #e0e6ef;
    border-radius: 18px;
    padding: 30px;
    box-shadow: 0 12px 35px rgba(24,39,75,.10);
}
.login-logo {
    font-size: 2rem;
    font-weight: 800;
    color: #172033;
}
.login-caption {
    color: #718096;
    margin-bottom: 20px;
}

/* Tables */
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
}

/* Hide Streamlit menu/footer */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ------------------------- DATABASE -------------------------
def get_conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def query_df(sql, params=()):
    c = get_conn()
    df = pd.read_sql_query(sql, c, params=params)
    c.close()
    return df


def execute(sql, params=()):
    c = get_conn()
    c.execute(sql, params)
    c.commit()
    c.close()


def init_db():
    c = get_conn()
    cur = c.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'Staff',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        contact TEXT,
        phone TEXT,
        email TEXT,
        address TEXT,
        active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        item_name TEXT NOT NULL,
        sub_category TEXT NOT NULL,
        unit TEXT NOT NULL,
        reorder_level REAL DEFAULT 0,
        active INTEGER DEFAULT 1,
        UNIQUE(category, item_name, sub_category)
    );

    CREATE TABLE IF NOT EXISTS monthly_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month_key TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        opening_qty REAL NOT NULL DEFAULT 0,
        purchase_qty REAL NOT NULL DEFAULT 0,
        purchase_unit_price REAL NOT NULL DEFAULT 0,
        closing_qty REAL NOT NULL DEFAULT 0,
        wastage_qty REAL NOT NULL DEFAULT 0,
        notes TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(month_key, item_id),
        FOREIGN KEY(item_id) REFERENCES items(id)
    );

    CREATE TABLE IF NOT EXISTS purchase_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        month_key TEXT NOT NULL,
        purchase_date TEXT,
        supplier_id INTEGER,
        item_id INTEGER NOT NULL,
        quantity REAL NOT NULL,
        unit_price REAL NOT NULL,
        invoice_no TEXT,
        notes TEXT,
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id),
        FOREIGN KEY(item_id) REFERENCES items(id)
    );
    """)

    c.commit()
    c.close()


init_db()


# ------------------------- HELPERS --------------------------
def money(value):
    return f"Rs. {float(value):,.2f}"


def month_label(month_key):
    return pd.to_datetime(month_key + "-01").strftime("%B %Y")


def previous_month(month_key):
    d = pd.to_datetime(month_key + "-01") - pd.DateOffset(months=1)
    return d.strftime("%Y-%m")


def next_month(month_key):
    d = pd.to_datetime(month_key + "-01") + pd.DateOffset(months=1)
    return d.strftime("%Y-%m")


def user_can(roles):
    return st.session_state.user["role"] in roles


def get_items():
    return query_df("""
        SELECT id, category, item_name, sub_category, unit, reorder_level
        FROM items
        WHERE active=1
        ORDER BY category, item_name, sub_category
    """)


def get_suppliers():
    return query_df("""
        SELECT id, name
        FROM suppliers
        WHERE active=1
        ORDER BY name
    """)


# ------------------------- AUTHENTICATION -------------------
def registration_exists():
    return int(query_df("SELECT COUNT(*) AS n FROM users").iloc[0]["n"]) > 0


def registration_page():
    st.markdown("""
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-logo">🍽️ Restaurant Inventory</div>
        <div class="login-caption">Create the first administrator account</div>
    """, unsafe_allow_html=True)

    st.info(
        "This registration is available only once. "
        "The first registered account becomes the Administrator. "
        "After registration, this section is permanently replaced by the Login screen."
    )

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
        elif registration_exists():
            st.warning("Registration has already been completed. Please use Login.")
            st.rerun()
        else:
            try:
                execute("""
                    INSERT INTO users
                    (username,password,full_name,role,active,created_at)
                    VALUES(?,?,?,?,?,?)
                """, (
                    username.strip(),
                    hash_password(password),
                    full_name.strip(),
                    "Admin",
                    1,
                    datetime.now().isoformat()
                ))
                st.success("Administrator account created successfully. You can now log in.")
                st.rerun()
            except sqlite3.IntegrityError:
                st.error("That username already exists. Please choose another username.")

    st.markdown("</div></div>", unsafe_allow_html=True)


def login_page():
    st.markdown("""
    <div class="login-wrap">
      <div class="login-card">
        <div class="login-logo">🍽️ Restaurant Inventory</div>
        <div class="login-caption">Monthly stock, purchases & sales estimation</div>
    """, unsafe_allow_html=True)

    username = st.text_input("Username", placeholder="Enter username")
    password = st.text_input("Password", type="password", placeholder="Enter password")

    if st.button("Sign In", type="primary", use_container_width=True):
        df = query_df("""
            SELECT * FROM users
            WHERE username=? AND password=? AND active=1
        """, (username.strip(), hash_password(password)))

        if not df.empty:
            st.session_state.user = df.iloc[0].to_dict()
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.markdown("</div></div>", unsafe_allow_html=True)


# First launch: show registration exactly once.
if "user" not in st.session_state:
    if not registration_exists():
        registration_page()
    else:
        login_page()
    st.stop()


# ------------------------- SIDEBAR --------------------------
user = st.session_state.user

st.sidebar.markdown('<div class="sidebar-brand">🍽️ Restaurant POS</div>', unsafe_allow_html=True)
st.sidebar.markdown('<div class="sidebar-sub">Inventory Management</div>', unsafe_allow_html=True)

st.sidebar.markdown(f"""
<div class="user-chip">
    <div class="user-name">{user["full_name"]}</div>
    <div class="user-role">{user["role"]} • @{user["username"]}</div>
</div>
""", unsafe_allow_html=True)

menu = [
    "Dashboard",
    "Monthly Stock",
    "Purchases",
    "Monthly Sales",
    "Items",
    "Suppliers",
]

if user_can(["Admin"]):
    menu.append("Settings")

page = st.sidebar.radio("MENU", menu)

st.sidebar.divider()

if st.sidebar.button("↪  Logout", use_container_width=True):
    st.session_state.pop("user", None)
    st.rerun()

st.sidebar.caption("Restaurant Inventory System")


# ============================================================
# DASHBOARD
# ============================================================
if page == "Dashboard":
    st.markdown('<div class="page-title">Dashboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Monthly stock position and estimated item sales.</div>',
        unsafe_allow_html=True
    )

    selected = st.date_input(
        "Select month",
        date.today().replace(day=1),
        key="dashboard_month"
    )
    mk = selected.strftime("%Y-%m")

    df = query_df("""
        SELECT
            mi.month_key,
            i.category,
            i.item_name,
            i.sub_category,
            i.unit,
            mi.opening_qty,
            mi.purchase_qty,
            mi.closing_qty,
            mi.wastage_qty,
            (mi.opening_qty + mi.purchase_qty - mi.wastage_qty - mi.closing_qty) AS sold_qty,
            mi.purchase_unit_price,
            (mi.purchase_qty * mi.purchase_unit_price) AS purchase_value
        FROM monthly_inventory mi
        JOIN items i ON i.id=mi.item_id
        WHERE mi.month_key=?
        ORDER BY i.category, i.item_name, i.sub_category
    """, (mk,))

    item_count = len(df)
    purchase_qty = df["purchase_qty"].sum() if not df.empty else 0
    sold_qty = df["sold_qty"].sum() if not df.empty else 0
    closing_qty = df["closing_qty"].sum() if not df.empty else 0
    purchase_value = df["purchase_value"].sum() if not df.empty else 0

    c1, c2, c3, c4 = st.columns(4)

    cards = [
        ("Items Recorded", item_count, "kpi-blue"),
        ("Purchased Quantity", f"{purchase_qty:,.2f}", "kpi-green"),
        ("Estimated Quantity Sold", f"{sold_qty:,.2f}", "kpi-orange"),
        ("Closing Quantity", f"{closing_qty:,.2f}", "kpi-purple"),
    ]

    for col, (label, value, cls) in zip([c1,c2,c3,c4], cards):
        with col:
            st.markdown(
                f'<div class="card {cls}"><div class="kpi-label">{label}</div>'
                f'<div class="kpi-value">{value}</div></div>',
                unsafe_allow_html=True
            )

    st.markdown('<div class="section-title">Monthly Stock Position</div>', unsafe_allow_html=True)

    if df.empty:
        st.info("No monthly stock has been entered for this month.")
    else:
        st.dataframe(
            df[[
                "category","item_name","sub_category","unit",
                "opening_qty","purchase_qty","closing_qty",
                "wastage_qty","sold_qty"
            ]].rename(columns={
                "category":"Category",
                "item_name":"Item",
                "sub_category":"Sub-category",
                "unit":"Unit",
                "opening_qty":"Opening",
                "purchase_qty":"Purchases",
                "closing_qty":"Closing",
                "wastage_qty":"Wastage",
                "sold_qty":"Estimated Sold",
            }),
            use_container_width=True,
            hide_index=True
        )

    # Trend
    trend = query_df("""
        SELECT month_key,
               SUM(opening_qty + purchase_qty - wastage_qty - closing_qty) sold_qty,
               SUM(purchase_qty) purchase_qty
        FROM monthly_inventory
        GROUP BY month_key
        ORDER BY month_key
    """)

    if not trend.empty:
        st.markdown('<div class="section-title">Monthly Quantity Trend</div>', unsafe_allow_html=True)
        trend["Month"] = pd.to_datetime(trend["month_key"] + "-01").dt.strftime("%b %Y")
        st.line_chart(trend.set_index("Month")[["purchase_qty","sold_qty"]].rename(
            columns={"purchase_qty":"Purchases", "sold_qty":"Estimated Sold"}
        ))


# ============================================================
# MONTHLY STOCK
# ============================================================
elif page == "Monthly Stock":
    st.markdown('<div class="page-title">Monthly Stock Entry</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Enter the physical closing stock at the end of every month. '
        'Opening stock is automatically taken from the previous month.</div>',
        unsafe_allow_html=True
    )

    selected = st.date_input("Stock month", date.today().replace(day=1), key="stock_month")
    mk = selected.strftime("%Y-%m")
    prev = previous_month(mk)

    items = get_items()

    if items.empty:
        st.warning("Please create items first.")
    else:
        st.info(
            f"Opening quantity for {month_label(mk)} is automatically linked to "
            f"the closing quantity of {month_label(prev)}."
        )

        rows = []

        for _, item in items.iterrows():
            old = query_df("""
                SELECT opening_qty, purchase_qty, purchase_unit_price,
                       closing_qty, wastage_qty, notes
                FROM monthly_inventory
                WHERE month_key=? AND item_id=?
            """, (mk, item.id))

            previous = query_df("""
                SELECT closing_qty
                FROM monthly_inventory
                WHERE month_key=? AND item_id=?
            """, (prev, item.id))

            if not previous.empty:
                opening = float(previous.iloc[0]["closing_qty"])
            else:
                opening = 0.0

            if not old.empty:
                purchase_qty = float(old.iloc[0]["purchase_qty"])
                purchase_price = float(old.iloc[0]["purchase_unit_price"])
                closing = float(old.iloc[0]["closing_qty"])
                wastage = float(old.iloc[0]["wastage_qty"])
            else:
                purchase_qty = 0.0
                purchase_price = 0.0
                closing = 0.0
                wastage = 0.0

            rows.append({
                "id": int(item.id),
                "label": f"{item.category} • {item.item_name} • {item.sub_category}",
                "unit": item.unit,
                "opening": opening,
                "purchase_qty": purchase_qty,
                "purchase_price": purchase_price,
                "closing": closing,
                "wastage": wastage,
            })

        with st.form("monthly_stock_form"):
            st.markdown("#### Enter monthly quantities")

            values = []

            for r in rows:
                a,b,c,d,e = st.columns([3.1,1.2,1.2,1.2,1.2])

                with a:
                    st.markdown(f"**{r['label']}**")
                    st.caption(f"Unit: {r['unit']}  |  Opening: {r['opening']:,.2f}")

                with b:
                    purchase_qty = st.number_input(
                        "Purchases",
                        min_value=0.0,
                        value=r["purchase_qty"],
                        step=1.0,
                        key=f"purchase_{r['id']}"
                    )

                with c:
                    purchase_price = st.number_input(
                        "Unit Price",
                        min_value=0.0,
                        value=r["purchase_price"],
                        step=0.01,
                        key=f"price_{r['id']}"
                    )

                with d:
                    closing = st.number_input(
                        "Closing Stock",
                        min_value=0.0,
                        value=r["closing"],
                        step=1.0,
                        key=f"closing_{r['id']}"
                    )

                with e:
                    wastage = st.number_input(
                        "Wastage",
                        min_value=0.0,
                        value=r["wastage"],
                        step=1.0,
                        key=f"waste_{r['id']}"
                    )

                sold = r["opening"] + purchase_qty - wastage - closing

                if sold < 0:
                    st.warning(
                        f"{r['label']}: calculated sold quantity is negative. "
                        "Check the stock entries."
                    )

                values.append((
                    r["id"],
                    r["opening"],
                    purchase_qty,
                    purchase_price,
                    closing,
                    wastage
                ))

            notes = st.text_area("Month notes")

            if st.form_submit_button("Save Monthly Stock", type="primary"):
                c = get_conn()

                for item_id, opening, purchase_qty, price, closing, wastage in values:
                    c.execute("""
                        INSERT INTO monthly_inventory
                        (month_key,item_id,opening_qty,purchase_qty,purchase_unit_price,
                         closing_qty,wastage_qty,notes,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(month_key,item_id)
                        DO UPDATE SET
                            opening_qty=excluded.opening_qty,
                            purchase_qty=excluded.purchase_qty,
                            purchase_unit_price=excluded.purchase_unit_price,
                            closing_qty=excluded.closing_qty,
                            wastage_qty=excluded.wastage_qty,
                            notes=excluded.notes,
                            updated_at=excluded.updated_at
                    """, (
                        mk, item_id, opening, purchase_qty, price,
                        closing, wastage, notes, datetime.now().isoformat()
                    ))

                c.commit()
                c.close()
                st.success(f"{month_label(mk)} stock saved successfully.")


# ============================================================
# PURCHASES
# ============================================================
elif page == "Purchases":
    st.markdown('<div class="page-title">Monthly Purchases</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Optional detailed purchase records. These are linked to the monthly stock quantities.</div>',
        unsafe_allow_html=True
    )

    items = get_items()
    suppliers = get_suppliers()

    if items.empty:
        st.warning("Create items first.")
    else:
        with st.form("purchase_detail_form"):
            a,b = st.columns(2)

            with a:
                purchase_date = st.date_input("Purchase Date", date.today())
                supplier_id = st.selectbox(
                    "Supplier",
                    [0] + suppliers.id.tolist(),
                    format_func=lambda x: "No supplier" if x == 0 else suppliers.loc[
                        suppliers.id == x, "name"
                    ].iloc[0]
                )
                invoice = st.text_input("Invoice No.")

            with b:
                item_id = st.selectbox(
                    "Item",
                    items.id.tolist(),
                    format_func=lambda x: (
                        lambda r: f"{r.category} • {r.item_name} • {r.sub_category} ({r.unit})"
                    )(items[items.id == x].iloc[0])
                )
                quantity = st.number_input("Quantity", min_value=0.0, step=1.0)
                unit_price = st.number_input("Unit Price (Rs.)", min_value=0.0, step=0.01)

            notes = st.text_area("Notes")

            if st.form_submit_button("Save Purchase", type="primary"):
                execute("""
                    INSERT INTO purchase_details
                    (month_key,purchase_date,supplier_id,item_id,quantity,unit_price,invoice_no,notes)
                    VALUES(?,?,?,?,?,?,?,?)
                """, (
                    purchase_date.strftime("%Y-%m"),
                    purchase_date.isoformat(),
                    None if supplier_id == 0 else supplier_id,
                    item_id,
                    quantity,
                    unit_price,
                    invoice,
                    notes
                ))
                st.success("Purchase detail saved.")

        mk = st.date_input("View month", date.today().replace(day=1), key="purchase_view").strftime("%Y-%m")

        df = query_df("""
            SELECT
                p.purchase_date Date,
                s.name Supplier,
                i.item_name Item,
                i.sub_category "Sub-category",
                i.unit Unit,
                p.quantity Quantity,
                p.unit_price "Unit Price",
                p.quantity*p.unit_price Total,
                p.invoice_no "Invoice No."
            FROM purchase_details p
            JOIN items i ON i.id=p.item_id
            LEFT JOIN suppliers s ON s.id=p.supplier_id
            WHERE p.month_key=?
            ORDER BY p.purchase_date DESC
        """, (mk,))

        st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# MONTHLY SALES
# ============================================================
elif page == "Monthly Sales":
    st.markdown('<div class="page-title">Monthly Sales / Consumption</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Estimated from stock movement: Opening + Purchases − Wastage − Closing.</div>',
        unsafe_allow_html=True
    )

    selected = st.date_input("Month", date.today().replace(day=1), key="sales_month")
    mk = selected.strftime("%Y-%m")

    df = query_df("""
        SELECT
            i.category Category,
            i.item_name Item,
            i.sub_category "Sub-category",
            i.unit Unit,
            mi.opening_qty Opening,
            mi.purchase_qty Purchases,
            mi.wastage_qty Wastage,
            mi.closing_qty Closing,
            (mi.opening_qty + mi.purchase_qty - mi.wastage_qty - mi.closing_qty) AS "Estimated Sold",
            mi.purchase_unit_price "Purchase Unit Price",
            (mi.opening_qty + mi.purchase_qty - mi.wastage_qty - mi.closing_qty)
                * mi.purchase_unit_price AS "Estimated Value"
        FROM monthly_inventory mi
        JOIN items i ON i.id=mi.item_id
        WHERE mi.month_key=?
        ORDER BY i.category,i.item_name,i.sub_category
    """, (mk,))

    if df.empty:
        st.info("No stock data entered for this month.")
    else:
        total = df["Estimated Sold"].sum()

        st.markdown(
            f'<div class="card kpi-orange"><div class="kpi-label">Total Estimated Quantity Sold</div>'
            f'<div class="kpi-value">{total:,.2f}</div></div>',
            unsafe_allow_html=True
        )

        st.dataframe(df, use_container_width=True, hide_index=True)

        chart = df.groupby("Category", as_index=False)["Estimated Sold"].sum()
        st.markdown("### Estimated Sales by Category")
        st.bar_chart(chart.set_index("Category"))

        # Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Monthly Sales", index=False)

        st.download_button(
            "Download Monthly Sales Excel",
            output.getvalue(),
            f"monthly_sales_{mk}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


# ============================================================
# ITEMS
# ============================================================
elif page == "Items":
    st.markdown('<div class="page-title">Item Master</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Define categories, products and pack sizes such as Water → 1L / 500ML.</div>',
        unsafe_allow_html=True
    )

    with st.form("item_form"):
        a,b,c = st.columns(3)

        with a:
            category = st.text_input("Category *", placeholder="Beverages")
            item_name = st.text_input("Item *", placeholder="Water")

        with b:
            sub_category = st.text_input("Sub-category / Pack Size *", placeholder="1L")
            unit = st.selectbox(
                "Unit",
                ["Bottle","Can","Packet","Box","Kg","g","L","ml","Piece"]
            )

        with c:
            reorder = st.number_input("Reorder Level", min_value=0.0, step=1.0)

        if st.form_submit_button("Add Item", type="primary"):
            if not category.strip() or not item_name.strip() or not sub_category.strip():
                st.error("Category, Item and Sub-category are required.")
            else:
                try:
                    execute("""
                        INSERT INTO items
                        (category,item_name,sub_category,unit,reorder_level)
                        VALUES(?,?,?,?,?)
                    """, (
                        category.strip(),
                        item_name.strip(),
                        sub_category.strip(),
                        unit,
                        reorder
                    ))
                    st.success("Item added.")
                except sqlite3.IntegrityError:
                    st.error("This item and sub-category already exist.")

    st.dataframe(
        query_df("""
            SELECT
                category Category,
                item_name Item,
                sub_category "Sub-category",
                unit Unit,
                reorder_level "Reorder Level"
            FROM items
            WHERE active=1
            ORDER BY category,item_name,sub_category
        """),
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# SUPPLIERS
# ============================================================
elif page == "Suppliers":
    st.markdown('<div class="page-title">Suppliers</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Manage restaurant suppliers.</div>', unsafe_allow_html=True)

    with st.form("supplier_form"):
        a,b = st.columns(2)

        with a:
            name = st.text_input("Supplier Name *")
            contact = st.text_input("Contact Person")
            phone = st.text_input("Phone")

        with b:
            email = st.text_input("Email")
            address = st.text_area("Address")

        if st.form_submit_button("Add Supplier", type="primary"):
            if not name.strip():
                st.error("Supplier name is required.")
            else:
                try:
                    execute("""
                        INSERT INTO suppliers(name,contact,phone,email,address)
                        VALUES(?,?,?,?,?)
                    """, (name,contact,phone,email,address))
                    st.success("Supplier added.")
                except sqlite3.IntegrityError:
                    st.error("Supplier already exists.")

    st.dataframe(
        query_df("""
            SELECT name Supplier,contact "Contact Person",phone Phone,
                   email Email,address Address
            FROM suppliers
            WHERE active=1
            ORDER BY name
        """),
        use_container_width=True,
        hide_index=True
    )


# ============================================================
# SETTINGS
# ============================================================
elif page == "Settings":
    if not user_can(["Admin"]):
        st.error("Only an Admin can access Settings and manage users.")
        st.stop()

    st.markdown('<div class="page-title">Settings</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">Administration, users and system controls.</div>',
        unsafe_allow_html=True
    )

    tab1, tab2, tab3 = st.tabs(["👥 Users", "🔑 My Password", "⚙️ System"])

    # USER MANAGEMENT
    with tab1:
        st.markdown("### User Management")
        st.caption("The first account is created through one-time registration and becomes Admin. After that, only an Admin can create additional users here.")

        with st.form("create_user"):
            a,b,c = st.columns(3)

            with a:
                username = st.text_input("Username *")
                full_name = st.text_input("Full Name *")

            with b:
                password = st.text_input("Password *", type="password")
                role = st.selectbox("Role", ["Admin","Manager","Storekeeper","Purchasing","Staff"])

            with c:
                active = st.checkbox("Active User", value=True)

            if st.form_submit_button("Create User", type="primary"):
                if not username.strip() or not full_name.strip() or not password:
                    st.error("Username, name and password are required.")
                elif len(password) < 6:
                    st.error("Password must contain at least 6 characters.")
                else:
                    try:
                        execute("""
                            INSERT INTO users
                            (username,password,full_name,role,active,created_at)
                            VALUES(?,?,?,?,?,?)
                        """, (
                            username.strip(),
                            hash_password(password),
                            full_name.strip(),
                            role,
                            1 if active else 0,
                            datetime.now().isoformat()
                        ))
                        st.success("User created.")
                    except sqlite3.IntegrityError:
                        st.error("Username already exists.")

        users = query_df("""
            SELECT id ID,username Username,full_name "Full Name",
                   role Role,active Active,created_at "Created At"
            FROM users
            ORDER BY username
        """)

        st.dataframe(users, use_container_width=True, hide_index=True)

        st.markdown("### Deactivate User")

        user_choices = users[users["username"] != user["username"]]
        if not user_choices.empty:
            selected_user = st.selectbox(
                "Select user",
                user_choices.id.tolist(),
                format_func=lambda x: user_choices.loc[
                    user_choices.id == x, "username"
                ].iloc[0]
            )

            if st.button("Deactivate Selected User"):
                execute("UPDATE users SET active=0 WHERE id=?", (selected_user,))
                st.success("User deactivated.")
                st.rerun()

    # PASSWORD
    with tab2:
        st.markdown("### Change My Password")

        old = st.text_input("Current Password", type="password")
        new = st.text_input("New Password", type="password")
        confirm = st.text_input("Confirm New Password", type="password")

        if st.button("Change Password", type="primary"):
            current = query_df(
                "SELECT password FROM users WHERE id=?",
                (user["id"],)
            )

            if current.empty or current.iloc[0]["password"] != hash_password(old):
                st.error("Current password is incorrect.")
            elif len(new) < 6:
                st.error("New password must contain at least 6 characters.")
            elif new != confirm:
                st.error("New passwords do not match.")
            else:
                execute(
                    "UPDATE users SET password=? WHERE id=?",
                    (hash_password(new), user["id"])
                )
                st.success("Password changed successfully.")

    # SYSTEM
    with tab3:
        st.markdown("### System Information")
        st.info(
            "Monthly sales are estimates based on stock counts. "
            "The system does not directly read POS sales transactions."
        )

        st.markdown("**Inventory formula**")
        st.code(
            "Estimated Sold = Opening Stock + Monthly Purchases - Wastage - Closing Stock"
        )

        st.markdown("**User access model**")
        st.markdown("""
        - The **first account is created once through the Registration section** and automatically becomes **Admin**.
        - After registration, the Registration section is no longer shown.
        - **Admin:** full system access, including Settings and user creation.
        - **User / Staff:** normal inventory, purchasing and reporting access; cannot manage users.
        - Additional users are created by the Admin from **Settings → Users**.
        """)

        st.markdown("**Recommended monthly workflow**")
        st.markdown("""
        1. Enter/confirm the previous month's physical closing stock.
        2. At the beginning of the month, record purchases.
        3. At the end of the month, count physical closing stock.
        4. The system automatically calculates estimated quantity sold.
        5. Review the Monthly Sales report.
        """)

        st.markdown("**Database**")
        st.code(DB)
