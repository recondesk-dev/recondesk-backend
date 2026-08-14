/**
 * Auto-generated from the live Supabase project schema.
 * Project: avhaubudivhyhcvankfi
 *
 * To regenerate:
 *   npx supabase gen types typescript --project-id avhaubudivhyhcvankfi > lib/supabase/types.ts
 *   (requires: supabase login)
 */

export type Json = string | number | boolean | null | { [key: string]: Json } | Json[];

export type UserRole = "Admin" | "Staff";
export type ReconciliationStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "finalized";
export type MatchStatus = "matched" | "missed" | "wrongful_risk" | "unmatched" | "review";
export type RecordType = "gstr" | "pr";
export type TeamMemberRole = "Staff" | "Manager";
export type PaymentStatus = "created" | "paid" | "failed" | "refunded";

export type Database = {
  __InternalSupabase: {
    PostgrestVersion: "12";
  };
  public: {
    Tables: {
      user_profiles: {
        Row: {
          id: string;
          email: string | null;
          full_name: string | null;
          firm_name: string | null;
          phone: string | null;
          role: UserRole;
          is_active: boolean | null;
          plan: string | null;
          runs_used: number | null;
          runs_limit: number | null;
          free_runs_remaining: number | null;
          runs_balance: number | null;
          gstin_limit: number | null;
          subscription_ends_at: string | null;
          firm_city: string | null;
          icai_membership_number: string | null;
          firm_gstin: string | null;
          onboarding_completed: boolean | null;
          demo_tour_seen: boolean | null;
          showcase_seen: boolean | null;
          created_at: string | null;
        };
        Insert: {
          id: string;
          email?: string | null;
          full_name?: string | null;
          firm_name?: string | null;
          phone?: string | null;
          role?: UserRole;
          is_active?: boolean | null;
          plan?: string | null;
          runs_used?: number | null;
          runs_limit?: number | null;
          gstin_limit?: number | null;
          subscription_ends_at?: string | null;
          firm_city?: string | null;
          icai_membership_number?: string | null;
          firm_gstin?: string | null;
          onboarding_completed?: boolean | null;
          demo_tour_seen?: boolean | null;
          created_at?: string | null;
        };
        Update: {
          email?: string | null;
          full_name?: string | null;
          firm_name?: string | null;
          phone?: string | null;
          role?: UserRole;
          is_active?: boolean | null;
          plan?: string | null;
          runs_used?: number | null;
          runs_limit?: number | null;
          runs_balance?: number | null;
          free_runs_remaining?: number | null;
          gstin_limit?: number | null;
          subscription_ends_at?: string | null;
          firm_city?: string | null;
          icai_membership_number?: string | null;
          firm_gstin?: string | null;
          onboarding_completed?: boolean | null;
          demo_tour_seen?: boolean | null;
        };
        Relationships: [];
      };

      client_gstins: {
        Row: {
          id: string;
          firm_owner_id: string;
          gstin: string;
          trade_name: string | null;
          legal_name: string | null;
          state_code: string | null;
          registration_type: string | null;
          assigned_to: string | null;
          scheme_type: 'regular' | 'composition' | 'casual' | 'nrtp' | 'isd' | 'tds_tcs_deductor';
          filing_frequency: 'monthly' | 'qrmp';
          is_demo: boolean;
          is_active: boolean;
          added_at: string;
        };
        Insert: {
          id?: string;
          firm_owner_id: string;
          gstin: string;
          trade_name?: string | null;
          legal_name?: string | null;
          state_code?: string | null;
          registration_type?: string | null;
          assigned_to?: string | null;
          scheme_type?: 'regular' | 'composition' | 'casual' | 'nrtp' | 'isd' | 'tds_tcs_deductor';
          filing_frequency?: 'monthly' | 'qrmp';
          is_demo?: boolean;
          is_active?: boolean;
          added_at?: string;
        };
        Update: {
          gstin?: string;
          trade_name?: string | null;
          legal_name?: string | null;
          state_code?: string | null;
          registration_type?: string | null;
          assigned_to?: string | null;
          scheme_type?: 'regular' | 'composition' | 'casual' | 'nrtp' | 'isd' | 'tds_tcs_deductor';
          filing_frequency?: 'monthly' | 'qrmp';
          is_demo?: boolean;
          is_active?: boolean;
        };
        Relationships: [];
      };

      reconciliation_runs: {
        Row: {
          id: string;
          firm_owner_id: string;
          assigned_to: string | null;
          client_gstin_id: string;
          period: string;
          run_number: number;
          status: ReconciliationStatus;
          progress_percent: number;
          status_message: string | null;
          gstr_file_key: string | null;
          pr_file_key: string | null;
          gstr_records_imported: number;
          pr_records_imported: number;
          matched_count: number | null;
          missed_itc_count: number | null;
          wrongful_risk_count: number | null;
          total_gstr_itc_paise: number | null;
          matched_itc_paise: number | null;
          missed_itc_paise: number | null;
          wrongful_risk_paise: number | null;
          sanity_all_passed: boolean | null;
          sanity_report: Json | null;
          processing_started_at: string | null;
          processing_completed_at: string | null;
          finalized_at: string | null;
          finalized_by: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          firm_owner_id: string;
          assigned_to?: string | null;
          client_gstin_id: string;
          period: string;
          run_number?: number;
          status?: ReconciliationStatus;
          progress_percent?: number;
          status_message?: string | null;
          gstr_file_key?: string | null;
          pr_file_key?: string | null;
          gstr_records_imported?: number;
          pr_records_imported?: number;
          created_at?: string;
        };
        Update: {
          assigned_to?: string | null;
          status?: ReconciliationStatus;
          progress_percent?: number;
          status_message?: string | null;
          matched_count?: number | null;
          missed_itc_count?: number | null;
          wrongful_risk_count?: number | null;
          total_gstr_itc_paise?: number | null;
          matched_itc_paise?: number | null;
          missed_itc_paise?: number | null;
          wrongful_risk_paise?: number | null;
          sanity_all_passed?: boolean | null;
          sanity_report?: Json | null;
          processing_started_at?: string | null;
          processing_completed_at?: string | null;
          finalized_at?: string | null;
          finalized_by?: string | null;
        };
        Relationships: [];
      };

      gstr_records: {
        Row: {
          id: string;
          run_id: string;
          supplier_gstin_raw: string | null;
          supplier_gstin: string | null;
          invoice_number_raw: string | null;
          invoice_number: string | null;
          invoice_date_raw: string | null;
          invoice_date: string | null;
          taxable_amount_raw: string | null;
          taxable_amount_paise: number | null;
          igst_paise: number | null;
          cgst_paise: number | null;
          sgst_paise: number | null;
          total_tax_paise: number | null;
          hsn_code: string | null;
          document_type: string | null;
          is_amendment: boolean;
          match_status: MatchStatus | null;
          match_level: number | null;
          match_confidence: number | null;
          matched_pr_record_id: string | null;
          match_reason: string | null;
          match_discrepancies: Json | null;
          possible_blocked_credit: boolean | null;
          decision_what: string | null;
          decision_why: string | null;
          decision_next: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          run_id: string;
          supplier_gstin_raw?: string | null;
          supplier_gstin?: string | null;
          invoice_number_raw?: string | null;
          invoice_number?: string | null;
          invoice_date_raw?: string | null;
          invoice_date?: string | null;
          taxable_amount_raw?: string | null;
          taxable_amount_paise?: number | null;
          igst_paise?: number | null;
          cgst_paise?: number | null;
          sgst_paise?: number | null;
          total_tax_paise?: number | null;
          hsn_code?: string | null;
          document_type?: string | null;
          is_amendment?: boolean;
          created_at?: string;
        };
        Update: {
          match_status?: MatchStatus | null;
          match_level?: number | null;
          match_confidence?: number | null;
          matched_pr_record_id?: string | null;
          match_reason?: string | null;
          match_discrepancies?: Json | null;
          possible_blocked_credit?: boolean | null;
          decision_what?: string | null;
          decision_why?: string | null;
          decision_next?: string | null;
        };
        Relationships: [];
      };

      pr_records: {
        Row: {
          id: string;
          run_id: string;
          supplier_gstin_raw: string | null;
          supplier_gstin: string | null;
          invoice_number_raw: string | null;
          invoice_number: string | null;
          invoice_date_raw: string | null;
          invoice_date: string | null;
          taxable_amount_raw: string | null;
          taxable_amount_paise: number | null;
          igst_paise: number | null;
          cgst_paise: number | null;
          sgst_paise: number | null;
          hsn_code: string | null;
          document_type: string | null;
          is_amendment: boolean;
          match_status: MatchStatus | null;
          match_level: number | null;
          match_confidence: number | null;
          matched_pr_record_id: string | null;
          match_reason: string | null;
          possible_blocked_credit: boolean | null;
          payment_date: string | null;
          is_paid: boolean | null;
          rule_37_status: string | null;
          rule_37_deadline: string | null;
          source_software: string | null;
          decision_what: string | null;
          decision_why: string | null;
          decision_next: string | null;
          sanity_gstin_valid: boolean | null;
          sanity_date_valid: boolean | null;
          sanity_amount_valid: boolean | null;
          sanity_duplicate_flag: boolean | null;
          discrepancy_gstin: string | null;
          discrepancy_amount_diff_paise: number | null;
          discrepancy_date_diff_days: number | null;
          discrepancy_notes: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          run_id: string;
          supplier_gstin_raw?: string | null;
          supplier_gstin?: string | null;
          invoice_number_raw?: string | null;
          invoice_number?: string | null;
          invoice_date_raw?: string | null;
          invoice_date?: string | null;
          taxable_amount_raw?: string | null;
          taxable_amount_paise?: number | null;
          igst_paise?: number | null;
          cgst_paise?: number | null;
          sgst_paise?: number | null;
          hsn_code?: string | null;
          document_type?: string | null;
          is_amendment?: boolean;
          source_software?: string | null;
          created_at?: string;
        };
        Update: {
          match_status?: MatchStatus | null;
          match_level?: number | null;
          match_confidence?: number | null;
          matched_pr_record_id?: string | null;
          match_reason?: string | null;
          possible_blocked_credit?: boolean | null;
          payment_date?: string | null;
          is_paid?: boolean | null;
          rule_37_status?: string | null;
          rule_37_deadline?: string | null;
          decision_what?: string | null;
          decision_why?: string | null;
          decision_next?: string | null;
          discrepancy_gstin?: string | null;
          discrepancy_amount_diff_paise?: number | null;
          discrepancy_date_diff_days?: number | null;
          discrepancy_notes?: string | null;
        };
        Relationships: [];
      };

      mismatch_notes: {
        Row: {
          id: string;
          record_id: string;
          record_type: RecordType;
          run_id: string;
          user_id: string;
          note: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          record_id: string;
          record_type: RecordType;
          run_id: string;
          user_id: string;
          note: string;
          created_at?: string;
        };
        Update: {
          note?: string;
        };
        Relationships: [];
      };

      team_members: {
        Row: {
          id: string;
          firm_owner_id: string;
          member_user_id: string;
          role: TeamMemberRole;
          invited_at: string;
          accepted_at: string | null;
          is_active: boolean;
        };
        Insert: {
          id?: string;
          firm_owner_id: string;
          member_user_id: string;
          role?: TeamMemberRole;
          invited_at?: string;
          accepted_at?: string | null;
          is_active?: boolean;
        };
        Update: {
          role?: TeamMemberRole;
          accepted_at?: string | null;
          is_active?: boolean;
        };
        Relationships: [];
      };

      payments: {
        Row: {
          id: string;
          firm_owner_id: string;
          run_id: string | null;
          razorpay_order_id: string | null;
          razorpay_payment_id: string | null;
          amount_paise: number;
          status: PaymentStatus;
          plan: string | null;
          runs_purchased: number | null;
          base_amount_paise: number | null;
          gst_paise: number | null;
          total_amount_paise: number | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          firm_owner_id: string;
          run_id?: string | null;
          razorpay_order_id?: string | null;
          razorpay_payment_id?: string | null;
          amount_paise?: number;
          status?: PaymentStatus;
          plan?: string | null;
          runs_purchased?: number | null;
          base_amount_paise?: number | null;
          gst_paise?: number | null;
          total_amount_paise?: number | null;
          created_at?: string;
        };
        Update: {
          id?: string;
          firm_owner_id?: string;
          run_id?: string | null;
          razorpay_order_id?: string | null;
          razorpay_payment_id?: string | null;
          amount_paise?: number;
          status?: PaymentStatus;
          plan?: string | null;
          runs_purchased?: number | null;
          base_amount_paise?: number | null;
          gst_paise?: number | null;
          total_amount_paise?: number | null;
          created_at?: string;
        };
        Relationships: [];
      };

      run_credits: {
        Row: {
          id: string;
          firm_owner_id: string;
          payment_id: string | null;
          plan: string;
          runs_purchased: number;
          runs_remaining: number;
          purchased_at: string;
          expires_at: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          firm_owner_id: string;
          payment_id?: string | null;
          plan: string;
          runs_purchased: number;
          runs_remaining: number;
          purchased_at?: string;
          expires_at: string;
          created_at?: string;
        };
        Update: {
          id?: string;
          firm_owner_id?: string;
          payment_id?: string | null;
          plan?: string;
          runs_purchased?: number;
          runs_remaining?: number;
          purchased_at?: string;
          expires_at?: string;
          created_at?: string;
        };
        Relationships: [];
      };

      audit_logs: {
        Row: {
          id: string;
          user_id: string | null;
          action: string;
          entity_type: string | null;
          entity_id: string | null;
          metadata: Json | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          user_id?: string | null;
          action: string;
          entity_type?: string | null;
          entity_id?: string | null;
          metadata?: Json | null;
          created_at?: string;
        };
        Update: Record<string, never>;
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
  };
};
