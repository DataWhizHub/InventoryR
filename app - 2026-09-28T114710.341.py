import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import io
from datetime import date, datetime
from pathlib import Path

st.set_page_config(page_title="Restaurant POS Inventory", page_icon="🍽️", layout="wide", initial_sidebar_state="expanded")

DB = "restaurant_pos.db"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html,body,[class*="css"]{font-family:Inter,sans-serif}
.stApp{background:#f5f7fb}
.block-container{max-width:1550px;padding-top:3.5rem!important;padding-bottom:2rem!important}
[data-testid="stAppViewContainer"]{overflow:visible!important}
[data-testid="stHeader"]{background:transparent!important}
.pos-title{display:block!important;visibility:visible!important;overflow:visible!important;line-height:1.25!important;padding-top:0.15rem!important;margin:0 0 .25rem 0!important;color:#111827!important;position:relative;z-index:2}
[data-testid="stSidebar"]{background:#111827}
[data-testid="stSidebar"] *{color:#f9fafb!important}
h1,h2,h3{color:#111827}
.pos-card{background:#fff;border:1px solid #e5e7eb;border-radius:16px;padding:18px;box-shadow:0 4px 18px rgba(17,24,39,.05)}
.pos-title{font-size:2rem;font-weight:800}
.pos-sub{color:#6b7280;margin-bottom:1rem}
.kpi-label{font-size:.78rem;color:#6b7280;font-weight:600}
.kpi-value{font-size:1.5rem;font-weight:800;color:#111827}
.badge{display:inline-block;padding:5px 9px;border-radius:999px;font-size:.72rem;font-weight:700}
</style>
""", unsafe_allow_html=True)

def conn():
    c=sqlite3.connect(DB, check_same_thread=False)
    c.execute("PRAGMA foreign_keys=ON")
    return c

def q(sql,p=()):
    c=conn(); d=pd.read_sql_query(sql,c,params=p); c.close(); return d

def x(sql,p=()):
    c=conn(); c.execute(sql,p); c.commit(); c.close()

def pw(v): return hashlib.sha256(v.encode()).hexdigest()
def money(v): return f"Rs. {float(v):,.2f}"

def init():
    c=conn(); cur=c.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT,
      full_name TEXT, role TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS suppliers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, contact TEXT,
      phone TEXT, email TEXT, address TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS categories(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS items(
      id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER, item_name TEXT,
      sub_category TEXT, unit TEXT, reorder_level REAL DEFAULT 0,
      opening_qty REAL DEFAULT 0, opening_unit_cost REAL DEFAULT 0, active INTEGER DEFAULT 1,
      FOREIGN KEY(category_id) REFERENCES categories(id));
    CREATE TABLE IF NOT EXISTS purchase_orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT, po_no TEXT UNIQUE, supplier_id INTEGER,
      order_date TEXT, status TEXT DEFAULT 'Draft', notes TEXT, total REAL DEFAULT 0,
      FOREIGN KEY(supplier_id) REFERENCES suppliers(id));
    CREATE TABLE IF NOT EXISTS po_lines(
      id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER, item_id INTEGER,
      quantity REAL, unit_price REAL, received_qty REAL DEFAULT 0,
      FOREIGN KEY(po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE,
      FOREIGN KEY(item_id) REFERENCES items(id));
    CREATE TABLE IF NOT EXISTS purchases(
      id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_date TEXT, supplier_id INTEGER,
      item_id INTEGER, quantity REAL, unit_price REAL, po_id INTEGER, invoice_no TEXT,
      FOREIGN KEY(supplier_id) REFERENCES suppliers(id), FOREIGN KEY(item_id) REFERENCES items(id));
    CREATE TABLE IF NOT EXISTS stock_movements(
      id INTEGER PRIMARY KEY AUTOINCREMENT, movement_date TEXT, item_id INTEGER,
      movement_type TEXT, quantity REAL, unit_cost REAL, reference TEXT, notes TEXT,
      FOREIGN KEY(item_id) REFERENCES items(id));
    CREATE TABLE IF NOT EXISTS wastage(
      id INTEGER PRIMARY KEY AUTOINCREMENT, waste_date TEXT, item_id INTEGER,
      quantity REAL, reason TEXT, unit_cost REAL, notes TEXT,
      FOREIGN KEY(item_id) REFERENCES items(id));
    CREATE TABLE IF NOT EXISTS month_closing(
      id INTEGER PRIMARY KEY AUTOINCREMENT, month_key TEXT, item_id INTEGER,
      closing_qty REAL, unit_cost REAL, stock_value REAL, closed_at TEXT,
      UNIQUE(month_key,item_id), FOREIGN KEY(item_id) REFERENCES items(id));
    """)
    if not cur.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        cur.execute("INSERT INTO users(username,password,full_name,role) VALUES(?,?,?,?)",
                    ("admin",pw("admin123"),"System Administrator","Admin"))
    c.commit(); c.close()
init()

def login():
    st.markdown("<div style='max-width:470px;margin:7rem auto'><div class='pos-card'>",unsafe_allow_html=True)
    st.markdown("## 🍽️ Restaurant POS")
    st.caption("Inventory & Purchasing Management")
    u=st.text_input("Username")
    p=st.text_input("Password",type="password")
    if st.button("Sign in",type="primary",use_container_width=True):
        d=q("SELECT * FROM users WHERE username=? AND password=? AND active=1",(u,pw(p)))
        if not d.empty:
            st.session_state.user=d.iloc[0].to_dict(); st.rerun()
        else: st.error("Invalid username or password.")
    st.info("Default administrator: admin / admin123")
    st.markdown("</div></div>",unsafe_allow_html=True)

if "user" not in st.session_state:
    login(); st.stop()

user=st.session_state.user
role=user["role"]

def allowed(roles):
    return role in roles

st.sidebar.markdown("### 🍽️ Restaurant POS")
st.sidebar.caption(f"{user['full_name']} • {role}")
menus=["Dashboard","Purchases","Purchase Orders","Stock Intake","Wastage","Month-End Closing","Inventory","Stock Movements","Suppliers","Item Master","Reports"]
page=st.sidebar.radio("NAVIGATION",menus)
if st.sidebar.button("Logout",use_container_width=True):
    del st.session_state.user; st.rerun()

today=date.today()
month_default=today.replace(day=1)

# DASHBOARD
if page=="Dashboard":
    st.markdown("<div class='pos-title'>Operations Dashboard</div><div class='pos-sub'>Purchasing, stock, consumption and month-end position</div>",unsafe_allow_html=True)
    m=st.date_input("Reporting month",month_default,key="dashmonth").strftime("%Y-%m")
    vals=[]
    vals.append(q("SELECT COUNT(*) n FROM items WHERE active=1").iloc[0,0])
    vals.append(q("SELECT COALESCE(SUM(quantity*unit_price),0) v FROM purchases WHERE substr(purchase_date,1,7)=?",(m,)).iloc[0,0])
    vals.append(q("SELECT COALESCE(SUM(quantity*unit_cost),0) v FROM wastage WHERE substr(waste_date,1,7)=?",(m,)).iloc[0,0])
    vals.append(q("SELECT COALESCE(SUM(stock_value),0) v FROM month_closing WHERE month_key=?",(m,)).iloc[0,0])
    cols=st.columns(4)
    labels=[("Active Items",str(vals[0])),("Monthly Purchases",money(vals[1])),("Wastage Value",money(vals[2])),("Closing Stock Value",money(vals[3]))]
    for c,(a,b) in zip(cols,labels):
        with c: st.markdown(f"<div class='pos-card'><div class='kpi-label'>{a}</div><div class='kpi-value'>{b}</div></div>",unsafe_allow_html=True)
    st.markdown("### Purchase Trend")
    trend=q("""SELECT substr(purchase_date,1,7) month,SUM(quantity*unit_price) total
               FROM purchases GROUP BY month ORDER BY month DESC LIMIT 12""").sort_values("month")
    if not trend.empty:
        st.line_chart(trend.set_index("month")["total"])
    c1,c2=st.columns(2)
    with c1:
        st.markdown("### Top Purchased Items")
        top=q("""SELECT i.item_name||' - '||i.sub_category item,
                 SUM(p.quantity) qty,SUM(p.quantity*p.unit_price) value
                 FROM purchases p JOIN items i ON i.id=p.item_id
                 WHERE substr(p.purchase_date,1,7)=?
                 GROUP BY p.item_id ORDER BY value DESC LIMIT 10""",(m,))
        st.dataframe(top,use_container_width=True,hide_index=True)
    with c2:
        st.markdown("### Recent Stock Movements")
        recent=q("""SELECT sm.movement_date Date,i.item_name Item,i.sub_category "Sub-category",
                    sm.movement_type Type,sm.quantity Quantity,sm.reference Reference
                    FROM stock_movements sm JOIN items i ON i.id=sm.item_id
                    ORDER BY sm.id DESC LIMIT 10""")
        st.dataframe(recent,use_container_width=True,hide_index=True)

# SUPPLIERS
elif page=="Suppliers":
    st.markdown("<div class='pos-title'>Supplier Management</div><div class='pos-sub'>Maintain supplier contacts and purchasing relationships.</div>",unsafe_allow_html=True)
    with st.form("supplier"):
        a,b,c=st.columns(3)
        with a: name=st.text_input("Supplier Name *"); contact=st.text_input("Contact Person")
        with b: phone=st.text_input("Phone"); email=st.text_input("Email")
        with c: address=st.text_area("Address")
        if st.form_submit_button("Add Supplier",type="primary"):
            if name.strip():
                x("INSERT INTO suppliers(name,contact,phone,email,address) VALUES(?,?,?,?,?)",(name,contact,phone,email,address)); st.success("Supplier added.")
    st.dataframe(q("SELECT id ID,name Supplier,contact Contact,phone Phone,email Email,address Address FROM suppliers ORDER BY name"),use_container_width=True,hide_index=True)

# ITEM MASTER
elif page=="Item Master":
    st.markdown("<div class='pos-title'>Item Master</div><div class='pos-sub'>Manage item hierarchy, pack sizes, units and reorder levels.</div>",unsafe_allow_html=True)
    with st.form("item"):
        a,b,c=st.columns(3)
        with a:
            cat=st.text_input("Category *",placeholder="Beverages")
            item=st.text_input("Item *",placeholder="Water")
        with b:
            sub=st.text_input("Sub-category / Pack Size *",placeholder="1L")
            unit=st.selectbox("Unit",["Bottle","Can","Packet","Box","Kg","g","L","ml","Piece"])
        with c:
            reorder=st.number_input("Reorder Level",min_value=0.0)
            opening=st.number_input("Opening Quantity",min_value=0.0)
            cost=st.number_input("Opening Unit Cost (Rs.)",min_value=0.0)
        if st.form_submit_button("Add Item",type="primary"):
            x("INSERT OR IGNORE INTO categories(name) VALUES(?)",(cat,))
            cid=q("SELECT id FROM categories WHERE name=?",(cat,)).iloc[0,0]
            x("""INSERT INTO items(category_id,item_name,sub_category,unit,reorder_level,opening_qty,opening_unit_cost)
                 VALUES(?,?,?,?,?,?,?)""",(cid,item,sub,unit,reorder,opening,cost))
            st.success("Item added.")
    st.dataframe(q("""SELECT i.id ID,c.name Category,i.item_name Item,i.sub_category "Sub-category",
                      i.unit Unit,i.reorder_level "Reorder Level",i.opening_qty "Opening Qty"
                      FROM items i LEFT JOIN categories c ON c.id=i.category_id
                      ORDER BY c.name,i.item_name,i.sub_category"""),use_container_width=True,hide_index=True)

# PURCHASES
elif page=="Purchases":
    st.markdown("<div class='pos-title'>Monthly Purchases</div><div class='pos-sub'>Record received purchases. Each saved purchase creates a stock movement automatically.</div>",unsafe_allow_html=True)
    items=q("""SELECT i.id,c.name category,i.item_name,i.sub_category,i.unit
               FROM items i LEFT JOIN categories c ON c.id=i.category_id WHERE i.active=1
               ORDER BY category,item_name,sub_category""")
    suppliers=q("SELECT id,name FROM suppliers WHERE active=1 ORDER BY name")
    if items.empty or suppliers.empty: st.warning("Create items and suppliers first.")
    else:
        with st.form("purchase"):
            a,b=st.columns(2)
            with a:
                d=st.date_input("Purchase Date",today)
                sid=st.selectbox("Supplier",suppliers.id.tolist(),format_func=lambda z:suppliers.loc[suppliers.id==z,"name"].iloc[0])
                invoice=st.text_input("Invoice No.")
            with b:
                iid=st.selectbox("Item",items.id.tolist(),format_func=lambda z:(lambda r:f"{r.category} • {r.item_name} • {r.sub_category} ({r.unit})")(items[items.id==z].iloc[0]))
                qty=st.number_input("Quantity",min_value=.01)
                price=st.number_input("Unit Price (Rs.)",min_value=0.0)
            if st.form_submit_button("Save Purchase",type="primary"):
                c=conn()
                cur=c.cursor(); cur.execute("""INSERT INTO purchases(purchase_date,supplier_id,item_id,quantity,unit_price,invoice_no)
                    VALUES(?,?,?,?,?,?)""",(d.isoformat(),sid,iid,qty,price,invoice))
                ref=f"PUR-{cur.lastrowid}"
                cur.execute("""INSERT INTO stock_movements(movement_date,item_id,movement_type,quantity,unit_cost,reference)
                    VALUES(?,?,?,?,?,?)""",(d.isoformat(),iid,"PURCHASE",qty,price,ref))
                c.commit(); c.close(); st.success("Purchase saved and stock movement posted.")
        m=st.date_input("Month",month_default,key="pmonth").strftime("%Y-%m")
        df=q("""SELECT p.purchase_date Date,s.name Supplier,i.item_name Item,i.sub_category "Sub-category",
                i.unit Unit,p.quantity Quantity,p.unit_price "Unit Price",p.quantity*p.unit_price Total,p.invoice_no "Invoice No."
                FROM purchases p JOIN items i ON i.id=p.item_id LEFT JOIN suppliers s ON s.id=p.supplier_id
                WHERE substr(p.purchase_date,1,7)=? ORDER BY p.purchase_date DESC""",(m,))
        st.dataframe(df,use_container_width=True,hide_index=True)

# PURCHASE ORDERS
elif page=="Purchase Orders":
    st.markdown("<div class='pos-title'>Purchase Orders</div><div class='pos-sub'>Create and track supplier purchase orders before goods are received.</div>",unsafe_allow_html=True)
    suppliers=q("SELECT id,name FROM suppliers WHERE active=1 ORDER BY name")
    items=q("SELECT i.id,c.name category,i.item_name,i.sub_category,i.unit FROM items i LEFT JOIN categories c ON c.id=i.category_id WHERE i.active=1 ORDER BY category,item_name")
    if suppliers.empty or items.empty: st.warning("Create suppliers and items first.")
    else:
        with st.form("po"):
            a,b=st.columns(2)
            with a: od=st.date_input("Order Date",today); sid=st.selectbox("Supplier",suppliers.id.tolist(),format_func=lambda z:suppliers.loc[suppliers.id==z,"name"].iloc[0])
            with b: iid=st.selectbox("Item",items.id.tolist(),format_func=lambda z:(lambda r:f"{r.item_name} • {r.sub_category} ({r.unit})")(items[items.id==z].iloc[0])); qty=st.number_input("Ordered Quantity",min_value=.01); price=st.number_input("Unit Price",min_value=0.0)
            notes=st.text_area("Notes")
            if st.form_submit_button("Create Purchase Order",type="primary"):
                c=conn(); cur=c.cursor(); stamp=datetime.now().strftime("%Y%m%d%H%M%S")
                cur.execute("INSERT INTO purchase_orders(po_no,supplier_id,order_date,status,notes,total) VALUES(?,?,?,?,?,?)",
                            (f"PO-{stamp}",sid,od.isoformat(),"Open",notes,qty*price))
                pid=cur.lastrowid
                cur.execute("INSERT INTO po_lines(po_id,item_id,quantity,unit_price) VALUES(?,?,?,?)",(pid,iid,qty,price))
                c.commit(); c.close(); st.success(f"Purchase order PO-{stamp} created.")
        st.dataframe(q("""SELECT po.po_no "PO No.",po.order_date Date,s.name Supplier,po.status Status,
                          po.total Total,po.notes Notes FROM purchase_orders po LEFT JOIN suppliers s ON s.id=po.supplier_id
                          ORDER BY po.id DESC"""),use_container_width=True,hide_index=True)

# STOCK INTAKE
elif page=="Stock Intake":
    st.markdown("<div class='pos-title'>Stock Intake</div><div class='pos-sub'>Record non-purchase stock receipts, transfers or opening adjustments.</div>",unsafe_allow_html=True)
    items=q("SELECT i.id,c.name category,i.item_name,i.sub_category,i.unit FROM items i LEFT JOIN categories c ON c.id=i.category_id WHERE i.active=1 ORDER BY category,item_name")
    with st.form("intake"):
        a,b=st.columns(2)
        with a: d=st.date_input("Date",today); typ=st.selectbox("Movement",["INTAKE","TRANSFER_IN","ADJUSTMENT_IN"])
        with b: iid=st.selectbox("Item",items.id.tolist(),format_func=lambda z:(lambda r:f"{r.item_name} • {r.sub_category} ({r.unit})")(items[items.id==z].iloc[0])); qty=st.number_input("Quantity",min_value=.01); cost=st.number_input("Unit Cost",min_value=0.0)
        ref=st.text_input("Reference"); notes=st.text_area("Notes")
        if st.form_submit_button("Post Stock Intake",type="primary"):
            x("INSERT INTO stock_movements(movement_date,item_id,movement_type,quantity,unit_cost,reference,notes) VALUES(?,?,?,?,?,?,?)",(d.isoformat(),iid,typ,qty,cost,ref,notes)); st.success("Stock intake posted.")

# WASTAGE
elif page=="Wastage":
    st.markdown("<div class='pos-title'>Wastage & Loss</div><div class='pos-sub'>Record spoilage, expiry, breakage and other inventory losses.</div>",unsafe_allow_html=True)
    items=q("SELECT i.id,i.item_name,i.sub_category,i.unit FROM items i WHERE i.active=1 ORDER BY i.item_name")
    with st.form("waste"):
        a,b=st.columns(2)
        with a: d=st.date_input("Waste Date",today); iid=st.selectbox("Item",items.id.tolist(),format_func=lambda z:(lambda r:f"{r.item_name} • {r.sub_category} ({r.unit})")(items[items.id==z].iloc[0])); qty=st.number_input("Quantity",min_value=.01)
        with b: reason=st.selectbox("Reason",["Spoilage","Expired","Damaged","Breakage","Preparation Waste","Other"]); cost=st.number_input("Unit Cost (Rs.)",min_value=0.0)
        notes=st.text_area("Notes")
        if st.form_submit_button("Record Wastage",type="primary"):
            c=conn(); cur=c.cursor(); cur.execute("INSERT INTO wastage(waste_date,item_id,quantity,reason,unit_cost,notes) VALUES(?,?,?,?,?,?)",(d.isoformat(),iid,qty,reason,cost,notes)); wid=cur.lastrowid
            cur.execute("INSERT INTO stock_movements(movement_date,item_id,movement_type,quantity,unit_cost,reference,notes) VALUES(?,?,?,?,?,?,?)",(d.isoformat(),iid,"WASTAGE",-qty,cost,f"WST-{wid}",reason)); c.commit(); c.close(); st.success("Wastage recorded.")
    m=st.date_input("Month",month_default,key="wmonth").strftime("%Y-%m")
    st.dataframe(q("""SELECT w.waste_date Date,i.item_name Item,i.sub_category "Sub-category",w.quantity Quantity,
                      w.reason Reason,w.unit_cost "Unit Cost",w.quantity*w.unit_cost "Loss Value"
                      FROM wastage w JOIN items i ON i.id=w.item_id WHERE substr(w.waste_date,1,7)=?
                      ORDER BY w.waste_date DESC""",(m,)),use_container_width=True,hide_index=True)

# MONTH END
elif page=="Month-End Closing":
    st.markdown("<div class='pos-title'>Month-End Stock Closing</div><div class='pos-sub'>Closing stock becomes the next month's opening stock. Quantity × weighted unit cost = closing value.</div>",unsafe_allow_html=True)
    m=st.date_input("Closing Month",month_default,key="closemonth")
    mk=m.strftime("%Y-%m")
    items=q("SELECT i.*,c.name category FROM items i LEFT JOIN categories c ON c.id=i.category_id WHERE i.active=1 ORDER BY category,item_name,sub_category")
    rows=[]
    for _,r in items.iterrows():
        # Opening is previous closing if available; otherwise master opening.
        prev=(pd.to_numeric(q("SELECT closing_qty FROM month_closing WHERE item_id=? AND month_key<? ORDER BY month_key DESC LIMIT 1",(r.id,mk)).iloc[:,0],errors="coerce").iloc[0] if not q("SELECT closing_qty FROM month_closing WHERE item_id=? AND month_key<? ORDER BY month_key DESC LIMIT 1",(r.id,mk)).empty else r.opening_qty)
        pur=q("SELECT COALESCE(SUM(quantity),0) q,COALESCE(SUM(quantity*unit_price),0) v FROM purchases WHERE item_id=? AND substr(purchase_date,1,7)=?",(r.id,mk)).iloc[0]
        moves=q("SELECT COALESCE(SUM(CASE WHEN quantity>0 THEN quantity ELSE 0 END),0) ins,COALESCE(SUM(CASE WHEN quantity<0 THEN quantity ELSE 0 END),0) outs FROM stock_movements WHERE item_id=? AND substr(movement_date,1,7)=?",(r.id,mk)).iloc[0]
        waste=q("SELECT COALESCE(SUM(quantity),0) q FROM wastage WHERE item_id=? AND substr(waste_date,1,7)=?",(r.id,mk)).iloc[0,0]
        # Physical closing is entered by user; system also displays theoretical stock.
        theoretical=float(prev)+float(pur.q)+float(moves.ins)+float(moves.outs)-float(waste)
        old=q("SELECT closing_qty,unit_cost FROM month_closing WHERE item_id=? AND month_key=?",(r.id,mk))
        oq=float(old.iloc[0,0]) if not old.empty else max(0,theoretical)
        oc=float(old.iloc[0,1]) if not old.empty else (float(pur.v)/float(pur.q) if pur.q else float(r.opening_unit_cost))
        rows.append((r.id,f"{r.category} • {r.item_name} • {r.sub_category}",float(prev),theoretical,oq,oc))
    st.caption("Theoretical quantity = previous closing + purchases + stock-in movements − stock-out movements − wastage. Verify against the physical count.")
    with st.form("closing"):
        values=[]
        for iid,label,opening,theory,qty,cost in rows:
            a,b,c,d=st.columns([4,1.5,1.5,1.5])
            with a: st.markdown(f"**{label}**"); st.caption(f"Opening: {opening:g} | Theoretical: {theory:g}")
            with b: cq=st.number_input("Physical Qty",min_value=0.0,value=max(0,qty),key=f"cq{iid}")
            with c: uc=st.number_input("Unit Cost",min_value=0.0,value=max(0,cost),key=f"uc{iid}")
            with d: st.metric("Value",money(cq*uc))
            values.append((iid,cq,uc))
        if st.form_submit_button("🔒 Finalize Month-End Closing",type="primary"):
            c=conn()
            for iid,cq,uc in values:
                c.execute("""INSERT INTO month_closing(month_key,item_id,closing_qty,unit_cost,stock_value,closed_at)
                             VALUES(?,?,?,?,?,?) ON CONFLICT(month_key,item_id) DO UPDATE SET
                             closing_qty=excluded.closing_qty,unit_cost=excluded.unit_cost,
                             stock_value=excluded.stock_value,closed_at=excluded.closed_at""",
                          (mk,iid,cq,uc,cq*uc,datetime.now().isoformat()))
            c.commit(); c.close(); st.success(f"Month {mk} closed/updated successfully.")

# INVENTORY
elif page=="Inventory":
    st.markdown("<div class='pos-title'>Live Inventory</div><div class='pos-sub'>Opening, purchases, stock movements, wastage and closing position by item.</div>",unsafe_allow_html=True)
    m=st.date_input("Month",month_default,key="invmonth").strftime("%Y-%m")
    df=q("""SELECT i.id,c.name Category,i.item_name Item,i.sub_category "Sub-category",i.unit Unit,
            i.reorder_level "Reorder Level",
            COALESCE((SELECT closing_qty FROM month_closing mc WHERE mc.item_id=i.id AND mc.month_key<? ORDER BY mc.month_key DESC LIMIT 1),i.opening_qty) Opening,
            COALESCE((SELECT SUM(quantity) FROM purchases p WHERE p.item_id=i.id AND substr(p.purchase_date,1,7)=?),0) Purchases,
            COALESCE((SELECT SUM(quantity) FROM stock_movements sm WHERE sm.item_id=i.id AND substr(sm.movement_date,1,7)=? AND sm.quantity>0),0) "Other In",
            COALESCE((SELECT SUM(quantity) FROM stock_movements sm WHERE sm.item_id=i.id AND substr(sm.movement_date,1,7)=? AND sm.quantity<0),0) "Other Out",
            COALESCE((SELECT SUM(quantity) FROM wastage w WHERE w.item_id=i.id AND substr(w.waste_date,1,7)=?),0) Wastage,
            COALESCE((SELECT closing_qty FROM month_closing mc WHERE mc.item_id=i.id AND mc.month_key=?),0) Closing
            FROM items i LEFT JOIN categories c ON c.id=i.category_id WHERE i.active=1
            ORDER BY c.name,i.item_name,i.sub_category""",(m,m,m,m,m,m))
    df["Available Before Closing"]=df.Opening+df.Purchases+df["Other In"]+df["Other Out"]-df.Wastage
    df["Status"]=df.apply(lambda r:"REORDER" if r.Closing<=r["Reorder Level"] else "OK",axis=1)
    st.dataframe(df.drop(columns=["id"]),use_container_width=True,hide_index=True)

# MOVEMENTS
elif page=="Stock Movements":
    st.markdown("<div class='pos-title'>Stock Movement History</div><div class='pos-sub'>Complete audit trail of inventory transactions.</div>",unsafe_allow_html=True)
    df=q("""SELECT sm.movement_date Date,i.item_name Item,i.sub_category "Sub-category",i.unit Unit,
            sm.movement_type Type,sm.quantity Quantity,sm.unit_cost "Unit Cost",
            sm.quantity*sm.unit_cost Value,sm.reference Reference,sm.notes Notes
            FROM stock_movements sm JOIN items i ON i.id=sm.item_id ORDER BY sm.id DESC""")
    st.dataframe(df,use_container_width=True,hide_index=True)

# REPORTS
elif page=="Reports":
    st.markdown("<div class='pos-title'>Management Reports</div><div class='pos-sub'>Excel-ready monthly reporting pack.</div>",unsafe_allow_html=True)
    m=st.date_input("Report Month",month_default,key="rmonth").strftime("%Y-%m")
    sheets={
      "Purchases":q("""SELECT p.purchase_date Date,s.name Supplier,i.item_name Item,i.sub_category "Sub-category",
                       p.quantity Quantity,p.unit_price "Unit Price",p.quantity*p.unit_price Total,p.invoice_no "Invoice No."
                       FROM purchases p JOIN items i ON i.id=p.item_id LEFT JOIN suppliers s ON s.id=p.supplier_id
                       WHERE substr(p.purchase_date,1,7)=?""",(m,)),
      "Wastage":q("""SELECT w.waste_date Date,i.item_name Item,i.sub_category "Sub-category",w.quantity Quantity,
                     w.reason Reason,w.unit_cost "Unit Cost",w.quantity*w.unit_cost "Loss Value"
                     FROM wastage w JOIN items i ON i.id=w.item_id WHERE substr(w.waste_date,1,7)=?""",(m,)),
      "Closing Stock":q("""SELECT i.item_name Item,i.sub_category "Sub-category",i.unit Unit,
                           mc.closing_qty "Closing Qty",mc.unit_cost "Unit Cost",mc.stock_value "Stock Value"
                           FROM month_closing mc JOIN items i ON i.id=mc.item_id WHERE mc.month_key=?""",(m,)),
      "Movements":q("""SELECT sm.movement_date Date,i.item_name Item,i.sub_category "Sub-category",
                       sm.movement_type Type,sm.quantity Quantity,sm.unit_cost "Unit Cost",sm.reference Reference
                       FROM stock_movements sm JOIN items i ON i.id=sm.item_id
                       WHERE substr(sm.movement_date,1,7)=?""",(m,))
    }
    for name,df in sheets.items():
        st.markdown(f"### {name}")
        st.dataframe(df,use_container_width=True,hide_index=True)
    output=io.BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        for name,df in sheets.items(): df.to_excel(writer,sheet_name=name[:31],index=False)
    st.download_button("⬇️ Download Complete Excel Report",output.getvalue(),f"restaurant_inventory_{m}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",type="primary")

st.sidebar.divider()
st.sidebar.caption("Restaurant Inventory POS • SQLite")
