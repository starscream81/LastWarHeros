from __future__ import annotations

# LastWarHeros — Streamlit app with Supabase auth (per-session), per-user RLS,
# profile (name + avatar upload), and per-user research/hero power.

import os
import time
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import streamlit as st
from supabase import Client, create_client

# ---------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------
st.set_page_config(page_title="LastWarHeros", layout="wide")

# ---------------------------------------------------------------------
# Per-session Supabase client (fixes auth leakage between users)
# ---------------------------------------------------------------------
def _load_supabase_creds() -> Tuple[str, str]:
    url = st.secrets.get("supabase_url") or st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("supabase_key") or st.secrets.get("SUPABASE_ANON_KEY")
    if not url or not key:
        sec = st.secrets.get("supabase", {})
        url = url or sec.get("url")
        key = key or sec.get("anon_key")
    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY.")
        st.stop()
    return url, key

def get_sb() -> Client:
    """Return a Supabase client isolated to this Streamlit session."""
    if "sb_client" not in st.session_state:
        url, key = _load_supabase_creds()
        st.session_state["sb_client"] = create_client(url, key)
    return st.session_state["sb_client"]

def reset_auth_session():
    sb = st.session_state.get("sb_client")
    if sb:
        try:
            sb.auth.sign_out()
        except Exception:
            pass
    for k in ("sb_client", "user_id", "auth_user", "_sb_tokens"):
        st.session_state.pop(k, None)

# ---------------------------------------------------------------------
# Constants / config
# ---------------------------------------------------------------------
ID_COL = "user_id"

base_buildings = [
    "HQ", "Wall",
    "Tech Center 1-3",
    "Barracks 1-4",
    "Drill Ground 1-4",
    "Hospital 1-4", "Emergency Center",
    "Tank Center", "Air Center", "Missile Center",   # fixed "Aircraft" -> "Air"
    "Alert Tower", "Recon Plane 1-3",
    "Coin Vault", "Food Warehouse", "Iron Warehouse",
    "Gold Mine 1-5", "Iron Mine 1-5", "Farmland 1-5", "Oil Well 1-5",
    "Smelter 1-5", "Training Base 1-5", "Material Workshop 1-5",
    "Alliance Center", "Builder's Hut", "Tavern", "Technical Institute",
    "Drone Parts Workshop", "Chip Lab", "Component Factory", "Gear Factory",
]

ALIASES = {
    "oil wall": "Oil Well",
    "coil vault": "Coin Vault",
    "farm warehouse": "Food Warehouse",
    "tactical institute": "Technical Institute",
    "training grounds": "Drill Ground",
}

def expand_ranges_in_order(names: List[str]) -> List[str]:
    out: List[str] = []
    for n in names:
        parts = n.rsplit(" ", 1)
        if len(parts) == 2 and "-" in parts[1]:
            head, rng = parts[0], parts[1]
            try:
                lo, hi = [int(x) for x in rng.split("-")]
                out += [f"{head} {i}" for i in range(lo, hi + 1)]
            except Exception:
                out.append(n)
        else:
            out.append(n)
    return out

DEFAULT_BUILDINGS = expand_ranges_in_order(base_buildings)

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
CENTER_NAMES = ["Tank Center", "Air Center", "Missile Center"]  # fixed

RESEARCH_CATEGORIES = [
    "Development", "Economy", "Hero", "Units",
    "Squad 1", "Squad 2", "Squad 3", "Squad 4",
    "Alliance Duel", "Intercity Truck", "Special Forces", "Siege to Seize",
    "Defense Fortifications", "Tank Mastery", "Missile Mastery", "Air Mastery",
    "The Age of Oil", "Tactical Weapon",
]

# ---------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------
def pct_chip(pct: float, label: str = "") -> str:
    p = max(0, min(100, int(round(pct))))
    return (
        f"<div style='display:inline-block;padding:6px 10px;border-radius:12px;"
        f"margin-bottom:10px;background:linear-gradient(90deg, rgba(255,120,120,1) 0%,"
        f" rgba(120,200,120,1) {p}%, rgba(235,235,235,1) {p}%);"
        f"color:black;font-weight:700;box-shadow:0 1px 4px rgba(0,0,0,0.08);'>"
        f"{label}{p}%</div>"
    )

# ---------------------------------------------------------------------
# RPC + bootstrap
# ---------------------------------------------------------------------
def seed_user_research_for_user(user_id: str) -> None:
    sb = get_sb()
    try:
        sb.rpc("seed_user_research", {"p_user_id": user_id}).execute()
    except Exception as e:
        # Non-fatal
        st.warning(f"Seeding user_research failed: {e}")

def bootstrap_user_if_needed(uid: str):
    sb = get_sb()
    # 1) buildings_kv zeros
    try:
        res = sb.table("buildings_kv").select("key", count="exact").eq(ID_COL, uid).limit(1).execute()
        has_any = bool((getattr(res, "count", None) or 0) > 0 or (res.data or []))
        if not has_any:
            seed = [{"key": k, "value": "0", ID_COL: uid} for k in DEFAULT_BUILDINGS]
            sb.table("buildings_kv").upsert(seed, on_conflict=f"{ID_COL},key").execute()
    except Exception:
        pass

    # 2) research_data seed rows (so chips don’t break)
    try:
        res = sb.table("research_data").select("id", count="exact").eq(ID_COL, uid).limit(1).execute()
        has_any = bool((getattr(res, "count", None) or 0) > 0 or (res.data or []))
        if not has_any:
            seed = []
            for cat in RESEARCH_CATEGORIES:
                seed.append({ID_COL: uid, "category": cat, "name": "_seed_", "level": 0, "max_level": 0, "order_index": 0})
            sb.table("research_data").upsert(seed).execute()
    except Exception:
        pass

# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
@dataclass
class AuthResult:
    user_id: str
    email: str

def _oauth_button(provider: str, label: str):
    sb = get_sb()
    if st.button(label, use_container_width=True, key=f"oauth::{provider}"):
        try:
            redirect_to = os.getenv("OAUTH_REDIRECT") or "http://localhost:8501"
            sb.auth.sign_in_with_oauth({"provider": provider, "options": {"redirect_to": redirect_to}})
            st.stop()
        except Exception as e:
            st.error(f"OAuth start failed: {e}")

def auth_ui() -> Optional[AuthResult]:
    sb = get_sb()
    st.sidebar.header("Sign in")
    tabs = st.sidebar.tabs(["Password", "Email code", "Google / GitHub"])

    with tabs[0]:
        with st.form("auth_pw"):
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            c1, c2 = st.columns(2)
            in_btn = c1.form_submit_button("Sign in")
            up_btn = c2.form_submit_button("Create account")
        if in_btn:
            try:
                data = sb.auth.sign_in_with_password({"email": email, "password": pw})
#               Save session tokens for this tab if present
                if getattr(data, "session", None):
                    st.session_state["_sb_tokens"] = {
                        "access_token": data.session.access_token,
                        "refresh_token": data.session.refresh_token,
                    }
                return AuthResult(user_id=data.user.id, email=data.user.email or "")

            except Exception as e:
                st.error(f"Sign in failed: {e}")
        if up_btn:
            try:
                sb.auth.sign_up({"email": email, "password": pw})
                st.success("Account created. Check email if confirmation is required.")
            except Exception as e:
                st.error(f"Sign up failed: {e}")

    with tabs[1]:
        with st.form("auth_otp"):
            email = st.text_input("Email")
            c1, c2 = st.columns(2)
            send = c1.form_submit_button("Send code")
            have = c2.form_submit_button("I have a code")
        if send:
            try:
                sb.auth.sign_in_with_otp({"email": email, "should_create_user": True})
                st.success("Code sent.")
            except Exception as e:
                st.error(f"Send failed: {e}")
        if have:
            code = st.text_input("6-digit code")
            if st.button("Verify"):
                try:
                    data = sb.auth.verify_otp({"email": email, "token": code, "type": "email"})
                    return AuthResult(user_id=data.user.id, email=data.user.email or "")
                except Exception as e:
                    st.error(f"Verification failed: {e}")

    with tabs[2]:
        st.caption("Enable providers in Supabase first.")
        _oauth_button("google", "Continue with Google")
        _oauth_button("github", "Continue with GitHub")

    return None

def get_current_user() -> Tuple[Optional[str], Optional[dict]]:
    sb = get_sb()
    try:
        resp = sb.auth.get_user()
        if resp and resp.user:
            uid = resp.user.id
            # seed user_research on first login
            seed_user_research_for_user(uid)
            return uid, resp.user.model_dump()  # type: ignore
    except Exception:
        pass
    return None, None

# ---------------------------------------------------------------------
# Owner / KV helpers (RLS-safe)
# ---------------------------------------------------------------------
def _eq_owner(q, uid: str):
    return q.eq(ID_COL, uid)

def owner_select(table: str, columns: str, user_id: str, order_by: Optional[str] = None, desc: bool = False):
    sb = get_sb()
    q = sb.from_(table).select(columns)
    q = _eq_owner(q, user_id)
    if order_by:
        q = q.order(order_by, desc=desc)
    return q.execute().data

def owner_upsert(table: str, payload: Union[dict, List[dict]], user_id: str):
    sb = get_sb()
    rows = [payload] if isinstance(payload, dict) else list(payload or [])
    for r in rows:
        r[ID_COL] = user_id
    conflict = f"{ID_COL},category,name" if table == "research_data" else f"{ID_COL},name"
    sb.table(table).upsert(rows, on_conflict=conflict).execute()

def kv_select(table: str, uid: str, keys: Optional[Union[str, List[str]]] = None) -> List[Dict[str, Any]]:
    sb = get_sb()
    q = sb.table(table).select("key,value,updated_at")
    q = _eq_owner(q, uid)
    if keys:
        if isinstance(keys, list):
            q = q.in_("key", keys)
        else:
            q = q.in_("key", [keys])
    try:
        return q.execute().data or []
    except Exception:
        # legacy fallback without user_id column
        q = sb.table(table).select("key,value,updated_at")
        if keys:
            if isinstance(keys, list):
                q = q.in_("key", keys)
            else:
                q = q.in_("key", [keys])
        return q.execute().data or []

def kv_upsert(table: str, uid: str, payload: Union[dict, List[dict]]):
    sb = get_sb()
    rows = [payload] if isinstance(payload, dict) else list(payload or [])
    for r in rows:
        r[ID_COL] = uid
    sb.table(table).upsert(rows, on_conflict=f"{ID_COL},key").execute()

def load_kv_map(table: str, uid: str) -> Dict[str, str]:
    rows = kv_select(table, uid, None)
    return {r.get("key"): r.get("value") for r in (rows or [])}

def kv_get_json(uid: str, key: str, default):
    try:
        rows = kv_select("buildings_kv", uid, key)
        if rows and rows[0].get("value"):
            return json.loads(rows[0]["value"])
    except Exception:
        pass
    return default

def kv_set_json(uid: str, key: str, obj):
    kv_upsert("buildings_kv", uid, [{"key": key, "value": json.dumps(obj)}])

# ---------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------
def load_profile(uid: str) -> Dict[str, Any]:
    sb = get_sb()
    try:
        data = (
            sb.table("profiles")
            .select("display_name,avatar_url")
            .eq(ID_COL, uid)
            .maybe_single()
            .execute()
            .data
        )
        if data:
            return data or {}
    except Exception:
        pass

    # fallback to KV
    try:
        rows = kv_select("buildings_kv", uid, ["display_name", "avatar_url"])
        kv = {r.get("key"): r.get("value") for r in rows or []}
        out = {}
        if kv.get("display_name"):
            out["display_name"] = kv.get("display_name")
        if kv.get("avatar_url"):
            out["avatar_url"] = kv.get("avatar_url")
        return out
    except Exception:
        return {}

def save_profile(uid: str, display_name: Optional[str] = None, avatar_url: Optional[str] = None) -> bool:
    sb = get_sb()
    obj = {ID_COL: uid}
    if display_name is not None:
        obj["display_name"] = display_name
    if avatar_url is not None:
        obj["avatar_url"] = avatar_url

    try:
        sb.table("profiles").upsert(obj, on_conflict=ID_COL).execute()
        return True
    except Exception:
        pass

    try:
        kv_payload = []
        if display_name is not None:
            kv_payload.append({"key": "display_name", "value": str(display_name)})
        if avatar_url is not None:
            kv_payload.append({"key": "avatar_url", "value": str(avatar_url)})
        if kv_payload:
            kv_upsert("buildings_kv", uid, kv_payload)
        return True
    except Exception:
        return False

def upload_avatar(uid: str, file) -> Optional[str]:
    sb = get_sb()
    import mimetypes
    try:
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp"]:
            ext = ".png"
        mime = mimetypes.guess_type(file.name)[0] or ("image/png" if ext == ".png" else "application/octet-stream")
        path = f"{uid}/avatar_{int(time.time())}{ext}"
        data = file.read()
        options = {"contentType": mime, "cacheControl": "3600", "upsert": "true"}
        sb.storage.from_("avatars").upload(path, data, options)
        url = sb.storage.from_("avatars").get_public_url(path)
        return url
    except Exception as e:
        st.warning(f"Avatar upload failed: {e}")
        return None

# ---------------------------------------------------------------------
# Research helpers
# ---------------------------------------------------------------------
def load_research_for_user(uid: str) -> pd.DataFrame:
    sb = get_sb()
    try:
        catalog = sb.table("research_catalog").select("name,category,max_level,order_index").execute().data or []
    except Exception:
        catalog = []
    cdf = pd.DataFrame(catalog)

    try:
        user_rows = sb.table("user_research").select("name,level,tracked,priority").eq("user_id", uid).execute().data or []
    except Exception:
        user_rows = []
    udf = pd.DataFrame(user_rows)

    if cdf.empty:
        return pd.DataFrame(columns=["name","category","max_level","order_index","level","tracked","priority"])

    if udf.empty:
        cdf["level"] = 0
        cdf["tracked"] = False
        cdf["priority"] = False
        return cdf

    df = cdf.merge(udf, on="name", how="left", suffixes=("","_u"))
    df["level"] = pd.to_numeric(df["level"], errors="coerce").fillna(0).astype(int)
    df["tracked"] = df["tracked"].fillna(False).astype(bool)
    df["priority"] = df["priority"].fillna(False).astype(bool)
    df["order_index"] = pd.to_numeric(df.get("order_index"), errors="coerce").fillna(0).astype(int)
    return df

# ---------------------------------------------------------------------
# Restore saved session tokens for this browser tab
# ---------------------------------------------------------------------
sb = get_sb()
_tokens = st.session_state.get("_sb_tokens")
if _tokens:
    try:
        sb.auth.set_session(_tokens["access_token"], _tokens["refresh_token"])
    except Exception:
        # If refresh token is expired or invalid, remove it
        st.session_state.pop("_sb_tokens", None)

# ---------------------------------------------------------------------
# AUTH GATE — ensure user_id is session-scoped
# ---------------------------------------------------------------------
user_id: Optional[str] = st.session_state.get("user_id")
auth_user = st.session_state.get("auth_user")

if not user_id:
    uid, user = get_current_user()
    if uid:
        st.session_state["user_id"] = uid
        st.session_state["auth_user"] = user
        user_id, auth_user = uid, user
    else:
        ar = auth_ui()
        if not ar:
            st.stop()
        st.session_state["user_id"] = ar.user_id
        st.session_state["auth_user"] = {"email": ar.email}
        user_id = ar.user_id
        auth_user = st.session_state["auth_user"]

# ---------------------------------------------------------------------
# SIDEBAR (single source of truth; unique keys per session)
# ---------------------------------------------------------------------
_sb_prefix = f"sb_{str(user_id)[:8]}_"
with st.sidebar:
    st.title("LastWarHeros")

    if st.button("Sign out", key=_sb_prefix + "signout"):
        reset_auth_session()
        st.rerun()

    st.caption(f"Signed in as: {user_id}")

    # Ensure safe defaults for new users
    bootstrap_user_if_needed(user_id)

    PAGES = [
        "Dashboard",
        "Buildings",
        "Heroes",
        "Add or Update Hero",
        "Research",
        "Update Player Name",
        "Update Profile Picture",
    ]
    page = st.radio("Navigate", PAGES, index=0, key=_sb_prefix + "nav")

    st.markdown(
        """
        <hr style='margin-top: 1.5em; margin-bottom: 1em; border: 1px solid #333;'/>
        <style>
          .beer-button {
            background-color: #f5c518;
            color: black;
            border: none;
            padding: 10px 24px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.3s ease;
            text-decoration: none;
            display: inline-block;
            margin-top: 0.5em;
            margin-bottom: 0.5em;
          }
          .beer-button:hover { background-color: #ffd84d; }
          .beer-container { text-align: center; margin-top: 0.5em; margin-bottom: 1.5em; }
        </style>
        <div class='beer-container'>
          <a class='beer-button' href='https://paypal.me/KMahana' target='_blank'>
            🍺 Buy Me a Beer
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("🔒 Privacy Policy", expanded=False):
        st.markdown(
            """
            **Complete Privacy Policy for LastWarHeros**

            **1. Introduction and Data Controller**  
            This Privacy Policy explains how Kevin Mahana ("we," "us," or "our") processes the personal data of users of the LastWarHeros application ("the Service").  
            We are committed to protecting your privacy in compliance with the EU's General Data Protection Regulation (GDPR) and relevant local laws.  

            **Data Controller:** Kevin Mahana, Germany  
            **Contact:** [lastwarheros.underfeed182@passmail.com](mailto:lastwarheros.underfeed182@passmail.com)  

            **2. Data We Collect and Purpose**  
            - **Email Address:** To create and manage your account.  
            - **Game Data:** Building levels, Hero stats, and Research progress that you voluntarily enter.  

            **3. Legal Basis & Storage**  
            - *Contractual necessity:* We process your email to operate your account.  
            - *Storage:* Supabase (AWS eu-west-1, Ireland).  
            - *Sharing:* We do **not** share your data with third parties.  

            **4. Retention**  
            Data is retained only while your account is active and is deleted when your account is removed.  

            **5. Your Rights (EU/UK Users)**  
            You may request access, correction, deletion, or portability of your data by emailing the contact above.  
            You may also lodge a complaint with your national data protection authority.
            """,
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------
# DASHBOARD
# ---------------------------------------------------------------------
if page == "Dashboard":
    prof = load_profile(user_id)
    left, right = st.columns([1, 3])

    with left:
        avatar_url = prof.get("avatar_url")
        if avatar_url:
            st.image(avatar_url, width=160)
        else:
            try:
                st.image("frog.png", width=160)
            except Exception:
                st.write("🐸")

    kv_map_full = load_kv_map("buildings_kv", user_id)

    def get_level(name: str) -> int:
        v = kv_map_full.get(ALIASES.get(name.lower(), name))
        if v is None:
            return 0
        try:
            return int(float(v))
        except Exception:
            return 0

    hq = get_level("HQ")

    # total hero power (per user)
    try:
        rows = owner_select("heroes", "power", user_id)
    except Exception:
        rows = []
    arr = pd.to_numeric(pd.DataFrame(rows).get("power") if rows else pd.Series([], dtype="float64"), errors="coerce").fillna(0)
    total_power = int(arr.sum())

    with right:
        display_name = prof.get("display_name") or "Commander"
        st.markdown(
            f"""
            <div style='margin-top:6px'>
              <h2 style='margin:0; font-weight:700;'>{display_name}</h2>
              <div style='font-size:1.1rem; margin-top:6px;'>
                <strong>HQ Level:</strong>
                <span style='font-weight:700; font-size:1.2rem;'>{hq}</span>
                &nbsp;&nbsp;&nbsp;
                <strong>Total Hero Power:</strong>
                <span style='font-weight:700; font-size:1.2rem;'>{total_power:,}</span>
              </div>
              <div style='margin-top:6px; opacity:.7; font-size:.9rem;'>
                Edit your name or picture from the sidebar:
                <em>Update Player Name</em> / <em>Update Profile Picture</em>.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.divider()
    col_teams, col_build, col_research = st.columns([1, 1, 1], gap="large")

    # ---- Teams ----
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

        for i in range(1, 3 + 1):
            tkey = f"team{i}_type"
            pkey = f"team{i}_power"
            if tkey not in st.session_state:
                st.session_state[tkey] = kv_get_simple(tkey, "Tank" if i == 1 else ("Air" if i == 2 else "Mixed"))
            if pkey not in st.session_state:
                st.session_state[pkey] = kv_get_simple(pkey, "")

            def _save_type(ii=i):
                kv_set_simple(f"team{ii}_type", st.session_state[f"team{ii}_type"])

            def _save_power(ii=i):
                cur = (st.session_state[f"team{ii}_power"] or "").strip()
                st.session_state[f"team{ii}_power"] = cur
                kv_set_simple(f"team{ii}_power", cur)

            sc, pc = st.columns([1.2, 1.4])
            with sc:
                st.selectbox(f"Team {i}", team_opts, key=tkey, on_change=_save_type)
            with pc:
                st.text_input("Power", key=pkey, placeholder="43.28M", on_change=_save_power)

    # ---- Buildings ----
    with col_build:
        st.subheader("Buildings")
        st.caption("What’s Cookin’")
        rows = owner_select("buildings_tracking", "name,upgrading,next", user_id)
        up_set = {r["name"] for r in rows if r.get("upgrading")}
        next_set = {r["name"] for r in rows if r.get("next")}
        if up_set:
            for nm in sorted(up_set):
                cur_lvl = get_level(nm)
                st.markdown(f"🔨 **{nm}** ({cur_lvl} → {cur_lvl + 1})")
        else:
            st.markdown("🔨 _Nothing upgrading_")
        st.caption("On Deck")
        if next_set:
            for nm in sorted(next_set):
                st.markdown(f"🧱 **{nm}**")
        else:
            st.markdown("🧱 _Nothing on deck_")

    # ---- Research ----
    with col_research:
        st.subheader("Research")
        df_r = load_research_for_user(user_id)

        st.caption("What’s Cookin’")
        hot = df_r[df_r["tracked"]] if not df_r.empty else pd.DataFrame([])
        if not hot.empty:
            for cat in sorted(hot["category"].unique()):
                items = hot[hot["category"] == cat].sort_values(["order_index", "name"])
                labels = [f"{r['name']} ({int(r['level'])} → {int(r['level'])+1})" for _, r in items.iterrows()]
                st.markdown(f"🔥 **{cat}** — " + " · ".join(labels))
        else:
            st.markdown("🔥 _Nothing in progress_")

        st.caption("On Deck")
        star = df_r[df_r["priority"]] if not df_r.empty else pd.DataFrame([])
        if not star.empty:
            for cat in sorted(star["category"].unique()):
                items = star[star["category"] == cat].sort_values(["order_index", "name"])
                st.markdown(f"⭐ **{cat}** — " + " · ".join(items["name"].tolist()))
        else:
            st.markdown("⭐ _Nothing on deck_")

    # ---- Highest Building Level ----
    st.subheader("Highest Building Level")

    try:
        kv_rows = kv_select("buildings_kv", user_id, None) or []
    except Exception:
        kv_rows = []
    lvl_map = {str(r.get("key") or ""): r.get("value") for r in kv_rows}

    def _to_int(x):
        try:
            return int(float(x))
        except Exception:
            return 0

    def _by_prefix(prefix: str) -> list[str]:
        pref = prefix.strip()
        res = []
        for k in lvl_map.keys():
            k2 = str(k).strip()
            if not k2:
                continue
            if k2 == pref or k2.startswith(pref + " "):
                res.append(k2)
        return sorted(res)

    def _max_level(names: list[str]) -> tuple[int, str]:
        if not names:
            return 0, ""
        pairs = [(n, _to_int(lvl_map.get(n, 0))) for n in names]
        mx = max(lv for _, lv in pairs) if pairs else 0
        detail = ", ".join(f"{(n.split()[-1] if n.split()[-1].isdigit() else n)}:{lv}" for n, lv in pairs)
        return mx, detail

    tech_center_names = ["Tech Center 1", "Tech Center 2", "Tech Center 3"]
    tam_center_names = ["Tank Center", "Air Center", "Missile Center"]  # fixed

    drill_names = _by_prefix("Drill Ground")
    barracks_names = _by_prefix("Barracks")
    hospital_names = _by_prefix("Hospital")

    wall_names = ["Wall"]
    alliance_center_names = ["Alliance Center"]

    tech_max, tech_detail = _max_level(tech_center_names)
    wall_max, wall_detail = _max_level(wall_names)
    drill_max, drill_detail = _max_level(drill_names)

    barracks_max, barracks_detail = _max_level(barracks_names)
    hospital_max, hospital_detail = _max_level(hospital_names)
    ac_max, ac_detail = _max_level(alliance_center_names)

    tam_max, tam_detail = _max_level(tam_center_names)

    row = st.columns(3)
    with row[0]:
        st.metric("Tech Center", tech_max, help=(tech_detail or "No entries yet"))
    with row[1]:
        st.metric("Wall", wall_max, help=(wall_detail or "No entry yet"))
    with row[2]:
        st.metric("Drill Ground", drill_max, help=(drill_detail or "No entries yet"))

    row = st.columns(3)
    with row[0]:
        st.metric("Barracks", barracks_max, help=(barracks_detail or "No entries yet"))
    with row[1]:
        st.metric("Hospital", hospital_max, help=(hospital_detail or "No entries yet"))
    with row[2]:
        st.metric("Alliance Center", ac_max, help=(ac_detail or "No entry yet"))

    st.metric("Tank/Air/Missile Center", tam_max, help=(tam_detail or "No entries yet"))

    # ---- Building Progress (chips) ----
    st.divider()
    st.subheader("Building Progress")

    def max_series_local(base: str, rng: List[int]) -> int:
        vals = []
        for i in rng:
            v = kv_map_full.get(f"{base} {i}")
            try:
                vals.append(int(float(v)) if v not in (None, "") else 0)
            except Exception:
                vals.append(0)
        return max(vals) if vals else 0

    def sum_series_local(base: str, rng: List[int]) -> int:
        s = 0
        for i in rng:
            v = kv_map_full.get(f"{base} {i}")
            try:
                s += int(float(v)) if v not in (None, "") else 0
            except Exception:
                pass
        return s

    def pct_of_hq_sum(base: str, series_key: str) -> float:
        if hq <= 0:
            return 0.0
        rng = SERIES[series_key]
        total = sum_series_local(base, rng)
        denom = len(rng) * hq
        return (total / denom) * 100.0 if denom > 0 else 0.0

    def pct_of_hq_single(name: str) -> float:
        if hq <= 0:
            return 0.0
        return (get_level(name) / hq) * 100.0

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
        ("Centers (Tank/Air/Missile)", lambda: (0.0 if hq <= 0 else (sum(get_level(c) for c in CENTER_NAMES) / (len(CENTER_NAMES) * hq) * 100.0))),
        ("Emergency Center",     lambda: pct_of_hq_single("Emergency Center")),
        ("Alert Tower",          lambda: pct_of_hq_single("Alert Tower")),
        ("Wall",                 lambda: pct_of_hq_single("Wall")),
        ("HQ",                   lambda: 100.0 if hq > 0 else 0.0),
        ("Warehouses (Coin/Food/Iron)", lambda: 0.0 if hq <= 0 else ((get_level("Coin Vault")+get_level("Food Warehouse")+get_level("Iron Warehouse"))/(3*hq)*100.0)),
    ]

    ca, cb, cc = st.columns(3)
    cols = [ca, cb, cc]
    for i, (label, fn) in enumerate(groups):
        with cols[i % 3]:
            st.markdown(f"**{label}**")
            st.markdown(pct_chip(fn()), unsafe_allow_html=True)

    # ---- Research Progress chips ----
    st.subheader("Research Progress")
    df_r2 = load_research_for_user(user_id)
    if df_r2.empty:
        st.caption("Overview (no research data)")
    else:
        df_r2["max_level"] = pd.to_numeric(df_r2["max_level"], errors="coerce").fillna(1)
        df_r2["pct"] = (pd.to_numeric(df_r2["level"], errors="coerce").fillna(0) / df_r2["max_level"].replace(0, 1)) * 100.0
        cats = (df_r2.groupby("category")["pct"].mean().sort_index().round(1).reset_index().values.tolist())
        cols = st.columns(3)
        for idx, (cat, pct) in enumerate(cats):
            with cols[idx % 3]:
                st.markdown(f"**{cat}**")
                st.markdown(pct_chip(pct, ""), unsafe_allow_html=True)

# ---------------------------------------------------------------------
# BUILDINGS
# ---------------------------------------------------------------------
elif page == "Buildings":
    st.header("Buildings")
    st.write("Standard table. Only updates rows you actually change. No undo/redo.")

    current_map = load_kv_map("buildings_kv", user_id)
    rows = [{"name": b, "level": int(float(current_map.get(b, 0) or 0))} for b in DEFAULT_BUILDINGS]
    df = pd.DataFrame(rows)

    tr_rows = owner_select("buildings_tracking", "name,upgrading,next", user_id)
    up_set = {r["name"] for r in tr_rows if r.get("upgrading")}
    next_set = {r["name"] for r in tr_rows if r.get("next")}
    df["hammer"] = df["name"].astype(str).isin(up_set)
    df["brick"]  = df["name"].astype(str).isin(next_set)

    up_count, next_count = int(df["hammer"].sum()), int(df["brick"].sum())
    if up_count or next_count:
        st.caption(f"🔨 {up_count} upgrading | 🧱 {next_count} next")

    editor_cols = ["hammer", "brick", "name", "level"]
    edited = st.data_editor(
        df[editor_cols],
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "hammer": st.column_config.CheckboxColumn("🔨 -  Currently Upgrading"),
            "brick": st.column_config.CheckboxColumn("🧱 -  Up Next"),
            "name": st.column_config.TextColumn("Building", width="large", required=True),
            "level": st.column_config.NumberColumn("Level", min_value=0, max_value=60, step=1),
        },
        hide_index=True,
        key="buildings_editor",
    )

    # persist tracking flags
    all_names = set(edited["name"]) if not edited.empty else set()
    payload = []
    for nm in all_names:
        payload.append({
            "name": nm,
            "upgrading": bool(nm in set(edited.loc[edited["hammer"], "name"])),
            "next": bool(nm in set(edited.loc[edited["brick"], "name"]))
        })
    if payload:
        owner_upsert("buildings_tracking", payload, user_id)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save changes", use_container_width=True):
            try:
                changes = []
                for _, r in edited.iterrows():
                    key = str(r["name"]).strip()
                    lvl = int(r.get("level", 0) or 0)
                    if str(current_map.get(key, "")) != str(lvl):
                        changes.append({"key": key, "value": str(lvl)})
                if changes:
                    kv_upsert("buildings_kv", user_id, changes)
                st.success("Saved"); st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")
    with c2:
        if st.button("Reload from Supabase", use_container_width=True):
            st.rerun()

# ---------------------------------------------------------------------
# HEROES (per-user list with highlights)
# ---------------------------------------------------------------------
elif page == "Heroes":
    st.header("Heroes")

    try:
        res = owner_select(
            "heroes",
            "id,name,level,power,rail_gun,rail_gun_stars,armor,armor_stars,"
            "data_chip,data_chip_stars,radar,radar_stars,weapon,weapon_level,"
            "max_skill_level,skill1,skill2,skill3,type,role,team,updated_at",
            user_id,
            order_by="name"
        )
        df = pd.DataFrame(res or [])
    except Exception:
        st.error("Could not load heroes (check RLS / user_id column).")
        df = pd.DataFrame([])

    if df.empty:
        st.info("No heroes yet. Use **Add or Update Hero** to create your first hero.")
    else:
        num_cols = [
            "power","level","rail_gun","armor","data_chip","radar",
            "weapon_level","max_skill_level","skill1","skill2","skill3"
        ]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        if "power" in df.columns:
            df = df.sort_values("power", ascending=False, na_position="last")

        display_cols = [c for c in [
            "name","power","level","type","role","team",
            "rail_gun","rail_gun_stars","armor","armor_stars",
            "data_chip","data_chip_stars","radar","radar_stars",
            "weapon","weapon_level","max_skill_level","skill1","skill2","skill3","updated_at"
        ] if c in df.columns]

        header_labels = {
            "name": "Hero",
            "power": "Power",
            "level": "Lvl",
            "type": "Type",
            "role": "Role",
            "team": "Team",
            "rail_gun": "Rail Gun",
            "rail_gun_stars": "Rail Stars",
            "armor": "Armor",
            "armor_stars": "Armor Stars",
            "data_chip": "Data Chip",
            "data_chip_stars": "Chip Stars",
            "radar": "Radar",
            "radar_stars": "Radar Stars",
            "weapon": "Weapon",
            "weapon_level": "Wpn Lvl",
            "max_skill_level": "Max Skill",
            "skill1": "Skill 1",
            "skill2": "Skill 2",
            "skill3": "Skill 3",
            "updated_at": "Last Update",
        }

        df_sub = df[display_cols]
        df_display = df_sub.rename(columns=header_labels)

        ORANGE = "background-color: #FFA500"
        GREEN  = "background-color: #008000"

        def star_is_five(x) -> bool:
            try:
                return float(x) == 5.0
            except Exception:
                return False

        role_orange_map = {
            "defense": {"Armor","Armor Stars","Radar","Radar Stars"},
            "attack":  {"Rail Gun","Rail Stars","Data Chip","Chip Stars"},
            "support": {"Rail Gun","Rail Stars","Radar","Radar Stars"},
        }

        pair_map = {
            "Rail Stars": "Rail Gun",
            "Armor Stars": "Armor",
            "Chip Stars": "Data Chip",
            "Radar Stars": "Radar",
        }

        disp_cols = list(df_display.columns)
        disp_set = set(disp_cols)
        role_col_label = header_labels["role"]

        def highlight_row_disp(row: pd.Series):
            styles = [""] * len(disp_cols)

            role_val = str(row.get(role_col_label, "") or "").strip().toLower() if hasattr(str, "toLower") else str(row.get(role_col_label, "") or "").strip().lower()
            role_cols = role_orange_map.get(role_val, set()) & disp_set

            green_cols = set()
            for star_col, base_col in pair_map.items():
                if star_col in disp_set:
                    val = row.get(star_col)
                    if star_is_five(val):
                        green_cols.add(star_col)
                        if base_col in disp_set:
                            green_cols.add(base_col)

            for i, col in enumerate(disp_cols):
                if col in green_cols:
                    styles[i] = GREEN
            for i, col in enumerate(disp_cols):
                if col in role_cols and col not in green_cols:
                    styles[i] = ORANGE if not styles[i] else styles[i]
            return styles

        styled = df_display.style.apply(highlight_row_disp, axis=1).format(precision=0, na_rep="", thousands=",")
        st.dataframe(styled, use_container_width=True)

# ---------------------------------------------------------------------
# ADD / UPDATE HERO (per-user, RLS-safe)
# ---------------------------------------------------------------------
elif page == "Add or Update Hero":
    st.header("Add or Update Hero")

    def v(d, k, default=None):
        return (d.get(k) if d else default)

    sb = get_sb()

    try:
        cols = "id,name,type,role,team,level,power,weapon,weapon_level,max_skill_level,skill1,skill2,skill3,rail_gun,rail_gun_stars,armor,armor_stars,data_chip,data_chip_stars,radar,radar_stars"
        my_rows = owner_select("heroes", cols, user_id, order_by="name")
    except Exception:
        my_rows = []
    my_by_name = {(r.get("name") or "").strip(): r for r in my_rows if r.get("name")}

    try:
        cat_res = sb.table("hero_catalog").select("name,type,role").order("name").execute()
        catalog_rows = cat_res.data or []
        catalog = {
            (r.get("name") or "").strip(): {
                "type": (r.get("type") or "").strip(),
                "role": (r.get("role") or "").strip(),
            }
            for r in catalog_rows if r.get("name")
        }
        catalog_names = sorted(catalog.keys())
    except Exception:
        catalog, catalog_names = {}, []

    names = ["<Create new>"]
    names += sorted(list({n for n in catalog_names if n}))
    names += [n for n in my_by_name.keys() if n and n not in catalog_names]
    selected = st.selectbox("Choose hero", names, index=0)

    current = my_by_name.get(selected) if selected != "<Create new>" else None
    cat_defaults = catalog.get(selected, {}) if selected not in ("", "<Create new>") else {}
    default_type = (v(current, "type") or "") or cat_defaults.get("type", "")
    default_role = (v(current, "role") or "") or cat_defaults.get("role", "")

    colA, colB, colC = st.columns(3)
    with colA:
        name = st.text_input("Name *", value=(v(current, "name") or (selected if selected != "<Create new>" else "") or ""))
        type_ = st.text_input("Type", value=default_type)
        role = st.text_input("Role", value=default_role)
        team = st.text_input("Team", value=(v(current, "team", "") or ""))

    with colB:
        level = st.number_input("Level", min_value=0, max_value=200, value=int(v(current, "level", 0) or 0), step=1)
        try:
            p_in = v(current, "power", 0); p_val = int(float(p_in)) if p_in is not None else 0
        except Exception:
            p_val = 0
        power = st.number_input("Power", min_value=0, step=1, value=p_val)
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

    hero_payload = {
        "name": (name or "").strip(),
        "type": (type_ or "").strip(),
        "role": (role or "").strip(),
        "team": (team or "").strip(),
        "level": int(level or 0),
        "power": float(power or 0),
        "weapon": bool(weapon),
        "weapon_level": int(weapon_level or 0),
        "max_skill_level": int(max_skill_level or 0),
        "skill1": int(skill1 or 0), "skill2": int(skill2 or 0), "skill3": int(skill3 or 0),
        "rail_gun": int(rail_gun or 0), "rail_gun_stars": (rail_gun_stars or "").strip(),
        "armor": int(armor or 0), "armor_stars": (armor_stars or "").strip(),
        "data_chip": int(data_chip or 0), "data_chip_stars": (data_chip_stars or "").strip(),
        "radar": int(radar or 0), "radar_stars": (radar_stars or "").strip(),
    }

    col_save, col_delete = st.columns([1, 1])
    with col_save:
        if st.button("Save", use_container_width=True, type="primary"):
            try:
                payload = dict(hero_payload)
                payload[ID_COL] = user_id
                if not payload["name"] and selected not in ("", "<Create new>"):
                    payload["name"] = selected
                get_sb().table("heroes").upsert(payload, on_conflict=f"{ID_COL},name").execute()
                st.success("Hero saved"); st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    with col_delete:
        if current and current.get("id"):
            if st.button("Delete", type="secondary", use_container_width=True):
                try:
                    get_sb().table("heroes").delete().eq("id", current["id"]).eq(ID_COL, user_id).execute()
                    st.success("Hero deleted"); st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")
        else:
            st.caption("Select an existing hero to enable Delete.")

# ---------------------------------------------------------------------
# RESEARCH
# ---------------------------------------------------------------------
elif page == "Research":
    st.header("Research")
    st.caption("Click a category to expand. Edit Level, 🔥, and ⭐. Max Level edits the shared catalog.")

    sb = get_sb()

    try:
        cat_rows = sb.table("research_catalog").select("name,category,max_level,order_index").execute().data or []
    except Exception:
        cat_rows = []
    cdf = pd.DataFrame(cat_rows)

    try:
        ur_rows = sb.table("user_research").select("name,level,tracked,priority").eq("user_id", user_id).execute().data or []
    except Exception:
        ur_rows = []
    udf = pd.DataFrame(ur_rows)

    if cdf.empty:
        st.info("No research catalog found. Populate research_catalog first.")
    else:
        df = cdf.merge(udf, on="name", how="left", suffixes=("", "_u"))
        df["level"] = pd.to_numeric(df.get("level"), errors="coerce").fillna(0).astype(int)
        df["tracked"] = df.get("tracked").fillna(False).astype(bool)
        df["priority"] = df.get("priority").fillna(False).astype(bool)
        df["max_level"] = pd.to_numeric(df.get("max_level"), errors="coerce").fillna(0).astype(int)
        df["category"] = df.get("category").fillna("Other").astype(str)
        df["order_index"] = pd.to_numeric(df.get("order_index"), errors="coerce").fillna(0).astype(int)

        cats = sorted(df["category"].astype(str).unique())
        preferred_order = [
            "Development","Economy","Hero","Units",
            "Squad 1","Squad 2","Squad 3","Squad 4",
            "Alliance Duel","Intercity Truck","Special Forces","Siege to Seize",
            "Defense Fortifications","Tank Mastery","Missile Mastery","Air Mastery",
            "The Age of Oil","Tactical Weapon",
        ]

        saved_order = kv_get_json(user_id, "research_category_order", preferred_order)
        pos_map = {cat: i for i, cat in enumerate(saved_order)}
        for cat in cats:
            if cat not in pos_map:
                pos_map[cat] = len(pos_map)
        render_cats = sorted(cats, key=lambda c: pos_map.get(c, 10**9))

        for cat in render_cats:
            sub = df[df["category"] == cat].sort_values(["order_index", "name"]).copy()
            denom = sub["max_level"].replace(0, 1)
            pct = ((sub["level"].clip(lower=0) / denom).mean() * 100.0) if len(sub) else 0.0

            fire_count = int(sub["tracked"].sum()) if "tracked" in sub.columns else 0
            star_count = int(sub["priority"].sum()) if "priority" in sub.columns else 0
            chips = []
            if fire_count > 0: chips.append(f"🔥 {fire_count}")
            if star_count > 0: chips.append(f"⭐ {star_count}")
            chips_text = "  ".join(chips)

            icon = "🟢" if pct >= 90 else ("🟠" if pct >= 50 else "🔴")
            label = f"{icon} {cat} — {pct:.1f}%"
            if chips_text:
                label = f"{label}   {chips_text}"

            with st.expander(label, expanded=False):
                orig_max_by_name = dict(zip(sub["name"], sub["max_level"]))
                orig_lvl_by_name = dict(zip(sub["name"], sub["level"]))
                orig_trk_by_name = dict(zip(sub["name"], sub["tracked"]))
                orig_pri_by_name = dict(zip(sub["name"], sub["priority"]))

                show_cols = ["name", "level", "max_level", "tracked", "priority"]
                edited = st.data_editor(
                    sub[show_cols],
                    key=f"research_editor_{cat}",
                    use_container_width=True,
                    num_rows="dynamic",
                    column_config={
                        "name": st.column_config.TextColumn("Research Name", width="large", required=True),
                        "level": st.column_config.NumberColumn("Level", min_value=0, max_value=999, step=1),
                        "max_level": st.column_config.NumberColumn("Max Level", min_value=0, max_value=999, step=1),
                        "tracked": st.column_config.CheckboxColumn("🔥 -  Currently Researching"),
                        "priority": st.column_config.CheckboxColumn("⭐ -  Up Next"),
                    },
                    hide_index=True,
                )

                c1, c2, c3 = st.columns([1, 1, 6])
                with c1:
                    if st.button("Save", key=f"save_{cat}", type="primary", use_container_width=True):
                        try:
                            ur_payload = []
                            for _, r in edited.iterrows():
                                nm = str(r["name"]).strip()
                                if not nm:
                                    continue
                                lvl = int(r.get("level", 0) or 0)
                                trk = bool(r.get("tracked", False))
                                pri = bool(r.get("priority", False))
                                changed = (
                                    lvl != orig_lvl_by_name.get(nm, 0)
                                    or trk != orig_trk_by_name.get(nm, False)
                                    or pri != orig_pri_by_name.get(nm, False)
                                )
                                if changed:
                                    ur_payload.append({
                                        "user_id": user_id,
                                        "name": nm,
                                        "level": lvl,
                                        "tracked": trk,
                                        "priority": pri,
                                    })
                            if ur_payload:
                                sb.table("user_research").upsert(ur_payload, on_conflict="user_id,name").execute()

                            cat_payload = []
                            for _, r in edited.iterrows():
                                nm = str(r["name"]).strip()
                                if not nm:
                                    continue
                                ml = int(r.get("max_level", 0) or 0)
                                if ml != orig_max_by_name.get(nm, ml):
                                    cat_payload.append({"name": nm, "category": cat, "max_level": ml})
                            if cat_payload:
                                sb.table("research_catalog").upsert(cat_payload, on_conflict="name").execute()

                            st.success("Saved"); st.rerun()
                        except Exception as e:
                            st.error(f"Save failed: {e}")

                with c2:
                    if st.button("Reload", key=f"reload_{cat}", use_container_width=True):
                        st.rerun()

                with c3:
                    st.markdown(f"**Preview Completion:** {pct:.1f}%")

        # ordering controls at bottom
        with st.expander("Manage Research Group Order", expanded=False):
            odf = pd.DataFrame({
                "Category": cats,
                "Position": [pos_map[c] for c in cats],
            }).sort_values("Position", kind="mergesort").reset_index(drop=True)

            edited_odf = st.data_editor(
                odf,
                key="research_category_order_editor",
                use_container_width=True,
                column_config={
                    "Category": st.column_config.TextColumn(disabled=True, width="large"),
                    "Position": st.column_config.NumberColumn(min_value=0, step=1),
                },
                hide_index=True,
            )

            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("Save Group Order", type="primary", use_container_width=True):
                    try:
                        new_order = (
                            edited_odf.sort_values(["Position", "Category"], kind="mergesort")["Category"]
                            .astype(str).tolist()
                        )
                        kv_set_json(user_id, "research_category_order", new_order)
                        st.success("Saved group order"); st.rerun()
                    except Exception as e:
                        st.error(f"Save failed: {e}")

            with c2:
                if st.button("Use Recommended Order", use_container_width=True):
                    merged = preferred_order + [c for c in cats if c not in preferred_order]
                    kv_set_json(user_id, "research_category_order", merged)
                    st.success("Applied recommended order"); st.rerun()

# ---------------------------------------------------------------------
# UPDATE PLAYER NAME
# ---------------------------------------------------------------------
elif page == "Update Player Name":
    st.header("Update Player Name")
    prof = load_profile(user_id)
    current = prof.get("display_name") or ""
    new_name = st.text_input("Display name", value=current, placeholder="e.g., Shōckwave [FER]")
    if st.button("Save name", type="primary"):
        ok = save_profile(user_id, display_name=new_name)
        if ok:
            st.success("Name saved."); st.rerun()
        else:
            st.error("Could not save your name (check RLS/policies).")

# ---------------------------------------------------------------------
# UPDATE PROFILE PICTURE
# ---------------------------------------------------------------------
elif page == "Update Profile Picture":
    st.header("Update Profile Picture")
    prof = load_profile(user_id)
    avatar_url = prof.get("avatar_url")
    if avatar_url:
        st.image(avatar_url, width=160)
    else:
        try:
            st.image("frog.png", width=160)
        except Exception:
            st.write("🐸")

    up = st.file_uploader("Choose an image (PNG, JPG, JPEG, WEBP)", type=["png","jpg","jpeg","webp"])
    if st.button("Upload", type="primary") and up is not None:
        url = upload_avatar(user_id, up)
        if url:
            if save_profile(user_id, avatar_url=url):
                st.success("Profile picture updated."); st.rerun()
            else:
                st.error("Upload succeeded but saving URL failed (check RLS/policies).")
        else:
            st.error("Upload failed. Try another image.")

# ---------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------
st.caption("Made with love. Drink a beer.")
