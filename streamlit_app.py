import streamlit as st
from supabase import create_client, Client
from typing import Dict, Any, Tuple, Optional
from datetime import datetime

# ---------------------------------------------
# Setup
# ---------------------------------------------
st.set_page_config(page_title="LastWarHeros Dashboard", page_icon="🛡️", layout="wide")

@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)

sb = get_supabase()

# ---------------------------------------------
# Constants and helpers
# ---------------------------------------------
# Source of truth is the buildings_kv table
# Expected schema:
#   key: text primary key
#   value: text
#   updated_at: timestamptz default now() with trigger to update on change
# Helpful SQL if needed:
#   create table if not exists public.buildings_kv (
#     key text primary key,
#     value text,
#     updated_at timestamptz not null default now()
#   );
#   create extension if not exists moddatetime;
#   create trigger set_buildings_kv_updated
#   before update on public.buildings_kv
#   for each row execute procedure moddatetime(updated_at);

DEFAULT_BUILDINGS = [
    "HQ","Wall","Oil Well","Iron Mine","Farm","Barracks","Garage","Airfield",
    "Missile Silo","Research Lab","Radar","Hospital","Warehouse","Power Plant"
]

# Minimal password gate for non public pages
def require_auth() -> bool:
    if "authed" not in st.session_state:
        st.session_state.authed = False
    if st.session_state.authed:
        return True
    with st.sidebar:
        st.markdown("### Admin access")
        pwd = st.text_input("Password", type="password", key="pwd_input")
        if st.button("Unlock"):
            # Use Streamlit secrets for a trivial gate. Replace with proper auth as needed.
            if pwd and pwd == st.secrets.get("app_password", ""):
                st.session_state.authed = True
                st.experimental_rerun()
            else:
                st.error("Incorrect password")
    return st.session_state.authed

# KV accessors

def kv_get(key: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (value, updated_at_iso) for the key, or (None, None) if missing."""
    res = sb.table("buildings_kv").select("value,updated_at").eq("key", key).maybe_single().execute()
    data = res.data
    if not data:
        return None, None
    return data.get("value"), data.get("updated_at")


def kv_set_if_fresh(key: str, new_value: str, expected_updated_at: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Optimistic update. Returns (success, new_updated_at). If expected_updated_at is None, performs upsert."""
    if expected_updated_at:
        # Conditional update. Only update when updated_at matches.
        res = sb.table("buildings_kv").update({"value": new_value}).eq("key", key).eq("updated_at", expected_updated_at).execute()
        if res.data:
            # Fetch the latest updated_at
            v, ts = kv_get(key)
            return True, ts
        return False, None
    else:
        # First write or missing timestamp, do upsert
        res = sb.table("buildings_kv").upsert({"key": key, "value": new_value}).execute()
        v, ts = kv_get(key)
        return True, ts


def kv_bulk_read(keys: list[str]) -> Dict[str, Dict[str, Any]]:
    """Return {key: {value: str|None, updated_at: str|None}} for all keys."""
    # Supabase allows an in_ filter but it can be limited. For small lists this is fine.
    results: Dict[str, Dict[str, Any]] = {k: {"value": None, "updated_at": None} for k in keys}
    if not keys:
        return results
    res = sb.table("buildings_kv").select("key,value,updated_at").in_("key", keys).execute()
    for row in res.data or []:
        results[row["key"]] = {"value": row.get("value"), "updated_at": row.get("updated_at")}
    return results

# ---------------------------------------------
# UI utilities
# ---------------------------------------------

def init_widget_once(key: str, default: str):
    flag = f"_inited_{key}"
    if not st.session_state.get(flag, False):
        st.session_state[key] = default
        st.session_state[flag] = True


def level_as_int_str(v: Optional[str]) -> str:
    try:
        if v is None or v == "":
            return "0"
        return str(int(v))
    except Exception:
        return "0"


def percentage_chip(label: str, current: int, target: int = 40):
    pct = 0 if target == 0 else int(round(min(100, max(0, (current / target) * 100))))
    # gradient chip with black text
    st.markdown(
        f"<div style='display:inline-block;padding:6px 10px;border-radius:16px;"
        f"background:linear-gradient(90deg, rgba(255,255,255,1) 0%, rgba(180,220,255,1) {pct}%, rgba(240,240,240,1) {pct}%);"
        f"box-shadow:0 1px 4px rgba(0,0,0,0.08);font-weight:600;'>"
        f"{label}: {current}/{target} · {pct}%"
        f"</div>", unsafe_allow_html=True
    )


def building_editor(name: str, row: Dict[str, Any]):
    col1, col2, col3 = st.columns([2, 2, 1])
    stored_val = level_as_int_str(row.get("value"))
    updated_at = row.get("updated_at")

    with col1:
        st.caption("Stored level")
        st.markdown(f"**{name} {stored_val}**")
    with col2:
        key = f"level_{name}"
        init_widget_once(key, stored_val)
        def _save_change():
            new_val = st.session_state.get(key, "0")
            ok, new_ts = kv_set_if_fresh(name, str(int(new_val) if new_val != "" else 0), updated_at)
            if ok:
                st.session_state[f"_inited_{key}"] = False  # force reload to reflect latest stored value next run
                st.toast(f"Saved {name} = {new_val}")
            else:
                st.warning(f"{name} changed in another window. Reloaded the latest value.")
                st.session_state[f"_inited_{key}"] = False
        st.text_input("Edit level", key=key, on_change=_save_change)
    with col3:
        if st.button("Reset", key=f"reset_{name}"):
            st.session_state[f"_inited_level_{name}"] = False
            st.session_state[f"level_{name}"] = stored_val
            st.toast(f"Reverted {name}")


# ---------------------------------------------
# Navigation
# ---------------------------------------------
PAGES = ["Dashboard", "Heroes", "Add or Update Hero", "Buildings"]  # keep Buildings available while default order preference is honored

with st.sidebar:
    st.title("LastWarHeros")
    page = st.radio("Navigate", PAGES, index=0)
    if st.button("Sync from Supabase"):
        # Clear all init flags to force widgets to rebind from KV
        for k in list(st.session_state.keys()):
            if k.startswith("_inited_"):
                st.session_state[k] = False
        st.toast("Synced latest values")

# ---------------------------------------------
# Pages
# ---------------------------------------------

if page == "Dashboard":
    st.header("Dashboard")
    st.write("This dashboard reads from buildings_kv for all building levels.")

    kv = kv_bulk_read(DEFAULT_BUILDINGS)

    # Percentage chips row
    chip_cols = st.columns(4)
    for i, name in enumerate(DEFAULT_BUILDINGS[:8]):
        with chip_cols[i % 4]:
            current = int(level_as_int_str(kv[name]["value"]))
            percentage_chip(name, current, 40)

    st.divider()
    st.subheader("Quick edit")
    grid = st.columns(2)
    left_names = DEFAULT_BUILDINGS[::2]
    right_names = DEFAULT_BUILDINGS[1::2]
    with grid[0]:
        for n in left_names:
            building_editor(n, kv[n])
    with grid[1]:
        for n in right_names:
            building_editor(n, kv[n])

elif page == "Buildings":
    st.header("Buildings")
    st.write("All fields autosave to buildings_kv and show the stored level next to the name.")

    kv = kv_bulk_read(DEFAULT_BUILDINGS)

    for name in DEFAULT_BUILDINGS:
        with st.container(border=True):
            building_editor(name, kv[name])

elif page == "Heroes":
    if not require_auth():
        st.stop()
    st.header("Heroes")
    st.info("Heroes management is gated. Build your UI here.")

elif page == "Add or Update Hero":
    if not require_auth():
        st.stop()
    st.header("Add or Update Hero")
    name = st.text_input("Hero name")
    role = st.text_input("Role")
    if st.button("Save hero"):
        st.success(f"Saved hero {name} as {role} (placeholder)")

# ---------------------------------------------
# Footer
# ---------------------------------------------
st.caption("Data source: Supabase buildings_kv. UI uses per field autosave with optimistic locking to avoid accidental overwrites.")
