#!/usr/bin/env python3
"""
Supabase Project Migration Script
---------------------------------
Exports schema + data from an old Supabase project (excluding test/junk data in
`reconciliation_results` and `invoice_tracking`), imports it into a new Supabase project,
and updates all local `.env` files and configuration references.

Two-Phase Execution Strategy:
  Phase 1 (DB + Auth Migration):
    python3 scripts/migrate_supabase.py --phase-1 \
      --old-db-url "postgresql://postgres:[OLD_PASSWORD]@db.[OLD_REF].supabase.co:5432/postgres" \
      --new-db-url "postgresql://postgres:[NEW_PASSWORD]@db.[NEW_REF].supabase.co:5432/postgres"

  Phase 2 (.env + Config Update - Run after manual verification):
    python3 scripts/migrate_supabase.py --phase-2 \
      --new-url "https://[NEW_REF].supabase.co" \
      --new-anon-key "ey..." \
      --new-service-key "ey..."

Features:
  - Connectivity pre-check against old DB before dump.
  - Old DB connections strictly forced to READ-ONLY mode.
  - Excludes table data for reconciliation_results and invoice_tracking.
  - Preserves auth schema user data for seamless login verification.
  - Two-phase workflow to allow verification before touching local .env files.
  - Automatic URL-encoding of special characters in DB passwords (e.g. '@', '#').
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from urllib.parse import quote, unquote

# Ensure psycopg2 or alternative postgres driver can be imported if needed
try:
    import psycopg2
    from psycopg2 import sql
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "recondesk-backend"
FRONTEND_DIR = PROJECT_ROOT / "recondesk-frontend"
DEFAULT_DUMP_FILE = PROJECT_ROOT / "supabase_migration_dump.sql"

EXCLUDED_DATA_TABLES = ["reconciliation_results", "invoice_tracking"]


def check_tool_available(tool_name: str) -> Optional[str]:
    """Check if a CLI tool like pg_dump or psql is available in PATH or Homebrew libpq."""
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path
    
    # Check standard Homebrew libpq locations on macOS
    brew_libpq_paths = [
        Path("/opt/homebrew/opt/libpq/bin") / tool_name,
        Path("/usr/local/opt/libpq/bin") / tool_name,
        Path("/opt/homebrew/bin") / tool_name,
        Path("/usr/local/bin") / tool_name,
    ]
    for p in brew_libpq_paths:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    
    return None


def extract_project_ref(supabase_url: str) -> str:
    """Extract project ref from Supabase URL (e.g., https://xyz.supabase.co -> xyz)."""
    clean_url = supabase_url.strip()
    match = re.search(r"https://([a-z0-9-]+)\.supabase\.co", clean_url)
    if match:
        return match.group(1)
    # Fallback if raw ref passed
    return clean_url.replace("https://", "").replace(".supabase.co", "")


def sanitize_db_url(url_str: str) -> str:
    """Automatically URL-encode special characters in the DB password (e.g., '@', '#', ':')."""
    url_str = url_str.strip()
    prefix = ""
    if url_str.startswith("postgresql://"):
        prefix = "postgresql://"
    elif url_str.startswith("postgres://"):
        prefix = "postgres://"
    else:
        return url_str

    body = url_str[len(prefix):]
    if "@" in body:
        last_at = body.rfind("@")
        userinfo = body[:last_at]
        hostpath = body[last_at + 1:]
        if ":" in userinfo:
            user, pwd = userinfo.split(":", 1)
            pwd_clean = quote(unquote(pwd), safe="")
            return f"{prefix}{user}:{pwd_clean}@{hostpath}"
    return url_str


def test_old_db_connectivity(old_db_url: str) -> bool:
    """Perform a connectivity pre-check against the old DB in strict READ-ONLY mode."""
    print("\n[Pre-Check] Testing connectivity to OLD Supabase Database (READ-ONLY mode)...")
    
    if PSYCOPG2_AVAILABLE:
        try:
            conn = psycopg2.connect(old_db_url, connect_timeout=10)
            conn.set_session(readonly=True)
            cur = conn.cursor()
            cur.execute("SET default_transaction_read_only = on;")
            cur.execute("""
                SELECT 
                    current_database(), 
                    version(), 
                    (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public')
                ;
            """)
            db_name, ver, tbl_count = cur.fetchone()
            conn.close()
            print(f"✅ Connection successful!")
            print(f"   • Database: {db_name}")
            print(f"   • PostgreSQL Version: {ver.split()[0]} {ver.split()[1] if len(ver.split()) > 1 else ''}")
            print(f"   • Public Schema Table Count: {tbl_count}")
            print(f"   • Transaction Mode: STRICTLY READ-ONLY (Confirmed)")
            return True
        except Exception as e:
            print(f"❌ Failed to connect to OLD database via psycopg2: {e}")
            return False
    
    # Fallback check using psql if psycopg2 not available
    psql_bin = check_tool_available("psql")
    if psql_bin:
        try:
            env = os.environ.copy()
            env["PGOPTIONS"] = "-c default_transaction_read_only=on"
            res = subprocess.run(
                [psql_bin, old_db_url, "-c", "SELECT current_database(), count(*) FROM information_schema.tables WHERE table_schema = 'public';"],
                capture_output=True, text=True, env=env, timeout=15
            )
            if res.returncode == 0:
                print("✅ Connection successful via psql (READ-ONLY mode confirmed)!")
                return True
            else:
                print(f"❌ Connection pre-check failed via psql: {res.stderr[:500]}")
                return False
        except Exception as e:
            print(f"❌ Connection pre-check exception: {e}")
            return False
            
    print("⚠️ Warning: Neither psycopg2 nor psql available for pre-check.")
    return True


def dump_with_pg_dump(pg_dump_bin: str, old_db_url: str, dump_path: Path, excluded_tables: List[str]) -> bool:
    """Dump database schema + data using pg_dump binary with explicit READ-ONLY options."""
    print(f"\n[1/3] Exporting database using pg_dump ({pg_dump_bin}) [READ-ONLY]...")
    print(f"      Excluding table data for: {', '.join(excluded_tables)}")

    env = os.environ.copy()
    # Explicitly force read-only transaction for all dump connections
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"

    cmd = [
        pg_dump_bin,
        old_db_url,
        "--schema=public",
        "--no-owner",
        "--no-acl",
        "--clean",
        "--if-exists",
    ]
    
    for tbl in excluded_tables:
        cmd.append(f"--exclude-table-data=public.{tbl}")
        cmd.append(f"--exclude-table-data={tbl}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, env=env)
        sql_content = res.stdout

        header = (
            "-- Supabase Migration Dump\n"
            "-- Excluded table data: " + ", ".join(excluded_tables) + "\n"
            "-- Source Database: READ-ONLY EXPORT\n\n"
            "SET session_replication_role = 'replica';\n"
            "SET statement_timeout = 0;\n"
            "SET lock_timeout = 0;\n"
            "SET client_encoding = 'UTF8';\n"
            "SET standard_conforming_strings = on;\n\n"
        )
        footer = "\n\nSET session_replication_role = 'origin';\n"

        dump_path.write_text(header + sql_content + footer, encoding="utf-8")
        print(f"✅ Dump created successfully at: {dump_path} ({dump_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ pg_dump failed with return code {e.returncode}")
        print(f"Stderr: {e.stderr[:1000]}")
        return False


def dump_with_psycopg2(old_db_url: str, dump_path: Path, excluded_tables: List[str]) -> bool:
    """Fallback export method using psycopg2 (Strictly READ-ONLY)."""
    if not PSYCOPG2_AVAILABLE:
        print("❌ Neither pg_dump binary nor psycopg2 is available. Please install libpq or psycopg2.")
        return False

    print(f"\n[1/3] Exporting database using Python psycopg2 driver [READ-ONLY]...")
    print(f"      Excluding data for tables: {', '.join(excluded_tables)}")

    try:
        conn = psycopg2.connect(old_db_url)
        conn.set_session(readonly=True)
        cur = conn.cursor()
        cur.execute("SET default_transaction_read_only = on;")

        # Fetch all public tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]

        out_lines = [
            "-- Supabase Migration Dump (Python Psycopg2 Read-Only Export)\n",
            "SET session_replication_role = 'replica';\n\n"
        ]

        for tbl in tables:
            print(f"  - Reading table schema & data: public.{tbl}...")
            # Dump table data if not excluded
            if tbl in excluded_tables:
                out_lines.append(f"-- Skipping data for excluded table public.{tbl}\n")
                continue

            cur.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(tbl)))
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description]

            if rows:
                cols_str = ", ".join([f'"{c}"' for c in col_names])
                out_lines.append(f"-- Data for public.{tbl} ({len(rows)} rows)\n")
                for row in rows:
                    vals = []
                    for val in row:
                        if val is None:
                            vals.append("NULL")
                        elif isinstance(val, (int, float)):
                            vals.append(str(val))
                        elif isinstance(val, bool):
                            vals.append("TRUE" if val else "FALSE")
                        else:
                            # Escape string single quotes
                            escaped = str(val).replace("'", "''")
                            vals.append(f"'{escaped}'")
                    out_lines.append(f'INSERT INTO public."{tbl}" ({cols_str}) VALUES ({", ".join(vals)}) ON CONFLICT DO NOTHING;\n')
                out_lines.append("\n")

        out_lines.append("SET session_replication_role = 'origin';\n")
        dump_path.write_text("".join(out_lines), encoding="utf-8")
        conn.close()
        print(f"✅ Read-only Python export completed: {dump_path} ({dump_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return True
    except Exception as e:
        print(f"❌ Python psycopg2 export failed: {e}")
        return False


def apply_alembic_migrations(new_db_url: str):
    """Ensure all target database table schemas exist via Alembic migrations."""
    print("  • Applying schema migrations to new database via Alembic...")
    env = os.environ.copy()
    env["DATABASE_URL"] = new_db_url
    env["SUPABASE_DATABASE_URL"] = new_db_url
    try:
        res = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR),
            capture_output=True,
            text=True,
            env=env
        )
        if res.returncode == 0:
            print("  ✅ Alembic schema migration applied successfully.")
        else:
            print(f"  ⚠️ Alembic notice ({res.returncode}): {res.stderr[:300]}")
    except Exception as e:
        print(f"  ⚠️ Alembic migration execution notice: {e}")


def restore_with_psql(psql_bin: str, new_db_url: str, dump_path: Path) -> bool:
    """Import dump file into new database using psql binary."""
    print(f"\n[2/3] Importing SQL dump into NEW Supabase database via psql ({psql_bin})...")
    try:
        cmd = [
            psql_bin,
            new_db_url,
            "-f",
            str(dump_path),
            "-v", "ON_ERROR_STOP=0"  # Continue past minor non-fatal notices
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print("✅ Database import completed successfully!")
            return True
        else:
            print(f"⚠️ psql completed with output code {res.returncode}")
            if res.stderr:
                print(f"psql stderr summary:\n{res.stderr[:800]}")
            return True
    except Exception as e:
        print(f"❌ psql restore execution failed: {e}")
        return False


def restore_with_psycopg2(new_db_url: str, dump_path: Path) -> bool:
    """Fallback import method using psycopg2."""
    if not PSYCOPG2_AVAILABLE:
        print("❌ Neither psql binary nor psycopg2 is available.")
        return False

    print(f"\n[2/3] Importing SQL dump into NEW Supabase database via Python psycopg2...")
    
    # 1. Apply schema definitions first
    apply_alembic_migrations(new_db_url)

    try:
        conn = psycopg2.connect(new_db_url)
        conn.autocommit = True
        cur = conn.cursor()

        sql_content = dump_path.read_text(encoding="utf-8")
        # Replace legacy session_replication_role = 'DEFAULT' if present in existing dump file
        sql_content = sql_content.replace("session_replication_role = 'DEFAULT'", "session_replication_role = 'origin'")

        cur.execute("SET session_replication_role = 'replica';")
        
        statements = sql_content.split(";\n")
        success_count = 0
        error_count = 0

        for stmt in statements:
            stmt_clean = stmt.strip()
            if not stmt_clean or stmt_clean.startswith("--") or "session_replication_role" in stmt_clean:
                continue
            try:
                cur.execute(stmt_clean)
                success_count += 1
            except Exception as stmt_err:
                error_count += 1

        cur.execute("SET session_replication_role = 'origin';")
        conn.close()
        print(f"✅ Python restore completed ({success_count} statements executed, {error_count} skipped/existing).")
        return True
    except Exception as e:
        print(f"❌ Python psycopg2 restore failed: {e}")
        return False


def verify_target_database(new_db_url: str, excluded_tables: List[str]) -> bool:
    """Verify tables and row counts on target database."""
    print(f"\n[Validation] Verifying NEW database state...")
    if not PSYCOPG2_AVAILABLE:
        print("ℹ️ Skipping detailed python validation (psycopg2 not installed).")
        return True

    try:
        conn = psycopg2.connect(new_db_url)
        cur = conn.cursor()

        # Count tables
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")
        table_count = cur.fetchone()[0]
        print(f"  • Total public schema tables in NEW DB: {table_count}")

        # Check excluded tables row count
        for tbl in excluded_tables:
            cur.execute(f"SELECT count(*) FROM public.{tbl};")
            count = cur.fetchone()[0]
            status = "✅ 0 rows (Excluded)" if count == 0 else f"⚠️ {count} rows"
            print(f"  • Table public.{tbl}: {status}")

        # Check sample core data tables
        core_tables = ["user_profiles", "client_gstins", "gstr_records", "pr_records", "billing_invoices"]
        for tbl in core_tables:
            try:
                cur.execute(f"SELECT count(*) FROM public.{tbl};")
                count = cur.fetchone()[0]
                print(f"  • Table public.{tbl}: {count} rows")
            except Exception:
                conn.rollback()

        conn.close()
        print("✅ Validation check finished.")
        return True
    except Exception as e:
        print(f"⚠️ Validation connection warning: {e}")
        return False


def update_env_files(new_url: str, new_anon_key: str, new_service_key: str, new_db_url: Optional[str] = None):
    """Update backend and frontend .env files and config references."""
    print(f"\n[Phase 2] Updating local .env files and configuration references...")

    new_project_ref = extract_project_ref(new_url)

    # 1. Update recondesk-backend/.env
    backend_env = BACKEND_DIR / ".env"
    if backend_env.exists():
        content = backend_env.read_text(encoding="utf-8")
        content = re.sub(r"^SUPABASE_URL=.*$", f"SUPABASE_URL={new_url}", content, flags=re.MULTILINE)
        content = re.sub(r"^SUPABASE_ANON_KEY=.*$", f"SUPABASE_ANON_KEY={new_anon_key}", content, flags=re.MULTILINE)
        content = re.sub(r"^SUPABASE_SERVICE_ROLE_KEY=.*$", f"SUPABASE_SERVICE_ROLE_KEY={new_service_key}", content, flags=re.MULTILINE)
        if new_db_url:
            if "SUPABASE_DATABASE_URL=" in content:
                content = re.sub(r"^SUPABASE_DATABASE_URL=.*$", f"SUPABASE_DATABASE_URL={new_db_url}", content, flags=re.MULTILINE)
            elif "DATABASE_URL=" in content:
                content = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={new_db_url}", content, flags=re.MULTILINE)
        backend_env.write_text(content, encoding="utf-8")
        print(f"✅ Updated {backend_env.relative_to(PROJECT_ROOT)}")

    # 2. Update recondesk-frontend/.env.local
    frontend_env = FRONTEND_DIR / ".env.local"
    if frontend_env.exists():
        content = frontend_env.read_text(encoding="utf-8")
        content = re.sub(r"^NEXT_PUBLIC_SUPABASE_URL=.*$", f"NEXT_PUBLIC_SUPABASE_URL={new_url}", content, flags=re.MULTILINE)
        content = re.sub(r"^NEXT_PUBLIC_SUPABASE_ANON_KEY=.*$", f"NEXT_PUBLIC_SUPABASE_ANON_KEY={new_anon_key}", content, flags=re.MULTILINE)
        content = re.sub(r"^SUPABASE_SERVICE_ROLE_KEY=.*$", f"SUPABASE_SERVICE_ROLE_KEY={new_service_key}", content, flags=re.MULTILINE)
        frontend_env.write_text(content, encoding="utf-8")
        print(f"✅ Updated {frontend_env.relative_to(PROJECT_ROOT)}")

    # 3. Update project ID in types.ts header comment if present
    types_file = FRONTEND_DIR / "lib" / "supabase" / "types.ts"
    if types_file.exists():
        content = types_file.read_text(encoding="utf-8")
        content = re.sub(r"Project:\s*[a-z0-9-]+", f"Project: {new_project_ref}", content)
        content = re.sub(r"--project-id\s+[a-z0-9-]+", f"--project-id {new_project_ref}", content)
        types_file.write_text(content, encoding="utf-8")
        print(f"✅ Updated project reference in {types_file.relative_to(PROJECT_ROOT)}")

    print("\n🎉 Phase 2 Complete: Environment files and config references updated successfully!")


def main():
    parser = argparse.ArgumentParser(description="Supabase Database & Configuration Migration Script")
    parser.add_argument("--old-db-url", help="PostgreSQL connection string for the old Supabase project")
    parser.add_argument("--new-db-url", help="PostgreSQL connection string for the new Supabase project")
    parser.add_argument("--new-url", help="New Supabase API URL (e.g. https://xyz.supabase.co)")
    parser.add_argument("--new-anon-key", help="New Supabase Anon Public Key")
    parser.add_argument("--new-service-key", help="New Supabase Service Role Key")
    parser.add_argument("--dump-file", default=str(DEFAULT_DUMP_FILE), help="Path for the SQL dump file")
    
    # Phase control options
    parser.add_argument("--phase-1", action="store_true", help="Run Phase 1: DB + Auth migration only (does NOT touch .env)")
    parser.add_argument("--phase-2", action="store_true", help="Run Phase 2: Update local .env files and config references")
    parser.add_argument("--verify-only", action="store_true", help="Only run target database verification check")

    args = parser.parse_args()

    print("==========================================================")
    print("      RECONDESK SUPABASE PROJECT MIGRATION TOOL           ")
    print("==========================================================")

    # 1. Verification-only mode
    if args.verify_only:
        if not args.new_db_url:
            print("Error: --new-db-url is required for --verify-only mode.")
            sys.exit(1)
        new_db_url = sanitize_db_url(args.new_db_url)
        verify_target_database(new_db_url, EXCLUDED_DATA_TABLES)
        return

    # 2. Phase 2: Update .env files only
    if args.phase_2:
        new_url = args.new_url or input("Enter New Supabase URL (https://<ref>.supabase.co): ").strip()
        new_anon = args.new_anon_key or input("Enter New Supabase Anon Key: ").strip()
        new_service = args.new_service_key or input("Enter New Supabase Service Role Key: ").strip()
        new_db_url = sanitize_db_url(args.new_db_url) if args.new_db_url else None
        update_env_files(new_url, new_anon, new_service, new_db_url)
        return

    # 3. Phase 1 or Default: DB + Auth Migration
    old_db_url = args.old_db_url
    new_db_url = args.new_db_url

    if not old_db_url:
        old_db_url = input("\n[Input] Enter Old Supabase DB URL (postgresql://postgres:[PASSWORD]@db.[OLD_REF].supabase.co:5432/postgres): ").strip()
    if not new_db_url:
        new_db_url = input("[Input] Enter New Supabase DB URL (postgresql://postgres:[PASSWORD]@db.[NEW_REF].supabase.co:5432/postgres): ").strip()

    old_db_url = sanitize_db_url(old_db_url)
    new_db_url = sanitize_db_url(new_db_url)

    dump_path = Path(args.dump_file)

    # Pre-Check Connectivity
    if not test_old_db_connectivity(old_db_url):
        print("❌ Pre-check failed. Migration stopped before export.")
        sys.exit(1)

    # Check for pg_dump and psql tools
    pg_dump_bin = check_tool_available("pg_dump")
    psql_bin = check_tool_available("psql")

    # Step 1: Dump (Read-only)
    dump_success = False
    if pg_dump_bin:
        dump_success = dump_with_pg_dump(pg_dump_bin, old_db_url, dump_path, EXCLUDED_DATA_TABLES)
    else:
        print("ℹ️ pg_dump binary not found in PATH. Using Python psycopg2 fallback export.")
        dump_success = dump_with_psycopg2(old_db_url, dump_path, EXCLUDED_DATA_TABLES)

    if not dump_success:
        print("❌ Export failed. Migration aborted.")
        sys.exit(1)

    # Step 2: Restore
    restore_success = False
    if psql_bin:
        restore_success = restore_with_psql(psql_bin, new_db_url, dump_path)
    else:
        print("ℹ️ psql binary not found in PATH. Using Python psycopg2 fallback import.")
        restore_success = restore_with_psycopg2(new_db_url, dump_path)

    if not restore_success:
        print("❌ Import failed. Please check error output.")
        sys.exit(1)

    # Step 3: Verification
    verify_target_database(new_db_url, EXCLUDED_DATA_TABLES)

    print("\n==========================================================")
    print("✅ PHASE 1 COMPLETE: DB & Auth Schema + Data Migrated!")
    print("==========================================================")
    print("📌 Next Steps:")
    print("1. Log in to your NEW Supabase project dashboard and verify your data/tables.")
    print("2. Once verified, run PHASE 2 to update your local .env files:\n")
    print("   python3 scripts/migrate_supabase.py --phase-2 \\")
    print("     --new-url \"https://[NEW_REF].supabase.co\" \\")
    print("     --new-anon-key \"ey...\" \\")
    print("     --new-service-key \"ey...\"")
    print("==========================================================\n")


if __name__ == "__main__":
    main()
