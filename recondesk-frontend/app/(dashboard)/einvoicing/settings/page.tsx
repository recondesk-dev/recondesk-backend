"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Building2,
  Users,
  Package,
  Plus,
  Trash2,
  Edit2,
  Check,
  ArrowLeft,
  Save,
  AlertCircle,
  X,
  Sparkles,
  Lock,
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  clientsApi,
  ClientGstin,
  billingModuleApi,
  BillingCompanyProfile,
  BillingCustomer,
  BillingItem,
  HsnSuggestion,
} from "@/lib/api";

import { INDIAN_STATES, getStateNameByCode, GST_UQC_CODES } from "@/lib/constants";

function MasterDataSettingsContent() {
  const searchParams = useSearchParams();
  const token = useAccessToken();

  const [clients, setClients] = useState<ClientGstin[]>([]);
  const [clientGstinId, setClientGstinId] = useState<string>(
    searchParams.get("client_gstin_id") || ""
  );
  const [activeTab, setActiveTab] = useState<"company" | "customers" | "items" | "credentials">("company");

  // e-Invoice Credentials state
  const [hasCredentials, setHasCredentials] = useState<boolean | null>(null);
  const [credUsername, setCredUsername] = useState<string>("");
  const [credPassword, setCredPassword] = useState<string>("");
  const [credLastUpdated, setCredLastUpdated] = useState<string | null>(null);

  // Load credential status for active client
  useEffect(() => {
    if (!token || !clientGstinId) return;
    billingModuleApi
      .getCredentialsStatus(token, clientGstinId)
      .then((res) => {
        setHasCredentials(res?.has_credentials ?? false);
        if (res?.username) setCredUsername(res.username);
        if (res?.updated_at) setCredLastUpdated(res.updated_at);
      })
      .catch(() => setHasCredentials(false));
  }, [token, clientGstinId]);

  // Company Profile state
  const [companyProfile, setCompanyProfile] = useState<Partial<BillingCompanyProfile>>({
    legal_name: "",
    trade_name: "",
    gstin: "",
    pan: "",
    address_line1: "",
    address_line2: "",
    city: "",
    state: "Maharashtra",
    state_code: "27",
    pincode: "",
    bank_account_number: "",
    bank_ifsc: "",
    bank_name: "",
    invoice_number_prefix: "INV/",
    invoice_number_next_seq: 1,
  });
  const [profileId, setProfileId] = useState<string | null>(null);

  // Customer List state
  const [customers, setCustomers] = useState<BillingCustomer[]>([]);
  const [showCustomerModal, setShowCustomerModal] = useState<boolean>(false);
  const [editingCustomer, setEditingCustomer] = useState<Partial<BillingCustomer>>({
    name: "",
    gstin: "",
    is_b2b: true,
    address_line1: "",
    city: "",
    state: "Maharashtra",
    state_code: "27",
    pincode: "",
  });

  // Item List state
  const [items, setItems] = useState<BillingItem[]>([]);
  const [showItemModal, setShowItemModal] = useState<boolean>(false);
  const [editingItem, setEditingItem] = useState<Partial<BillingItem>>({
    name: "",
    hsn_or_sac_code: "9983",
    unit: "NOS",
    default_rate: 10000,
    default_tax_rate_percent: 18.0,
    item_type: "service",
  });

  // HSN/SAC auto-suggest & mismatch detection state
  const [hsnSuggestions, setHsnSuggestions] = useState<HsnSuggestion[]>([]);
  const [hsnLoading, setHsnLoading] = useState<boolean>(false);
  const [showHsnDropdown, setShowHsnDropdown] = useState<boolean>(false);
  const [typeMismatchWarning, setTypeMismatchWarning] = useState<string | null>(null);

  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Debounced HSN/SAC auto-suggest as user types item name
  useEffect(() => {
    if (!showItemModal || !editingItem.name || editingItem.name.trim().length < 2) {
      setHsnSuggestions([]);
      setShowHsnDropdown(false);
      return;
    }

    const timer = setTimeout(async () => {
      if (!token) return;
      try {
        setHsnLoading(true);
        const results = await billingModuleApi.suggestHsn(
          token,
          (editingItem.name || "").trim(),
          editingItem.item_type
        );
        setHsnSuggestions(results || []);
        setShowHsnDropdown(Boolean(results && results.length > 0));
      } catch (err) {
        console.error("Error fetching HSN suggestions:", err);
        setHsnSuggestions([]);
        setShowHsnDropdown(false);
      } finally {
        setHsnLoading(false);
      }
    }, 400);

    return () => clearTimeout(timer);
  }, [showItemModal, editingItem.name, editingItem.item_type, token]);

  // Inline mismatch detection for HSN (goods) vs SAC (service 99xx)
  useEffect(() => {
    if (!showItemModal || !editingItem.hsn_or_sac_code || !editingItem.item_type) {
      setTypeMismatchWarning(null);
      return;
    }

    const code = editingItem.hsn_or_sac_code.trim();
    const digits = code.replace(/\D/g, "");
    if (!digits || digits.length < 2) {
      setTypeMismatchWarning(null);
      return;
    }

    const isSac = digits.startsWith("99");
    const currentType = editingItem.item_type;

    if (isSac && currentType === "goods") {
      setTypeMismatchWarning(
        "This looks like a Service (SAC 99xx) code, but Item Type is set to Goods. Please confirm this is correct."
      );
    } else if (!isSac && currentType === "service") {
      setTypeMismatchWarning(
        "This looks like a Goods (HSN) code, but Item Type is set to Service. Please confirm this is correct."
      );
    } else {
      setTypeMismatchWarning(null);
    }
  }, [showItemModal, editingItem.hsn_or_sac_code, editingItem.item_type]);

  // Load clients
  useEffect(() => {
    if (!token) return;
    clientsApi.list(token).then((data) => {
      setClients(data || []);
      if (!clientGstinId && data && data.length > 0) {
        setClientGstinId(data[0].id);
      }
    });
  }, [token]);

  // Load data for active client
  useEffect(() => {
    if (!token || !clientGstinId) return;
    setLoading(true);
    setMessage(null);

    Promise.all([
      billingModuleApi.listCompanyProfiles(token, clientGstinId),
      billingModuleApi.listCustomers(token, clientGstinId),
      billingModuleApi.listItems(token, clientGstinId),
    ])
      .then(([profiles, custs, itemCatalog]) => {
        if (profiles && profiles.length > 0) {
          setCompanyProfile(profiles[0]);
          setProfileId(profiles[0].id);
        } else {
          const selClient = clients.find((c) => c.id === clientGstinId);
          setCompanyProfile({
            legal_name: selClient?.legal_name || selClient?.trade_name || "",
            trade_name: selClient?.trade_name || "",
            gstin: selClient?.gstin || "",
            pan: selClient?.gstin ? selClient.gstin.substring(2, 12) : "",
            address_line1: "",
            city: "",
            state: "Maharashtra",
            state_code: selClient?.gstin ? selClient.gstin.substring(0, 2) : "27",
            pincode: "",
            invoice_number_prefix: "INV/",
            invoice_number_next_seq: 1,
          });
          setProfileId(null);
        }

        setCustomers(custs || []);
        setItems(itemCatalog || []);
      })
      .catch((err) => {
        console.error("Error loading master data:", err);
      })
      .finally(() => setLoading(false));
  }, [token, clientGstinId, clients]);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !clientGstinId) return;
    setSaving(true);
    setMessage(null);

    try {
      if (profileId) {
        await billingModuleApi.updateCompanyProfile(token, profileId, clientGstinId, companyProfile);
      } else {
        const created = await billingModuleApi.createCompanyProfile(token, {
          ...companyProfile,
          client_gstin_id: clientGstinId,
        } as any);
        setProfileId(created.id);
      }
      setMessage({ type: "success", text: "Company profile saved successfully" });
    } catch (err: any) {
      const text = err?.detail || err?.message || (typeof err === "string" ? err : "Failed to save company profile");
      setMessage({ type: "error", text });
    } finally {
      setSaving(false);
    }
  };

  const handleSaveCustomer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !clientGstinId) return;
    setSaving(true);
    setMessage(null);

    try {
      if (editingCustomer.id) {
        await billingModuleApi.updateCustomer(token, editingCustomer.id, clientGstinId, editingCustomer);
      } else {
        await billingModuleApi.createCustomer(token, {
          ...editingCustomer,
          client_gstin_id: clientGstinId,
        } as any);
      }
      setShowCustomerModal(false);
      const updated = await billingModuleApi.listCustomers(token, clientGstinId);
      setCustomers(updated || []);
      setMessage({ type: "success", text: "Customer saved successfully" });
    } catch (err: any) {
      const text = err?.detail || err?.message || (typeof err === "string" ? err : "Failed to save customer");
      setMessage({ type: "error", text });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteCustomer = async (id: string) => {
    if (!token || !clientGstinId || !confirm("Are you sure you want to delete this customer?")) return;
    try {
      await billingModuleApi.deleteCustomer(token, id, clientGstinId);
      setCustomers((prev) => prev.filter((c) => c.id !== id));
    } catch (err: any) {
      alert(err?.detail || err?.message || "Failed to delete customer");
    }
  };

  const handleSaveItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !clientGstinId) return;
    setSaving(true);
    setMessage(null);

    try {
      if (editingItem.id) {
        await billingModuleApi.updateItem(token, editingItem.id, clientGstinId, editingItem);
      } else {
        await billingModuleApi.createItem(token, {
          ...editingItem,
          client_gstin_id: clientGstinId,
        } as any);
      }
      setShowItemModal(false);
      const updated = await billingModuleApi.listItems(token, clientGstinId);
      setItems(updated || []);
      setMessage({ type: "success", text: "Item saved successfully" });
    } catch (err: any) {
      const text = err?.detail || err?.message || (typeof err === "string" ? err : "Failed to save item");
      setMessage({ type: "error", text });
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteItem = async (id: string) => {
    if (!token || !clientGstinId || !confirm("Are you sure you want to delete this item?")) return;
    try {
      await billingModuleApi.deleteItem(token, id, clientGstinId);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (err: any) {
      alert(err.detail || "Failed to delete item");
    }
  };

  const handleSaveCredentials = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !clientGstinId || !credUsername || !credPassword) return;
    setSaving(true);
    setMessage(null);

    try {
      const res = await billingModuleApi.saveCredentials(token, clientGstinId, credUsername, credPassword);
      if (res && res.has_credentials) {
        setHasCredentials(true);
        setCredLastUpdated(res.updated_at || new Date().toISOString());
        setCredPassword("");
        setMessage({ type: "success", text: "e-Invoice portal API credentials saved securely." });
      }
    } catch (err: any) {
      const text = err?.detail || err?.message || (typeof err === "string" ? err : "Failed to save e-Invoice credentials");
      setMessage({ type: "error", text });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-800 hover:text-black font-semibold mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices
          </Link>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">E-Invoicing Master Data</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Manage company profile, customer registry, item master catalog, and e-Invoice portal credentials.
          </p>
        </div>

        {/* Client Selector */}
        <div className="flex items-center gap-2 bg-white border border-gray-200 rounded-xl px-3.5 py-2 shadow-sm">
          <Building2 className="w-4 h-4 text-slate-400" />
          <span className="text-xs text-slate-500 font-medium">Client:</span>
          <select
            value={clientGstinId}
            onChange={(e) => setClientGstinId(e.target.value)}
            className="bg-transparent text-slate-900 text-sm font-semibold focus:outline-none cursor-pointer"
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id} className="text-slate-900">
                {c.trade_name || c.legal_name || c.gstin} ({c.gstin})
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Alert Messages */}
      {message && (
        <div
          className={`p-4 rounded-xl flex items-center gap-3 text-sm font-medium border ${
            message.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-900"
              : "bg-red-50 border-red-200 text-red-900"
          }`}
        >
          {message.type === "success" ? (
            <Check className="w-5 h-5 text-emerald-600" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-600" />
          )}
          {message.text}
        </div>
      )}

      {/* Tabs Header */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab("company")}
          className={`px-5 py-3 text-sm font-bold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "company"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-900"
          }`}
        >
          <Building2 className="w-4 h-4" /> Company Profile
        </button>
        <button
          onClick={() => setActiveTab("customers")}
          className={`px-5 py-3 text-sm font-bold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "customers"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-900"
          }`}
        >
          <Users className="w-4 h-4" /> Customer Directory ({customers.length})
        </button>
        <button
          onClick={() => setActiveTab("items")}
          className={`px-5 py-3 text-sm font-bold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "items"
              ? "border-slate-900 text-slate-900"
              : "border-transparent text-slate-500 hover:text-slate-900"
          }`}
        >
          <Package className="w-4 h-4" /> Item Catalog ({items.length})
        </button>
        <button
          onClick={() => setActiveTab("credentials")}
          className={`px-5 py-3 text-sm font-bold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "credentials"
              ? "border-indigo-600 text-indigo-600 font-extrabold"
              : "border-transparent text-slate-500 hover:text-slate-900"
          }`}
        >
          <Lock className="w-4 h-4" /> e-Invoice Credentials
          {hasCredentials ? (
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
          ) : (
            <span className="w-2 h-2 rounded-full bg-amber-500" />
          )}
        </button>
      </div>

      {loading ? (
        <div className="p-12 text-center text-slate-500 font-medium">Loading master data...</div>
      ) : (
        <>
          {/* TAB 1: Company Profile Form */}
          {activeTab === "company" && (
            <form onSubmit={handleSaveProfile} className="bg-white border border-gray-200/80 rounded-2xl p-6 space-y-6 shadow-sm">
              <h2 className="text-lg font-bold text-slate-900 border-b border-gray-100 pb-3">
                Business & Bank Profile (Invoice Seller Details)
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Legal Name *</label>
                  <input
                    type="text"
                    required
                    value={companyProfile.legal_name || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, legal_name: e.target.value })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="e.g. Acme Corp Private Limited"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Trade Name</label>
                  <input
                    type="text"
                    value={companyProfile.trade_name || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, trade_name: e.target.value })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="e.g. Acme Solutions"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Seller GSTIN *</label>
                  <input
                    type="text"
                    required
                    maxLength={15}
                    value={companyProfile.gstin || ""}
                    onChange={(e) => {
                      const val = e.target.value.toUpperCase();
                      const pan = val.length >= 12 ? val.substring(2, 12) : companyProfile.pan;
                      const sc = val.length >= 2 ? val.substring(0, 2) : companyProfile.state_code;
                      setCompanyProfile({ ...companyProfile, gstin: val, pan, state_code: sc });
                    }}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="27AAAAA0000A1Z5"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">PAN Number</label>
                  <input
                    type="text"
                    maxLength={10}
                    value={companyProfile.pan || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, pan: e.target.value.toUpperCase() })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="AAAAA0000A"
                  />
                </div>
              </div>

              {/* Address */}
              <div className="space-y-4 pt-2">
                <h3 className="text-sm font-bold text-slate-900">Registered Address</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Address Line 1 *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.address_line1 || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, address_line1: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="Street name, premises"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Address Line 2</label>
                    <input
                      type="text"
                      value={companyProfile.address_line2 || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, address_line2: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="Area, landmark"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">City *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.city || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, city: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="Mumbai"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">State & State Code *</label>
                    <select
                      value={companyProfile.state_code || "27"}
                      onChange={(e) => {
                        const code = e.target.value;
                        const st = INDIAN_STATES.find((s) => s.code === code);
                        setCompanyProfile({
                          ...companyProfile,
                          state_code: code,
                          state: st ? st.name : companyProfile.state,
                        });
                      }}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white cursor-pointer font-medium"
                    >
                      {INDIAN_STATES.map((s) => (
                        <option key={s.code} value={s.code}>
                          {s.name} ({s.code})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Pincode *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.pincode || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, pincode: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white font-mono"
                      placeholder="400001"
                    />
                  </div>
                </div>
              </div>

              {/* Numbering & Bank Details */}
              <div className="space-y-4 pt-2">
                <h3 className="text-sm font-bold text-slate-900">Invoice Numbering & Bank Details</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Invoice Prefix</label>
                    <input
                      type="text"
                      value={companyProfile.invoice_number_prefix || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, invoice_number_prefix: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="e.g. INV/24-25/"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Next Sequence #</label>
                    <input
                      type="number"
                      min={1}
                      value={companyProfile.invoice_number_next_seq || 1}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, invoice_number_next_seq: parseInt(e.target.value) || 1 })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Bank Name</label>
                    <input
                      type="text"
                      value={companyProfile.bank_name || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_name: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="HDFC Bank"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Bank Account Number</label>
                    <input
                      type="text"
                      value={companyProfile.bank_account_number || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_account_number: e.target.value })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="50100000000000"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">IFSC Code</label>
                    <input
                      type="text"
                      value={companyProfile.bank_ifsc || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_ifsc: e.target.value.toUpperCase() })}
                      className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                      placeholder="HDFC0000123"
                    />
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-4 border-t border-gray-100">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center gap-2 px-6 py-2.5 bg-slate-900 hover:bg-black text-white font-semibold rounded-xl text-sm shadow-sm transition-all"
                >
                  <Save className="w-4 h-4" /> {saving ? "Saving..." : "Save Company Profile"}
                </button>
              </div>
            </form>
          )}

          {/* TAB 2: Customer Directory */}
          {activeTab === "customers" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500">
                  Manage B2B and B2C buyer profiles used in invoice creation.
                </p>
                <button
                  onClick={() => {
                    setEditingCustomer({
                      name: "",
                      gstin: "",
                      is_b2b: true,
                      address_line1: "",
                      city: "",
                      state: "Maharashtra",
                      state_code: "27",
                      pincode: "",
                    });
                    setShowCustomerModal(true);
                  }}
                  className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white rounded-xl text-xs font-semibold hover:bg-black shadow-sm transition-colors"
                >
                  <Plus className="w-4 h-4" /> Add Customer
                </button>
              </div>

              <div className="bg-white border border-gray-200/80 rounded-2xl overflow-hidden shadow-sm">
                {customers.length === 0 ? (
                  <div className="p-10 text-center text-slate-500">No customers found. Click "Add Customer" to create one.</div>
                ) : (
                  <table className="w-full text-left text-sm text-slate-800">
                    <thead className="bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-gray-200/80">
                      <tr>
                        <th className="px-4 py-3.5">Customer Name</th>
                        <th className="px-4 py-3.5">Type</th>
                        <th className="px-4 py-3.5">GSTIN</th>
                        <th className="px-4 py-3.5">Location & Pincode</th>
                        <th className="px-4 py-3.5 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {customers.map((c) => (
                        <tr key={c.id} className="hover:bg-slate-50/50">
                          <td className="px-4 py-3.5 font-bold text-slate-900">{c.name}</td>
                          <td className="px-4 py-3.5 text-xs">
                            {c.is_b2b ? (
                              <span className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-900 border border-slate-200 font-semibold">B2B</span>
                            ) : (
                              <span className="px-2.5 py-1 rounded-lg bg-slate-100 text-slate-600 border border-slate-200 font-semibold">B2C</span>
                            )}
                          </td>
                          <td className="px-4 py-3.5 font-mono text-xs text-slate-700 font-semibold">{c.gstin || "—"}</td>
                          <td className="px-4 py-3.5 text-xs text-slate-600">
                            {c.city ? `${c.city}, ` : ""}{getStateNameByCode(c.state_code, c.state)} ({c.state_code}){c.pincode ? ` - ${c.pincode}` : ""}
                          </td>
                          <td className="px-4 py-3.5 text-right space-x-2">
                            <button
                              onClick={() => {
                                setEditingCustomer(c);
                                setShowCustomerModal(true);
                              }}
                              className="p-1.5 text-slate-500 hover:text-slate-900"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDeleteCustomer(c.id)}
                              className="p-1.5 text-slate-400 hover:text-red-600"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {/* TAB 3: Item Catalog */}
          {activeTab === "items" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm text-slate-500">
                  Manage reusable goods and service items for line-item autocomplete.
                </p>
                <button
                  onClick={() => {
                    setEditingItem({
                      name: "",
                      hsn_or_sac_code: "9983",
                      unit: "NOS",
                      default_rate: 10000,
                      default_tax_rate_percent: 18.0,
                      item_type: "service",
                    });
                    setShowItemModal(true);
                  }}
                  className="flex items-center gap-1.5 px-4 py-2 bg-slate-900 text-white rounded-xl text-xs font-semibold hover:bg-black shadow-sm transition-colors"
                >
                  <Plus className="w-4 h-4" /> Add Item
                </button>
              </div>

              <div className="bg-white border border-gray-200/80 rounded-2xl overflow-hidden shadow-sm">
                {items.length === 0 ? (
                  <div className="p-10 text-center text-slate-500">No items in catalog. Click "Add Item" to add one.</div>
                ) : (
                  <table className="w-full text-left text-sm text-slate-800">
                    <thead className="bg-slate-50/80 text-xs font-semibold text-slate-500 uppercase tracking-wider border-b border-gray-200/80">
                      <tr>
                        <th className="px-4 py-3.5">Item Name</th>
                        <th className="px-4 py-3.5">Type</th>
                        <th className="px-4 py-3.5">HSN / SAC</th>
                        <th className="px-4 py-3.5">Unit</th>
                        <th className="px-4 py-3.5 text-right">Default Rate (₹)</th>
                        <th className="px-4 py-3.5 text-right">GST Rate %</th>
                        <th className="px-4 py-3.5 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {items.map((i) => (
                        <tr key={i.id} className="hover:bg-slate-50/50">
                          <td className="px-4 py-3.5 font-bold text-slate-900">{i.name}</td>
                          <td className="px-4 py-3.5 text-xs capitalize text-slate-500 font-medium">{i.item_type}</td>
                          <td className="px-4 py-3.5 font-mono text-xs font-semibold text-slate-700">{i.hsn_or_sac_code}</td>
                          <td className="px-4 py-3.5 text-xs text-slate-600 font-semibold">{i.unit}</td>
                          <td className="px-4 py-3.5 text-right font-mono font-medium">
                            ₹{(i.default_rate / 100).toFixed(2)}
                          </td>
                          <td className="px-4 py-3.5 text-right font-bold text-slate-900">
                            {i.default_tax_rate_percent}%
                          </td>
                          <td className="px-4 py-3.5 text-right space-x-2">
                            <button
                              onClick={() => {
                                setEditingItem(i);
                                setShowItemModal(true);
                              }}
                              className="p-1.5 text-slate-500 hover:text-slate-900"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDeleteItem(i.id)}
                              className="p-1.5 text-slate-400 hover:text-red-600"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {/* TAB 4: e-Invoice Credentials */}
          {activeTab === "credentials" && (
            <form onSubmit={handleSaveCredentials} className="bg-white border border-gray-200/80 rounded-2xl p-6 space-y-6 shadow-sm max-w-3xl">
              <div className="flex items-start justify-between border-b border-gray-100 pb-4">
                <div>
                  <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                    <Lock className="w-5 h-5 text-indigo-600" /> e-Invoice Portal Credentials
                  </h2>
                  <p className="text-xs text-slate-500 mt-1">
                    Configure government e-Invoice API portal credentials for Sandbox & IRP direct submission.
                  </p>
                </div>
                <div>
                  {hasCredentials ? (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      <Check className="w-3.5 h-3.5 text-emerald-500" /> Credentials Configured
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                      <AlertCircle className="w-3.5 h-3.5 text-amber-500" /> Missing Credentials
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                    e-Invoice Portal Username / API Client ID *
                  </label>
                  <input
                    type="text"
                    required
                    value={credUsername}
                    onChange={(e) => setCredUsername(e.target.value)}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="e.g. GSTIN_API_USER123"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                    e-Invoice Portal Password / Secret *
                  </label>
                  <input
                    type="password"
                    required
                    value={credPassword}
                    onChange={(e) => setCredPassword(e.target.value)}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="Enter API portal password"
                  />
                </div>

                {credLastUpdated && (
                  <p className="text-xs text-slate-400 font-mono">
                    Last updated: {new Date(credLastUpdated).toLocaleString()}
                  </p>
                )}
              </div>

              <div className="flex justify-end pt-4 border-t border-gray-100">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-semibold rounded-xl text-sm shadow-sm transition-all"
                >
                  <Save className="w-4 h-4" /> {saving ? "Saving Credentials..." : "Save Portal Credentials"}
                </button>
              </div>
            </form>
          )}
        </>
      )}

      {/* Modal: Customer Add/Edit */}
      {showCustomerModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <h3 className="text-lg font-bold text-slate-900">
                {editingCustomer.id ? "Edit Customer" : "Add New Customer"}
              </h3>
              <button onClick={() => setShowCustomerModal(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveCustomer} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Customer Name *</label>
                <input
                  type="text"
                  required
                  value={editingCustomer.name || ""}
                  onChange={(e) => setEditingCustomer({ ...editingCustomer, name: e.target.value })}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                />
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editingCustomer.is_b2b ?? true}
                    onChange={(e) => setEditingCustomer({ ...editingCustomer, is_b2b: e.target.checked })}
                    className="accent-slate-900 rounded"
                  />
                  Is B2B Customer (Requires GSTIN)
                </label>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">
                  Customer GSTIN {editingCustomer.is_b2b ? "*" : "(Optional for B2C)"}
                </label>
                <input
                  type="text"
                  maxLength={15}
                  required={editingCustomer.is_b2b}
                  value={editingCustomer.gstin || ""}
                  onChange={(e) => {
                    const val = e.target.value.toUpperCase();
                    const sc = val.length >= 2 ? val.substring(0, 2) : editingCustomer.state_code;
                    const stName = getStateNameByCode(sc, editingCustomer.state || "");
                    setEditingCustomer({ ...editingCustomer, gstin: val, state_code: sc, state: stName });
                  }}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                  placeholder="e.g. 27AAACB1001R1Z1"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Address Line 1 *</label>
                <input
                  type="text"
                  required
                  value={editingCustomer.address_line1 || ""}
                  onChange={(e) => setEditingCustomer({ ...editingCustomer, address_line1: e.target.value })}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                  placeholder="Building name, street address"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Address Line 2 (Optional)</label>
                <input
                  type="text"
                  value={editingCustomer.address_line2 || ""}
                  onChange={(e) => setEditingCustomer({ ...editingCustomer, address_line2: e.target.value })}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                  placeholder="Landmark, suite, floor"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">City *</label>
                  <input
                    type="text"
                    required
                    value={editingCustomer.city || ""}
                    onChange={(e) => setEditingCustomer({ ...editingCustomer, city: e.target.value })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="e.g. Mumbai"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Pincode *</label>
                  <input
                    type="text"
                    required
                    maxLength={6}
                    value={editingCustomer.pincode || ""}
                    onChange={(e) => setEditingCustomer({ ...editingCustomer, pincode: e.target.value.replace(/\D/g, "") })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                    placeholder="e.g. 400001"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">State & State Code *</label>
                <select
                  value={editingCustomer.state_code || "27"}
                  onChange={(e) => {
                    const code = e.target.value;
                    const st = INDIAN_STATES.find((s) => s.code === code);
                    setEditingCustomer({
                      ...editingCustomer,
                      state_code: code,
                      state: st ? st.name : editingCustomer.state,
                    });
                  }}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white cursor-pointer font-medium"
                >
                  {INDIAN_STATES.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name} ({s.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setShowCustomerModal(false)}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-slate-900 hover:bg-black text-white text-xs font-semibold rounded-xl shadow-sm"
                >
                  {saving ? "Saving..." : "Save Customer"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Item Add/Edit */}
      {showItemModal && (
        <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white border border-gray-200 rounded-2xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <h3 className="text-lg font-bold text-slate-900">
                {editingItem.id ? "Edit Catalog Item" : "Add New Catalog Item"}
              </h3>
              <button onClick={() => setShowItemModal(false)} className="text-slate-400 hover:text-slate-700">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveItem} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Item Name *</label>
                <input
                  type="text"
                  required
                  value={editingItem.name || ""}
                  onChange={(e) => setEditingItem({ ...editingItem, name: e.target.value })}
                  className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider">HSN or SAC Code *</label>
                    {hsnLoading && (
                      <span className="text-[11px] font-medium text-blue-600 flex items-center gap-1">
                        <Sparkles className="w-3 h-3 animate-pulse" /> Finding suggestions...
                      </span>
                    )}
                  </div>
                  <input
                    type="text"
                    required
                    value={editingItem.hsn_or_sac_code || ""}
                    onChange={(e) => setEditingItem({ ...editingItem, hsn_or_sac_code: e.target.value })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                  />

                  {/* Inline type mismatch warning */}
                  {typeMismatchWarning && (
                    <div className="mt-2 p-2.5 bg-amber-50 border border-amber-200 rounded-xl flex items-start gap-2 text-xs text-amber-900 font-medium">
                      <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                      <span>{typeMismatchWarning}</span>
                    </div>
                  )}

                  {/* Auto-suggest dropdown */}
                  {showHsnDropdown && hsnSuggestions.length > 0 && (
                    <div className="mt-2 bg-slate-50 border border-gray-200 rounded-xl p-3 space-y-2 shadow-md">
                      <div className="flex items-center justify-between text-[11px] font-bold text-slate-600 uppercase tracking-wider px-1">
                        <span className="flex items-center gap-1.5 text-blue-600">
                          <Sparkles className="w-3.5 h-3.5" /> Suggested HSN/SAC Codes
                        </span>
                        <button
                          type="button"
                          onClick={() => setShowHsnDropdown(false)}
                          className="text-slate-400 hover:text-slate-700"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                        {hsnSuggestions.map((sug) => (
                          <button
                            key={sug.code}
                            type="button"
                            onClick={() => {
                              setEditingItem({
                                ...editingItem,
                                hsn_or_sac_code: sug.code,
                                item_type: sug.item_type,
                              });
                              setShowHsnDropdown(false);
                            }}
                            className="w-full text-left p-2.5 bg-white hover:bg-blue-50/60 border border-gray-200/80 rounded-lg transition-colors group flex items-start justify-between gap-3 shadow-xs"
                          >
                            <div className="space-y-0.5">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-xs text-slate-900 group-hover:text-blue-600">
                                  {sug.code}
                                </span>
                                <span
                                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase ${
                                    sug.item_type === "goods"
                                      ? "bg-emerald-100 text-emerald-800"
                                      : "bg-blue-100 text-blue-800"
                                  }`}
                                >
                                  {sug.item_type}
                                </span>
                              </div>
                              <p className="text-xs text-slate-600 font-medium line-clamp-2">{sug.description}</p>
                            </div>
                            <span className="text-xs font-semibold text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 pt-0.5">
                              Select →
                            </span>
                          </button>
                        ))}
                      </div>

                      <p className="text-[11px] text-slate-500 italic px-1 pt-1 border-t border-gray-200">
                        Suggested — please verify against your actual product/service classification.
                      </p>
                    </div>
                  )}
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">GST Unit Code (UQC) *</label>
                  <select
                    value={editingItem.unit || "NOS"}
                    onChange={(e) => setEditingItem({ ...editingItem, unit: e.target.value })}
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white cursor-pointer font-semibold"
                  >
                    {GST_UQC_CODES.map((uqc) => (
                      <option key={uqc.code} value={uqc.code}>
                        {uqc.code} - {uqc.description}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Default Rate (₹) *</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    required
                    value={(editingItem.default_rate || 0) / 100}
                    onChange={(e) =>
                      setEditingItem({
                        ...editingItem,
                        default_rate: Math.round((parseFloat(e.target.value) || 0) * 100),
                      })
                    }
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 font-mono focus:outline-none focus:border-slate-900 focus:bg-white"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">GST Tax Rate % *</label>
                  <select
                    value={editingItem.default_tax_rate_percent || 18}
                    onChange={(e) =>
                      setEditingItem({ ...editingItem, default_tax_rate_percent: parseFloat(e.target.value) })
                    }
                    className="w-full bg-slate-50 border border-gray-200 rounded-xl px-3.5 py-2 text-sm text-slate-900 focus:outline-none focus:border-slate-900 focus:bg-white cursor-pointer font-semibold"
                  >
                    <option value={0}>0% (Exempt)</option>
                    <option value={5}>5%</option>
                    <option value={12}>12%</option>
                    <option value={18}>18%</option>
                    <option value={28}>28%</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1">Item Type</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer">
                    <input
                      type="radio"
                      name="item_type"
                      checked={editingItem.item_type === "service"}
                      onChange={() => setEditingItem({ ...editingItem, item_type: "service" })}
                      className="accent-slate-900"
                    />
                    Service
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold text-slate-700 cursor-pointer">
                    <input
                      type="radio"
                      name="item_type"
                      checked={editingItem.item_type === "goods"}
                      onChange={() => setEditingItem({ ...editingItem, item_type: "goods" })}
                      className="accent-slate-900"
                    />
                    Goods
                  </label>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => setShowItemModal(false)}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-slate-900 hover:bg-black text-white text-xs font-semibold rounded-xl shadow-sm"
                >
                  {saving ? "Saving..." : "Save Item"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

export default function MasterDataSettingsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center p-8 text-sm text-slate-500 font-medium">
          Loading master data settings...
        </div>
      }
    >
      <MasterDataSettingsContent />
    </Suspense>
  );
}
