"""Aurora PostgreSQL client adapter providing a Supabase/PostgREST-compatible API.

Translates PostgREST-style method chaining (.table().select().eq().execute())
into parameterized SQL executed directly on AWS Aurora PostgreSQL via SQLAlchemy.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row

from app.aurora import get_aurora_engine

_log = logging.getLogger("recondesk.aurora.client")


def _serialize_value(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_serialize_value(item) for item in v]
    return v


def _serialize_row(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _serialize_value(v) for k, v in d.items()}


# PostgreSQL columns known to be native arrays (e.g. uuid[], text[]).
# All other list values in ReconDesk are stored in JSONB columns.
_NATIVE_ARRAY_COLS = {"client_gstin_ids", "record_ids"}


def _prepare_sql_param(col: str, val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, dict):
        return json.dumps(val)
    if isinstance(val, list):
        if col in _NATIVE_ARRAY_COLS:
            return list(val)
        return json.dumps(val)
    return val


class APIResponse:
    """Supabase-compatible APIResponse object."""

    def __init__(self, data: Any, count: Optional[int] = None):
        self.data = data
        self.count = count if count is not None else (len(data) if isinstance(data, list) else (1 if data is not None else 0))

    def __repr__(self) -> str:
        return f"<APIResponse count={self.count}>"


class _AuroraNotModifier:
    """Helper to support PostgREST `.not_.is_()`, `.not_.in_()`, `.not_.eq()` on AuroraTableQuery."""

    def __init__(self, query: "AuroraTableQuery"):
        self._query = query

    def is_(self, column: str, value: Any) -> "AuroraTableQuery":
        col = column.strip().replace('"', "")
        if value is None or str(value).lower() in ("null", "none"):
            self._query._where_clauses.append(f'"{col}" IS NOT NULL')
        elif str(value).lower() == "true":
            self._query._where_clauses.append(f'"{col}" IS NOT TRUE')
        elif str(value).lower() == "false":
            self._query._where_clauses.append(f'"{col}" IS NOT FALSE')
        else:
            self._query._where_clauses.append(f'"{col}" IS NOT NULL')
        return self._query

    def in_(self, column: str, values: Any) -> "AuroraTableQuery":
        col = column.strip().replace('"', "")
        if not values:
            return self._query
        val_list = list(values)
        param_names = []
        for v in val_list:
            p = self._query._next_param("not_in")
            param_names.append(f":{p}")
            self._query._params[p] = v
        self._query._where_clauses.append(f'"{col}" NOT IN ({", ".join(param_names)})')
        return self._query

    def eq(self, column: str, value: Any) -> "AuroraTableQuery":
        return self._query.neq(column, value)

    def neq(self, column: str, value: Any) -> "AuroraTableQuery":
        return self._query.eq(column, value)

    def like(self, column: str, pattern: str) -> "AuroraTableQuery":
        col = column.strip().replace('"', "")
        p = self._query._next_param("nlike")
        self._query._where_clauses.append(f'"{col}" NOT LIKE :{p}')
        self._query._params[p] = pattern
        return self._query

    def ilike(self, column: str, pattern: str) -> "AuroraTableQuery":
        col = column.strip().replace('"', "")
        p = self._query._next_param("nilike")
        self._query._where_clauses.append(f'"{col}" NOT ILIKE :{p}')
        self._query._params[p] = pattern
        return self._query


class AuroraTableQuery:
    """Builder that compiles chained PostgREST calls into parameterized SQL for Aurora."""

    @property
    def not_(self) -> _AuroraNotModifier:
        return _AuroraNotModifier(self)

    def __init__(self, table_name: str):
        # Validate table name to prevent SQL injection
        self.table_name = table_name.strip().replace('"', "")
        self._action = "select"  # select | insert | update | delete | upsert
        self._select_cols = "*"
        self._where_clauses: List[str] = []
        self._params: Dict[str, Any] = {}
        self._order_by: List[str] = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None
        self._single = False
        self._maybe_single = False
        self._count_mode: Optional[str] = None
        self._head: bool = False
        self._data_payload: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None
        self._on_conflict_col = "id"
        self._param_counter = 0

    def _next_param(self, prefix: str = "p") -> str:
        self._param_counter += 1
        return f"{prefix}_{self._param_counter}"

    # ── Actions ───────────────────────────────────────────────────────────────

    def select(self, columns: str = "*", count: Optional[str] = None, head: bool = False) -> AuroraTableQuery:
        self._action = "select"
        self._select_cols = columns if columns and columns.strip() else "*"
        self._count_mode = count
        self._head = head
        return self

    def insert(self, data: Union[Dict[str, Any], List[Dict[str, Any]]], upsert: bool = False) -> AuroraTableQuery:
        self._action = "upsert" if upsert else "insert"
        self._data_payload = data
        return self

    def update(self, data: Dict[str, Any]) -> AuroraTableQuery:
        self._action = "update"
        self._data_payload = data
        return self

    def delete(self) -> AuroraTableQuery:
        self._action = "delete"
        return self

    def upsert(self, data: Union[Dict[str, Any], List[Dict[str, Any]]], on_conflict: str = "id") -> AuroraTableQuery:
        self._action = "upsert"
        self._data_payload = data
        self._on_conflict_col = on_conflict
        return self

    # ── Filters ───────────────────────────────────────────────────────────────

    def eq(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        if value is None:
            self._where_clauses.append(f'"{col}" IS NULL')
        else:
            p = self._next_param("eq")
            self._where_clauses.append(f'"{col}" = :{p}')
            self._params[p] = value
        return self

    def neq(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        if value is None:
            self._where_clauses.append(f'"{col}" IS NOT NULL')
        else:
            p = self._next_param("neq")
            self._where_clauses.append(f'"{col}" != :{p}')
            self._params[p] = value
        return self

    def gt(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("gt")
        self._where_clauses.append(f'"{col}" > :{p}')
        self._params[p] = value
        return self

    def gte(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("gte")
        self._where_clauses.append(f'"{col}" >= :{p}')
        self._params[p] = value
        return self

    def lt(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("lt")
        self._where_clauses.append(f'"{col}" < :{p}')
        self._params[p] = value
        return self

    def lte(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("lte")
        self._where_clauses.append(f'"{col}" <= :{p}')
        self._params[p] = value
        return self

    def like(self, column: str, pattern: str) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("like")
        self._where_clauses.append(f'"{col}" LIKE :{p}')
        self._params[p] = pattern
        return self

    def ilike(self, column: str, pattern: str) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        p = self._next_param("ilike")
        self._where_clauses.append(f'"{col}" ILIKE :{p}')
        self._params[p] = pattern
        return self

    def is_(self, column: str, value: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        if value is None or str(value).lower() in ("null", "none"):
            self._where_clauses.append(f'"{col}" IS NULL')
        elif str(value).lower() == "true":
            self._where_clauses.append(f'"{col}" IS TRUE')
        elif str(value).lower() == "false":
            self._where_clauses.append(f'"{col}" IS FALSE')
        elif str(value).lower() in ("not null", "not_null"):
            self._where_clauses.append(f'"{col}" IS NOT NULL')
        return self

    def in_(self, column: str, values: Any) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        if not values:
            self._where_clauses.append("1=0")
            return self
        val_list = list(values)
        param_names = []
        for v in val_list:
            p = self._next_param("in")
            param_names.append(f":{p}")
            self._params[p] = v
        self._where_clauses.append(f'"{col}" IN ({", ".join(param_names)})')
        return self

    def match(self, query_dict: Dict[str, Any]) -> AuroraTableQuery:
        for k, v in query_dict.items():
            self.eq(k, v)
        return self

    # ── Ordering & Pagination ─────────────────────────────────────────────────

    def order(self, column: str, desc: bool = False, nullsfirst: bool = False) -> AuroraTableQuery:
        col = column.strip().replace('"', "")
        direction = "DESC" if desc else "ASC"
        nulls = "NULLS FIRST" if nullsfirst else "NULLS LAST"
        self._order_by.append(f'"{col}" {direction} {nulls}')
        return self

    def limit(self, count: int) -> AuroraTableQuery:
        self._limit = count
        return self

    def offset(self, count: int) -> AuroraTableQuery:
        self._offset = count
        return self

    def range(self, start: int, end: int) -> AuroraTableQuery:
        self._offset = start
        self._limit = end - start + 1
        return self

    def single(self) -> AuroraTableQuery:
        self._single = True
        self._limit = 1
        return self

    def maybe_single(self) -> AuroraTableQuery:
        self._maybe_single = True
        self._limit = 1
        return self

    # ── Execution ─────────────────────────────────────────────────────────────

    def _build_where_clause(self) -> str:
        if not self._where_clauses:
            return ""
        return " WHERE " + " AND ".join(self._where_clauses)

    def _clean_select_cols(self) -> str:
        if not self._select_cols or self._select_cols.strip() == "*":
            return "*"
        # PostgREST allows comma-separated column names, e.g. "id, email, full_name"
        cols = [c.strip() for c in self._select_cols.split(",") if c.strip()]
        cleaned = []
        for c in cols:
            # Handle functions or raw stars
            if "(" in c or c == "*":
                cleaned.append(c)
            else:
                cleaned.append(f'"{c}"')
        return ", ".join(cleaned)

    def execute(self) -> APIResponse:
        engine = get_aurora_engine()

        with engine.connect() as conn:
            if self._action == "select":
                total_count: Optional[int] = None
                if self._count_mode is not None:
                    count_sql = f'SELECT COUNT(*) FROM public."{self.table_name}"{self._build_where_clause()}'
                    c_res = conn.execute(text(count_sql), self._params).scalar()
                    total_count = int(c_res) if c_res is not None else 0

                if self._head:
                    return APIResponse([], count=total_count)

                cols_sql = self._clean_select_cols()
                sql = f'SELECT {cols_sql} FROM public."{self.table_name}"{self._build_where_clause()}'
                if self._order_by:
                    sql += " ORDER BY " + ", ".join(self._order_by)
                if self._limit is not None:
                    sql += f" LIMIT {int(self._limit)}"
                if self._offset is not None:
                    sql += f" OFFSET {int(self._offset)}"

                res = conn.execute(text(sql), self._params)
                rows = [_serialize_row(dict(r._mapping)) for r in res.fetchall()]

                if self._single:
                    if not rows:
                        raise RuntimeError(f"JSON object requested, multiple (or no) rows returned for {self.table_name}")
                    return APIResponse(rows[0], count=total_count)
                if self._maybe_single:
                    return APIResponse(rows[0] if rows else None, count=total_count)
                return APIResponse(rows, count=total_count)

            elif self._action == "insert":
                if not self._data_payload:
                    return APIResponse([])
                records = self._data_payload if isinstance(self._data_payload, list) else [self._data_payload]
                if not records:
                    return APIResponse([])

                inserted_rows: List[Dict[str, Any]] = []
                for rec in records:
                    cols = list(rec.keys())
                    p_names = []
                    item_params = dict(self._params)
                    for col in cols:
                        p = self._next_param("ins")
                        p_names.append(f":{p}")
                        item_params[p] = _prepare_sql_param(col, rec[col])

                    col_names = ", ".join([f'"{c}"' for c in cols])
                    val_placeholders = ", ".join(p_names)
                    sql = f'INSERT INTO public."{self.table_name}" ({col_names}) VALUES ({val_placeholders}) RETURNING *'
                    res = conn.execute(text(sql), item_params)
                    for r in res.fetchall():
                        inserted_rows.append(_serialize_row(dict(r._mapping)))
                conn.commit()

                if self._single or (isinstance(self._data_payload, dict) and self._single):
                    return APIResponse(inserted_rows[0] if inserted_rows else None)
                return APIResponse(inserted_rows if isinstance(self._data_payload, list) else (inserted_rows or [self._data_payload]))

            elif self._action == "update":
                if not self._data_payload or not isinstance(self._data_payload, dict):
                    return APIResponse([])
                set_clauses = []
                update_params = dict(self._params)
                for col, val in self._data_payload.items():
                    p = self._next_param("upd")
                    set_clauses.append(f'"{col}" = :{p}')
                    update_params[p] = _prepare_sql_param(col, val)

                where_sql = self._build_where_clause()
                sql = f'UPDATE public."{self.table_name}" SET {", ".join(set_clauses)}{where_sql} RETURNING *'
                res = conn.execute(text(sql), update_params)
                conn.commit()
                rows = [_serialize_row(dict(r._mapping)) for r in res.fetchall()]
                if self._single:
                    return APIResponse(rows[0] if rows else None)
                return APIResponse(rows)

            elif self._action == "delete":
                where_sql = self._build_where_clause()
                sql = f'DELETE FROM public."{self.table_name}"{where_sql} RETURNING *'
                res = conn.execute(text(sql), self._params)
                conn.commit()
                rows = [_serialize_row(dict(r._mapping)) for r in res.fetchall()]
                return APIResponse(rows)

            elif self._action == "upsert":
                if not self._data_payload:
                    return APIResponse([])
                records = self._data_payload if isinstance(self._data_payload, list) else [self._data_payload]
                upserted_rows: List[Dict[str, Any]] = []

                conflict_cols = [c.strip().replace('"', "") for c in self._on_conflict_col.split(",") if c.strip()]
                conflict_sql = ", ".join([f'"{c}"' for c in conflict_cols])

                for rec in records:
                    cols = list(rec.keys())
                    p_names = []
                    item_params = dict(self._params)
                    for col in cols:
                        p = self._next_param("ups")
                        p_names.append(f":{p}")
                        item_params[p] = _prepare_sql_param(col, rec[col])

                    col_names = ", ".join([f'"{c}"' for c in cols])
                    val_placeholders = ", ".join(p_names)

                    # EXCLUDED update columns
                    update_cols = [c for c in cols if c not in conflict_cols]
                    if update_cols:
                        do_update = ", ".join([f'"{c}" = EXCLUDED."{c}"' for c in update_cols])
                        conflict_action = f"DO UPDATE SET {do_update}"
                    else:
                        conflict_action = "DO NOTHING"

                    sql = (
                        f'INSERT INTO public."{self.table_name}" ({col_names}) '
                        f'VALUES ({val_placeholders}) '
                        f'ON CONFLICT ({conflict_sql}) {conflict_action} '
                        f'RETURNING *'
                    )
                    res = conn.execute(text(sql), item_params)
                    for r in res.fetchall():
                        upserted_rows.append(_serialize_row(dict(r._mapping)))
                conn.commit()
                return APIResponse(upserted_rows if isinstance(self._data_payload, list) else (upserted_rows or [self._data_payload]))

        return APIResponse([])


class AuroraAuthUser:
    """Mock user object matching Supabase User structure."""

    def __init__(self, id: str, email: str, user_metadata: Optional[Dict[str, Any]] = None):
        self.id = id
        self.email = email
        self.user_metadata = user_metadata or {}


class AuroraAuthSession:
    """Session object providing access_token and refresh_token."""

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        self.access_token = access_token
        self.refresh_token = refresh_token


class AuroraAuthResponse:
    """Mock auth response matching Supabase auth response structure."""

    def __init__(self, user: Optional[AuroraAuthUser] = None, session: Optional[AuroraAuthSession] = None):
        self.user = user
        self.session = session


class AuroraAuthAdmin:
    """Supabase-compatible auth.admin adapter backed by Aurora & Cognito."""

    def get_user_by_id(self, user_id: str) -> AuroraAuthResponse:
        engine = get_aurora_engine()
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT id, email, full_name, phone, role FROM public.user_profiles WHERE id = :uid LIMIT 1"),
                {"uid": user_id},
            )
            row = res.first()
            if not row:
                return AuroraAuthResponse(user=None)
            d = dict(row._mapping)
            user = AuroraAuthUser(
                id=str(d["id"]),
                email=str(d.get("email") or ""),
                user_metadata={
                    "full_name": d.get("full_name"),
                    "phone": d.get("phone"),
                    "role": d.get("role"),
                },
            )
            return AuroraAuthResponse(user=user)


class AuroraAuthClient:
    """Cognito and Aurora-backed auth client adapter."""

    def __init__(self):
        self.admin = AuroraAuthAdmin()

    def get_user(self, jwt: Optional[str] = None) -> AuroraAuthResponse:
        return AuroraAuthResponse(user=None)

    @staticmethod
    def _get_secret_hash(username: str, client_id: str, client_secret: str) -> str:
        import base64
        import hashlib
        import hmac
        msg = username + client_id
        dig = hmac.new(str(client_secret).encode("utf-8"), msg=str(msg).encode("utf-8"), digestmod=hashlib.sha256).digest()
        return base64.b64encode(dig).decode()

    def sign_up(self, params: Dict[str, Any]) -> AuroraAuthResponse:
        import uuid
        import boto3
        from app.config import get_settings

        s = get_settings()
        email = str(params.get("email") or "").strip().lower()
        password = str(params.get("password") or "")
        options = params.get("options") or {}
        data = options.get("data") or {}

        # 1. Check if email already exists in Aurora user_profiles
        engine = get_aurora_engine()
        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM public.user_profiles WHERE LOWER(email) = :em LIMIT 1"),
                {"em": email},
            ).first()
            if existing:
                # Already exists
                return AuroraAuthResponse(user=None)

        user_id = str(uuid.uuid4())
        cognito_sub = None

        # 2. Register in AWS Cognito
        try:
            cognito = boto3.client("cognito-idp", region_name=s.COGNITO_REGION)
            user_attrs = [
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ]
            phone = str(data.get("phone") or "").strip()
            if phone:
                norm_phone = phone if phone.startswith("+") else ("+91" + phone if len(phone) == 10 else "+" + phone)
                user_attrs.append({"Name": "phone_number", "Value": norm_phone})
            if data.get("full_name"):
                user_attrs.append({"Name": "name", "Value": str(data["full_name"])})

            cognito_res = cognito.admin_create_user(
                UserPoolId=s.COGNITO_USER_POOL_ID,
                Username=email,
                UserAttributes=user_attrs,
                MessageAction="SUPPRESS",
            )
            cognito.admin_set_user_password(
                UserPoolId=s.COGNITO_USER_POOL_ID,
                Username=email,
                Password=password,
                Permanent=True,
            )
            for a in cognito_res.get("User", {}).get("Attributes", []):
                if a["Name"] == "sub":
                    cognito_sub = a["Value"]
        except Exception as exc:
            _log.warning("Cognito sign_up exception for %s: %s", email, exc)
            raise

        # 3. Create trusted identity mapping in Aurora
        if cognito_sub:
            with engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO public.cognito_user_mappings
                        (id, cognito_user_pool_id, cognito_sub, user_id, email, mapping_method, is_verified, provisioned_by)
                        VALUES (:id, :pool, :sub, :uid, :em, 'admin_provisioned', true, 'signup')
                        ON CONFLICT (cognito_user_pool_id, cognito_sub) DO NOTHING
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "pool": s.COGNITO_USER_POOL_ID,
                        "sub": cognito_sub,
                        "uid": user_id,
                        "em": email,
                    },
                )
                conn.commit()

        user = AuroraAuthUser(id=user_id, email=email, user_metadata=data)
        return AuroraAuthResponse(user=user)

    def sign_in_with_password(self, params: Dict[str, Any]) -> AuroraAuthResponse:
        import boto3
        from botocore import UNSIGNED
        from botocore.config import Config
        from app.config import get_settings

        s = get_settings()
        email = str(params.get("email") or "").strip().lower()
        password = str(params.get("password") or "")

        logging.getLogger("botocore").setLevel(logging.INFO)
        logging.getLogger("botocore.endpoint").setLevel(logging.INFO)

        cognito = boto3.client("cognito-idp", region_name=s.COGNITO_REGION)
        auth_params = {
            "USERNAME": email,
            "PASSWORD": password,
        }
        if s.COGNITO_CLIENT_SECRET:
            auth_params["SECRET_HASH"] = self._get_secret_hash(
                email, s.COGNITO_CLIENT_ID, s.COGNITO_CLIENT_SECRET
            )

        auth_res = None
        # Step 1: Attempt direct AWS Cognito authentication (public initiate_auth flow first, then admin fallback)
        try:
            cognito_pub = boto3.client(
                "cognito-idp",
                region_name=s.COGNITO_REGION,
                config=Config(signature_version=UNSIGNED),
            )
            auth_res = cognito_pub.initiate_auth(
                ClientId=s.COGNITO_CLIENT_ID,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters=auth_params,
            )
        except Exception as cognito_exc:
            _log.info("Cognito direct auth attempt for %s: %s", email, cognito_exc)
            try:
                auth_res = cognito.admin_initiate_auth(
                    UserPoolId=s.COGNITO_USER_POOL_ID,
                    ClientId=s.COGNITO_CLIENT_ID,
                    AuthFlow="ADMIN_NO_SRP_AUTH",
                    AuthParameters=auth_params,
                )
            except Exception as admin_exc:
                _log.info("Cognito admin_initiate_auth fallback for %s: %s", email, admin_exc)

        if not auth_res:
            _log.warning("AuroraAuthClient.sign_in_with_password: Cognito authentication returned no response for %s", email)
            return AuroraAuthResponse(user=None, session=None)

        tokens = auth_res.get("AuthenticationResult", {})
        access_token = tokens.get("AccessToken")
        refresh_token = tokens.get("RefreshToken")

        if not access_token:
            _log.warning("AuroraAuthClient.sign_in_with_password: No AccessToken in AuthenticationResult for %s (keys: %s)", email, list(tokens.keys()))
            return AuroraAuthResponse(user=None, session=None)

        # Step 3: Resolve mapped user_id from Aurora user_profiles
        from sqlalchemy.exc import OperationalError
        from app.aurora import reset_aurora_engine_with_secrets_manager

        engine = get_aurora_engine()
        prof = None
        try:
            with engine.connect() as conn:
                prof = conn.execute(
                    text("SELECT id, email, full_name, phone, role FROM public.user_profiles WHERE LOWER(email) = :em LIMIT 1"),
                    {"em": email},
                ).first()
        except OperationalError as op_err:
            if "password authentication failed" in str(op_err):
                _log.warning("Aurora password authentication failed; attempting recovery via AWS Secrets Manager")
                new_engine = reset_aurora_engine_with_secrets_manager()
                if new_engine:
                    engine = new_engine
                    with engine.connect() as conn:
                        prof = conn.execute(
                            text("SELECT id, email, full_name, phone, role FROM public.user_profiles WHERE LOWER(email) = :em LIMIT 1"),
                            {"em": email},
                        ).first()
                else:
                    raise
            else:
                raise

        if not prof:
            _log.warning("AuroraAuthClient.sign_in_with_password: No user_profiles record found for email %s", email)
            return AuroraAuthResponse(user=None, session=None)

        user_id = str(prof.id)

        # Auto-sync identity mapping in Aurora
        id_token = tokens.get("IdToken")
        cognito_sub = None
        if id_token:
            try:
                import jwt as pyjwt
                unverified = pyjwt.decode(id_token, options={"verify_signature": False})
                cognito_sub = unverified.get("sub")
            except Exception:
                pass
        if cognito_sub:
            try:
                import uuid
                with engine.connect() as map_conn:
                    map_conn.execute(
                        text("""
                            INSERT INTO public.cognito_user_mappings
                            (id, cognito_user_pool_id, cognito_sub, user_id, email, mapping_method, is_verified, provisioned_by)
                            VALUES (:id, :pool, :sub, :uid, :em, 'admin_provisioned', true, 'login')
                            ON CONFLICT (cognito_user_pool_id, cognito_sub) DO UPDATE
                            SET user_id = EXCLUDED.user_id, email = EXCLUDED.email
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "pool": s.COGNITO_USER_POOL_ID,
                            "sub": cognito_sub,
                            "uid": user_id,
                            "em": email,
                        },
                    )
                    map_conn.commit()
            except Exception as map_err:
                _log.warning("Auto-sync cognito mapping exception: %s", map_err)

        user = AuroraAuthUser(
            id=user_id,
            email=str(prof.email),
            user_metadata={
                "full_name": prof.full_name,
                "phone": prof.phone,
                "role": prof.role,
            },
        )
        session = AuroraAuthSession(access_token=access_token, refresh_token=refresh_token)
        return AuroraAuthResponse(user=user, session=session)


class AuroraRpcQuery:
    """Supports PostgREST client.rpc(func_name, params).execute() on Aurora."""

    def __init__(self, func_name: str, params: Optional[Dict[str, Any]] = None):
        self.func_name = func_name.strip().replace('"', "")
        self.params = params or {}

    def execute(self) -> APIResponse:
        engine = get_aurora_engine()
        with engine.connect() as conn:
            param_placeholders = []
            param_dict: Dict[str, Any] = {}
            for i, (k, v) in enumerate(self.params.items()):
                p_key = f"rpc_p_{i}"
                param_placeholders.append(f"{k} => :{p_key}")
                param_dict[p_key] = _prepare_sql_param(k, v)
            args_str = ", ".join(param_placeholders)
            sql = f'SELECT * FROM public."{self.func_name}"({args_str})'
            try:
                res = conn.execute(text(sql), param_dict)
                conn.commit()
                rows = [_serialize_row(dict(r._mapping)) for r in res.fetchall()]
                if len(rows) == 1 and len(rows[0]) == 1:
                    first_val = list(rows[0].values())[0]
                    return APIResponse(first_val)
                return APIResponse(rows)
            except Exception:
                conn.rollback()
                sql_scalar = f'SELECT public."{self.func_name}"({args_str})'
                res = conn.execute(text(sql_scalar), param_dict)
                conn.commit()
                first_row = res.first()
                val = first_row[0] if first_row else None
                return APIResponse(val)


class AuroraClient:
    """High-level client providing the PostgREST / Supabase interface over Aurora."""

    def __init__(self):
        self.auth = AuroraAuthClient()

    def table(self, table_name: str) -> AuroraTableQuery:
        return AuroraTableQuery(table_name)

    def rpc(self, func_name: str, params: Optional[Dict[str, Any]] = None) -> AuroraRpcQuery:
        return AuroraRpcQuery(func_name, params)
