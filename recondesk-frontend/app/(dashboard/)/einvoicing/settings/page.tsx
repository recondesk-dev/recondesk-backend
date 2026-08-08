"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Building,
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
} from "lucide-react";
import { useAccessToken } from "@/lib/hooks/useAccessToken";
import {
  clientsApi,
  ClientGstin,
  billingModuleApi,
  BillingCompanyProfile,
  BillingCustomer,
  BillingItem,
} from "@/lib/api";

const INDIAN_STATES = [
  { code: "27", name: "Maharashtra" },
  { code: "07", name: "Delhi" },
  { code: "29", name: "Karnataka" },
  { code: "33", name: "Tamil Nadu" },
  { code: "09", name: "Uttar Pradesh" },
  { code: "19", name: "West Bengal" },
  { code: "24", name: "Gujarat" },
  { code: "06", name: "Haryana" },
  { code: "36", name: "Telangana" },
  { code: "32", name: "Kerala" },
  { code: "08", name: "Rajasthan" },
  { code: "23", name: "Madhya Pradesh" },
  { code: "10", name: "Bihar" },
  { code: "37", name: "Andhra Pradesh" },
  { code: "21", name: "Odisha" },
  { code: "03", name: "Punjab" },
  { code: "22", name: "Chhattisgarh" },
  { code: "20", name: "Jharkhand" },
  { code: "05", name: "Uttarakhand" },
  { code: "02", name: "Himachal Pradesh" },
  { code: "01", name: "Jammu and Kashmir" },
  { code: "30", name: "Goa" },
  { code: "18", name: "Assam" },
  { code: "99", name: "Other Territory / Overseas" },
];

export default function MasterDataSettingsPage() {
  const searchParams = useSearchParams();
  const token = useAccessToken();

  const [clients, setClients] = useState<ClientGstin[]>([]);
  const [clientGstinId, setClientGstinId] = useState<string>(
    searchParams.get("client_gstin_id") || ""
  );
  const [activeTab, setActiveTab] = useState<"company" | "customers" | "items">("company");

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
    default_rate: 10000, // ₹100 in paise
    default_tax_rate_percent: 18.0,
    item_type: "service",
  });

  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

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
          // Pre-populate GSTIN from selected client if available
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

  // Handle Save Company Profile
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
      setMessage({ type: "error", text: err.detail || "Failed to save company profile" });
    } finally {
      setSaving(false);
    }
  };

  // Handle Save Customer
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
      setMessage({ type: "error", text: err.detail || "Failed to save customer" });
    } finally {
      setSaving(false);
    }
  };

  // Handle Delete Customer
  const handleDeleteCustomer = async (id: string) => {
    if (!token || !clientGstinId || !confirm("Are you sure you want to delete this customer?")) return;
    try {
      await billingModuleApi.deleteCustomer(token, id, clientGstinId);
      setCustomers((prev) => prev.filter((c) => c.id !== id));
    } catch (err: any) {
      alert(err.detail || "Failed to delete customer");
    }
  };

  // Handle Save Item
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
      setMessage({ type: "error", text: err.detail || "Failed to save item" });
    } finally {
      setSaving(false);
    }
  };

  // Handle Delete Item
  const handleDeleteItem = async (id: string) => {
    if (!token || !clientGstinId || !confirm("Are you sure you want to delete this item?")) return;
    try {
      await billingModuleApi.deleteItem(token, id, clientGstinId);
      setItems((prev) => prev.filter((i) => i.id !== id));
    } catch (err: any) {
      alert(err.detail || "Failed to delete item");
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <Link
            href={`/einvoicing?client_gstin_id=${clientGstinId}`}
            className="inline-flex items-center gap-1.5 text-xs text-indigo-400 hover:text-indigo-300 font-medium mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Invoices
          </Link>
          <h1 className="text-2xl font-bold text-white">E-Invoicing Master Data</h1>
          <p className="text-sm text-gray-400">
            Manage company profile, customer registry, and item catalog.
          </p>
        </div>

        {/* Client Selector */}
        <div className="flex items-center gap-2 bg-[#161B26] border border-white/10 rounded-lg px-3 py-2">
          <Building className="w-4 h-4 text-gray-400" />
          <span className="text-xs text-gray-400">Client:</span>
          <select
            value={clientGstinId}
            onChange={(e) => setClientGstinId(e.target.value)}
            className="bg-transparent text-white text-sm focus:outline-none cursor-pointer"
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id} className="bg-[#161B26] text-white">
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
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
              : "bg-red-500/10 border-red-500/30 text-red-300"
          }`}
        >
          {message.type === "success" ? (
            <Check className="w-5 h-5 text-emerald-400" />
          ) : (
            <AlertCircle className="w-5 h-5 text-red-400" />
          )}
          {message.text}
        </div>
      )}

      {/* Tabs Header */}
      <div className="flex border-b border-white/10">
        <button
          onClick={() => setActiveTab("company")}
          className={`px-5 py-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "company"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-gray-400 hover:text-gray-200"
          }`}
        >
          <Building className="w-4 h-4" /> Company Profile
        </button>
        <button
          onClick={() => setActiveTab("customers")}
          className={`px-5 py-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "customers"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-gray-400 hover:text-gray-200"
          }`}
        >
          <Users className="w-4 h-4" /> Customer Directory ({customers.length})
        </button>
        <button
          onClick={() => setActiveTab("items")}
          className={`px-5 py-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            activeTab === "items"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-gray-400 hover:text-gray-200"
          }`}
        >
          <Package className="w-4 h-4" /> Item Catalog ({items.length})
        </button>
      </div>

      {loading ? (
        <div className="p-12 text-center text-gray-400">Loading master data...</div>
      ) : (
        <>
          {/* TAB 1: Company Profile Form */}
          {activeTab === "company" && (
            <form onSubmit={handleSaveProfile} className="bg-[#161B26] border border-white/10 rounded-xl p-6 space-y-6">
              <h2 className="text-lg font-semibold text-white border-b border-white/10 pb-3">
                Business & Bank Profile (Invoice Seller Info)
              </h2>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-gray-400 font-medium mb-1">Legal Name *</label>
                  <input
                    type="text"
                    required
                    value={companyProfile.legal_name || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, legal_name: e.target.value })}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    placeholder="e.g. Acme Corp Private Limited"
                  />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 font-medium mb-1">Trade Name</label>
                  <input
                    type="text"
                    value={companyProfile.trade_name || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, trade_name: e.target.value })}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    placeholder="e.g. Acme Solutions"
                  />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 font-medium mb-1">Seller GSTIN *</label>
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
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                    placeholder="27AAAAA0000A1Z5"
                  />
                </div>

                <div>
                  <label className="block text-xs text-gray-400 font-medium mb-1">PAN Number</label>
                  <input
                    type="text"
                    maxLength={10}
                    value={companyProfile.pan || ""}
                    onChange={(e) => setCompanyProfile({ ...companyProfile, pan: e.target.value.toUpperCase() })}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                    placeholder="AAAAA0000A"
                  />
                </div>
              </div>

              {/* Address */}
              <div className="space-y-4 pt-2">
                <h3 className="text-sm font-semibold text-gray-300">Registered Address</h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Address Line 1 *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.address_line1 || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, address_line1: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                      placeholder="Street name, premises"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Address Line 2</label>
                    <input
                      type="text"
                      value={companyProfile.address_line2 || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, address_line2: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                      placeholder="Area, landmark"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">City *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.city || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, city: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                      placeholder="Mumbai"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">State & State Code *</label>
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
                      className="w-full bg-[#161B26] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                    >
                      {INDIAN_STATES.map((s) => (
                        <option key={s.code} value={s.code}>
                          {s.name} ({s.code})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Pincode *</label>
                    <input
                      type="text"
                      required
                      value={companyProfile.pincode || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, pincode: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                      placeholder="400001"
                    />
                  </div>
                </div>
              </div>

              {/* Invoice Numbering Config & Bank Details */}
              <div className="space-y-4 pt-2">
                <h3 className="text-sm font-semibold text-gray-300">Invoice Numbering & Bank Details</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Invoice Prefix</label>
                    <input
                      type="text"
                      value={companyProfile.invoice_number_prefix || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, invoice_number_prefix: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                      placeholder="e.g. INV/24-25/"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Next Sequence #</label>
                    <input
                      type="number"
                      min={1}
                      value={companyProfile.invoice_number_next_seq || 1}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, invoice_number_next_seq: parseInt(e.target.value) || 1 })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Bank Name</label>
                    <input
                      type="text"
                      value={companyProfile.bank_name || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_name: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                      placeholder="HDFC Bank"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">Bank Account Number</label>
                    <input
                      type="text"
                      value={companyProfile.bank_account_number || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_account_number: e.target.value })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                      placeholder="50100000000000"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-400 font-medium mb-1">IFSC Code</label>
                    <input
                      type="text"
                      value={companyProfile.bank_ifsc || ""}
                      onChange={(e) => setCompanyProfile({ ...companyProfile, bank_ifsc: e.target.value.toUpperCase() })}
                      className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                      placeholder="HDFC0000123"
                    />
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-4 border-t border-white/10">
                <button
                  type="submit"
                  disabled={saving}
                  className="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-lg text-sm transition-colors"
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
                <p className="text-sm text-gray-400">
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
                  className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-semibold hover:bg-indigo-500 transition-colors"
                >
                  <Plus className="w-4 h-4" /> Add Customer
                </button>
              </div>

              <div className="bg-[#161B26] border border-white/10 rounded-xl overflow-hidden">
                {customers.length === 0 ? (
                  <div className="p-8 text-center text-gray-400">No customers found. Click "Add Customer" to create one.</div>
                ) : (
                  <table className="w-full text-left text-sm text-gray-300">
                    <thead className="bg-white/5 text-xs text-gray-400 uppercase tracking-wider border-b border-white/10">
                      <tr>
                        <th className="px-4 py-3">Customer Name</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">GSTIN</th>
                        <th className="px-4 py-3">State & Code</th>
                        <th className="px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {customers.map((c) => (
                        <tr key={c.id} className="hover:bg-white/[0.02]">
                          <td className="px-4 py-3 font-semibold text-white">{c.name}</td>
                          <td className="px-4 py-3 text-xs">
                            {c.is_b2b ? (
                              <span className="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20 font-medium">B2B</span>
                            ) : (
                              <span className="px-2 py-0.5 rounded bg-gray-500/10 text-gray-400 border border-gray-500/20 font-medium">B2C</span>
                            )}
                          </td>
                          <td className="px-4 py-3 font-mono text-xs">{c.gstin || "—"}</td>
                          <td className="px-4 py-3 text-xs">{c.state} ({c.state_code})</td>
                          <td className="px-4 py-3 text-right space-x-2">
                            <button
                              onClick={() => {
                                setEditingCustomer(c);
                                setShowCustomerModal(true);
                              }}
                              className="p-1 text-gray-400 hover:text-indigo-400"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDeleteCustomer(c.id)}
                              className="p-1 text-gray-400 hover:text-red-400"
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
                <p className="text-sm text-gray-400">
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
                  className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-semibold hover:bg-indigo-500 transition-colors"
                >
                  <Plus className="w-4 h-4" /> Add Item
                </button>
              </div>

              <div className="bg-[#161B26] border border-white/10 rounded-xl overflow-hidden">
                {items.length === 0 ? (
                  <div className="p-8 text-center text-gray-400">No items in catalog. Click "Add Item" to add one.</div>
                ) : (
                  <table className="w-full text-left text-sm text-gray-300">
                    <thead className="bg-white/5 text-xs text-gray-400 uppercase tracking-wider border-b border-white/10">
                      <tr>
                        <th className="px-4 py-3">Item Name</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">HSN / SAC</th>
                        <th className="px-4 py-3">Unit</th>
                        <th className="px-4 py-3 text-right">Default Rate (₹)</th>
                        <th className="px-4 py-3 text-right">GST Rate %</th>
                        <th className="px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {items.map((i) => (
                        <tr key={i.id} className="hover:bg-white/[0.02]">
                          <td className="px-4 py-3 font-semibold text-white">{i.name}</td>
                          <td className="px-4 py-3 text-xs capitalize text-gray-400">{i.item_type}</td>
                          <td className="px-4 py-3 font-mono text-xs">{i.hsn_or_sac_code}</td>
                          <td className="px-4 py-3 text-xs">{i.unit}</td>
                          <td className="px-4 py-3 text-right font-mono">
                            ₹{(i.default_rate / 100).toFixed(2)}
                          </td>
                          <td className="px-4 py-3 text-right font-semibold text-indigo-400">
                            {i.default_tax_rate_percent}%
                          </td>
                          <td className="px-4 py-3 text-right space-x-2">
                            <button
                              onClick={() => {
                                setEditingItem(i);
                                setShowItemModal(true);
                              }}
                              className="p-1 text-gray-400 hover:text-indigo-400"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => handleDeleteItem(i.id)}
                              className="p-1 text-gray-400 hover:text-red-400"
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
        </>
      )}

      {/* Modal: Customer Add/Edit */}
      {showCustomerModal && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#161B26] border border-white/10 rounded-xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-lg font-semibold text-white">
                {editingCustomer.id ? "Edit Customer" : "Add New Customer"}
              </h3>
              <button onClick={() => setShowCustomerModal(false)} className="text-gray-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveCustomer} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Customer Name *</label>
                <input
                  type="text"
                  required
                  value={editingCustomer.name || ""}
                  onChange={(e) => setEditingCustomer({ ...editingCustomer, name: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editingCustomer.is_b2b ?? true}
                    onChange={(e) => setEditingCustomer({ ...editingCustomer, is_b2b: e.target.checked })}
                    className="accent-indigo-600 rounded"
                  />
                  Is B2B Customer (Requires GSTIN)
                </label>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">
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
                    setEditingCustomer({ ...editingCustomer, gstin: val, state_code: sc });
                  }}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">State & State Code *</label>
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
                  className="w-full bg-[#161B26] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                >
                  {INDIAN_STATES.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name} ({s.code})
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowCustomerModal(false)}
                  className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-semibold rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
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
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#161B26] border border-white/10 rounded-xl w-full max-w-lg p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <h3 className="text-lg font-semibold text-white">
                {editingItem.id ? "Edit Catalog Item" : "Add New Catalog Item"}
              </h3>
              <button onClick={() => setShowItemModal(false)} className="text-gray-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSaveItem} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">Item Name *</label>
                <input
                  type="text"
                  required
                  value={editingItem.name || ""}
                  onChange={(e) => setEditingItem({ ...editingItem, name: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">HSN or SAC Code *</label>
                  <input
                    type="text"
                    required
                    value={editingItem.hsn_or_sac_code || ""}
                    onChange={(e) => setEditingItem({ ...editingItem, hsn_or_sac_code: e.target.value })}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Unit (e.g. NOS, KG, HRS) *</label>
                  <input
                    type="text"
                    required
                    value={editingItem.unit || "NOS"}
                    onChange={(e) => setEditingItem({ ...editingItem, unit: e.target.value.toUpperCase() })}
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Default Rate (₹) *</label>
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
                    className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">GST Tax Rate % *</label>
                  <select
                    value={editingItem.default_tax_rate_percent || 18}
                    onChange={(e) =>
                      setEditingItem({ ...editingItem, default_tax_rate_percent: parseFloat(e.target.value) })
                    }
                    className="w-full bg-[#161B26] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500"
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
                <label className="block text-xs text-gray-400 mb-1">Item Type</label>
                <div className="flex gap-4">
                  <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                    <input
                      type="radio"
                      name="item_type"
                      checked={editingItem.item_type === "service"}
                      onChange={() => setEditingItem({ ...editingItem, item_type: "service" })}
                      className="accent-indigo-600"
                    />
                    Service
                  </label>
                  <label className="flex items-center gap-2 text-xs text-gray-300 cursor-pointer">
                    <input
                      type="radio"
                      name="item_type"
                      checked={editingItem.item_type === "goods"}
                      onChange={() => setEditingItem({ ...editingItem, item_type: "goods" })}
                      className="accent-indigo-600"
                    />
                    Goods
                  </label>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                <button
                  type="button"
                  onClick={() => setShowItemModal(false)}
                  className="px-4 py-2 bg-white/5 hover:bg-white/10 text-gray-300 text-xs font-semibold rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-lg"
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
