from __future__ import annotations

# LastWarHeros — Streamlit app with Supabase auth (password, email OTP, Google/GitHub),
# per-user filtering (RLS owner policies), and autosave widgets.
#
# Prereqs:
#   pip install streamlit supabase==2.* python-dotenv pandas numpy
# Secrets/Env:
#   SUPABASE_URL, SUPABASE_ANON_KEY, optional OAUTH_REDIRECT
#
# Notes:
# - Tables that are per-user must have an owner_id uuid column and a unique constraint on (owner_id, key) or (owner_id, name).
# - This file defensively falls back to non-owner schemas for legacy tables (no owner_id) so you can migrate gradually.

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st
from supabase import Client, create_client

# --------------------------------------------------
# Supabase client
# --------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_supabase() -> Client:
    # 1) Streamlit Cloud secrets (flat)
    url = st.secrets.get("supabase_url") or st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("supabase_key") or st.secrets.get("SUPABASE_ANON_KEY")
    # 2) [supabase] url/anon_key
    if not url or not key:
        sec = st.secrets.get("supabase", {})
        url = url or sec.get("url")
        key = key or sec.get("anon_key")
    # 3) env
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error("Supabase credentials missing. Add SUPABASE_URL and SUPABASE_ANON_KEY to secrets or env.")
        st.stop()
    return create_client(url, key)

sb: Client = get_supabase()

# Optional: light connection check
try:
    sb.table("buildings_kv").select("key").limit(1).execute()
except Exception:
    st.warning("⚠️ Supabase connection check failed. Verify URL and key.")

# --------------------------------------------------
# Auth (Password, Email OTP, Google/GitHub OAuth)
# --------------------------------------------------
@dataclass
class AuthResult:
    user_id: str
    email: str


def _oauth_button(sb: Client, provider: str, label: str):
    if st.button(label, use_container_width=True, key=f"oauth::{provider}"):
        try:
            redirect_to = os.getenv("OAUTH_REDIRECT") or "http://localhost:8501"
            sb.auth.sign_in_with_oauth({
                "provider": provider,
                "options": {"redirect_to": redirect_to},
            })
            st.stop()  # handoff to provider
        except Exception as e:
            st.error(f"OAuth start failed: {e}")


def auth_ui(sb: Client) -> Optional[AuthResult]:
    st.sidebar.header("Sign in")
    tabs = st.sidebar.tabs(["Password", "Email code", "Google / GitHub"])

    # 1) Email + Password
    with tabs[0]:
        with st.form("auth_pw", clear_on_submit=False):
            email = st.text_input("Email", key="auth_email_pw")
            password = st.text_input("Password", type="password", key="auth_password_pw")
            c1, c2 = st.columns(2)
            in_btn = c1.form_submit_button("Sign in")
            up_btn = c2.form_submit_button("Create account")
        if in_btn:
            try:
                data = sb.auth.sign_in_with_password({"email": email, "password": password})
                return AuthResult(user_id=data.user.id, email=data.user.email or "")
            except Exception as e:
                st.error(f"Sign in failed: {e}")
        if up_btn:
            try:
                sb.auth.sign_up({"email": email, "password": password})
                st.info("Account created. If confirmation is required, check email.")
            except Exception as e:
                st.error(f"Sign up failed: {e}")

    # 2) Email one-time code
    with tabs[1]:
        st.write("We will send a 6-digit code to your email.")
        with st.form("auth_otp", clear_on_submit=False):
            email_otp = st.text_input("Email", key="auth_email_otp")
            c1, c2 = st.columns(2)
            send_btn = c1.form_submit_button("Send code")
            have_btn = c2.form_submit_button("I have a code")
        if send_btn:
            try:
                sb.auth.sign_in_with_otp({"email": email_otp, "should_create_user": True})
                st.success("Code sent. Check your inbox.")
            except Exception as e:
                st.error(f"Could not send code: {e}")
        if have_btn:
            code = st.text_input("Enter 6-digit code", key="auth_email_code")
            if st.button("Verify code"):
                try:
                    data = sb.auth.verify_otp({"email": email_otp, "token": code, "type": "email"})
                    return AuthResult(user_id=data.user.id, email=data.user.email or "")
                except Exception as e:
                    st.error(f"Verification failed: {e}")

    # 3) OAuth
    with tabs[2]:
        st.caption("Enable providers in Supabase Auth first.")
        _oauth_button(sb, "google", "Continue with Google")
        _oauth_button(sb, "github", "Continue with GitHub")

    return None


def get_current_user(sb: Client) -> Tuple[Optional[str], Optional[dict]]:
    try:
        resp = sb.auth.get_user()
        if resp and resp.user:
            return resp.user.id, resp.user.model_dump()  # type: ignore
    except Exception:
        pass
    return None, None

# --------------------------------------------------
# Owner-scoped data helpers (with legacy fallback)
# --------------------------------------------------
# Your schema uses user_id (not owner_id). Configure the column name here.
ID_COL = "user_id"

def _eq_owner(q, owner_id: str, column: str = ID_COL):
    try:
        return q.eq(column, owner_id)
    except Exception:
        return q  # fallback when column doesn't exist


def kv_select(table: str, owner_id: str, keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    # Try owner-scoped first; if the table has no owner_id, gracefully fall back to unscoped
    try:
        q = sb.table(table).select("key,value,updated_at")
        q = _eq_owner(q, owner_id)
        if keys:
            q = q.in_("key", keys)
        return q.execute().data or []
    except Exception:
        # fallback: no owner_id column in this table
        q = sb.table(table).select("key,value,updated_at")
        if keys:
            q = q.in_("key", keys)
        return q.execute().data or []


def kv_upsert(table: str, owner_id: str, rows: List[Dict[str, Any]], on_conflict: str | None = None):
    payload = []
    for r in rows:
        item = {"key": r["key"], "value": str(r.get("value", ""))}
        # include user id when table supports it
        item[ID_COL] = owner_id
        payload.append(item)
    # default conflict pair uses configured id column
    kwargs = {"on_conflict": on_conflict or f"{ID_COL},key"}
    try:
        sb.table(table).upsert(payload, **kwargs).execute()
    except Exception:
        # legacy table without the id column present
        for x in payload:
            x.pop(ID_COL, None)
        sb.table(table).upsert(payload, on_conflict="key").execute()
        pass
        payload.append(item)
    kwargs = {"on_conflict": on_conflict or "owner_id,key"}
    try:
        sb.table(table).upsert(payload, **kwargs).execute()
    except Exception:
        # legacy table without owner_id
        sb.table(table).upsert([{k: v for k, v in x.items() if k != "owner_id"} for x in payload], on_conflict="key").execute()


def tracking_select(table: str, owner_id: str, fields: str) -> List[Dict[str, Any]]:
    # Try owner-scoped; if missing column, fall back to unscoped for legacy tables
    try:
        q = sb.table(table).select(fields)
        q = _eq_owner(q, owner_id)
        return q.execute().data or []
    except Exception:
        return sb.table(table).select(fields).execute().data or []


def tracking_upsert(table: str, owner_id: str, rows: List[Dict[str, Any]], conflict: str):
    payload = []
    for r in rows:
        item = dict(r)
        item[ID_COL] = owner_id
        payload.append(item)
    try:
        sb.table(table).upsert(payload, on_conflict=conflict.replace("owner_id", ID_COL)).execute()
    except Exception:
        # fallback w/o id column
        for x in payload:
            x.pop(ID_COL, None)
        sb.table(table).upsert(payload, on_conflict=conflict.replace("owner_id,", "").replace(ID_COL + ",", "")).execute()
        # fallback w/o owner
        for x in payload:
            x.pop("owner_id", None)
        sb.table(table).upsert(payload, on_conflict=conflict.replace("owner_id,", "")).execute()
        
def load_kv_map(sb: Client, table: str, owner_id: str) -> Dict[str, str]:
    rows = kv_select(table, owner_id, None)
    return {r.get("key"): r.get("value") for r in (rows or [])}

# --------------------------------------------------
# Autosave widgets (write on change)
# --------------------------------------------------

def autosave_text_input(
    table: str,
    owner_id: str,
    label: str,
    key_name: str,
    initial: str,
    help_text: Optional[str] = None,
):
    wkey = f"kv::{table}::{key_name}"
    if wkey not in st.session_state:
        st.session_state[wkey] = initial

    def _save():
        kv_upsert(table, owner_id, [{"key": key_name, "value": st.session_state.get(wkey, "")}])
        st.toast(f"Saved {label}")

    st.text_input(label, value=st.session_state[wkey], key=wkey, on_change=_save, help=help_text)


def autosave_number_input(
    table: str,
    owner_id: str,
    label: str,
    key_name: str,
    initial: float | int,
    min_value: Optional[float | int] = None,
    max_value: Optional[float | int] = None,
    step: Optional[float | int] = 1,
    help_text: Optional[str] = None,
):
    wkey = f"kvnum::{table}::{key_name}"
    if wkey not in st.session_state:
        st.session_state[wkey] = initial

    def _save():
        kv_upsert(table, owner_id, [{"key": key_name, "value": st.session_state.get(wkey, initial)}])
        st.toast(f"Saved {label}")

    st.number_input(
        label,
        value=st.session_state[wkey],
        min_value=min_value,
        max_value=max_value,
        step=step,
        key=wkey,
        on_change=_save,
        help=help_text,
    )

# --------------------------------------------------
# Data & helpers shared by pages
# --------------------------------------------------
from collections import OrderedDict

base_buildings = [
    "HQ", "Wall",
    "Tech Center 1-3",
    "Barracks 1-4",
    "Drill Ground 1-4",
    "Hospital 1-4", "Emergency Center",
    "Tank Center", "Aircraft Center", "Missile Center",
    "Alert Tower", "Recon Plane 1-3",
    "Coin Vault", "Food Warehouse", "Iron Warehouse",
    "Gold Mine 1-5", "Iron Mine 1-5", "Farmland 1-5", "Oil Well 1-5",
    "Smelter 1-5", "Training Base 1-5", "Material Workshop 1-5",
    "Alliance Center", "Builder's Hut", "Tavern", "Technical Institute",
    "Drone Parts Workshop", "Chip Lab", "Component Factory", "Gear Factory",
]

def expand_ranges_in_order(names: List[str]) -> List[str]:
    out: List[str] = []
    for n in names:
        parts = n.rsplit(" ", 1)
        if len(parts) == 2 and "-" in parts[1]:
            head, rng = parts[0], parts[1]
            try:
                lo, hi = [int(x) for x in rng.split("-")]
                for i in range(lo, hi + 1):
                    out.append(f"{head} {i}")
            except Exception:
                out.append(n)
        else:
            out.append(n)
    return out

DEFAULT_BUILDINGS: List[str] = expand_ranges_in_order(base_buildings)

ALIASES = {
    "oil wall": "Oil Well",
    "coil vault": "Coin Vault",
    "farm warehouse": "Food Warehouse",
    "tactical institute": "Technical Institute",
    "training grounds": "Drill Ground",
}

SERIES = {
    "Tech Center": list(range(1, 4)),
    "Barracks": list(range(1, 5)),
    "Hospital": list(range(1, 5)),
    "Drill Ground": list(range(1, 5)),
    "Recon Plane": list(range(1, 4)),
    "Gold Mine": list(range(1, 6)),
    "Iron Mine": list(range(1, 6)),
    "Farmland": list(range(1, 6)),
    "Oil Well": list(range(1, 6)),
    "Smelter": list(range(1, 6)),
    "Training Base": list(range(1, 6)),
    "Material Workshop": list(range(1, 6)),
}

CENTER_NAMES = ["Tank Center", "Aircraft Center", "Missile Center"]


def kv_read_many(owner_id: str, keys: List[str]) -> Dict[str, Dict[str, Any]]:
    rows = kv_select("buildings_kv", owner_id, keys)
    by_key = {r["key"]: r for r in rows}
    ordered: Dict[str, Dict[str, Any]] = OrderedDict()
    for k in keys:
        r = by_key.get(k)
        if r:
            ordered[k] = {"value": r.get("value"), "updated_at": r.get("updated_at")}
        else:
            ordered[k] = {"value": None, "updated_at": None}
    return ordered


def get_level(kv_map: Dict[str, Dict[str, Any]], name: str) -> int:
    n = ALIASES.get(name.lower(), name)
    row = kv_map.get(n)
    if row is None:
        return 0
    v = row.get("value")
    try:
        return int(v) if v not in (None, "") else 0
    except Exception:
        try:
            return int(float(str(v)))
        except Exception:
            return 0


def max_series(kv_map: Dict[str, Dict[str, Any]], base: str, rng: List[int]) -> int:
    vals = [get_level(kv_map, f"{base} {i}") for i in rng]
    return max(vals) if vals else 0


def sum_series(kv_map: Dict[str, Dict[str, Any]], base: str, rng: List[int]) -> int:
    return sum(get_level(kv_map, f"{base} {i}") for i in rng)


def pct_chip(pct: float, label: str) -> str:
    p = max(0, min(100, int(round(pct))))
    return (
        f"<div style='display:inline-block;padding:6px 10px;border-radius:12px;"
        f"margin-bottom:10px;"
        f"background:linear-gradient(90deg, rgba(255,120,120,1) 0%, rgba(120,200,120,1) {p}%, rgba(235,235,235,1) {p}%);"
        f"color:black;font-weight:700;box-shadow:0 1px 4px rgba(0,0,0,0.08);'>"
        f"{label}{p}%"
        f"</div>"
    )

# --------------------------------------------------
# Navigation
# --------------------------------------------------
st.set_page_config(page_title="LastWarHeros", layout="wide")
PAGES = ["Dashboard", "Buildings", "Heroes", "Add or Update Hero", "Research"]
with st.sidebar:
    st.title("LastWarHeros")

# Determine current user (show auth if missing)
user_id, _ = get_current_user(sb)
if not user_id:
    auth = auth_ui(sb)
    if not auth:
        st.stop()
    user_id = auth.user_id
else:
    if st.sidebar.button("Sign out"):
        try:
            sb.auth.sign_out()
        finally:
            st.rerun()
st.sidebar.caption(f"Signed in as user_id: {user_id}")

page = st.sidebar.radio("Navigate", PAGES, index=0)

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
if page == "Dashboard":
    kv_map = kv_read_many(user_id, DEFAULT_BUILDINGS)
    hq = get_level(kv_map, "HQ")

    # total hero power (legacy shared table, no owner filter)
    try:
        res = sb.table("heroes").select("power").execute()
        arr = pd.to_numeric(pd.DataFrame(res.data or []).get("power"), errors="coerce")
        total_power = int(arr.fillna(0).sum())
    except Exception:
        total_power = 0
    formatted_power = f"{total_power:,}"

    h_left, h_right = st.columns([1, 3])
    with h_left:
        try:
            st.image("frog.png", width=160)
        except Exception:
            st.write(":frog: (frog.png not found)")
    with h_right:
        st.markdown(f"""
        <div style='display:flex; align-items:center; height:160px;'>
          <div style='margin-left:15px;'>
            <h2 style='margin:0; font-weight:700;'>Shōckwave [FER]</h2>
            <div style='font-size:1.1rem; margin-top:6px;'>
              <strong>HQ Level:</strong>
              <span style='font-weight:700; font-size:1.2rem;'>{hq}</span>
              &nbsp;&nbsp;&nbsp;
              <strong>Total Hero Power:</strong>
              <span style='font-weight:700; font-size:1.2rem;'>{formatted_power}</span>
            </div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    col_teams, col_build, col_research = st.columns([1, 1, 1], gap="large")

    # Teams (dropdown + power, autosaved in buildings_kv)
    with col_teams:
        st.subheader("Teams")
        team_opts = ["Tank", "Air", "Missile", "Mixed"]

        def kv_get_simple(k: str, default: str = "") -> str:
            rows = kv_select("buildings_kv", user_id, [k])
            if rows:
                v = rows[0].get("value")
                return v if v is not None else default
            return default

        def kv_set_simple(k: str, v: str):
            kv_upsert("buildings_kv", user_id, [{"key": k, "value": v}])

        # Show 3 teams on the dashboard
        for i in range(1, 4):
            tkey = f"team{i}_type"
            pkey = f"team{i}_power"

            if tkey not in st.session_state:
                default_type = "Tank" if i == 1 else ("Air" if i == 2 else "Mixed")
                st.session_state[tkey] = kv_get_simple(tkey, default_type)
            if pkey not in st.session_state:
                st.session_state[pkey] = kv_get_simple(pkey, "")

            def _save_type(ii=i):
                kv_set_simple(f"team{ii}_type", st.session_state[f"team{ii}_type"])

            def _save_power(ii=i):
                cur = (st.session_state[f"team{ii}_power"] or "").strip()
                st.session_state[f"team{ii}_power"] = cur
                kv_set_simple(f"team{ii}_power", cur)

            sel_col, pow_col = st.columns([1.2, 1.4])
            with sel_col:
                st.selectbox(f"Team {i}", team_opts, key=tkey, on_change=_save_type)
            with pow_col:
                st.text_input("Power", key=pkey, placeholder="43.28M", on_change=_save_power)

    # Buildings (🔨 / 🧱 tracking, owner-scoped)
    with col_build:
        st.subheader("Buildings")
        st.caption("What’s Cookin’")
        rows = tracking_select("buildings_tracking", user_id, "name, upgrading, next")
        up_set = {r["name"] for r in rows if r.get("upgrading")}
        next_set = {r["name"] for r in rows if r.get("next")}

        if up_set:
            for nm in sorted(up_set):
                cur_lvl = get_level(kv_map, nm)
                st.markdown(f"🔨 **{nm}** ({cur_lvl} → {cur_lvl + 1})")
        else:
            st.markdown("🔨 _Nothing upgrading_")

        st.caption("On Deck")
        if next_set:
            for nm in sorted(next_set):
                st.markdown(f"🧱 **{nm}**")
        else:
            st.markdown("🧱 _Nothing on deck_")

    # Research quick lists (shared research_data + owner-scoped research_tracking for flags)
    with col_research:
        st.subheader("Research")

        # ---- Overview chips (per category) ----
        try:
            res = sb.table("research_data").select("category,level,max_level").execute()
            df = pd.DataFrame(res.data or [])
            if not df.empty:
                df["category"] = df["category"].fillna("Other").astype(str)
                df["level"] = pd.to_numeric(df["level"], errors="coerce").fillna(0)
                df["max_level"] = pd.to_numeric(df["max_level"], errors="coerce").fillna(0)

                cats: List[Tuple[str, float]] = []
                for cat, g in df.groupby("category", sort=True):
                    valid = g["max_level"] > 0
                    if valid.any():
                        pct = float(
                            (np.minimum(g.loc[valid, "level"], g.loc[valid, "max_level"])
                             / g.loc[valid, "max_level"]).mean() * 100.0
                        )
                    else:
                        pct = 0.0
                    cats.append((cat, round(pct, 1)))

                st.caption("Overview")
                chip_cols = st.columns(3)
                for i, (cat, pct) in enumerate(cats):
                    with chip_cols[i % 3]:
                        st.markdown(f"**{cat}**")
                        st.markdown(pct_chip(pct, ""), unsafe_allow_html=True)
                st.write("")
            else:
                st.caption("Overview (no research data)")
        except Exception:
            st.caption("Overview (no research data)")

        try:
            res = sb.table("research_data").select("category,name,level,tracked,priority,order_index").execute()
            rows = res.data or []
        except Exception:
            rows = []

        from collections import defaultdict
        hot_by = defaultdict(list)
        star_by = defaultdict(list)
        for r in rows:
            cat = (r.get("category") or "Other").strip()
            if bool(r.get("tracked")): hot_by[cat].append(r)
            if bool(r.get("priority")): star_by[cat].append(r)

        st.caption("What’s Cookin’")
        if any(hot_by.values()):
            for cat in sorted(hot_by.keys()):
                items = sorted(hot_by[cat], key=lambda x: (x.get("order_index") is None, x.get("order_index"), x.get("name") or ""))
                labels = []
                for r in items:
                    nm = (r.get("name") or "").strip(); lvl = r.get("level")
                    arrow = f" ({int(lvl)} → {int(lvl)+1})" if isinstance(lvl, (int, float)) else ""
                    labels.append(f"{nm}{arrow}")
                st.markdown(f"🔥 **{cat}** — " + " · ".join(labels))
        else:
            st.markdown("🔥 _Nothing in progress_")

        st.caption("On Deck")
        if any(star_by.values()):
            for cat in sorted(star_by.keys()):
                items = sorted(star_by[cat], key=lambda x: (x.get("order_index") is None, x.get("order_index"), x.get("name") or ""))
                st.markdown(f"⭐ **{cat}** — " + " · ".join([(r.get("name") or "").strip() for r in items]))
        else:
            st.markdown("⭐ _Nothing on deck_")

    st.divider()
    # ===== Building Progress (dynamic, covers all core groups) =====
    st.subheader("Building Progress")

    def pct_of_hq_sum(base: str, series_key: str) -> float:
        if hq <= 0:
            return 0.0
        rng = SERIES[series_key]
        total = sum_series(kv_map, base, rng)
        denom = len(rng) * hq
        return (total / denom) * 100.0 if denom > 0 else 0.0

    def pct_of_hq_single(name: str) -> float:
        if hq <= 0:
            return 0.0
        return (get_level(kv_map, name) / hq) * 100.0

    # Define groups → function that returns % complete
    groups = [
        ("Tech Center",          lambda: pct_of_hq_sum("Tech Center", "Tech Center")),
        ("Barracks",             lambda: pct_of_hq_sum("Barracks", "Barracks")),
        ("Hospital",             lambda: pct_of_hq_sum("Hospital", "Hospital")),
        ("Training Grounds",     lambda: pct_of_hq_sum("Drill Ground", "Drill Ground")),
        ("Recon Plane",          lambda: pct_of_hq_sum("Recon Plane", "Recon Plane")),
        ("Gold Mine",            lambda: pct_of_hq_sum("Gold Mine", "Gold Mine")),
        ("Iron Mine",            lambda: pct_of_hq_sum("Iron Mine", "Iron Mine")),
        ("Farmland",             lambda: pct_of_hq_sum("Farmland", "Farmland")),
        ("Oil Well",             lambda: pct_of_hq_sum("Oil Well", "Oil Well")),
        ("Smelter",              lambda: pct_of_hq_sum("Smelter", "Smelter")),
        ("Training Base",        lambda: pct_of_hq_sum("Training Base", "Training Base")),
        ("Material Workshop",    lambda: pct_of_hq_sum("Material Workshop", "Material Workshop")),
        ("Centers (Tank/Air/Missile)", lambda: (
            0.0 if hq <= 0 else (sum(get_level(kv_map, c) for c in CENTER_NAMES) / (len(CENTER_NAMES) * hq) * 100.0)
        )),
        ("Emergency Center",     lambda: pct_of_hq_single("Emergency Center")),
        ("Alert Tower",          lambda: pct_of_hq_single("Alert Tower")),
        ("Wall",                 lambda: pct_of_hq_single("Wall")),
        ("HQ",                   lambda: 100.0 if hq > 0 else 0.0),
        ("Warehouses (Coin/Food/Iron)", lambda: (
            0.0 if hq <= 0 else (
                (get_level(kv_map, "Coin Vault") + get_level(kv_map, "Food Warehouse") + get_level(kv_map, "Iron Warehouse"))
                / (3 * hq) * 100.0
            )
        )),
    ]

    # Render in 3 columns
    col_a, col_b, col_c = st.columns(3)
    cols = [col_a, col_b, col_c]
    for idx, (label, fn) in enumerate(groups):
        with cols[idx % 3]:
            st.markdown(f"**{label}**")
            st.markdown(pct_chip(fn(), ""), unsafe_allow_html=True)


# --------------------------------------------------
# BUILDINGS PAGE
# --------------------------------------------------
elif page == "Buildings":
    st.header("Buildings")
    st.write("Standard table. Only updates rows you actually change. No undo/redo.")

    current_map = {k: v for k, v in kv_read_many(user_id, DEFAULT_BUILDINGS).items()}
    rows = [{"name": b, "level": int((current_map.get(b, {}).get("value") or 0))} for b in DEFAULT_BUILDINGS]
    df = pd.DataFrame(rows)

    # tracking sets
    tr_rows = tracking_select("buildings_tracking", user_id, "name, upgrading, next")
    up_set = {r["name"] for r in tr_rows if r.get("upgrading")}
    next_set = {r["name"] for r in tr_rows if r.get("next")}

    df["hammer"] = df["name"].astype(str).isin(up_set)
    df["brick"] = df["name"].astype(str).isin(next_set)

    up_count, next_count = int(df["hammer"].sum()), int(df["brick"].sum())
    if up_count or next_count:
        st.caption(f"🔨 {up_count} upgrading | 🧱 {next_count} next")

    editor_cols = ["hammer", "brick", "name", "level"]
    edited = st.data_editor(
        df[editor_cols],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "hammer": st.column_config.CheckboxColumn("🔨"),
            "brick": st.column_config.CheckboxColumn("🧱"),
            "name": st.column_config.TextColumn("Building", width="large", required=True),
            "level": st.column_config.NumberColumn("Level", min_value=0, max_value=60, step=1),
        },
        hide_index=True,
        key="buildings_editor",
    )

    # persist tracking changes
    all_names = set(edited["name"]) if not edited.empty else set()
    payload = []
    for nm in all_names:
        payload.append({"name": nm, "upgrading": bool(nm in set(edited.loc[edited["hammer"], "name"])), "next": bool(nm in set(edited.loc[edited["brick"], "name"]))})
    if payload:
        tracking_upsert("buildings_tracking", user_id, payload, conflict=f"{ID_COL},name")

    colA, colB = st.columns(2)
    with colA:
        if st.button("Save changes", use_container_width=True):
            try:
                changes = []
                for _, r in edited.iterrows():
                    key = str(r["name"]).strip(); lvl = int(r.get("level", 0) or 0)
                    if str(current_map.get(key, {}).get("value", "")) != str(lvl):
                        changes.append({"key": key, "value": str(lvl)})
                if changes:
                    kv_upsert("buildings_kv", user_id, changes)
                st.success("Saved")
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
    with colB:
        if st.button("Reload from Supabase", use_container_width=True):
            st.rerun()

# --------------------------------------------------
# HEROES PAGE (shared table, unchanged)
# --------------------------------------------------
elif page == "Heroes":
    st.header("Heroes")
    try:
        cols = (
            "id,name,level,power,"
            "rail_gun,rail_gun_stars,armor,armor_stars,data_chip,data_chip_stars,radar,radar_stars,"
            "weapon,weapon_level,max_skill_level,skill1,skill2,skill3,"
            "type,role,team,updated_at"
        )
        res = sb.table("heroes").select(cols).order("power", desc=True).execute()
        rows = res.data or []
        if not rows:
            st.warning("No heroes found in table 'heroes'.")
        else:
            df = pd.DataFrame(rows)
            num_cols = ["power","level","rail_gun","armor","data_chip","radar","weapon_level","max_skill_level","skill1","skill2","skill3"]
            for c in num_cols:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            if "power" in df.columns:
                df = df.sort_values("power", ascending=False, na_position="last")
            display_cols = [c for c in [
                "name","power","level","type","role","team",
                "rail_gun","rail_gun_stars","armor","armor_stars",
                "data_chip","data_chip_stars","radar","radar_stars",
                "weapon","weapon_level","max_skill_level","skill1","skill2","skill3",
                "updated_at"
            ] if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True)
    except Exception as e:
        st.error("Could not load heroes (check table).")
        st.code(str(e))

# --------------------------------------------------
# ADD/UPDATE HERO PAGE (shared table, unchanged)
# --------------------------------------------------
elif page == "Add or Update Hero":
    st.header("Add or Update Hero")
    try:
        res = sb.table("heroes").select("id,name,power").order("power", desc=True).execute()
        hero_rows = res.data or []
    except Exception as e:
        st.error("Could not load heroes for selector.")
        st.code(str(e))
        hero_rows = []

    names = ["<Create new>"] + [h.get("name", "") for h in hero_rows]
    selected = st.selectbox("Choose hero", names, index=0)

    current = None
    if selected != "<Create new>":
        cur = next((h for h in hero_rows if h.get("name") == selected), None)
        if cur and cur.get("id"):
            try:
                full = sb.table("heroes").select(
                    "id,name,level,power,"
                    "rail_gun,rail_gun_stars,armor,armor_stars,data_chip,data_chip_stars,radar,radar_stars,"
                    "weapon,weapon_level,max_skill_level,skill1,skill2,skill3,"
                    "type,role,team,updated_at"
                ).eq("id", cur["id"]).maybe_single().execute().data
                current = full or cur
            except Exception:
                current = cur

    def v(d, k, default=None):
        return (d.get(k) if d else default)

    colA, colB, colC = st.columns(3)
    with colA:
        name = st.text_input("Name *", value=v(current, "name", "") or "")
        type_ = st.text_input("Type", value=v(current, "type", "") or "")
        role = st.selectbox("Role", ["", "Attack", "Defense", "Support"], index=0)
        team = st.text_input("Team", value=v(current, "team", "") or "")

    with colB:
        level = st.number_input("Level", min_value=0, max_value=200, value=int(v(current, "level", 0) or 0), step=1)
        p_in = v(current, "power", 0)
        try: p_val = int(float(p_in)) if p_in is not None else 0
        except Exception: p_val = 0
        power = st.number_input("Power", min_value=0, step=1, value=int(p_val))
        weapon = st.checkbox("Weapon?", value=bool(v(current, "weapon", False)))
        weapon_level = st.number_input("Weapon Level", min_value=0, max_value=200, value=int(v(current, "weapon_level", 0) or 0), step=1)
        max_skill_level = st.number_input("Max Skill Level", min_value=0, max_value=40, value=int(v(current, "max_skill_level", 0) or 0), step=1)
        skill1 = st.number_input("Skill 1", min_value=0, max_value=40, value=int(v(current, "skill1", 0) or 0), step=1)
        skill2 = st.number_input("Skill 2", min_value=0, max_value=40, value=int(v(current, "skill2", 0) or 0), step=1)
        skill3 = st.number_input("Skill 3", min_value=0, max_value=40, value=int(v(current, "skill3", 0) or 0), step=1)

    with colC:
        rail_gun = st.number_input("Rail Gun", min_value=0, max_value=200, value=int(v(current, "rail_gun", 0) or 0), step=1)
        rail_gun_stars = st.text_input("Rail Gun Stars", value=v(current, "rail_gun_stars", "") or "")
        armor = st.number_input("Armor", min_value=0, max_value=200, value=int(v(current, "armor", 0) or 0), step=1)
        armor_stars = st.text_input("Armor Stars", value=v(current, "armor_stars", "") or "")
        data_chip = st.number_input("Data Chip", min_value=0, max_value=200, value=int(v(current, "data_chip", 0) or 0), step=1)
        data_chip_stars = st.text_input("Data Chip Stars", value=v(current, "data_chip_stars", "") or "")
        radar = st.number_input("Radar", min_value=0, max_value=200, value=int(v(current, "radar", 0) or 0), step=1)
        radar_stars = st.text_input("Radar Stars", value=v(current, "radar_stars", "") or "")

    st.divider()

    errors = []
    if not name.strip():
        errors.append("Name is required.")

    def _to_int(x, default=0):
        try:
            if x is None or str(x).strip() == "":
                return default
            return int(float(x))
        except Exception:
            return default

    def _to_float(x, default=0.0):
        try:
            if x is None or str(x).strip() == "":
                return default
            return float(x)
        except Exception:
            return default

    if errors:
        for e in errors: st.error(e)
    else:
        col_save, col_delete = st.columns([1, 1])
        hero_payload = {
            "name": name.strip(),
            "type": (type_ or "").strip(),
            "role": (role or "").strip(),
            "team": (team or "").strip(),
            "level": _to_int(level, 0),
            "power": _to_float(power, 0.0),
            "weapon": bool(weapon),
            "weapon_level": _to_int(weapon_level, 0),
            "max_skill_level": _to_int(max_skill_level, 0),
            "skill1": _to_int(skill1, 0), "skill2": _to_int(skill2, 0), "skill3": _to_int(skill3, 0),
            "rail_gun": _to_int(rail_gun, 0), "rail_gun_stars": (rail_gun_stars or "").strip(),
            "armor": _to_int(armor, 0), "armor_stars": (armor_stars or "").strip(),
            "data_chip": _to_int(data_chip, 0), "data_chip_stars": (data_chip_stars or "").strip(),
            "radar": _to_int(radar, 0), "radar_stars": (radar_stars or "").strip(),
        }
        with col_save:
            if st.button("Save", use_container_width=True):
                try:
                    if current and current.get("id"):
                        sb.table("heroes").update(hero_payload).eq("id", current["id"]).execute()
                    else:
                        sb.table("heroes").insert(hero_payload).execute()
                    st.success("Hero saved"); st.rerun()
                except Exception as e:
                    st.error(f"Save failed: {e}")
        with col_delete:
            if current and current.get("id"):
                if st.button("Delete", type="secondary", use_container_width=True):
                    try:
                        sb.table("heroes").delete().eq("id", current["id"]).execute()
                        st.success("Hero deleted"); st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")
            else:
                st.caption("Select an existing hero to enable Delete.")

# --------------------------------------------------
# RESEARCH PAGE (shared research_data + owner-scoped tracking)
# --------------------------------------------------
elif page == "Research":
    st.header("Research")
    st.caption("Click a category to expand. Edit Level and Max Level. Use 🔥 for in-progress and ⭐ for next up.")

    RESEARCH_CATEGORIES = [
        "Development", "Economy", "Hero", "Units", "Squad 1", "Squad 2", "Squad 3", "Squad 4",
        "Alliance Duel", "Intercity Truck", "Special Forces", "Siege to Seize", "Defense Fortifications",
        "Tank Mastery", "Missile Mastery", "Air Mastery", "The Age of Oil", "Tactical Weapon",
    ]

    def research_load(category: str):
        try:
            res = (
                sb.table("research_data")
                  .select("id, name, level, max_level, order_index")
                  .eq("category", category)
                  .order("order_index")
                  .execute()
            )
            rows = res.data or []
        except Exception:
            rows = []
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=["id","name","level","max_level","order_index"])
        for c in ["level","max_level","order_index"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        return df

    def research_save(category: str, edited_df: pd.DataFrame):
        payload = []
        for _, r in edited_df.iterrows():
            name = str(r.get("name", "")).strip()
            if not name: continue
            row = {"category": category, "name": name, "level": int(r.get("level", 0) or 0), "max_level": int(r.get("max_level", 0) or 0) or 10}
            rid = r.get("id");
            if isinstance(rid, str) and rid: row["id"] = rid
            if "order_index" in edited_df.columns and pd.notna(r.get("order_index")):
                try: row["order_index"] = int(r.get("order_index"))
                except Exception: pass
            payload.append(row)
        if payload: sb.table("research_data").upsert(payload).execute()

    def research_completion(df: pd.DataFrame) -> float:
        if df is None or df.empty: return 0.0
        levels = pd.to_numeric(df.get("level"), errors="coerce").fillna(0)
        maxes  = pd.to_numeric(df.get("max_level"), errors="coerce").fillna(0)
        valid = maxes > 0
        if not valid.any(): return 0.0
        clamped = np.minimum(levels[valid], maxes[valid])
        frac = (clamped / maxes[valid]).fillna(0)
        return float(round(frac.mean() * 100, 1))

    def tracking_load_sets(category: str) -> Tuple[set, set]:
        try:
            res = sb.table("research_tracking").select(f"name, tracked, priority, {ID_COL}").eq("category", category)
            res = _eq_owner(res, user_id).execute()
            rows = res.data or []
            tracked = {r["name"] for r in rows if r.get("tracked")}
            starred = {r["name"] for r in rows if r.get("priority")}
            return tracked, starred
        except Exception:
            return set(), set()

    def tracking_save_from_editor(category: str, edited_df: pd.DataFrame):
        payload = []
        for _, r in edited_df.iterrows():
            name = str(r.get("name", "")).strip()
            if not name: continue
            payload.append({"category": category, "name": name, "tracked": bool(r.get("track", False)), "priority": bool(r.get("star", False))})
        if payload:
            tracking_upsert("research_tracking", user_id, payload, conflict=f"{ID_COL},category,name")

    for cat in RESEARCH_CATEGORIES:
        df = research_load(cat)
        tracked_set, starred_set = tracking_load_sets(cat)
        if "track" not in df.columns: df["track"] = df["name"].astype(str).isin(tracked_set)
        if "star" not in df.columns:  df["star"]  = df["name"].astype(str).isin(starred_set)
        pct = research_completion(df)
        icon = "🟢" if pct >= 90 else ("🟠" if pct >= 50 else "🔴")
        extras = (" 🔥" if tracked_set else "") + (" ⭐" if starred_set else "")
        label = f"{icon} {cat} — {pct:.1f}% complete{extras}"
        with st.expander(label, expanded=False):
            st.markdown(f"**Tree Completion:** {pct:.1f}%")
            editor_cols = ["track","star","name","level","max_level"] + (["id"] if "id" in df.columns else [])
            show = df[editor_cols].copy() if not df.empty else pd.DataFrame(columns=editor_cols)
            edited = st.data_editor(
                show,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "track": st.column_config.CheckboxColumn(""),
                    "star": st.column_config.CheckboxColumn("⭐"),
                    "name": st.column_config.TextColumn("Research Name", width="large", required=True),
                    "level": st.column_config.NumberColumn("Level", min_value=0, max_value=999, step=1),
                    "max_level": st.column_config.NumberColumn("Max Level", min_value=1, max_value=999, step=1),
                    "id": st.column_config.Column("id", disabled=True, width="small") if "id" in show.columns else None,
                },
                hide_index=True,
                key=f"research_editor_{cat}",
            )
            tracking_save_from_editor(cat, edited)
            colA, colB, colC = st.columns([1, 1, 6])
            with colA:
                if st.button("Save changes", key=f"save_{cat}", type="primary", use_container_width=True):
                    try:
                        to_save = edited.drop(columns=[c for c in ["track","star"] if c in edited.columns])
                        research_save(cat, to_save)
                        st.success("Saved"); st.rerun()
                    except Exception as e:
                        st.error(f"Save failed: {e}")
            with colB:
                if st.button("Reload", key=f"reload_{cat}", use_container_width=True):
                    st.rerun()
            with colC:
                st.markdown(f"**Preview Completion:** {research_completion(edited):.1f}%")

# --------------------------------------------------
# Footer
# --------------------------------------------------
st.caption("Made with love. Drink a beer.")
