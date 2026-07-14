"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";

import { useToast } from "@/components/providers/ToastProvider";
import { INDIAN_STATE_NAMES, isValidGSTIN } from "@/components/ui/GstinInput";
import {
  isApiError,
  usersApi,
  type AuthMeProfile,
  type ProfileUpdatePayload,
} from "@/lib/api";
import {
  AUTH_PROFILE_SWR_OPTIONS,
  authProfileFetcher,
} from "@/lib/auth-profile";
import { createClient } from "@/lib/supabase/client";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import { normalizeProfilePhone, validateIndianPhone } from "@/lib/profile-validation";

type ProfileFormValues = {
  fullName: string;
  email: string;
  phone: string;
  firmName: string;
  icaiMembershipNumber: string;
  firmGstin: string;
  state: string;
};

type FieldKey = keyof ProfileFormValues;

type FieldErrors = Partial<Record<FieldKey, string>>;

const FIELD_CLASS =
  "min-h-[44px] w-full rounded-full border-0 bg-[#F5F5F6] px-4 text-sm font-medium text-[var(--ink)] placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-black/10";

const EMPTY_PROFILE_FORM: ProfileFormValues = {
  fullName: "",
  email: "",
  phone: "",
  firmName: "",
  icaiMembershipNumber: "",
  firmGstin: "",
  state: "",
};

function emptyProfileForm(): ProfileFormValues {
  return { ...EMPTY_PROFILE_FORM };
}

function valuesFromProfile(me: AuthMeProfile): ProfileFormValues {
  return {
    fullName: (me.full_name ?? "").trim(),
    email: "",
    phone: me.phone ? normalizeProfilePhone(String(me.phone)) : "",
    firmName: (me.firm_name ?? "").trim(),
    icaiMembershipNumber: (me.icai_membership_number ?? "").trim(),
    firmGstin: (me.firm_gstin ?? "").trim().toUpperCase(),
    state: (me.firm_city ?? "").trim(),
  };
}

function normalizeForCompare(v: ProfileFormValues): ProfileFormValues {
  return {
    fullName: v.fullName.trim(),
    email: v.email.trim().toLowerCase(),
    phone: normalizeProfilePhone(v.phone),
    firmName: v.firmName.trim(),
    icaiMembershipNumber: v.icaiMembershipNumber.trim(),
    firmGstin: v.firmGstin.trim().replace(/\s/g, "").toUpperCase(),
    state: v.state.trim(),
  };
}

function payloadFromValues(v: ProfileFormValues): ProfileUpdatePayload {
  const n = normalizeForCompare(v);
  return {
    full_name: n.fullName,
    phone: n.phone || null,
    firm_name: n.firmName || null,
    icai_membership_number: n.icaiMembershipNumber || null,
    firm_gstin: n.firmGstin || null,
    firm_city: n.state || null,
  };
}

function ProfileFormSkeleton() {
  return (
    <div className="dashboard-card animate-pulse space-y-6 p-5 md:p-6">
      <div className="h-4 w-full max-w-md rounded bg-gray-100" />
      <div className="grid gap-4 md:grid-cols-2">
        {[1, 2, 3, 4, 5, 6].map((i) => (
          <div key={i} className="space-y-2">
            <div className="h-4 w-24 rounded bg-gray-100" />
            <div className="h-11 rounded-full bg-gray-100" />
          </div>
        ))}
      </div>
      <div className="h-11 w-32 rounded-full bg-gray-100" />
    </div>
  );
}

function FieldLabel({
  htmlFor,
  children,
  required,
}: {
  htmlFor: string;
  children: React.ReactNode;
  required?: boolean;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="mb-1 block text-sm font-medium text-[var(--text-primary)]"
    >
      {children}
      {required ? <span className="text-[var(--danger)]"> *</span> : null}
    </label>
  );
}

export default function ProfileSettingsPage() {
  const toast = useToast();
  const tokenState = useAccessToken();
  const authToken =
    typeof tokenState === "string" && tokenState.trim().length > 0
      ? tokenState.trim()
      : null;

  const meKey = authToken ? (["/api/v1/auth/me", authToken] as const) : null;
  const { data: me, error: meError, isLoading: meLoading } = useSWR(
    meKey,
    ([, t]) => authProfileFetcher(t),
    AUTH_PROFILE_SWR_OPTIONS
  );

  const [values, setValues] = useState<ProfileFormValues | null>(null);
  const [baseline, setBaseline] = useState<ProfileFormValues | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [loadSettled, setLoadSettled] = useState(false);
  const [authEmail, setAuthEmail] = useState("");

  useEffect(() => {
    if (!authToken) {
      setAuthEmail("");
      return;
    }
    const supabase = createClient();
    const syncAuthEmail = () => {
      void supabase.auth.getUser().then(({ data: { user } }) => {
        setAuthEmail((user?.email ?? "").trim());
      });
    };
    syncAuthEmail();
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(() => {
      syncAuthEmail();
    });
    return () => subscription.unsubscribe();
  }, [authToken]);

  useEffect(() => {
    if (!authToken) {
      setValues(null);
      setBaseline(null);
      setLoadSettled(false);
      return;
    }
    setValues(null);
    setBaseline(null);
    setLoadSettled(false);
    setErrors({});
  }, [authToken]);

  useEffect(() => {
    if (!me) return;
    const next = valuesFromProfile(me);
    setValues(next);
    setBaseline(next);
    setErrors({});
    setLoadSettled(true);
  }, [me]);

  useEffect(() => {
    if (!authToken || loadSettled || meLoading) return;
    if (meError || !me) {
      const empty = emptyProfileForm();
      setValues(empty);
      setBaseline(empty);
      setLoadSettled(true);
    }
  }, [authToken, loadSettled, meLoading, meError, me]);

  useEffect(() => {
    if (!authToken || loadSettled) return;
    const timer = window.setTimeout(() => {
      const empty = emptyProfileForm();
      setValues((current) => current ?? empty);
      setBaseline((current) => current ?? empty);
      setLoadSettled(true);
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [authToken, loadSettled]);

  const isDirty = useMemo(() => {
    if (!values || !baseline) return false;
    return JSON.stringify(normalizeForCompare(values)) !== JSON.stringify(normalizeForCompare(baseline));
  }, [values, baseline]);

  const setField = useCallback((key: FieldKey, value: string) => {
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev));
    setErrors((prev) => {
      if (!prev[key]) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const validateRequired = useCallback((v: ProfileFormValues): FieldErrors => {
    const next: FieldErrors = {};
    if (!v.fullName.trim()) next.fullName = "Full name is required";
    const phoneErr = validateIndianPhone(v.phone);
    if (phoneErr) next.phone = phoneErr;
    const gst = v.firmGstin.trim().replace(/\s/g, "").toUpperCase();
    if (gst && !isValidGSTIN(gst)) next.firmGstin = "Invalid GSTIN format";
    return next;
  }, []);

  const handleGstinBlur = useCallback(() => {
    if (!values) return;
    const gst = values.firmGstin.trim().replace(/\s/g, "").toUpperCase();
    setErrors((prev) => {
      const next = { ...prev };
      if (!gst || isValidGSTIN(gst)) delete next.firmGstin;
      else next.firmGstin = "Invalid GSTIN format";
      return next;
    });
  }, [values]);

  const handleBlurRequired = useCallback(
    (key: "fullName" | "phone") => {
      if (!values) return;
      const fieldErrors = validateRequired(values);
      const msg = fieldErrors[key];
      setErrors((prev) => {
        const next = { ...prev };
        if (msg) next[key] = msg;
        else delete next[key];
        return next;
      });
    },
    [values, validateRequired]
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!authToken || !values) return;

    const fieldErrors = validateRequired(values);
    if (Object.keys(fieldErrors).length > 0) {
      setErrors(fieldErrors);
      return;
    }

    setSaving(true);
    try {
      const updated = await usersApi.updateProfile(authToken, payloadFromValues(values));
      const next = valuesFromProfile(updated);
      setValues(next);
      setBaseline(next);
      setErrors({});
      if (meKey) {
        await mutate(meKey, updated, { revalidate: false });
      }
      toast("Profile saved", "success");
    } catch (err: unknown) {
      const msg = isApiError(err) ? err.detail : "Could not save profile.";
      toast(msg, "error");
    } finally {
      setSaving(false);
    }
  };

  if (tokenState === null || (authToken && !loadSettled)) {
    return (
      <div className="space-y-6">
        <Link
          href="/settings"
          className="inline-flex min-h-[44px] items-center text-sm font-semibold text-[var(--ink)] underline"
        >
          ← Back to settings
        </Link>
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">Profile</h1>
        <ProfileFormSkeleton />
      </div>
    );
  }

  if (!authToken) {
    return (
      <div className="space-y-4">
        <Link
          href="/settings"
          className="inline-flex min-h-[44px] items-center text-sm font-semibold text-[var(--ink)] underline"
        >
          ← Back to settings
        </Link>
        <div className="dashboard-card px-5 py-8 text-center text-sm text-gray-500">
          Sign in required to edit your profile.
        </div>
      </div>
    );
  }

  const formValues = values ?? emptyProfileForm();
  const displayEmail = authEmail.trim();

  const inputClass = (key: FieldKey) =>
    `${FIELD_CLASS}${errors[key] ? " border-red-300" : ""}`;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/settings"
          className="inline-flex min-h-[40px] items-center text-sm font-semibold text-[var(--ink)] hover:underline"
        >
          ← Back to settings
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--ink)]">
          Profile
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Your name, firm, and contact details
        </p>
      </div>

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-6">
        <div className="dashboard-card px-5 py-4 text-sm text-gray-600">
          This information appears on your exported reconciliation reports.
        </div>

        <div className="dashboard-card space-y-6 p-5 md:p-6">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <FieldLabel htmlFor="profile-full-name" required>
                Full Name
              </FieldLabel>
              <input
                id="profile-full-name"
                type="text"
                required
                value={formValues.fullName}
                onChange={(e) => setField("fullName", e.target.value)}
                onBlur={() => handleBlurRequired("fullName")}
                className={inputClass("fullName")}
                autoComplete="name"
              />
              {errors.fullName && (
                <p className="mt-1 text-xs text-red-600">{errors.fullName}</p>
              )}
            </div>

            <div>
              <FieldLabel htmlFor="profile-email">Email</FieldLabel>
              <input
                id="profile-email"
                type="email"
                value={displayEmail}
                readOnly
                disabled
                className={`${inputClass("email")} cursor-not-allowed bg-gray-50 text-[var(--text-secondary)]`}
                autoComplete="email"
              />
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                To change your email, contact support.
              </p>
            </div>

            <div>
              <FieldLabel htmlFor="profile-phone">Phone Number</FieldLabel>
              <input
                id="profile-phone"
                type="tel"
                inputMode="numeric"
                value={formValues.phone}
                onChange={(e) =>
                  setField("phone", e.target.value.replace(/[^\d+\s-]/g, ""))
                }
                onBlur={() => handleBlurRequired("phone")}
                className={inputClass("phone")}
                placeholder="10-digit mobile"
                autoComplete="tel"
              />
              {errors.phone && (
                <p className="mt-1 text-xs text-red-600">{errors.phone}</p>
              )}
            </div>

            <div>
              <FieldLabel htmlFor="profile-firm-name">Firm Name</FieldLabel>
              <input
                id="profile-firm-name"
                type="text"
                value={formValues.firmName}
                onChange={(e) => setField("firmName", e.target.value)}
                className={inputClass("firmName")}
                autoComplete="organization"
              />
            </div>

            <div>
              <FieldLabel htmlFor="profile-icai">ICAI Membership Number</FieldLabel>
              <input
                id="profile-icai"
                type="text"
                value={formValues.icaiMembershipNumber}
                onChange={(e) => setField("icaiMembershipNumber", e.target.value)}
                className={inputClass("icaiMembershipNumber")}
              />
            </div>

            <div>
              <FieldLabel htmlFor="profile-firm-gstin">Firm GSTIN</FieldLabel>
              <input
                id="profile-firm-gstin"
                type="text"
                value={formValues.firmGstin}
                onChange={(e) => setField("firmGstin", e.target.value.toUpperCase())}
                onBlur={handleGstinBlur}
                className={inputClass("firmGstin")}
                placeholder="27AAAAA0000A1Z5"
                spellCheck={false}
                maxLength={15}
              />
              {errors.firmGstin && (
                <p className="mt-1 text-xs text-red-600">{errors.firmGstin}</p>
              )}
            </div>

            <div className="md:col-span-2 md:max-w-md">
              <FieldLabel htmlFor="profile-state">State</FieldLabel>
              <select
                id="profile-state"
                value={formValues.state}
                onChange={(e) => setField("state", e.target.value)}
                className={inputClass("state")}
              >
                <option value="">Select state</option>
                {INDIAN_STATE_NAMES.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-[#F0F0F0] pt-5">
            <button
              type="submit"
              disabled={!isDirty || saving}
              className="inline-flex min-h-[44px] items-center justify-center rounded-full bg-[var(--ink)] px-6 text-sm font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
